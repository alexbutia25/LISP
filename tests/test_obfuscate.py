#!/usr/bin/env python3
"""Teste offline pentru ofuscarea surselor AutoLISP (tools/obfuscate.py), fara AutoCAD.

    python tests/test_obfuscate.py

Verifica:
  - lista alba / de redenumit: comenzile c:, simbolurile din incarcator, cele din siruri (DCL,
    action_tile, eval / read), *error*, S::* raman; restul simbolurilor interne se redenumesc;
  - redenumire determinista de seed si CONSECVENTA peste toate modulele (o functie definita intr-un
    modul e apelata cu acelasi nume nou in celelalte) si in varianta en/;
  - ofuscarea atinge doar codul, nu sirurile / comentariile (numele pastrate raman in siruri);
  - pipeline-ul din build_installer.module_source: ofuscare -> lic_gate.inject -> compiled_source
    pastreaza comenzile c: si referintele "<fmt>\\\\X.fas";
  - incarcarea in simulator (tests/acad_sim + autolisp_mini) a intregului lant ofuscat (TopoKit
    incarca Anexe / Teren / Inclinare / Cad / Proiect): Stereo70->WGS84 pe punctele de control
    (ca tests/run_tests.py), lungimea listelor DCL si comanda IMPPCT (ca tests/test_teren.py),
    toate prin numele noi (dovada ca redenumirea nu a stricat apelurile intre module);
  - fara constructie dinamica de nume de simbol interne (read / eval pe siruri strcat).
"""
import math, os, pathlib, re, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(__file__))
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import obfuscate as O
import lic_gate
import build_installer as B

SEED = bytes(range(32))                      # seed fix pentru teste (in build e os.urandom(32))
MODULES = O.MODULES


def tok_set(text):
    """Tokenurile de cod (litere mari), fara siruri / comentarii."""
    return {t.upper() for t in O._code_tokens(text)}


# ================================================================ 1. lista alba / de redenumit
rename_set, keep_set, all_tokens = O.scan()
assert len(rename_set) > 700, len(rename_set)
assert not (rename_set & keep_set)
# comenzile c: nu sunt niciodata candidate (nu se redenumesc)
assert not any(n.startswith("C:") for n in rename_set | keep_set)
# numele rezervate nu se redenumesc
for r in ("*ERROR*", "S::STARTUP"):
    assert r not in rename_set
# punctele de intrare la care se refera incarcatorul TopoKitLoad.lsp raman
for entry in ("TK:START", "TKA:GENERATE", "TKT:MENU", "TKI:RUN", "*TK:VERSION*"):
    assert entry in keep_set, entry
    assert entry not in rename_set, entry
# functiile numite in sirurile de actiune DCL raman (altfel action_tile "(...)" nu le-ar gasi)
for s in ("TK:MAINSAVE", "TKA:SIDESAPPLY", "TK:ABOUT", "*TKA:F_EXEC*", "TK:READCADRUTILES"):
    assert s in keep_set, s
# helperele pur interne se redenumesc
for s in ("TK:TAN", "TK:ASIN", "TK:STOP", "TK:ERROR", "TK:CROSS"):
    assert s in rename_set, s
# niciun nume nou nu se ciocneste cu un simbol existent (prefix "_", inexistent in surse)
m = O.mapping(SEED)
assert all(v.startswith("_") for v in m.values())
assert len(set(m.values())) == len(m), "nume noi unice"
assert not (set(all_tokens) & {v.upper() for v in m.values()}), "nume nou = simbol existent"
print(f"lista alba: {len(rename_set)} redenumite, {len(keep_set)} pastrate (c:, incarcator, siruri DCL, *error*)")

# ================================================================ 2. determinism + consecventa
t0 = (ROOT / "TopoKit.lsp").read_text(encoding="utf-8")
assert O.apply(t0, SEED) == O.apply(t0, SEED), "determinista pentru acelasi seed"
assert O.apply(t0, SEED) != O.apply(t0, bytes(range(1, 33))), "seed diferit -> alta redenumire"

# o functie definita in TopoKit.lsp (TK:Error) si apelata in TopoKitAnexe.lsp (din *error*) primeste
# acelasi nume nou
assert "TK:ERROR" in rename_set
new = m["TK:ERROR"]
ob_topokit = O.apply(t0, SEED)
ob_anexe = O.apply((ROOT / "TopoKitAnexe.lsp").read_text(encoding="utf-8"), SEED)
assert new.upper() in tok_set(ob_topokit), "definitia redenumita in TopoKit"
assert new.upper() in tok_set(ob_anexe), "apelul redenumit la fel in TopoKitAnexe"
assert "TK:ERROR" not in tok_set(ob_topokit) and "TK:ERROR" not in tok_set(ob_anexe), "numele vechi dispare din cod"
print(f"consecvent intre module: TK:Error -> {new} in TopoKit.lsp si TopoKitAnexe.lsp")

# varianta en/ (generata de i18n) primeste ACEEASI redenumire
import i18n
with tempfile.TemporaryDirectory(prefix="tkobf_en_") as td:
    i18n.build(pathlib.Path(td))
    en_anexe = (pathlib.Path(td) / "TopoKitAnexe.lsp").read_text(encoding="utf-8")
    ob_en_anexe = O.apply(en_anexe, SEED)
    assert new.upper() in tok_set(ob_en_anexe), "en/ foloseste acelasi nume nou"
    assert "TK:ERROR" not in tok_set(ob_en_anexe), "numele vechi dispare si din en/"
print("varianta en/: aceeasi redenumire ca romana")

# ================================================================ 3. doar codul, nu sirurile
# un nume pastrat ramane in sir (sirul de actiune DCL din TK:DclLines / action_tile)
assert "(TK:MainSave)" in t0 and "(TK:MainSave)" in ob_topokit, "sirul DCL cu numele pastrat ramane neatins"
# un nume redenumit nu mai apare deloc ca token de cod, dar numele modulelor din siruri raman
assert '"TopoKitAnexe.lsp"' in ob_topokit, "numele fisierului modul (sir) ramane pentru compiled_source"
# comentariile sunt scoase (strip implicit)
assert ";;" not in ob_topokit, "comentariile ;; scoase"
print("ofuscarea atinge doar codul: sirurile DCL si numele de fisier raman, comentariile dispar")

# ================================================================ 4. pipeline module_source
for fmt in B.FAS_FORMATS:
    out = B.module_source(t0, "TopoKit", fmt, SEED)                  # ofuscare -> inject -> compiled_source
    assert lic_gate.MARK in out, "poarta de licenta injectata"
    assert f'"{fmt}\\\\TopoKitAnexe.fas"' in out, "referintele intre module -> .fas"
    # comenzile c: raman (numele comenzii neschimbat), de ex. c:TOPOKIT
    assert re.search(r"\(defun\s+c:TOPOKIT\b", out, re.I), "comanda c:TOPOKIT pastrata"
    assert new.upper() not in tok_set(B.compiled_source(t0, fmt)), "fara ofuscare numele vechi exista"
# fara key (dezvoltare) nu se ofusca
assert B.module_source(t0, "TopoKit", "fas5", None) == B.compiled_source(lic_gate.inject(t0, "TopoKit", None), "fas5")
print("pipeline: ofuscare -> inject -> compiled_source; comenzile c: si referintele .fas pastrate; fara key = neschimbat")

# ================================================================ 5. incarcare in simulator
from acad_sim import Acad, Sym, call
import autolisp_mini as MM

OUT = tempfile.mkdtemp(prefix="topokit_obf_")
OBF = pathlib.Path(tempfile.mkdtemp(prefix="topokit_obfsrc_"))
for f in MODULES:
    (OBF / f).write_text(O.apply((ROOT / f).read_text(encoding="utf-8"), SEED), encoding="utf-8")

acad = Acad(str(ROOT), OUT)
# modulele .lsp vin din folderul ofuscat; restul (.dcl, .gsb, anexe) din ROOT
_mods = set(MODULES)
_orig_path = acad.path
def _path(p):
    base = os.path.basename(str(p).replace("\\", "/"))
    return str(OBF / base) if base in _mods else _orig_path(p)
acad.path = _path

MM.load(str(OBF / "TopoKit.lsp"))      # incarca intreg lantul ofuscat (Anexe/Teren/Inclinare/Cad/Proiect)
acad.after_load()
assert any("TopoKit Teren incarcat" in o for o in acad.out), acad.out[-5:]

# numele interpretorului sunt cu litere mari (autolisp_mini.atom: Sym(t.upper())); numele noi sunt
# cu litere mici (base36), deci in simulator apar cu litere mari. AutoLISP e oricum insensibil la
# litere, deci numele mici din product sunt corecte - aici doar le cautam cu litere mari.
def new_sym(name):
    return Sym(m.get(name.upper(), name.upper()).upper())


# alias: ca testul (harness) sa poata apela functiile interne pe numele VECHI. Apelurile INTRE
# module folosesc deja numele noi (ambele parti redenumite) - aliasul e doar pentru test.
for orig, nw in m.items():
    so, sn = Sym(orig.upper()), Sym(nw.upper())
    if sn in MM.funcs:
        MM.funcs[so] = MM.funcs[sn]
    if sn in MM.env:
        MM.env[so] = MM.env[sn]
# TK:Run simulat (after_load l-a pus pe numele vechi) trebuie vazut si sub numele nou
if "TK:RUN" in m and Sym("TK:RUN") in MM.env:
    MM.env[new_sym("TK:RUN")] = MM.env[Sym("TK:RUN")]


def ofn(name, *a):
    return call(new_sym(name), list(a))


def oenv(name, val):
    MM.env[new_sym(name)] = val
    MM.env[Sym(name.upper())] = val


# 5a. Stereo70 -> WGS84 pe punctele de control (aceleasi valori ca tests/run_tests.py)
known = [((500000, 500000), (24.998445775149445, 45.99971818665659)),
         ((588000, 325000), (26.10355990247839, 44.419369931978245)),
         ((400000, 700000), (23.663689203941257, 47.79141542227441))]
for (en, ll) in known:
    r = ofn("TK:Stereo70ToWGS84", [float(en[0]), float(en[1])])
    assert abs(r[0] - ll[0]) < 1e-8 and abs(r[1] - ll[1]) < 1e-8, (en, r, ll)
print("Stereo70->WGS84 pe lantul ofuscat: identic cu valorile de control")

# 5b. lungimea listelor DCL = numarul de linii din fisierul .dcl (sirurile au supravietuit)
for dcl, fnname in (("TopoKit.dcl", "TK:DclLines"), ("TopoKitTeren.dcl", "TKT:DclLines"),
                    ("TopoKitAnexe.dcl", "TKA:DclLines")):
    lines = ofn(fnname)
    want = (ROOT / dcl).read_text(encoding="utf-8").splitlines()
    assert isinstance(lines, list) and len(lines) == len(want), (fnname, len(lines), len(want))
print("listele DCL (TK/TKT/TKA:DclLines) au exact lungimea fisierelor .dcl")

# 5c. comanda IMPPCT (ca tests/test_teren.py): fisier de puncte -> entitati POINT
oenv("*TK:USEGRID*", "0")
E0, N0 = 545000.0, 458000.0
pts = []
nr = 0
for j in range(5):
    for i in range(5):
        nr += 1
        pts.append((nr, i * 5.0, j * 5.0, 500.0 + 0.1 * (i + j), ""))
fpts = os.path.join(OUT, "puncte.txt")
with open(fpts, "w", encoding="utf-8") as fh:
    fh.write("Nr;X;Y;Z;Cod\n")
    for p in pts:
        fh.write(f"{p[0]};{N0 + p[2]:.3f};{E0 + p[1]:.3f};{p[3]:.3f};{p[4]}\n".replace(".", ","))
acad.inputs = [("file", fpts)]
ofn("c:IMPPCT")
P = [e for e in acad.entities("Model", "POINT")]
assert len(P) == 25, len(P)
print(f"comanda IMPPCT pe lantul ofuscat: {len(P)} puncte importate corect")

# ================================================================ 6. fara constructie dinamica de nume
for f in MODULES:
    src = (ROOT / f).read_text(encoding="utf-8")
    assert not re.search(r'\((?:read|eval|set)\b[^\n]*?\(strcat\s+"\*?TK', src, re.I), \
        f"{f}: construieste dinamic un nume TK (ar scapa ofuscarii)"
print("fara (read/eval (strcat \"TK...\")): nicio construire dinamica de nume intern")

shutil.rmtree(OUT, ignore_errors=True)
shutil.rmtree(str(OBF), ignore_errors=True)
print("\nToate testele ofuscarii au trecut.")
