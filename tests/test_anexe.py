#!/usr/bin/env python3
"""Teste offline pentru TopoKitAnexe.lsp (generatorul de anexe, Ordinul 600/2023).

    python3 tests/test_anexe.py [--render DIR] [--word]

Ruleaza comenzile pe un desen simulat (acad_sim.py): PAD (anexa 16), PADDEZ
(anexa 17 + PAD pe loturi), PADALIP, RELEVEU (anexa 18), foaia colectiva
(anexa 19), meniul ANEXE si exportul JSON pentru anexele Word.
  --render DIR  salveaza layout-urile generate ca imagini PNG in DIR
  --word        completeaza si sabloanele Word cu PowerShell (pwsh) daca exista
"""
import os, sys, json, math, re, shutil, subprocess, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from acad_sim import Acad, grp, grps, Sym, call, env, T
import autolisp_mini as M

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_hook = sys.excepthook
def _trace(t, v, tb):
    _hook(t, v, tb)
    if getattr(v, "lisp_trace", None): print("Stiva AutoLISP:", " <- ".join(v.lisp_trace), file=sys.stderr)
sys.excepthook = _trace
args = sys.argv[1:]
RENDER = args[args.index("--render") + 1] if "--render" in args else None
WORD = "--word" in args
OUT = os.environ.get("TOPOKIT_OUT") or tempfile.mkdtemp(prefix="topokit_anexe_")
os.makedirs(OUT, exist_ok=True)

acad = Acad(ROOT, OUT)
M.load(os.path.join(ROOT, "TopoKit.lsp"))          # incarca automat si TopoKitAnexe.lsp
acad.after_load()
assert any("TopoKit Anexe incarcat" in o for o in acad.out), acad.out[-3:]
assert sum("TopoKit Anexe incarcat" in o for o in acad.out) == 1 and env.get(Sym("*TKA:LOADING*")) is None


def fn(name, *a): return call(Sym(name.upper()), list(a))
def R(x): return re.sub(r"\\U\+([0-9A-F]{4})", lambda m: chr(int(m.group(1), 16)), x)
def texts(layout):
    out = []
    for e in acad.entities(layout):
        d = acad.db[e]
        if grp(d, 0) in ("TEXT", "MTEXT"):
            out.append(R("".join(grps(d, 3)) + grp(d, 1)))
    return out
def render(layout, name):
    if RENDER:
        from render_layout import render_layout
        os.makedirs(RENDER, exist_ok=True)
        render_layout(acad, layout, os.path.join(RENDER, name + ".png"))


# ---------------------------------------------------------------- desenul de test (Stereo 70)
P = [(545000.00, 458040.00), (545024.60, 458041.80), (545026.10, 458018.50),
     (545023.40, 458000.30), (545001.20, 457999.40), (544998.60, 458021.70)]
A = (P[5][0] + 0.35 * (P[0][0] - P[5][0]), P[5][1] + 0.35 * (P[0][1] - P[5][1]))   # puncte noi pe contur
B = (P[1][0] + 0.55 * (P[2][0] - P[1][0]), P[1][1] + 0.55 * (P[2][1] - P[1][1]))
# imobilul desenat in sens trigonometric, din alt punct decat N-V (se reordoneaza)
parcel = acad.add_lw([P[3], P[2], P[1], P[0], P[5], P[4]], layer="IMOBIL")
lot1 = acad.add_lw([P[0], P[1], B, A], layer="LOTURI")
lot2 = acad.add_lw([A, B, P[2], P[3], P[4], P[5]], layer="LOTURI")
c1 = acad.add_lw([(545005, 458005), (545017, 458005), (545017, 458015), (545005, 458015)], layer="CONSTR")
c2 = acad.add_lw([(545010, 458032), (545016, 458032), (545016, 458036), (545010, 458036)], layer="CONSTR")
for p, t in [((545012, 458044.5), "nr. cad. 101234"), ((545031.0, 458030.0), "str. Lalelelor"),
             ((545029.5, 458009.0), "str. Lalelelor"), ((545012, 457995.8), "nr. cad. 101240"),
             ((544994.0, 458010.0), "Popescu Ion"), ((544994.8, 458032.0), "nr. cad. 101250"),
             ((545000.5, 458041.5), "1"), ((545008, 458020), "CC"), ((545014.0, 457998.2), "C9")]:
    acad.add_text(p, t, 0.35, "TEXTE")

# datele lucrarii si ale executantului
for k, v in {"NRCAD": "123456", "NRCF": "123456", "UAT": "Brașov", "LOCALITATE": "Brașov", "JUDET": "Brașov",
             "STRADA": "Lalelelor", "NR": "12", "SACT": "1050", "P1_NUME": "Ionescu", "P1_PRENUME": "Maria",
             "P1_CNP": "2800101080011", "P1_LOC": "Brașov", "P1_STR": "Lalelelor", "P1_NR": "12",
             "ACT_PROP": "contract de vânzare-cumpărare nr. 1234/2015", "TIP": "PRIMA", "COMUNICARE": "EMAIL",
             "OCPI": "Brașov", "BCPI": "Brașov"}.items():
    fn("TKA:Put", k, v)
for k, v in {"E_TITLU": "ing.", "E_NUME": "Buția", "E_PRENUME": "Mihai Alexandru", "E_AUT_SERIA": "RO-BV-F",
             "E_AUT_NR": "0123", "E_CAT": "D", "E_TEL": "0722000000"}.items():
    fn("TKA:EPut", k, v)
assert fn("TKA:Get", "UAT") == "Brașov" and acad.envs["TopoKit_E_NUME"] == "Buția"

# ---------------------------------------------------------------- unitare
assert fn("TKA:R", "Suprafa`ta ^in`s") == "Suprafa\\U+021Ba \\U+00EEn\\U+0219"
assert fn("TKA:Json", "Brașov \"x\"\n`a") == '"Bra\\u0219ov \\"x\\"\\n\\u0103"'
assert fn("TKA:Ascii", "Suprafa`ta") == "Suprafata" and fn("TKA:Real", "`a^i") == "ăî"
assert fn("TKA:LargestRemainder", [10.6, 20.3, 30.1], 61) == [11, 20, 30]
assert fn("TKA:MtextPlain", "{\\fArial|b1;Lot} 1\\PS=200") == "Lot 1 S=200"
ring = fn("TKA:Clockwise", [list(p) for p in [P[3], P[2], P[1], P[0], P[5], P[4]]])
assert ring[0] == list(P[0]) and fn("TKA:SArea", ring) < 0, ring
dens = fn("TKA:Densify", ring, [list(A), list(B)])
assert len(dens) == 8 and dens[1] == list(P[1]) and dens[2] == list(B) and dens[7] == list(A), dens
lung = "loc. Brașov, str. General Traian Moșoiu nr. 112, bl. A4, sc. B, et. 3, ap. 17, tarla 45, parcela 1234/5/6, jud. Brașov"
assert fn("TKA:AddrRowH", "loc. Brașov") == 5.2 and fn("TKA:AddrRowH", lung) > 8.4 and fn("TKA:HeaderH", lung) > 49.0
env[Sym("*TKA:HH*")] = 49.0
ch = fn("TKA:ChooseSheet", [0.0, 0.0, 20.0, 20.0], 260.0)            # tabele foarte inalte
assert fn("TKA:SG", ch[0], "CODE") not in ("A4P", "A3L"), ch[0]       # foile fara loc pentru tabele
print("Functii de baza: corecte")

# ---------------------------------------------------------------- PAD (anexa 16)
cdata = {"DENUMIRE": "Casă de locuit", "REGIM": "P+1E", "AN": "2005", "SD": "240"}
acad.inputs = [("entsel", parcel), ("ssget", [c1, c2]), ("ssget", None)]
acad.dcl.scripts = {
    "tka_constr": [[("set", k, v) for k, v in cdata.items()] + [("pick", "DEST", "0")],
                   [("set", "DENUMIRE", "Magazie"), ("pick", "DEST", "3")]],
    "tka_laturi": [[("click", "bt_auto"),
                    ("pick", "lb_lat", "0"), ("pick", "eb_vecin", "Popa Vasile"), ("click", "bt_aplica"),
                    ("pick", "lb_lat", "0 1 2 3 4 5"), ("pick", "pl_mat", "1"), ("click", "bt_aplica"),
                    ("click", "accept")]]}
acad.vars["OSMODE"] = 4133
fn("c:PAD")
assert not acad.inputs and not acad.alerts, (acad.inputs, acad.alerts)
assert acad.vars["OSMODE"] == 4133 and acad.vars["CMDECHO"] == 1, "variabilele de sistem nu au fost restabilite"
lay = "PAD_123456"
assert lay.upper() in acad.layouts, acad.layouts.keys()
sd = env[Sym("*TKA:SD*")]
assert [x[0] for x in sd] == ["nr. cad. 101234", "str. Lalelelor", "str. Lalelelor", "nr. cad. 101240",
                              "Popescu Ion", "nr. cad. 101250"], sd
assert sd[0][1] == "Popa Vasile" and all(x[2] == "gard de plasă" for x in sd), sd
tx = texts(lay)
for need in ["Plan de amplasament și delimitare a imobilului", "Scara 1:200", "123456",
             "A. Date referitoare la teren", "B. Date referitoare la construcții", "C1", "C2", "1", "6",
             "Total", "%%uAnexa nr. 16", "A3-200"]:
    assert need in tx, (need, tx)
assert any("Casă de locuit, regim de înălțime P+1E, construită în anul 2005, Sc=120 mp, Sd=240 mp" in t for t in tx), tx
assert "Imobil împrejmuit cu gard de plasă." in tx, tx                    # mentiunile din materializare
assert any(t.startswith("{\\fArial|b1|i0|c0|p34;Executant} ing. Buția Mihai Alexandru") for t in tx)
area = fn("TKA:Int", acad.curve_area(parcel))
assert str(area) in tx and f"Suprafața totală măsurată a imobilului = {area} mp\\PSuprafața din act = 1050 mp" in tx
vp = [e for e in acad.entities(lay, "VIEWPORT") if grp(acad.db[e], 69) != 1]
assert len(vp) == 1 and grp(acad.db[vp[0]], 8) == "PAD_VIEWPORT", vp     # viewport-ul implicit a fost sters
vpt = env[Sym("*TKA:VPT*")]
assert abs(vpt[4] - 5.0) < 1e-9, vpt                                       # 1:200 -> 5 mm/m
# vecinii deja scrisi in model nu se repeta pe plan; latura cu vecin nou ("Popa Vasile" are identificator) nu
assert "Popescu Ion" not in tx and "nr. cad. 101250" not in tx, tx
render(lay, "anexa16_PAD")
SNAP = {"tka_laturi": acad.dcl.snapshots["tka_laturi"], "tka_constr": acad.dcl.snapshots["tka_constr"]}
print(f"PAD (anexa 16): layout {lay}, {len(acad.entities(lay))} entitati, S={area} mp")


def shoelace(pts):
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))) / 2


# ---------------------------------------------------------------- PADDEZ (anexa 17 + PAD pe loturi)
acad.inputs = [("entsel", parcel), ("entsel", lot1), ("entsel", lot2), ("entsel", None),
               ("ssget", [c1, c2]), ("ssget", None)]
acad.dcl.scripts = {"tka_laturi": [[("click", "accept")]]}
fn("c:PADDEZ")
assert not acad.inputs and not acad.alerts, (acad.inputs, acad.alerts)
for lay in ("PAD_dezlipire_123456", "PAD_lot1_123456", "PAD_lot2_123456"):
    assert lay.upper() in acad.layouts, (lay, list(acad.layouts))
lots = env[Sym("*TKA:LOTURI*")]
a1, a2 = shoelace([P[0], P[1], B, A]), shoelace([A, B, P[2], P[3], P[4], P[5]])
la = [fn("TKA:R1", r, "AREA") for r in lots]
assert sum(la) == area and abs(la[0] - a1) < 1 and abs(la[1] - a2) < 1, (la, a1, a2, area)
tx = texts("PAD_dezlipire_123456")
for need in ["Plan de amplasament și delimitare a imobilului cu propunerea de dezlipire", "%%uAnexa nr. 17",
             "Situația actuală (înainte de dezlipire)", "Situația viitoare (după dezlipire)",
             "Lot 1 - Curți construcții", "Lot 2 - Curți construcții", str(la[0]), str(la[1]),
             "Curți construcții", "7", "8", "Lot 1\\PS=" + str(la[0]) + " mp"]:
    assert need in tx, (need, tx)
assert tx.count("Total") == 2 and tx.count(str(area)) >= 3, tx
# numerotarea comuna: conturul are 8 puncte (punctele noi A, B intercalate)
tab = fn("TKA:R1", lots[0], "TAB")
assert len(tab) == 8 and [x.cdr for x in tab] == list(range(1, 9)), tab
nums = {fn("TKA:PtKey", list(p)): n for p, n in [(A, 8), (B, 3), (P[0], 1), (P[1], 2), (P[2], 4)]}
for k, n in nums.items():
    assert next(x.cdr for x in tab if x.car == k) == n, (k, n, tab)
# vecinii loturilor: latura interioara = lotul alaturat, latura exterioara mosteneste vecinul imobilului
s1 = fn("TKA:R1", lots[0], "SIDES")
assert [x[6] for x in s1] == ["nr. cad. 101234", "str. Lalelelor", "Lot 2", "nr. cad. 101250"], s1
tl1 = texts("PAD_lot1_123456")
assert "Limite: gard de plasă (1-2, 2-3, 8-1); nematerializat (3-8)." in tl1, tl1
assert f"Suprafața totală măsurată a imobilului = {la[0]} mp\\PSuprafața din act = {la[0]} mp" in tl1, tl1
assert "Plan de amplasament și delimitare a imobilului - lot 1" in tl1 and "Lot 2" in tl1, tl1
assert "C2" in tl1 and "C1" not in tl1, tl1                    # constructiile din lot
render("PAD_dezlipire_123456", "anexa17_dezlipire"); render("PAD_lot1_123456", "anexa16_lot1")
render("PAD_lot2_123456", "anexa16_lot2")
print(f"PADDEZ (anexa 17): loturi {la} mp (suma {sum(la)}), 3 layout-uri")

# ---------------------------------------------------------------- PADALIP
acad.inputs = [("entsel", lot1), ("entsel", lot2), ("entsel", None), ("str", "111111"), ("str", "222222"),
               ("entsel", parcel), ("ssget", [c1, c2])]
acad.dcl.scripts = {"tka_laturi": [[("click", "accept")]]}
fn("c:PADALIP")
assert not acad.inputs and not acad.alerts, (acad.inputs, acad.alerts)
ta = texts("PAD_alipire_123456")
for need in ["Plan de amplasament și delimitare a imobilului cu propunerea de alipire",
             "Situația actuală (înainte de alipire)", "Situația viitoare (după alipire)", "111111", "222222",
             "Imobil rezultat din alipire", "Imobil 1\\PS=" + str(la[0]) + " mp"]:
    assert need in ta, (need, ta)
assert "PAD_REZULTAT_123456" in acad.layouts
render("PAD_alipire_123456", "anexa17_alipire")
print("PADALIP (anexa 17 alipire): corect")

# ---------------------------------------------------------------- RELEVEU (anexa 18) + foaia colectiva (19)
O = (546000.0, 459000.0)
def rect(x1, y1, x2, y2, layer="INCAPERI"):
    return acad.add_lw([(O[0] + x1, O[1] + y1), (O[0] + x2, O[1] + y1), (O[0] + x2, O[1] + y2), (O[0] + x1, O[1] + y2)], layer=layer)
rooms = []
for (x1, y1, x2, y2, name) in [(0, 0, 5, 4, "Living"), (5, 0, 10, 4, "Dormitor"), (0, 4, 4, 8, "Bucătărie"),
                               (4, 4, 6, 8, "Baie"), (6, 4, 10, 5.5, "Balcon"),
                               (12, 0, 17, 4, "Cameră"), (17, 0, 20, 3, "Baie"), (12, 4, 16, 8, "Hol"),
                               (16, 4, 20, 6, "Logie")]:
    rooms.append(rect(x1, y1, x2, y2))
    acad.add_text((O[0] + (x1 + x2) / 2, O[1] + (y1 + y2) / 2), name, 0.25, "TEXTE")
ui1, ui2 = rect(0, 0, 10, 8, "UI"), rect(12, 0, 20, 8, "UI")
acad.add_text((O[0] + 8, O[1] + 7), "Apartament 1", 0.3, "TEXTE")
acad.add_text((O[0] + 18, O[1] + 7), "Apartament 2", 0.3, "TEXTE")
acad.inputs = [("ssget", rooms), ("ssget", [ui1, ui2]), ("str", "etaj 1")]
fn("c:RELEVEU")
assert not acad.inputs and not acad.alerts, (acad.inputs, acad.alerts)
uis = acad.ldata[("TOPOKIT_ANEXE", "UI")]
assert [(u[0], u[1], u[2]) for u in uis] == [("etaj 1", "Apartament 1", 64.0), ("etaj 1", "Apartament 2", 45.0)], uis
assert uis[0][3] == "Living, Dormitor, Bucătărie, Baie `si Balcon", uis[0]
tr = texts("RELEVEU_etaj_1")
for need in ["Releveu etaj 1", "Suprafața utilă", "Suprafața totală", "64.0", "70.0", "45.0", "53.0",
             "Apartament 1", "Apartament 2", "Logie", "%%uAnexa nr. 18"]:
    assert need in tr, (need, tr)
render("RELEVEU_etaj_1", "anexa18_releveu")
rows, tot = fn("TKA:UiTable", 1045.0)
d = [dict((x.car, x.cdr) for x in r) for r in rows]
assert [r["CPC"] for r in d] == ["640/1090", "450/1090"] and d[0]["SU"] == "64.0", d
cpt = [int(r["CPT"].split("/")[0]) for r in d]
assert sum(cpt) == 104500 and all(r["CPT"].endswith("/104500") for r in d), d
assert d[0]["COD"] == "123456-C1-U1" and d[1]["NRAP"] == "Apartament 2", d
print(f"RELEVEU (anexa 18): 2 UI, Su 64.0 + 45.0 mp; foaia colectiva Cpt {cpt}")

# ---------------------------------------------------------------- anexele Word: fisierul JSON
recp = fn("TKA:Imobil", parcel, None, [c1, c2], None, None)
env[Sym("*TKA:UIDATA*")] = [rows, tot]
fn("TKA:MakeWord", [13, 14, 15, 20, 0, 19], recp, "")
job = os.path.join(OUT, "Anexe_123456", "TopoKit_anexe.json")
data = json.load(open(job, encoding="utf-8"))
F, TB = data["fields"], data["tables"]
assert F["P1_NUMEC"] == "Ionescu Maria" and F["UAT"] == "Brașov" and F["SMAS"] == str(area), F
assert F["E_NUMEC"] == "ing. Buția Mihai Alexandru" and F["E_AUT"] == "seria RO-BV-F nr. 0123", F
assert F["CHK_PRIMA"] == "[X]" and F["CHK_EMAIL"] == "[X]" and F["NRCF_NRCAD"] == "123456 / 123456", F
assert F["ADRESA"] == "loc. Brașov, str. Lalelelor nr. 12, jud. Brașov", F["ADRESA"]
assert F["TOT_CPT"] == "104500/104500" and F["C1_SC_MP"] == "120 mp", F
assert "CHK_D4" not in F and F["CHK_D5"] == "[X]" and F["LIT_TEXT"] == "imobilul nu se află în litigiu.", F
assert "C1 - Casă de locuit, regim de înălțime P+1E" in F["CONSTR_TEXT"], F["CONSTR_TEXT"]
assert len(TB["PCT"]) == 6 and TB["PCT"][0]["NR"] == "1" and TB["PCT"][0]["X"] == "458040,000", TB["PCT"][0]
assert [r["LATURA"] for r in TB["LAT"]] == ["1-2", "2-3-4", "4-5", "5-6", "6-1"], TB["LAT"]
assert TB["LAT"][1]["VECIN"] == "" and TB["LAT"][1]["ID"] == "str. Lalelelor", TB["LAT"]
assert TB["PROP"][0]["CNP"] == "2800101080011" and len(TB["UI"]) == 2, TB["PROP"]
assert [os.path.basename(x["output"].replace("\\", "/")) for x in data["documents"]] == [
    "Anexa13_Cerere_receptie_inscriere.docx", "Anexa14_Declaratie.docx", "Anexa15_Memoriu_tehnic.docx",
    "Anexa20_PV_vecinatate.docx", "Inventar_coordonate.docx", "Anexa19_Foaia_colectiva.docx"]
assert any("TopoKitDocx.ps1" in r for r in acad.runs) and any(r.startswith("explorer.exe") for r in acad.runs) is False
print(f"Anexe Word: JSON cu {len(F)} campuri, {len(data['documents'])} documente")
if WORD:
    pwsh = shutil.which("pwsh") or os.environ.get("PWSH")
    if pwsh:
        # caile din job folosesc "\" (Windows); pe Linux se normalizeaza
        txt = open(job, encoding="utf-8").read().replace("\\\\", "/")
        open(job, "w", encoding="utf-8").write(txt)
        subprocess.run([pwsh, "-NoProfile", "-File", os.path.join(ROOT, "anexe", "TopoKitDocx.ps1"), "-Job", job], check=True)
        log = open(job + ".log", encoding="utf-8").read()
        assert log.count("OK\t") == 6 and "EROARE" not in log, log
        import zipfile
        doc13 = zipfile.ZipFile(os.path.join(OUT, "Anexe_123456", "Anexa13_Cerere_receptie_inscriere.docx")).read("word/document.xml").decode()
        assert "Ionescu Maria" in doc13 and "{{" not in doc13, "campuri necompletate in anexa 13"
        print("Anexe Word completate cu PowerShell:", OUT)
    else:
        print("pwsh lipseste: completarea sabloanelor Word este omisa")

# ---------------------------------------------------------------- meniul ANEXE si dialogurile de date
acad.runs.clear()
acad.dcl.scripts = {
    "tka_main": [[("click", "bt_imobil")], [("click", "bt_lucrare")], [("click", "bt_exec")], [("click", "bt_opt")],
                 [("click", "pk_prima"), ("set", "tg_pdf", "0"), ("click", "accept")]],
    "tka_imobil": [[("set", "P2_NUME", "Ionescu"), ("set", "P2_PRENUME", "Andrei"), ("pick", "CATEG", "10")]],
    "tka_lucrare": [[("pick", "TIP", "0"), ("pick", "COMUNICARE", "1"), ("set", "PV_EXEMPLARE", "4"),
                     ("set", "POZ_INCERTA", "1")]],
    "tka_exec": [[("set", "E_FIRMA", "Topo Expert SRL")]],
    "tka_opt": [[("pick", "pl_format", "0"), ("pick", "pl_scara", "3"), ("set", "rr_sep", "rb_virg"), ("set", "tg_inv", "1")]],
    "tka_laturi": [[("click", "accept")]]}
acad.inputs = [("kw", "Da")]
n0 = len(acad.dcl.log)
fn("c:ANEXE")
assert not acad.inputs and not acad.alerts, (acad.inputs, acad.alerts)
assert acad.dcl.log[n0:] == ["tka_main", "tka_imobil", "tka_main", "tka_lucrare", "tka_main", "tka_exec",
                             "tka_main", "tka_opt", "tka_main", "tka_laturi"], acad.dcl.log[n0:]
assert fn("TKA:Get", "P2_NUME") == "Ionescu" and fn("TKA:Get", "CATEG") == "CC" and fn("TKA:Get", "COMUNICARE") == "POSTA"
assert acad.envs["TopoKit_E_FIRMA"] == "Topo Expert SRL" and env[Sym("*TKA:SCARA*")] == 500
assert env[Sym("*TKA:SEL*")] == ["16", 13, 14, 15, 20, 0] and fn("TKA:Get", "TIP") == "PRIMA"
lay2 = "PAD_123456_2"                                   # al doilea PAD: nume unic
assert lay2.upper() in acad.layouts and "Scara 1:500" in texts(lay2), texts(lay2)[:5]
assert "Inventar de coordonate (Stereo 70)" in texts(lay2)
data = json.load(open(job, encoding="utf-8"))
assert data["fields"]["P2_NUMEC"] == "Ionescu Andrei" and data["fields"]["CHK_POSTA"] == "[X]"
assert data["fields"]["CHK_D4"] == "[X]"                         # coproprietar -> informarea celorlalti proprietari
assert data["fields"]["E_NUMEC_AUT"] == "ing. Buția Mihai Alexandru, autorizat ANCPI seria RO-BV-F nr. 0123, Topo Expert SRL"
assert len(data["documents"]) == 5 and data["pdf"] is False
assert sum("explorer.exe" in r for r in acad.runs) == 0     # folderul se deschide doar daca scriptul a creat fisiere
render(lay2, "anexa16_PAD_1_500_inventar")
for k in ("tka_main", "tka_imobil", "tka_lucrare", "tka_exec", "tka_opt"): SNAP[k] = acad.dcl.snapshots[k]
print("Meniul ANEXE: dialoguri, pachetul 'Prima inregistrare', PAD 1:500 cu inventar si anexele Word")

# ---------------------------------------------------------------- PAD + releveu din meniu (layout curent -> model)
acad.dcl.scripts = {"tka_main": [[("pick", "lb_anexe", "0 3"), ("click", "accept")]], "tka_laturi": [[("click", "accept")]]}
acad.inputs = [("kw", "Da"), ("ssget", rooms), ("ssget", [ui1, ui2]), ("str", "parter")]
fn("c:ANEXE")
assert not acad.inputs and "RELEVEU_PARTER" in acad.layouts and acad.vars["CTAB"] == "RELEVEU_parter"
print("Meniul ANEXE: PAD urmat de releveu (selectia revine in model space)")

# ---------------------------------------------------------------- parcele de folosinta + releveu cu o singura UI
acad.add_text((545004.0, 458035.0), "A", 0.35, "TEXTE")                # categoria scrisa in parcela
n_lay = set(acad.layouts)
acad.inputs = [("entsel", parcel), ("ssget", [c1, c2]), ("ssget", [lot1, lot2])]
acad.dcl.scripts = {"tka_laturi": [[("click", "accept")]]}
fn("c:PAD")
newlay = [acad.layouts[k].name for k in set(acad.layouts) - n_lay][0]
tp = texts(newlay)
assert "1A" in tp and "2CC" in tp and str(la[0]) in tp and str(la[1]) in tp, tp     # etichete + tabelul A
assert fn("TKA:LGet", lot1, "CATEG") == "A" and fn("TKA:LGet", lot2, "CATEG") == "CC"
acad.inputs = [("ssget", rooms[:5]), ("ssget", None), ("str", ""), ("str", "mansarda")]
fn("c:RELEVEU")
uis = acad.ldata[("TOPOKIT_ANEXE", "UI")]
assert [(u[0], u[1], u[2]) for u in uis][-1] == ("mansarda", "Apartament 1", 64.0), uis
print("Parcele de folosinta (A, CC) si releveu cu o singura UI: corecte")

# ---------------------------------------------------------------- verificarea: oprirea generarii la erori
bow = acad.add_lw([(545100, 458000), (545130, 458030), (545130, 458000), (545100, 458030)], layer="IMOBIL")
n_lay = set(acad.layouts)
acad.inputs = [("entsel", bow), ("ssget", None), ("ssget", None)]
acad.dcl.scripts = {"tka_laturi": [[("click", "accept")]], "tka_raport": [[("click", "cancel")]]}
fn("c:PAD")
rap = acad.dcl.snapshots["tka_raport"]["lists"]["lb_rap"]
assert "E: Conturul imobilului se autointersecteaza." in rap, rap
SNAP["tka_raport"] = acad.dcl.snapshots["tka_raport"]
assert set(acad.layouts) == n_lay and env[Sym("*TKA:STOP*")], "planul nu trebuia generat"
acad.envs["TopoKit_E_NUME"] = ""
acad.dcl.scripts = {"tka_raport": [[("click", "accept")]]}
fn("c:VERIFICARE")
rap = acad.dcl.snapshots["tka_raport"]
assert "A: Lipsesc datele executantului (persoana autorizata)." in rap["lists"]["lb_rap"], rap["lists"]
assert rap["tiles"]["accept"] == "OK" and "Continuati" not in rap["tiles"]["tx_titlu"], rap["tiles"]
acad.envs["TopoKit_E_NUME"] = "Buția"
# arce: suprafata analitica din varfuri + atentionare
arc = acad.add_lw([(545200, 458000), (545220, 458000), (545220, 458020), (545200, 458020)], layer="IMOBIL", bulges={0: 0.2})
assert fn("TKA:HasArcs", arc) and abs(fn("TKA:Area", arc) - 400.0) < 1e-6
msgs = fn("TKA:Verify", fn("TKA:Imobil", arc, None, None, None, None), None, None)
assert any(m.startswith("A: Conturul are laturi ^in arc") for m in msgs), msgs
# loturi care nu acopera imobilul / se suprapun
lotx = acad.add_lw([P[0], P[1], B, (545010.0, 458010.0)], layer="LOTURI")
r_par = fn("TKA:Imobil", parcel, None, None, None, None)
msgs = fn("TKA:Verify", r_par, [fn("TKA:Imobil", l, None, None, None, None) for l in (lotx, lot2)], "DEZ")
assert any(m.startswith("E: Loturile ^insumeaz`a") for m in msgs) and any("se suprapun" in m for m in msgs), msgs
print("Verificare: autointersectie (generare oprita), date lipsa, arce, loturi suprapuse")

# ---------------------------------------------------------------- planurile in PDF
env[Sym("*TKA:PDFPLAN*")] = "1"
acad.vars["BACKGROUNDPLOT"] = 2
acad.inputs = [("entsel", parcel), ("ssget", [c1, c2]), ("ssget", None)]
acad.dcl.scripts = {"tka_laturi": [[("click", "accept")]]}
fn("c:PAD")
assert len(acad.plots) == 1 and os.path.exists(acad.plots[0][1]) and acad.plots[0][1].endswith(".pdf"), acad.plots
assert acad.vars["BACKGROUNDPLOT"] == 2, "BACKGROUNDPLOT nu a fost restabilit"
env[Sym("*TKA:PDFPLAN*")] = "0"
acad.plots.clear()
fn("c:PLANEPDF")
gen = [l for l in fn("LAYOUTLIST") if l.upper().startswith(("PAD_", "RELEVEU_"))]
assert sorted(x[0] for x in acad.plots) == sorted(gen) and len(gen) >= 10, (acad.plots, gen)
print(f"Planuri PDF: dupa generare si comanda PLANEPDF ({len(gen)} layout-uri)")

# ---------------------------------------------------------------- numerotarea din desen (texte / blocuri de punct)
for k, (x, y) in enumerate([P[0], P[1], P[2], P[3], P[4]]):
    if k == 2:
        acad.add_insert((x, y), "PUNCT", [("COTA", "512.30"), ("NR", "129")])     # bloc de punct
    else:
        acad.add_text((x + 0.6, y + 0.6), str([127, 128, 0, 130, 131][k]), 0.3, "PUNCTE")
env[Sym("*TKA:NRMOD*")] = "DES"
tabd = fn("TKA:Numbering", [fn("TKA:Clockwise", fn("TKA:PolyPts", parcel))], 1)
nums = [fn("TKA:PtNo", list(p), tabd) for p in P]
assert nums == [127, 128, 129, 130, 131, 132], nums                # P6 fara numar -> 132 (urmatorul)
env[Sym("*TKA:NRMOD*")] = "NV"
print("Numerotarea din desen: 127-131 din texte si bloc, punctul fara numar -> 132")

# ---------------------------------------------------------------- MVIEW esuat: mesaj si transformarea calculata
orig_cmd = M.funcs[Sym("COMMAND")]
M.funcs[Sym("COMMAND")] = lambda *a: None if a and isinstance(a[0], str) and "MVIEW" in a[0].upper() else orig_cmd(*a)
fn("TK:Start"); fn("TKA:NewLayout", "TEST_MVIEW", fn("TKA:Sheet", "A3L", 100.0))
assert fn("TKA:Viewport", [22.0, 7.0, 230.0, 290.0], [545000.0, 458000.0], 200) is None
assert env[Sym("*TKA:VPT*")] == [545000.0, 458000.0, 126.0, 148.5, 5.0] and "creat (MVIEW)" in acad.out[-1]
M.funcs[Sym("COMMAND")] = orig_cmd; fn("TK:Stop")
print("MVIEW esuat: atentionare si transformarea calculata (adnotarile raman corecte)")

# ---------------------------------------------------------------- releveu reluat: UI raman in ordine
acad.inputs = [("ssget", rooms), ("ssget", [ui1, ui2]), ("str", "etaj 1")]
fn("c:RELEVEU")
order = [u[0] for u in acad.ldata[("TOPOKIT_ANEXE", "UI")]]
assert order[:2] == ["etaj 1", "etaj 1"] and order.count("etaj 1") == 2, order
print("Releveu reluat pentru un nivel existent: ordinea UI se pastreaza")

# ---------------------------------------------------------------- dialogul generat din TKA:DclLines
lines = fn("TKA:DclLines")
assert lines == open(os.path.join(ROOT, "TopoKitAnexe.dcl"), encoding="utf-8").read().splitlines(), \
    "TKA:DclLines nu corespunde cu TopoKitAnexe.dcl (rulati tools/embed_dcl.py)"
real_find = M.funcs[Sym("FINDFILE")]
M.funcs[Sym("FINDFILE")] = lambda f: None if f.lower().endswith(".dcl") or f.lower().endswith(".lsp") else real_find(f)
env[Sym("*TKA:DCLTMP*")] = None
tmp = fn("TKA:DclPath")
assert tmp and open(tmp, encoding="utf-8").read().splitlines() == lines
M.funcs[Sym("FINDFILE")] = real_find
print("Dialogul DCL de rezerva (TKA:DclLines): identic cu TopoKitAnexe.dcl")
# ---------------------------------------------------------------- TOPOKIT: modulul 4 deschide meniul anexelor
acad.dcl.scripts = {"topokit_main": [[("click", "bt_anexe")]], "tka_main": [[("click", "cancel")]]}
n0 = len(acad.dcl.log)
fn("c:TOPOKIT")
assert acad.dcl.log[n0:] == ["topokit_main", "tka_main"], acad.dcl.log[n0:]
assert acad.dcl.last["tiles"]["tx_stare"].startswith("Imobil: nr. cad. 123456"), acad.dcl.last["tiles"]["tx_stare"]
print("TOPOKIT: butonul 'Generator anexe...' deschide meniul ANEXE")
SNAP["topokit_main"] = acad.dcl.snapshots["topokit_main"]
if RENDER:
    from dcl_mockup import Mockup
    for name, snap in SNAP.items():
        src = "TopoKit.dcl" if name.startswith("topokit") else "TopoKitAnexe.dcl"
        Mockup(open(os.path.join(ROOT, src), encoding="utf-8").read(), name, snap).render(
            os.path.join(RENDER, "macheta_" + name + ".png"))
    print("Machetele dialogurilor:", RENDER)
print("\nToate testele TopoKitAnexe au trecut.")
