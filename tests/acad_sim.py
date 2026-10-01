"""Simulator AutoCAD minimal pentru testarea offline a TopoKitAnexe.lsp.

Peste interpretorul din autolisp_mini.py simuleaza: baza de date de entitati
(entmake/entget/handent/ssget), tabelele LAYER/STYLE, layout-urile si
viewport-urile (MVIEW/MSPACE/PLAN/ZOOM), functiile vlax-curve, ldata,
variabilele de sistem si de mediu, fisierele si dialogurile DCL (fisierul .dcl
este analizat sintactic; cheile folosite de program trebuie sa existe in el).
Intrarile utilizatorului (entsel, ssget, getstring...) si actiunile din
dialoguri se dau prin scenarii.
"""
import math, os, re, json, subprocess
from autolisp_mini import *   # noqa: F401,F403
import autolisp_mini as M


class Ent:
    __slots__ = ("i",)
    def __init__(s, i): s.i = i
    def __eq__(s, o): return isinstance(o, Ent) and o.i == s.i
    def __hash__(s): return hash(("E", s.i))
    def __repr__(s): return f"<Entity {s.i:X}>"


class Obj:
    """Obiect ActiveX simulat (document, colectia de layout-uri, layout, viewport)."""
    def __init__(s, kind, **kw): s.kind = kind; s.props = {}; s.__dict__.update(kw)
    def __repr__(s): return f"<VLA {s.kind} {getattr(s, 'name', '')}>"


def grp(d, code):
    """Valoarea grupului DXF CODE dintr-o lista de entitate (sau None)."""
    for x in d or []:
        if isinstance(x, DP) and x.car == code: return x.cdr
        if isinstance(x, list) and x and x[0] == code: return x[1:]
    return None


def grps(d, code):
    return [x.cdr if isinstance(x, DP) else x[1:] for x in d or []
            if (isinstance(x, DP) and x.car == code) or (isinstance(x, list) and x and x[0] == code)]


# ---------------------------------------------------------------- DCL
KNOWN_TILES = {"dialog", "row", "column", "boxed_row", "boxed_column", "radio_row", "radio_column",
               "boxed_radio_row", "boxed_radio_column", "button", "edit_box", "list_box", "popup_list",
               "toggle", "radio_button", "text", "image", "image_button", "slider", "spacer", "spacer_0",
               "spacer_1", "concatenation", "paragraph", "text_part", "errtile", "ok_cancel", "ok_only",
               "ok_cancel_help", "ok_cancel_help_errtile", "default_button", "retirement_button"}
KNOWN_ATTRS = {"label", "key", "width", "height", "fixed_width", "fixed_height", "alignment", "edit_width",
               "edit_limit", "mnemonic", "is_default", "is_cancel", "multiple_select", "tabs", "value",
               "children_alignment", "children_fixed_width", "children_fixed_height", "color", "aspect_ratio",
               "list", "allow_accept", "is_enabled", "is_tab_stop", "initial_focus", "fixed_width_font",
               "action", "layout", "big_increment", "small_increment", "max_value", "min_value", "password_char",
               "tab_truncate", "is_bold"}
STD_REFS = {"ok_cancel": ["accept", "cancel"], "ok_only": ["accept"], "errtile": ["error"],
            "ok_cancel_help": ["accept", "cancel", "help"], "ok_cancel_help_errtile": ["accept", "cancel", "help", "error"],
            "spacer": [], "spacer_0": [], "spacer_1": []}


def parse_dcl(text):
    """Analiza sintactica stricta a unui fisier DCL -> {nume: (tip, corp)}."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    tok_re = r'"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z0-9_]*|-?\d+(?:\.\d+)?|[{}:;=]'
    rest = re.sub(tok_re + r"|\s", "", text)
    assert rest == "", f"caractere nepermise in DCL: {rest[:40]!r}"
    toks = re.findall(tok_re, text)
    pos = [0]

    def expect(t):
        assert toks[pos[0]] == t, f"DCL: asteptam {t!r}, am gasit {toks[pos[0]]!r} ({' '.join(toks[max(0, pos[0]-6):pos[0]+3])})"
        pos[0] += 1

    def body():
        items = []
        while toks[pos[0]] != "}":
            t = toks[pos[0]]
            if t == ":":
                pos[0] += 1; typ = toks[pos[0]]; pos[0] += 1
                expect("{"); b = body(); expect("}")
                items.append(("tile", typ, b))
            elif re.match(r"[A-Za-z_]", t) and toks[pos[0] + 1] == "=":
                val = toks[pos[0] + 2]; pos[0] += 3; expect(";")
                items.append(("attr", t, val))
            elif re.match(r"[A-Za-z_]", t) and toks[pos[0] + 1] == ";":
                items.append(("ref", t)); pos[0] += 2
            else:
                raise SyntaxError(f"DCL: element neasteptat {t!r}")
        return items

    defs = {}
    while pos[0] < len(toks):
        name = toks[pos[0]]; pos[0] += 1
        expect(":"); typ = toks[pos[0]]; pos[0] += 1
        expect("{"); b = body(); expect("}")
        defs[name] = (typ, b)
    return defs


def dcl_dialogs(defs):
    """Pentru fiecare dialog: {cheie: (tip, atribute)}; verifica tipurile si atributele."""
    def check_attrs(items, where, dialog=False):
        for it in items:
            if it[0] == "attr":
                assert it[1] in KNOWN_ATTRS, f"{where}: atribut DCL necunoscut {it[1]}"
                if it[1] in ("label", "key", "tabs", "value", "mnemonic"):
                    assert it[2].startswith('"'), f"{where}: {it[1]} trebuie sa fie text"
                    assert all(ord(c) < 128 for c in it[2]), f"{where}: text non-ASCII in DCL: {it[2]}"
                    # '&' in etichetele tile-urilor marcheaza tasta de acces (titlul dialogului e liber)
                    assert dialog or "&" not in it[2], f"{where}: '&' in eticheta DCL"
                if it[1] in ("width", "height", "edit_width", "edit_limit"):
                    float(it[2])

    def walk(items, out, where, proto_attrs=None):
        for it in items:
            if it[0] == "tile":
                typ = it[1]
                attrs = {}
                base = typ
                while base not in KNOWN_TILES:
                    assert base in defs, f"{where}: tip DCL necunoscut {base}"
                    for a in defs[base][1]:
                        if a[0] == "attr": attrs.setdefault(a[1], a[2])
                    base = defs[base][0]
                for a in it[2]:
                    if a[0] == "attr": attrs[a[1]] = a[2]
                check_attrs(it[2], where)
                if "key" in attrs:
                    k = attrs["key"].strip('"')
                    assert k not in out, f"{where}: cheie DCL duplicata {k}"
                    out[k] = (base, {a: v.strip('"') for a, v in attrs.items()})
                walk(it[2], out, where)
            elif it[0] == "ref":
                assert it[1] in STD_REFS or it[1] in defs, f"{where}: referinta DCL necunoscuta {it[1]}"
                for k in STD_REFS.get(it[1], []):
                    out[k] = ("button" if k != "error" else "errtile", {})
        return out

    res = {}
    for name, (typ, body) in defs.items():
        if typ == "dialog":
            check_attrs(body, name, dialog=True)
            res[name] = walk(body, {}, name)
    return res


def check_dcl_text(v):
    """Textele afisate in dialoguri: fara coduri \\U+XXXX si fara marcaje de diacritice."""
    assert "\\U+" not in v and not re.search(r"[`^][aAiIsStT]", v), f"text DCL nerezolvat: {v!r}"


class Dcl:
    """Dialogurile DCL simulate: valorile tile-urilor, listele, actiunile si scenariile."""
    def __init__(s, acad): s.acad = acad; s.scripts = {}; s.log = []; s.stack = []; s.files = {}; s.snapshots = {}

    def load_dialog(s, path):
        p = s.acad.path(path)
        if not os.path.exists(p): return -1
        s.files[len(s.files) + 1] = dcl_dialogs(parse_dcl(open(p, encoding="utf-8").read()))
        return len(s.files)

    def unload_dialog(s, i): return None

    def new_dialog(s, name, i, *a):
        d = s.files[i]
        if name not in d: return None
        s.stack.append({"name": name, "keys": d[name], "tiles": {}, "actions": {}, "lists": {},
                        "cur": None, "done": None})
        for k, (typ, attrs) in d[name].items():
            s.stack[-1]["tiles"][k] = attrs.get("value", "0" if typ in ("toggle", "popup_list") else "")
        return T

    @property
    def cur(s): return s.stack[-1]

    def _key(s, k):
        assert isinstance(k, str), k
        assert k in s.cur["keys"], f"dialogul {s.cur['name']}: cheia {k!r} nu exista in DCL"

    def set_tile(s, k, v):
        s._key(k); assert isinstance(v, str), f"set_tile {k}: valoarea nu este text: {v!r}"
        check_dcl_text(v)
        s.cur["tiles"][k] = v; return v

    def get_tile(s, k): s._key(k); return s.cur["tiles"][k]

    def action_tile(s, k, a):
        s._key(k); assert isinstance(a, str), f"action_tile {k}: actiunea nu este text"
        parse(tokenize(a))                       # actiunea trebuie sa fie cod AutoLISP valid
        s.cur["actions"][k] = a; return T

    def mode_tile(s, k, m): s._key(k); return None

    def start_list(s, k, op=3, idx=None):
        s._key(k); assert s.cur["keys"][k][0] in ("list_box", "popup_list"), k
        s.cur["cur"] = k
        if op == 3: s.cur["lists"][k] = []
        return k

    def add_list(s, v):
        assert isinstance(v, str), v
        check_dcl_text(v)
        s.cur["lists"][s.cur["cur"]].append(v); return v

    def end_list(s): s.cur["cur"] = None; return None

    def done_dialog(s, n=1): s.cur["done"] = n; return [0, 0]

    # imaginile din dialoguri (desenate cu vector_image / fill_image)
    def dim_tile(s, k, i):
        s._key(k); a = s.cur["keys"][k][1]
        return int(float(a.get("width" if i == 0 else "height", "10")) * (7 if i == 0 else 15))
    def start_image(s, k):
        s._key(k); assert s.cur["keys"][k][0] in ("image", "image_button")
        s.cur["img"] = k; s.cur.setdefault("images", {})[k] = []; return k
    def vector_image(s, *a):
        assert len(a) == 5 and all(isinstance(x, int) for x in a), a
        s.cur["images"][s.cur["img"]].append(("v",) + a); return a[-1]
    def fill_image(s, *a):
        assert len(a) == 5 and all(isinstance(x, int) for x in a), a
        s.cur["images"][s.cur["img"]].append(("f",) + a); return a[-1]
    def end_image(s): s.cur["img"] = None; return None

    def fire(s, k):
        a = s.cur["actions"].get(k)
        if a is None:
            if k == "accept": s.cur["done"] = 1
            elif k == "cancel": s.cur["done"] = 0
            return
        env[Sym("$KEY")] = k; env[Sym("$VALUE")] = s.cur["tiles"].get(k, "")
        for f in parse(tokenize(a)): ev(f)

    def start_dialog(s):
        name = s.cur["name"]
        script = s.scripts.get(name)
        events = script.pop(0) if script else []
        s.log.append(name)
        for e in events:
            if s.cur["done"] is not None: break
            if callable(e): e(s); continue
            if e[0] == "set": s._key(e[1]); s.cur["tiles"][e[1]] = e[2]
            elif e[0] == "pick": s._key(e[1]); s.cur["tiles"][e[1]] = e[2]; s.fire(e[1])
            elif e[0] == "click": s._key(e[1]); s.fire(e[1])
        s.snapshots[name] = {"tiles": dict(s.cur["tiles"]), "lists": {k: list(v) for k, v in s.cur["lists"].items()},
                             "images": dict(s.cur.get("images", {}))}
        if s.cur["done"] is None: s.fire("accept")
        if s.cur["done"] is None: s.fire("cancel")
        res = s.cur["done"]; s.last = s.stack.pop()
        return res


# ---------------------------------------------------------------- AutoCAD
class Acad:
    def __init__(s, root, outdir, verbose=False):
        s.root, s.outdir, s.verbose = root, outdir, verbose
        s.db, s.order, s.deleted, s.handles = {}, [], set(), {}
        s.tables = {"LAYER": {"0": [DP(0, "LAYER"), DP(2, "0"), DP(70, 0), DP(62, 7)]}, "STYLE": {}}
        s.vars = {"CTAB": "Model", "LISPSYS": 1, "SYSCODEPAGE": "ANSI_1250", "CDATE": 20261001.101530,
                  "DWGTITLED": 1, "DWGPREFIX": outdir.rstrip("/") + "/", "DWGNAME": "test.dwg", "ERRNO": 0,
                  "CVPORT": 2, "CMDECHO": 1, "OSMODE": 0, "ATTREQ": 1, "DIMZIN": 8, "TILEMODE": 1}
        s.envs, s.ldata, s.inputs, s.out, s.alerts, s.cmds, s.runs = {}, {}, [], [], [], [], []
        s.layouts = {"MODEL": Obj("layout", name="Model", vp_init=True),
                     "LAYOUT1": Obj("layout", name="Layout1", vp_init=False)}
        s.vpid = 1
        s.dcl = Dcl(s)
        s.doc = Obj("document"); s.app = Obj("application")
        s.install()

    # ------------------------------------------------------------ utilitare
    def path(s, p):
        p = p.replace("\\", "/")
        return p if os.path.isabs(p) else os.path.join(s.root, p)

    def new(s, dxf):
        e = Ent(len(s.order) + 0x100); s.order.append(e)
        h = f"{e.i:X}"; s.handles[h] = e
        s.db[e] = list(dxf)
        return e

    def ed(s, e): return s.db[e]

    def space(s, e):
        d = s.db[e]
        return grp(d, 410) or ("Model" if not grp(d, 67) else s.vars["CTAB"])

    def add_lw(s, pts, closed=True, layer="0"):
        d = [DP(0, "LWPOLYLINE"), DP(100, "AcDbEntity"), DP(410, "Model"), DP(8, layer),
             DP(100, "AcDbPolyline"), DP(90, len(pts)), DP(70, 1 if closed else 0)]
        for p in pts: d.append([10, float(p[0]), float(p[1])])
        return s.new(d)

    def add_text(s, p, txt, h=1.0, layer="0", rot=0.0):
        return s.new([DP(0, "TEXT"), DP(410, "Model"), DP(8, layer), [10, float(p[0]), float(p[1]), 0.0],
                      DP(40, h), DP(1, txt), DP(50, rot), DP(72, 0), DP(73, 0)])

    def entities(s, layout=None, typ=None):
        out = []
        for e in s.order:
            if e in s.deleted: continue
            d = s.db[e]
            if typ and grp(d, 0) not in typ.split(","): continue
            if layout and s.space(e).upper() != layout.upper(): continue
            out.append(e)
        return out

    def verts(s, e):
        return [(p[0], p[1]) for p in grps(s.db[e], 10)]

    # ------------------------------------------------------------ entitati
    def entget(s, e, apps=None):
        if e is None or e in s.deleted or e not in s.db: return None
        d = s.db[e]
        h = next(k for k, v in s.handles.items() if v == e)
        return [DP(-1, e), d[0], DP(5, h)] + d[1:]

    def entmake(s, d=None):
        if d is None: return None
        d = list(d)
        typ = grp(d, 0)
        assert typ, f"entmake fara grupul 0: {d}"
        if typ in ("LAYER", "STYLE"):
            name = grp(d, 2); assert name and grp(d, 70) is not None, d
            if typ == "STYLE": assert grp(d, 3), "stil fara fisier de font"
            s.tables[typ][name.upper()] = d
            return d
        layer = grp(d, 8)
        assert layer, f"{typ} fara strat"
        if layer.upper() not in s.tables["LAYER"]: s.tables["LAYER"][layer.upper()] = [DP(0, "LAYER"), DP(2, layer), DP(62, 7)]
        # ordinea subclaselor: grupurile AcDbEntity (8, 67, 410, 62) dupa (100 . "AcDbEntity")
        markers = [i for i, x in enumerate(d) if isinstance(x, DP) and x.car == 100]
        if markers:
            ient = next((i for i in markers if d[i].cdr == "AcDbEntity"), None)
            assert ient is not None, f"{typ}: lipseste (100 . AcDbEntity)"
            nxt = [i for i in markers if i > ient]
            lim = nxt[0] if nxt else len(d)
            for i, x in enumerate(d):
                if isinstance(x, DP) and x.car in (8, 67, 410, 62):
                    assert ient < i < lim, f"{typ}: grupul {x.car} in afara subclasei AcDbEntity"
        if grp(d, 67) == 1:
            lay = grp(d, 410)
            assert lay and lay.upper() in s.layouts and lay.upper() != "MODEL", f"{typ}: layout inexistent {lay}"
        if typ == "TEXT":
            assert grp(d, 10) and grp(d, 40) and grp(d, 1) is not None, d
            assert isinstance(grp(d, 1), str)
            if grp(d, 72) or grp(d, 73): assert grp(d, 11), "TEXT justificat fara punctul 11"
            assert grp(d, 7) is None or grp(d, 7).upper() in s.tables["STYLE"], f"stil inexistent {grp(d, 7)}"
        elif typ == "MTEXT":
            assert [x.cdr for x in d if isinstance(x, DP) and x.car == 100] == ["AcDbEntity", "AcDbMText"], d
            assert grp(d, 10) and grp(d, 40) and grp(d, 1) is not None and 1 <= grp(d, 71) <= 9
            for x in grps(d, 3): assert len(x) == 250, "grupurile 3 ale MTEXT au 250 de caractere"
            assert len(grp(d, 1)) <= 250
        elif typ == "LWPOLYLINE":
            assert [x.cdr for x in d if isinstance(x, DP) and x.car == 100] == ["AcDbEntity", "AcDbPolyline"]
            assert grp(d, 90) == len(grps(d, 10)) >= 2, d
        elif typ == "SOLID":
            for c in (10, 11, 12, 13): assert grp(d, c), d
        elif typ == "LINE":
            assert grp(d, 10) and grp(d, 11)
        elif typ == "CIRCLE":
            assert grp(d, 10) and grp(d, 40) > 0
        s.new(d)
        return d

    def entdel(s, e): s.deleted.add(e); return e
    def entlast(s): return next((e for e in reversed(s.order) if e not in s.deleted), None)
    def handent(s, h):
        e = s.handles.get(h)
        return None if e is None or e in s.deleted else e

    def tblsearch(s, t, n, *a):
        return s.tables.get(t.upper(), {}).get(n.upper())

    def match(s, e, flt):
        d = s.db[e]
        flt = lst(flt)
        if any(f.car == -4 for f in flt):
            # doar forma folosita de program: (-4 . "<NOT") (-4 . "&") (70 . masca) (-4 . "NOT>")
            i = next(k for k, f in enumerate(flt) if f.car == -4 and f.cdr == "<NOT")
            assert flt[i + 1].cdr == "&" and flt[i + 3].cdr == "NOT>", flt
            if (grp(d, 70) or 0) & flt[i + 2].cdr: return False
            flt = flt[:i] + flt[i + 4:]
        for f in flt:
            c, v = f.car, f.cdr
            if c == 0:
                if not any(re.fullmatch(p.replace("*", ".*"), grp(d, 0), re.I) for p in v.split(",")): return False
            elif c == 410:
                if s.space(e).upper() != v.upper(): return False
            elif c == 8:
                if (grp(d, 8) or "").upper() != v.upper(): return False
        return True

    def ssget(s, *a):
        if a and a[0] in ("_X", "X"):
            r = [e for e in s.order if e not in s.deleted and s.match(e, a[1] if len(a) > 1 else None)]
            return r or None
        assert s.vars["CTAB"] == "Model", "selectie interactiva in afara model space"
        kind, val = s.inputs.pop(0)
        assert kind == "ssget", f"intrare asteptata ssget, scenariul are {kind}"
        flt = a[-1] if a and isinstance(a[-1], list) else None
        r = [e for e in lst(val) if s.match(e, flt)]
        return r or None

    def entsel(s, msg=None):
        if msg: s.out.append(msg)
        assert s.vars["CTAB"] == "Model", "entsel in afara model space"
        kind, val = s.inputs.pop(0)
        assert kind == "entsel", f"intrare asteptata entsel, scenariul are {kind} ({msg})"
        if val is None: s.vars["ERRNO"] = 52; return None
        s.vars["ERRNO"] = 0
        p = s.verts(val)[0] if grp(s.db[val], 0) == "LWPOLYLINE" else grp(s.db[val], 10)
        return [val, [p[0], p[1], 0.0]]

    def getstring(s, *a):
        msg = a[-1] if a else ""
        kind, val = s.inputs.pop(0)
        assert kind == "str", f"intrare asteptata text, scenariul are {kind} ({msg})"
        return val

    def getkword(s, msg=None):
        kind, val = s.inputs.pop(0)
        assert kind == "kw", f"intrare asteptata cuvant cheie, scenariul are {kind} ({msg})"
        return val

    # ------------------------------------------------------------ curbe
    def _poly(s, e):
        d = s.db[e]
        assert grp(d, 0) == "LWPOLYLINE", "vlax-curve: doar LWPOLYLINE in simulator"
        return s.verts(e), bool(grp(d, 70) & 1)

    def curve_endparam(s, e):
        v, c = s._poly(e); return float(len(v) if c else len(v) - 1)

    def curve_point(s, e, t):
        v, c = s._poly(e); n = len(v)
        i = int(math.floor(t + 1e-12)); f = t - i
        a = v[i % n]; b = v[(i + 1) % n]
        if f < 1e-12: return [a[0], a[1], 0.0]
        return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, 0.0]

    def curve_area(s, e):
        v, c = s._poly(e)
        return abs(sum(v[i][0] * v[(i + 1) % len(v)][1] - v[(i + 1) % len(v)][0] * v[i][1] for i in range(len(v)))) / 2

    # ------------------------------------------------------------ layout-uri, viewport-uri, comenzi
    def setvar(s, v, val):
        v = v.upper()
        if v == "CTAB":
            lay = s.layouts.get(val.upper())
            assert lay, f"CTAB: layout inexistent {val}"
            s.vars["CTAB"] = lay.name
            if not lay.vp_init and lay.name != "Model":
                # la prima activare AutoCAD creeaza viewport-ul hartiei (ID 1) si unul implicit
                lay.vp_init = True
                s.new([DP(0, "VIEWPORT"), DP(67, 1), DP(410, lay.name), DP(8, "0"), [10, 148.5, 105.0, 0.0],
                       DP(40, 297.0), DP(41, 210.0), DP(68, 1), DP(69, 1), [12, 0.0, 0.0], [17, 0.0, 0.0, 0.0], DP(45, 210.0)])
                s.vpid += 1
                s.new([DP(0, "VIEWPORT"), DP(67, 1), DP(410, lay.name), DP(8, "0"), [10, 140.0, 100.0, 0.0],
                       DP(40, 250.0), DP(41, 180.0), DP(68, 2), DP(69, s.vpid), [12, 0.0, 0.0], [17, 0.0, 0.0, 0.0], DP(45, 180.0)])
            s.vars["CVPORT"] = 1 if lay.name != "Model" else 2
        elif v == "CVPORT":
            ok = [grp(s.db[e], 69) for e in s.entities(s.vars["CTAB"], "VIEWPORT")]
            assert val in ok and val != 1, f"CVPORT invalid {val}"
            s.vars[v] = val
        else:
            s.vars[v] = val
        return val

    def getvar(s, v): return s.vars.get(v.upper())

    def _vp(s, vid):
        return next(e for e in s.entities(s.vars["CTAB"], "VIEWPORT") if grp(s.db[e], 69) == vid)

    def _setg(s, e, code, val):
        d = s.db[e]
        for i, x in enumerate(d):
            if (isinstance(x, DP) and x.car == code) or (isinstance(x, list) and x and x[0] == code):
                d[i] = DP(code, val) if not isinstance(val, list) else [code] + val
                return
        d.append(DP(code, val) if not isinstance(val, list) else [code] + val)

    def command(s, *args):
        args = list(args)
        s.cmds.append(args)
        while args:
            c = args.pop(0)
            if c is None: continue
            name = c.upper().lstrip("_.").lstrip("_") if isinstance(c, str) else c
            if name == "PSPACE":
                assert s.vars["CTAB"] != "Model"; s.vars["CVPORT"] = 1
            elif name == "MSPACE":
                vps = [grp(s.db[e], 69) for e in s.entities(s.vars["CTAB"], "VIEWPORT") if grp(s.db[e], 69) != 1]
                assert vps, "MSPACE fara viewport"
                s.vars["CVPORT"] = vps[-1]
            elif name == "MVIEW":
                assert s.vars["CTAB"] != "Model" and s.vars["CVPORT"] == 1, "MVIEW doar in paper space"
                assert s.vars["OSMODE"] == 0, "MVIEW cu OSNAP activ"
                p1, p2 = args.pop(0), args.pop(0)
                s.vpid += 1
                w, h = abs(p2[0] - p1[0]), abs(p2[1] - p1[1])
                s.new([DP(0, "VIEWPORT"), DP(67, 1), DP(410, s.vars["CTAB"]), DP(8, "0"),
                       [10, (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, 0.0], DP(40, w), DP(41, h), DP(68, 1),
                       DP(69, s.vpid), [12, 0.0, 0.0], [17, 0.0, 0.0, 0.0], DP(45, h)])
            elif name == "PLAN":
                assert s.vars["CVPORT"] != 1, "PLAN in paper space"
                args.pop(0)
            elif name == "ZOOM":
                opt = args.pop(0).upper().lstrip("_")
                assert opt == "C", opt
                assert s.vars["OSMODE"] == 0, "ZOOM Centru cu OSNAP activ"
                pt, sc = args.pop(0), args.pop(0)
                m = re.fullmatch(r"([0-9.]+)XP", sc.upper()); assert m, sc
                e = s._vp(s.vars["CVPORT"])
                assert s.vars["CVPORT"] != 1, "ZOOM XP in paper space"
                s._setg(e, 12, [pt[0], pt[1]])
                s._setg(e, 45, grp(s.db[e], 41) / float(m.group(1)))
            else:
                raise AssertionError(f"comanda nesimulata: {c}")
        return None

    # ------------------------------------------------------------ fisiere
    def findfile(s, f):
        p = s.path(f)
        return p if os.path.exists(p) else None

    def open(s, f, mode, *enc):
        p = s.path(f)
        try: return open(p, {"w": "w", "r": "r", "a": "a"}[mode.lower()], encoding="utf-8", newline="\r\n" if mode.lower() != "r" else None)
        except OSError: return None

    def read_line(s, fh):
        l = fh.readline()
        return l.rstrip("\r\n") if l else None

    # ------------------------------------------------------------ instalarea in interpretor
    def install(s):
        F = {
            "ENTGET": s.entget, "ENTMAKE": s.entmake, "ENTDEL": s.entdel, "ENTLAST": s.entlast,
            "HANDENT": s.handent, "TBLSEARCH": s.tblsearch, "SSGET": s.ssget, "SSLENGTH": lambda ss: len(ss),
            "SSNAME": lambda ss, i: ss[i] if i < len(ss) else None, "ENTSEL": s.entsel,
            "GETSTRING": s.getstring, "GETKWORD": s.getkword, "INITGET": lambda *a: None,
            "GETVAR": s.getvar, "SETVAR": s.setvar, "COMMAND": s.command,
            "GETENV": lambda k: s.envs.get(k), "SETENV": lambda k, v: s.envs.__setitem__(k, v) or v,
            "VLAX-LDATA-GET": lambda o, k, *a: s.ldata.get((o if isinstance(o, str) else o.i, k)),
            "VLAX-LDATA-PUT": lambda o, k, v, *a: s.ldata.__setitem__((o if isinstance(o, str) else o.i, k), v) or v,
            "VLAX-CURVE-GETENDPARAM": s.curve_endparam, "VLAX-CURVE-GETPOINTATPARAM": s.curve_point,
            "VLAX-CURVE-ISCLOSED": lambda e: T if s._poly(e)[1] else None,
            "VLAX-CURVE-GETSTARTPOINT": lambda e: s.curve_point(e, 0.0),
            "VLAX-CURVE-GETENDPOINT": lambda e: s.curve_point(e, s.curve_endparam(e)),
            "VLAX-CURVE-GETAREA": s.curve_area,
            "VLAX-GET-ACAD-OBJECT": lambda: s.app, "VLA-GET-ACTIVEDOCUMENT": lambda a: s.doc,
            "VLA-STARTUNDOMARK": lambda d: None, "VLA-ENDUNDOMARK": lambda d: None,
            "VLA-GET-LAYOUTS": lambda d: Obj("layouts"),
            "VLA-ITEM": lambda c, n: s.layouts[n.upper()] if n.upper() in s.layouts else (_ for _ in ()).throw(KeyError(n)),
            "VLA-ADD": s.vla_add, "VLAX-ENAME->VLA-OBJECT": lambda e: Obj("entity", ename=e),
            "VLA-REFRESHPLOTDEVICEINFO": lambda o: None,
            "FINDFILE": s.findfile, "LOAD": lambda f, *a: M.load(s.path(f)),
            "VL-FILENAME-DIRECTORY": lambda f: os.path.dirname(f.replace("\\", "/")),
            "VL-FILENAME-BASE": lambda f: os.path.splitext(os.path.basename(f.replace("\\", "/")))[0],
            "VL-FILE-DIRECTORY-P": lambda f: T if os.path.isdir(s.path(f)) else None,
            "VL-MKDIR": lambda f: os.makedirs(s.path(f), exist_ok=True) or T,
            "VL-FILE-DELETE": lambda f: (os.remove(s.path(f)) or T) if os.path.exists(s.path(f)) else None,
            "VL-FILENAME-MKTEMP": lambda p=None, d=None, ext="": os.path.join(s.outdir, f"{p or 'tmp'}_{len(s.order)}{ext or ''}"),
            "OPEN": s.open, "CLOSE": lambda fh: fh.close(), "WRITE-LINE": lambda t, fh: fh.write(t + "\n") and t,
            "READ-LINE": s.read_line, "ALERT": lambda m: s.alerts.append(m),
            "PRINC": s.princ,
            "LOAD_DIALOG": s.dcl.load_dialog, "UNLOAD_DIALOG": s.dcl.unload_dialog, "NEW_DIALOG": s.dcl.new_dialog,
            "START_DIALOG": s.dcl.start_dialog, "DONE_DIALOG": s.dcl.done_dialog, "SET_TILE": s.dcl.set_tile,
            "GET_TILE": s.dcl.get_tile, "ACTION_TILE": s.dcl.action_tile, "MODE_TILE": s.dcl.mode_tile,
            "START_LIST": s.dcl.start_list, "ADD_LIST": s.dcl.add_list, "END_LIST": s.dcl.end_list,
            "DIMX_TILE": lambda k: s.dcl.dim_tile(k, 0), "DIMY_TILE": lambda k: s.dcl.dim_tile(k, 1),
            "START_IMAGE": s.dcl.start_image, "VECTOR_IMAGE": s.dcl.vector_image, "FILL_IMAGE": s.dcl.fill_image,
            "END_IMAGE": s.dcl.end_image,
        }
        for k, v in F.items(): funcs[Sym(k)] = v
        for k in ("CONFIGNAME", "CANONICALMEDIANAME", "PAPERUNITS", "PLOTROTATION", "STANDARDSCALE", "PLOTTYPE",
                  "PLOTWITHLINEWEIGHTS", "DISPLAYLOCKED", "LAYER"):
            funcs[Sym("VLA-PUT-" + k)] = (lambda k: lambda o, v: s.vla_put(o, k, v))(k)

    def princ(s, *a):
        if a and isinstance(a[0], str):
            s.out.append(a[0])
            if s.verbose: print(a[0], end="")
        return a[0] if a else None

    def vla_add(s, coll, name):
        assert coll.kind == "layouts"
        assert name.upper() not in s.layouts, f"layout existent {name}"
        s.layouts[name.upper()] = Obj("layout", name=name, vp_init=False)
        return s.layouts[name.upper()]

    def vla_put(s, o, k, v):
        o.props[k] = v
        if o.kind == "entity" and k == "LAYER":
            s._setg(o.ename, 8, v)
        return v

    def after_load(s):
        """Inlocuiri dupa incarcarea TopoKit.lsp (rularea programelor externe)."""
        def run(cmd, wait):
            s.runs.append(cmd)
            return 0
        env[Sym("TK:RUN")] = run
