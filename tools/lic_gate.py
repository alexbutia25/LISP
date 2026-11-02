"""Verificarea licentei in interiorul fiecarui modul compilat (.fas).

    from lic_gate import inject
    text = inject(text, "TopoKitAnexe.lsp", key)   # key = 32 octeti (secretul build-ului)

Incarcatorul TopoKitLoad.lsp ramane .lsp necompilat, deci verificarea din el se poate ocoli.
De aceea fiecare modul primeste propria verificare, legata de un secret pe care doar TopoKit.exe
il stie (provocare-raspuns cu HMAC-SHA256).

Protocolul
  - secretul build-ului (key, 32 de octeti aleatori, facut de build_installer.py) e in TopoKit.exe
    (proof_header: bucati amestecate si mascate, fara sirul hex al cheii) si, ca stari intermediare
    SHA-256 (HMAC "midstate" dupa blocul ipad / opad, mascate), in fiecare modul. Cheia insasi nu
    apare in .fas;
  - la incarcare modulul face un nonce, ruleaza ascuns "TopoKit.exe" /license /proof <nonce> <fisier>
    si asteapta; TopoKit.exe scrie "<cod> <exp> <nonce> <mac> <calculator>", cu
        mac = HMAC-SHA256(key, "TKP2|nonce|cod|exp|<calculator = codul calculatorului, 24 hex>")
    Modulul calculeaza singur codul calculatorului ca license.c: SHA-256("TopoKit/1|<MachineGuid mic>|
    <seria volumului de sistem, %08X>"); volumul = unitatea din SystemRoot (registrul HKLM ...\\Windows NT\\
    CurrentVersion, apoi variabila de mediu), seria prin Scripting.FileSystemObject. Codul folosit in mac:
      * calculul local a reusit: codul raportat de exe doar daca e unul dintre cele locale -
        H(guid, serie) sau H("", serie) (license.c foloseste "" cand MachineGuid nu e REG_SZ, de ex.
        REG_EXPAND_SZ, sau e prea lung); altfel H(guid, serie). Un raspuns cerut de pe alt calculator
        (releu: exe-ul licentiat al altcuiva semneaza pentru atacator) poarta codul ACELUI calculator ->
        mac gresit -> fara licenta;
      * calculul local a esuat (FSO / vlax indisponibil, seria nu e INT, registrul da eroare): codul
        raportat de exe (legat in mac). Doar pe un astfel de calculator releul redevine posibil - altfel
        o licenta valida ar fi refuzata (blocare falsa) pe fiecare modul.
    Raspunsul vechi cu 4 campuri (fara calculator) ramane valid cu codul local.
    Doar cod 0 + nonce-ul trimis + exp nu mai vechi de 2 zile (ceas local, toleranta pentru fus orar;
    atof, fara depasire in 2038) + mac corect = licenta buna.

Ce stim despre motorul AutoLISP (AutoCAD 2026, ambele motoare, verificat in accoreconsole):
  - o functie definita de utilizator are (type f) = SUBR si se tipareste "#<SUBR @... NUME>", exact
    ca una incorporata -> verificarea de tip singura nu prinde redefinirile;
  - in codul .fas, TOATE apelurile de functii (si car, not, =, eq ...) merg prin simbol la momentul
    apelului, deci se pot redefini inainte de incarcare; formele speciale (if, and, or, cond, while,
    repeat, foreach, progn, setq, quote, lambda, defun) se compileaza in linie si NU se pot redefini;
  - variabilele locale sunt dinamice (o functie apelata le poate citi / schimba).
De aceea verificarea (Check):
  1. sonde de aritate: functiile incorporate variadice / cu argumente optionale (=, <, +, boole,
     strcat, substr, strlen, mapcar ...) se apeleaza direct cu un numar de argumente pe care nicio
     functie (defun ...) nu il poate primi -> o redefinire in AutoLISP opreste incarcarea (eroare);
     plus fapte simple ((<= 1 2), (= "a" "b") = nil, (boole ...), (nth ...) ...);
  2. tipul si forma tiparita ("#<SUBR @... NUME>", numele exact) pentru fiecare functie incorporata
     folosita (TRUSTED): prinde (setq = equal), lambda-uri, schimburi intre functii;
  3. un test cu raspuns cunoscut: HMAC(key, "TKSELF|<modul>") calculat in AutoLISP = constanta de la
     build (orice "carlig" care strica aritmetica / listele strica si asta);
  4. sondele 1-2 se repeta dupa citirea raspunsului si inca o data la decizie;
  5. SHA-256 / HMAC sunt scrise IN LINIE in Check (expresii (lambda ...) generate aici), fara functii
     ajutatoare globale care s-ar putea inlocui in timpul verificarii; constantele sunt in Check;
  6. comparatia finala: (= mac primit) si o comparatie caracter cu caracter, cu numarare.
Decizia si structura modulului
  - Check ruleaza INAINTE de orice forma a modulului; e o lambda aplicata direct, iar rezultatul e pus
    o singura data: (setq *G:OK* (if ((lambda (/ ...) ...)) T)) - fara niciun simbol de functie (nici
    in timpul verificarii, nici dupa: nimic apelabil care sa contina secretul, fara oracol HMAC). Orice
    eroare in Check (de ex. o sonda) opreste incarcarea: nimic din modul nu se defineste.
  - Fiecare forma de la nivelul de sus al modulului e pazita: (if *G:OK* FORMA). Indicatorul e o
    variabila globala, dar: e scris doar din Check, imediat inainte de formele pazite; intre ele, fara
    licenta, nu se apeleaza nicio functie (if / setq / defun sunt in linie), deci nimic nu-l poate
    schimba; o valoare pusa inainte de incarcare e suprascrisa; una pusa dupa nu mai conteaza (formele
    au rulat deja sau nu); la sfarsit e sters. Pazirea fiecarei forme (nu un singur (progn ...) urias)
    pastreaza comportamentul formelor de nivel de sus si evita limitele compilatorului.
  - Fara licenta: comenzile c: devin stub-uri (mesaj + deschide TopoKit), iar functiile de nivel de
    sus ale modulului devin (defun NUME (argumente) nil) - forme statice, fara eval / read / foreach.
    *error* si S::* nu se ating.

Codul adaugat e ASCII si foloseste doar functii comune LISPSYS 0 (FAS4) si 1 (FAS5). inject() e
determinista pentru un (text, module, key) dat si idempotenta (MARK). Fara key (build de dezvoltare /
fara licentiere) inject() intoarce textul neschimbat.

Limite (oneste): un atacator care decompileaza .fas-ul afla constantele (echivalente cu cheia) si
poate scrie "carlige" care imita exact functiile incorporate; un modul .NET / ARX poate defini functii
LISP variadice. Protectia ridica efortul de la "o linie de (defun ...)" la inginerie inversa.
"""
import hashlib
import hmac as _hmac
import pathlib
import random
import re

MARK = ";;; @@TKGATE@@"
END_MARK = ";;; @@TKGATE-END@@"
BODY_MARK = ";;; @@TKGATE-BODY@@ module forms, each guarded by the licence decision"
MSG_RO = "TopoKit: licenta lipsa sau expirata - deschideti TopoKit pentru activare."
MSG_EN = "TopoKit: licence missing or expired - open TopoKit to activate it."
MISMATCH_RO = "TopoKit: codul calculatorului din AutoCAD difera de cel al TopoKit.exe - licenta refuzata (trimiteti mesajul la suport)"
MISMATCH_EN = "TopoKit: the computer code in AutoCAD differs from TopoKit.exe - licence refused (send this message to support)"
CMD_RE = re.compile(r"\(\s*defun\s+c:([^\s()'\";]+)", re.I)
DEFUN_RE = re.compile(r"\(\s*defun\s+([^\s()'\";]+)", re.I)
TOP_DEFUN_RE = re.compile(r"\(\s*defun\s+([^\s()'\";]+)\s*\(([^()]*)\)", re.I)
PROOF_TAG = "TKP2"
KAT_TAG = "TKSELF|"
REG_GUID = "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography"
REG_WINNT = "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"

# functiile incorporate apelate in Check (tip SUBR + forma tiparita "#<SUBR @... NUME>").
# tests/test_lic_gate.py verifica: lista acopera TOATE apelurile din Check, cu exceptia UNCHECKED.
TRUSTED = ["+", "-", "*", "/", "=", "<", "<=", ">", "REM", "BOOLE", "STRCAT", "SUBSTR", "STRLEN",
           "LIST", "APPEND", "MAPCAR", "CAR", "CDR", "CADR", "CADDR", "NTH", "LENGTH", "EQ", "TYPE",
           "EVAL", "FIX", "ATOI", "ATOF", "STRCASE", "VL-STRING->LIST", "VL-STRING-SEARCH", "VL-PRIN1-TO-STRING",
           "VL-CATCH-ALL-APPLY", "GETVAR", "GETENV", "VL-REGISTRY-READ",
           "VL-FILENAME-MKTEMP", "FINDFILE", "OPEN", "READ-LINE", "CLOSE", "VL-FILE-DELETE", "PRINC"]
# nu se verifica: vlax-* (sub LISPSYS=1 in accoreconsole nu exista, tipul / numele difera intre motoare;
# sunt doar intrari - raspunsul e semnat) si vl-load-com (se tipareste VL-LOAD-REACTORS)
UNCHECKED = ["VL-LOAD-COM", "VLAX-CREATE-OBJECT", "VLAX-INVOKE", "VLAX-GET-PROPERTY", "VLAX-RELEASE-OBJECT",
             "VLAX-VARIANT-VALUE"]

# SHA-256: constante standard (radacini cubice / patrate ale primelor numere prime)
_SHA_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]
_SHA_H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]


# ------------------------------------------------------------------ utilitare Python
def module_id(module_name):
    """Prefixul functiilor injectate: TKG-<NUMELE MODULULUI, doar litere si cifre>."""
    stem = pathlib.PurePath(str(module_name).replace("\\", "/")).stem
    ident = re.sub(r"[^A-Z0-9]", "", stem.upper()) or "MODULE"
    return "TKG-" + ident


def stub_id(module_name):
    """Prefixul functiilor care raman dupa incarcare (stub-uri, gasirea TopoKit.exe) - fara secret."""
    return "TKS-" + module_id(module_name)[4:]


def commands(text):
    """Comenzile (defun c:NUME ...) din sursa, cu litere mari, sortate, fara dubluri."""
    return sorted({m.upper() for m in CMD_RE.findall(text)})


def defuns(text):
    """Toate functiile (defun NUME ...) din sursa, cu numele original, in ordinea aparitiei, unice."""
    seen, out = set(), []
    for m in DEFUN_RE.findall(text):
        if m.upper() not in seen:
            seen.add(m.upper())
            out.append(m)
    return out


def _skip_comment(text, i):
    if text.startswith(";|", i):
        j = text.find("|;", i + 2)
        if j < 0:
            raise ValueError("comentariu ;| neinchis")
        return j + 2
    j = text.find("\n", i)
    return len(text) if j < 0 else j + 1


def _skip_string(text, i):
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
        elif text[j] == '"':
            return j + 1
        else:
            j += 1
    raise ValueError("sir neinchis")


def _skip_datum(text, i):
    n = len(text)
    while i < n and text[i] == "'":
        i += 1
        while i < n and text[i].isspace():
            i += 1
    if i >= n:
        raise ValueError("forma incompleta")
    c = text[i]
    if c == '"':
        return _skip_string(text, i)
    if c == ")":
        raise ValueError(f") in plus la pozitia {i}")
    if c != "(":
        j = i
        while j < n and not text[j].isspace() and text[j] not in "()';\"":
            j += 1
        return j
    depth, j = 0, i
    while j < n:
        c = text[j]
        if c == ";":
            j = _skip_comment(text, j)
        elif c == '"':
            j = _skip_string(text, j)
        elif c == "(":
            depth += 1
            j += 1
        elif c == ")":
            depth -= 1
            j += 1
            if depth == 0:
                return j
        else:
            j += 1
    raise ValueError("paranteze neinchise")


def top_forms(text):
    """Intervalele (inceput, sfarsit) ale formelor de la nivelul de sus (comentariile raman intre ele)."""
    spans, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == ";":
            i = _skip_comment(text, i)
        else:
            j = _skip_datum(text, i)
            spans.append((i, j))
            i = j
    return spans


def top_defuns(text):
    """Functiile definite la nivelul de sus: [(nume, [argumente obligatorii])], unice, in ordine."""
    seen, out = set(), []
    for a, b in top_forms(text):
        m = TOP_DEFUN_RE.match(text, a, b)
        if not m:
            continue
        name = m.group(1)
        if name.upper() in seen:
            continue
        seen.add(name.upper())
        args = m.group(2).split("/")[0].split()
        out.append((name, args))
    return out


def stub_helpers(text):
    """Ajutatoarele neutralizate fara licenta: functiile de nivel de sus, fara c:, *error*, S::*."""
    return [(n, a) for n, a in top_defuns(text)
            if not n.upper().startswith(("C:", "S::")) and n.upper() != "*ERROR*"]


def _english(module_name):
    parts = pathlib.PurePath(str(module_name).replace("\\", "/")).parts[:-1]
    return any(p.lower() == "en" for p in parts)


def _lisp_str(s):
    assert s.isascii() and '"' not in s and "\\" not in s, s
    return '"' + s + '"'


# ------------------------------------------------------------------ criptografie de referinta (Python)
def _compress(h, block):
    """O compresie SHA-256 (h = 8 cuvinte, block = 64 de octeti) -> 8 cuvinte."""
    m = 0xFFFFFFFF
    rr = lambda x, n: ((x >> n) | (x << (32 - n))) & m        # noqa: E731
    w = [int.from_bytes(block[4 * i:4 * i + 4], "big") for i in range(16)]
    for i in range(16, 64):
        s0 = rr(w[i - 15], 7) ^ rr(w[i - 15], 18) ^ (w[i - 15] >> 3)
        s1 = rr(w[i - 2], 17) ^ rr(w[i - 2], 19) ^ (w[i - 2] >> 10)
        w.append((w[i - 16] + s0 + w[i - 7] + s1) & m)
    a, b, c, d, e, f, g, hh = h
    for i in range(64):
        t1 = (hh + (rr(e, 6) ^ rr(e, 11) ^ rr(e, 25)) + ((e & f) ^ (~e & g)) + _SHA_K[i] + w[i]) & m
        t2 = ((rr(a, 2) ^ rr(a, 13) ^ rr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) & m
        hh, g, f, e, d, c, b, a = g, f, e, (d + t1) & m, c, b, a, (t1 + t2) & m
    return [(x + y) & m for x, y in zip(h, [a, b, c, d, e, f, g, hh])]


def midstates(key):
    """Starile SHA-256 dupa blocul (key xor ipad) si (key xor opad): HMAC fara cheie in clar."""
    k = bytes(key) + bytes(64 - len(key))
    return (_compress(_SHA_H, bytes(b ^ 0x36 for b in k)), _compress(_SHA_H, bytes(b ^ 0x5C for b in k)))


def machine_code(guid, serial):
    """Codul calculatorului ca license.c / licenta.py: 24 cifre hex mari (serial = int, si negativ)."""
    src = f"TopoKit/1|{guid.lower()}|{serial & 0xFFFFFFFF:08X}"
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:24].upper()


def proof_mac(key: bytes, nonce: str, code, exp, machine: str) -> str:
    """mac-ul din raspunsul /proof: HMAC-SHA256(key, "TKP2|nonce|cod|exp|calculator"), hex mic.
    Referinta pentru teste si pentru lansatorul C (trebuie sa dea exact acelasi sir)."""
    msg = f"{PROOF_TAG}|{nonce}|{code}|{exp}|{machine}".encode("ascii")
    return _hmac.new(key, msg, hashlib.sha256).hexdigest()


def kat_mac(key, module_name):
    return _hmac.new(bytes(key), (KAT_TAG + module_id(module_name)).encode("ascii"), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ cheia in TopoKit.exe (C)
def _mix(seed, c, j):
    x = (seed ^ (c * 0x9E3779B9) ^ (j * 0x85EBCA6B)) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x2C1B3C6D) & 0xFFFFFFFF
    x ^= x >> 12
    x = (x * 0x297A2D39) & 0xFFFFFFFF
    x ^= x >> 15
    return (x >> 8) & 0xFF


def proof_header(key, rng=None):
    """Antetul C cu secretul build-ului pentru license.c (#include TK_PROOF_FILE): 8 bucati de 4 octeti,
    in ordine amestecata, fiecare mascata cu o functie de amestec (tk_pk_mix in license.c). Nici cheia,
    nici hex-ul ei nu apar ca sir continuu. Fisierul se face la build si se sterge dupa compilare."""
    key = bytes(key)
    if len(key) != 32:
        raise ValueError("key trebuie sa fie 32 de octeti")
    rng = rng or random.SystemRandom()
    seed = rng.getrandbits(32)
    perm = list(range(8))
    rng.shuffle(perm)
    data = []
    for c in range(8):                      # bucata c din tabel = bucata perm[c] din cheie
        for j in range(4):
            data.append(key[perm[c] * 4 + j] ^ _mix(seed, c, j))
    return ("/* generat de tools/lic_gate.py la build - NU se pune in depozit */\n"
            f"#define TK_PK_SEED 0x{seed:08X}u\n"
            "static const unsigned char tk_pk_perm[8] = {" + ", ".join(map(str, perm)) + "};\n"
            "static const unsigned char tk_pk_data[32] = {" + ", ".join(map(str, data)) + "};\n")


def proof_key_from_header(text):
    """Inversul lui proof_header (pentru teste): cheia din antetul C."""
    seed = int(re.search(r"TK_PK_SEED 0x([0-9A-F]+)u", text).group(1), 16)
    perm = [int(x) for x in re.search(r"tk_pk_perm\[8\] = \{([^}]*)\}", text).group(1).split(",")]
    data = [int(x) for x in re.search(r"tk_pk_data\[32\] = \{([^}]*)\}", text).group(1).split(",")]
    key = bytearray(32)
    for c in range(8):
        for j in range(4):
            key[perm[c] * 4 + j] = data[c * 4 + j] ^ _mix(seed, c, j)
    return bytes(key)


# ------------------------------------------------------------------ generarea codului AutoLISP
def _wl(ws):
    """Lista LISP de cuvinte de 32 de biti ca perechi (hi lo) de cate 16 biti."""
    return "(" + " ".join(f"({w >> 16} {w & 0xFFFF})" for w in ws) + ")"


def _bl(bs):
    return "(" + " ".join(str(b) for b in bs) + ")"


def _rot(x, n):
    """rotr(x, n) pe (hi lo), n constant: doar / rem * + pe numere < 65536 (fara depasiri)."""
    h, l = f"(car {x})", f"(cadr {x})"
    if n >= 16:
        h, l, n = l, h, n - 16
    if n == 0:
        return f"(list {h} {l})"
    p, q = 2 ** n, 2 ** (16 - n)
    return f"(list (+ (/ {h} {p}) (* (rem {l} {p}) {q})) (+ (/ {l} {p}) (* (rem {h} {p}) {q})))"


def _shr(x, n):
    h, l = f"(car {x})", f"(cadr {x})"
    if n >= 16:
        return f"(list 0 (/ {h} {2 ** (n - 16)}))"
    p, q = 2 ** n, 2 ** (16 - n)
    return f"(list (/ {h} {p}) (+ (/ {l} {p}) (* (rem {h} {p}) {q})))"


def _x3(e1, e2, e3):
    return (f"((lambda (u v z) (list (boole 6 (car u) (car v) (car z)) (boole 6 (cadr u) (cadr v) (cadr z))))"
            f" {e1} {e2} {e3})")


def _add(*es):
    ps = [f"q{i}" for i in range(len(es))]
    lo = "(+ " + " ".join(f"(cadr {p})" for p in ps) + ")"
    hi = "(+ " + " ".join(f"(car {p})" for p in ps) + ")"
    return (f"((lambda ({' '.join(ps)} / y) (setq y {lo}) (list (rem (+ {hi} (/ y 65536)) 65536) (rem y 65536)))"
            f" {' '.join(es)})")


def _sha_block():
    """Corpul SHA-256 in linie: intrari sm (octeti), sh (starea initiala), sp (octeti deja comprimati:
    0 sau 64); iesire sd (32 de octeti). Doar forme speciale + functii incorporate (fara ajutatoare)."""
    big_s1 = _x3(_rot("e", 6), _rot("e", 11), _rot("e", 25))
    big_s0 = _x3(_rot("a", 2), _rot("a", 13), _rot("a", 22))
    ch = ("(list (boole 6 (boole 1 (car e) (car f)) (boole 1 (boole 6 (car e) 65535) (car g)))"
          " (boole 6 (boole 1 (cadr e) (cadr f)) (boole 1 (boole 6 (cadr e) 65535) (cadr g))))")
    maj = ("(list (boole 6 (boole 1 (car a) (car b)) (boole 1 (car a) (car c)) (boole 1 (car b) (car c)))"
           " (boole 6 (boole 1 (cadr a) (cadr b)) (boole 1 (cadr a) (cadr c)) (boole 1 (cadr b) (cadr c))))")
    s0 = f"((lambda (x) {_x3(_rot('x', 7), _rot('x', 18), _shr('x', 3))}) (nth (- j 15) w))"
    s1 = f"((lambda (x) {_x3(_rot('x', 17), _rot('x', 19), _shr('x', 10))}) (nth (- j 2) w))"
    word = ("(list (+ (* (nth (+ i j) pad) 256) (nth (+ i j 1) pad))"
            " (+ (* (nth (+ i j 2) pad) 256) (nth (+ i j 3) pad)))")
    return f"""(setq pad (append sm (list 128)) i (rem (+ sp (length pad)) 64))
          (repeat (rem (- 120 i) 64) (setq pad (append pad (list 0))))
          (setq bits (* (+ sp (length sm)) 8)
                pad (append pad (list 0 0 0 0 (rem (/ bits 16777216) 256) (rem (/ bits 65536) 256)
                                      (rem (/ bits 256) 256) (rem bits 256)))
                i 0)
          (while (< i (length pad))
            (setq w nil j 0)
            (repeat 16 (setq w (append w (list {word})) j (+ j 4)))
            (setq j 16)
            (while (< j 64)
              (setq w (append w (list {_add(s1, "(nth (- j 7) w)", s0, "(nth (- j 16) w)")})) j (+ j 1)))
            (setq a (nth 0 sh) b (nth 1 sh) c (nth 2 sh) d (nth 3 sh) e (nth 4 sh) f (nth 5 sh)
                  g (nth 6 sh) hh (nth 7 sh) j 0)
            (while (< j 64)
              (setq t1 {_add("hh", big_s1, ch, "(nth j kk)", "(nth j w)")}
                    t2 {_add(big_s0, maj)}
                    hh g g f f e e {_add("d", "t1")} d c c b b a a {_add("t1", "t2")} j (+ j 1)))
            (setq sh (mapcar '(lambda (x y) {_add("x", "y")}) sh (list a b c d e f g hh)) i (+ i 64)))
          (setq sd nil)
          (foreach x sh (setq sd (append sd (list (/ (car x) 256) (rem (car x) 256) (/ (cadr x) 256) (rem (cadr x) 256)))))"""


def _probe():
    """Sonde: apeluri directe pe care doar functiile incorporate le accepta (aritate variabila /
    argumente optionale) + fapte simple. O redefinire (defun ...) cu aritate fixa = eroare = incarcare
    oprita; un rezultat gresit = nil."""
    return """(and (= 1 1 1) (= "ab" "ab" "ab") (if (= 1 1 2) nil T) (if (= "a" "b") nil T)
           (< 1 2 3) (if (< 1 3 2) nil T) (<= 1 1 2) (if (<= 2 1) nil T) (> 3 2 1) (if (> 1 2) nil T)
           (= (+ 1 2 3 4) 10) (= (+) 0) (= (- 10 1 2) 7) (= (* 2 3 4) 24) (= (/ 100 5 2) 10) (= (rem 100 7 3) 2)
           (= (boole 6 1 2 4) 7) (= (boole 1 7 3 1) 1) (= (boole 7 1 2 4) 7) (= (boole 6 5 3) 6)
           (= (strcat "a" "b" "c") "abc") (= (strcat) "") (= (substr "abcd" 2) "bcd") (= (substr "abcd" 2 2) "bc")
           (= (strlen "ab" "cde") 5) (= (strlen) 0) (= (length (list 1 2 3)) 3)
           (= (length (append '(1) '(2) '(3 4))) 4) (= (car (mapcar '+ '(1 2) '(10 20) '(100 200))) 111)
           (= (vl-string-search "b" "abcb" 2) 3) (= (strcase "aB" T) "ab") (= (car '(1 2)) 1)
           (= (cadr '(1 2)) 2) (= (caddr '(1 2 3)) 3) (= (nth 2 '(5 6 7)) 7) (eq 'a 'a) (if (eq 'a 'b) nil T)
           (eq (type 1) 'INT) (eq (type "a") 'STR) (if (type nil) nil T) (= (fix 2.7) 2) (= (atoi "42") 42)
           (= (atof "2.5") 2.5) (< 4000000000.0 (atof "4100000000") 4200000000.0))"""


def _tc():
    """Tipul si forma tiparita a fiecarei functii din TRUSTED: "#<SUBR @<adresa> <NUME>"."""
    pairs = " ".join(f'("{n}" . {n.lower()})' for n in TRUSTED)
    return f"""(foreach p '({pairs})
            (setq f (eval (cdr p)) x (vl-prin1-to-string f))
            (if (and (eq (type f) 'SUBR) (eq (type x) 'STR) (< (+ (strlen (car p)) 9) (strlen x))
                     (= (substr x 1 8) "#<SUBR @")
                     (= (substr x (- (strlen x) (strlen (car p)))) (strcat (car p) ">"))
                     (= (substr x (- (strlen x) (strlen (car p)) 1) 1) " "))
              nil (setq ok nil)))"""


def _hex(var, src, n):
    """var = cele n (<= 7) cifre hex mici ale intregului src (si negativ: complement fata de 2)."""
    return (f'(setq hn (boole 1 {src} {16 ** n - 1}) {var} "") '
            f'(repeat {n} (setq {var} (strcat (substr "0123456789abcdef" (+ 1 (rem hn 16)) 1) {var}) hn (/ hn 16)))')


def _hex8u(var, src):
    """var = %08X al intregului pe 32 de biti src (seria volumului poate fi negativa), fara literali > 2^31."""
    return (f'(setq hn (boole 1 {src} 65535) hn (list (boole 1 (/ (- {src} hn) 65536) 65535) hn) {var} "") '
            f'(foreach y hn (setq i 0) (repeat 4 (setq {var} (strcat {var} (substr "0123456789ABCDEF" '
            f'(+ 1 (rem (/ y (nth i (list 4096 256 16 1))) 16)) 1)) i (+ i 1))))')


def _check(module_name, key, s, g):
    mismatch = MISMATCH_EN if _english(module_name) else MISMATCH_RO
    is_, os_ = midstates(key)
    mask = hashlib.sha256(b"TKmask" + bytes(key)).digest() + hashlib.sha256(b"TKmask2" + bytes(key)).digest()
    mw = [int.from_bytes(mask[4 * i:4 * i + 4], "big") for i in range(16)]
    isx = [a ^ b for a, b in zip(is_, mw[:8])]
    osx = [a ^ b for a, b in zip(os_, mw[8:])]
    kat_msg = (KAT_TAG + module_id(module_name)).encode("ascii")
    kat = kat_mac(key, module_name)
    unmask = "(mapcar '(lambda (x y) (list (boole 6 (car x) (car y)) (boole 6 (cadr x) (cadr y))))"
    probe, tc = _probe(), _tc()
    locals_ = ("ok p f x exe n nonce hn hs gd dv sn r mmsg out fh line toks tk now kk is os ph jobs res job sm sh sp"
               " sd pad bits i j w a b c d e f g hh t1 t2 mach vmsg inner fin mac katx diff cnt loc mmsg2 ms em")
    return f""";; Check: T doar cu un raspuns /proof bun. O lambda aplicata direct (nu exista niciun simbol de apelat
;; sau de inlocuit, nici dupa o incarcare oprita), totul in linie (fara functii ajutatoare globale).
(setq *{g}:OK* (if ((lambda (/ {locals_})
  ;; 1. sonde + functiile incorporate originale
  (setq ok {probe})
  {tc}
  ;; 2. intrarile (nesigure; raspunsul e semnat): TopoKit.exe, nonce, codul calculatorului, raspunsul
  (vl-load-com)
  (setq exe (vl-catch-all-apply '{s}:Exe nil))
  (if (eq (type exe) 'STR) nil (setq exe nil))
  (setq {s}:N (if (eq (type {s}:N) 'INT) (+ {s}:N 1) 1))
  (setq x (getvar "MILLISECS") x (if (eq (type x) 'INT) x (if (eq (type x) 'REAL) (fix (rem x 268435456.0)) 0)))
  {_hex("hs", "x", 7)} (setq nonce (strcat "tk" hs))
  {_hex("hs", s + ":N", 5)} (setq nonce (strcat nonce hs))
  (setq x (getvar "CDATE") x (if (eq (type x) 'REAL) (fix (rem (* x 1000000.0) 268435456.0)) 0))
  {_hex("hs", "x", 7)} (setq nonce (strcat nonce hs))
  (setq x (getvar "DATE") now (if (eq (type x) 'REAL) (* (- x 2440587.5) 86400.0) 0.0)
        x (fix (rem (* (if (eq (type x) 'REAL) x 0.0) 100000.0) 268435456.0)))
  {_hex("hs", "x", 7)} (setq nonce (strcat nonce hs))
  ;; codul calculatorului ca license.c: SHA-256("TopoKit/1|<MachineGuid mic>|<seria volumului, %08X>");
  ;; loc = calculul local a reusit (altfel se foloseste codul raportat de exe, legat in mac)
  (setq gd (vl-catch-all-apply 'vl-registry-read (list "{REG_GUID.replace(chr(92), chr(92) * 2)}" "MachineGuid")))
  (setq loc (if gd (eq (type gd) 'STR) T)
        gd (if (eq (type gd) 'STR) (strcase gd T) ""))
  ;; unitatea sistemului (GetSystemWindowsDirectory in license.c): registrul, apoi %SystemRoot%
  (setq dv (vl-catch-all-apply 'vl-registry-read (list "{REG_WINNT.replace(chr(92), chr(92) * 2)}" "SystemRoot")))
  (if (and (eq (type dv) 'STR) (< 1 (strlen dv)) (= (substr dv 2 1) ":")) nil (setq dv (getenv "SystemRoot")))
  (setq dv (if (and (eq (type dv) 'STR) (< 1 (strlen dv)) (= (substr dv 2 1) ":")) (substr dv 1 2) "C:"))
  (setq sn (vl-catch-all-apply
             '(lambda (/ fso drv v)
                (setq fso (vlax-create-object "Scripting.FileSystemObject")
                      drv (vlax-invoke fso 'GetDrive dv)
                      v (vlax-get-property drv 'SerialNumber))
                (vlax-release-object drv)
                (vlax-release-object fso)
                (if (eq (type v) 'VARIANT) (vlax-variant-value v) v))
             nil))
  (setq loc (and loc (eq (type sn) 'INT)) sn (if (eq (type sn) 'INT) sn 0))
  {_hex8u("hs", "sn")} (setq mmsg (strcat "TopoKit/1|" gd "|" hs) mmsg2 (strcat "TopoKit/1||" hs))
  ;; TopoKit.exe /license /proof <nonce> <fisier>
  (setq out (vl-filename-mktemp "tkp.txt"))
  (if exe
    (vl-catch-all-apply
      '(lambda (/ sh)
         (setq sh (vlax-create-object "WScript.Shell"))
         (vlax-invoke sh 'Run (strcat "\\"" exe "\\" /license /proof " nonce " \\"" out "\\"") 0 :vlax-true)
         (vlax-release-object sh))
      nil))
  (if (and out (findfile out) (setq fh (open out "r")))
    (progn (setq line (read-line fh)) (close fh) (vl-catch-all-apply 'vl-file-delete (list out))))
  (setq toks nil)
  (if (eq (type line) 'STR)
    (progn
      (while (setq i (vl-string-search " " line)) (setq toks (append toks (list (substr line 1 i))) line (substr line (+ i 2))))
      (setq toks (append toks (list line)))))
  ;; 3. din nou sondele (un "carlig" pus in timpul pasului 2 se vede aici)
  (setq ok (and ok {probe}))
  {tc}
  ;; 4. SHA-256 / HMAC in linie: faza 1 = codul calculatorului, 2 = HMAC interior, 3 = exterior
  (setq kk '{_wl(_SHA_K)}
        is {unmask} '{_wl(isx)} '{_wl(mw[:8])})
        os {unmask} '{_wl(osx)} '{_wl(mw[8:])})
        mach nil inner nil fin nil)
  (foreach ph '(1 2 3)
    (setq jobs (if (= ph 1) (list (list '{_wl(_SHA_H)} 0 (vl-string->list mmsg))
                                  (list '{_wl(_SHA_H)} 0 (vl-string->list mmsg2)))
                 (if (= ph 2) (list (list is 64 '{_bl(kat_msg)}) (list is 64 (vl-string->list vmsg)))
                   (list (list os 64 (car inner)) (list os 64 (cadr inner)))))
          res nil)
    (foreach job jobs
      (setq sh (car job) sp (cadr job) sm (caddr job))
      {_sha_block()}
      (setq res (append res (list sd))))
    (if (= ph 1)
      (progn
        (setq ms nil)
        (foreach r res
          (setq mach "" i 0)
          (repeat 12
            (setq mach (strcat mach (substr "0123456789ABCDEF" (+ 1 (/ (nth i r) 16)) 1)
                               (substr "0123456789ABCDEF" (+ 1 (rem (nth i r) 16)) 1))
                  i (+ i 1)))
          (setq ms (append ms (list mach))))
        ;; codul din mac: cel raportat de exe doar daca e unul local (sau calculul local a esuat)
        (setq em (if (= (length toks) 5) (nth 4 toks))
              mach (if loc (if (and em (or (= em (car ms)) (= em (cadr ms)))) em (car ms))
                     (if (and (eq (type em) 'STR) (= (strlen em) 24)) em "x")))
        ;; nepotrivire (releu sau o diferenta de calcul): refuzat, dar nu in tacere
        (if (and loc (eq (type em) 'STR) (= (strlen em) 24) (= (nth 0 toks) "0"))
          (if (or (= em (car ms)) (= em (cadr ms))) nil
            (princ (strcat "\\n{mismatch} (AutoCAD " (car ms) ", TopoKit.exe " em ")"))))
        (setq vmsg (strcat "{PROOF_TAG}|" nonce "|"
                           (if (or (= (length toks) 4) (= (length toks) 5)) (strcat (nth 0 toks) "|" (nth 1 toks)) "x|x")
                           "|" mach)))
      (if (= ph 2) (setq inner res) (setq fin res))))
  (setq mac "" katx "")
  (foreach b (cadr fin)
    (setq mac (strcat mac (substr "0123456789abcdef" (+ 1 (/ b 16)) 1) (substr "0123456789abcdef" (+ 1 (rem b 16)) 1))))
  (foreach b (car fin)
    (setq katx (strcat katx (substr "0123456789abcdef" (+ 1 (/ b 16)) 1) (substr "0123456789abcdef" (+ 1 (rem b 16)) 1))))
  ;; 5. decizia: tot ce urmeaza sunt forme speciale + functii verificate mai sus
  (setq n (length toks) tk (if (or (= n 4) (= n 5)) (nth 3 toks) "") diff 0 cnt 0 i 1)
  (while (<= i 64)
    (if (= (substr mac i 1) (substr tk i 1)) nil (setq diff (+ diff 1)))
    (setq cnt (+ cnt 1) i (+ i 1)))
  (if (and ok {probe}
           (= katx "{kat}") (= (strlen mac) 64) (or (= (length toks) 4) (= (length toks) 5))
           (= (nth 0 toks) "0") (= (nth 2 toks) nonce) (< (- now 172800.0) (atof (nth 1 toks)))
           (= (strlen tk) 64) (= mac tk) (= diff 0) (= cnt 64))
    T))) T))
"""


def header(module_name, key, test_exe=None):
    g, s = module_id(module_name), stub_id(module_name)
    msg = MSG_EN if _english(module_name) else MSG_RO
    if test_exe is None:
        exe = f"""(defun {s}:Slash (s) (vl-string-right-trim "\\\\/" (vl-string-translate "/" "\\\\" s)))
(defun {s}:Dir (f) (if (= (type f) 'STR) (vl-filename-directory f)))
;; TopoKit.exe: Contents\\install.txt (prima linie = folderul instalarii), apoi registrul
(defun {s}:Exe (/ k l f fh)
  (setq k "HKEY_CURRENT_USER\\\\Software\\\\TopoKit")
  (foreach d (list (vl-registry-read k "ContentsDir")
                   ({s}:Dir (findfile "TopoKitLoad.fas")) ({s}:Dir (findfile "TopoKitLoad.lsp"))
                   ({s}:Dir (findfile "TopoKit.fas")) ({s}:Dir (findfile "TopoKit.lsp"))
                   ({s}:Dir ({s}:Dir (findfile "TopoKit.fas"))) ({s}:Dir ({s}:Dir (findfile "TopoKit.lsp"))))
    (if (and (= (type d) 'STR) (/= d "")
             (setq f (findfile (strcat ({s}:Slash d) "\\\\install.txt")))
             (setq fh (open f "r")))
      (progn (setq l (cons (read-line fh) l)) (close fh))))
  (vl-some '(lambda (d)
              (if (and (= (type d) 'STR) (/= (setq d (vl-string-trim " \\t\\r\\n" d)) "")
                       (findfile (strcat ({s}:Slash d) "\\\\TopoKit.exe")))
                (strcat ({s}:Slash d) "\\\\TopoKit.exe")))
           (append (reverse l) (list (vl-registry-read k "InstallDir")))))"""
    else:                                   # doar testele (tests/): calea exe-ului de test, fixa
        assert str(test_exe).isascii() and '"' not in str(test_exe)
        exe = f'(defun {s}:Exe () "{str(test_exe).replace(chr(92), chr(92) * 2)}")'
    return f"""{MARK} licence gate - generated by tools/lic_gate.py, do not edit
(setq *{g}:OK* nil)
{exe}
(defun {s}:Stub (/ exe)
  (princ "\\n{msg}")
  (setq exe (vl-catch-all-apply '{s}:Exe nil))
  (if (= (type exe) 'STR) (vl-catch-all-apply 'startapp (list exe)))
  (princ))
{_check(module_name, key, s, g)};;; end of licence gate header

"""


def stubs(module_name, cmds, helpers, chunk=120):
    """Formele statice fara licenta: (defun C:X () (S:Stub)) si (defun AJUTATOR (args) nil)."""
    g, s = module_id(module_name), stub_id(module_name)
    forms = [f"(defun C:{c} () ({s}:Stub))" for c in cmds]
    forms += [f"(defun {n} ({' '.join(a)}) nil)" for n, a in helpers]
    out = []
    for i in range(0, len(forms), chunk):
        out.append(f"(if *{g}:OK* nil (progn\n  " + "\n  ".join(forms[i:i + chunk]) + "))\n")
    return "".join(out)


def guard_body(text, flag):
    """Fiecare forma de la nivelul de sus devine (if FLAG FORMA); comentariile raman pe loc."""
    out, last = [], 0
    for a, b in top_forms(text):
        out.append(text[last:a])
        out.append(f"(if {flag} {text[a:b]})")
        last = b
    out.append(text[last:])
    return "".join(out)


def footer(module_name):
    g = module_id(module_name)
    return f"""
{END_MARK}
(setq *{g}:OK* nil)
(princ)
"""


def inject(text: str, module_name: str, key: bytes = None, test_exe=None) -> str:
    """Sursa modulului cu poarta de licenta. key = secretul build-ului (32 de octeti).
    Fara key (dezvoltare / fara licentiere) textul ramane neschimbat (poarta dezactivata).
    test_exe: DOAR pentru teste - calea fixa a unui TopoKit.exe de test (build-ul nu o foloseste)."""
    if key is None:
        return text
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise ValueError("key trebuie sa fie 32 de octeti")
    if MARK in text:
        return text
    body = text if text.endswith("\n") else text + "\n"
    g = module_id(module_name)
    return (header(module_name, bytes(key), test_exe) + stubs(module_name, commands(text), stub_helpers(text))
            + BODY_MARK + "\n" + guard_body(body, f"*{g}:OK*") + footer(module_name))


def unguard(out, module_name):
    """Inversul lui inject (pentru teste): textul original al modulului din textul injectat."""
    g = module_id(module_name)
    start = out.index(BODY_MARK + "\n") + len(BODY_MARK) + 1
    end = out.rindex("\n" + END_MARK)
    body = out[start:end]
    flag = f"(if *{g}:OK* "
    res, last = [], 0
    for a, b in top_forms(body):
        res.append(body[last:a])
        form = body[a:b]
        assert form.startswith(flag) and form.endswith(")"), form[:80]
        res.append(form[len(flag):-1])
        last = b
    res.append(body[last:])
    return "".join(res)


if __name__ == "__main__":
    import os
    import sys
    k = os.urandom(32)
    for f in sys.argv[1:]:
        print(inject(pathlib.Path(f).read_text(encoding="utf-8"), f, k), end="")
