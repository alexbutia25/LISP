/*
 * fake_acad.exe - "AutoCAD" simulat pentru testarea lansatorului TopoKit.exe
 * sub Wine (tests/test_installer.py). Expune prin COM (tabela de obiecte
 * active, ProgID AutoCAD.Application) un model minimal:
 *
 *   Application: Version, HWND, Visible, ActiveDocument, Documents, GetAcadState()
 *   Documents:   Count, Add()
 *   Document:    Name, SendCommand(text)    -> textul este scris in fisierul jurnal
 *   AcadState:   IsQuiescent
 *
 *   fake_acad.exe /regserver JURNAL   inregistreaza ProgID-ul si serverul COM (HKCR)
 *   fake_acad.exe                     ruleaza 60 s (sau pana la SendCommand "QUIT")
 *
 * Testul il copiaza ca "acad.exe" (lansatorul recunoaste AutoCAD dupa proces).
 * Fereastra principala are titlul Civil 3D 2025 si primeste comenzi si prin
 * WM_COPYDATA (dwData = 1), scrise in jurnal ca "COPYDATA <text>". Cu valoarea
 * HKCU\Software\TopoKitTest\NoRot = "1" nu se inregistreaza in ROT (AutoCAD
 * fara legatura COM, ca in cazurile reale cu Civil 3D 2025).
 *
 * Jurnalul (calea din HKCU\Software\TopoKitTest\Log) primeste cate o linie
 * pentru fiecare SendCommand, cu caracterele de control scrise ca <03>, <LF>.
 */
#ifndef UNICODE
#define UNICODE
#endif
#define COBJMACROS
#include <windows.h>
#include <ole2.h>
#include <oleauto.h>
#include <stdio.h>
#include <wchar.h>

static const CLSID CLSID_Fake = { 0x7a1c0b52, 0x3f0e, 0x4c1a, { 0x9b, 0x61, 0x2d, 0x55, 0x10, 0x7e, 0x41, 0x0a } };
static wchar_t g_log[MAX_PATH];
static HWND g_hwnd;
static int g_docs = 0;
static int g_busyPolls = 2;     /* primele interogari GetAcadState: ocupat (pornire) */
static BOOL g_quit;

enum { O_APP, O_DOCS, O_DOC, O_STATE };
typedef struct { IDispatch disp; LONG ref; int kind; } Obj;
static IDispatchVtbl g_vtbl;

static IDispatch *NewObj(int kind)
{
    Obj *o = (Obj *)calloc(1, sizeof(Obj));
    o->disp.lpVtbl = &g_vtbl;
    o->ref = 1;
    o->kind = kind;
    return &o->disp;
}

static void LogLine(const wchar_t *prefix, const wchar_t *t)
{
    FILE *f = _wfopen(g_log, L"a");
    if (!f) return;
    fwprintf(f, L"%ls", prefix);
    for (; t && *t; t++) {
        if (*t == L'\n') fwprintf(f, L"<LF>");
        else if (*t < 32) fwprintf(f, L"<%02X>", (unsigned)*t);
        else fputwc(*t, f);
    }
    fputwc(L'\n', f);
    fclose(f);
}

static HRESULT STDMETHODCALLTYPE QI(IDispatch *t, REFIID riid, void **ppv)
{
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IDispatch)) {
        *ppv = t;
        IDispatch_AddRef(t);
        return S_OK;
    }
    *ppv = NULL;
    return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE AddRef(IDispatch *t) { return InterlockedIncrement(&((Obj *)t)->ref); }
static ULONG STDMETHODCALLTYPE Release(IDispatch *t)
{
    LONG r = InterlockedDecrement(&((Obj *)t)->ref);
    if (!r) free(t);
    return r;
}
static HRESULT STDMETHODCALLTYPE TIC(IDispatch *t, UINT *n) { (void)t; *n = 0; return S_OK; }
static HRESULT STDMETHODCALLTYPE TI(IDispatch *t, UINT i, LCID l, ITypeInfo **ti)
{
    (void)t; (void)i; (void)l; *ti = NULL; return E_NOTIMPL;
}

static const wchar_t *NAMES[] = { L"Version", L"HWND", L"Visible", L"ActiveDocument", L"Documents",
                                  L"GetAcadState", L"Count", L"Add", L"Name", L"SendCommand", L"IsQuiescent", L"Activate" };
#define NNAMES ((int)(sizeof(NAMES) / sizeof(NAMES[0])))

static HRESULT STDMETHODCALLTYPE IDs(IDispatch *t, REFIID r, LPOLESTR *names, UINT n, LCID l, DISPID *ids)
{
    int i;
    (void)t; (void)r; (void)l;
    if (n != 1) return E_INVALIDARG;
    for (i = 0; i < NNAMES; i++)
        if (!_wcsicmp(names[0], NAMES[i])) { ids[0] = i + 1; return S_OK; }
    LogLine(L"UNKNOWN ", names[0]);
    ids[0] = DISPID_UNKNOWN;
    return DISP_E_UNKNOWNNAME;
}

static HRESULT STDMETHODCALLTYPE Inv(IDispatch *t, DISPID id, REFIID r, LCID l, WORD fl, DISPPARAMS *dp,
                                     VARIANT *res, EXCEPINFO *ei, UINT *ae)
{
    Obj *o = (Obj *)t;
    const wchar_t *name = id >= 1 && id <= NNAMES ? NAMES[id - 1] : L"?";
    (void)r; (void)l; (void)fl; (void)ae;
    if (res) VariantInit(res);
    if (o->kind == O_APP && !wcscmp(name, L"Version")) {
        res->vt = VT_BSTR; res->bstrVal = SysAllocString(L"25.0s (LMS Tech)");
    } else if (o->kind == O_APP && !wcscmp(name, L"HWND")) {
        res->vt = VT_I8; res->llVal = (LONGLONG)(LONG_PTR)g_hwnd;
    } else if (o->kind == O_APP && !wcscmp(name, L"Visible")) {
        if (res) { res->vt = VT_BOOL; res->boolVal = VARIANT_TRUE; }
    } else if (o->kind == O_APP && !wcscmp(name, L"ActiveDocument")) {
        if (!g_docs) return DISP_E_EXCEPTION;
        res->vt = VT_DISPATCH; res->pdispVal = NewObj(O_DOC);
    } else if (o->kind == O_APP && !wcscmp(name, L"Documents")) {
        res->vt = VT_DISPATCH; res->pdispVal = NewObj(O_DOCS);
    } else if (o->kind == O_APP && !wcscmp(name, L"GetAcadState")) {
        res->vt = VT_DISPATCH; res->pdispVal = NewObj(O_STATE);
    } else if (o->kind == O_STATE && !wcscmp(name, L"IsQuiescent")) {
        res->vt = VT_BOOL;
        res->boolVal = g_busyPolls > 0 ? VARIANT_FALSE : VARIANT_TRUE;
        if (g_busyPolls > 0) g_busyPolls--;
    } else if (o->kind == O_DOCS && !wcscmp(name, L"Count")) {
        res->vt = VT_I4; res->lVal = g_docs;
    } else if (o->kind == O_DOCS && !wcscmp(name, L"Add")) {
        g_docs++;
        LogLine(L"DOCUMENTS.ADD", L"");
        res->vt = VT_DISPATCH; res->pdispVal = NewObj(O_DOC);
    } else if (o->kind == O_DOC && !wcscmp(name, L"Name")) {
        res->vt = VT_BSTR; res->bstrVal = SysAllocString(L"Plan_cadastral.dwg");
    } else if (o->kind == O_DOC && !wcscmp(name, L"Activate")) {
        LogLine(L"ACTIVATE", L"");
    } else if (o->kind == O_DOC && !wcscmp(name, L"SendCommand")) {
        const wchar_t *c;
        if (!dp || dp->cArgs != 1 || dp->rgvarg[0].vt != VT_BSTR) return DISP_E_TYPEMISMATCH;
        /* ca AutoCAD 2025/2026: caracterele de control (Ctrl+C, Esc) -> "Invalid input" */
        for (c = dp->rgvarg[0].bstrVal; *c; c++)
            if (*c < 32 && *c != L'\n' && *c != L'\r') {
                LogLine(L"REJECTED ", dp->rgvarg[0].bstrVal);
                if (ei) {
                    memset(ei, 0, sizeof *ei);
                    ei->bstrDescription = SysAllocString(L"Invalid input");
                    ei->scode = (SCODE)0x80200003;
                }
                return DISP_E_EXCEPTION;
            }
        LogLine(L"SEND ", dp->rgvarg[0].bstrVal);
        if (wcsstr(dp->rgvarg[0].bstrVal, L"QUIT")) g_quit = TRUE;
    } else {
        LogLine(L"BADCALL ", name);
        return DISP_E_MEMBERNOTFOUND;
    }
    return S_OK;
}

static IDispatchVtbl g_vtbl = { QI, AddRef, Release, TIC, TI, IDs, Inv };

static LRESULT CALLBACK WndProc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_COPYDATA) {
        COPYDATASTRUCT *cd = (COPYDATASTRUCT *)lp;
        if (cd && cd->dwData == 1 && cd->lpData) {
            LogLine(L"COPYDATA ", (const wchar_t *)cd->lpData);
            if (wcsstr((const wchar_t *)cd->lpData, L"QUIT")) g_quit = TRUE;
        }
        return TRUE;
    }
    return DefWindowProcW(h, msg, wp, lp);
}

static void SetKey(HKEY root, const wchar_t *key, const wchar_t *name, const wchar_t *val)
{
    HKEY h;
    if (RegCreateKeyExW(root, key, 0, NULL, 0, KEY_WRITE, NULL, &h, NULL) == ERROR_SUCCESS) {
        RegSetValueExW(h, name, 0, REG_SZ, (const BYTE *)val, (DWORD)((wcslen(val) + 1) * sizeof(wchar_t)));
        RegCloseKey(h);
    }
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show)
{
    int argc;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc), clsid[64], key[128], exe[MAX_PATH];
    DWORD cookie = 0, size = sizeof g_log;
    wchar_t norot[8] = L"";
    DWORD nsz = sizeof norot;
    WNDCLASSW wc;
    IDispatch *app;
    DWORD t0;
    MSG msg;
    HKEY h;
    (void)prev; (void)cmd; (void)show;
    StringFromGUID2(&CLSID_Fake, clsid, 64);
    if (argc >= 3 && !wcscmp(argv[1], L"/regserver")) {
        GetModuleFileNameW(NULL, exe, MAX_PATH);
        SetKey(HKEY_CLASSES_ROOT, L"AutoCAD.Application\\CLSID", NULL, clsid);
        SetKey(HKEY_CLASSES_ROOT, L"AutoCAD.Application.25\\CLSID", NULL, clsid);
        swprintf(key, 128, L"CLSID\\%ls\\ProgID", clsid);
        SetKey(HKEY_CLASSES_ROOT, key, NULL, L"AutoCAD.Application.25");
        swprintf(key, 128, L"CLSID\\%ls\\LocalServer32", clsid);
        SetKey(HKEY_CLASSES_ROOT, key, NULL, exe);
        SetKey(HKEY_CURRENT_USER, L"Software\\TopoKitTest", L"Log", argv[2]);
        return 0;
    }
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software\\TopoKitTest", 0, KEY_READ, &h) == ERROR_SUCCESS) {
        RegQueryValueExW(h, L"Log", NULL, NULL, (BYTE *)g_log, &size);
        RegQueryValueExW(h, L"NoRot", NULL, NULL, (BYTE *)norot, &nsz);
        RegCloseKey(h);
    }
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.lpszClassName = L"Afx:FakeAcad";
    RegisterClassW(&wc);
    g_hwnd = CreateWindowExW(0, L"Afx:FakeAcad", L"Autodesk Civil 3D 2025 - [Plan_cadastral.dwg]",
                             WS_OVERLAPPEDWINDOW | WS_VISIBLE, 0, 0, 400, 300, NULL, NULL, inst, NULL);
    Sleep(1500);                 /* AutoCAD real: cateva secunde pana la inregistrare */
    app = NewObj(O_APP);
    if (norot[0] != L'1') RegisterActiveObject((IUnknown *)app, &CLSID_Fake, ACTIVEOBJECT_STRONG, &cookie);
    LogLine(norot[0] == L'1' ? L"STARTED NOROT" : L"STARTED", L"");
    t0 = GetTickCount();
    while (!g_quit && GetTickCount() - t0 < 60000) {
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
        MsgWaitForMultipleObjects(0, NULL, FALSE, 100, QS_ALLINPUT);
    }
    if (cookie) RevokeActiveObject(cookie, NULL);
    IDispatch_Release(app);
    LogLine(L"EXIT", L"");
    CoUninitialize();
    return 0;
}
