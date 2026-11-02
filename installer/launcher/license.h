/* license.h - licenta TopoKit (vezi license.c si tools/licenta.py) */
#ifndef TOPOKIT_LICENSE_H
#define TOPOKIT_LICENSE_H
#include <windows.h>

/* Starea licentei = codul de iesire al "TopoKit.exe /license" (folosit si de AutoCAD si de
 * programele Python). 0 = se poate lucra (licenta buna sau licentiere dezactivata la build). */
enum { LIC_OK = 0, LIC_NONE = 10, LIC_BAD = 11, LIC_PC = 12, LIC_EXPIRED = 13, LIC_CLOCK = 14 };

/* Rezultatul reinnoirii / dezactivarii prin server */
enum { LIC_R_OK = 0, LIC_R_NET = 1, LIC_R_REVOKED = 2, LIC_R_NODEVICE = 3 };

typedef struct {
    int status;                 /* LIC_* */
    wchar_t name[128];          /* numele din licenta */
    wchar_t lid[64];            /* ID-ul licentei / dispozitivului */
    long long iat, exp;         /* emisa / expira (secunde Unix, UTC) */
    BOOL device;                /* activata online (exista state.dat: se poate reinnoi) */
} LicInfo;

BOOL Lic_Enabled(void);                         /* cheia publica a fost compilata in program */
void Lic_Machine(wchar_t *out, BOOL grouped);   /* codul calculatorului: 24 (sau 27 cu "-") caractere */
int  Lic_Check(const wchar_t *file, LicInfo *li);  /* file NULL = license.lic implicit */
long long Lic_Now(void);
int  Lic_Activate(const wchar_t *code, wchar_t *msg, int cch);   /* LIC_OK sau eroare (msg completat) */
int  Lic_Refresh(wchar_t *msg, int cch);        /* LIC_R_* */
/* idem, cu asteptarea dupa mutex data. flags LIC_RF_CLI (linia de comanda, AutoCAD asteapta): dupa
 * mutex se verifica din nou Lic_NeedsRefresh (alt proces a reinnoit / a esuat intre timp: fara retea),
 * iar lockms e limita TOTALA (mutex + cererea HTTP, aceasta pe alt fir, cu timpi WinHTTP scurti) */
#define LIC_RF_CLI 1
int  Lic_RefreshEx(wchar_t *msg, int cch, DWORD lockms, int flags);
BOOL Lic_RefreshBackoff(void);                  /* TRUE = o reinnoire a esuat in ultima ora (refresh.dat):
                                                 * liniile de comanda nu mai incearca reteaua */
BOOL Lic_NeedsRefresh(int code, const LicInfo *li);   /* reinnoire automata din linia de comanda: necesara?
                                                 * (state.dat, fara pauza, licenta lipsa / rea / < 3 zile) */
int  Lic_Deactivate(wchar_t *msg, int cch);     /* LIC_R_* */
BOOL Lic_Import(const wchar_t *file, wchar_t *msg, int cch);
const wchar_t *Lic_StatusText(int status);
void Lic_FormatDate(long long t, wchar_t *out, int cch);   /* "14.11.2026" */

/* provocare-raspuns pentru modulele AutoLISP compilate (vezi tools/lic_gate.py):
 *   Lic_ProofEnabled - secretul build-ului (antetul TK_PROOF_FILE, lic_gate.proof_header) a fost compilat;
 *   Lic_NonceOk      - nonce valid: 16..64 caractere [0-9A-Za-z];
 *   Lic_Proof        - scrie in out linia ASCII "<cod> <exp> <nonce> <mac> <calculator>\n", cu
 *                      mac = HMAC-SHA256(cheie, "TKP2|<nonce>|<cod>|<exp>|<calculator>") in hexa cu litere
 *                      mici; calculator = codul calculatorului (24 hex, Lic_Machine). */
BOOL Lic_ProofEnabled(void);
BOOL Lic_NonceOk(const char *nonce);
BOOL Lic_Proof(int code, long long exp, const char *nonce, char *out, int cch);

#endif
