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
 *
 * Ceasul dat inapoi: pe langa "iat" din licenta (data serverului, semnata), lansatorul tine minte
 * cea mai mare ora vazuta cu o licenta buna (seen.dat in folderul licentei + o copie in
 * HKCU\Software\TopoKit\LicSeen, ambele DPAPI). Ceasul mai mult de o zi in urma acelei ore =
 * LIC_CLOCK; o reinnoire reusita (data serverului) corecteaza o ora gresita ramasa din viitor.
 *
 * Doar in build-urile de test (-DTK_LIC_TESTENV): TOPOKIT_LICDIR (alt folder pentru license.lic /
 * state.dat / seen.dat), TOPOKIT_LICSERVER (alt server) si TOPOKIT_LICREG (cheia HKCU pentru
 * copia orei vazute; fara ea nu se scrie in registru). Build-ul de livrare le ignora.
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
#define LIC_SEEN_TOL (24 * 3600)        /* ceasul poate fi cu cel mult o zi in urma orei vazute */
#define LIC_SEEN_STEP 3600              /* ora vazuta se scrie cel mult o data pe ora */
#define LIC_LOCK_MS 120000              /* asteptarea dupa alta operatie cu licenta (alt fir / proces) */
#define LIC_SEEN_LOCK_MS 250            /* ora vazuta: asteptare scurta, apoi se scrie oricum */
#define LIC_RETRY_S 3600                /* dupa o reinnoire esuata (fara retea): fara alta incercare automata 1 h */

#ifdef TK_LIC_PUB
/* o cheie gresita la compilare nu are voie sa dezactiveze in tacere licentierea */
_Static_assert(sizeof(TK_LIC_PUB) == 129, "TK_LIC_PUB = 128 cifre hex (X||Y, P-256)");
#endif

BOOL Lic_Enabled(void)
{
#ifdef TK_LIC_PUB
    return TRUE;
#else
    return FALSE;
#endif
}

/* variabilele de mediu pentru teste; in build-ul de livrare nu exista */
static DWORD TestEnv(const wchar_t *name, wchar_t *out, DWORD cch)
{
#ifdef TK_LIC_TESTENV
    DWORD n = GetEnvironmentVariableW(name, out, cch);
    return n < cch ? n : 0;
#else
    (void)name; (void)out; (void)cch;
    return 0;
#endif
}

/* Operatiile care scriu licenta (activare, reinnoire, dezactivare, import) nu se suprapun: firul de
 * reinnoire al lansatorului, fereastra licentei si "TopoKit.exe /license" pornit din AutoCAD. */
static HANDLE LicLock(DWORD ms)
{
    HANDLE m = CreateMutexW(NULL, FALSE, L"Local\\TopoKitLicense");
    DWORD w;
    if (!m) return NULL;
    w = WaitForSingleObject(m, ms);
    if (w == WAIT_OBJECT_0 || w == WAIT_ABANDONED) return m;
    CloseHandle(m);
    return NULL;
}

static void LicUnlock(HANDLE m)
{
    if (!m) return;
    ReleaseMutex(m);
    CloseHandle(m);
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
    int n;
    if (!TestEnv(L"TOPOKIT_LICDIR", d, MAX_PATH)) {
        if (FAILED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA | CSIDL_FLAG_CREATE, NULL, 0, d))) return FALSE;
        if (wcslen(d) + 9 >= MAX_PATH) return FALSE;
        wcscat(d, L"\\TopoKit");
    }
    CreateDirectoryW(d, NULL);
    n = swprintf(out, MAX_PATH, L"%ls\\%ls", d, name);
    return n > 0 && n < MAX_PATH;
}

/* citire fara a bloca inlocuirea fisierului (MoveFileEx) de catre alt proces */
static int ReadAll(const wchar_t *path, char *buf, int cap)
{
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL,
                           OPEN_EXISTING, 0, NULL);
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
    int k = swprintf(tmp, MAX_PATH + 8, L"%ls.tmp", path);
    if (k <= 0 || k >= MAX_PATH + 8) return FALSE;
    h = CreateFileW(tmp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return FALSE;
    ok = WriteFile(h, data, len, &n, NULL) && n == len && FlushFileBuffers(h);
    CloseHandle(h);
    if (ok && MoveFileExW(tmp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) return TRUE;
    DeleteFileW(tmp);
    return FALSE;
}

/* ------------------------------------------------------------------ pauza dupa o reinnoire esuata
 * refresh.dat = "TKR1 <ora ultimei reinnoiri esuate>". Fara internet, aproape de expirare, incarcatorul
 * si cele 6 module rulau fiecare "/license" cu reinnoire sincrona (AutoCAD astepta de 7 ori dupa
 * server). Acum, dupa un esec, liniile de comanda nu mai incearca reteaua o ora (Lic_RefreshBackoff).
 * Fisierul nu e secret: modificat, poate doar amana reinnoirea pe acest calculator. */
static long long FailGet(void)
{
    wchar_t p[MAX_PATH];
    char s[48];
    if (!LicPath(L"refresh.dat", p) || ReadAll(p, s, sizeof s) <= 5 || strncmp(s, "TKR1 ", 5)) return 0;
    return strtoll(s + 5, NULL, 10);
}

static void FailPut(long long t)
{
    wchar_t p[MAX_PATH];
    char s[48];
    int n = snprintf(s, sizeof s, "TKR1 %lld\r\n", t);
    if (n > 0 && n < (int)sizeof s && LicPath(L"refresh.dat", p)) WriteAll(p, s, (DWORD)n);
}

static void FailClear(void)
{
    wchar_t p[MAX_PATH];
    if (LicPath(L"refresh.dat", p)) DeleteFileW(p);
}

BOOL Lic_RefreshBackoff(void)
{
    long long t = FailGet(), now = Lic_Now();
    return t > 0 && t <= now && now - t < LIC_RETRY_S;          /* o ora din viitor (ceas mutat) nu conteaza */
}

/* Reinnoirea automata din liniile de comanda (AutoCAD asteapta raspunsul): doar daca e nevoie (licenta
 * lipsa / stricata / expirata / ceasul gresit, sau expira in < 3 zile si e mai veche de 20 h), doar cu
 * state.dat si nu in ora de dupa o reinnoire esuata. Lic_RefreshEx(LIC_RF_CLI) o verifica din nou dupa
 * mutex (alt proces poate sa fi reinnoit / esuat intre timp). */
BOOL Lic_NeedsRefresh(int code, const LicInfo *li)
{
    long long now = Lic_Now();
    if (!li->device || Lic_RefreshBackoff()) return FALSE;
    if (code == LIC_OK) return li->exp - now < 3 * 86400 && now - li->iat >= 20 * 3600;
    return code == LIC_NONE || code == LIC_EXPIRED || code == LIC_BAD || code == LIC_CLOCK;
}

static void DeleteLicFiles(void)
{
    wchar_t p[MAX_PATH];
    if (LicPath(L"license.lic", p)) DeleteFileW(p);
    if (LicPath(L"state.dat", p)) DeleteFileW(p);
    FailClear();
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
        if (v == -2) {                          /* "=" doar la sfarsit */
            for (; i < len; i++)
                if (s[i] != '=') return -1;
            break;
        }
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
            if (!cp) return FALSE;              /* \u0000 ar scurta sirul */
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

/* identificatorii dati de server (dispozitiv, secret): doar litere, cifre, "-" si "_" */
static BOOL Token(const char *s)
{
    if (!*s) return FALSE;
    for (; *s; s++)
        if (!((*s >= 'A' && *s <= 'Z') || (*s >= 'a' && *s <= 'z') || (*s >= '0' && *s <= '9') || *s == '-' || *s == '_'))
            return FALSE;
    return TRUE;
}

/* UTF-8 -> UTF-16, mereu terminat cu 0 (trunchiat daca nu incape) */
static void U8ToW(const char *s, wchar_t *out, int cch)
{
    wchar_t w[600];
    if (!MultiByteToWideChar(CP_UTF8, 0, s, -1, w, 600)) w[0] = 0;
    w[599] = 0;
    lstrcpynW(out, w, cch);
}

/* ------------------------------------------------------------------ verificarea licentei */
/* textul licentei fara spatii / BOM la inceput si sfarsit */
static void Trim(const char *text, char *t, int cap)
{
    char *e;
    while (*text == ' ' || *text == '\r' || *text == '\n' || *text == '\t' || (unsigned char)*text == 0xEF ||
           (unsigned char)*text == 0xBB || (unsigned char)*text == 0xBF) text++;
    lstrcpynA(t, text, cap);
    for (e = t + strlen(t); e > t && (e[-1] == ' ' || e[-1] == '\r' || e[-1] == '\n' || e[-1] == '\t'); e--) e[-1] = 0;
}

/* Semnatura, versiunea, kid, calculatorul, expirarea si data emiterii - la fiecare citire a licentei,
 * nu doar la activare. */
static int CheckText(const char *text, LicInfo *li)
{
    char t[MAX_LIC], payload[MAX_LIC], s[512];
    BYTE sig[80];
    const char *d1, *d2;
    int n, len;
    long long v = 0, now;
    wchar_t mine[32];
    char mine8[32];
    memset(li, 0, sizeof *li);
    li->status = LIC_BAD;
    Trim(text, t, sizeof t);
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
    if (!JsonNum(payload, "iat", &li->iat) || !JsonNum(payload, "exp", &li->exp)) return LIC_BAD;
    if (JsonStr(payload, "name", s, sizeof s)) U8ToW(s, li->name, 128);
    if (JsonStr(payload, "lid", s, sizeof s)) U8ToW(s, li->lid, 64);
    if (!JsonStr(payload, "machine", s, sizeof s)) return LIC_BAD;
    Lic_Machine(mine, FALSE);
    WideCharToMultiByte(CP_UTF8, 0, mine, -1, mine8, sizeof mine8, NULL, NULL);
    mine8[24] = 0;
    if (strlen(s) != 24 || _stricmp(mine8, s)) return li->status = LIC_PC;
    now = Lic_Now();
    if (now >= li->exp) return li->status = LIC_EXPIRED;
    if (now + 86400 < li->iat) return li->status = LIC_CLOCK;       /* ceasul dat mult inapoi */
    return li->status = LIC_OK;
}

/* ------------------------------------------------------------------ ora cea mai mare vazuta (DPAPI) */
static const BYTE SEEN_ENT[] = "TopoKit ora";

/* cheia HKCU pentru copia din registru; in build-ul de test doar daca s-a dat TOPOKIT_LICREG */
static BOOL SeenRegKey(wchar_t *key, DWORD cch)
{
    if (TestEnv(L"TOPOKIT_LICREG", key, cch)) return TRUE;
#ifdef TK_LIC_TESTENV
    return FALSE;
#else
    lstrcpynW(key, L"Software\\TopoKit", (int)cch);
    return TRUE;
#endif
}

static long long SeenDecode(const BYTE *b, DWORD n)
{
    DATA_BLOB in, out, ent = { sizeof SEEN_ENT - 1, (BYTE *)SEEN_ENT };
    long long t = 0;
    in.pbData = (BYTE *)b;
    in.cbData = n;
    if (n && CryptUnprotectData(&in, NULL, &ent, NULL, NULL, CRYPTPROTECT_UI_FORBIDDEN, &out)) {
        char s[40];
        if (out.cbData < sizeof s) {
            memcpy(s, out.pbData, out.cbData);
            s[out.cbData] = 0;
            if (!strncmp(s, "TKS1 ", 5)) t = strtoll(s + 5, NULL, 10);
        }
        LocalFree(out.pbData);
    }
    return t > 0 ? t : 0;
}

static long long SeenGet(void)
{
    BYTE buf[1024];
    wchar_t p[MAX_PATH], key[MAX_PATH];
    HKEY k;
    DWORD cb, type;
    int n;
    long long a = 0, b = 0;
    if (LicPath(L"seen.dat", p) && (n = ReadAll(p, (char *)buf, sizeof buf)) > 0) a = SeenDecode(buf, (DWORD)n);
    if (SeenRegKey(key, MAX_PATH) && !RegOpenKeyExW(HKEY_CURRENT_USER, key, 0, KEY_QUERY_VALUE, &k)) {
        cb = sizeof buf;
        if (!RegQueryValueExW(k, L"LicSeen", NULL, &type, buf, &cb) && type == REG_BINARY) b = SeenDecode(buf, cb);
        RegCloseKey(k);
    }
    return a > b ? a : b;
}

static void SeenPut(long long t)
{
    char s[40];
    DATA_BLOB in, out, ent = { sizeof SEEN_ENT - 1, (BYTE *)SEEN_ENT };
    wchar_t p[MAX_PATH], key[MAX_PATH];
    HKEY k;
    int n = snprintf(s, sizeof s, "TKS1 %lld", t);
    if (n <= 0 || n >= (int)sizeof s) return;
    in.pbData = (BYTE *)s;
    in.cbData = (DWORD)n;
    if (!CryptProtectData(&in, L"TopoKit", &ent, NULL, NULL, CRYPTPROTECT_UI_FORBIDDEN, &out)) return;
    if (LicPath(L"seen.dat", p)) WriteAll(p, out.pbData, out.cbData);
    if (SeenRegKey(key, MAX_PATH) &&
        !RegCreateKeyExW(HKEY_CURRENT_USER, key, 0, NULL, 0, KEY_SET_VALUE, NULL, &k, NULL)) {
        RegSetValueExW(k, L"LicSeen", 0, REG_BINARY, out.pbData, out.cbData);
        RegCloseKey(k);
    }
    LocalFree(out.pbData);
}

/* Licenta din folderul implicit: ceasul dat inapoi fata de ora cea mai mare vazuta = LIC_CLOCK.
 * Ora vazuta creste doar cu o licenta buna (sau expirata de curand - ceasul dus mult inainte din
 * greseala nu blocheaza licenta pentru totdeauna). */
static void SeenCheck(LicInfo *li)
{
    long long now = Lic_Now(), seen;
    HANDLE m;
    if (li->status != LIC_OK && !(li->status == LIC_EXPIRED && now < li->exp + 30 * 86400LL)) return;
    seen = SeenGet();
    if (li->status == LIC_OK && seen && now + LIC_SEEN_TOL < seen) {
        li->status = LIC_CLOCK;
        return;
    }
    /* ora vazuta avanseaza si cand alt proces tine mutex-ul (altfel un proces care il tine blocat ar
     * ingheta ora vazuta): o asteptare scurta, apoi scrierea oricum - WriteAll inlocuieste atomic
     * (MoveFileEx), iar o cursa intre doua scrieri pierde cel mult cateva secunde */
    if (now > seen + LIC_SEEN_STEP) {
        m = LicLock(LIC_SEEN_LOCK_MS);
        SeenPut(now);
        LicUnlock(m);
    }
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
        CheckText(text, li);
        if (file == p) SeenCheck(li);           /* doar licenta instalata, nu un fisier dat */
        li->device = dev;
        return li->status;
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
    if (t < 0 || t > 253402300799LL) t = 253402300799LL;        /* 31.12.9999 (exp din licenta) */
    u.QuadPart = (ULONGLONG)(t + 11644473600LL) * 10000000ULL;
    ft.dwLowDateTime = u.LowPart;
    ft.dwHighDateTime = u.HighPart;
    if (!FileTimeToLocalFileTime(&ft, &lt) || !FileTimeToSystemTime(&lt, &st)) {
        lstrcpynW(out, L"?", cch);
        return;
    }
    swprintf(out, cch, L"%02u.%02u.%04u", st.wDay, st.wMonth, st.wYear);
}

/* ------------------------------------------------------------------ provocare-raspuns (/proof)
 * Secretul build-ului (32 de octeti) vine dintr-un antet generat la build (TK_PROOF_FILE, facut de
 * tools/lic_gate.py proof_header si sters dupa compilare - nu e in depozit si nu apare in linia de
 * comanda gcc): 8 bucati de 4 octeti in ordine amestecata (tk_pk_perm), fiecare octet mascat cu
 * PkMix(seed, bucata, pozitie). Cheia nu apare nici ca hex, nici ca 32 de octeti consecutivi.
 * Acelasi secret e in modulele AutoLISP (ca stari intermediare HMAC), ca sa poata verifica
 * raspunsul. Fara TK_PROOF_FILE (build fara licentiere) provocarea-raspuns e dezactivata. */
#if defined(TK_LIC_PUB) && defined(TK_PROOF_FILE)
#define TK_HAS_PROOF 1
#include TK_PROOF_FILE

/* aceeasi functie ca lic_gate._mix (Python) */
static BYTE PkMix(unsigned seed, unsigned c, unsigned j)
{
    unsigned x = seed ^ (c * 0x9E3779B9u) ^ (j * 0x85EBCA6Bu);
    x ^= x >> 15;
    x *= 0x2C1B3C6Du;
    x ^= x >> 12;
    x *= 0x297A2D39u;
    x ^= x >> 15;
    return (BYTE)(x >> 8);
}

static BOOL ProofKey(BYTE out[32])
{
    unsigned c, j;
    for (c = 0; c < 8; c++) {
        if (tk_pk_perm[c] > 7) return FALSE;
        for (j = 0; j < 4; j++)
            out[tk_pk_perm[c] * 4 + j] = (BYTE)(tk_pk_data[c * 4 + j] ^ PkMix(TK_PK_SEED, c, j));
    }
    return TRUE;
}

#ifndef BCRYPT_ALG_HANDLE_HMAC_FLAG
#define BCRYPT_ALG_HANDLE_HMAC_FLAG 0x00000008
#endif
static BOOL Hmac256(const BYTE *key, DWORD keylen, const char *msg, DWORD msglen, BYTE out[32])
{
    BCRYPT_ALG_HANDLE a = NULL;
    BCRYPT_HASH_HANDLE h = NULL;
    BOOL ok = FALSE;
    if (BCryptOpenAlgorithmProvider(&a, BCRYPT_SHA256_ALGORITHM, NULL, BCRYPT_ALG_HANDLE_HMAC_FLAG)) return FALSE;
    if (!BCryptCreateHash(a, &h, NULL, 0, (PUCHAR)key, keylen, 0)) {
        ok = !BCryptHashData(h, (PUCHAR)msg, msglen, 0) && !BCryptFinishHash(h, out, 32, 0);
        BCryptDestroyHash(h);
    }
    BCryptCloseAlgorithmProvider(a, 0);
    return ok;
}
#endif

BOOL Lic_ProofEnabled(void)
{
#ifdef TK_HAS_PROOF
    return TRUE;
#else
    return FALSE;
#endif
}

BOOL Lic_NonceOk(const char *nonce)
{
    size_t n = nonce ? strlen(nonce) : 0, i;
    if (n < 16 || n > 64) return FALSE;
    for (i = 0; i < n; i++) {
        char c = nonce[i];
        if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'))) return FALSE;
    }
    return TRUE;
}

BOOL Lic_Proof(int code, long long exp, const char *nonce, char *out, int cch)
{
#ifdef TK_HAS_PROOF
    BYTE key[32], mac[32];
    char msg[160], hex[65], mach8[32];
    wchar_t mach[32];
    static const char hx[] = "0123456789abcdef";
    int n, i;
    if (!Lic_NonceOk(nonce) || !ProofKey(key)) return FALSE;
    /* codul calculatorului in mesaj: un raspuns cerut pe alt calculator (releu) nu se potriveste -
     * modulul AutoLISP calculeaza singur codul (lic_gate.py), la fel ca Lic_Machine */
    Lic_Machine(mach, FALSE);
    WideCharToMultiByte(CP_UTF8, 0, mach, -1, mach8, sizeof mach8, NULL, NULL);
    mach8[24] = 0;
    n = snprintf(msg, sizeof msg, "TKP2|%s|%d|%lld|%s", nonce, code, exp, mach8);
    if (n <= 0 || n >= (int)sizeof msg || !Hmac256(key, 32, msg, (DWORD)n, mac)) {
        SecureZeroMemory(key, sizeof key);
        return FALSE;
    }
    SecureZeroMemory(key, sizeof key);
    SecureZeroMemory(msg, sizeof msg);
    for (i = 0; i < 32; i++) {
        hex[2 * i] = hx[mac[i] >> 4];
        hex[2 * i + 1] = hx[mac[i] & 15];
    }
    hex[64] = 0;
    /* al 5-lea camp: codul calculatorului din mesaj. Modulul AutoLISP il foloseste doar daca nu-l poate
     * calcula singur (Scripting.FileSystemObject indisponibil) - vezi lic_gate.py */
    n = snprintf(out, cch, "%d %lld %s %s %s\n", code, exp, nonce, hex, mach8);
    return n > 0 && n < cch;
#else
    (void)code; (void)exp; (void)nonce; (void)out; (void)cch;
    return FALSE;
#endif
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
    if (!TestEnv(L"TOPOKIT_LICSERVER", out, (DWORD)cch)) lstrcpynW(out, WIDEN(TK_LIC_URL), cch);
    return out[0] != 0;
}

/* POST JSON; intoarce codul HTTP (0 = fara raspuns). quick = linia de comanda: timpi scurti. */
static DWORD HttpPostRaw(const wchar_t *path, const char *body, char *resp, int cap, BOOL quick)
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
#ifndef TK_LIC_TESTENV
    if (uc.nScheme != INTERNET_SCHEME_HTTPS) return 0;      /* livrare: doar HTTPS */
#endif
    s = WinHttpOpen(L"TopoKit/" WIDEN(TK_VERSION), WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_NO_PROXY_NAME,
                    WINHTTP_NO_PROXY_BYPASS, 0);
    if (!s) s = WinHttpOpen(L"TopoKit/" WIDEN(TK_VERSION), WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME,
                            WINHTTP_NO_PROXY_BYPASS, 0);
    if (!s) return 0;
    if (quick) WinHttpSetTimeouts(s, 2500, 2500, 3000, 4000);
    else WinHttpSetTimeouts(s, 6000, 6000, 8000, 12000);
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

/* Cererea cu o limita totala de timp (linia de comanda: AutoCAD asteapta). Timpii WinHTTP limiteaza
 * fiecare pas, dar nu si suma lor (proxy WPAD, mai multe adrese, TLS); aici cererea ruleaza pe alt fir,
 * iar dupa limitesms raspunsul nu mai e asteptat (= fara raspuns). Firul ramas termina singur si
 * elibereaza contextul (numarator de referinte); procesul liniei de comanda se inchide oricum. */
typedef struct {
    LONG refs;
    const wchar_t *path;
    char *body, *resp;
    int cap;
    DWORD status;
} HttpJob;

static void HttpJobRelease(HttpJob *j)
{
    if (InterlockedDecrement(&j->refs)) return;
    SecureZeroMemory(j->body, strlen(j->body));
    SecureZeroMemory(j->resp, (size_t)j->cap);
    HeapFree(GetProcessHeap(), 0, j);
}

static DWORD WINAPI HttpJobThread(LPVOID p)
{
    HttpJob *j = (HttpJob *)p;
    j->status = HttpPostRaw(j->path, j->body, j->resp, j->cap, TRUE);
    HttpJobRelease(j);
    return 0;
}

static DWORD HttpPost(const wchar_t *path, const char *body, char *resp, int cap, DWORD limitms)
{
    HttpJob *j;
    HANDLE t;
    size_t bl = strlen(body) + 1;
    DWORD status = 0;
    if (!limitms) return HttpPostRaw(path, body, resp, cap, FALSE);
    resp[0] = 0;
    j = (HttpJob *)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof *j + bl + (size_t)cap);
    if (!j) return 0;
    j->refs = 2;
    j->path = path;                             /* sir constant */
    j->body = (char *)(j + 1);
    j->resp = j->body + bl;
    j->cap = cap;
    memcpy(j->body, body, bl);
    if (!(t = CreateThread(NULL, 0, HttpJobThread, j, 0, NULL))) {
        j->refs = 1;
        HttpJobRelease(j);
        return 0;
    }
    if (WaitForSingleObject(t, limitms) == WAIT_OBJECT_0) {
        status = j->status;
        memcpy(resp, j->resp, (size_t)cap);
        resp[cap - 1] = 0;
    }
    CloseHandle(t);
    HttpJobRelease(j);
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


static void WrongAnswer(wchar_t *msg, int cch)
{
    lstrcpynW(msg, TR(L"Răspuns greșit de la serverul de licențe.", L"Wrong answer from the licence server."), cch);
}

static void Busy(wchar_t *msg, int cch)
{
    lstrcpynW(msg, TR(L"Licența este folosită de altă operație – reîncercați.",
                      L"The licence is busy with another operation – try again."), cch);
}

/* licenta din raspunsul serverului, verificata complet (semnatura, kid, calculator, date);
 * -1 = raspuns fara licenta */
static int ServerLicense(const char *resp, char *lic, int cap, LicInfo *li)
{
    if (!JsonStr(resp, "license", lic, cap)) return -1;
    return CheckText(lic, li);
}

/* scrie licenta verificata (doar textul ei, fara spatiile din jur) in license.lic */
static BOOL SaveLicense(const char *lic, wchar_t *msg, int cch)
{
    char t[MAX_LIC + 2];
    wchar_t p[MAX_PATH];
    Trim(lic, t, MAX_LIC);
    strcat(t, "\r\n");                          /* strlen(t) <= MAX_LIC - 1 */
    if (!LicPath(L"license.lic", p) || !WriteAll(p, t, (DWORD)strlen(t))) {
        lstrcpynW(msg, TR(L"Nu pot salva licența.", L"Cannot save the licence."), cch);
        return FALSE;
    }
    return TRUE;
}

/* licenta noua de la server (data serverului, semnata): o ora vazuta ramasa din viitor (ceasul fusese
 * dus inainte din greseala) se corecteaza */
static void SeenFromServer(const LicInfo *li)
{
    if (SeenGet() > li->iat + LIC_SEEN_TOL) SeenPut(li->iat);
}

int Lic_Activate(const wchar_t *code, wchar_t *msg, int cch)
{
    char c[64], body[512], resp[MAX_LIC + 512], dev[128], sec[160], pc[64], lic[MAX_LIC];
    wchar_t m[32];
    LicInfo li;
    HANDLE lk;
    DWORD status;
    int i, n = 0, st = LIC_BAD, r;
    BOOL saved;
    msg[0] = 0;
    for (i = 0; code[i] && n < 40; i++)               /* doar litere si cifre */
        if (iswalnum(code[i]) && code[i] < 128) c[n++] = (char)towupper(code[i]);
    c[n] = 0;
    if (n < 8) {
        lstrcpynW(msg, TR(L"Introduceți codul de activare primit de la administrator.",
                          L"Enter the activation code you received from the administrator."), cch);
        return LIC_NONE;
    }
    if (!(lk = LicLock(LIC_LOCK_MS))) {
        Busy(msg, cch);
        return LIC_NONE;
    }
    Lic_Machine(m, FALSE);
    ComputerName(pc, sizeof pc);
    snprintf(body, sizeof body, "{\"code\":\"%s\",\"machine\":\"%ls\",\"pc\":\"%s\",\"version\":\"%s\"}", c, m, pc,
             TK_VERSION);
    status = HttpPost(L"/api/activate", body, resp, sizeof resp, 0);
    sec[0] = 0;
    if (status != 200) {
        ErrorText(status, resp, msg, cch);
        r = LIC_NONE;
    } else if (!JsonStr(resp, "device", dev, sizeof dev) || !JsonStr(resp, "secret", sec, sizeof sec) ||
               !Token(dev) || !Token(sec) || (st = ServerLicense(resp, lic, sizeof lic, &li)) < 0) {
        WrongAnswer(msg, cch);
        r = LIC_BAD;
    } else {
        /* codul e consumat pe server: cu ceasul gresit dispozitivul se pastreaza totusi, ca licenta
         * sa se poata lua cu "Reinnoieste" dupa corectarea datei (altfel trebuia un cod nou) */
        saved = (st == LIC_OK || st == LIC_CLOCK) && SaveState(dev, sec);
        if (st != LIC_OK) {
            lstrcpynW(msg, Lic_StatusText(st), cch);
            r = st;
        } else if (!SaveLicense(lic, msg, cch)) {
            r = LIC_BAD;
        } else {
            SeenFromServer(&li);
            FailClear();
            if (!saved)
                lstrcpynW(msg, TR(L"Licența e salvată, dar nu se va putea reînnoi automat.",
                                  L"The licence is saved but cannot be renewed automatically."), cch);
            r = LIC_OK;
        }
    }
    SecureZeroMemory(sec, sizeof sec);
    SecureZeroMemory(resp, sizeof resp);
    LicUnlock(lk);
    return r;
}

int Lic_Refresh(wchar_t *msg, int cch)
{
    return Lic_RefreshEx(msg, cch, LIC_LOCK_MS, 0);
}

int Lic_RefreshEx(wchar_t *msg, int cch, DWORD lockms, int flags)
{
    char dev[128], sec[160], d[128], body[640], resp[MAX_LIC + 512], e[64] = "", lic[MAX_LIC];
    wchar_t m[32];
    LicInfo li;
    HANDLE lk;
    DWORD status, t0 = GetTickCount(), netms = 0, used;
    int st, r;
    msg[0] = 0;
    if (!(lk = LicLock(lockms))) {
        Busy(msg, cch);
        return LIC_R_NET;
    }
    if (flags & LIC_RF_CLI) {
        /* dupa asteptarea mutex-ului: alt proces (lansatorul, alt modul) poate sa fi reinnoit licenta sau
         * sa fi esuat intre timp - atunci fara retea. Restul timpului (lockms) e limita cererii HTTP. */
        if (!Lic_NeedsRefresh(Lic_Check(NULL, &li), &li)) {
            LicUnlock(lk);
            return !li.device ? LIC_R_NODEVICE : Lic_RefreshBackoff() ? LIC_R_NET : LIC_R_OK;
        }
        used = GetTickCount() - t0;
        if (used + 1500 > lockms) {             /* prea putin timp ramas: data viitoare */
            LicUnlock(lk);
            Busy(msg, cch);
            return LIC_R_NET;
        }
        netms = lockms - used;
    }
    if (!LoadState(dev, sizeof dev, sec, sizeof sec)) {
        LicUnlock(lk);
        return LIC_R_NODEVICE;
    }
    Lic_Machine(m, FALSE);
    JsonSafe(dev, d, sizeof d);
    JsonSafe(sec, sec, sizeof sec);
    snprintf(body, sizeof body, "{\"device\":\"%s\",\"secret\":\"%s\",\"machine\":\"%ls\",\"version\":\"%s\"}", d, sec, m,
             TK_VERSION);
    SecureZeroMemory(sec, sizeof sec);
    status = HttpPost(L"/api/refresh", body, resp, sizeof resp, netms);
    SecureZeroMemory(body, sizeof body);
    if (status == 200) {
        /* orice licenta primita trece prin aceeasi verificare ca la citire: un server fals sau un
         * raspuns modificat nu poate da o licenta pentru alt calculator, expirata sau nesemnata */
        st = ServerLicense(resp, lic, sizeof lic, &li);
        if (st < 0) {
            WrongAnswer(msg, cch);
            r = LIC_R_NET;
        } else if (st != LIC_OK) {
            lstrcpynW(msg, Lic_StatusText(st), cch);
            r = LIC_R_NET;
        } else if (!SaveLicense(lic, msg, cch)) {
            r = LIC_R_NET;
        } else {
            SeenFromServer(&li);
            r = LIC_R_OK;
        }
    } else {
        JsonStr(resp, "error", e, sizeof e);
        ErrorText(status, resp, msg, cch);
        r = LIC_R_NET;
        if ((status == 403 || status == 404) && (!strcmp(e, "revoked") || !strcmp(e, "user_disabled") ||
                                                 !strcmp(e, "unknown_device") || !strcmp(e, "machine"))) {
            DeleteLicFiles();                   /* accesul a fost oprit: licenta nu mai ramane */
            r = LIC_R_REVOKED;
        }
    }
    if (r == LIC_R_OK) FailClear();
    else if (r == LIC_R_NET) FailPut(Lic_Now());    /* fara retea / server cazut: pauza (Lic_RefreshBackoff) */
    LicUnlock(lk);
    return r;
}

int Lic_Deactivate(wchar_t *msg, int cch)
{
    char dev[128], sec[160], d[128], body[512], resp[1024], e[64] = "";
    HANDLE lk;
    DWORD status;
    int r;
    msg[0] = 0;
    if (!(lk = LicLock(LIC_LOCK_MS))) {
        Busy(msg, cch);
        return LIC_R_NET;
    }
    if (!LoadState(dev, sizeof dev, sec, sizeof sec)) {
        DeleteLicFiles();                       /* licenta offline: doar se sterge */
        LicUnlock(lk);
        return LIC_R_NODEVICE;
    }
    JsonSafe(dev, d, sizeof d);
    JsonSafe(sec, sec, sizeof sec);
    snprintf(body, sizeof body, "{\"device\":\"%s\",\"secret\":\"%s\"}", d, sec);
    SecureZeroMemory(sec, sizeof sec);
    status = HttpPost(L"/api/deactivate", body, resp, sizeof resp, 0);
    SecureZeroMemory(body, sizeof body);
    JsonStr(resp, "error", e, sizeof e);
    if (status == 200 || ((status == 403 || status == 404) && e[0])) {
        DeleteLicFiles();
        r = status == 200 ? LIC_R_OK : LIC_R_REVOKED;
    } else {
        ErrorText(status, resp, msg, cch);
        r = LIC_R_NET;
    }
    LicUnlock(lk);
    return r;
}

BOOL Lic_Import(const wchar_t *file, wchar_t *msg, int cch)
{
    char text[MAX_LIC];
    LicInfo li;
    HANDLE lk;
    int st;
    BOOL ok;
    if (ReadAll(file, text, sizeof text) <= 0) {
        lstrcpynW(msg, TR(L"Nu pot citi fișierul.", L"Cannot read the file."), cch);
        return FALSE;
    }
    if ((st = CheckText(text, &li)) != LIC_OK) {
        lstrcpynW(msg, Lic_StatusText(st), cch);
        return FALSE;
    }
    if (!(lk = LicLock(LIC_LOCK_MS))) {
        Busy(msg, cch);
        return FALSE;
    }
    ok = SaveLicense(text, msg, cch);
    LicUnlock(lk);
    return ok;
}
