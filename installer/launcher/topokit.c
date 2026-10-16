/*
 * TopoKit.exe - lansatorul TopoKit (iconita din bara de sistem, langa ceas).
 *
 * Ruleaza in fundal si tine legatura cu AutoCAD prin COM (AutoCAD.Application):
 *   - fereastra principala TopoKit (ui.c): starea conexiunii si modulele;
 *   - detecteaza AutoCAD (orice versiune 2013 - 2026) si afiseaza starea
 *     conexiunii in iconita (verde = conectat, gri = AutoCAD nepornit);
 *   - din meniul iconitei porneste comenzile TopoKit in desenul activ
 *     (TOPOKIT, ANEXE, TOPOTEREN, ...); daca AutoCAD nu ruleaza, il porneste
 *     si trimite comanda dupa ce s-a incarcat;
 *   - se asigura ca TopoKit este incarcat in desen (TopoKitLoad.lsp);
 *   - optional porneste odata cu Windows (HKCU\...\Run, parametrul /background).
 *
 * Linie de comanda:
 *   TopoKit.exe               deschide fereastra TopoKit (lansatorul ramane in fundal)
 *   TopoKit.exe /background   doar ruleaza in fundal (pornire cu Windows)
 *   TopoKit.exe /cmd ANEXE    trimite o comanda TopoKit in AutoCAD
 *   TopoKit.exe /quit         inchide lansatorul care ruleaza deja
 *   TopoKit.exe /diag         raportul de diagnostic (diagnostic.txt, in Notepad)
 *   TopoKit.exe /snapshot F.png [on|off|starting] [hover] [scara]
 *                             salveaza imaginea ferestrei (documentatie, teste)
 *
 * Compilare (MinGW-w64): vezi tools/build_installer.py
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
#include <shlwapi.h>
#include <stdarg.h>
#include <stdio.h>
#include <wchar.h>
#include "resource.h"
#include "ui.h"

#define APP_TITLE   L"TopoKit"
#define WND_CLASS   L"TopoKitLauncherWnd"
#define MUTEX_NAME  L"Local\\TopoKitLauncher"
#define REG_APP     L"Software\\TopoKit"
#define REG_RUN     L"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
#define WM_TRAY     (WM_APP + 1)
#define TIMER_POLL  1
#define POLL_MS     3000
#define START_WAIT_MS (240 * 1000)

enum { ID_STATUS = 1000, ID_CMD0 = 1001, ID_OPEN = 1099, ID_START = 1100, ID_RELOAD, ID_AUTORUN,
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
static int g_mode;                      /* legatura curenta: 1 = COM, 2 = doar fereastra AutoCAD */
static wchar_t g_note[256];             /* mesajul afisat in fereastra dupa o actiune */
static int g_noteKind;                  /* UI_NOTE_OK / UI_NOTE_ERR / UI_NOTE_INFO */
static DWORD g_noteTick;
static HRESULT g_lastHr;                /* ultimul rezultat COM (diagnostic) */
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
    for (major = 27; major >= 19 && g_nclsid < MAXCLSID; major--) {
        int minor;
        for (minor = -1; minor <= 3 && g_nclsid < MAXCLSID; minor++) {   /* .25 si .25.0 ... .25.3 */
            int i, dup = 0;
            if (minor < 0) swprintf(pid, 64, L"AutoCAD.Application.%d", major);
            else swprintf(pid, 64, L"AutoCAD.Application.%d.%d", major, minor);
            if (FAILED(CLSIDFromProgID(pid, &c))) continue;
            for (i = 0; i < g_nclsid; i++) dup |= IsEqualCLSID(&c, &g_clsid[i]);
            if (!dup) g_clsid[g_nclsid++] = c;
        }
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

/* CLSID-ul inregistrat are un ProgID AutoCAD.Application*? */
static BOOL IsAcadClsid(const wchar_t *clsidStr)
{
    wchar_t key[96], v[128];
    swprintf(key, 96, L"CLSID\\%ls\\ProgID", clsidStr);
    if (!RegGetStr(HKEY_CLASSES_ROOT, key, NULL, v, 128)) return FALSE;
    return !_wcsnicmp(v, L"AutoCAD.Application", 19);
}

/* Cautare directa in tabela de obiecte active (ROT): intrarile AutoCAD
 * ("!{CLSID}" cu ProgID AutoCAD.Application) si desenele deschise (*.dwg,
 * obiect AcadDocument -> .Application). Ajuta cand versiunea instalata nu are
 * ProgID-ul cautat de GetActiveObject (de exemplu AutoCAD / Civil 3D 2025). */
static IDispatch *ConnectRot(void)
{
    IRunningObjectTable *rot = NULL;
    IEnumMoniker *en = NULL;
    IBindCtx *bc = NULL;
    IMoniker *mk;
    IDispatch *found = NULL;
    if (FAILED(GetRunningObjectTable(0, &rot))) return NULL;
    if (FAILED(CreateBindCtx(0, &bc)) || FAILED(IRunningObjectTable_EnumRunning(rot, &en)) || !en) goto done;
    while (!found && IEnumMoniker_Next(en, 1, &mk, NULL) == S_OK) {
        LPOLESTR name = NULL;
        BOOL app = FALSE, dwg = FALSE;
        if (SUCCEEDED(IMoniker_GetDisplayName(mk, bc, NULL, &name)) && name) {
            size_t n = wcslen(name);
            if (name[0] == L'!' && name[1] == L'{' && n >= 39) {
                wchar_t g[40];
                lstrcpynW(g, name + 1, 39);
                app = IsAcadClsid(g);
            }
            dwg = n > 4 && !_wcsicmp(name + n - 4, L".dwg");
            CoTaskMemFree(name);
        }
        if (app || dwg) {
            IUnknown *u = NULL;
            IDispatch *d = NULL;
            if (SUCCEEDED(IRunningObjectTable_GetObject(rot, mk, &u)) && u) {
                IUnknown_QueryInterface(u, &IID_IDispatch, (void **)&d);
                IUnknown_Release(u);
            }
            if (d && dwg) {
                found = GetObj(d, L"Application");
                IDispatch_Release(d);
            } else if (d) {
                found = d;
            }
        }
        IMoniker_Release(mk);
    }
done:
    if (en) IEnumMoniker_Release(en);
    if (bc) IBindCtx_Release(bc);
    IRunningObjectTable_Release(rot);
    return found;
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
    {
        IDispatch *d = ConnectRot();
        if (d) {
            if (last != S_OK) Log(L"Conectat prin tabela ROT (GetActiveObject: 0x%08lX)", (unsigned long)hr);
            last = S_OK;
            g_lastHr = S_OK;
            return d;
        }
    }
    if (hr != last && hr != MK_E_UNAVAILABLE) Log(L"Conectare COM esuata: 0x%08lX", (unsigned long)hr);
    last = hr;
    g_lastHr = hr;
    return NULL;
}

/* ------------------------------------------------------------------ fereastra AutoCAD (fara COM) */
typedef struct {
    HWND hwnd;
    DWORD pid;
    int elevated;               /* 1 da, 0 nu, -1 necunoscut (acces refuzat: probabil administrator) */
    wchar_t exe[MAX_PATH], title[256], product[64], doc[MAX_PATH];
} AcadWin;

static int ProcessElevated(HANDLE proc)
{
    HANDLE tok;
    TOKEN_ELEVATION te;
    DWORD n;
    int r = -1;
    if (OpenProcessToken(proc, TOKEN_QUERY, &tok)) {
        if (GetTokenInformation(tok, TokenElevation, &te, sizeof te, &n)) r = te.TokenIsElevated ? 1 : 0;
        CloseHandle(tok);
    }
    return r;
}

/* "Autodesk Civil 3D 2025 - [Plan.dwg]" -> produs "Civil 3D 2025", desen "Plan.dwg" */
static void ParseTitle(AcadWin *w)
{
    const wchar_t *t = w->title, *b, *e;
    wchar_t *d;
    if (!_wcsnicmp(t, L"Autodesk ", 9)) t += 9;
    lstrcpynW(w->product, t, 64);
    if ((d = wcsstr(w->product, L" - "))) *d = 0;
    if ((d = wcsstr(w->product, L"  "))) *d = 0;
    if ((d = wcschr(w->product, L'['))) *d = 0;
    StrTrimW(w->product, L" -");
    w->doc[0] = 0;
    if ((b = wcsrchr(w->title, L'[')) && (e = wcschr(b, L']')) && e > b + 1) {
        lstrcpynW(w->doc, b + 1, (int)(e - b));
        if ((d = wcsrchr(w->doc, L'\\'))) memmove(w->doc, d + 1, (wcslen(d + 1) + 1) * sizeof(wchar_t));
    }
}

static BOOL CALLBACK EnumAcad(HWND h, LPARAM lp)
{
    AcadWin *w = (AcadWin *)lp, c;
    HANDLE proc;
    DWORD n = MAX_PATH;
    const wchar_t *base;
    if (!IsWindowVisible(h) || GetWindow(h, GW_OWNER)) return TRUE;
    memset(&c, 0, sizeof c);
    if (!GetWindowTextW(h, c.title, 256) || !c.title[0]) return TRUE;
    GetWindowThreadProcessId(h, &c.pid);
    if (!(proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, c.pid))) return TRUE;
    if (!QueryFullProcessImageNameW(proc, 0, c.exe, &n)) { CloseHandle(proc); return TRUE; }
    base = wcsrchr(c.exe, L'\\') ? wcsrchr(c.exe, L'\\') + 1 : c.exe;
    if (_wcsicmp(base, L"acad.exe")) { CloseHandle(proc); return TRUE; }
    c.elevated = ProcessElevated(proc);
    CloseHandle(proc);
    c.hwnd = h;
    ParseTitle(&c);
    /* fereastra principala: titlul "Autodesk ..." (palete, dialoguri au alt titlu) */
    if (!w->hwnd || (_wcsnicmp(w->title, L"Autodesk", 8) && !_wcsnicmp(c.title, L"Autodesk", 8))) *w = c;
    return _wcsnicmp(w->title, L"Autodesk", 8) != 0;    /* prima fereastra principala in ordinea Z */
}

static BOOL FindAcadWindow(AcadWin *w)
{
    memset(w, 0, sizeof *w);
    EnumWindows(EnumAcad, (LPARAM)w);
    return w->hwnd != NULL;
}

static int SelfElevated(void)
{
    return ProcessElevated(GetCurrentProcess());
}

static void Note(int kind, const wchar_t *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vswprintf(g_note, 256, fmt, ap);
    va_end(ap);
    g_noteKind = kind;
    g_noteTick = GetTickCount();
    Log(L"Mesaj: %ls", g_note);
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

/* Textul trimis in linia de comanda: incarca TopoKit daca lipseste, apoi
 * ruleaza comanda. reload = reincarca toate modulele. */
static void CommandText(const wchar_t *cmd, BOOL reload, wchar_t *text, int cch)
{
    wchar_t lsp[MAX_PATH];
    LispPath(lsp, MAX_PATH);
    if (reload)
        swprintf(text, cch, L"\x03\x03(progn (if (not TKL:Load) (load \"%ls\")) (TKL:Load T) (princ))\n", lsp);
    else
        swprintf(text, cch,
                 L"\x03\x03(progn (if (not TKL:Load) (load \"%ls\")) (if (not c:TOPOKIT) (TKL:Load nil)) (princ))\n%ls%ls",
                 lsp, cmd ? cmd : L"", cmd ? L"\n" : L"");
}

/* Trimiterea prin COM (Document.SendCommand), in desenul activ */
static HRESULT SendToAcad(IDispatch *app, const wchar_t *cmd, BOOL reload)
{
    wchar_t text[3 * MAX_PATH];
    IDispatch *doc;
    VARIANT arg;
    HRESULT hr = E_FAIL;
    g_retryMs = 10000;
    doc = ActiveDoc(app);
    if (doc) {
        CommandText(cmd, reload, text, 3 * MAX_PATH);
        BringToFront(app);
        Call(doc, DISPATCH_METHOD, L"Activate", NULL, 0, NULL);   /* fila desenului, nu fila Start */
        arg.vt = VT_BSTR;
        arg.bstrVal = SysAllocString(text);
        hr = Call(doc, DISPATCH_METHOD, L"SendCommand", NULL, 1, &arg);
        SysFreeString(arg.bstrVal);
        Log(L"SendCommand %ls%ls: 0x%08lX", cmd ? cmd : L"", reload ? L"(reincarcare)" : L"", (unsigned long)hr);
        IDispatch_Release(doc);
    } else {
        Log(L"SendCommand: niciun document activ");
    }
    g_retryMs = POLL_RETRY_MS;
    return hr;
}

/* Trimiterea prin fereastra AutoCAD (WM_COPYDATA, dwData = 1: text pentru linia
 * de comanda). Folosita cand AutoCAD nu raspunde prin COM. Intoarce 0 sau codul Win32. */
static DWORD SendViaWindow(const AcadWin *w, const wchar_t *cmd, BOOL reload)
{
    wchar_t text[3 * MAX_PATH];
    COPYDATASTRUCT cd;
    DWORD_PTR res = 0;
    DWORD err = 0;
    CommandText(cmd, reload, text, 3 * MAX_PATH);
    if (IsIconic(w->hwnd)) ShowWindow(w->hwnd, SW_RESTORE);
    SetForegroundWindow(w->hwnd);
    cd.dwData = 1;
    cd.cbData = (DWORD)((wcslen(text) + 1) * sizeof(wchar_t));
    cd.lpData = text;
    SetLastError(0);
    if (!SendMessageTimeoutW(w->hwnd, WM_COPYDATA, (WPARAM)g_hwnd, (LPARAM)&cd, SMTO_ABORTIFHUNG, 8000, &res))
        err = GetLastError() ? GetLastError() : ERROR_TIMEOUT;
    Log(L"WM_COPYDATA %ls%ls catre %ls: %lu", cmd ? cmd : L"", reload ? L"(reincarcare)" : L"", w->title,
        (unsigned long)err);
    return err;
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
    Ui_Refresh();
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

/* Scurtatura din meniul Start catre acad.exe (pornirea "Civil 3D 2025" cu profilul
 * ei, nu AutoCAD simplu). Preferinta: produsul folosit ultima data, apoi anul
 * cel mai recent, apoi Civil 3D / Map 3D. */
static int g_bestScore;
static void ScanShortcuts(const wchar_t *dir, int depth, const wchar_t *last, wchar_t *best)
{
    wchar_t pat[MAX_PATH], f[MAX_PATH];
    WIN32_FIND_DATAW fd;
    HANDLE h;
    swprintf(pat, MAX_PATH, L"%ls\\*", dir);
    if ((h = FindFirstFileW(pat, &fd)) == INVALID_HANDLE_VALUE) return;
    do {
        if (fd.cFileName[0] == L'.') continue;
        swprintf(f, MAX_PATH, L"%ls\\%ls", dir, fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (depth < 3) ScanShortcuts(f, depth + 1, last, best);
        } else if (wcslen(fd.cFileName) > 4 && !_wcsicmp(fd.cFileName + wcslen(fd.cFileName) - 4, L".lnk")) {
            IShellLinkW *sl = NULL;
            IPersistFile *pf = NULL;
            wchar_t target[MAX_PATH] = L"";
            if (SUCCEEDED(CoCreateInstance(&CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER, &IID_IShellLinkW, (void **)&sl))) {
                if (SUCCEEDED(IShellLinkW_QueryInterface(sl, &IID_IPersistFile, (void **)&pf))) {
                    if (SUCCEEDED(IPersistFile_Load(pf, f, STGM_READ)))
                        IShellLinkW_GetPath(sl, target, MAX_PATH, NULL, SLGP_RAWPATH);
                    IPersistFile_Release(pf);
                }
                IShellLinkW_Release(sl);
            }
            if (wcslen(target) > 8 && !_wcsicmp(target + wcslen(target) - 8, L"acad.exe")) {
                const wchar_t *y = fd.cFileName;
                int score = 0, year = 0;
                for (; *y; y++)
                    if (y[0] == L'2' && y[1] == L'0' && iswdigit(y[2]) && iswdigit(y[3])) { year = _wtoi(y); break; }
                score = year * 10;
                if (StrStrIW(fd.cFileName, L"Civil 3D")) score += 3;
                else if (StrStrIW(fd.cFileName, L"Map 3D")) score += 2;
                if (last[0] && StrStrIW(fd.cFileName, last)) score += 100000;
                if (StrStrIW(fd.cFileName, L"Reset") || StrStrIW(fd.cFileName, L"Uninstall")) score = 0;
                if (score > g_bestScore) { g_bestScore = score; lstrcpynW(best, f, MAX_PATH); }
            }
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

static BOOL FindAcadShortcut(wchar_t *lnk)
{
    wchar_t dir[MAX_PATH], last[64];
    static const int where[] = { CSIDL_PROGRAMS, CSIDL_COMMON_PROGRAMS, CSIDL_DESKTOPDIRECTORY,
                                 CSIDL_COMMON_DESKTOPDIRECTORY };
    unsigned i;
    RegGetStr(HKEY_CURRENT_USER, REG_APP, L"LastProduct", last, 64);
    g_bestScore = 0;
    lnk[0] = 0;
    for (i = 0; i < sizeof where / sizeof where[0]; i++)
        if (SUCCEEDED(SHGetFolderPathW(NULL, where[i], NULL, 0, dir))) ScanShortcuts(dir, 0, last, lnk);
    return lnk[0] != 0;
}

static HWND MsgOwner(void)
{
    HWND u = Ui_Hwnd();
    return u ? u : g_hwnd;
}

static void StartAcad(const wchar_t *cmd)
{
    wchar_t exe[MAX_PATH], lnk[MAX_PATH];
    const wchar_t *what;
    BOOL viaLnk = FindAcadShortcut(lnk);
    if (!viaLnk && !FindAcadExe(exe, MAX_PATH)) {
        Log(L"AutoCAD nu a fost gasit");
        Note(UI_NOTE_ERR, L"AutoCAD nu a fost găsit pe acest calculator");
        MessageBoxW(MsgOwner(), L"AutoCAD nu a fost găsit pe acest calculator.\n\n"
                    L"TopoKit funcționează în AutoCAD 2013 sau mai nou (inclusiv Civil 3D / Map 3D). "
                    L"Dacă AutoCAD este instalat, porniți-l normal: TopoKit se conectează singur.",
                    APP_TITLE, MB_ICONWARNING | MB_SETFOREGROUND);
        return;
    }
    what = viaLnk ? lnk : exe;
    Log(L"Pornesc %ls", what);
    if ((INT_PTR)ShellExecuteW(NULL, L"open", what, NULL, NULL, SW_SHOWNORMAL) <= 32) {
        Note(UI_NOTE_ERR, L"AutoCAD nu a putut fi pornit");
        MessageBoxW(MsgOwner(), L"AutoCAD nu a putut fi pornit.", APP_TITLE, MB_ICONWARNING | MB_SETFOREGROUND);
        return;
    }
    lstrcpynW(g_pending, cmd ? cmd : L"", 64);
    if (!cmd) g_pending[0] = L' ', g_pending[1] = 0;   /* doar asteptam conectarea */
    g_pendingSince = GetTickCount();
    g_readyPolls = 0;
    Balloon(APP_TITLE, L"Se pornește AutoCAD. TopoKit se deschide imediat ce AutoCAD este gata.");
    UpdateTray();
}

static void ReportWindowError(const AcadWin *w, DWORD err)
{
    if (err == ERROR_ACCESS_DENIED || (w->elevated != 0 && SelfElevated() == 0))
        Note(UI_NOTE_ERR, L"%ls rulează ca administrator: porniți AutoCAD normal (fără „Run as administrator”)",
             w->product[0] ? w->product : L"AutoCAD");
    else if (err == ERROR_TIMEOUT)
        Note(UI_NOTE_ERR, L"%ls nu răspunde – terminați comanda curentă și încercați din nou",
             w->product[0] ? w->product : L"AutoCAD");
    else
        Note(UI_NOTE_ERR, L"Comanda nu a putut fi trimisă în %ls (cod %lu)", w->product[0] ? w->product : L"AutoCAD",
             (unsigned long)err);
}

static void NoteSent(const wchar_t *cmd, BOOL reload, const wchar_t *product, const wchar_t *doc)
{
    if (reload)
        Note(UI_NOTE_OK, L"TopoKit a fost reîncărcat în %ls", product);
    else
        Note(UI_NOTE_OK, L"%ls trimisă în %ls%ls%ls%ls", cmd, product, doc && doc[0] ? L" (" : L"",
             doc && doc[0] ? doc : L"", doc && doc[0] ? L")" : L"");
}

/* Comanda ceruta de utilizator: in AutoCAD daca ruleaza, altfel il porneste */
static void RunCommand(const wchar_t *cmd, BOOL reload)
{
    IDispatch *app = Connect();
    AcadWin w;
    BOOL haveWin = FindAcadWindow(&w);
    const wchar_t *product = haveWin && w.product[0] ? w.product : g_acadName[0] ? g_acadName : L"AutoCAD";
    if (app) {
        HRESULT hr = SendToAcad(app, cmd, reload);
        IDispatch_Release(app);
        if (SUCCEEDED(hr)) { NoteSent(cmd, reload, product, g_docName); return; }
        if (haveWin) {                                   /* COM a refuzat: incercam prin fereastra */
            DWORD err = SendViaWindow(&w, cmd, reload);
            if (!err) NoteSent(cmd, reload, product, w.doc);
            else ReportWindowError(&w, err);
            return;
        }
        if (hr == RPC_E_CALL_REJECTED || hr == RPC_E_SERVERCALL_RETRYLATER)
            Note(UI_NOTE_ERR, L"AutoCAD este ocupat – terminați comanda curentă (Esc) și încercați din nou");
        else
            Note(UI_NOTE_ERR, L"AutoCAD a refuzat comanda (cod 0x%08lX) – deschideți un desen și încercați din nou",
                 (unsigned long)hr);
    } else if (haveWin) {
        DWORD err = SendViaWindow(&w, cmd, reload);
        if (!err) NoteSent(cmd, reload, product, w.doc);
        else ReportWindowError(&w, err);
    } else if (g_pending[0]) {
        lstrcpynW(g_pending, cmd ? cmd : L" ", 64);
        Note(UI_NOTE_INFO, L"AutoCAD pornește – %ls se deschide imediat ce este gata", cmd ? cmd : L"TopoKit");
    } else {
        StartAcad(cmd);
    }
}

/* Sondajul periodic: starea conexiunii si comenzile in asteptare */
static void Poll(void)
{
    IDispatch *app = Connect();
    AcadWin w;
    BOOL haveWin = FindAcadWindow(&w);
    BOOL was = g_connected;
    int wasMode = g_mode;
    wchar_t name[64];
    if (haveWin && w.product[0]) {
        wchar_t last[64];
        if (!RegGetStr(HKEY_CURRENT_USER, REG_APP, L"LastProduct", last, 64) || wcscmp(last, w.product)) {
            HKEY h;
            if (RegCreateKeyExW(HKEY_CURRENT_USER, REG_APP, 0, NULL, 0, KEY_SET_VALUE, NULL, &h, NULL) == ERROR_SUCCESS) {
                RegSetValueExW(h, L"LastProduct", 0, REG_SZ, (const BYTE *)w.product,
                               (DWORD)((wcslen(w.product) + 1) * sizeof(wchar_t)));
                RegCloseKey(h);
            }
        }
    }
    if (app && !AcadName(app, name, 64)) {
        /* AutoCAD ruleaza dar respinge apelurile: pastram starea anterioara */
        IDispatch_Release(app);
        if (g_connected != TRUE) {
            lstrcpyW(g_acadName, haveWin && w.product[0] ? w.product : L"AutoCAD");
            g_connected = TRUE;
            g_mode = 1;
            UpdateTray();
        }
        return;
    }
    if (app) {
        IDispatch *doc;
        lstrcpyW(g_acadName, haveWin && w.product[0] ? w.product : name);
        g_docName[0] = 0;
        if ((doc = GetObj(app, L"ActiveDocument"))) {
            GetStr(doc, L"Name", g_docName, MAX_PATH);
            IDispatch_Release(doc);
        }
        g_connected = TRUE;
        g_mode = 1;
        if (g_pending[0]) {
            /* AutoCAD tocmai pornit: asteptam sa fie inactiv doua sondaje la rand */
            if (Quiescent(app)) g_readyPolls++;
            else g_readyPolls = 0;
            if (g_readyPolls >= 2) {
                wchar_t cmd[64];
                HRESULT hr;
                lstrcpyW(cmd, g_pending);
                g_pending[0] = 0;
                hr = SendToAcad(app, cmd[0] == L' ' ? NULL : cmd, FALSE);
                if (SUCCEEDED(hr)) NoteSent(cmd[0] == L' ' ? L"TopoKit" : cmd, FALSE, g_acadName, g_docName);
            }
        }
        IDispatch_Release(app);
    } else if (haveWin) {
        /* AutoCAD vizibil, dar fara legatura COM: lucram prin fereastra lui */
        lstrcpyW(g_acadName, w.product[0] ? w.product : L"AutoCAD");
        lstrcpyW(g_docName, w.doc);
        g_connected = TRUE;
        g_mode = 2;
        if (g_pending[0]) {
            if (++g_readyPolls >= 4) {                   /* ~12 s dupa aparitia ferestrei */
                wchar_t cmd[64];
                DWORD err;
                lstrcpyW(cmd, g_pending);
                g_pending[0] = 0;
                err = SendViaWindow(&w, cmd[0] == L' ' ? NULL : cmd, FALSE);
                if (!err) NoteSent(cmd[0] == L' ' ? L"TopoKit" : cmd, FALSE, g_acadName, g_docName);
                else ReportWindowError(&w, err);
            }
        }
    } else {
        g_connected = FALSE;
        g_mode = 0;
        g_docName[0] = 0;
        if (g_pending[0] && GetTickCount() - g_pendingSince > START_WAIT_MS) {
            g_pending[0] = 0;
            Note(UI_NOTE_ERR, L"AutoCAD nu a pornit în 4 minute – porniți-l manual, TopoKit se conectează singur");
        }
    }
    if (was != g_connected || wasMode != g_mode) {
        if (g_connected == TRUE)
            Log(L"Conectat la %ls (%ls)", g_acadName, g_mode == 1 ? L"COM" : L"fereastra, fara COM");
        else
            Log(L"AutoCAD inchis / nepornit");
        if (g_connected == TRUE && was != TRUE && was != -1) {
            wchar_t t[256];
            swprintf(t, 256, L"TopoKit este conectat la %ls.", g_acadName);
            Balloon(APP_TITLE, t);
        }
    }
    UpdateTray();
}

/* Raportul de diagnostic (%LOCALAPPDATA%\\TopoKit\\diagnostic.txt), deschis in Notepad */
static void Diagnostic(void)
{
    wchar_t path[MAX_PATH], v[MAX_PATH], lnk[MAX_PATH];
    FILE *f;
    AcadWin w;
    IDispatch *app;
    OSVERSIONINFOW os = { sizeof os, 0, 0, 0, 0, { 0 } };
    int i;
    lstrcpyW(path, g_logPath);
    if (!path[0]) return;
    lstrcpyW(wcsrchr(path, L'\\') + 1, L"diagnostic.txt");
    if (!(f = _wfopen(path, L"w, ccs=UTF-8"))) return;
    {
        typedef LONG(WINAPI * RtlGetVersionFn)(OSVERSIONINFOW *);
        RtlGetVersionFn rgv = (RtlGetVersionFn)(void *)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion");
        if (rgv) rgv(&os);
    }
    fwprintf(f, L"TopoKit %hs - diagnostic\n\n", TK_VERSION);
    fwprintf(f, L"Windows %lu.%lu build %lu; TopoKit ca administrator: %ls\n", os.dwMajorVersion, os.dwMinorVersion,
             os.dwBuildNumber, SelfElevated() == 1 ? L"DA" : L"nu");
    fwprintf(f, L"Fisiere LISP: %ls (%ls)\n", g_contents, PathFileExistsW(g_contents) ? L"exista" : L"LIPSESTE");
    for (i = 0; i < 3; i++) {
        static const wchar_t *files[] = { L"TopoKitLoad.lsp", L"TopoKit.lsp", L"anexe\\TopoKitDocx.ps1" };
        swprintf(v, MAX_PATH, L"%ls\\%ls", g_contents, files[i]);
        fwprintf(f, L"  %ls: %ls\n", files[i], PathFileExistsW(v) ? L"da" : L"LIPSESTE");
    }
    fwprintf(f, L"\nProgID-uri AutoCAD.Application inregistrate: %d\n", g_nclsid);
    for (i = 0; i < g_nclsid; i++) {
        wchar_t g[40], key[96], pid[128], srv[2 * MAX_PATH];
        StringFromGUID2(&g_clsid[i], g, 40);
        swprintf(key, 96, L"CLSID\\%ls\\ProgID", g);
        RegGetStr(HKEY_CLASSES_ROOT, key, NULL, pid, 128);
        swprintf(key, 96, L"CLSID\\%ls\\LocalServer32", g);
        RegGetStr(HKEY_CLASSES_ROOT, key, NULL, srv, 2 * MAX_PATH);
        fwprintf(f, L"  %ls %ls -> %ls\n", g, pid, srv);
    }
    app = Connect();
    fwprintf(f, L"Legatura COM: %ls (ultimul cod 0x%08lX)\n", app ? L"DA" : L"nu", (unsigned long)g_lastHr);
    if (app) {
        wchar_t ver[64], dn[MAX_PATH];
        IDispatch *doc;
        GetStr(app, L"Version", ver, 64);
        fwprintf(f, L"  Version: %ls; desene deschise: ", ver);
        if ((doc = GetObj(app, L"Documents"))) {
            fwprintf(f, L"%lld", GetInt(doc, L"Count", -1));
            IDispatch_Release(doc);
        }
        if ((doc = GetObj(app, L"ActiveDocument"))) {
            GetStr(doc, L"Name", dn, MAX_PATH);
            fwprintf(f, L"; activ: %ls", dn);
            IDispatch_Release(doc);
        }
        fwprintf(f, L"; liber: %ls\n", Quiescent(app) ? L"da" : L"nu (comanda in curs)");
        IDispatch_Release(app);
    }
    if (FindAcadWindow(&w))
        fwprintf(f, L"Fereastra AutoCAD: \"%ls\"\n  produs: %ls; desen: %ls\n  %ls (pid %lu); administrator: %ls\n",
                 w.title, w.product, w.doc, w.exe, (unsigned long)w.pid,
                 w.elevated == 1 ? L"DA" : w.elevated == 0 ? L"nu" : L"probabil DA (acces refuzat)");
    else
        fwprintf(f, L"Fereastra AutoCAD: negasita (acad.exe nu ruleaza?)\n");
    fwprintf(f, L"Pornire AutoCAD: %ls\n", FindAcadShortcut(lnk) ? lnk : FindAcadExe(v, MAX_PATH) ? v : L"negasit");
    if (RegGetStr(HKEY_CURRENT_USER, REG_APP, L"LoadedAt", v, MAX_PATH)) {
        wchar_t in[128] = L"";
        RegGetStr(HKEY_CURRENT_USER, REG_APP, L"LoadedIn", in, 128);
        fwprintf(f, L"TopoKit incarcat ultima data in AutoCAD: %ls (%ls)\n", v, in);
    } else {
        fwprintf(f, L"TopoKit incarcat in AutoCAD: niciodata (pachetul nu a fost incarcat)\n");
    }
    {   /* ultimele randuri din jurnal */
        FILE *lg = _wfopen(g_logPath, L"r, ccs=UTF-8");
        static wchar_t lines[40][400];
        int n = 0, k;
        if (lg) {
            while (fgetws(lines[n % 40], 400, lg)) n++;
            fclose(lg);
            fwprintf(f, L"\nJurnal (ultimele %d randuri):\n", n < 40 ? n : 40);
            for (k = n < 40 ? 0 : n - 40; k < n; k++) fwprintf(f, L"%ls", lines[k % 40]);
        }
    }
    fclose(f);
    ShellExecuteW(NULL, L"open", L"notepad.exe", path, NULL, SW_SHOWNORMAL);
    Note(UI_NOTE_INFO, L"Raportul de diagnostic s-a deschis în Notepad");
}

static void ShowMain(void)
{
    Log(L"Fereastra TopoKit afisata");
    Ui_Show();
}

/* ------------------------------------------------------------------ legatura cu fereastra (ui.c) */
void App_State(UiState *st)
{
    st->state = g_connected == TRUE ? UI_ON : g_pending[0] ? UI_STARTING : UI_OFF;
    st->acad = g_acadName;
    st->doc = g_docName;
    st->autorun = AutorunEnabled();
    st->note = NULL;
    if (g_note[0] && GetTickCount() - g_noteTick < (DWORD)(g_noteKind == UI_NOTE_ERR ? 45000 : 12000)) {
        st->note = g_note;
        st->noteKind = g_noteKind;
    }
}

void App_Action(int act, int arg)
{
    wchar_t f[MAX_PATH];
    switch (act) {
    case ACT_CMD:
        if (arg >= 0 && arg < NCMDS) RunCommand(CMDS[arg].cmd, FALSE);
        break;
    case ACT_START:
        if (g_connected != TRUE && !g_pending[0]) StartAcad(NULL);
        break;
    case ACT_RELOAD:
        RunCommand(NULL, TRUE);
        break;
    case ACT_AUTORUN:
        SetAutorun(!AutorunEnabled());
        break;
    case ACT_FOLDER:
        ShellExecuteW(NULL, L"open", g_contents, NULL, NULL, SW_SHOWNORMAL);
        break;
    case ACT_HELP:
        GetModuleFileNameW(NULL, f, MAX_PATH);
        lstrcpyW(wcsrchr(f, L'\\') + 1, L"README.html");
        if (GetFileAttributesW(f) == INVALID_FILE_ATTRIBUTES) swprintf(f, MAX_PATH, L"%ls\\README.md", g_contents);
        ShellExecuteW(NULL, L"open", f, NULL, NULL, SW_SHOWNORMAL);
        break;
    case ACT_DIAG:
        Diagnostic();
        break;
    case ACT_HIDDEN:
        Balloon(APP_TITLE, L"TopoKit rulează în continuare în fundal. Îl găsiți în iconița de lângă ceas.");
        break;
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
    AppendMenuW(m, MF_STRING, ID_OPEN, L"Deschide TopoKit");
    SetMenuDefaultItem(m, ID_OPEN, FALSE);
    AppendMenuW(m, MF_STRING | MF_GRAYED, ID_STATUS, status);
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    for (i = 0; i < NCMDS; i++) AppendMenuW(m, MF_STRING, ID_CMD0 + i, CMDS[i].label);
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
    if (sel == ID_OPEN) ShowMain();
    else if (sel >= ID_CMD0 && sel < (UINT)(ID_CMD0 + NCMDS)) App_Action(ACT_CMD, (int)(sel - ID_CMD0));
    else if (sel == ID_START) App_Action(ACT_START, 0);
    else if (sel == ID_RELOAD) App_Action(ACT_RELOAD, 0);
    else if (sel == ID_AUTORUN) App_Action(ACT_AUTORUN, 0);
    else if (sel == ID_FOLDER) App_Action(ACT_FOLDER, 0);
    else if (sel == ID_HELP) App_Action(ACT_HELP, 0);
    else if (sel == ID_EXIT) DestroyWindow(g_hwnd);
}

/* Comanda primita de la o a doua pornire a TopoKit.exe (WM_COPYDATA) */
static void Remote(const wchar_t *arg)
{
    Log(L"Cerere: %ls", arg);
    if (!wcscmp(arg, L"/quit")) DestroyWindow(g_hwnd);
    else if (!wcscmp(arg, L"/background")) Poll();
    else if (!wcscmp(arg, L"/diag")) Diagnostic();
    else if (!arg[0]) ShowMain();
    else RunCommand(arg, FALSE);
}

static LRESULT CALLBACK WndProc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_TRAY:
        if (LOWORD(lp) == WM_LBUTTONDBLCLK) ShowMain();
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
        Ui_Destroy();
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
        } else if (!_wcsicmp(argv[i], L"/background") || !_wcsicmp(argv[i], L"/quit") || !_wcsicmp(argv[i], L"/diag")) {
            lstrcpynW(out, argv[i], cch);
            _wcslwr(out);
        }
    }
    LocalFree(argv);
}

/* /snapshot F.png [on|off|starting] [hover] [scara]: imaginea ferestrei, fara lansator */
static BOOL Snapshot(void)
{
    int argc, hover = -1;
    float scale = 1.0f;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    BOOL ok;
    if (!argv || argc < 3 || _wcsicmp(argv[1], L"/snapshot")) { LocalFree(argv); return FALSE; }
    if (argc > 3 && !_wcsicmp(argv[3], L"on")) {
        g_connected = TRUE;
        lstrcpyW(g_acadName, L"AutoCAD 2024");
        lstrcpyW(g_docName, L"Plan_cadastral.dwg");
    } else if (argc > 3 && !_wcsicmp(argv[3], L"starting")) {
        lstrcpyW(g_pending, L"ANEXE");
    }
    if (argc > 4) hover = _wtoi(argv[4]);
    if (argc > 5) scale = (float)_wtof(argv[5]);
    if (scale < 0.5f || scale > 4.0f) scale = 1.0f;
    ok = Ui_Init(g_inst) && Ui_Snapshot(argv[2], scale, hover);
    LocalFree(argv);
    ExitProcess(ok ? 0 : 2);
    return TRUE;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show)
{
    WNDCLASSEXW wc;
    MSG msg;
    HANDLE mutex;
    wchar_t arg[64];
    (void)prev; (void)cmdline; (void)show;
    g_inst = inst;
    if (Snapshot()) return 0;
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
    Ui_Init(inst);

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

    if (!arg[0]) ShowMain();
    else if (!wcscmp(arg, L"/diag")) Diagnostic();
    else if (wcscmp(arg, L"/background")) RunCommand(arg, FALSE);

    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    CoRegisterMessageFilter(NULL, NULL);
    CoUninitialize();
    if (mutex) CloseHandle(mutex);
    return 0;
}
