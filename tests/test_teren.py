#!/usr/bin/env python3
"""Teste offline pentru TopoKitTeren.lsp (puncte, TIN, curbe, volume, raster, KML).

    python3 tests/test_teren.py [--render DIR]

Verificarile sunt analitice: proprietatea Delaunay a triangulatiei, numarul de
triunghiuri (2n - 2 - h), curbele de nivel aflate exact pe TIN la cota lor,
volume exacte pentru suprafete plane, georeferentierea dupa fisierul world si
dus-intors Stereo 70 -> WGS84 -> Stereo 70 prin KML/KMZ.
"""
import os, sys, math, random, tempfile, zipfile
sys.path.insert(0, os.path.dirname(__file__))
from acad_sim import Acad, Sym, call, env, grp, grps, DP, T
import autolisp_mini as M

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
args = sys.argv[1:]
RENDER = args[args.index("--render") + 1] if "--render" in args else None
OUT = os.environ.get("TOPOKIT_OUT") or tempfile.mkdtemp(prefix="topokit_teren_")
os.makedirs(OUT, exist_ok=True)

acad = Acad(ROOT, OUT)
M.load(os.path.join(ROOT, "TopoKit.lsp"))          # incarca automat si modulele Anexe si Teren
acad.after_load()
assert any("TopoKit Teren incarcat" in o for o in acad.out)
env[Sym("*TK:USEGRID*")] = "0"                     # grila NTv2 se citeste prin ADODB (doar in AutoCAD)


def fn(name, *a): return call(Sym(name.upper()), list(a))
def ents(typ, layer=None):
    return [e for e in acad.entities("Model", typ) if layer is None or (grp(acad.db[e], 8) or "").upper() == layer.upper()]
def texts(layer):
    return [grp(acad.db[e], 1) for e in ents("TEXT", layer)]


# ---------------------------------------------------------------- import puncte (separator ";", virgula zecimala)
E0, N0 = 545000.0, 458000.0
def zf(x, y): return 500.0 + 0.04 * x + 2.0 * math.sin(x / 12.0) * math.cos(y / 15.0)
random.seed(7)
pts, nr = [], 0
for j in range(13):
    for i in range(13):
        x = i * 5.0 + (random.uniform(-1.2, 1.2) if 0 < i < 12 else 0.0)
        y = j * 5.0 + (random.uniform(-1.2, 1.2) if 0 < j < 12 else 0.0)
        nr += 1
        pts.append((nr, x, y, zf(x, y), "GARD" if (j == 0 and 2 <= i <= 6) else ""))
f = os.path.join(OUT, "puncte.txt")
with open(f, "w", encoding="utf-8") as fh:
    fh.write("Nr;X;Y;Z;Cod\n")
    for p in pts:
        fh.write(f"{p[0]};{N0 + p[2]:.3f};{E0 + p[1]:.3f};{p[3]:.3f};{p[4]}\n".replace(".", ","))
acad.inputs = [("file", f)]
fn("c:IMPPCT")
assert not acad.inputs, acad.inputs
P = ents("POINT", "PUNCTE")
assert len(P) == 169, len(P)
p0 = grp(acad.db[P[0]], 10)
assert abs(p0[0] - E0) < 1e-6 and abs(p0[1] - N0) < 1e-6 and abs(p0[2] - pts[0][3]) < 1e-3, p0
assert "1" in texts("PCT_NR") and f"{pts[0][3]:.2f}" in texts("PCT_COTA")
gard = [e for e in acad.entities("Model", "POLYLINE") if grp(acad.db[e], 8) == "COD_GARD"]
assert len(gard) == 1, gard
i = acad.order.index(gard[0]); vx = []
while grp(acad.db[acad.order[i + 1]], 0) == "VERTEX": vx.append(grp(acad.db[acad.order[i + 1]], 10)); i += 1
assert len(vx) == 5 and abs(vx[0][2] - pts[2][3]) < 1e-3, vx
print(f"IMPPCT: 169 puncte 3D (separator ';', virgula zecimala), linia de cod GARD cu {len(vx)} varfuri")

# ---------------------------------------------------------------- TIN (Delaunay)
acad.inputs = [("ssget", P), ("entsel", None)]
ntri = fn("c:TIN") or len(ents("3DFACE", "TIN"))
F = [[tuple(grp(acad.db[e], c)) for c in (10, 11, 12)] for e in ents("3DFACE", "TIN")]
xy = [(grp(acad.db[e], 10)[0], grp(acad.db[e], 10)[1]) for e in P]
def hull(ps):
    ps = sorted(set(ps)); cr = lambda o, a, b: (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lo, up = [], []
    for p in ps:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], p) <= 1e-9: lo.pop()
        lo.append(p)
    for p in reversed(ps):
        while len(up) >= 2 and cr(up[-2], up[-1], p) <= 1e-9: up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]
# punctele de pe contur (inclusiv cele coliniare de pe laturile patratului)
hv = hull(xy)
h = sum(1 for p in xy if any(abs((b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0])) < 1e-6 and
                             min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9 and
                             min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9
                             for a, b in zip(hv, hv[1:] + hv[:1])))
assert len(F) == 2 * len(xy) - 2 - h, (len(F), len(xy), h)
def circ(a, b, c):
    ax, ay, bx, by, cx, cy = a[0], a[1], b[0], b[1], c[0], c[1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax*ax + ay*ay) * (by - cy) + (bx*bx + by*by) * (cy - ay) + (cx*cx + cy*cy) * (ay - by)) / d
    uy = ((ax*ax + ay*ay) * (cx - bx) + (bx*bx + by*by) * (ax - cx) + (cx*cx + cy*cy) * (bx - ax)) / d
    return ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2
loc = lambda p: (p[0] - E0, p[1] - N0)                     # coordonate locale (precizie numerica)
lxy = [loc(p) for p in xy]
for t in F:
    lt = [loc(p) for p in t]
    ux, uy, r2 = circ(*lt)
    assert all((p[0] - ux) ** 2 + (p[1] - uy) ** 2 >= r2 - 1e-6 for p in lxy if p not in lt), t
area = sum(abs((t[1][0]-t[0][0])*(t[2][1]-t[0][1]) - (t[2][0]-t[0][0])*(t[1][1]-t[0][1])) / 2 for t in F)
assert abs(area - 3600.0) < 1e-6, area                      # triangulatia acopera exact patratul 60 x 60
print(f"TIN: {len(F)} triunghiuri = 2n-2-b (b = {h} puncte pe contur), proprietatea Delaunay verificata, aria {area:.1f} mp")

# ---------------------------------------------------------------- curbe de nivel
def z_on_tin(x, y):
    for a, b, c in F:
        d = (b[1]-c[1])*(a[0]-c[0]) + (c[0]-b[0])*(a[1]-c[1])
        l1 = ((b[1]-c[1])*(x-c[0]) + (c[0]-b[0])*(y-c[1])) / d
        l2 = ((c[1]-a[1])*(x-c[0]) + (a[0]-c[0])*(y-c[1])) / d
        if l1 >= -1e-9 and l2 >= -1e-9 and 1 - l1 - l2 >= -1e-9:
            return l1 * a[2] + l2 * b[2] + (1 - l1 - l2) * c[2]
env[Sym("*TKT:ECHID*")] = 0.5; env[Sym("*TKT:PRINC*")] = 4
acad.inputs = [("ssget", ents("3DFACE", "TIN"))]
fn("c:CURBE")
C = ents("LWPOLYLINE", "CURBE_PRINC") + ents("LWPOLYLINE", "CURBE_SEC")
assert C, "fara curbe"
worst = 0.0
for e in C:
    hh = grp(acad.db[e], 38)
    assert abs(hh / 0.5 - round(hh / 0.5)) < 1e-9
    assert (grp(acad.db[e], 8) == "CURBE_PRINC") == (round(hh / 0.5) % 4 == 0)
    for v in grps(acad.db[e], 10):
        worst = max(worst, abs(z_on_tin(v[0], v[1]) - hh))
assert worst < 1e-5, worst                 # varfurile aflate exact pe nivel se ridica cu 1 micron
levels = {grp(acad.db[e], 38) for e in C}
zs = [p[2] for t in F for p in t]
assert levels == {k * 0.5 for k in range(math.ceil(min(zs) / 0.5), math.floor(max(zs) / 0.5) + 1)}, levels
assert texts("CURBE_COTE"), "fara cote pe curbele principale"
print(f"CURBE: {len(C)} curbe pe {len(levels)} niveluri, abatere maxima fata de TIN {worst:.1e} m")

# ---------------------------------------------------------------- volume
sq = lambda f, dx=0.0: [[(dx + 0, 0, f(0, 0)), (dx + 10, 0, f(10, 0)), (dx + 10, 10, f(10, 10))],
                        [(dx + 0, 0, f(0, 0)), (dx + 10, 10, f(10, 10)), (dx + 0, 10, f(0, 10))]]
tl = lambda tris: [[list(map(float, p)) for p in t] for t in tris]
r = fn("TKT:VolPlane", tl(sq(lambda x, y: 0.1 * x)), 0.5)
assert abs(r[0] - 12.5) < 1e-9 and abs(r[1] - 12.5) < 1e-9 and abs(r[2] - 50) < 1e-9 and abs(r[4] - 100) < 1e-9, r
r = fn("TKT:VolTins", tl(sq(lambda x, y: 0.0)), tl(sq(lambda x, y: 1.0 + 0.1 * x)), 0.5)
assert abs(r[0]) < 1e-9 and abs(r[1] - 150.0) < 1e-6 and abs(r[2] - 100.0) < 1e-9, r
r = fn("TKT:VolTins", tl(sq(lambda x, y: 0.5)), tl(sq(lambda x, y: 0.1 * x)), 0.25)
assert abs(r[0] - 12.5) < 1e-6 and abs(r[1] - 12.5) < 1e-6, r
# comanda VOLUM pe TIN-ul terenului, fata de cota medie, cu tabelul in desen
acad.inputs = [("ssget", ents("3DFACE", "TIN")), ("real", 501.0), ("pt", [E0 + 80, N0 + 60])]
fn("c:VOLUM")
vt = texts("VOLUME")
assert "Volume fata de cota 501.00" in vt and "Sapatura (mc)" in vt, vt
print("VOLUM / VOLUM2: volume exacte pentru plane (12,5 / 12,5 mc; 150 mc), tabel in desen")

# ---------------------------------------------------------------- tabel de coordonate si legenda
acad.inputs = [("ssget", P[:12]), ("pt", [E0 + 80, N0 + 120])]
fn("c:TABPCT")
tt = texts("TABEL_PCT")
assert "Inventar de coordonate - Stereo 70" in tt and "1" in tt and f"{N0:.3f}" in tt and f"{E0:.3f}" in tt, tt[:12]
acad.tables["BLOCK"] = {"STALP": [DP(0, "BLOCK"), DP(2, "STALP"), DP(4, "Stalp de iluminat")]}
acad.new([DP(0, "INSERT"), DP(410, "Model"), DP(8, "STALPI"), DP(2, "STALP"), [10, E0 + 20, N0 + 20, 0.0]])
acad.inputs = [("pt", [E0 + 130, N0 + 120])]
fn("c:LEGENDA")
lt = texts("LEGENDA")
assert "Stalp de iluminat (1)" in lt and "COD_GARD (1)" in lt and any(t.startswith("LEGEND") for t in lt), lt
leg = [e for e in ents("INSERT", "LEGENDA")]
assert len(leg) == 1 and abs(grp(acad.db[leg[0]], 41) - 0.7 * 9 * 0.5) < 1e-9, leg   # blocul incadrat in celula
print(f"TABPCT: tabel cu 12 puncte; LEGENDA: {len(lt) - 1} semne conventionale (bloc scalat in celula)")

# ---------------------------------------------------------------- raster georeferentiat
from PIL import Image
img = os.path.join(OUT, "orto.png")
Image.new("RGB", (40, 30), (120, 160, 90)).save(img)
open(os.path.join(OUT, "orto.pgw"), "w").write("0.5\n0.0\n0.0\n-0.5\n545000.25\n458014.75\n")
acad.inputs = [("file", img)]
fn("c:GEOREF")
ras = acad.rasters[-1].props
assert ras["W"] == 20.0 and ras["H"] == 15.0 and ras["ROT"] == 0.0, ras
assert abs(ras["ORIGIN"][0] - 545000.0) < 1e-9 and abs(ras["ORIGIN"][1] - 458000.0) < 1e-9, ras
print("GEOREF: imagine 40x30 px, pixel 0,5 m, coltul S-V 545000, 458000 (dupa fisierul .pgw)")

# ---------------------------------------------------------------- KML / KMZ: Stereo 70 -> WGS84 -> Stereo 70
poly = [(588000.0, 325000.0), (588060.0, 325010.0), (588050.0, 325070.0), (587995.0, 325060.0)]
ll = [fn("TK:Stereo70ToWGS84", [e, n]) for e, n in poly]
coords = " ".join(f"{a:.10f},{b:.10f},0" for a, b in ll + ll[:1])
kml = f"""<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name><![CDATA[Parcela A]]></name><Polygon><outerBoundaryIs><LinearRing><coordinates>
 {coords}
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>Borna 1</name><Point><coordinates>{ll[0][0]:.10f},{ll[0][1]:.10f},0</coordinates></Point></Placemark>
</Document></kml>"""
fk = os.path.join(OUT, "parcela.kml"); open(fk, "w").write(kml)
acad.inputs = [("file", fk)]
fn("c:IMPKML")
K = ents("LWPOLYLINE", "KML")
assert len(K) == 1 and grp(acad.db[K[0]], 70) == 1 and len(ents("POINT", "KML")) == 1, K
err = max(math.dist(v, p) for v, p in zip(grps(acad.db[K[0]], 10), poly))
assert err < 1e-4 and "Parcela A" in texts("KML") and "Borna 1" in texts("KML"), (err, texts("KML"))
fz = os.path.join(OUT, "parcela.kmz")
with zipfile.ZipFile(fz, "w") as z: z.writestr("doc.kml", kml)
acad.inputs = [("file", fz)]
fn("c:IMPKML")
assert len(ents("LWPOLYLINE", "KML")) == 2 and any("Expand-Archive" in r for r in acad.runs)
print(f"IMPKML: poligon si punct din KML si KMZ, eroare dus-intors {err * 1000:.3f} mm")

# ---------------------------------------------------------------- harta online
acad.inputs = [("pt", [588000.0, 325000.0, 0.0])]
url = fn("TKT:Map")
assert url.startswith("https://www.google.com/maps/search/?api=1&query=44.41") and any("explorer.exe" in r and url in r for r in acad.runs), url
print("HARTA:", url)

# ---------------------------------------------------------------- meniul TOPOTEREN si sectiunea 5 din TOPOKIT
acad.dcl.scripts = {"tkt_main": [[("set", "eb_echid", "0"), ("click", "bt_curbe"), ("click", "cancel")]]}
fn("c:TOPOTEREN")
snap = acad.dcl.snapshots["tkt_main"]
assert "pozitive" in snap["tiles"]["error"] and env[Sym("*TKT:ECHID*")] == 0.5, snap["tiles"]["error"]
assert snap["lists"]["pl_cols"][0].startswith("Nr, X (Nord)") and snap["tiles"]["pl_scara"] == "2"
acad.dcl.scripts = {"tkt_main": [[("click", "bt_harta")]]}
acad.inputs = [("pt", None)]
acad.vars["VIEWCTR"] = [588000.0, 325000.0, 0.0]
n_runs = len(acad.runs)
fn("c:TOPOTEREN")
assert len(acad.runs) == n_runs + 1 and "google.com/maps" in acad.runs[-1]
acad.dcl.scripts = {"topokit_main": [[("click", "bt_teren")]], "tkt_main": [[("click", "cancel")]]}
n0 = len(acad.dcl.log)
fn("c:TOPOKIT")
assert acad.dcl.log[n0:] == ["topokit_main", "tkt_main"], acad.dcl.log[n0:]
assert acad.dcl.files and "Modulul de teren este incarcat" in acad.dcl.snapshots["topokit_main"]["tiles"]["tx_teren"]
lines = fn("TKT:DclLines")
assert lines == open(os.path.join(ROOT, "TopoKitTeren.dcl"), encoding="utf-8").read().splitlines()
print("TOPOTEREN: validarea optiunilor, butoanele, sectiunea 5 din TOPOKIT, copia DCL")

if RENDER:
    from render_layout import render_model
    from dcl_mockup import Mockup
    os.makedirs(RENDER, exist_ok=True)
    render_model(acad, os.path.join(RENDER, "teren_tin_curbe.png"), (E0 - 5, N0 - 5, E0 + 170, N0 + 130), 8.0)
    acad.dcl.scripts = {"tkt_main": [[("click", "cancel")]]}
    fn("c:TOPOTEREN")
    Mockup(open(os.path.join(ROOT, "TopoKitTeren.dcl"), encoding="utf-8").read(), "tkt_main",
           acad.dcl.snapshots["tkt_main"]).render(os.path.join(RENDER, "macheta_teren.png"))
    print("Imagini:", RENDER)
print("\nToate testele TopoKitTeren au trecut.")
