#!/usr/bin/env python3
"""Teste offline pentru TopoKitProiect.lsp (pregatire proiect nou, scara, caroiaj).

    python tests/test_proiect.py

In simulatorul AutoCAD: straturile standard (culori, grosimi, diacritice), stergerea
straturilor nefolosite, Arial in stilurile de text, unitatile, scara (CANNOSCALE,
LTSCALE, PDSIZE, setarile TopoKit), redimensionarea textelor la TKSCARA si caroiajul
desenat fara Civil 3D. Partea Civil 3D ruleaza pe un model COM simulat; fiecare
proprietate folosita trebuie sa existe in API-ul Civil 3D 2026 (tests/data/civil3d_com_names.txt),
iar valorile (stiluri, enumerari, marimi) se verifica una cate una.
"""
import os, sys, math, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from acad_sim import Acad, Sym, call, env, grp, grps, DP, T, Obj
import autolisp_mini as M

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.environ.get("TOPOKIT_OUT") or tempfile.mkdtemp(prefix="topokit_proiect_")
acad = Acad(ROOT, OUT)
COM_NAMES = {}
for _n in open(os.path.join(os.path.dirname(__file__), "data", "civil3d_com_names.txt")):
    _n = _n.strip()
    if _n and not _n.startswith("#") and (_n.upper() not in COM_NAMES or _n[0].isupper()):
        COM_NAMES[_n.upper()] = _n                 # "Color" inaintea lui "color" (interfetele XML)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------- model COM Civil 3D simulat
PUTS = {}            # (drum, proprietate) -> valoare
CALLS = []           # (drum, metoda, argumente)


class Com:
    def __init__(s, path, **props):
        s.path, s.props, s.cache = path, {k.upper(): v for k, v in props.items()}, {}

    def __repr__(s): return f"<COM {s.path}>"

    def get(s, p):
        p = str(p).upper()
        check(p in COM_NAMES, f"proprietate Civil 3D inexistenta: {s.path}.{p}")
        if p in s.props: return s.props[p]
        if p not in s.cache:
            s.cache[p] = Coll(f"{s.path}.{COM_NAMES[p]}") if p.endswith("COMPONENTS") else Com(f"{s.path}.{COM_NAMES[p]}")
        return s.cache[p]

    def put(s, p, v):
        p = str(p).upper()
        check(p in COM_NAMES, f"proprietate Civil 3D inexistenta: {s.path}.{p}")
        s.props[p] = v
        PUTS[(s.path, COM_NAMES[p])] = v
        return v

    def invoke(s, m, args):
        CALLS.append((s.path, str(m).upper(), list(args)))
        return None


class Coll(Com):
    def __init__(s, path, names=()):
        super().__init__(path)
        s.items = [Com(f"{path}[{n}]", Name=n) for n in names]

    def invoke(s, m, args):
        m = str(m).upper()
        CALLS.append((s.path, m, list(args)))
        if m == "ADD":
            o = Com(f"{s.path}[{args[0]}]", Name=args[0])
            s.items.append(o)
            return o
        return super().invoke(m, args)


cdoc = Com("Doc", PointStyles=Coll("PointStyles", ["Standard", "Basic"]),
           PointLabelStyles=Coll("PointLabelStyles", ["Description Only", "Point Number Only"]),
           GeneralNoteLabelStyles=Coll("NoteStyles", ["General Note"]),
           PointGroups=Coll("PointGroups", ["_All Points"]))
c3dapp = Com("App", ActiveDocument=cdoc)
civil = [True]


def getinterface(app, progid):
    if civil[0] and progid == "AeccXUiLand.AeccApplication.13.8":
        return c3dapp
    raise M.LispError(f"clasa inexistenta {progid}") if hasattr(M, "LispError") else RuntimeError(progid)


def vlax_get(o, p):
    if isinstance(o, Com): return o.get(p)
    if isinstance(o, Obj): return o.props.get(str(p).upper())
    raise RuntimeError(f"vlax-get {o} {p}")


def vlax_put(o, p, v):
    if isinstance(o, Com): return o.put(p, v)
    raise RuntimeError(f"vlax-put {o} {p}")


def vlax_invoke(o, m, *a):
    if isinstance(o, Com): return o.invoke(m, a)
    if isinstance(o, Obj) and str(m).upper() == "GETATTRIBUTES": return list(o.atts)
    raise RuntimeError(f"vlax-invoke {o} {m}")


# ---------------------------------------------------------------- AutoCAD: tabele, stiluri, comenzi
acad.tables["LTYPE"] = {}


def tblobjname(t, n):
    return ("TBL", t.upper(), n.upper()) if n.upper() in acad.tables.get(t.upper(), {}) else None


_entget = acad.entget
def entget(e, *a):
    if isinstance(e, tuple) and e[0] == "TBL":
        return list(acad.tables[e[1]][e[2]]) + [DP(-1, e)]
    return _entget(e, *a)


def entmod(d):
    e = grp(d, -1)
    d = [x for x in d if not (isinstance(x, DP) and x.car in (-1, 5))]
    if isinstance(e, tuple) and e[0] == "TBL":
        acad.tables[e[1]][e[2]] = d
    else:
        acad.db[e] = d
    return d


def layer_objs(doc):
    return Obj("layers", items=[Obj("layer", name=grp(d, 2)) for d in acad.tables["LAYER"].values()])


REFD = {"V-NODE", "GOL UTILIZATOR"}            # straturi goale, dar folosite de stiluri
DELETE_TRIED = []
def vla_delete(o):
    if o.kind == "layer":
        DELETE_TRIED.append(o.name.upper())
        used = {(grp(acad.db[e], 8) or "").upper() for e in acad.order if e not in acad.deleted}
        if o.name.upper() in used or o.name.upper() in REFD:
            raise RuntimeError("Object is referenced")
        del acad.tables["LAYER"][o.name.upper()]
        return None
    raise RuntimeError(o.kind)


# blocurile desenului: model space (entitatile simulatorului) + un bloc cu un obiect pe A-BLOC
# si o insertie cu atribut pe C-ATRIB
def blocks(doc):
    ms = [Obj("ent", layer=grp(acad.db[e], 8) or "0", oname="AcDbText") for e in acad.order if e not in acad.deleted]
    ms.append(Obj("ent", layer="0", oname="AcDbBlockReference", atts=[Obj("ent", layer="C-ATRIB", oname="AcDbAttribute")]))
    return Obj("blocks", items=[Obj("block", items=ms), Obj("block", items=[Obj("ent", layer="A-BLOC", oname="AcDbLine")])])


def style_objs(doc):
    return Obj("styles", items=[Obj("style", name=grp(d, 2)) for d in acad.tables["STYLE"].values()])


def setfont(o, face, bold, italic, cs, pf):
    d = acad.tables["STYLE"][o.name.upper()]
    acad.tables["STYLE"][o.name.upper()] = [x for x in d if not (isinstance(x, DP) and x.car == 3)] + [DP(3, face + ".ttf")]
    return None


COMMANDS = []
def command(*args):
    COMMANDS.append(list(args))
    if args and args[0] == "_.-LAYMRG":            # LAYMRG: stratul gol se muta pe 0 si dispare
        assert list(args[1:2] + args[3:]) == ["_N", "", "_N", "0", "_Y"], args
        acad.tables["LAYER"].pop(args[2].upper(), None)
    return None


for k, v in {"TBLOBJNAME": tblobjname, "ENTGET": entget, "ENTMOD": entmod, "COMMAND": command,
             "VLA-GET-LAYERS": layer_objs, "VLA-GET-NAME": lambda o: o.name, "VLA-DELETE": vla_delete,
             "VLA-GET-TEXTSTYLES": style_objs, "VLAX-VLA-OBJECT->ENAME": lambda o: ("TBL", "LAYER" if o.kind == "layer" else "STYLE", o.name.upper()),
             "VLA-SETFONT": setfont, "VLA-REGEN": lambda *a: None, "VLA-GET-LINETYPES": lambda d: Obj("ltypes"),
             "VLA-LOAD": lambda *a: None, "NAMEDOBJDICT": lambda: "NOD", "DICTSEARCH": lambda *a: None,
             "VLA-GETINTERFACEOBJECT": getinterface, "VLAX-GET": vlax_get, "VLAX-PUT": vlax_put,
             "VLAX-INVOKE": vlax_invoke, "VLAX-PUT-PROPERTY": vlax_put, "GETCORNER": lambda *a: acad.ask("pt"), "GETPOINT": lambda *a: acad.ask("pt"),
             "TEXTSCR": lambda: None, "GETINT": lambda *a: acad.ask("int"),
             "VLA-GET-BLOCKS": blocks, "VLA-GET-LAYER": lambda o: o.layer,
             "VLA-GET-OBJECTNAME": lambda o: o.oname,
             "VLA-GET-HASATTRIBUTES": lambda o: "VLAX-TRUE" if getattr(o, "atts", None) else "VLAX-FALSE"}.items():
    M.funcs[Sym(k)] = v
env[Sym(":VLAX-TRUE")] = "VLAX-TRUE"
env[Sym(":VLAX-FALSE")] = "VLAX-FALSE"
env[Sym("ACALLVIEWPORTS")] = 3
acad.vars["CMDACTIVE"] = 0

M.load(os.path.join(ROOT, "TopoKit.lsp"))          # incarca si TopoKitProiect.lsp
acad.after_load()
check(any("TopoKit Proiect incarcat" in o for o in acad.out), acad.out[-3:])


def fn(name, *a): return call(Sym(name.upper()), list(a))
def lay(name): return acad.tables["LAYER"].get(name.upper())
def ents(typ, layer=None):
    return [e for e in acad.entities("Model", typ) if layer is None or (grp(acad.db[e], 8) or "") == layer]


# ---------------------------------------------------------------- desenul "Civil 3D" de pornire
for name, col in (("C-TOPO-POINTS", 2), ("V-NODE", 3), ("C-ANNO", 7), ("Proprietari", 6), ("Gol utilizator", 4),
                  ("A-BLOC", 1), ("C-ATRIB", 2)):
    acad.entmake([DP(0, "LAYER"), DP(2, name), DP(70, 0), DP(62, col)])
acad.add_text([10.0, 10.0], "obiect", 1.0, "Proprietari")          # strat folosit: ramane
acad.vars["CLAYER"] = "C-ANNO"
acad.entmake([DP(0, "STYLE"), DP(2, "Standard"), DP(70, 0), DP(3, "txt.shx")])
acad.entmake([DP(0, "STYLE"), DP(2, "Annotative"), DP(70, 0), DP(3, "romans.shx")])
acad.entmake([DP(0, "STYLE"), DP(2, "LTYPESHP"), DP(70, 1), DP(3, "ltypeshp.shx")])   # stil de forme

# ---------------------------------------------------------------- TKPROIECT (dialog)
acad.dcl.scripts["tkp_proiect"] = [("set", "scara", "3"), ("set", "unghi", "G"), ("click", "accept")]
fn("c:TKPROIECT")
out = "".join(acad.out)

# DOAR straturile goale se sterg: C-TOPO-POINTS si C-ANNO direct, V-NODE (folosit de stiluri) cu LAYMRG
for name in ("C-TOPO-POINTS", "V-NODE", "C-ANNO"):
    check(lay(name) is None, f"stratul gol {name} trebuia sters")
check([c for c in COMMANDS if c[0] == "_.-LAYMRG"] == [["_.-LAYMRG", "_N", "V-NODE", "", "_N", "0", "_Y"]], COMMANDS)
# straturile cu obiecte (in model, intr-un bloc, intr-un atribut) nu se ating deloc
for name in ("Proprietari", "A-BLOC", "C-ATRIB"):
    check(lay(name) is not None and name.upper() not in DELETE_TRIED, f"stratul cu obiecte {name} nu se sterge")
# stratul gol al utilizatorului folosit de un stil (nume care nu e din sablonul Civil 3D) ramane
check(lay("Gol utilizator") is not None, "stratul gol folosit de stiluri, din afara sablonului, ramane")
check(lay("0") is not None, "stratul 0")
check("Straturi goale sterse: 3 (1 goale raman: sunt folosite de stiluri); straturile cu obiecte nu se sterg." in out, out[-900:])

# straturile standard, cu diacritice
expect = {"Puncte": (7, 0), "Puncte Leica": (7, 0), "Puncte interpolate": (7, 0), "Terenuri": (6, 40),
          "Vecinătăți": (3, -3), "Dimensiuni": (7, -3), "Construcții": (5, 0), "Caroiaj": (8, 0), "PAD": (7, -3),
          "Ascuns - puncte Leica": (-7, 0)}
for name, (col, lw) in expect.items():
    d = lay(name)
    check(d is not None, f"lipseste stratul {name}")
    check(grp(d, 2) == name and grp(d, 62) == col and grp(d, 370) == lw, f"{name}: {d}")
check(len([k for k in acad.tables["LAYER"] if k not in ("0", "PROPRIETARI", "GOL UTILIZATOR", "A-BLOC", "C-ATRIB")]) == 15,
      acad.tables["LAYER"].keys())
check(acad.vars["CLAYER"] == "Puncte", "stratul curent: Puncte")
# a doua curatare (proiect deja pregatit): straturile standard goale, cu sau fara diacritice, raman
DELETE_TRIED.clear()
r = fn("TKP:Purge")
check(all(lay(n) is not None for n in expect), "straturile standard nu se sterg")
check(not any(n in DELETE_TRIED for n in ("VECINĂTĂȚI", "CONSTRUCȚII", "PUNCTE", "CAROIAJ")), DELETE_TRIED)
acad.vars["CLAYER"] = "Puncte"

# Arial in stilurile de text, nu si in stilul de forme
for s in ("STANDARD", "ANNOTATIVE"):
    check(grp(acad.tables["STYLE"][s], 3) == "Arial.ttf", s)
check(grp(acad.tables["STYLE"]["LTYPESHP"], 3) == "ltypeshp.shx", "stilul de forme ramane")
check("Font Arial in 2 stiluri de text" in out, out[-600:])

# unitati si scara 1:500
v = acad.vars
check((v["INSUNITS"], v["LUNITS"], v["LUPREC"], v["AUNITS"], v["AUPREC"]) == (6, 2, 3, 2, 4), "unitati")
check(v["CANNOSCALE"] == "1:500" and abs(v["LTSCALE"] - 1.0) < 1e-9 and v["MSLTSCALE"] == 0, "scara")
check(v["PDMODE"] == 33 and abs(v["PDSIZE"] - 0.5) < 1e-9, "PTYPE: cerculet de 0.5 m la 1:500")
check(["_.-SCALELISTEDIT", "_A", "1:500", "1:500", "_E"] in COMMANDS, COMMANDS)
check(fn("TKP:Scara") == 500 and fn("TKC:Cfg", "SCARA") == 500.0, "scara salvata pentru TopoKit si cadastru")
check(env[Sym("*TK:SCARA*")] == 2, "scara cadrului (1:500)")

# Civil 3D: unitati, puncte, etichete, caroiaj
P = PUTS
amb = "Doc.Settings.DrawingSettings.AmbientSettings"
check(P[("Doc.Settings.DrawingSettings.UnitZoneSettings", "DrawingUnits")] == 2, "metri")
check(P[("Doc.Settings.DrawingSettings.UnitZoneSettings", "AngularUnits")] == 3, "grade centesimale")
check(P[(amb + ".DistanceSettings.Unit", "Value")] == 1 and P[(amb + ".DistanceSettings.Precision", "Value")] == 2, "distante")
check(P[(amb + ".AngleSettings.Unit", "Value")] == 3 and P[(amb + ".AngleSettings.Format", "Value")] == 1, "unghiuri")
check(P[(amb + ".DirectionSettings.MeasurementType", "Value")] == 2, "azimut")
check(P[(amb + ".AreaSettings.Unit", "Value")] == 1 and P[(amb + ".CoordinateSettings.Precision", "Value")] == 3, "arii, coord")
ps = "PointStyles[Basic]"
check(P[(ps, "MarkerType")] == 0 and P[(ps, "MarkerSizeType")] == 0 and abs(P[(ps, "MarkerSize")] - 0.001) < 1e-12, "Basic")
check(P[(ps + ".MarkerDisplayStylePlan", "Color")] == 7, "punct alb")
lbl = "PointLabelStyles[Point Description]"
check(("PointLabelStyles", "ADD", ["Point Description"]) in CALLS, "stilul Point Description se creeaza")
tc = lbl + ".TextComponents[Point Description]"
check(P[(tc + ".Contents", "Value")] == "<[Full Description(CP)]>", "descrierea")
check(abs(P[(tc + ".Height", "Value")] - 0.0015) < 1e-12 and P[(tc + ".Color", "Value")] == 7, "1.5 mm, alb")
check(P[(tc + ".AnchorPoint", "Value")] == 3 and P[(tc + ".Attachment", "Value")] == 3, "Middle left / Middle left")
check(abs(P[(tc + ".XOffset", "Value")] - 0.00075) < 1e-12, "gap = jumatate din text")
check(P[(lbl + ".DraggedLeaderStyle.Visibility", "Value")] == "VLAX-FALSE", "fara leader cand e mutata")
check(P[(lbl + ".DraggedComponentStyle.StackText", "Value")] == "VLAX-FALSE", "as composed")
check(P[(lbl + ".LabelProperties.TextStyle", "Value")] == "Standard", "stilul de text (Arial)")
check(P[("Doc.Settings.PointSettings.StyleSettings.Style", "Value")] == "Basic", "stilul punctelor noi")
check(P[("Doc.Settings.PointSettings.StyleSettings.LabelStyle", "Value")] == "Point Description", "eticheta noua")
check(P[("PointGroups[_All Points]", "PointLabelStyle")].path == lbl, "_All Points")
check(P[("Doc.Settings.DrawingSettings.ObjectLayerSettings.PointEntityLayer", "Layer")] == "Puncte", "strat puncte")
check(P[("Doc.Settings.DrawingSettings.ObjectLayerSettings.GeneralNoteLabelLayer", "Layer")] == "Caroiaj", "strat caroiaj")

# stilurile de caroiaj: N= orizontal, E= vertical, linii in L spre interior
for k, (sx, sy, an, ae) in {"stanga sus": (1, -1, 0, 2), "dreapta sus": (-1, -1, 2, 8),
                             "stanga jos": (1, 1, 6, 0), "dreapta jos": (-1, 1, 8, 6)}.items():
    st = f"NoteStyles[Caroiaj - colt {k}]"
    n, e = st + ".TextComponents[Nord]", st + ".TextComponents[Est]"
    check(P[(n + ".Contents", "Value")] == "N=<[Northing(Um|P0|RN|AP|GC|UN|Sn|OF)]>", k)
    check(P[(e + ".Contents", "Value")] == "E=<[Easting(Um|P0|RN|AP|GC|UN|Sn|OF)]>", k)
    check(P[(n + ".Attachment", "Value")] == an and P[(e + ".Attachment", "Value")] == ae, f"{k}: atasare")
    check(P[(n + ".Angle", "Value")] == 0.0 and abs(P[(e + ".Angle", "Value")] - math.pi / 2) < 1e-12, k)
    check(math.copysign(1, P[(n + ".XOffset", "Value")]) == sx and math.copysign(1, P[(e + ".YOffset", "Value")]) == sy, k)
    ho, ve = st + ".LineComponents[Linie orizontala]", st + ".LineComponents[Linie verticala]"
    check(abs(P[(ho + ".Angle", "Value")] - (0.0 if sx > 0 else math.pi)) < 1e-12, k)
    check(abs(P[(ve + ".Angle", "Value")] - (math.pi / 2 if sy > 0 else 1.5 * math.pi)) < 1e-12, k)
    check(abs(P[(ho + ".Length", "Value")] - 0.013) < 1e-12, k)
    check(P[(ho + ".UseEndPointAnchor", "Value")] == "VLAX-FALSE", f"{k}: linia are unghi si lungime proprii")
    # textele nu se suprapun in colt: incep la 1.5 x inaltimea din colt
    check(abs(abs(P[(n + ".XOffset", "Value")]) - 0.00225) < 1e-12 and abs(abs(P[(e + ".YOffset", "Value")]) - 0.00225) < 1e-12, k)
    check(P[(st + ".LabelProperties.PlanReadable", "Value")] == "VLAX-FALSE", k)
check(abs(P[("NoteStyles[Caroiaj - cruciulita].LineComponents[Brat sud].Angle", "Value")] - 1.5 * math.pi) < 1e-12, "cruce")
# textul implicit "Note" al stilurilor noi se ascunde (doar coordonatele si liniile)
for k in ("colt stanga sus", "colt dreapta jos"):
    st = cdoc.get("GeneralNoteLabelStyles")
    sty = next(x for x in st.items if x.props.get("NAME") == f"Caroiaj - {k}")
    note = sty.get("TextComponents").invoke("ADD", ["Text"])     # componenta implicita "Note"
fn("TKP:GridStyles", cdoc)
for k in ("colt stanga sus", "colt dreapta jos"):
    check(P[(f"NoteStyles[Caroiaj - {k}].TextComponents[Text].Visibility", "Value")] == "VLAX-FALSE", f"{k}: Note ascuns")
    check(P[(f"NoteStyles[Caroiaj - {k}].TextComponents[Nord].Visibility", "Value")] == "VLAX-TRUE", k)
check("Civil 3D: stilurile de caroiaj (General Note Label) sunt gata" in out, out[-900:])

# ---------------------------------------------------------------- caroiajul (Civil 3D: General Note Label)
COMMANDS.clear()
acad.inputs += [("pt", [545010.0, 458010.0, 0.0]), ("pt", [545090.0, 458070.0, 0.0]), ("kw", None)]
fn("c:TKCAROIAJ")
notes = [c for c in COMMANDS if c and c[0] == "_.AeccAddNoteLabel"]
check(len(notes) == 5, COMMANDS)                     # 4 colturi + cruciulitele
pts = [c[1] for c in COMMANDS if len(c) == 2 and c[0] == "_non"]
corners = pts[:4]
check(corners == [[545025.0, 458025.0, 0.0], [545075.0, 458025.0, 0.0], [545025.0, 458050.0, 0.0],
                  [545075.0, 458050.0, 0.0]], corners)
check(len(pts) == 4 + 2, pts)                        # noduri 3 x 2: interiorul are 2 cruciulite
check(P[("Doc.Settings.GeneralCommandsSettings.AddNoteLabelSettings.StyleSettings.NoteLabelStyle", "Value")]
      == "Caroiaj - cruciulita", "ultimul stil folosit: cruciulita")
check(acad.vars["CLAYER"] == "Caroiaj", "caroiajul pe stratul Caroiaj")

# ---------------------------------------------------------------- TKSCARA: textele se redimensioneaza
acad.add_text([545030.0, 458030.0], "Ion Popescu", 0.75, "Vecinătăți")
acad.add_text([545030.0, 458040.0], "alt strat", 2.0, "Proprietari")
acad.inputs += [("str", "1:1000")]
fn("c:TKSCARA")
txt = {grp(acad.db[e], 1): grp(acad.db[e], 40) for e in ents("TEXT")}
check(abs(txt["Ion Popescu"] - 1.5) < 1e-9 and txt["alt strat"] == 2.0, txt)
check(acad.vars["CANNOSCALE"] == "1:1000" and abs(acad.vars["LTSCALE"] - 2.0) < 1e-9 and abs(acad.vars["PDSIZE"] - 1.0) < 1e-9, "1:1000")
check(fn("TKP:Scara") == 1000 and fn("TKC:Cfg", "SCARA") == 1000.0, "scara noua salvata")
acad.inputs += [("str", "300")]
fn("c:TKSCARA")
check(fn("TKP:Scara") == 1000 and "Scara trebuie sa fie una din standard" in "".join(acad.out[-3:]), "scara gresita")

# ---------------------------------------------------------------- caroiajul fara Civil 3D (linii si texte)
civil[0] = False
acad.inputs += [("pt", [545000.0, 458000.0, 0.0]), ("pt", [545210.0, 458160.0, 0.0]), ("kw", "Nu")]
n0 = len(ents("LINE", "Caroiaj"))
fn("c:TKCAROIAJ")
lines = ents("LINE", "Caroiaj")[n0:]
check(len(lines) == 8, len(lines))                  # 4 colturi x 2 linii, fara cruciulite
texts = {grp(acad.db[e], 1): acad.db[e] for e in ents("TEXT", "Caroiaj")}
check(set(texts) == {"N=458000", "N=458150", "E=545000", "E=545200"}, set(texts))
for e in ents("TEXT", "Caroiaj"):
    d = acad.db[e]
    check(abs(grp(d, 40) - 1.5) < 1e-9, "text 1.5 m la 1:1000")
    if grp(d, 1).startswith("E="):
        check(abs(grp(d, 50) - math.pi / 2) < 1e-12, "E= vertical")
# coltul stanga jos: linia orizontala spre est, cea verticala spre nord, de 13 m (13 mm la 1:1000)
L = [(grp(acad.db[e], 10), grp(acad.db[e], 11)) for e in lines[:2]]
check(L == [([545000.0, 458000.0, 0.0], [545013.0, 458000.0, 0.0]), ([545000.0, 458000.0, 0.0], [545000.0, 458013.0, 0.0])], L)

print("Toate testele TopoKitProiect au trecut.")
