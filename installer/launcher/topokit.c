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
#include <commdlg.h>
#include "resource.h"
#include "ui.h"
#include "license.h"

#define APP_TITLE   L"TopoKit"
#ifndef WND_CLASS                       /* alte nume doar pentru teste (o a doua instanta) */
#define WND_CLASS   L"TopoKitLauncherWnd"
#endif
#ifndef MUTEX_NAME
#define MUTEX_NAME  L"Local\\TopoKitLauncher"
#endif
#define REG_APP     L"Software\\TopoKit"
#define REG_RUN     L"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
#define WM_TRAY     (WM_APP + 1)
#define WM_REMOTE   (WM_APP + 2)    /* cererea altei instante, procesata dupa WM_COPYDATA */
#define WM_LICDONE  (WM_APP + 3)    /* reinnoirea licentei (fir separat) s-a terminat */
#define WM_LICDLG   (WM_APP + 4)    /* deschide fereastra licentei */
#define TIMER_LIC   2
#define LIC_TICK_MS (20 * 60 * 1000)
#define TIMER_POLL  1
#define POLL_MS     3000
#define START_WAIT_MS (240 * 1000)

enum { ID_STATUS = 1000, ID_CMD0 = 1001, ID_OPEN = 1099, ID_START = 1100, ID_RELOAD, ID_AUTORUN,
       ID_FOLDER, ID_HELP, ID_EXIT, ID_LANG, ID_LICENSE, HOTKEY_ID = 1 };

static const struct { const wchar_t *label, *label_en, *cmd; } CMDS[] = {
    { L"Proiect nou (straturi, unități, stiluri)", L"New project (layers, units, styles)", L"TKPROIECT" },
    { L"Scara planului", L"Plan scale", L"TKSCARA" },
    { L"Caroiaj de coordonate", L"Coordinate grid", L"TKCAROIAJ" },
    { L"Setări module (TopoKit)", L"Module settings (TopoKit)", L"TOPOKITSET" },
    { L"Generator anexe (Ordin ANCPI 600/2023)", L"Annex generator (ANCPI Order 600/2023)", L"ANEXE" },
    { L"Teren: puncte, TIN, curbe de nivel, volume", L"Terrain: points, TIN, contour lines, volumes", L"TOPOTEREN" },
    { L"Verificare documentație", L"Check documentation", L"VERIFICARE" },
    { L"Planșe PDF", L"PDF sheets", L"PLANEPDF" },
    { L"Export KMZ (Google Earth)", L"Export KMZ (Google Earth)", L"EXPKMZ" },
    { L"DWG to KMZ (convertor DXF/DWG → KMZ)", L"DWG to KMZ (DXF/DWG → KMZ converter)", L"DWGKMZ" },
    { L"Inserare cadru planșă", L"Insert sheet frame", L"INSCADRU" },
    { L"Adăugare vertexi (ADDVTX)", L"Add vertices (ADDVTX)", L"ADDVTX" },
    { L"Calcul înclinație (Plan Înclinare)", L"Inclination (Plan Înclinare)", L"PLANINCL" },
    { L"Detașare suprafață", L"Area detachment", L"TKDETASARE" },
    { L"Suprafețe (S=, hașură)", L"Areas (S=, hatch)", L"TKSUPRAF" },
    { L"Detașare multiplă", L"Multiple detachment", L"TKDETMULT" },
    { L"Raportare puncte din fișier", L"Draw points from file", L"TKIMPPCT" },
    { L"Legendă automată", L"Automatic legend", L"TKLEGENDA" },
    { L"Cote laturi", L"Side lengths", L"TKCOTE" },
    { L"Setări cadastru", L"Cadastre settings", L"TKCADSET" },
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
BOOL g_en;                              /* interfata in engleza (Language = "EN") */
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
static wchar_t g_excep[256];            /* ultima eroare raportata de AutoCAD (EXCEPINFO) */
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

static void RegSetStr(const wchar_t *name, const wchar_t *v)
{
    HKEY h;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, REG_APP, 0, NULL, 0, KEY_SET_VALUE, NULL, &h, NULL) != ERROR_SUCCESS) return;
    RegSetValueExW(h, name, 0, REG_SZ, (const BYTE *)v, (DWORD)((wcslen(v) + 1) * sizeof(wchar_t)));
    RegCloseKey(h);
}

/* limba aleasa (TOPOKITLANG in AutoCAD sau butonul din fereastra) */
/* Limba se pastreaza in %LOCALAPPDATA%\TopoKit\language.txt ("RO" / "EN"), citit si de
 * TopoKitLoad.lsp. Fisier, nu registru: unele instalari AutoCAD vad o copie virtualizata a
 * registrului, iar fereastra si AutoCAD trebuie sa aiba aceeasi limba. */
static BOOL LangFile(wchar_t *path)
{
    wchar_t dir[MAX_PATH];
    if (FAILED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA | CSIDL_FLAG_CREATE, NULL, 0, dir))) return FALSE;
    swprintf(path, MAX_PATH, L"%ls\\TopoKit", dir);
    CreateDirectoryW(path, NULL);
    lstrcatW(path, L"\\language.txt");
    return TRUE;
}

static void LoadLang(void)
{
    wchar_t p[MAX_PATH], v[16];
    char b[8] = { 0 };
    FILE *f;
    if (LangFile(p) && (f = _wfopen(p, L"rb"))) {
        fread(b, 1, sizeof b - 1, f);
        fclose(f);
        g_en = (b[0] == 'E' || b[0] == 'e') && (b[1] == 'N' || b[1] == 'n');
        return;
    }
    g_en = RegGetStr(HKEY_CURRENT_USER, REG_APP, L"Language", v, 16) && !_wcsicmp(v, L"EN");
}

static void SaveLang(void)
{
    wchar_t p[MAX_PATH];
    FILE *f;
    if (LangFile(p) && (f = _wfopen(p, L"wb"))) {
        fputs(g_en ? "EN\r\n" : "RO\r\n", f);
        fclose(f);
    }
    RegSetStr(L"Language", g_en ? L"EN" : L"RO");
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

/* Incarcatorul din folder: TopoKitLoad.fas (pachetul compilat) sau TopoKitLoad.lsp */
static BOOL LoaderIn(const wchar_t *dir, wchar_t *out, int cch)
{
    swprintf(out, cch, L"%ls\\TopoKitLoad.fas", dir);
    if (GetFileAttributesW(out) != INVALID_FILE_ATTRIBUTES) return TRUE;
    swprintf(out, cch, L"%ls\\TopoKitLoad.lsp", dir);
    return GetFileAttributesW(out) != INVALID_FILE_ATTRIBUTES;
}

/* Folderul cu fisierele LISP: valoarea scrisa de instalator, altfel pachetul
 * ApplicationPlugins standard, altfel folderul programului. */
static void FindContents(void)
{
    wchar_t p[MAX_PATH], f[MAX_PATH];
    if (RegGetStr(HKEY_CURRENT_USER, REG_APP, L"ContentsDir", p, MAX_PATH) && LoaderIn(p, f, MAX_PATH)) {
        wcscpy(g_contents, p);
        return;
    }
    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_APPDATA, NULL, 0, p))) {
        swprintf(f, MAX_PATH, L"%ls\\Autodesk\\ApplicationPlugins\\TopoKit.bundle\\Contents", p);
        if (LoaderIn(f, p, MAX_PATH)) { wcscpy(g_contents, f); return; }
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
    EXCEPINFO ei;
    HRESULT hr;
    wchar_t *p;
    if (res) VariantInit(res);
    if (!d) return E_POINTER;
    hr = IDispatch_GetIDsOfNames(d, &IID_NULL, &n, 1, LOCALE_USER_DEFAULT, &id);
    if (FAILED(hr)) return hr;
    if (flags & DISPATCH_PROPERTYPUT) { dp.rgdispidNamedArgs = &put; dp.cNamedArgs = 1; }
    memset(&ei, 0, sizeof ei);
    hr = IDispatch_Invoke(d, id, &IID_NULL, LOCALE_USER_DEFAULT, flags, &dp, res, &ei, NULL);
    if (hr == DISP_E_EXCEPTION) {
        /* 0x80020009 spune doar "exceptie": textul si codul AutoCAD sunt in EXCEPINFO */
        if (ei.pfnDeferredFillIn) ei.pfnDeferredFillIn(&ei);
        swprintf(g_excep, 256, L"%ls: %ls (0x%08lX)", name, ei.bstrDescription ? ei.bstrDescription : L"?",
                 (unsigned long)(ei.scode ? ei.scode : ei.wCode));
        for (p = g_excep; *p; p++)
            if (*p == L'\r' || *p == L'\n') *p = L' ';
    }
    SysFreeString(ei.bstrSource);
    SysFreeString(ei.bstrDescription);
    SysFreeString(ei.bstrHelpFile);
    return hr;
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
    LoaderIn(g_contents, out, cch);
    for (p = out; *p; p++)
        if (*p == L'\\') *p = L'/';
}

/* Textul trimis in linia de comanda: incarca TopoKit daca lipseste, apoi
 * ruleaza comanda. reload = reincarca toate modulele. cancel = incepe cu doua
 * Ctrl+C (anuleaza comanda in curs); doar pentru WM_COPYDATA: SendCommand
 * respinge orice caracter de control (Ctrl+C, Esc) cu "Invalid input"
 * (0x80200003, vazut ca 0x80020009) - verificat in Civil 3D 2026. */
static void CommandText(const wchar_t *cmd, BOOL reload, BOOL cancel, wchar_t *text, int cch)
{
    wchar_t lsp[MAX_PATH];
    const wchar_t *pre = cancel ? L"\x03\x03" : L"";
    LispPath(lsp, MAX_PATH);
    if (reload)
        swprintf(text, cch, L"%ls(progn (if (not TKL:Load) (load \"%ls\")) (TKL:Load T) (princ))\n", pre, lsp);
    else
        swprintf(text, cch,
                 /* TopoKit lipseste, nu e incarcat sau e alta versiune decat lansatorul
                  * (actualizat cu AutoCAD deschis): incarcatorul se reincarca si,
                  * prin TKL:Stale, reincarca modulele */
                 L"%ls(progn (if (or (not TKL:Load) (not TKL:Stale) (/= *TK:VERSION* \"%hs\")) (load \"%ls\")) "
                 L"(if (not c:TOPOKIT) (TKL:Load nil)) (princ))\n%ls%ls",
                 pre, TK_VERSION, lsp, cmd ? cmd : L"", cmd ? L"\n" : L"");
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
        CommandText(cmd, reload, FALSE, text, 3 * MAX_PATH);
        BringToFront(app);
        Call(doc, DISPATCH_METHOD, L"Activate", NULL, 0, NULL);   /* fila desenului, nu fila Start */
        arg.vt = VT_BSTR;
        arg.bstrVal = SysAllocString(text);
        g_excep[0] = 0;
        hr = Call(doc, DISPATCH_METHOD, L"SendCommand", NULL, 1, &arg);
        SysFreeString(arg.bstrVal);
        Log(L"SendCommand %ls%ls: 0x%08lX%ls%ls", cmd ? cmd : L"", reload ? L"(reincarcare)" : L"", (unsigned long)hr,
            g_excep[0] ? L" - " : L"", g_excep);
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
    CommandText(cmd, reload, TRUE, text, 3 * MAX_PATH);
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
        swprintf(g_nid.szTip, 128, TR(L"TopoKit - conectat la %ls%ls%ls", L"TopoKit - connected to %ls%ls%ls"), g_acadName,
                 g_docName[0] ? L"\n" : L"", g_docName);
    else if (g_pending[0])
        swprintf(g_nid.szTip, 128, TR(L"TopoKit - se pornește AutoCAD...", L"TopoKit - starting AutoCAD..."));
    else
        swprintf(g_nid.szTip, 128, TR(L"TopoKit - AutoCAD nu rulează", L"TopoKit - AutoCAD is not running"));
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
        Note(UI_NOTE_ERR, TR(L"AutoCAD nu a fost găsit pe acest calculator", L"AutoCAD was not found on this computer"));
        MessageBoxW(MsgOwner(), TR(L"AutoCAD nu a fost găsit pe acest calculator.\n\n"
                    L"TopoKit funcționează în AutoCAD 2013 sau mai nou (inclusiv Civil 3D / Map 3D). "
                    L"Dacă AutoCAD este instalat, porniți-l normal: TopoKit se conectează singur.",
                    L"AutoCAD was not found on this computer.\n\n"
                    L"TopoKit works in AutoCAD 2013 or newer (including Civil 3D / Map 3D). "
                    L"If AutoCAD is installed, start it normally: TopoKit connects by itself."),
                    APP_TITLE, MB_ICONWARNING | MB_SETFOREGROUND);
        return;
    }
    what = viaLnk ? lnk : exe;
    Log(L"Pornesc %ls", what);
    if ((INT_PTR)ShellExecuteW(NULL, L"open", what, NULL, NULL, SW_SHOWNORMAL) <= 32) {
        Note(UI_NOTE_ERR, TR(L"AutoCAD nu a putut fi pornit", L"AutoCAD could not be started"));
        MessageBoxW(MsgOwner(), TR(L"AutoCAD nu a putut fi pornit.", L"AutoCAD could not be started."), APP_TITLE,
                    MB_ICONWARNING | MB_SETFOREGROUND);
        return;
    }
    lstrcpynW(g_pending, cmd ? cmd : L"", 64);
    if (!cmd) g_pending[0] = L' ', g_pending[1] = 0;   /* doar asteptam conectarea */
    g_pendingSince = GetTickCount();
    g_readyPolls = 0;
    Balloon(APP_TITLE, TR(L"Se pornește AutoCAD. TopoKit se deschide imediat ce AutoCAD este gata.",
                          L"Starting AutoCAD. TopoKit opens as soon as AutoCAD is ready."));
    UpdateTray();
}

static void ReportWindowError(const AcadWin *w, DWORD err)
{
    if (err == ERROR_ACCESS_DENIED || (w->elevated != 0 && SelfElevated() == 0))
        Note(UI_NOTE_ERR, TR(L"%ls rulează ca administrator: porniți AutoCAD normal (fără „Run as administrator”)",
                             L"%ls runs as administrator: start AutoCAD normally (without \"Run as administrator\")"),
             w->product[0] ? w->product : L"AutoCAD");
    else if (err == ERROR_TIMEOUT)
        Note(UI_NOTE_ERR, TR(L"%ls nu răspunde – terminați comanda curentă și încercați din nou",
                             L"%ls does not respond – finish the current command and try again"),
             w->product[0] ? w->product : L"AutoCAD");
    else
        Note(UI_NOTE_ERR, TR(L"Comanda nu a putut fi trimisă în %ls (cod %lu)", L"The command could not be sent to %ls (code %lu)"), w->product[0] ? w->product : L"AutoCAD",
             (unsigned long)err);
}

static void NoteSent(const wchar_t *cmd, BOOL reload, const wchar_t *product, const wchar_t *doc)
{
    if (reload)
        Note(UI_NOTE_OK, TR(L"TopoKit a fost reîncărcat în %ls", L"TopoKit was reloaded in %ls"), product);
    else
        Note(UI_NOTE_OK, TR(L"%ls trimisă în %ls%ls%ls%ls", L"%ls sent to %ls%ls%ls%ls"), cmd, product, doc && doc[0] ? L" (" : L"",
             doc && doc[0] ? doc : L"", doc && doc[0] ? L")" : L"");
}

/* Comanda ceruta de utilizator: in AutoCAD daca ruleaza, altfel il porneste */
static void RunCommand(const wchar_t *cmd, BOOL reload)
{
    IDispatch *app = Connect();
    AcadWin w;
    BOOL haveWin = FindAcadWindow(&w);
    const wchar_t *product = haveWin && w.product[0] ? w.product : g_acadName[0] ? g_acadName : L"AutoCAD";
    if (app && haveWin && !Quiescent(app)) {
        /* comanda in curs: SendCommand n-o poate anula (nu accepta Ctrl+C), fereastra da */
        IDispatch_Release(app);
        app = NULL;
    }
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
            Note(UI_NOTE_ERR, TR(L"AutoCAD este ocupat – terminați comanda curentă (Esc) și încercați din nou",
                                 L"AutoCAD is busy – finish the current command (Esc) and try again"));
        else
            Note(UI_NOTE_ERR, TR(L"AutoCAD a refuzat comanda (cod 0x%08lX) – deschideți un desen și încercați din nou",
                                 L"AutoCAD refused the command (code 0x%08lX) – open a drawing and try again"),
                 (unsigned long)hr);
    } else if (haveWin) {
        DWORD err = SendViaWindow(&w, cmd, reload);
        if (!err) NoteSent(cmd, reload, product, w.doc);
        else ReportWindowError(&w, err);
    } else if (g_pending[0]) {
        lstrcpynW(g_pending, cmd ? cmd : L" ", 64);
        Note(UI_NOTE_INFO, TR(L"AutoCAD pornește – %ls se deschide imediat ce este gata",
                              L"AutoCAD is starting – %ls opens as soon as it is ready"), cmd ? cmd : L"TopoKit");
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
            Note(UI_NOTE_ERR, TR(L"AutoCAD nu a pornit în 4 minute – porniți-l manual, TopoKit se conectează singur",
                                 L"AutoCAD did not start within 4 minutes – start it manually, TopoKit connects by itself"));
        }
    }
    if (was != g_connected || wasMode != g_mode) {
        if (g_connected == TRUE)
            Log(L"Conectat la %ls (%ls)", g_acadName, g_mode == 1 ? L"COM" : L"fereastra, fara COM");
        else
            Log(L"AutoCAD inchis / nepornit");
        if (g_connected == TRUE && was != TRUE && was != -1) {
            wchar_t t[256];
            swprintf(t, 256, TR(L"TopoKit este conectat la %ls.", L"TopoKit is connected to %ls."), g_acadName);
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
    for (i = 0; i < 5; i++) {
        /* modulele: sursa (build de dezvoltare) sau compilate in ambele formate (fas4 / fas5) */
        static const wchar_t *files[] = { L"TopoKitLoad.lsp", L"TopoKit.lsp", L"fas4\\TopoKit.fas",
                                          L"fas5\\TopoKit.fas", L"anexe\\TopoKitDocx.ps1" };
        swprintf(v, MAX_PATH, L"%ls\\%ls", g_contents, files[i]);
        fwprintf(f, L"  %ls: %ls\n", files[i], PathFileExistsW(v) ? L"da" : L"nu");
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
    if (g_excep[0]) fwprintf(f, L"  ultima eroare AutoCAD: %ls\n", g_excep);
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
    Note(UI_NOTE_INFO, TR(L"Raportul de diagnostic s-a deschis în Notepad", L"The diagnostic report opened in Notepad"));
}

static LicInfo g_lic;                   /* licenta (vezi mai jos, "licenta") */
static void LicUpdate(void);

static void ShowMain(void)
{
    Log(L"Fereastra TopoKit afisata");
    LoadLang();                         /* limba aleasa intre timp in AutoCAD (TOPOKITLANG) */
    Ui_Show();
    if (Lic_Enabled()) {
        LicUpdate();
        if (g_lic.status != LIC_OK) PostMessageW(g_hwnd, WM_LICDLG, 0, 0);
    }
}

/* ------------------------------------------------------------------ licenta (license.c) */
static BOOL g_licChecked, g_licBusy, g_licTried;
static DWORD g_licTry;

static void LicUpdate(void)
{
    if (!Lic_Enabled()) return;
    Lic_Check(NULL, &g_lic);
    g_licChecked = TRUE;
}

static DWORD WINAPI LicRefreshThread(LPVOID p)
{
    wchar_t m[256];
    int r = Lic_Refresh(m, 256);
    (void)p;
    PostMessageW(g_hwnd, WM_LICDONE, (WPARAM)r, 0);
    return 0;
}

/* reinnoire in fundal: o data pe zi (licenta are 14 zile), reincercare la o ora dupa o eroare */
static void LicTick(void)
{
    HANDLE t;
    if (!Lic_Enabled() || g_licBusy) return;
    LicUpdate();
    if (!g_lic.device) return;
    if (g_lic.status == LIC_OK && Lic_Now() - g_lic.iat < 20 * 3600) return;
    if (g_licTried && GetTickCount() - g_licTry < 60 * 60 * 1000) return;
    g_licTried = TRUE;
    g_licTry = GetTickCount();
    g_licBusy = TRUE;
    if ((t = CreateThread(NULL, 0, LicRefreshThread, NULL, 0, NULL)) != NULL) CloseHandle(t);
    else g_licBusy = FALSE;
}

static void LicDlgFill(HWND d, const wchar_t *status)
{
    wchar_t t[600], m[32], date[32];
    BOOL ok;
    LicUpdate();
    ok = g_lic.status == LIC_OK;
    SetWindowTextW(d, TR(L"Licență TopoKit", L"TopoKit licence"));
    if (ok) {
        Lic_FormatDate(g_lic.exp, date, 32);
        swprintf(t, 600, TR(L"Licență activă pentru %ls.\nValabilă până la %ls%ls.", L"Active licence for %ls.\nValid until %ls%ls."),
                 g_lic.name, date, g_lic.device ? TR(L" – se reînnoiește singură când există internet",
                                                       L" – renewed automatically when online") : L"");
    } else if (g_lic.status == LIC_CLOCK) {
        swprintf(t, 600, L"%ls.\n%ls", Lic_StatusText(g_lic.status),
                 TR(L"Corectați data și ora din Windows, apoi apăsați Activează (fără cod: se reînnoiește licența).",
                    L"Correct the Windows date and time, then press Activate (without a code: the licence is renewed)."));
    } else if (g_lic.device) {
        swprintf(t, 600, L"%ls.\n%ls", Lic_StatusText(g_lic.status),
                 TR(L"Apăsați Activează fără cod pentru a reînnoi activarea existentă sau introduceți un cod nou.",
                    L"Press Activate without a code to renew the existing activation, or enter a new code."));
    } else {
        swprintf(t, 600, L"%ls.\n%ls", Lic_StatusText(g_lic.status),
                 TR(L"Introduceți codul de activare primit de la administrator și apăsați Activează.",
                    L"Enter the activation code you received from the administrator and press Activate."));
    }
    SetDlgItemTextW(d, IDC_LIC_INFO, t);
    SetDlgItemTextW(d, IDC_LIC_CODELBL, TR(L"Cod de activare:", L"Activation code:"));
    ShowWindow(GetDlgItem(d, IDC_LIC_CODELBL), ok ? SW_HIDE : SW_SHOW);
    ShowWindow(GetDlgItem(d, IDC_LIC_CODE), ok ? SW_HIDE : SW_SHOW);
    Lic_Machine(m, TRUE);
    swprintf(t, 600, TR(L"Codul acestui calculator: %ls", L"This computer's code: %ls"), m);
    SetDlgItemTextW(d, IDC_LIC_MACHINE, t);
    SetDlgItemTextW(d, IDC_LIC_COPY, TR(L"Copiază codul", L"Copy code"));
    SetDlgItemTextW(d, IDC_LIC_IMPORT, TR(L"Importă fișier...", L"Import file..."));
    SetDlgItemTextW(d, IDC_LIC_DEACT, TR(L"Dezactivează", L"Deactivate"));
    /* dezactivarea elibereaza locul si cu licenta expirata, cat timp exista activarea online */
    ShowWindow(GetDlgItem(d, IDC_LIC_DEACT), ok || g_lic.device ? SW_SHOW : SW_HIDE);
    SetDlgItemTextW(d, IDOK, ok ? TR(L"Reînnoiește", L"Renew") : TR(L"Activează", L"Activate"));
    EnableWindow(GetDlgItem(d, IDOK), !ok || g_lic.device);
    SetDlgItemTextW(d, IDCANCEL, TR(L"Închide", L"Close"));
    if (status) SetDlgItemTextW(d, IDC_LIC_STATUS, status);
}

static void CopyText(HWND owner, const wchar_t *t)
{
    size_t n = (wcslen(t) + 1) * sizeof(wchar_t);
    HGLOBAL h;
    if (!OpenClipboard(owner)) return;
    EmptyClipboard();
    if ((h = GlobalAlloc(GMEM_MOVEABLE, n)) != NULL) {
        memcpy(GlobalLock(h), t, n);
        GlobalUnlock(h);
        if (!SetClipboardData(CF_UNICODETEXT, h)) GlobalFree(h);
    }
    CloseClipboard();
}

static INT_PTR CALLBACK LicDlgProc(HWND d, UINT msg, WPARAM wp, LPARAM lp)
{
    wchar_t code[64], msgt[512], f[MAX_PATH] = L"";
    HCURSOR old;
    (void)lp;
    switch (msg) {
    case WM_INITDIALOG:
        SendMessageW(d, WM_SETICON, ICON_BIG, (LPARAM)LoadIconW(g_inst, MAKEINTRESOURCEW(IDI_APP)));
        SendDlgItemMessageW(d, IDC_LIC_CODE, EM_LIMITTEXT, 40, 0);
        LicDlgFill(d, L"");
        if (g_lic.status != LIC_OK) { SetFocus(GetDlgItem(d, IDC_LIC_CODE)); return FALSE; }
        return TRUE;
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case IDOK:
            old = SetCursor(LoadCursorW(NULL, IDC_WAIT));
            SetDlgItemTextW(d, IDC_LIC_STATUS, TR(L"Se contactează serverul de licențe...", L"Contacting the licence server..."));
            UpdateWindow(d);
            code[0] = 0;
            if (g_lic.status != LIC_OK) GetDlgItemTextW(d, IDC_LIC_CODE, code, 64);
            /* licenta buna, sau activare online existenta si niciun cod: reinnoire (si dupa
             * corectarea ceasului sau o licenta expirata) */
            if (g_lic.status == LIC_OK || (g_lic.device && !code[0])) {
                int r = Lic_Refresh(msgt, 512);
                if (r == LIC_R_OK) lstrcpyW(msgt, TR(L"Licența a fost reînnoită.", L"The licence was renewed."));
            } else {
                if (Lic_Activate(code, msgt, 512) == LIC_OK && !msgt[0])
                    lstrcpyW(msgt, TR(L"TopoKit a fost activat pe acest calculator.", L"TopoKit was activated on this computer."));
            }
            SetCursor(old);
            Log(L"Licenta: %ls", msgt);
            LicDlgFill(d, msgt);
            return TRUE;
        case IDC_LIC_IMPORT: {
            OPENFILENAMEW ofn;
            memset(&ofn, 0, sizeof ofn);
            ofn.lStructSize = sizeof ofn;
            ofn.hwndOwner = d;
            ofn.lpstrFilter = L"TopoKit (*.lic)\0*.lic\0*.*\0*.*\0";
            ofn.lpstrFile = f;
            ofn.nMaxFile = MAX_PATH;
            ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;
            if (GetOpenFileNameW(&ofn)) {
                if (Lic_Import(f, msgt, 512)) lstrcpyW(msgt, TR(L"Licența a fost importată.", L"The licence was imported."));
                Log(L"Licenta importata din %ls: %ls", f, msgt);
                LicDlgFill(d, msgt);
            }
            return TRUE;
        }
        case IDC_LIC_DEACT:
            if (MessageBoxW(d, TR(L"Dezactivați TopoKit pe acest calculator?\nLocul se eliberează pentru alt calculator; "
                                  L"aici veți avea nevoie de un cod nou.",
                                  L"Deactivate TopoKit on this computer?\nThe seat is freed for another computer; "
                                  L"here you will need a new code."),
                            TR(L"Licență TopoKit", L"TopoKit licence"), MB_YESNO | MB_ICONQUESTION) == IDYES) {
                old = SetCursor(LoadCursorW(NULL, IDC_WAIT));
                if (Lic_Deactivate(msgt, 512) != LIC_R_NET)
                    lstrcpyW(msgt, TR(L"TopoKit a fost dezactivat pe acest calculator.", L"TopoKit was deactivated on this computer."));
                SetCursor(old);
                Log(L"Licenta: %ls", msgt);
                LicDlgFill(d, msgt);
            }
            return TRUE;
        case IDC_LIC_COPY:
            Lic_Machine(code, TRUE);
            CopyText(d, code);
            SetDlgItemTextW(d, IDC_LIC_STATUS, TR(L"Codul calculatorului a fost copiat.", L"The computer code was copied."));
            return TRUE;
        case IDCANCEL:
            EndDialog(d, 0);
            return TRUE;
        }
        break;
    }
    return FALSE;
}

static void LicenseDialog(void)
{
    static BOOL open;
    if (open || !Lic_Enabled()) return;
    open = TRUE;
    DialogBoxParamW(g_inst, MAKEINTRESOURCEW(IDD_LICENSE), Ui_Hwnd(), LicDlgProc, 0);
    open = FALSE;
    LicUpdate();
    Ui_Refresh();
    UpdateTray();
}

/* ------------------------------------------------------------------ licenta: linia de comanda
 *   /license [F]   cod de iesire 0 = se poate lucra, 10..14 = LIC_* (TopoKitLoad.lsp, programele Python);
 *                  o licenta care expira in mai putin de 3 zile se reinnoieste intai, daca e internet
 *   /machine       codul calculatorului
 *   /activate COD, /refresh, /deactivate   (teste si administrare)
 * Textul merge la iesirea standard, daca procesul care ne-a pornit a redirectat-o. */
static void Out(const wchar_t *fmt, ...)
{
    wchar_t w[600];
    char u8[1400];
    va_list ap;
    DWORD n;
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    if (!h || h == INVALID_HANDLE_VALUE) return;
    va_start(ap, fmt);
    vswprintf(w, 600, fmt, ap);
    va_end(ap);
    n = (DWORD)WideCharToMultiByte(CP_UTF8, 0, w, -1, u8, sizeof u8, NULL, NULL);
    if (n > 1) WriteFile(h, u8, n - 1, &n, NULL);
}

/* scrie exact len octeti ASCII in fisier (raspunsul /proof pentru modulele AutoLISP) */
static BOOL WriteAsciiFile(const wchar_t *path, const char *data)
{
    HANDLE h = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    DWORD n = 0, len = (DWORD)strlen(data);
    BOOL ok;
    if (h == INVALID_HANDLE_VALUE) return FALSE;
    ok = WriteFile(h, data, len, &n, NULL) && n == len;
    CloseHandle(h);
    return ok;
}

/* Reinnoirea sincrona din liniile de comanda (/license, /license /proof - AutoCAD asteapta raspunsul):
 * doar daca e nevoie (Lic_NeedsRefresh: licenta lipsa / stricata / expirata / ceasul gresit, sau expira
 * in < 3 zile si e mai veche de 20 h), nu in ora de dupa o reinnoire esuata (fara internet: altfel
 * incarcatorul si cele 6 module ar astepta fiecare dupa server). CLI_BUDGET_MS = limita totala
 * (mutex + server); dupa mutex conditia se verifica din nou (LIC_RF_CLI). */
#define CLI_BUDGET_MS 8000
static BOOL CliRefresh(int code, const LicInfo *li)
{
    wchar_t msg[512];
    if (!Lic_NeedsRefresh(code, li)) return FALSE;
    Lic_RefreshEx(msg, 512, CLI_BUDGET_MS, LIC_RF_CLI);
    return TRUE;
}

/*   /license /proof <nonce> <fisier>: aceeasi verificare (si reinnoire) ca /license, apoi scrie
 *   in fisier linia semnata pentru modulul AutoLISP. Codul de iesire ramane cel al licentei. */
static int ProofCli(int argc, wchar_t **argv)
{
    char nonce[96], line[256];
    LicInfo li;
    long long exp = 0;
    int code = LIC_OK, k;
    if (argc < 5) return LIC_BAD;
    k = WideCharToMultiByte(CP_UTF8, 0, argv[3], -1, nonce, sizeof nonce, NULL, NULL);
    if (k <= 0 || !Lic_NonceOk(nonce)) return LIC_BAD;
    if (Lic_Enabled()) {
        code = Lic_Check(NULL, &li);
        if (CliRefresh(code, &li)) code = Lic_Check(NULL, &li);
        exp = (code == LIC_OK) ? li.exp : 0;
    }
    if (Lic_Proof(code, exp, nonce, line, sizeof line)) WriteAsciiFile(argv[4], line);
    return code;
}

static BOOL LicenseCli(void)
{
    int argc, code = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc), msg[512] = L"", buf[64];
    LicInfo li;
    if (!argv || argc < 2) { LocalFree(argv); return FALSE; }
    LoadLang();
    if (!_wcsicmp(argv[1], L"/license")) {
        if (argc > 2 && !_wcsicmp(argv[2], L"/proof")) {
            code = ProofCli(argc, argv);
            LocalFree(argv);
            ExitProcess((UINT)code);
            return TRUE;
        }
        if (!Lic_Enabled()) Out(L"0 licentiere dezactivata\n");
        else {
            const wchar_t *f = argc > 2 ? argv[2] : NULL;
            code = Lic_Check(f, &li);
            /* reinnoire inainte de raspuns; si la LIC_CLOCK: o ora gresita ramasa din viitor se
             * corecteaza cu data serverului (ceasul dat inapoi ramane LIC_CLOCK) */
            if (!f && CliRefresh(code, &li)) code = Lic_Check(NULL, &li);
            if (code == LIC_OK) {
                Lic_FormatDate(li.exp, buf, 64);
                Out(L"0 %ls %ls\n", li.name, buf);
            } else Out(L"%d %ls\n", code, Lic_StatusText(code));
        }
    } else if (!_wcsicmp(argv[1], L"/machine")) {
        Lic_Machine(buf, TRUE);
        Out(L"%ls\n", buf);
    } else if (!_wcsicmp(argv[1], L"/activate") && argc > 2) {
        code = Lic_Activate(argv[2], msg, 512) == LIC_OK ? 0 : 2;
        Out(L"%d %ls\n", code, msg);
    } else if (!_wcsicmp(argv[1], L"/refresh")) {
        code = Lic_Refresh(msg, 512);
        Out(L"%d %ls\n", code, msg);
    } else if (!_wcsicmp(argv[1], L"/deactivate")) {
        code = Lic_Deactivate(msg, 512);
        Out(L"%d %ls\n", code, msg);
    } else {
        LocalFree(argv);
        return FALSE;
    }
    LocalFree(argv);
    ExitProcess((UINT)code);
    return TRUE;
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
    st->lic = NULL;
    st->licOk = TRUE;
    if (Lic_Enabled()) {
        static wchar_t lic[160];
        if (!g_licChecked) LicUpdate();
        st->licOk = g_lic.status == LIC_OK;
        if (st->licOk) swprintf(lic, 160, L"\u2714 %ls", g_lic.name[0] ? g_lic.name : TR(L"Licență activă", L"Active licence"));
        else swprintf(lic, 160, L"\u26A0 %ls", TR(L"Activați TopoKit", L"Activate TopoKit"));
        st->lic = lic;
    }
}

void App_Action(int act, int arg)
{
    wchar_t f[MAX_PATH];
    switch (act) {
    case ACT_LICENSE:
        LicenseDialog();
        break;
    case ACT_CMD:
        if (Lic_Enabled()) {
            LicUpdate();
            if (g_lic.status != LIC_OK) {       /* fara licenta: intai activarea */
                LicenseDialog();
                break;
            }
        }
        if (arg >= 0 && arg < NCMDS &&
            (!wcscmp(CMDS[arg].cmd, L"PLANINCL") || !wcscmp(CMDS[arg].cmd, L"DWGKMZ"))) {
            /* programele separate (nu au nevoie de AutoCAD): Plan Inclinare si
             * convertorul DWG to KMZ, instalate langa TopoKit.exe */
            BOOL pi = !wcscmp(CMDS[arg].cmd, L"PLANINCL");
            const wchar_t *name = pi ? L"Plan Înclinare" : L"DWG to KMZ";
            GetModuleFileNameW(NULL, f, MAX_PATH);
            lstrcpyW(wcsrchr(f, L'\\') + 1, pi ? L"PlanInclinare\\PlanInclinare.exe" : L"modules\\DWGtoKMZ.exe");
            if (PathFileExistsW(f) && (INT_PTR)ShellExecuteW(NULL, L"open", f, NULL, NULL, SW_SHOWNORMAL) > 32) {
                Log(L"Pornit: %ls", f);
                Note(UI_NOTE_OK, TR(L"%ls a fost pornit", L"%ls was started"), name);
            } else if (pi) {
                Log(L"Lipseste: %ls", f);
                Note(UI_NOTE_ERR, TR(L"Nu găsesc PlanInclinare.exe – reinstalați TopoKit",
                                     L"PlanInclinare.exe was not found – reinstall TopoKit"));
            } else {
                Log(L"Lipseste: %ls - exportul DWGKMZ din AutoCAD", f);
                RunCommand(CMDS[arg].cmd, FALSE);
            }
        } else if (arg >= 0 && arg < NCMDS) {
            RunCommand(CMDS[arg].cmd, FALSE);
        }
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
    case ACT_FUNC:                      /* pagina cu toate functiile (in engleza: Functii_EN.html) */
        GetModuleFileNameW(NULL, f, MAX_PATH);
        lstrcpyW(wcsrchr(f, L'\\') + 1, g_en ? L"Functii_EN.html" : L"Functii.html");
        ShellExecuteW(NULL, L"open", f, NULL, NULL, SW_SHOWNORMAL);
        break;
    case ACT_DIAG:
        Diagnostic();
        break;
    case ACT_HIDDEN:
        Balloon(APP_TITLE, TR(L"TopoKit rulează în continuare în fundal. Îl găsiți în iconița de lângă ceas.",
                              L"TopoKit keeps running in the background. You find it in the icon next to the clock."));
        break;
    case ACT_LANG:          /* romana <-> engleza; AutoCAD reincarca TopoKit in limba noua */
        g_en = !g_en;
        SaveLang();
        Log(L"Limba: %ls", g_en ? L"EN" : L"RO");
        if (g_connected == TRUE) RunCommand(NULL, TRUE);
        else Note(UI_NOTE_INFO, TR(L"Limba română – se aplică și în AutoCAD la pornire",
                                   L"English – also applied in AutoCAD at start-up"));
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
    LoadLang();
    if (g_connected == TRUE)
        swprintf(status, 256, TR(L"Conectat: %ls%ls%ls", L"Connected: %ls%ls%ls"), g_acadName, g_docName[0] ? L" - " : L"", g_docName);
    else
        swprintf(status, 256, TR(L"AutoCAD nu rulează", L"AutoCAD is not running"));
    AppendMenuW(m, MF_STRING, ID_OPEN, TR(L"Deschide TopoKit", L"Open TopoKit"));
    SetMenuDefaultItem(m, ID_OPEN, FALSE);
    AppendMenuW(m, MF_STRING | MF_GRAYED, ID_STATUS, status);
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    for (i = 0; i < NCMDS; i++) AppendMenuW(m, MF_STRING, ID_CMD0 + i, TR(CMDS[i].label, CMDS[i].label_en));
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING | (g_connected == TRUE ? MF_GRAYED : 0), ID_START, TR(L"Pornește AutoCAD", L"Start AutoCAD"));
    AppendMenuW(m, MF_STRING | (g_connected == TRUE ? 0 : MF_GRAYED), ID_RELOAD, TR(L"Reîncarcă TopoKit în AutoCAD", L"Reload TopoKit in AutoCAD"));
    AppendMenuW(m, MF_STRING | (AutorunEnabled() ? MF_CHECKED : 0), ID_AUTORUN, TR(L"Pornește odată cu Windows", L"Start with Windows"));
    AppendMenuW(m, MF_STRING, ID_LANG, TR(L"English", L"Română"));
    AppendMenuW(m, MF_STRING, ID_FOLDER, TR(L"Deschide folderul TopoKit", L"Open the TopoKit folder"));
    if (Lic_Enabled()) AppendMenuW(m, MF_STRING, ID_LICENSE, TR(L"Licență...", L"Licence..."));
    AppendMenuW(m, MF_STRING, ID_HELP, TR(L"Ajutor", L"Help"));
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING, ID_EXIT, TR(L"Ieșire", L"Exit"));
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
    else if (sel == ID_LANG) App_Action(ACT_LANG, 0);
    else if (sel == ID_LICENSE) App_Action(ACT_LICENSE, 0);
    else if (sel == ID_EXIT) DestroyWindow(g_hwnd);
}

/* Comanda primita de la o a doua pornire a TopoKit.exe (WM_COPYDATA) */
static void Remote(const wchar_t *arg)
{
    const wchar_t *p;
    /* aceleasi reguli ca ParseArgs: orice proces poate trimite WM_COPYDATA, iar textul ajunge in
     * linia de comanda AutoCAD - doar nume de comenzi, fara expresii LISP */
    for (p = arg; *arg != L'/' && *p; p++)
        if (!iswalnum(*p) && *p != L'_' && *p != L'-') {
            Log(L"Cerere respinsa (caractere nepermise)");
            return;
        }
    Log(L"Cerere: %ls", arg);
    if (arg[0] == L'/' && wcscmp(arg, L"/quit") && wcscmp(arg, L"/background") && wcscmp(arg, L"/diag")) return;
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
        else if (wp == TIMER_LIC) { LicTick(); Ui_Refresh(); }
        return 0;
    case WM_LICDONE:
        g_licBusy = FALSE;
        Log(L"Licenta: reinnoire %ls", wp == LIC_R_OK ? L"reusita" : wp == LIC_R_REVOKED ? L"refuzata (acces oprit)" :
                                       wp == LIC_R_NODEVICE ? L"fara activare online" : L"amanata (fara legatura)");
        LicUpdate();
        Ui_Refresh();
        UpdateTray();
        if (wp == LIC_R_REVOKED)
            Balloon(APP_TITLE, TR(L"Licența TopoKit de pe acest calculator a fost oprită de administrator.",
                                  L"The TopoKit licence on this computer was stopped by the administrator."));
        return 0;
    case WM_LICDLG:
        LicenseDialog();
        return 0;
    case WM_HOTKEY:
        if (wp == HOTKEY_ID) ShowMain();          /* fereastra TopoKit */
        return 0;
    case WM_COPYDATA: {
        COPYDATASTRUCT *cd = (COPYDATASTRUCT *)lp;
        wchar_t arg[128] = L"";
        if (cd && cd->dwData == 0x544B && cd->lpData && cd->cbData < sizeof arg) {
            memcpy(arg, cd->lpData, cd->cbData);
            arg[127] = 0;
            /* in timpul unui SendMessage COM refuza apelurile catre AutoCAD
             * (RPC_E_CANTCALLOUT_ININPUTSYNCCALL, 0x8001010D): raspundem si
             * procesam cererea dupa aceea */
            PostMessageW(h, WM_REMOTE, 0, (LPARAM)_wcsdup(arg));
        }
        return TRUE;
    }
    case WM_REMOTE:
        if (lp) {
            Remote((const wchar_t *)lp);
            free((void *)lp);
        }
        return 0;
    case WM_DESTROY:
        KillTimer(h, TIMER_POLL);
        KillTimer(h, TIMER_LIC);
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
    LoadLang();
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
    if (LicenseCli()) return 0;
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
    Log(L"Lansator TopoKit %hs pornit (%ls)", TK_VERSION, arg[0] ? arg : L"interactiv");
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    {
        IMessageFilter *old = NULL;
        CoRegisterMessageFilter(&g_mf, &old);
    }
    FindContents();
    LoadLang();
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
    if (Lic_Enabled()) {
        LicUpdate();
        Log(L"Licenta: %ls%ls%ls", Lic_StatusText(g_lic.status), g_lic.name[0] ? L" - " : L"", g_lic.name);
        LicTick();
        SetTimer(g_hwnd, TIMER_LIC, LIC_TICK_MS, NULL);
    }

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
