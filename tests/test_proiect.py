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
# stilul de segment din sablon: "Distance Only" cu lungimea in picioare, 3 zecimale
line_styles = Coll("LineStyles", ["Distance Only"])
_seg = line_styles.items[0].get("TextComponents").invoke("ADD", ["Distance"])
_seg.get("Contents").props["VALUE"] = "<[General Segment Length(Uft|P3|RN|AP|GC|UN|Sn|OF)]>'"
cdoc.props["GENERALLINELABELSTYLES"] = line_styles
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
STYLE_LOG = []
NOTE_ACTIVE = [False]
def command(*args):
    if args and args[0] == "_.AeccAddNoteLabel":
        NOTE_ACTIVE[0] = True
    elif args and args[0] == "_non" and NOTE_ACTIVE[0]:
        acad.entmake([DP(0, "AECC_GENERAL_NOTE_LABEL"), DP(8, "C-ANNO"), [10] + list(args[1])])
    elif args == ("",):
        NOTE_ACTIVE[0] = False
    if args and args[0] == "_.AeccAddNoteLabel":
        STYLE_LOG.append(("style", PUTS.get(("Doc.Settings.GeneralCommandsSettings.AddNoteLabelSettings.StyleSettings.NoteLabelStyle", "Value"))))
    COMMANDS.append(list(args))
    laymrg(list(args))
    return None


# -LAYMRG simulat, si cand argumentele vin in mai multe apeluri (command): _N strat [_N strat ...] "" _N tinta _Y
LAYMRG = {"state": None, "names": [], "runs": []}
def laymrg(args):
    for a in args:
        st = LAYMRG["state"]
        if a == "_.-LAYMRG":
            LAYMRG.update(state="sel", names=[])
        elif st == "sel":
            assert a in ("_N", ""), a
            LAYMRG["state"] = "name" if a == "_N" else "target"
        elif st == "name":
            assert acad.tables["LAYER"].get(a.upper()) is not None, f"LAYMRG: strat inexistent {a}"
            LAYMRG["names"].append(a); LAYMRG["state"] = "sel"
        elif st == "target":
            assert a == "_N", a; LAYMRG["state"] = "tname"
        elif st == "tname":
            assert a == "0", a; LAYMRG["state"] = "yes"
        elif st == "yes":
            assert a == "_Y", a
            for n in LAYMRG["names"]:
                acad.tables["LAYER"].pop(n.upper(), None)       # stratul gol se muta pe 0 si dispare
            LAYMRG["runs"].append(list(LAYMRG["names"])); LAYMRG["state"] = None


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
_setvar = acad.setvar
def setvar(v, val):
    if v.upper() == "CLAYER":
        d = acad.tables["LAYER"].get(str(val).upper())
        if d is None or (grp(d, 70) or 0) & 1:
            raise RuntimeError(f'AutoCAD variable setting rejected: "CLAYER" "{val}"')
    return _setvar(v, val)
M.funcs[Sym("SETVAR")] = setvar
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
check(LAYMRG["runs"] == [["V-NODE"]], LAYMRG["runs"])        # un singur LAYMRG pentru toate straturile din sablon
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
# scara de adnotare ramane 1:1000; la 1:500 se schimba doar marimile
check(v["CANNOSCALE"] == "1:1000" and abs(v["LTSCALE"] - 1.0) < 1e-9 and v["MSLTSCALE"] == 0, "scara")
check(abs(v["DIMSCALE"] - 0.3) < 1e-9, "cote: text 1.5 mm pe hartie la 1:500 (DIMTXT 2.5)")
check(v["PDMODE"] == 33 and abs(v["PDSIZE"] - 0.5) < 1e-9, "PTYPE: cerculet de 0.5 m la 1:500")
check(["_.-SCALELISTEDIT", "_A", "1:1000", "1:1000", "_E"] in COMMANDS, COMMANDS)
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
check(P[(ps, "MarkerType")] == 0 and P[(ps, "MarkerSizeType")] == 2 and abs(P[(ps, "MarkerSize")] - 0.5) < 1e-12, "Basic: 0.5 m la 1:500")
check(P[(ps + ".MarkerDisplayStylePlan", "Color")] == 7, "punct alb")
lbl = "PointLabelStyles[Point Description]"
check(("PointLabelStyles", "ADD", ["Point Description"]) in CALLS, "stilul Point Description se creeaza")
tc = lbl + ".TextComponents[Point Description]"
check(P[(tc + ".Contents", "Value")] == "<[Full Description(CP)]>", "descrierea")
check(abs(P[(tc + ".Height", "Value")] - 0.00075) < 1e-12 and P[(tc + ".Color", "Value")] == 7, "0.75 m la 1:500 (adnotare 1:1000), alb")
check(P[(tc + ".AnchorPoint", "Value")] == 3 and P[(tc + ".Attachment", "Value")] == 3, "Middle left / Middle left")
check(abs(P[(tc + ".XOffset", "Value")] - 0.000375) < 1e-12, "gap = jumatate din text")
check(P[(lbl + ".DraggedLeaderStyle.Visibility", "Value")] == "VLAX-FALSE", "fara leader cand e mutata")
check(P[(lbl + ".DraggedComponentStyle.StackText", "Value")] == "VLAX-FALSE", "as composed")
check(P[(lbl + ".LabelProperties.TextStyle", "Value")] == "Standard", "stilul de text (Arial)")
check(P[("Doc.Settings.PointSettings.StyleSettings.Style", "Value")] == "Basic", "stilul punctelor noi")
check(P[("Doc.Settings.PointSettings.StyleSettings.LabelStyle", "Value")] == "Point Description", "eticheta noua")
check(P[("PointGroups[_All Points]", "PointLabelStyle")].path == lbl, "_All Points")
check(P[("Doc.Settings.DrawingSettings.ObjectLayerSettings.PointEntityLayer", "Layer")] == "Puncte", "strat puncte")
check(P[("Doc.Settings.DrawingSettings.ObjectLayerSettings.GeneralNoteLabelLayer", "Layer")] == "Caroiaj", "strat caroiaj")

# eticheta de segment Distance Only: metri, 2 zecimale, " m", 0.75 m la 1:500, Bottom center, pe Dimensiuni
seg = "LineStyles[Distance Only].TextComponents[Distance]"
check(P[(seg + ".Contents", "Value")] == "<[General Segment Length(Um|P2|RN|AP|GC|UN|Sn|OF)]> m", "Distance Only")
# "drag mode" oprit: la Distance Only si ca valoare implicita pentru stilurile noi din desen
check(P[("LineStyles[Distance Only].DraggedLeaderStyle.Visibility", "Value")] == "VLAX-FALSE", "Distance Only fara leader")
check(P[("LineStyles[Distance Only].DraggedComponentStyle.StackText", "Value")] == "VLAX-FALSE", "Distance Only as composed")
dd = "Doc.Settings.DrawingSettings.LabelStyleDefaults"
check(P[(dd + ".DraggedLeaderStyle.Visibility", "Value")] == "VLAX-FALSE"
      and P[(dd + ".DraggedComponentStyle.StackText", "Value")] == "VLAX-FALSE", "implicit pentru stilurile noi")
check(abs(P[(seg + ".Height", "Value")] - 0.00075) < 1e-12 and P[(seg + ".Attachment", "Value")] == 7, "marime, Bottom center")
check(abs(P[(seg + ".YOffset", "Value")] - 0.000375) < 1e-12 and P[(seg + ".Color", "Value")] == 7, "gap, alb")
check(P[("Doc.Settings.DrawingSettings.ObjectLayerSettings.GeneralSegmentLabelLayer", "Layer")] == "Dimensiuni", "strat cote")
for k in ("AddSegmentLabelSettings", "AddSegmentLabelsSettings"):
    check(P[(f"Doc.Settings.GeneralCommandsSettings.{k}.StyleSettings.LineLabelStyle", "Value")] == "Distance Only", k)

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
    check(abs(P[(ho + ".Length", "Value")] - 0.0065) < 1e-12, k)
    check(P[(ho + ".UseEndPointAnchor", "Value")] == "VLAX-FALSE", f"{k}: linia are unghi si lungime proprii")
    # textele nu se suprapun in colt: incep la 1.5 x inaltimea din colt
    check(abs(abs(P[(n + ".XOffset", "Value")]) - 0.001125) < 1e-12 and abs(abs(P[(e + ".YOffset", "Value")]) - 0.001125) < 1e-12, k)
    check(P[(st + ".LabelProperties.PlanReadable", "Value")] == "VLAX-FALSE", k)
check(abs(P[("NoteStyles[Caroiaj - cruciulita].LineComponents[Brat sud].Angle", "Value")] - 1.5 * math.pi) < 1e-12, "cruce")
# textul implicit "Note" al stilurilor noi se ascunde (doar coordonatele si liniile)
for k in ("colt stanga sus", "colt dreapta jos"):
    st = cdoc.get("GeneralNoteLabelStyles")
    sty = next(x for x in st.items if x.props.get("NAME") == f"Caroiaj - {k}")
    note = sty.get("TextComponents").invoke("ADD", ["Text"])     # componenta implicita "Note"
fn("TKP:GridStyles", cdoc, 500)
for k in ("colt stanga sus", "colt dreapta jos"):
    check(P[(f"NoteStyles[Caroiaj - {k}].TextComponents[Text].Visibility", "Value")] == "VLAX-FALSE", f"{k}: Note ascuns")
    check(P[(f"NoteStyles[Caroiaj - {k}].TextComponents[Nord].Visibility", "Value")] == "VLAX-TRUE", k)
check("Civil 3D: stilurile de caroiaj (General Note Label) sunt gata" in out, out[-900:])

# ---------------------------------------------------------------- caroiajul (Civil 3D: General Note Label)
# ca in desenul utilizatorului: stratul Caroiaj e inghetat si oprit, stratul curent e Puncte
d = acad.tables["LAYER"]["CAROIAJ"]
acad.tables["LAYER"]["CAROIAJ"] = [x for x in d if not (isinstance(x, DP) and x.car in (62, 70))] + [DP(70, 1), DP(62, -8)]
acad.vars["CLAYER"] = "Puncte"
acad.out.clear()
COMMANDS.clear()
acad.inputs += [("real", None), ("pt", [545010.0, 458010.0, 0.0]), ("pt", [545090.0, 458070.0, 0.0]), ("kw", None),
                ("kw", None)]                         # cruciulite: Da; coordonate: implicit (Directie)
fn("c:TKCAROIAJ")
notes = [c for c in COMMANDS if c and c[0] == "_.AeccAddNoteLabel"]
check(len(notes) == 6, COMMANDS)                     # 4 colturi + cruciulita de jos (E sus) + cea de sus (E jos)
pts = [c[1] for c in COMMANDS if len(c) == 2 and c[0] == "_non"]
corners = pts[:4]
check(corners == [[545025.0, 458025.0, 0.0], [545075.0, 458025.0, 0.0], [545025.0, 458050.0, 0.0],
                  [545075.0, 458050.0, 0.0]], corners)
check(len(pts) == 4 + 2, pts)                        # noduri 3 x 2: interiorul are 2 cruciulite
# cele 2 cruciulite sunt pe marginile de jos si de sus: arata E= (coordonata care se schimba pe margine)
check(sorted(v for k, v in STYLE_LOG[4:]) == ["Caroiaj - cruciulita E", "Caroiaj - cruciulita E jos"], STYLE_LOG)
check(fn("TKP:Get", "CRUCECOORD") == "Directie", "setarea se pastreaza")
# stratul curent al utilizatorului nu se schimba; Caroiaj e dezghetat si pornit; etichetele trec pe Caroiaj
check(acad.vars["CLAYER"] == "Puncte", acad.vars["CLAYER"])
d = acad.tables["LAYER"]["CAROIAJ"]
check((grp(d, 70) or 0) & 1 == 0 and grp(d, 62) == 8, d)
check(any("Stratul Caroiaj era inghetat sau oprit" in o for o in acad.out), acad.out[-6:])
labels = ents("AECC_GENERAL_NOTE_LABEL")
check(len(labels) == 6 and all(grp(acad.db[e], 8) == "Caroiaj" for e in labels), [grp(acad.db[e], 8) for e in labels])

# stilurile cruciulitelor cu coordonate: N= orizontal, E= vertical, ca la coltul din stanga jos
cx = "NoteStyles[Caroiaj - cruciulita N E]"
check(P[(cx + ".TextComponents[Nord].Contents", "Value")] == "N=<[Northing(Um|P0|RN|AP|GC|UN|Sn|OF)]>", "N E")
check(abs(P[(cx + ".TextComponents[Est].Angle", "Value")] - math.pi / 2) < 1e-12, "E vertical")
check(P[(cx + ".TextComponents[Nord].Attachment", "Value")] == 6 and P[(cx + ".TextComponents[Est].Attachment", "Value")] == 0, "atasare")
check(("NoteStyles[Caroiaj - cruciulita N].TextComponents[Est].Contents", "Value") not in P, "stilul N nu are E=")
check(P[("NoteStyles[Caroiaj - cruciulita E].TextComponents[Est].Visibility", "Value")] == "VLAX-TRUE", "stilul E")
# design ca la colturi (scara 1:500): bratul cu text = linia L (6.5 mm), celelalte brate scurte (1.25 mm)
def arm(style, a): return P[(f"NoteStyles[{style}].LineComponents[Brat {a}].Length", "Value")]
for style, longs in (("Caroiaj - cruciulita E", {"nord"}), ("Caroiaj - cruciulita E jos", {"sud"}),
                     ("Caroiaj - cruciulita N", {"est"}), ("Caroiaj - cruciulita N stanga", {"vest"}),
                     ("Caroiaj - cruciulita N E", {"est", "nord"}), ("Caroiaj - cruciulita N E stanga jos", {"vest", "sud"}),
                     ("Caroiaj - cruciulita", set())):
    for a in ("est", "vest", "nord", "sud"):
        check(abs(arm(style, a) - (0.0065 if a in longs else 0.00125)) < 1e-12, (style, a, arm(style, a)))
# textul pe bratul lung, spre interior (atasare ca la colturi)
ej = "NoteStyles[Caroiaj - cruciulita E jos].TextComponents[Est]"
check(P[(ej + ".Attachment", "Value")] == 2 and P[(ej + ".YOffset", "Value")] < 0, "E jos: text pe bratul de jos")
ns = "NoteStyles[Caroiaj - cruciulita N stanga].TextComponents[Nord]"
check(P[(ns + ".Attachment", "Value")] == 8 and P[(ns + ".XOffset", "Value")] < 0, "N stanga: text pe bratul din stanga")
nesj = "NoteStyles[Caroiaj - cruciulita N E stanga jos].TextComponents"
check(P[(nesj + "[Nord].Attachment", "Value")] == 2 and P[(nesj + "[Est].Attachment", "Value")] == 8, "N E stanga jos = colt SD")

# Directie pe o retea 5 x 5: sus/jos E=, stanga/dreapta N=, interiorul simplu
def note_groups():
    """(stil, puncte) pentru fiecare AeccAddNoteLabel, in ordine"""
    out, style_seq = [], [v for (k, v) in STYLE_LOG]
    i = 0
    for c in COMMANDS:
        if c and c[0] == "_.AeccAddNoteLabel":
            out.append([style_seq[i], []]); i += 1
        elif len(c) == 2 and c[0] == "_non" and out:
            out[-1][1].append(tuple(c[1][:2]))
    return out
COMMANDS.clear(); STYLE_LOG.clear()
acad.inputs += [("real", None), ("pt", [545000.0, 458000.0, 0.0]), ("pt", [545100.0, 458100.0, 0.0]), ("kw", None), ("kw", "Directie")]
fn("c:TKCAROIAJ")
g = {st: pts for st, pts in note_groups()}
check(sorted(g) == ["Caroiaj - colt dreapta jos", "Caroiaj - colt dreapta sus", "Caroiaj - colt stanga jos",
                    "Caroiaj - colt stanga sus", "Caroiaj - cruciulita", "Caroiaj - cruciulita E", "Caroiaj - cruciulita E jos",
                    "Caroiaj - cruciulita N", "Caroiaj - cruciulita N stanga"], sorted(g))
# textele spre interior: jos E= in sus, sus E= in jos, stanga N= spre dreapta, dreapta N= spre stanga
check(sorted(g["Caroiaj - cruciulita E"]) == [(x, 458000.0) for x in (545025.0, 545050.0, 545075.0)], "E= jos")
check(sorted(g["Caroiaj - cruciulita E jos"]) == [(x, 458100.0) for x in (545025.0, 545050.0, 545075.0)], "E= sus")
check(sorted(g["Caroiaj - cruciulita N"]) == [(545000.0, y) for y in (458025.0, 458050.0, 458075.0)], "N= stanga")
check(sorted(g["Caroiaj - cruciulita N stanga"]) == [(545100.0, y) for y in (458025.0, 458050.0, 458075.0)], "N= dreapta")
check(len(g["Caroiaj - cruciulita"]) == 9, "interiorul fara coordonate")
# Ambele: toate cruciulitele cu N= si E=
COMMANDS.clear(); STYLE_LOG.clear()
acad.inputs += [("real", None), ("pt", [545000.0, 458000.0, 0.0]), ("pt", [545100.0, 458100.0, 0.0]), ("kw", None), ("kw", "Ambele")]
fn("c:TKCAROIAJ")
g = {st: pts for st, pts in note_groups()}
check(sum(len(v) for k, v in g.items() if k.startswith("Caroiaj - cruciulita N E")) == 21 and "Caroiaj - cruciulita" not in g, "Ambele")
# colturile interioare ale marginilor: sus-dreapta nu exista (e colt); randul de sus -> "jos", coloana din dreapta -> "stanga"
check(sorted(g["Caroiaj - cruciulita N E jos"]) == [(x, 458100.0) for x in (545025.0, 545050.0, 545075.0)], "Ambele: randul de sus")
check(sorted(g["Caroiaj - cruciulita N E stanga"]) == [(545100.0, y) for y in (458025.0, 458050.0, 458075.0)], "Ambele: coloana din dreapta")
check(len(g["Caroiaj - cruciulita N E"]) == 15, "Ambele: restul spre dreapta-sus")
check(fn("TKP:Get", "CRUCECOORD") == "Ambele", "setarea noua se pastreaza")

# ---------------------------------------------------------------- TKSCARA: textele se redimensioneaza
acad.add_text([545030.0, 458030.0], "Ion Popescu", 0.75, "Vecinătăți")
acad.add_text([545030.0, 458040.0], "alt strat", 2.0, "Proprietari")
acad.inputs += [("str", "1:1000")]
fn("c:TKSCARA")
txt = {grp(acad.db[e], 1): grp(acad.db[e], 40) for e in ents("TEXT")}
check(abs(txt["Ion Popescu"] - 1.5) < 1e-9 and txt["alt strat"] == 2.0, txt)
check(acad.vars["CANNOSCALE"] == "1:1000" and abs(acad.vars["LTSCALE"] - 2.0) < 1e-9 and abs(acad.vars["PDSIZE"] - 1.0) < 1e-9, "1:1000")
# stilurile Civil 3D ale TopoKit au marimile noi (adnotarea ramane 1:1000)
check(abs(P[(tc + ".Height", "Value")] - 0.0015) < 1e-12 and abs(P[(ps, "MarkerSize")] - 1.0) < 1e-12, "1:1000: text 1.5 m, punct 1 m")
check(abs(P[("NoteStyles[Caroiaj - colt stanga jos].TextComponents[Nord].Height", "Value")] - 0.0015) < 1e-12, "caroiaj 1:1000")
check(abs(P[("LineStyles[Distance Only].TextComponents[Distance].Height", "Value")] - 0.0015) < 1e-12, "cote 1:1000")
check(abs(P[("NoteStyles[Caroiaj - cruciulita].LineComponents[Brat est].Length", "Value")] - 0.0025) < 1e-12, "cruciulita 1:1000")
check(fn("TKP:Scara") == 1000 and fn("TKC:Cfg", "SCARA") == 1000.0, "scara noua salvata")
acad.inputs += [("str", "300")]
fn("c:TKSCARA")
check(fn("TKP:Scara") == 1000 and "Scara trebuie sa fie una din standard" in "".join(acad.out[-3:]), "scara gresita")

# ---------------------------------------------------------------- caroiajul fara Civil 3D (linii si texte)
civil[0] = False
env[Sym("*TKP:C3DAPP*")] = None                     # legatura Civil 3D se cauta din nou (AutoCAD simplu)
acad.inputs += [("real", 30.0), ("pt", [545000.0, 458000.0, 0.0]), ("pt", [545210.0, 458160.0, 0.0]), ("kw", "Nu")]
n_txt0 = len(ents("TEXT", "Caroiaj"))
n0 = len(ents("LINE", "Caroiaj"))
fn("c:TKCAROIAJ")
lines = ents("LINE", "Caroiaj")[n0:]
check(len(lines) == 8, len(lines))                  # 4 colturi x 2 linii, fara cruciulite
texts = {grp(acad.db[e], 1): acad.db[e] for e in ents("TEXT", "Caroiaj")}
check(set(texts) == {"N=458010", "N=458160", "E=545010", "E=545190"}, set(texts))   # cruciulite la 30 m (scris)
for e in ents("TEXT", "Caroiaj"):
    d = acad.db[e]
    check(abs(grp(d, 40) - 1.5) < 1e-9, "text 1.5 m la 1:1000")
    if grp(d, 1).startswith("E="):
        check(abs(grp(d, 50) - math.pi / 2) < 1e-12, "E= vertical")
# coltul stanga jos: linia orizontala spre est, cea verticala spre nord, de 13 m (13 mm la 1:1000)
L = [(grp(acad.db[e], 10), grp(acad.db[e], 11)) for e in lines[:2]]
check(L == [([545010.0, 458010.0, 0.0], [545023.0, 458010.0, 0.0]), ([545010.0, 458010.0, 0.0], [545010.0, 458023.0, 0.0])], L)

# cruciulitele fara Civil 3D, Directie: pe randul de sus E= pe bratul de jos (lung, 13 m), spre interior
for e in ents("LINE", "Caroiaj") + ents("TEXT", "Caroiaj"):
    acad.deleted.add(e)
acad.inputs += [("real", 50.0), ("pt", [545000.0, 458000.0, 0.0]), ("pt", [545100.0, 458100.0, 0.0]), ("kw", None), ("kw", "Directie")]
fn("c:TKCAROIAJ")
segs = {(tuple(grp(acad.db[e], 10)[:2]), tuple(grp(acad.db[e], 11)[:2])) for e in ents("LINE", "Caroiaj")}
# cruciulita (545050, 458100) de pe randul de sus: brat vertical de la 458087 (13 m in jos) la 458102.5 (2.5 m sus)
check(((545050.0, 458087.0), (545050.0, 458102.5)) in segs, sorted(s for s in segs if s[0][0] == 545050.0))
# cruciulita (545100, 458050) de pe coloana din dreapta: brat orizontal lung spre vest
check(((545087.0, 458050.0), (545102.5, 458050.0)) in segs, sorted(s for s in segs if s[0][1] == 458050.0))
tx = [acad.db[e] for e in ents("TEXT", "Caroiaj")]
e_sus = [d for d in tx if grp(d, 1) == "E=545050" and grp(d, 11)[1] > 458050.0]      # randul de sus
e_jos = [d for d in tx if grp(d, 1) == "E=545050" and grp(d, 11)[1] < 458050.0]      # randul de jos
n_dr = [d for d in tx if grp(d, 1) == "N=458050" and grp(d, 11)[0] > 545050.0]       # coloana din dreapta
check(len(e_sus) == len(e_jos) == len(n_dr) == 1, [grp(d, 1) for d in tx])
check(grp(e_sus[0], 11)[1] < 458100.0 and grp(n_dr[0], 11)[0] < 545100.0, "textele spre interior")
check((grp(e_sus[0], 72), grp(e_sus[0], 73)) == (2, 3), "sus: E= TR, ca la coltul stanga sus")
check((grp(e_jos[0], 72), grp(e_jos[0], 73)) == (0, 3) and grp(e_jos[0], 11)[1] > 458000.0, "jos: E= TL, in sus")

# ---------------------------------------------------------------- TKLEGENDA: legenda automata din straturi cu polilinii
for e in list(acad.order):
    acad.deleted.add(e)
DESC = {"GARD LEMN": "Gard de lemn"}
def layer_item(coll, name):
    if getattr(coll, "kind", None) == "layers":
        if name.upper() not in acad.tables["LAYER"]: raise KeyError(name)
        return Obj("layer", name=grp(acad.tables["LAYER"][name.upper()], 2))
    return _vla_item(coll, name)
_vla_item = M.funcs[Sym("VLA-ITEM")]
M.funcs[Sym("VLA-ITEM")] = layer_item
M.funcs[Sym("VLA-GET-DESCRIPTION")] = lambda o: DESC.get(o.name.upper(), "")
M.funcs[Sym("VLA-PUT-DESCRIPTION")] = lambda o, v: DESC.__setitem__(o.name.upper(), v)
def textbox(d):
    t, h = grp(d, 1), grp(d, 40)
    return [[0.0, 0.0, 0.0], [0.6 * h * len(t), h, 0.0]]
M.funcs[Sym("TEXTBOX")] = textbox
for name, col, flags in (("terenuri", 6, 0), ("Gard lemn", 3, 0), ("Drum", 250, 0), ("Oprit", -2, 0),
                         ("Inghetat", 4, 1), ("Plan|xref", 7, 0)):
    acad.entmake([DP(0, "LAYER"), DP(2, name), DP(70, flags), DP(62, col)])
def pl(layer, extra=()):
    acad.entmake([DP(0, "LWPOLYLINE"), DP(100, "AcDbEntity"), DP(410, "Model"), DP(8, layer)] + list(extra) +
                 [DP(100, "AcDbPolyline"), DP(90, 2), DP(70, 0), [10, 0.0, 0.0], [10, 50.0, 0.0]])
pl("terenuri", [DP(48, 0.5)]); pl("terenuri")
acad.db[acad.order[-2]] = [x for x in acad.db[acad.order[-2]]] + [DP(43, 0.4)]     # latime globala pe prima
pl("Gard lemn", [DP(6, "GARDLEMN"), DP(62, 3)]); pl("Drum")
for lay in ("Oprit", "Inghetat", "Plan|xref", "LEGENDA", "Caroiaj"):
    pl(lay)
# dialogul: randurile sunt Drum, Gard de lemn (din descriere), Terenuri; Terenuri -> "Limita PUZ", Drum scos
acad.dcl.scripts["tkp_legenda"] = [[("pick", "lst", "2"), ("pick", "txt", "Limita PUZ"), ("pick", "lst", "0"),
                                    ("click", "inc"), ("click", "accept")]]
acad.inputs += [("pt", [1000.0, 2000.0, 0.0])]
n0 = len(acad.order)
fn("c:TKLEGENDA")
snap = acad.dcl.snapshots["tkp_legenda"]["lists"]["lst"]
check([r.split("(")[-1].rstrip(")") for r in snap] == ["Drum", "Gard lemn", "terenuri"], snap)   # fara oprit/inghetat/xref/LEGENDA/Caroiaj
check(snap[0].startswith("[ ] Drum") and snap[2].startswith("[x] Limita PUZ"), snap)
new_e = [e for e in acad.order[n0:] if e not in acad.deleted]
leg = [acad.db[e] for e in new_e]
texts = [(grp(d, 1), grp(d, 11), grp(d, 40), grp(d, 72), grp(d, 73)) for d in leg if grp(d, 0) == "TEXT"]
k = fn("TKP:K", fn("TKP:Scara"))
check(texts[0][0] == "Legend\u0103:" and abs(texts[0][2] - 3.0 * k) < 1e-9 and (texts[0][3], texts[0][4]) == (1, 2), texts[0])
check([t[0] for t in texts[1:]] == ["Gard de lemn:", "Limita PUZ:"], texts)
check(abs(texts[1][1][0] - (1000 + 2.015 * k)) < 1e-9 and abs(texts[1][1][1] - (2000 - 15.154 * k)) < 1e-9, texts[1])
check(abs(texts[2][1][1] - (2000 - (15.154 + 3.755) * k)) < 1e-9 and abs(texts[1][2] - 2.0 * k) < 1e-9, texts[2])
frame = [d for d in leg if grp(d, 0) == "LWPOLYLINE" and grp(d, 8) == "LEGENDA"]
check(len(frame) == 1 and grp(frame[0], 70) == 1 and len(grps(frame[0], 10)) == 4, frame)
ys = [v[1] for v in grps(frame[0], 10)]
check(abs((max(ys) - min(ys)) - (15.154 + 3.755 + 1.378 + 5.489) * k) < 1e-9, ys)
under = [d for d in leg if grp(d, 0) == "LINE" and grp(d, 8) == "LEGENDA"]
check(len(under) == 1 and abs(grp(under[0], 10)[1] - (2000 - (5.654 + 1.94) * k)) < 1e-9, under)
samples = {grp(d, 8): d for d in leg if grp(d, 0) == "LWPOLYLINE" and grp(d, 8) != "LEGENDA"}
check(set(samples) == {"Gard lemn", "terenuri"}, set(samples))
g = samples["Gard lemn"]
check(grp(g, 6) == "GARDLEMN" and grp(g, 62) == 3, g)                       # tipul si culoarea polilinii
t = samples["terenuri"]
check(abs(grp(t, 43) - 0.4) < 1e-12 and abs(grp(t, 48) - 0.5) < 1e-12, t)  # latimea globala si scara liniei
v = grps(t, 10)
check(abs((v[1][0] - v[0][0]) - 27.822 * k) < 1e-9 and abs(v[0][1] - (2000 - (15.154 + 3.755 + 1.378) * k)) < 1e-9, v)
check(DESC.get("TERENURI") == "Limita PUZ" and DESC.get("GARD LEMN") == "Gard de lemn", DESC)   # textele raman in descrieri
check(any("Legenda cu 2 randuri" in o for o in acad.out), acad.out[-3:])

print("Toate testele TopoKitProiect au trecut.")
