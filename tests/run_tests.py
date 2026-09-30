#!/usr/bin/env python3
"""Teste offline pentru TopoKit.lsp (fara AutoCAD).

    python3 tests/run_tests.py

Verifica: incarcarea fisierului, conversia Stereo 70 -> WGS84 (fata de PROJ,
daca pyproj este instalat), comanda ADDVTX pe o baza de date de entitati
simulata (linii, arce, contacte in T, suprapuneri, polilinii 3D), caroiajul
si validitatea XML a fisierului KML generat.
"""
import math, os, sys, random, xml.dom.minidom
sys.path.insert(0, os.path.dirname(__file__))
from autolisp_mini import *

LSP = os.path.join(os.path.dirname(__file__), "..", "TopoKit.lsp")
load(LSP); print()

def fn(name, *args): return call(Sym(name.upper()), list(args))

# ---------------------------------------------------------------- Stereo 70
known = [((500000, 500000), (24.998445775149445, 45.99971818665659)),
         ((588000, 325000), (26.10355990247839, 44.419369931978245)),
         ((400000, 700000), (23.663689203941257, 47.79141542227441))]
for (en, ll) in known:
    r = fn("TK:Stereo70ToWGS84", [float(en[0]), float(en[1])])
    assert abs(r[0]-ll[0]) < 1e-8 and abs(r[1]-ll[1]) < 1e-8, (en, r, ll)
try:
    import pyproj
    t = pyproj.Transformer.from_crs(3844, 4326, always_xy=True)
    random.seed(1); mx = 0
    for _ in range(200):
        E, N = random.uniform(120000, 900000), random.uniform(200000, 800000)
        r = fn("TK:Stereo70ToWGS84", [E, N]); p = t.transform(E, N)
        mx = max(mx, abs(r[0]-p[0]), abs(r[1]-p[1]))
    assert mx < 1e-9, mx
    print(f"Stereo70->WGS84 vs PROJ: diferenta maxima {mx:.2e} grade")
except ImportError:
    print("pyproj lipseste: se folosesc doar punctele de control")

# ---------------------------------------------------------------- ADDVTX
class Ent:
    def __init__(s, i): s.i = i
    def __eq__(s, o): return isinstance(o, Ent) and o.i == s.i
    def __hash__(s): return s.i
    def __repr__(s): return f"<E{s.i}>"
db, order, deleted, pending, created, sel = {}, [], set(), [], [], []
def add(dxf):
    e = Ent(len(order)); order.append(e); db[e] = [DP(-1, e)] + dxf; return e
def lw(pts, closed=False, elev=0.0, bulges=None):
    d = [DP(0, "LWPOLYLINE"), DP(8, "0"), DP(90, len(pts)), DP(70, 1 if closed else 0), DP(38, elev)]
    for k, p in enumerate(pts):
        d += [[10, float(p[0]), float(p[1])], DP(40, 0.0), DP(41, 0.0), DP(42, (bulges or {}).get(k, 0.0))]
    return add(d + [[210, 0.0, 0.0, 1.0]])
def p3d(pts):
    e = add([DP(0, "POLYLINE"), DP(8, "0"), DP(66, 1), [10, 0.0, 0.0, 0.0], DP(70, 8)])
    for p in pts: add([DP(0, "VERTEX"), DP(8, "0"), [10] + [float(x) for x in p], DP(70, 32)])
    add([DP(0, "SEQEND"), DP(8, "0")]); return e
def entnext(e):
    i = order.index(e) + 1
    return order[i] if i < len(order) else None
def entmake(d=None):
    if d is None: pending.clear(); return None
    pending.append(d)
    if d[0].cdr == "SEQEND":
        first = None
        for x in pending:
            e = add(list(x)); first = first or e
        pending.clear(); created.append(first)
    return d
def entmod(d): db[d[0].cdr] = d; return d
funcs.update({Sym("ENTGET"): lambda e, a=None: db[e], Sym("ENTMOD"): entmod,
              Sym("ENTUPD"): lambda e: e, Sym("ENTNEXT"): entnext, Sym("ENTMAKE"): entmake,
              Sym("ENTDEL"): lambda e: deleted.add(e) or e,
              Sym("TBLSEARCH"): lambda t, n: [DP(0, "LAYER"), DP(2, n), DP(70, 0)],
              Sym("SSGET"): lambda f: sel, Sym("SSLENGTH"): len, Sym("SSNAME"): lambda s, i: s[i]})
env[Sym("TK:START")] = lambda: None; env[Sym("TK:STOP")] = lambda: None
def verts(e):
    d = db[e]; out = []
    if d[1].cdr == "LWPOLYLINE":
        for g in d:
            if isinstance(g, list) and g[0] == 10: out.append([g[1], g[2], 0.0])
            if isinstance(g, DP) and g.car == 42: out[-1][2] = g.cdr
        return [[round(v, 4) + 0.0 for v in p] for p in out]
    x = entnext(e); r = []
    while db[x][1].cdr == "VERTEX":
        r.append([round(v, 4) for v in funcs[Sym("ASSOC")](10, db[x])[1:]]); x = entnext(x)
    return r

A  = lw([(0, 0), (10, 0), (10, 10), (0, 10)], True)
B  = lw([(5, 5), (15, 5), (15, 15), (5, 15)], True)
C  = lw([(0, 20), (10, 20)]); D = lw([(5, 20), (5, 30)])            # contact in T
Ar = lw([(30, -5), (30, 5)], bulges={0: 1.0}); L = lw([(20, 0), (40, 0)])
P3 = p3d([(50, -10, 0), (50, 10, 100)]); L2 = lw([(40, 0), (60, 0)], elev=7.0)
A1 = lw([(95, 0), (105, 0)], bulges={0: -1.0}); A2 = lw([(101, 0), (111, 0)], bulges={0: -1.0})
O1 = lw([(200, 0), (210, 0)]); O2 = lw([(205, 0), (215, 0)])       # suprapunere colineara
sel[:] = [A, B, C, D, Ar, L, P3, L2, A1, A2, O1, O2]
fn("c:ADDVTX"); print()
b8 = round(math.tan(math.pi / 8), 4)
expect = {
  A:  [[0, 0, 0], [10, 0, 0], [10, 5, 0], [10, 10, 0], [5, 10, 0], [0, 10, 0]],
  B:  [[5, 5, 0], [10, 5, 0], [15, 5, 0], [15, 15, 0], [5, 15, 0], [5, 10, 0]],
  C:  [[0, 20, 0], [5, 20, 0], [10, 20, 0]],
  D:  [[5, 20, 0], [5, 30, 0]],
  Ar: [[30, -5, b8], [35, 0, b8], [30, 5, 0]],
  L:  [[20, 0, 0], [35, 0, 0], [40, 0, 0]],
  L2: [[40, 0, 0], [50, 0, 0], [60, 0, 0]],
  A1: [[95, 0, -0.618], [103, 4, -0.2361], [105, 0, 0]],
  A2: [[101, 0, -0.2361], [103, 4, -0.618], [111, 0, 0]],
  O1: [[200, 0, 0], [205, 0, 0], [210, 0, 0]],
  O2: [[205, 0, 0], [210, 0, 0], [215, 0, 0]]}
for e, v in expect.items():
    assert verts(e) == [[float(x) for x in p] for p in v], (e, verts(e))
assert P3 in deleted and verts(created[0]) == [[50, -10, 0], [50, 0, 50], [50, 10, 100]]
print("ADDVTX: toate cazurile corecte")

# ---------------------------------------------------------------- caroiaj + KML
drawn = []
funcs[Sym("ENTMAKE")] = lambda d=None: drawn.append(d) or d
fn("TK:Caroiaj", 588020.0, 325010.0, 588220.0, 325153.5, 588130.0, 325035.0, 0.5)
texts = [x.cdr for d in drawn if d[0].cdr == "TEXT" for x in d if isinstance(x, DP) and x.car == 1]
assert texts == ["Y=588050", "Y=588100", "X=325050", "X=325100", "X=325150"], texts
files = {}
class FH:
    def __init__(s, n): s.n = n; files[n] = ""
funcs.update({Sym("OPEN"): lambda f, m, enc=None: FH(f), Sym("CLOSE"): lambda h: None,
              Sym("WRITE-LINE"): lambda s, h: files.__setitem__(h.n, files[h.n] + s + "\n") or s})
funcs[Sym("GETVAR")] = lambda v: {"DWGNAME": "Test & <1>.dwg"}[v]
pts = [[588000.0, 325000.0, 0.0], [588100.0, 325000.0, 0.0], [588100.0, 325080.0, 0.0], [588000.0, 325080.0, 0.0]]
assert fn("TK:WriteKml", "x.kml", 'Parcela "A" & B', pts, pts, 8000.0, 360.0)
doc = xml.dom.minidom.parseString(files["x.kml"].encode())
ring = doc.getElementsByTagName("coordinates")[0].firstChild.data.split()
assert len(ring) == 5 and ring[0] == ring[-1]
assert len(doc.getElementsByTagName("Point")) == 4
print("Caroiaj si KML: corecte")

# ---------------------------------------------------------------- grila NTv2
GRID = os.environ.get("TOPOKIT_GRID") or os.path.join(os.path.dirname(__file__), "..", "stereo70_etrs89A.gsb")
if os.path.exists(GRID):
    data = open(GRID, "rb").read()
    funcs.update({Sym("FINDFILE"): lambda f: GRID if f.endswith(".gsb") else None,
                  Sym("GETVAR"): lambda v: 0})
    env[Sym("TK:BINOPEN")] = lambda f: "stream"
    env[Sym("TK:BINREAD")] = lambda st, pos, n: list(data[pos:pos+n])
    env[Sym("TK:BINCLOSE")] = lambda st: None
    assert fn("TK:GridOpen"), "grila nu s-a deschis"
    g = env[Sym("*TK:GRID*")]
    assert g[7] * g[8] == 356616, g
    # 1) puncte de control (Stereo 70 -> ETRS89) publicate cu grila
    ctrl = [((449113.51419, 397303.417679), (24.35213603753, 45.07364502616))]
    try:
        import shapefile
        vp = next((c for c in (os.path.join(os.path.dirname(GRID), "verification_points"),
                               os.path.join(os.path.dirname(GRID), "..", "verification_points"))
                   if os.path.isdir(c)), None) or os.path.join(os.path.dirname(__file__), "data", "verification_points")
        if not os.path.isdir(vp): vp = None
        if vp:
            st = shapefile.Reader(dbf=open(os.path.join(vp, "stereo.dbf"), "rb")).records()
            wg = shapefile.Reader(dbf=open(os.path.join(vp, "wgs84.dbf"), "rb")).records()
            ctrl = [((a[1], a[2]), (b[1], b[2])) for a, b in zip(st, wg)]
    except ImportError:
        pass
    def dm(a, b): return math.hypot((a[0]-b[0])*111320*math.cos(math.radians(a[1])), (a[1]-b[1])*110574)
    env[Sym("*TK:NHELM*")] = 0
    errs = [dm(fn("TK:Stereo70ToWGS84", [float(e), float(n)]), ref) for (e, n), ref in ctrl]
    assert max(errs) < 0.02 and env[Sym("*TK:NHELM*")] == 0, errs
    print(f"Grila NTv2: {len(ctrl)} puncte de control, eroare maxima {max(errs)*1000:.1f} mm")
    # 2) identic cu PROJ hgridshift in toata zona acoperita
    try:
        import pyproj, tempfile, shutil
        d = tempfile.mkdtemp(); shutil.copy(GRID, os.path.join(d, "stereo70_etrs89A.gsb"))
        pyproj.datadir.append_data_dir(d)
        tp = pyproj.Transformer.from_pipeline(
            "+proj=pipeline +step +inv +proj=sterea +lat_0=46 +lon_0=25 +k=0.99975 +x_0=500000 "
            "+y_0=500000 +ellps=krass +step +proj=hgridshift +grids=stereo70_etrs89A.gsb "
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg")
        random.seed(3); mx = 0; ng = 0; nh = 0
        for _ in range(400):
            E, N = random.uniform(150000, 880000), random.uniform(250000, 760000)
            env[Sym("*TK:NHELM*")] = 0
            r = fn("TK:Stereo70ToWGS84", [E, N])
            if env[Sym("*TK:NHELM*")]:
                nh += 1; continue          # in afara grilei -> Helmert
            ng += 1; mx = max(mx, dm(r, tp.transform(E, N)))
        assert mx < 1e-4, mx
        print(f"Grila NTv2 vs PROJ hgridshift: {ng} puncte, diferenta maxima {mx*1000:.4f} mm; {nh} puncte in afara grilei -> Helmert")
    except ImportError:
        pass
    # 3) in afara grilei -> Helmert (fara erori)
    env[Sym("*TK:NHELM*")] = 0
    fn("TK:Stereo70ToWGS84", [60000.0, 150000.0]); assert env[Sym("*TK:NHELM*")] == 1
    fn("TK:GridClose")
else:
    print("Grila stereo70_etrs89A.gsb lipseste: testele NTv2 sunt omise (setati TOPOKIT_GRID)")
print("\nToate testele au trecut.")
