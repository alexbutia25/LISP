"""Ofuscarea surselor AutoLISP TopoKit inainte de compilare (.fas).

    from obfuscate import apply
    text = apply(text, key)        # key = secretul build-ului (32 de octeti); seed-ul ofuscarii

Scop: in .fas numele simbolurilor raman lizibile (TK:MainMenu, TKA:Generate ...), ceea ce
usureaza decompilarea. Acest modul redenumeste simbolurile INTERNE (functii definite cu defun
si variabile globale *...*) in nume scurte fara inteles ("_" + base36), CONSECVENT in toate
modulele (modulele se apeleaza intre ele) si in variantele en/ (aceeasi redenumire - acelasi
seed). Se aplica in tools/build_installer.py (module_source) INAINTE de lic_gate.inject, deci
doar la build-urile licentiate (compilate); la build-urile de dezvoltare (key=None) nu se aplica.

Ce NU se redenumeste (lista alba, construita automat)
  - comenzile c: (le tasteaza utilizatorul, apar in ribbon / stub-uri);
  - ORICE simbol la care se refera incarcatorul TopoKitLoad.lsp (ramane .lsp neofuscat:
    TK:Start, TKA:Generate, TKT:Menu, TKI:Run, *TK:VERSION* etc.);
  - ORICE simbol care apare intr-un sir literal, oriunde in surse / .dcl / incarcator /
    variantele en/ (siruri de actiune DCL "(TK:...)", argumente pentru eval / read, chei,
    nume construite dinamic): daca numele apare intr-un sir, pastrarea lui garanteaza ca
    referintele prin sir (action_tile, eval, read, startapp, load) continua sa gaseasca functia;
  - numele rezervate AutoCAD: *error*, S::STARTUP / S::* ;
  - numele generate de poarta de licenta (TKG-*, TKS-*) - oricum injectate DUPA ofuscare.

Strategia "redenumeste doar ce nu apare in niciun sir" acopera automat construirea dinamica de
nume (read / eval / action_tile / defun-q / vl-symbol-value): acele referinte sunt siruri, deci
simbolurile lor ajung in lista alba. Simbolurile ramase (apelate doar din cod, niciodata numite
intr-un sir) se redenumesc fara risc.

Numele noi: "_" + base36 (prefix care nu se poate ciocni cu functiile incorporate AutoLISP sau cu
simbolurile existente - niciun simbol din surse nu incepe cu "_"). Permutarea e determinista de
seed (key), deci acelasi build da aceeasi redenumire peste module; builduri diferite -> nume
diferite. Seed-ul nu se pastreaza nicaieri (os.urandom in build_installer).
"""
import hashlib
import pathlib
import random
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES = ["TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitTeren.lsp", "TopoKitInclinare.lsp",
           "TopoKitCad.lsp", "TopoKitProiect.lsp"]
LOADER = "TopoKitLoad.lsp"
DCL = ["TopoKit.dcl", "TopoKitAnexe.dcl", "TopoKitTeren.dcl", "TopoKitInclinare.dcl"]

# un "token" LISP: sir maxim de caractere care nu sunt delimitatori ( ) ' " ; sau spatiu.
# include * : _ - < > = + / . (ca sa prinda *TK:FOO*, vl-string->list, <= etc.)
TOKEN_RE = re.compile(r"[*A-Za-z0-9:_<>=+./\-]+")
DEFUN_RE = re.compile(r"\(\s*defun(?:-q)?\s+([^\s()'\";]+)", re.I)
# prefixul familiei TopoKit: TK urmat de litere, apoi ":" (TK:, TKA:, TKC:, TKI:, TKP:, TKT: ...),
# optional intre stele pentru globale (*TK:FOO*). NU TKL: (definit in incarcator, nu in module).
FAMILY_RE = re.compile(r"^\*?TK[A-Z]*:")
RESERVED = {"*ERROR*", "S::STARTUP"}


def _segments(text):
    """Imparte textul in bucati (kind, continut): 'code', 'string' (cu ghilimelele), 'comment'.
    Respecta comentariile ; si ;| |; si sirurile "..." (cu \\\" escapat)."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == ";":
            if text.startswith(";|", i):
                j = text.find("|;", i + 2)
                j = n if j < 0 else j + 2
            else:
                j = text.find("\n", i)
                j = n if j < 0 else j + 1
            yield ("comment", text[i:j])
            i = j
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            yield ("string", text[i:j])
            i = j
        else:
            j = i
            while j < n and text[j] not in ';"':
                j += 1
            yield ("code", text[i:j])
            i = j


def _code_tokens(text):
    out = []
    for kind, s in _segments(text):
        if kind == "code":
            out += TOKEN_RE.findall(s)
    return out


def _string_tokens(text):
    """Toate tokenurile (litere mari) care apar in sirurile literale - lista alba."""
    out = set()
    for kind, s in _segments(text):
        if kind == "string":
            inner = s[1:-1] if len(s) >= 2 else s
            out |= {t.upper() for t in TOKEN_RE.findall(inner)}
    return out


def _is_family(u):
    return bool(FAMILY_RE.match(u))


def _defined_symbols(text):
    """Simbolurile DEFINITE in modul care pot fi redenumite: numele defun din familia TK
    (fara c:, S::, *error*) si globalele *TK...* care apar in cod."""
    defs = set()
    for m in DEFUN_RE.findall(text):
        u = m.upper()
        if _is_family(u) and not u.startswith("C:") and not u.startswith("S::") and u not in RESERVED:
            defs.add(u)
    for tok in _code_tokens(text):
        u = tok.upper()
        if u.startswith("*") and u.endswith("*") and _is_family(u):
            defs.add(u)
    return defs


_SCAN = None


def _read(name, base=ROOT):
    return (pathlib.Path(base) / name).read_text(encoding="utf-8")


def scan(root=ROOT):
    """(rename_set, keep_set, all_tokens): ce se redenumeste, ce se pastreaza si de ce.
    rezultatul nu depinde de seed - se calculeaza o data si se pastreaza in memorie."""
    global _SCAN
    if _SCAN is not None and root == ROOT:
        return _SCAN
    root = pathlib.Path(root)
    candidates, whitelist, all_tokens = set(), set(RESERVED), set()

    # module (romana): candidatii + lista alba din siruri
    for f in MODULES:
        src = _read(f, root)
        candidates |= _defined_symbols(src)
        whitelist |= _string_tokens(src)
        all_tokens |= {t.upper() for t in _code_tokens(src)}

    # varianta engleza (generata de tools/i18n.py): doar sirurile pot diferi (mesaje traduse);
    # numele simbolurilor sunt identice. Best-effort - daca i18n nu merge, scanarea romana ajunge.
    try:
        import sys
        import tempfile
        sys.path.insert(0, str(root / "tools"))
        import i18n
        with tempfile.TemporaryDirectory(prefix="tkobf_en_") as td:
            i18n.build(pathlib.Path(td))
            for f in MODULES:
                p = pathlib.Path(td) / f
                if p.exists():
                    whitelist |= _string_tokens(p.read_text(encoding="utf-8"))
            for f in DCL:
                p = pathlib.Path(td) / f
                if p.exists():
                    whitelist |= {t.upper() for t in TOKEN_RE.findall(p.read_text(encoding="utf-8"))}
    except Exception:
        pass

    # fisierele .dcl (siruri de actiune "(TK:...)", chei): tot textul in lista alba
    for f in DCL:
        try:
            whitelist |= {t.upper() for t in TOKEN_RE.findall(_read(f, root))}
        except FileNotFoundError:
            pass

    # incarcatorul: ramane .lsp neofuscat, deci ORICE simbol la care se refera trebuie pastrat
    loader = _read(LOADER, root)
    whitelist |= {t.upper() for t in _code_tokens(loader)}
    whitelist |= _string_tokens(loader)

    # ribbon (make_ribbon.CMDS) + paginile Functii: numele comenzilor (c:) - oricum excluse, dar
    # le adaugam in lista alba pentru siguranta
    try:
        import sys
        sys.path.insert(0, str(root / "tools"))
        import make_ribbon
        whitelist |= {str(k).upper() for k in getattr(make_ribbon, "CMDS", {})}
        whitelist |= {str(k).upper() for k in getattr(make_ribbon, "ALIASES", {})}
        whitelist |= {str(v).upper() for v in getattr(make_ribbon, "ALIASES", {}).values()}
    except Exception:
        pass

    rename_set = {c for c in candidates if c not in whitelist}
    keep_set = {c for c in candidates if c in whitelist}
    res = (rename_set, keep_set, all_tokens)
    if root == ROOT:
        _SCAN = res
    return res


def _base36(n):
    if n == 0:
        return "0"
    d = "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = d[r] + s
    return s


_MAP_CACHE = {}


def mapping(seed, root=ROOT):
    """{NUME_ORIGINAL_MARE: nume_nou}. Determinista de seed (key). Numele noi: "_" + base36,
    permutate dupa seed. Garantat unice si fara coliziune cu simbolurile existente (prefix "_")."""
    key = bytes(seed)
    ck = (key, str(root))
    if ck in _MAP_CACHE:
        return _MAP_CACHE[ck]
    rename_set, _keep, all_tokens = scan(root)
    names = sorted(rename_set)
    rng = random.Random(hashlib.sha256(b"TKOBF|" + key).digest())
    idx = list(range(len(names)))
    rng.shuffle(idx)
    m, used = {}, set()
    for i, name in enumerate(names):
        new = "_" + _base36(idx[i])
        assert new not in used and new.upper() not in all_tokens, new   # fara coliziune
        used.add(new)
        m[name] = new
    _MAP_CACHE[ck] = m
    return m


def rename(text, m, strip=True):
    """Redenumeste in text tokenurile din m (dupa litere mari), doar in cod (nu in siruri /
    comentarii). strip=True: scoate comentariile si liniile goale (FAS oricum pierde comentariile;
    ajuta calea en/). Restul textului ramane neschimbat octet cu octet."""
    out = []
    for kind, s in _segments(text):
        if kind == "string":
            out.append(s)
        elif kind == "comment":
            out.append("\n" if strip else s)      # pastreaza separarea tokenurilor
        else:
            out.append(TOKEN_RE.sub(lambda mo: m.get(mo.group(0).upper(), mo.group(0)), s))
    res = "".join(out)
    if strip:
        lines = [ln.rstrip() for ln in res.splitlines()]
        res = "\n".join(ln for ln in lines if ln.strip()) + "\n"
    return res


def apply(text, seed, root=ROOT, strip=True):
    """Sursa unui modul ofuscata. seed = key (secretul build-ului). Aceeasi redenumire in toate
    modulele si variantele en/ pentru acelasi seed."""
    return rename(text, mapping(seed, root), strip=strip)


def report(seed=b"\x00" * 32, root=ROOT):
    """Statistici (pentru teste / linia de comanda): cate simboluri se redenumesc vs se pastreaza."""
    rename_set, keep_set, _all = scan(root)
    m = mapping(seed, root)
    return {"renamed": len(rename_set), "kept": len(keep_set),
            "rename_set": sorted(rename_set), "keep_set": sorted(keep_set), "map": m}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        r = report()
        print(f"redenumite: {r['renamed']}   pastrate (in lista alba): {r['kept']}")
        print("exemple redenumite:", r["rename_set"][:10])
        print("exemple pastrate:  ", r["keep_set"][:10])
    else:
        import os
        k = os.urandom(32)
        for f in sys.argv[1:]:
            print(apply(pathlib.Path(f).read_text(encoding="utf-8"), k), end="")
