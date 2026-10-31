/*
 * license.c - licenta TopoKit in lansator
 *
 *  - codul calculatorului: SHA-256("TopoKit/1|MachineGuid|seria volumului de sistem"), 24 cifre hex;
 *  - fisierul %LOCALAPPDATA%\TopoKit\license.lic: "TK1.<payload>.<semnatura>", semnat ECDSA P-256
 *    (formatul complet in tools/licenta.py); verificat cu cheia publica compilata (TK_LIC_PUB);
 *  - activarea si reinnoirea prin serverul de licente (server/worker.js), cu WinHTTP;
 *  - state.dat: ID-ul dispozitivului si secretul lui, protejate cu DPAPI (doar acest utilizator
 *    Windows le poate citi).
 *
 * Fara TK_LIC_PUB la compilare licentierea e dezactivata (build de dezvoltare): Lic_Enabled() = FALSE
 * si "TopoKit.exe /license" iese cu 0. Criptografia este cea din Windows (CNG) - fara biblioteci.
 * Pentru teste: TOPOKIT_LICDIR (alt folder pentru license.lic / state.dat) si TOPOKIT_LICSERVER.
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <wincrypt.h>
#include <winhttp.h>
#include <shlobj.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include "license.h"
#include "ui.h"

#ifndef TK_VERSION
#define TK_VERSION "dev"
#endif
#ifndef TK_LIC_KID
#define TK_LIC_KID "k1"
#endif
#ifndef TK_LIC_URL
#define TK_LIC_URL ""
#endif
#ifndef WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY
#define WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY 4
#endif
#define WIDEN2(x) L##x
#define WIDEN(x) WIDEN2(x)

#define MAX_LIC 4096

BOOL Lic_Enabled(void)
{
#ifdef TK_LIC_PUB
    return sizeof(TK_LIC_PUB) == 129;           /* 64 octeti X||Y in hex */
#else
    return FALSE;
#endif
}

long long Lic_Now(void)
{
    FILETIME ft;
    ULARGE_INTEGER u;
    GetSystemTimeAsFileTime(&ft);
    u.LowPart = ft.dwLowDateTime;
    u.HighPart = ft.dwHighDateTime;
    return (long long)(u.QuadPart / 10000000ULL) - 11644473600LL;
}

/* ------------------------------------------------------------------ fisiere */
static BOOL LicPath(const wchar_t *name, wchar_t *out)
{
    wchar_t d[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"TOPOKIT_LICDIR", d, MAX_PATH);
    if (!n || n >= MAX_PATH) {
        if (FAILED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA | CSIDL_FLAG_CREATE, NULL, 0, d))) return FALSE;
        lstrcatW(d, L"\\TopoKit");
    }
    CreateDirectoryW(d, NULL);
    return swprintf(out, MAX_PATH, L"%ls\\%ls", d, name) > 0;
}

static int ReadAll(const wchar_t *path, char *buf, int cap)
{
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    DWORD n = 0;
    if (h == INVALID_HANDLE_VALUE) return -1;
    if (!ReadFile(h, buf, (DWORD)cap - 1, &n, NULL)) n = 0;
    CloseHandle(h);
    buf[n] = 0;
    return (int)n;
}

static BOOL WriteAll(const wchar_t *path, const void *data, DWORD len)
{
    wchar_t tmp[MAX_PATH + 8];
    HANDLE h;
    DWORD n = 0;
    BOOL ok;
    swprintf(tmp, MAX_PATH + 8, L"%ls.tmp", path);
    h = CreateFileW(tmp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return FALSE;
    ok = WriteFile(h, data, len, &n, NULL) && n == len;
    CloseHandle(h);
    return ok && MoveFileExW(tmp, path, MOVEFILE_REPLACE_EXISTING);
}

static void DeleteLicFiles(void)
{
    wchar_t p[MAX_PATH];
    if (LicPath(L"license.lic", p)) DeleteFileW(p);
    if (LicPath(L"state.dat", p)) DeleteFileW(p);
}

/* ------------------------------------------------------------------ CNG: SHA-256 si ECDSA P-256 */
static BOOL Sha256(const void *data, DWORD len, BYTE out[32])
{
    BCRYPT_ALG_HANDLE a = NULL;
    BCRYPT_HASH_HANDLE h = NULL;
    BOOL ok = FALSE;
    if (BCryptOpenAlgorithmProvider(&a, BCRYPT_SHA256_ALGORITHM, NULL, 0)) return FALSE;
    if (!BCryptCreateHash(a, &h, NULL, 0, NULL, 0, 0)) {
        ok = !BCryptHashData(h, (PUCHAR)data, len, 0) && !BCryptFinishHash(h, out, 32, 0);
        BCryptDestroyHash(h);
    }
    BCryptCloseAlgorithmProvider(a, 0);
    return ok;
}

static int HexVal(int c)
{
    return c >= '0' && c <= '9' ? c - '0' : c >= 'A' && c <= 'F' ? c - 'A' + 10 : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1;
}

static BOOL VerifySig(const char *msg, DWORD len, const BYTE sig[64])
{
#ifdef TK_LIC_PUB
    static const char pub[] = TK_LIC_PUB;
    BYTE blob[sizeof(BCRYPT_ECCKEY_BLOB) + 64], h[32];
    BCRYPT_ECCKEY_BLOB *hdr = (BCRYPT_ECCKEY_BLOB *)blob;
    BCRYPT_ALG_HANDLE a = NULL;
    BCRYPT_KEY_HANDLE k = NULL;
    NTSTATUS st = -1;
    int i;
    if (sizeof pub != 129) return FALSE;
    hdr->dwMagic = BCRYPT_ECDSA_PUBLIC_P256_MAGIC;
    hdr->cbKey = 32;
    for (i = 0; i < 64; i++) {
        int hi = HexVal(pub[2 * i]), lo = HexVal(pub[2 * i + 1]);
        if (hi < 0 || lo < 0) return FALSE;
        blob[sizeof(BCRYPT_ECCKEY_BLOB) + i] = (BYTE)(hi * 16 + lo);
    }
    if (!Sha256(msg, len, h)) return FALSE;
    if (BCryptOpenAlgorithmProvider(&a, BCRYPT_ECDSA_P256_ALGORITHM, NULL, 0)) return FALSE;
    if (!BCryptImportKeyPair(a, NULL, BCRYPT_ECCPUBLIC_BLOB, &k, blob, sizeof blob, 0)) {
        st = BCryptVerifySignature(k, NULL, h, 32, (PUCHAR)sig, 64, 0);
        BCryptDestroyKey(k);
    }
    BCryptCloseAlgorithmProvider(a, 0);
    return st == 0;
#else
    (void)msg; (void)len; (void)sig;
    return FALSE;
#endif
}

/* ------------------------------------------------------------------ codul calculatorului */
void Lic_Machine(wchar_t *out, BOOL grouped)
{
    wchar_t guid[64] = L"", win[MAX_PATH] = L"C:\\", root[4], src[160];
    char u8[400];
    DWORD serial = 0, cb = sizeof guid - sizeof(wchar_t), type = 0;
    BYTE h[32];
    HKEY k;
    int i, n;
    if (!RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Cryptography", 0, KEY_READ | KEY_WOW64_64KEY, &k)) {
        if (RegQueryValueExW(k, L"MachineGuid", NULL, &type, (BYTE *)guid, &cb) || type != REG_SZ) guid[0] = 0;
        RegCloseKey(k);
    }
    guid[63] = 0;
    _wcslwr(guid);
    GetSystemWindowsDirectoryW(win, MAX_PATH);
    lstrcpynW(root, win, 4);                    /* "C:\" */
    GetVolumeInformationW(root, NULL, 0, &serial, NULL, NULL, NULL, 0);
    swprintf(src, 160, L"TopoKit/1|%ls|%08lX", guid, (unsigned long)serial);
    n = WideCharToMultiByte(CP_UTF8, 0, src, -1, u8, sizeof u8, NULL, NULL) - 1;
    if (n < 0 || !Sha256(u8, (DWORD)n, h)) memset(h, 0, sizeof h);
    for (i = 0, n = 0; i < 12; i++) {
        if (grouped && i && i % 3 == 0) out[n++] = L'-';
        n += swprintf(out + n, 4, L"%02X", h[i]);
    }
    out[n] = 0;
}

/* ------------------------------------------------------------------ base64url si JSON simplu */
static int B64uDec(const char *s, int len, BYTE *out, int cap)
{
    int i, n = 0, bits = 0, v;
    unsigned acc = 0;
    for (i = 0; i < len; i++) {
        int c = s[i];
        v = c >= 'A' && c <= 'Z' ? c - 'A' : c >= 'a' && c <= 'z' ? c - 'a' + 26 : c >= '0' && c <= '9' ? c - '0' + 52 :
            c == '-' ? 62 : c == '_' ? 63 : c == '=' ? -2 : -1;
        if (v == -2) break;
        if (v < 0) return -1;
        acc = (acc << 6) | (unsigned)v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            if (n >= cap) return -1;
            out[n++] = (BYTE)(acc >> bits);
        }
    }
    return n;
}

/* valoarea cheii "key" dintr-un obiect JSON plat (cheile cautate nu apar in alte siruri:
 * ghilimelele din valori sunt mereu precedate de "\") */
static const char *JsonFind(const char *j, const char *key)
{
    size_t n = strlen(key);
    const char *p = j;
    while ((p = strchr(p, '"')) != NULL) {
        if ((p == j || p[-1] != '\\') && !strncmp(p + 1, key, n) && p[1 + n] == '"') {
            const char *q = p + 2 + n;
            while (*q == ' ' || *q == '\t' || *q == '\r' || *q == '\n') q++;
            if (*q == ':') {
                q++;
                while (*q == ' ' || *q == '\t' || *q == '\r' || *q == '\n') q++;
                return q;
            }
        }
        p++;
    }
    return NULL;
}

static BOOL JsonStr(const char *j, const char *key, char *out, int cap)
{
    const char *p = JsonFind(j, key);
    int n = 0;
    if (!p || *p != '"' || cap < 1) return FALSE;
    for (p++; *p && *p != '"'; p++) {
        unsigned cp = (unsigned char)*p;
        if (*p == '\\') {
            p++;
            switch (*p) {
            case 'n': cp = '\n'; break;
            case 't': cp = '\t'; break;
            case 'r': cp = '\r'; break;
            case 'b': cp = '\b'; break;
            case 'f': cp = '\f'; break;
            case 'u': {
                int i, d;
                cp = 0;
                for (i = 1; i <= 4; i++) {
                    if ((d = HexVal(p[i])) < 0) return FALSE;
                    cp = cp * 16 + (unsigned)d;
                }
                p += 4;
                if (cp >= 0xD800 && cp < 0xDC00 && p[1] == '\\' && p[2] == 'u') {     /* pereche surogat */
                    unsigned lo = 0;
                    for (i = 3; i <= 6; i++) {
                        if ((d = HexVal(p[i])) < 0) return FALSE;
                        lo = lo * 16 + (unsigned)d;
                    }
                    if (lo >= 0xDC00 && lo < 0xE000) { cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00); p += 6; }
                }
                break;
            }
            case 0: return FALSE;
            default: cp = (unsigned char)*p;
            }
            /* cod Unicode -> UTF-8 */
            if (cp < 0x80) { if (n + 1 >= cap) return FALSE; out[n++] = (char)cp; }
            else if (cp < 0x800) { if (n + 2 >= cap) return FALSE; out[n++] = (char)(0xC0 | cp >> 6); out[n++] = (char)(0x80 | (cp & 63)); }
            else if (cp < 0x10000) {
                if (n + 3 >= cap) return FALSE;
                out[n++] = (char)(0xE0 | cp >> 12); out[n++] = (char)(0x80 | ((cp >> 6) & 63)); out[n++] = (char)(0x80 | (cp & 63));
            } else {
                if (n + 4 >= cap) return FALSE;
                out[n++] = (char)(0xF0 | cp >> 18); out[n++] = (char)(0x80 | ((cp >> 12) & 63));
                out[n++] = (char)(0x80 | ((cp >> 6) & 63)); out[n++] = (char)(0x80 | (cp & 63));
            }
            continue;
        }
        if (n + 1 >= cap) return FALSE;
        out[n++] = *p;
    }
    if (*p != '"') return FALSE;
    out[n] = 0;
    return TRUE;
}

static BOOL JsonNum(const char *j, const char *key, long long *out)
{
    const char *p = JsonFind(j, key);
    char *end;
    if (!p) return FALSE;
    *out = strtoll(p, &end, 10);
    return end != p;
}

/* sir pentru JSON: doar caracterele sigure (coduri, ID-uri, nume de calculator) */
static void JsonSafe(const char *in, char *out, int cap)
{
    int n = 0;
    for (; *in && n + 1 < cap; in++)
        if ((unsigned char)*in >= 0x20 && *in != '"' && *in != '\\') out[n++] = *in;
    out[n] = 0;
}

/* ------------------------------------------------------------------ verificarea licentei */
static int CheckText(const char *text, LicInfo *li)
{
    char t[MAX_LIC], payload[MAX_LIC], s[160];
    BYTE sig[80];
    const char *d1, *d2;
    char *e;
    int n, len;
    long long v = 0;
    wchar_t mine[32], lic[32];
    memset(li, 0, sizeof *li);
    li->status = LIC_BAD;
    /* fara spatii la inceput / sfarsit */
    while (*text == ' ' || *text == '\r' || *text == '\n' || *text == '\t' || (unsigned char)*text == 0xEF ||
           (unsigned char)*text == 0xBB || (unsigned char)*text == 0xBF) text++;
    lstrcpynA(t, text, sizeof t);
    for (e = t + strlen(t); e > t && (e[-1] == ' ' || e[-1] == '\r' || e[-1] == '\n' || e[-1] == '\t'); e--) e[-1] = 0;
    if (!*t) { li->status = LIC_NONE; return LIC_NONE; }
    if (strncmp(t, "TK1.", 4) || !(d1 = t + 3) || !(d2 = strchr(d1 + 1, '.'))) return LIC_BAD;
    len = (int)(d2 - t);
    n = B64uDec(d1 + 1, (int)(d2 - d1 - 1), (BYTE *)payload, sizeof payload - 1);
    if (n <= 0) return LIC_BAD;
    payload[n] = 0;
    if (B64uDec(d2 + 1, (int)strlen(d2 + 1), sig, sizeof sig) != 64) return LIC_BAD;
    if (!VerifySig(t, (DWORD)len, sig)) return LIC_BAD;
    if (!JsonNum(payload, "v", &v) || v != 1) return LIC_BAD;
    if (!JsonStr(payload, "kid", s, sizeof s) || strcmp(s, TK_LIC_KID)) return LIC_BAD;
    JsonNum(payload, "iat", &li->iat);
    JsonNum(payload, "exp", &li->exp);
    if (JsonStr(payload, "name", s, sizeof s)) MultiByteToWideChar(CP_UTF8, 0, s, -1, li->name, 128);
    if (JsonStr(payload, "lid", s, sizeof s)) MultiByteToWideChar(CP_UTF8, 0, s, -1, li->lid, 64);
    if (!JsonStr(payload, "machine", s, sizeof s)) return LIC_BAD;
    MultiByteToWideChar(CP_UTF8, 0, s, -1, lic, 32);
    Lic_Machine(mine, FALSE);
    if (_wcsicmp(mine, lic)) return li->status = LIC_PC;
    if (Lic_Now() >= li->exp) return li->status = LIC_EXPIRED;
    if (Lic_Now() + 86400 < li->iat) return li->status = LIC_CLOCK;      /* ceasul dat mult inapoi */
    return li->status = LIC_OK;
}

int Lic_Check(const wchar_t *file, LicInfo *li)
{
    wchar_t p[MAX_PATH];
    char text[MAX_LIC];
    memset(li, 0, sizeof *li);
    li->status = LIC_NONE;
    if (LicPath(L"state.dat", p)) li->device = GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES;
    if (!file) {
        if (!LicPath(L"license.lic", p)) return LIC_NONE;
        file = p;
    }
    if (ReadAll(file, text, sizeof text) < 0) return LIC_NONE;
    {
        BOOL dev = li->device;
        int st = CheckText(text, li);
        li->device = dev;
        return st;
    }
}

const wchar_t *Lic_StatusText(int status)
{
    switch (status) {
    case LIC_OK: return TR(L"Licență activă", L"Active licence");
    case LIC_NONE: return TR(L"TopoKit nu este activat pe acest calculator", L"TopoKit is not activated on this computer");
    case LIC_PC: return TR(L"Licența este pentru alt calculator", L"The licence is for another computer");
    case LIC_EXPIRED: return TR(L"Licența a expirat", L"The licence has expired");
    case LIC_CLOCK: return TR(L"Data calculatorului este greșită", L"The computer date is wrong");
    default: return TR(L"Fișierul de licență nu este valid", L"The licence file is not valid");
    }
}

void Lic_FormatDate(long long t, wchar_t *out, int cch)
{
    ULARGE_INTEGER u;
    FILETIME ft, lt;
    SYSTEMTIME st;
    u.QuadPart = (ULONGLONG)(t + 11644473600LL) * 10000000ULL;
    ft.dwLowDateTime = u.LowPart;
    ft.dwHighDateTime = u.HighPart;
    FileTimeToLocalFileTime(&ft, &lt);
    FileTimeToSystemTime(&lt, &st);
    swprintf(out, cch, L"%02u.%02u.%04u", st.wDay, st.wMonth, st.wYear);
}

/* ------------------------------------------------------------------ state.dat (DPAPI) */
static const BYTE ENTROPY[] = "TopoKit licenta";

static BOOL SaveState(const char *device, const char *secret)
{
    char plain[400];
    DATA_BLOB in, out, ent = { sizeof ENTROPY - 1, (BYTE *)ENTROPY };
    wchar_t p[MAX_PATH];
    BOOL ok = FALSE;
    int n = snprintf(plain, sizeof plain, "%s\n%s\n", device, secret);
    if (n <= 0 || n >= (int)sizeof plain || !LicPath(L"state.dat", p)) return FALSE;
    in.pbData = (BYTE *)plain;
    in.cbData = (DWORD)n;
    if (CryptProtectData(&in, L"TopoKit", &ent, NULL, NULL, CRYPTPROTECT_UI_FORBIDDEN, &out)) {
        ok = WriteAll(p, out.pbData, out.cbData);
        LocalFree(out.pbData);
    }
    SecureZeroMemory(plain, sizeof plain);
    return ok;
}

static BOOL LoadState(char *device, int dcap, char *secret, int scap)
{
    BYTE buf[2048];
    DATA_BLOB in, out, ent = { sizeof ENTROPY - 1, (BYTE *)ENTROPY };
    wchar_t p[MAX_PATH];
    char *nl;
    int n;
    BOOL ok = FALSE;
    if (!LicPath(L"state.dat", p) || (n = ReadAll(p, (char *)buf, sizeof buf)) <= 0) return FALSE;
    in.pbData = buf;
    in.cbData = (DWORD)n;
    if (!CryptUnprotectData(&in, NULL, &ent, NULL, NULL, CRYPTPROTECT_UI_FORBIDDEN, &out)) return FALSE;
    if (out.cbData < 400) {
        char plain[400];
        memcpy(plain, out.pbData, out.cbData);
        plain[out.cbData] = 0;
        if ((nl = strchr(plain, '\n')) != NULL) {
            *nl = 0;
            lstrcpynA(device, plain, dcap);
            lstrcpynA(secret, nl + 1, scap);
            if ((nl = strchr(secret, '\n')) != NULL) *nl = 0;
            ok = device[0] && secret[0];
        }
        SecureZeroMemory(plain, sizeof plain);
    }
    SecureZeroMemory(out.pbData, out.cbData);
    LocalFree(out.pbData);
    return ok;
}

/* ------------------------------------------------------------------ HTTP (WinHTTP, proxy-ul sistemului) */
static BOOL ServerUrl(wchar_t *out, int cch)
{
    DWORD n = GetEnvironmentVariableW(L"TOPOKIT_LICSERVER", out, (DWORD)cch);
    if (!n || n >= (DWORD)cch) lstrcpynW(out, WIDEN(TK_LIC_URL), cch);
    return out[0] != 0;
}

/* POST JSON; intoarce codul HTTP (0 = fara raspuns) */
static DWORD HttpPost(const wchar_t *path, const char *body, char *resp, int cap)
{
    wchar_t url[600], host[256], upath[600];
    URL_COMPONENTS uc;
    HINTERNET s = NULL, c = NULL, r = NULL;
    DWORD status = 0, sz = sizeof status, got;
    int n = 0;
    resp[0] = 0;
    if (!ServerUrl(url, 300)) return 0;
    lstrcatW(url, path);
    memset(&uc, 0, sizeof uc);
    uc.dwStructSize = sizeof uc;
    uc.lpszHostName = host;
    uc.dwHostNameLength = 256;
    uc.lpszUrlPath = upath;
    uc.dwUrlPathLength = 600;
    if (!WinHttpCrackUrl(url, 0, 0, &uc)) return 0;
    s = WinHttpOpen(L"TopoKit/" WIDEN(TK_VERSION), WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_NO_PROXY_NAME,
                    WINHTTP_NO_PROXY_BYPASS, 0);
    if (!s) s = WinHttpOpen(L"TopoKit/" WIDEN(TK_VERSION), WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME,
                            WINHTTP_NO_PROXY_BYPASS, 0);
    if (!s) return 0;
    WinHttpSetTimeouts(s, 6000, 6000, 8000, 12000);
    if ((c = WinHttpConnect(s, host, uc.nPort, 0)) != NULL &&
        (r = WinHttpOpenRequest(c, L"POST", upath, NULL, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                uc.nScheme == INTERNET_SCHEME_HTTPS ? WINHTTP_FLAG_SECURE : 0)) != NULL &&
        WinHttpSendRequest(r, L"Content-Type: application/json\r\n", (DWORD)-1, (LPVOID)body, (DWORD)strlen(body),
                           (DWORD)strlen(body), 0) &&
        WinHttpReceiveResponse(r, NULL) &&
        WinHttpQueryHeaders(r, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_HEADER_NAME_BY_INDEX,
                            &status, &sz, WINHTTP_NO_HEADER_INDEX)) {
        while (n < cap - 1 && WinHttpReadData(r, resp + n, (DWORD)(cap - 1 - n), &got) && got) n += (int)got;
        resp[n] = 0;
    }
    if (r) WinHttpCloseHandle(r);
    if (c) WinHttpCloseHandle(c);
    WinHttpCloseHandle(s);
    return status;
}

static void ErrorText(DWORD status, const char *resp, wchar_t *msg, int cch)
{
    char e[64] = "";
    JsonStr(resp, "error", e, sizeof e);
    if (!status)
        lstrcpynW(msg, TR(L"Serverul de licențe nu răspunde – verificați conexiunea la internet.",
                          L"The licence server does not answer – check the internet connection."), cch);
    else if (!strcmp(e, "code_invalid"))
        lstrcpynW(msg, TR(L"Codul de activare este greșit.", L"The activation code is wrong."), cch);
    else if (!strcmp(e, "code_used"))
        lstrcpynW(msg, TR(L"Codul a fost deja folosit – cereți un cod nou administratorului.",
                          L"The code was already used – ask the administrator for a new one."), cch);
    else if (!strcmp(e, "code_expired"))
        lstrcpynW(msg, TR(L"Codul a expirat – cereți un cod nou administratorului.",
                          L"The code has expired – ask the administrator for a new one."), cch);
    else if (!strcmp(e, "user_disabled"))
        lstrcpynW(msg, TR(L"Accesul la TopoKit a fost oprit de administrator.",
                          L"Access to TopoKit was stopped by the administrator."), cch);
    else if (!strcmp(e, "too_many_devices"))
        lstrcpynW(msg, TR(L"Ați atins numărul maxim de calculatoare – dezactivați TopoKit pe alt calculator sau "
                          L"cereți administratorului.",
                          L"You reached the maximum number of computers – deactivate TopoKit on another computer or "
                          L"ask the administrator."), cch);
    else if (!strcmp(e, "rate_limited"))
        lstrcpynW(msg, TR(L"Prea multe încercări – reîncercați peste o oră.", L"Too many attempts – try again in an hour."), cch);
    else if (!strcmp(e, "revoked") || !strcmp(e, "unknown_device") || !strcmp(e, "machine"))
        lstrcpynW(msg, TR(L"Activarea de pe acest calculator a fost anulată.",
                          L"The activation on this computer was cancelled."), cch);
    else
        swprintf(msg, cch, TR(L"Eroare la serverul de licențe (%lu %hs).", L"Licence server error (%lu %hs)."),
                 (unsigned long)status, e);
}

static void ComputerName(char *out, int cap)
{
    wchar_t w[MAX_COMPUTERNAME_LENGTH + 1];
    char u8[64];
    DWORD n = MAX_COMPUTERNAME_LENGTH + 1;
    if (!GetComputerNameW(w, &n)) lstrcpyW(w, L"?");
    WideCharToMultiByte(CP_UTF8, 0, w, -1, u8, sizeof u8, NULL, NULL);
    JsonSafe(u8, out, cap);
}

/* raspunsul serverului: licenta noua, verificata inainte de a fi salvata */
static BOOL StoreLicense(const char *resp, wchar_t *msg, int cch)
{
    char lic[MAX_LIC];
    wchar_t p[MAX_PATH];
    LicInfo li;
    int st;
    if (!JsonStr(resp, "license", lic, sizeof lic)) {
        lstrcpynW(msg, TR(L"Răspuns greșit de la serverul de licențe.", L"Wrong answer from the licence server."), cch);
        return FALSE;
    }
    if ((st = CheckText(lic, &li)) != LIC_OK) {
        lstrcpynW(msg, Lic_StatusText(st), cch);
        return FALSE;
    }
    lstrcatA(lic, "\r\n");
    if (!LicPath(L"license.lic", p) || !WriteAll(p, lic, (DWORD)strlen(lic))) {
        lstrcpynW(msg, TR(L"Nu pot salva licența.", L"Cannot save the licence."), cch);
        return FALSE;
    }
    return TRUE;
}

int Lic_Activate(const wchar_t *code, wchar_t *msg, int cch)
{
    char c[64], body[512], resp[MAX_LIC + 512], dev[128], sec[160], pc[64];
    wchar_t m[32];
    DWORD status;
    int i, n = 0;
    msg[0] = 0;
    for (i = 0; code[i] && n < 40; i++)               /* doar litere si cifre */
        if (iswalnum(code[i]) && code[i] < 128) c[n++] = (char)towupper(code[i]);
    c[n] = 0;
    if (n < 8) {
        lstrcpynW(msg, TR(L"Introduceți codul de activare primit de la administrator.",
                          L"Enter the activation code you received from the administrator."), cch);
        return LIC_NONE;
    }
    Lic_Machine(m, FALSE);
    ComputerName(pc, sizeof pc);
    snprintf(body, sizeof body, "{\"code\":\"%s\",\"machine\":\"%ls\",\"pc\":\"%s\",\"version\":\"%s\"}", c, m, pc,
             TK_VERSION);
    status = HttpPost(L"/api/activate", body, resp, sizeof resp);
    if (status != 200) {
        ErrorText(status, resp, msg, cch);
        return LIC_NONE;
    }
    if (!JsonStr(resp, "device", dev, sizeof dev) || !JsonStr(resp, "secret", sec, sizeof sec)) {
        lstrcpynW(msg, TR(L"Răspuns greșit de la serverul de licențe.", L"Wrong answer from the licence server."), cch);
        return LIC_BAD;
    }
    if (!StoreLicense(resp, msg, cch)) return LIC_BAD;
    if (!SaveState(dev, sec)) {
        lstrcpynW(msg, TR(L"Licența e salvată, dar nu se va putea reînnoi automat.",
                          L"The licence is saved but cannot be renewed automatically."), cch);
    }
    SecureZeroMemory(sec, sizeof sec);
    return LIC_OK;
}

int Lic_Refresh(wchar_t *msg, int cch)
{
    char dev[128], sec[160], d[128], body[640], resp[MAX_LIC + 512], e[64] = "";
    wchar_t m[32];
    DWORD status;
    msg[0] = 0;
    if (!LoadState(dev, sizeof dev, sec, sizeof sec)) return LIC_R_NODEVICE;
    Lic_Machine(m, FALSE);
    JsonSafe(dev, d, sizeof d);
    snprintf(body, sizeof body, "{\"device\":\"%s\",\"secret\":\"%s\",\"machine\":\"%ls\",\"version\":\"%s\"}", d, sec, m,
             TK_VERSION);
    SecureZeroMemory(sec, sizeof sec);
    status = HttpPost(L"/api/refresh", body, resp, sizeof resp);
    SecureZeroMemory(body, sizeof body);
    if (status == 200) return StoreLicense(resp, msg, cch) ? LIC_R_OK : LIC_R_NET;
    JsonStr(resp, "error", e, sizeof e);
    ErrorText(status, resp, msg, cch);
    if ((status == 403 || status == 404) && (!strcmp(e, "revoked") || !strcmp(e, "user_disabled") ||
                                             !strcmp(e, "unknown_device") || !strcmp(e, "machine"))) {
        DeleteLicFiles();                       /* accesul a fost oprit: licenta nu mai ramane */
        return LIC_R_REVOKED;
    }
    return LIC_R_NET;
}

int Lic_Deactivate(wchar_t *msg, int cch)
{
    char dev[128], sec[160], d[128], body[512], resp[1024], e[64] = "";
    DWORD status;
    msg[0] = 0;
    if (!LoadState(dev, sizeof dev, sec, sizeof sec)) {
        DeleteLicFiles();                       /* licenta offline: doar se sterge */
        return LIC_R_NODEVICE;
    }
    JsonSafe(dev, d, sizeof d);
    snprintf(body, sizeof body, "{\"device\":\"%s\",\"secret\":\"%s\"}", d, sec);
    SecureZeroMemory(sec, sizeof sec);
    status = HttpPost(L"/api/deactivate", body, resp, sizeof resp);
    SecureZeroMemory(body, sizeof body);
    JsonStr(resp, "error", e, sizeof e);
    if (status == 200 || ((status == 403 || status == 404) && e[0])) {
        DeleteLicFiles();
        return status == 200 ? LIC_R_OK : LIC_R_REVOKED;
    }
    ErrorText(status, resp, msg, cch);
    return LIC_R_NET;
}

BOOL Lic_Import(const wchar_t *file, wchar_t *msg, int cch)
{
    char text[MAX_LIC];
    wchar_t p[MAX_PATH];
    LicInfo li;
    int st;
    if (ReadAll(file, text, sizeof text) <= 0) {
        lstrcpynW(msg, TR(L"Nu pot citi fișierul.", L"Cannot read the file."), cch);
        return FALSE;
    }
    if ((st = CheckText(text, &li)) != LIC_OK) {
        lstrcpynW(msg, Lic_StatusText(st), cch);
        return FALSE;
    }
    if (!LicPath(L"license.lic", p) || !WriteAll(p, text, (DWORD)strlen(text))) {
        lstrcpynW(msg, TR(L"Nu pot salva licența.", L"Cannot save the licence."), cch);
        return FALSE;
    }
    return TRUE;
}
