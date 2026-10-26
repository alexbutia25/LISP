#!/usr/bin/env python3
"""Teste offline pentru TopoKitInclinare.lsp (planul de inclinare / verticalitate).

    python3 tests/test_inclinare.py [--render folder]

Valorile de referinta sunt cele ale programului original Plan Inclinare (Python)
pentru tests/data/inclinare_siloz.csv: portarea AutoLISP produce exact acelasi
desen (aceleasi linii, cercuri, texte si aceeasi planșa).
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from acad_sim import Acad, Sym, call, env, grp, DP, T
import autolisp_mini as M

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
args = sys.argv[1:]
RENDER = args[args.index("--render") + 1] if "--render" in args else None
OUT = os.environ.get("TOPOKIT_OUT") or tempfile.mkdtemp(prefix="topokit_incl_")
CSV = os.path.join(ROOT, "tests", "data", "inclinare_siloz.csv")

acad = Acad(ROOT, OUT)
reg = {}
M.funcs[Sym("VL-REGISTRY-READ")] = lambda k, n=None: reg.get(n)
M.funcs[Sym("VL-REGISTRY-WRITE")] = lambda k, n=None, v=None: reg.__setitem__(n, v) or v
M.load(os.path.join(ROOT, "TopoKit.lsp"))          # incarca automat si modulul de inclinare
acad.after_load()
assert any("TopoKit Inclinare incarcat" in o for o in acad.out), acad.out[-5:]


def fn(name, *a): return call(Sym(name.upper()), list(a))
def ents(typ): return [e for e in acad.entities("Model", typ) if grp(acad.db[e], 8) == "PLAN_INCLINARE"]


# ---------------------------------------------------------------- calculul (fata de programul original)
pts = fn("TKI:FromFile", CSV)
assert len(pts) == 49 and pts[0] == ["64", 2000.5138, 1001.766, 15.8133, "spate"], pts[0]
assert fn("TKI:Codes", pts) == ["dreapta", "spate", "stanga"]
rows = fn("TKI:Compute", pts)
ref = {"stanga": (20, 0.27899, 15.6699, 1), "dreapta": (21, 0.15349, 15.4534, -1)}
for row in rows:
    cod, n, top, sign = row[0][0], len(row[1]), row[3], row[2]
    rn, rv, rh, rs = ref[cod]
    assert n == rn and abs(top[4] - rv) < 5e-5 and abs(top[1] - rh) < 5e-4 and sign == rs, (cod, n, top[4], top[1], sign)
assert fn("TKI:FmtVal", rows[0][3][4]) == "27.9 cm" and fn("TKI:FmtVal", rows[1][3][4]) == "15.3 cm"
fn("TKI:Set", "abatere", "proiectata")
rows_p = fn("TKI:Compute", pts)
assert [fn("TKI:FmtVal", r[3][4]) for r in rows_p] == ["20.6 cm", "6.9 cm"]
fn("TKI:Set", "abatere", "totala")
# un singur rand: directia nu se poate deduce (mesaj), aplecare implicita spre dreapta
fn("TKI:Set", "rand2", "||auto")
assert len(fn("TKI:Compute", pts)) == 1 and "directia nu se poate deduce" in env[Sym("*TKI:MSGS*")][0]
fn("TKI:Set", "rand2", "dreapta|PARTEA DREAPTA|auto")
# potrivirea codurilor
assert fn("TKI:Match", "Stanga_1", "stanga", "incepe cu") and not fn("TKI:Match", "x_stanga", "stanga", "incepe cu")
assert fn("TKI:Match", "x_stanga", "dr, stanga", "contine") and not fn("TKI:Match", "stanga1", "stanga", "exact")
assert fn("TKI:Guess", ["D_1", "S_1", "spate"]) == ["S_1", "D_1", "spate"]
print("Calcul: abaterile totale si proiectate, directia si potrivirea codurilor ca in programul original")

# ---------------------------------------------------------------- planșa: autofit
lay = fn("TKI:Layout", rows)
assert lay[1] == ["A4", "portret", 100, T] and len(lay[0]) == 207, (lay[1], len(lay[0]))
bb = fn("TKI:BBox", lay[0])
assert [round(v, 3) for v in bb] == [0.0, 0.0, 21.0, 29.7], bb
fn("TKI:Set", "prioritate", "format mic"); fn("TKI:Set", "orientare", "peisaj"); fn("TKI:Set", "text_mm", "3.5")
assert fn("TKI:Layout", rows)[1] == ["A3", "peisaj", 200, T]
for k, v in (("prioritate", "scara mare"), ("orientare", "auto"), ("text_mm", "1.8")): fn("TKI:Set", k, v)
print("Plansa: A4 portret 1:100 ales automat; prioritatea 'format mic' alege A3 peisaj 1:200")

# ---------------------------------------------------------------- comanda INCLINARE (fisier, dialog, desen)
env[Sym("*TKI:CFG*")] = None
acad.inputs = [("ssget", None), ("file", CSV), ("pt", [1000.0, 2000.0, 0.0])]
errs = []
acad.dcl.scripts = {"tki_main": [[("set", "eb_zec", "9"), ("click", "accept"), lambda d: errs.append(d.cur["tiles"]["error"]),
                                   ("set", "eb_zec", "1"),
                                   ("set", "eb_ben", "Beneficiar SRL"), ("click", "accept")]]}
fn("c:INCLINARE")
assert not acad.inputs, acad.inputs
snap = acad.dcl.snapshots["tki_main"]
assert "49 puncte" in snap["tiles"]["tx_pct"] and "stanga: 27.9 cm spre dreapta" in snap["tiles"]["tx_rez"], snap["tiles"]
assert snap["tiles"]["tx_plansa"] == "Plansa A4 portret, scara 1:100" and errs == ["Zecimale: 0...4."], (snap["tiles"]["tx_plansa"], errs)
assert snap["lists"]["pl_cod1"] == ["<coduri>", "dreapta", "spate", "stanga"]
assert len(ents("LWPOLYLINE")) == 3 + 2 + 3 and len(ents("CIRCLE")) == 41, (len(ents("LWPOLYLINE")), len(ents("CIRCLE")))
txt = [grp(acad.db[e], 1) for e in ents("TEXT")]
assert "PLAN INCLINARE SILOZ" in txt and "Beneficiar SRL" in txt and "Abatere la varf: 27.9 cm" in txt, txt[:10]
frame = [e for e in ents("LWPOLYLINE") if grp(acad.db[e], 62) == 8][0]
assert grp(acad.db[frame], 10) == [1000.0, 2000.0], grp(acad.db[frame], 10)     # coltul foii in punctul ales
assert reg.get("beneficiar") == "Beneficiar SRL" and reg.get("rand1", "").startswith("stanga|")
print("INCLINARE: puncte din fisier, dialog (validare, rezultat, plansa), desen pe stratul PLAN_INCLINARE, setari pastrate")

# coduri nepotrivite: dialogul propune codurile gasite
reg.clear(); env[Sym("*TKI:CFG*")] = None
pts2 = [[p[0], p[1], p[2], p[3], {"stanga": "S_1", "dreapta": "D_1"}.get(p[4], p[4])] for p in pts]
env[Sym("*TKI:PTS*")] = pts2
fn("TKI:Set", "rand1", "nimic|A|auto"); fn("TKI:Set", "rand2", "||auto")
acad.dcl.scripts = {"tki_main": [[("click", "cancel")]]}
fn("TKI:Dialog")
snap = acad.dcl.snapshots["tki_main"]
assert snap["tiles"]["eb_cod1"] == "S_1" and snap["tiles"]["eb_cod2"] == "D_1" and snap["tiles"]["eb_cod3"] == "spate"
lines = fn("TKI:DclLines")
assert lines == open(os.path.join(ROOT, "TopoKitInclinare.dcl"), encoding="utf-8").read().splitlines()
print("Dialog: propunerea codurilor (S_1 / D_1 / spate), copia DCL identica")

if RENDER:
    from render_layout import render_model
    from dcl_mockup import Mockup
    os.makedirs(RENDER, exist_ok=True)
    render_model(acad, os.path.join(RENDER, "inclinare_plan.png"), (1000.0, 2000.0, 1021.0, 2029.7), 30.0)
    Mockup(open(os.path.join(ROOT, "TopoKitInclinare.dcl"), encoding="utf-8").read(), "tki_main",
           snap).render(os.path.join(RENDER, "macheta_inclinare.png"))
    print("Imagini:", RENDER)
print("\nToate testele TopoKitInclinare au trecut.")
