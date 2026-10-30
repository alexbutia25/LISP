#!/usr/bin/env python3
"""Teste offline pentru TopoKitCad.lsp (cadastru: detasari, suprafete, cote, suma,
puncte TopoLT, import / export coordonate).

    python3 tests/test_cad.py
"""
import os, sys, math, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from acad_sim import Acad, Sym, call, env, grp, grps, DP, T
import autolisp_mini as M

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.environ.get("TOPOKIT_OUT") or tempfile.mkdtemp(prefix="topokit_cad_")
acad = Acad(ROOT, OUT)

# ---------------------------------------------------------------- completari ale simulatorului
acad.tables["BLOCK"] = {}
_inblock = [None]
_entmake = acad.entmake
def entmake(d=None):
    typ = grp(list(d), 0)
    if typ == "BLOCK":
        _inblock[0] = grp(list(d), 2); acad.tables["BLOCK"][_inblock[0].upper()] = list(d); return d
    if typ == "ENDBLK":
        _inblock[0] = None; return d
    if _inblock[0]:
        return d                                   # entitatile din definitia blocului
    return _entmake(d)
def entmod(d):
    e = grp(d, -1)
    acad.db[e] = [x for x in d if not (isinstance(x, DP) and x.car in (-1, 5))]
    return d
def entlast():                                     # ca in AutoCAD: ultima entitate principala
    return next((e for e in reversed(acad.order)
                 if e not in acad.deleted and grp(acad.db[e], 0) not in ("ATTRIB", "SEQEND")), None)
def entsel(msg=None):
    """(ename, punct) = clic pe obiect in punctul dat; altfel ca in simulator"""
    if acad.inputs and isinstance(acad.inputs[0][1], tuple):
        kind, val = acad.inputs.pop(0)
        assert kind == "entsel", (kind, msg)
        acad.vars["ERRNO"] = 0
        return [val[0], [val[1][0], val[1][1], 0.0]]
    return acad.entsel(msg)
_match = acad.match
def match(e, flt):
    flt = list(flt or [])
    for i, f in enumerate(flt):
        if isinstance(f, DP) and f.car == -4 and f.cdr == "&=":
            mask = flt[i + 1].cdr
            if (grp(acad.db[e], 70) or 0) & mask != mask: return False
            return _match(e, flt[:i] + flt[i + 2:])
    return _match(e, flt)
acad.match = match
for k, v in {"ENTMAKE": entmake, "ENTMOD": entmod, "ENTLAST": entlast, "ENTSEL": entsel,
             "REGAPP": lambda n: n, "ENTUPD": lambda e: e, "GRDRAW": lambda *a: None, "REDRAW": lambda *a: None,
             "TEXTSCR": lambda: None, "SSSETFIRST": lambda *a: None,
             "SSADD": lambda e=None, ss=None: (ss if ss is not None else []) + ([e] if e else []),
             "GETINT": lambda *a: acad.ask("int")}.items():
    M.funcs[Sym(k)] = v

M.load(os.path.join(ROOT, "TopoKit.lsp"))          # incarca si TopoKitCad.lsp
acad.after_load()
assert any("TopoKit Cadastru incarcat" in o for o in acad.out), acad.out[-3:]


def fn(name, *a): return call(Sym(name.upper()), list(a))
def area(pts): return abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1]))) / 2
def ents(typ, layer=None):
    return [e for e in acad.entities("Model", typ) if layer is None or (grp(acad.db[e], 8) or "") == layer]
def pline(pts, layer="PARCELE"):
    acad.entmake([DP(0, "LWPOLYLINE"), DP(100, "AcDbEntity"), DP(8, layer), DP(100, "AcDbPolyline"),
                  DP(90, len(pts)), DP(70, 1)] + [[10, float(x), float(y)] for x, y in pts])
    return acad.order[-1]


# ---------------------------------------------------------------- calculele detasarii
R = [[0.0, 0.0], [100.0, 0.0], [100.0, 50.0], [0.0, 50.0]]
res = fn("TKC:DetHP", R, [0.0, 1.0], 1234.56)              # paralela cu latura de jos
assert abs(area(res[0]) - 1234.56) < 1e-6 and abs(area(res[1]) - (5000 - 1234.56)) < 1e-6
cut = res[2]
assert len(cut) == 1 and abs(cut[0][0][1] - 12.3456) < 1e-6 and abs(cut[0][1][1] - 12.3456) < 1e-6, cut
# punct obligat (in CadTopo dadea eroare: ct:sub era suprascrisa de functia de meniu)
L = [[0.0, 0.0], [80.0, 0.0], [80.0, 30.0], [30.0, 30.0], [30.0, 70.0], [0.0, 70.0]]
F = [50.0, 0.0]
res = fn("TKC:DetPO", L, F, 0, T, 900.0)
assert abs(area(res[0]) - 900.0) < 1e-6 and abs(area(res[1]) - (area(L) - 900.0)) < 1e-6
assert res[2][0][0] == F, res[2]
# detasari multiple: suprafetele cerute si restul
mres = fn("TKC:MDetHP", R, [0.0, 1.0], [1000.0, 1500.0, 800.0])
assert [round(area(p[0]), 6) for p in mres[0]] == [1000.0, 1500.0, 800.0], [area(p[0]) for p in mres[0]]
assert abs(area(mres[1]) - 1700.0) < 1e-6
mpo = fn("TKC:MDetPO", L, F, 0, T, [500.0, 700.0])
assert [round(area(p[0]), 6) for p in mpo[0]] == [500.0, 700.0]
# poligon neconvex (U): linia taie conturul de 4 ori -> doua bucati de taietura, suprafata corecta
U = [[0.0, 0.0], [90.0, 0.0], [90.0, 60.0], [60.0, 60.0], [60.0, 20.0], [30.0, 20.0], [30.0, 60.0], [0.0, 60.0]]
res = fn("TKC:DetHP", U, [0.0, 1.0], 2400.0)
assert abs(area(res[0]) - 2400.0) < 1e-6 and len(res[2]) == 2, res[2]
assert all(abs(c[0][1] - c[1][1]) < 1e-9 for c in res[2])
assert sorted(tuple(sorted(round(p[0], 6) for p in c)) for c in res[2]) == [(0.0, 30.0), (60.0, 90.0)], res[2]
print("Detasare: paralela, punct obligat (eroarea din CadTopo corectata), multipla, poligon neconvex")

# ---------------------------------------------------------------- TKDETASARE in desen
E0, N0 = 588000.0, 325000.0
pe = pline([(E0 + x, N0 + y) for x, y in R])
acad.inputs = [("kw", "PAralela"), ("entsel", (pe, [E0 + 50.0, N0 + 0.2])), ("real", 2000.0),
               ("str", "17"), ("str", "Popescu Ion")]
fn("c:TKDETASARE")
assert not acad.inputs, acad.inputs
P = ents("LWPOLYLINE", "PARCELE")
assert pe in acad.deleted and len(P) == 2, P
areas = sorted(round(area(acad.verts(e)), 4) for e in P)
assert areas == [2000.0, 3000.0], areas
low = min(P, key=lambda e: min(v[1] for v in acad.verts(e)))
assert abs(area(acad.verts(low)) - 2000.0) < 1e-4                      # dinspre latura aleasa (jos)
lab = [grp(acad.db[e], 1) for e in ents("TEXT", "Suprafete")]
assert "17" in lab and "Popescu Ion" in lab and "2000.00mp" in lab, lab
assert call(Sym("VLAX-LDATA-GET"), ["TOPOKIT", "NRPAR"]) == 17
print("TKDETASARE: polilinia rupta in 2000 + 3000 mp, eticheta cu numar, proprietar si suprafata")

# ---------------------------------------------------------------- suprafete, cote, suma
sq = pline([(E0 + 200, N0), (E0 + 240, N0), (E0 + 240, N0 + 25), (E0 + 200, N0 + 25)], "S")
acad.inputs = [("ssget", [sq])]
fn("c:TKSUPRAF")
st = [e for e in ents("TEXT", "Suprafete") if grp(acad.db[e], 1) == "S=1000.00 mp"]
assert len(st) == 1 and abs(grp(acad.db[st[0]], 11)[0] - (E0 + 220)) < 1e-6, st
acad.inputs = [("ssget", [sq])]
fn("c:TKCOTE")
ct = ents("TEXT", "Dimensions")
assert sorted(grp(acad.db[e], 1) for e in ct) == ["25.00m", "25.00m", "40.00m", "40.00m"]
bottom = [e for e in ct if abs(grp(acad.db[e], 11)[0] - (E0 + 220)) < 1e-6 and grp(acad.db[e], 11)[1] < N0]
assert len(bottom) == 1, "cota laturii de jos trebuie sa fie sub poligon (spre exterior)"
for s, v in [("S=500mp", 500.0), ("{\\fArial|b0|i0;12.5}", 12.5), ("Lot 3 S=1234.56 mp", 1234.56),
             ("12,5 m", 12.5), ("-3.2", -3.2), ("abc", None), ("\\A1;7.94m", 7.94),
             ("S=1.234,5 mp", 1234.5), ("S=1,234.5", 1234.5)]:
    r = fn("TKC:Num", s)
    assert (r is None and v is None) or abs(r - v) < 1e-9, (s, r)
print("TKSUPRAF, TKCOTE (spre exterior), TKSUMA: S= dupa '=', MTEXT formatat, virgula zecimala")

# ---------------------------------------------------------------- puncte TopoLT
fn("TKC:CfgAll")
e1 = fn("TKC:MkPct", [E0 + 1.0, N0 + 2.0], "pt2", 85.5, "Grf")
assert fn("TKC:IsP", e1) and fn("TKC:Att", e1, "DENPCT") == "pt2" and fn("TKC:Att", e1, "COTA") == "85.500"
tx = fn("TKC:NrTxt", e1)
assert tx and grp(acad.db[tx], 1) == "pt2" and grp(acad.db[tx], 8) == "0_pnt_number"
fn("TKC:SetNr", e1, "pt3")
assert fn("TKC:Att", e1, "DENPCT") == "pt3" and grp(acad.db[tx], 1) == "pt3"
fn("TKC:MkPct", [E0 + 5.0, N0 + 5.0], "pt10", 86.0, "Grf")
fn("TKC:MkPct", [E0 + 9.0, N0 + 9.0], "pt9", 86.0, "Gard")
lst = fn("TKC:Pcts", None)
assert [a[1] for a in fn("TKC:SortPcts", lst)] == ["pt3", "pt9", "pt10"]     # ordine naturala
assert fn("TKC:NextNr", "pt", lst) == "pt11" and fn("TKC:NrLa", [E0 + 5.01, N0 + 5.0], lst) == "pt10"
print("Puncte TopoLT: bloc Punct + atribute + text legat prin XDATA, renumerotare, ordine naturala pt2 < pt10")

# ---------------------------------------------------------------- import / export coordonate
f = os.path.join(OUT, "pct.txt")
open(f, "w").write("Nr;X;Y;Z;Cod\n101;325100,125;588300,250;90,5;Borna\n102;325110,000;588310,000;91,0\nx;y\n")
acad.inputs = [("file", f)]
fn("c:TKIMPPCT")
imp = {a[1]: a for a in fn("TKC:Pcts", None)}
assert abs(imp["101"][2] - 588300.25) < 1e-9 and abs(imp["101"][3] - 325100.125) < 1e-9 and imp["101"][5] == "Borna"
assert imp["102"][5] == "Grf" and abs(imp["102"][4] - 91.0) < 1e-9          # cod implicit
out = os.path.join(OUT, "exp.txt")
acad.inputs = [("ssget", None), ("file", out)]
fn("c:TKEXPPCT")
rows = open(out).read().splitlines()
assert rows[0].startswith("101,325100.125,588300.250,90.500,Borna"), rows[:2]
assert [r.split(",")[0] for r in rows] == ["101", "102", "pt3", "pt9", "pt10"], rows
assert fn("TKC:Fields", "1,500000.123,325000.456")[1] == ["1", "500000.123", "325000.456"]
print("TKIMPPCT (separator ';', virgula zecimala, cod implicit), TKEXPPCT (ordine naturala)")

# ---------------------------------------------------------------- renumerotare cu verificarea dublurilor
p9 = imp["102"][0]
acad.inputs = [("int", 101), ("str", ""), ("entsel", (p9, [0, 0])), ("kw", "Nu"), ("entsel", None)]
acad.vars["ERRNO"] = 0
fn("c:TKRENUM")
assert fn("TKC:Att", p9, "DENPCT") == "102", "numarul existent nu trebuie folosit fara confirmare"
print("TKRENUM: avertizeaza cand numarul exista deja la alt punct")

# ---------------------------------------------------------------- setari in desen
env[Sym("*TKC:CFG*")] = None
assert fn("TKC:Cfg", "SCARA") == 1000.0 and abs(env[Sym("*TKC:TXTH*")] - 1.2) < 1e-12
env[Sym("*TKC:CFG*")] = [DP(k, (500.0 if k == "SCARA" else v)) for k, v in
                         ((x.car, x.cdr) for x in fn("TKC:CfgAll"))]
fn("TKC:SaveCfg")
env[Sym("*TKC:CFG*")] = None
assert fn("TKC:Cfg", "SCARA") == 500.0 and abs(env[Sym("*TKC:TXTH*")] - 0.6) < 1e-12
print("TKCADSET: setarile (mm pe hartie x scara) se pastreaza in desen")
print("\nToate testele TopoKitCad au trecut.")
