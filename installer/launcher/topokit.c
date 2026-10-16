/*
 * TopoKit.exe - lansatorul TopoKit (iconita din bara de sistem, langa ceas).
 *
 * Ruleaza in fundal si tine legatura cu AutoCAD prin COM (AutoCAD.Application):
 *   - detecteaza AutoCAD (orice versiune 2013 - 2026) si afiseaza starea
 *     conexiunii in iconita (verde = conectat, gri = AutoCAD nepornit);
 *   - din meniul iconitei porneste comenzile TopoKit in desenul activ
 *     (TOPOKIT, ANEXE, TOPOTEREN, ...); daca AutoCAD nu ruleaza, il porneste
 *     si trimite comanda dupa ce s-a incarcat;
 *   - se asigura ca TopoKit este incarcat in desen (TopoKitLoad.lsp);
 *   - optional porneste odata cu Windows (HKCU\...\Run, parametrul /background).
 *
 * Linie de comanda:
 *   TopoKit.exe               deschide meniul TOPOKIT in AutoCAD (il porneste daca e nevoie)
 *   TopoKit.exe /background   doar ruleaza in fundal (pornire cu Windows)
 *   TopoKit.exe /cmd ANEXE    trimite o comanda TopoKit in AutoCAD
 *   TopoKit.exe /quit         inchide lansatorul care ruleaza deja
 *
 * Compilare (MinGW-w64): vezi tools/build_installer.sh
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <ole2.h>
#include <oleauto.h>
#include <shlobj.h>
#include <stdarg.h>
#include <stdio.h>
#include <wchar.h>
#include "resource.h"

#define APP_TITLE   L"TopoKit"
#define WND_CLASS   L"TopoKitLauncherWnd"
#define MUTEX_NAME  L"Local\\TopoKitLauncher"
#define REG_APP     L"Software\\TopoKit"
#define REG_RUN     L"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
#define WM_TRAY     (WM_APP + 1)
#define TIMER_POLL  1
#define POLL_MS     3000
#define START_WAIT_MS (240 * 1000)

enum { ID_STATUS = 1000, ID_CMD0 = 1001, ID_START = 1100, ID_RELOAD, ID_AUTORUN,
       ID_FOLDER, ID_HELP, ID_EXIT, HOTKEY_ID = 1 };

static const struct { const wchar_t *label, *cmd; } CMDS[] = {
    { L"Meniu TopoKit\tCtrl+Alt+Shift+T", L"TOPOKIT" },
    { L"Generator anexe (Ordin ANCPI 600/2023)", L"ANEXE" },
    { L"Teren: puncte, TIN, curbe de nivel, volume", L"TOPOTEREN" },
    { L"Verificare documentație", L"VERIFICARE" },
    { L"Planșe PDF", L"PLANEPDF" },
    { L"Export KMZ (Google Earth)", L"EXPKMZ" },
    { L"Inserare cadru planșă", L"INSCADRU" },
    { L"Adăugare vertexuri (ADDVTX)", L"ADDVTX" },
};
#define NCMDS ((int)(sizeof(CMDS) / sizeof(CMDS[0])))

/* ProgID-uri incercate pentru conectare: intai cel generic (ultima versiune
 * instalata), apoi cele pe versiuni (R19 = 2013 ... R26). */
#define MAXCLSID 24
static CLSID g_clsid[MAXCLSID];
static int g_nclsid;

static HINSTANCE g_inst;
static HWND g_hwnd;
static UINT g_msgTaskbar;
static NOTIFYICONDATAW g_nid;
static HICON g_icoOn, g_icoOff;
static BOOL g_connected = -1;           /* -1 = necunoscut (primul sondaj) */
static wchar_t g_acadName[64] = L"";    /* "AutoCAD 2024" */
static wchar_t g_docName[MAX_PATH] = L"";
static wchar_t g_pending[64] = L"";     /* comanda de trimis dupa pornirea AutoCAD */
static DWORD g_pendingSince;
static int g_readyPolls;
#define POLL_RETRY_MS 400
static DWORD g_retryMs = POLL_RETRY_MS;  /* cat asteptam cand AutoCAD este ocupat */
static wchar_t g_contents[MAX_PATH];    /* folderul cu TopoKit.lsp */
static wchar_t g_logPath[MAX_PATH];

/* ------------------------------------------------------------------ jurnal */
static void Log(const wchar_t *fmt, ...)
{
    FILE *f;
    SYSTEMTIME st;
    va_list ap;
    if (!g_logPath[0]) return;
    f = _wfopen(g_logPath, L"a, ccs=UTF-8");
    if (!f) return;
    GetLocalTime(&st);
    fwprintf(f, L"%04d-%02d-%02d %02d:%02d:%02d  ", st.wYear, st.wMonth, st.wDay,
             st.wHour, st.wMinute, st.wSecond);
    va_start(ap, fmt);
    vfwprintf(f, fmt, ap);
    va_end(ap);
    fputwc(L'\n', f);
    fclose(f);
}

static void InitLog(void)
{
    wchar_t dir[MAX_PATH];
    WIN32_FILE_ATTRIBUTE_DATA fa;
    if (FAILED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA | CSIDL_FLAG_CREATE, NULL, 0, dir))) return;
    wcscat(dir, L"\\TopoKit");
    CreateDirectoryW(dir, NULL);
    swprintf(g_logPath, MAX_PATH, L"%ls\\TopoKit.log", dir);
    if (GetFileAttributesExW(g_logPath, GetFileExInfoStandard, &fa) && fa.nFileSizeLow > 256 * 1024)
        DeleteFileW(g_logPath);
}

/* ------------------------------------------------------------------ registru */
static BOOL RegGetStr(HKEY root, const wchar_t *key, const wchar_t *name, wchar_t *out, DWORD cch)
{
    HKEY h;
    DWORD type, cb = cch * sizeof(wchar_t);
    BOOL ok = FALSE;
    out[0] = 0;
    if (RegOpenKeyExW(root, key, 0, KEY_READ | KEY_WOW64_64KEY, &h) != ERROR_SUCCESS) return FALSE;
    if (RegQueryValueExW(h, name, NULL, &type, (BYTE *)out, &cb) == ERROR_SUCCESS &&
        (type == REG_SZ || type == REG_EXPAND_SZ)) {
        out[cch - 1] = 0;
        ok = TRUE;
    }
    RegCloseKey(h);
    return ok && out[0];
}

static BOOL AutorunEnabled(void)
{
    wchar_t v[2 * MAX_PATH];
    return RegGetStr(HKEY_CURRENT_USER, REG_RUN, APP_TITLE, v, 2 * MAX_PATH);
}

static void SetAutorun(BOOL on)
{
    HKEY h;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, REG_RUN, 0, NULL, 0, KEY_SET_VALUE, NULL, &h, NULL) != ERROR_SUCCESS)
        return;
    if (on) {
        wchar_t exe[MAX_PATH], v[2 * MAX_PATH];
        GetModuleFileNameW(NULL, exe, MAX_PATH);
        swprintf(v, 2 * MAX_PATH, L"\"%ls\" /background", exe);
        RegSetValueExW(h, APP_TITLE, 0, REG_SZ, (const BYTE *)v, (DWORD)((wcslen(v) + 1) * sizeof(wchar_t)));
    } else {
        RegDeleteValueW(h, APP_TITLE);
    }
    RegCloseKey(h);
}

/* Folderul cu fisierele LISP: valoarea scrisa de instalator, altfel pachetul
 * ApplicationPlugins standard, altfel folderul programului. */
static void FindContents(void)
{
    wchar_t p[MAX_PATH], f[MAX_PATH];
    if (RegGetStr(HKEY_CURRENT_USER, REG_APP, L"ContentsDir", p, MAX_PATH)) {
        swprintf(f, MAX_PATH, L"%ls\\TopoKitLoad.lsp", p);
        if (GetFileAttributesW(f) != INVALID_FILE_ATTRIBUTES) { wcscpy(g_contents, p); return; }
    }
    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_APPDATA, NULL, 0, p))) {
        swprintf(f, MAX_PATH, L"%ls\\Autodesk\\ApplicationPlugins\\TopoKit.bundle\\Contents", p);
        swprintf(p, MAX_PATH, L"%ls\\TopoKitLoad.lsp", f);
        if (GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES) { wcscpy(g_contents, f); return; }
    }
    GetModuleFileNameW(NULL, p, MAX_PATH);
    *wcsrchr(p, L'\\') = 0;
    wcscpy(g_contents, p);
}

/* ------------------------------------------------------------------ COM */
static HRESULT STDMETHODCALLTYPE MF_QueryInterface(IMessageFilter *t, REFIID riid, void **ppv)
{
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IMessageFilter)) {
        *ppv = t;
        return S_OK;
    }
    *ppv = NULL;
    return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE MF_AddRef(IMessageFilter *t) { (void)t; return 2; }
static ULONG STDMETHODCALLTYPE MF_Release(IMessageFilter *t) { (void)t; return 1; }
static DWORD STDMETHODCALLTYPE MF_HandleInComingCall(IMessageFilter *t, DWORD type, HTASK task, DWORD tick,
                                                     LPINTERFACEINFO info)
{
    (void)t; (void)type; (void)task; (void)tick; (void)info;
    return SERVERCALL_ISHANDLED;
}
/* AutoCAD respinge apelurile cat timp executa o comanda: reincercam un timp. */
static DWORD STDMETHODCALLTYPE MF_RetryRejectedCall(IMessageFilter *t, HTASK task, DWORD elapsed, DWORD reject)
{
    (void)t; (void)task;
    if (reject == SERVERCALL_RETRYLATER && elapsed < g_retryMs) return 150;
    return (DWORD)-1;
}
static DWORD STDMETHODCALLTYPE MF_MessagePending(IMessageFilter *t, HTASK task, DWORD tick, DWORD type)
{
    (void)t; (void)task; (void)tick; (void)type;
    return PENDINGMSG_WAITDEFPROCESS;
}
static IMessageFilterVtbl g_mfVtbl = { MF_QueryInterface, MF_AddRef, MF_Release, MF_HandleInComingCall,
                                       MF_RetryRejectedCall, MF_MessagePending };
static IMessageFilter g_mf = { &g_mfVtbl };

static void InitClsids(void)
{
    wchar_t pid[64];
    int major;
    CLSID c;
    g_nclsid = 0;
    if (SUCCEEDED(CLSIDFromProgID(L"AutoCAD.Application", &c))) g_clsid[g_nclsid++] = c;
    for (major = 26; major >= 19 && g_nclsid < MAXCLSID; major--) {
        int i, dup = 0;
        swprintf(pid, 64, L"AutoCAD.Application.%d", major);
        if (FAILED(CLSIDFromProgID(pid, &c))) continue;
        for (i = 0; i < g_nclsid; i++) dup |= IsEqualCLSID(&c, &g_clsid[i]);
        if (!dup) g_clsid[g_nclsid++] = c;
    }
    Log(L"Versiuni AutoCAD inregistrate COM: %d", g_nclsid);
}

static HRESULT Call(IDispatch *d, WORD flags, const wchar_t *name, VARIANT *res, int argc, VARIANT *argv)
{
    DISPID id, put = DISPID_PROPERTYPUT;
    LPOLESTR n = (LPOLESTR)name;
    DISPPARAMS dp = { argv, NULL, (UINT)argc, 0 };
    HRESULT hr;
    if (res) VariantInit(res);
    if (!d) return E_POINTER;
    hr = IDispatch_GetIDsOfNames(d, &IID_NULL, &n, 1, LOCALE_USER_DEFAULT, &id);
    if (FAILED(hr)) return hr;
    if (flags & DISPATCH_PROPERTYPUT) { dp.rgdispidNamedArgs = &put; dp.cNamedArgs = 1; }
    return IDispatch_Invoke(d, id, &IID_NULL, LOCALE_USER_DEFAULT, flags, &dp, res, NULL, NULL);
}

static IDispatch *GetObj(IDispatch *d, const wchar_t *name)
{
    VARIANT v;
    if (FAILED(Call(d, DISPATCH_PROPERTYGET | DISPATCH_METHOD, name, &v, 0, NULL))) return NULL;
    if (v.vt == VT_DISPATCH) return v.pdispVal;
    VariantClear(&v);
    return NULL;
}

static BOOL GetStr(IDispatch *d, const wchar_t *name, wchar_t *out, int cch)
{
    VARIANT v;
    out[0] = 0;
    if (FAILED(Call(d, DISPATCH_PROPERTYGET, name, &v, 0, NULL))) return FALSE;
    if (SUCCEEDED(VariantChangeType(&v, &v, 0, VT_BSTR)) && v.bstrVal) lstrcpynW(out, v.bstrVal, cch);
    VariantClear(&v);
    return TRUE;
}

static LONGLONG GetInt(IDispatch *d, const wchar_t *name, LONGLONG def)
{
    VARIANT v;
    LONGLONG r = def;
    if (FAILED(Call(d, DISPATCH_PROPERTYGET, name, &v, 0, NULL))) return def;
    if (v.vt == VT_BOOL) r = v.boolVal ? 1 : 0;
    else if (SUCCEEDED(VariantChangeType(&v, &v, 0, VT_I8))) r = v.llVal;
    VariantClear(&v);
    return r;
}

/* AutoCAD care ruleaza (din tabela de obiecte active), sau NULL */
static IDispatch *Connect(void)
{
    static HRESULT last = S_OK;
    HRESULT hr = MK_E_UNAVAILABLE;
    int i;
    for (i = 0; i < g_nclsid; i++) {
        IUnknown *u = NULL;
        IDispatch *d = NULL;
        hr = GetActiveObject(&g_clsid[i], NULL, &u);
        if (SUCCEEDED(hr) && u) {
            hr = IUnknown_QueryInterface(u, &IID_IDispatch, (void **)&d);
            IUnknown_Release(u);
            if (d) { last = S_OK; return d; }
        }
    }
    if (hr != last && hr != MK_E_UNAVAILABLE) Log(L"Conectare COM esuata: 0x%08lX", (unsigned long)hr);
    last = hr;
    return NULL;
}

/* "24.3s (LMS Tech)" -> "AutoCAD 2024" */
static BOOL AcadName(IDispatch *app, wchar_t *out, int cch)
{
    wchar_t ver[64];
    int ma = 0, mi = 0, year = 0;
    if (!GetStr(app, L"Version", ver, 64)) return FALSE;     /* AutoCAD ocupat (dialog, comanda) */
    if (swscanf(ver, L"%d.%d", &ma, &mi) >= 1 && ma >= 19 && ma <= 25) {
        static const int base[] = { 2013, 2015, 2017, 2018, 2019, 2021, 2025 };  /* R19 ... R25 */
        year = base[ma - 19] + mi;
    }
    if (year) swprintf(out, cch, L"AutoCAD %d", year);
    else swprintf(out, cch, L"AutoCAD %ls", ver);
    return TRUE;
}

static void BringToFront(IDispatch *app)
{
    HWND h = (HWND)(LONG_PTR)GetInt(app, L"HWND", 0);
    VARIANT v;
    v.vt = VT_BOOL;
    v.boolVal = VARIANT_TRUE;
    Call(app, DISPATCH_PROPERTYPUT, L"Visible", NULL, 1, &v);
    if (h && IsWindow(h)) {
        if (IsIconic(h)) ShowWindow(h, SW_RESTORE);
        SetForegroundWindow(h);
    }
}

/* Documentul activ; creeaza un desen nou daca nu e niciunul deschis */
static IDispatch *ActiveDoc(IDispatch *app)
{
    IDispatch *docs = GetObj(app, L"Documents"), *doc = NULL;
    if (!docs) return NULL;
    if (GetInt(docs, L"Count", 0) == 0) {
        VARIANT r;
        if (SUCCEEDED(Call(docs, DISPATCH_METHOD, L"Add", &r, 0, NULL)) && r.vt == VT_DISPATCH)
            doc = r.pdispVal;
        else
            VariantClear(&r);
    }
    IDispatch_Release(docs);
    return doc ? doc : GetObj(app, L"ActiveDocument");
}

/* AutoCAD inactiv (fara comanda in curs)? */
static BOOL Quiescent(IDispatch *app)
{
    VARIANT r;
    BOOL q = TRUE;
    if (SUCCEEDED(Call(app, DISPATCH_METHOD, L"GetAcadState", &r, 0, NULL)) && r.vt == VT_DISPATCH) {
        q = GetInt(r.pdispVal, L"IsQuiescent", 1) != 0;
        VariantClear(&r);
    } else {
        VariantClear(&r);
    }
    return q;
}

static void LispPath(wchar_t *out, int cch)
{
    wchar_t *p;
    swprintf(out, cch, L"%ls\\TopoKitLoad.lsp", g_contents);
    for (p = out; *p; p++)
        if (*p == L'\\') *p = L'/';
}

/* Trimite comanda in desenul activ: incarca TopoKit daca lipseste, apoi
 * ruleaza comanda. reload = reincarca toate modulele. */
static BOOL SendToAcad(IDispatch *app, const wchar_t *cmd, BOOL reload)
{
    wchar_t lsp[MAX_PATH], text[3 * MAX_PATH];
    IDispatch *doc;
    VARIANT arg;
    HRESULT hr;
    BOOL ok = FALSE;
    g_retryMs = 10000;
    doc = ActiveDoc(app);
    if (doc) {
        LispPath(lsp, MAX_PATH);
        if (reload)
            swprintf(text, 3 * MAX_PATH,
                     L"\x03\x03(progn (if (not TKL:Load) (load \"%ls\")) (TKL:Load T) (princ))\n", lsp);
        else
            swprintf(text, 3 * MAX_PATH,
                     L"\x03\x03(progn (if (not TKL:Load) (load \"%ls\")) (if (not c:TOPOKIT) (TKL:Load nil)) (princ))\n%ls%ls",
                     lsp, cmd ? cmd : L"", cmd ? L"\n" : L"");
        arg.vt = VT_BSTR;
        arg.bstrVal = SysAllocString(text);
        BringToFront(app);
        hr = Call(doc, DISPATCH_METHOD, L"SendCommand", NULL, 1, &arg);
        SysFreeString(arg.bstrVal);
        ok = SUCCEEDED(hr);
        Log(L"SendCommand %ls%ls: 0x%08lX", cmd ? cmd : L"", reload ? L"(reincarcare)" : L"", (unsigned long)hr);
        IDispatch_Release(doc);
    }
    g_retryMs = POLL_RETRY_MS;
    return ok;
}

/* ------------------------------------------------------------------ tray */
static void Balloon(const wchar_t *title, const wchar_t *text)
{
    g_nid.uFlags = NIF_INFO;
    lstrcpynW(g_nid.szInfoTitle, title, 64);
    lstrcpynW(g_nid.szInfo, text, 256);
    g_nid.dwInfoFlags = NIIF_INFO;
    Shell_NotifyIconW(NIM_MODIFY, &g_nid);
}

static void UpdateTray(void)
{
    g_nid.uFlags = NIF_ICON | NIF_TIP;
    g_nid.hIcon = g_connected == TRUE ? g_icoOn : g_icoOff;
    if (g_connected == TRUE)
        swprintf(g_nid.szTip, 128, L"TopoKit - conectat la %ls%ls%ls", g_acadName,
                 g_docName[0] ? L"\n" : L"", g_docName);
    else if (g_pending[0])
        swprintf(g_nid.szTip, 128, L"TopoKit - se pornește AutoCAD...");
    else
        swprintf(g_nid.szTip, 128, L"TopoKit - AutoCAD nu rulează");
    Shell_NotifyIconW(NIM_MODIFY, &g_nid);
}

static void AddTray(void)
{
    memset(&g_nid, 0, sizeof g_nid);
    g_nid.cbSize = sizeof g_nid;
    g_nid.hWnd = g_hwnd;
    g_nid.uID = 1;
    g_nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
    g_nid.uCallbackMessage = WM_TRAY;
    g_nid.hIcon = g_icoOff;
    lstrcpyW(g_nid.szTip, APP_TITLE);
    Shell_NotifyIconW(NIM_ADD, &g_nid);
    g_nid.uVersion = NOTIFYICON_VERSION;
    Shell_NotifyIconW(NIM_SETVERSION, &g_nid);
    UpdateTray();
}

/* Calea acad.exe pentru pornire: serverul COM inregistrat, apoi AcadLocation */
static BOOL FindAcadExe(wchar_t *exe, int cch)
{
    int i;
    for (i = 0; i < g_nclsid; i++) {
        wchar_t key[128], v[2 * MAX_PATH], *s, *e;
        LPOLESTR str;
        if (FAILED(StringFromCLSID(&g_clsid[i], &str))) continue;
        swprintf(key, 128, L"CLSID\\%ls\\LocalServer32", str);
        CoTaskMemFree(str);
        if (!RegGetStr(HKEY_CLASSES_ROOT, key, NULL, v, 2 * MAX_PATH)) continue;
        s = v;
        if (*s == L'"') { s++; if ((e = wcschr(s, L'"'))) *e = 0; }
        else if ((e = wcsstr(s, L" /"))) *e = 0;
        if (GetFileAttributesW(s) != INVALID_FILE_ATTRIBUTES) { lstrcpynW(exe, s, cch); return TRUE; }
    }
    {   /* HKLM\SOFTWARE\Autodesk\AutoCAD\<CurVer>\<CurVer>\AcadLocation */
        wchar_t r[64], p[64], key[256], loc[MAX_PATH];
        if (RegGetStr(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Autodesk\\AutoCAD", L"CurVer", r, 64)) {
            swprintf(key, 256, L"SOFTWARE\\Autodesk\\AutoCAD\\%ls", r);
            if (RegGetStr(HKEY_LOCAL_MACHINE, key, L"CurVer", p, 64)) {
                swprintf(key, 256, L"SOFTWARE\\Autodesk\\AutoCAD\\%ls\\%ls", r, p);
                if (RegGetStr(HKEY_LOCAL_MACHINE, key, L"AcadLocation", loc, MAX_PATH)) {
                    swprintf(exe, cch, L"%ls\\acad.exe", loc);
                    if (GetFileAttributesW(exe) != INVALID_FILE_ATTRIBUTES) return TRUE;
                }
            }
        }
    }
    return FALSE;
}

static void StartAcad(const wchar_t *cmd)
{
    wchar_t exe[MAX_PATH];
    if (!FindAcadExe(exe, MAX_PATH)) {
        Log(L"AutoCAD nu a fost gasit");
        MessageBoxW(g_hwnd, L"AutoCAD nu a fost găsit pe acest calculator.\n\n"
                    L"TopoKit funcționează în AutoCAD 2013 sau mai nou (inclusiv Civil 3D / Map 3D).",
                    APP_TITLE, MB_ICONWARNING);
        return;
    }
    Log(L"Pornesc %ls", exe);
    if ((INT_PTR)ShellExecuteW(NULL, L"open", exe, NULL, NULL, SW_SHOWNORMAL) <= 32) {
        MessageBoxW(g_hwnd, L"AutoCAD nu a putut fi pornit.", APP_TITLE, MB_ICONWARNING);
        return;
    }
    lstrcpynW(g_pending, cmd ? cmd : L"", 64);
    if (!cmd) g_pending[0] = L' ', g_pending[1] = 0;   /* doar asteptam conectarea */
    g_pendingSince = GetTickCount();
    g_readyPolls = 0;
    Balloon(APP_TITLE, L"Se pornește AutoCAD. TopoKit se deschide imediat ce AutoCAD este gata.");
    UpdateTray();
}

/* Comanda ceruta de utilizator: in AutoCAD daca ruleaza, altfel il porneste */
static void RunCommand(const wchar_t *cmd, BOOL reload)
{
    IDispatch *app = Connect();
    if (app) {
        if (!SendToAcad(app, cmd, reload))
            Balloon(APP_TITLE, L"AutoCAD este ocupat. Încercați din nou după terminarea comenzii curente.");
        IDispatch_Release(app);
    } else if (g_pending[0]) {
        lstrcpynW(g_pending, cmd ? cmd : L" ", 64);
    } else {
        StartAcad(cmd);
    }
}

/* Sondajul periodic: starea conexiunii si comenzile in asteptare */
static void Poll(void)
{
    IDispatch *app = Connect();
    BOOL was = g_connected;
    if (app && !AcadName(app, g_acadName, 64)) {
        /* AutoCAD ruleaza dar respinge apelurile: pastram starea anterioara */
        IDispatch_Release(app);
        if (g_connected != TRUE) { lstrcpyW(g_acadName, L"AutoCAD"); g_connected = TRUE; UpdateTray(); }
        return;
    }
    if (app) {
        IDispatch *doc;
        g_docName[0] = 0;
        if ((doc = GetObj(app, L"ActiveDocument"))) {
            GetStr(doc, L"Name", g_docName, MAX_PATH);
            IDispatch_Release(doc);
        }
        g_connected = TRUE;
        if (g_pending[0]) {
            /* AutoCAD tocmai pornit: asteptam sa fie inactiv doua sondaje la rand */
            if (Quiescent(app)) g_readyPolls++;
            else g_readyPolls = 0;
            if (g_readyPolls >= 2) {
                wchar_t cmd[64];
                lstrcpyW(cmd, g_pending);
                g_pending[0] = 0;
                SendToAcad(app, cmd[0] == L' ' ? NULL : cmd, FALSE);
            }
        }
        IDispatch_Release(app);
    } else {
        g_connected = FALSE;
        g_docName[0] = 0;
        if (g_pending[0] && GetTickCount() - g_pendingSince > START_WAIT_MS) {
            g_pending[0] = 0;
            Balloon(APP_TITLE, L"AutoCAD nu a răspuns. Deschideți TopoKit din nou după ce AutoCAD a pornit.");
        }
    }
    if (was != g_connected) {
        Log(g_connected ? L"Conectat la %ls" : L"AutoCAD inchis / nepornit%ls", g_connected ? g_acadName : L"");
        if (g_connected == TRUE && was != -1) {
            wchar_t t[256];
            swprintf(t, 256, L"TopoKit este conectat la %ls. Comenzile TopoKit sunt în meniul acestei iconițe "
                     L"și în AutoCAD (TOPOKIT, ANEXE, TOPOTEREN).", g_acadName);
            Balloon(APP_TITLE, t);
        }
    }
    UpdateTray();
}

static void ShowMenu(void)
{
    HMENU m = CreatePopupMenu();
    POINT pt;
    wchar_t status[256];
    int i;
    UINT sel;
    if (g_connected == TRUE)
        swprintf(status, 256, L"Conectat: %ls%ls%ls", g_acadName, g_docName[0] ? L" - " : L"", g_docName);
    else
        swprintf(status, 256, L"AutoCAD nu rulează");
    AppendMenuW(m, MF_STRING | MF_GRAYED, ID_STATUS, status);
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    for (i = 0; i < NCMDS; i++) AppendMenuW(m, MF_STRING, ID_CMD0 + i, CMDS[i].label);
    SetMenuDefaultItem(m, ID_CMD0, FALSE);
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING | (g_connected == TRUE ? MF_GRAYED : 0), ID_START, L"Pornește AutoCAD");
    AppendMenuW(m, MF_STRING | (g_connected == TRUE ? 0 : MF_GRAYED), ID_RELOAD, L"Reîncarcă TopoKit în AutoCAD");
    AppendMenuW(m, MF_STRING | (AutorunEnabled() ? MF_CHECKED : 0), ID_AUTORUN, L"Pornește odată cu Windows");
    AppendMenuW(m, MF_STRING, ID_FOLDER, L"Deschide folderul TopoKit");
    AppendMenuW(m, MF_STRING, ID_HELP, L"Ajutor");
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING, ID_EXIT, L"Ieșire");
    GetCursorPos(&pt);
    SetForegroundWindow(g_hwnd);
    sel = (UINT)TrackPopupMenu(m, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY, pt.x, pt.y, 0, g_hwnd, NULL);
    PostMessageW(g_hwnd, WM_NULL, 0, 0);
    DestroyMenu(m);
    if (sel >= ID_CMD0 && sel < (UINT)(ID_CMD0 + NCMDS)) RunCommand(CMDS[sel - ID_CMD0].cmd, FALSE);
    else if (sel == ID_START) StartAcad(NULL);
    else if (sel == ID_RELOAD) RunCommand(NULL, TRUE);
    else if (sel == ID_AUTORUN) SetAutorun(!AutorunEnabled());
    else if (sel == ID_FOLDER) ShellExecuteW(NULL, L"open", g_contents, NULL, NULL, SW_SHOWNORMAL);
    else if (sel == ID_HELP) {
        wchar_t f[MAX_PATH];
        GetModuleFileNameW(NULL, f, MAX_PATH);
        lstrcpyW(wcsrchr(f, L'\\') + 1, L"README.html");
        if (GetFileAttributesW(f) == INVALID_FILE_ATTRIBUTES) swprintf(f, MAX_PATH, L"%ls\\README.md", g_contents);
        ShellExecuteW(NULL, L"open", f, NULL, NULL, SW_SHOWNORMAL);
    } else if (sel == ID_EXIT) DestroyWindow(g_hwnd);
}

/* Comanda primita de la o a doua pornire a TopoKit.exe (WM_COPYDATA) */
static void Remote(const wchar_t *arg)
{
    Log(L"Cerere: %ls", arg);
    if (!wcscmp(arg, L"/quit")) DestroyWindow(g_hwnd);
    else if (!wcscmp(arg, L"/background")) Poll();
    else RunCommand(arg[0] ? arg : L"TOPOKIT", FALSE);
}

static LRESULT CALLBACK WndProc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_TRAY:
        if (LOWORD(lp) == WM_LBUTTONDBLCLK) RunCommand(L"TOPOKIT", FALSE);
        else if (LOWORD(lp) == WM_RBUTTONUP || LOWORD(lp) == WM_CONTEXTMENU) ShowMenu();
        return 0;
    case WM_TIMER:
        if (wp == TIMER_POLL) Poll();
        return 0;
    case WM_HOTKEY:
        if (wp == HOTKEY_ID) RunCommand(L"TOPOKIT", FALSE);
        return 0;
    case WM_COPYDATA: {
        COPYDATASTRUCT *cd = (COPYDATASTRUCT *)lp;
        wchar_t arg[128] = L"";
        if (cd && cd->dwData == 0x544B && cd->lpData && cd->cbData < sizeof arg) {
            memcpy(arg, cd->lpData, cd->cbData);
            arg[127] = 0;
            Remote(arg);
        }
        return TRUE;
    }
    case WM_DESTROY:
        KillTimer(h, TIMER_POLL);
        UnregisterHotKey(h, HOTKEY_ID);
        Shell_NotifyIconW(NIM_DELETE, &g_nid);
        Log(L"Lansator oprit");
        PostQuitMessage(0);
        return 0;
    default:
        if (msg == g_msgTaskbar && g_msgTaskbar) { AddTray(); return 0; }   /* Explorer repornit */
    }
    return DefWindowProcW(h, msg, wp, lp);
}

/* "/cmd ANEXE" -> "ANEXE"; "/background", "/quit"; implicit "" (TOPOKIT) */
static void ParseArgs(wchar_t *out, int cch)
{
    int argc, i;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    out[0] = 0;
    for (i = 1; argv && i < argc; i++) {
        if (!_wcsicmp(argv[i], L"/cmd") && i + 1 < argc) {
            wchar_t *p;
            lstrcpynW(out, argv[++i], cch);
            for (p = out; *p; p++)              /* doar nume de comenzi */
                if (!iswalnum(*p) && *p != L'_' && *p != L'-') { *p = 0; break; }
        } else if (!_wcsicmp(argv[i], L"/background") || !_wcsicmp(argv[i], L"/quit")) {
            lstrcpynW(out, argv[i], cch);
            _wcslwr(out);
        }
    }
    LocalFree(argv);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show)
{
    WNDCLASSEXW wc;
    MSG msg;
    HANDLE mutex;
    wchar_t arg[64];
    (void)prev; (void)cmdline; (void)show;
    g_inst = inst;
    ParseArgs(arg, 64);

    mutex = CreateMutexW(NULL, TRUE, MUTEX_NAME);
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        /* Lansatorul ruleaza deja: ii transmitem cererea si iesim */
        HWND other = FindWindowW(WND_CLASS, NULL);
        if (other) {
            COPYDATASTRUCT cd = { 0x544B, (DWORD)((wcslen(arg) + 1) * sizeof(wchar_t)), arg };
            AllowSetForegroundWindow(ASFW_ANY);
            SendMessageW(other, WM_COPYDATA, 0, (LPARAM)&cd);
        }
        return 0;
    }
    if (!wcscmp(arg, L"/quit")) return 0;

    InitLog();
    Log(L"Lansator pornit (%ls)", arg[0] ? arg : L"interactiv");
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    {
        IMessageFilter *old = NULL;
        CoRegisterMessageFilter(&g_mf, &old);
    }
    FindContents();
    Log(L"Fisiere LISP: %ls", g_contents);
    InitClsids();

    g_icoOn = (HICON)LoadImageW(inst, MAKEINTRESOURCEW(IDI_ON), IMAGE_ICON, GetSystemMetrics(SM_CXSMICON),
                                GetSystemMetrics(SM_CYSMICON), 0);
    g_icoOff = (HICON)LoadImageW(inst, MAKEINTRESOURCEW(IDI_OFF), IMAGE_ICON, GetSystemMetrics(SM_CXSMICON),
                                 GetSystemMetrics(SM_CYSMICON), 0);
    memset(&wc, 0, sizeof wc);
    wc.cbSize = sizeof wc;
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.hIcon = LoadIconW(inst, MAKEINTRESOURCEW(IDI_APP));
    wc.lpszClassName = WND_CLASS;
    RegisterClassExW(&wc);
    /* fereastra ascunsa (nu "message-only", ca sa primeasca TaskbarCreated) */
    g_hwnd = CreateWindowExW(WS_EX_TOOLWINDOW, WND_CLASS, APP_TITLE, WS_POPUP, 0, 0, 0, 0, NULL, NULL, inst, NULL);
    if (!g_hwnd) return 1;
    g_msgTaskbar = RegisterWindowMessageW(L"TaskbarCreated");
    AddTray();
    RegisterHotKey(g_hwnd, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_SHIFT | 0x4000 /* MOD_NOREPEAT */, 'T');
    Poll();
    SetTimer(g_hwnd, TIMER_POLL, POLL_MS, NULL);

    if (wcscmp(arg, L"/background")) {
        if (g_connected != TRUE) {
            Balloon(APP_TITLE, L"TopoKit rulează în fundal (iconița de lângă ceas).");
        }
        RunCommand(arg[0] ? arg : L"TOPOKIT", FALSE);
    }

    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    CoRegisterMessageFilter(NULL, NULL);
    CoUninitialize();
    if (mutex) CloseHandle(mutex);
    return 0;
}
