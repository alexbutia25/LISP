"""
DWG to KMZ - convertor DXF/DWG (Stereo 70) -> KMZ (Google Earth), parte din TopoKit
"""
import html
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
import zipfile
from dataclasses import dataclass, field

import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageDraw, ImageTk

import customtkinter as ctk
import ezdxf
from ezdxf import recover
from ezdxf import path as ezpath
from ezdxf.colors import aci2rgb, int2rgb
from pyproj import Transformer

from transdatro import OutsideGrid, stereo70_to_etrs89
import dwg
import tklic

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    HAS_DND = False

APP_NAME = "DWG to KMZ"
TOPOKIT = "TopoKit 1.10.0"   # programul face parte din TopoKit
HELP_FILE = "Instructiuni DWG to KMZ.html"
FLAT_DIST = 0.05  # metri - precizia aproximarii arcelor / curbelor

# (cheie, eticheta, culoare accent)
CATEGORIES = [
    ("polygon", "Poligoane", "#2E8B57"),
    ("polyline", "Polilinii", "#1F8FBF"),
    ("line", "Linii", "#8A6D3B"),
    ("point", "Puncte", "#D08A12"),
    ("text", "Texte / Tabele", "#6A4FB6"),
]
CAT_LABEL = {k: l for k, l, _ in CATEGORIES}
LINEAR = ("polyline", "line")   # categorii desenate ca linie

ACCENT = "#1B6A8F"          # teal TopoKit
EXCLUDED_COL = "#D64541"
TOOL_CLICK, TOOL_RECT, TOOL_POLY = "🖐 Click", "▭ Dreptunghi", "⬠ Poligon"
SEL_OUT, SEL_IN = "➖ Scoate", "➕ Pune înapoi"
MODE_FULL, MODE_TOUCH = "Complet în zonă", "Atinge zona"
PREVIEW_HINT = ("🖱  Click pe obiect = scoate / pune la export   ·   Shift + trage = scoate o zonă   ·   "
                "Ctrl + trage = pune zona înapoi   ·   Rotiță = zoom   ·   Trage = mută")
ACCENT_HOVER = "#0F3D5E"    # bleumarin TopoKit
NAVY = "#0F3D5E"
BG = "#F4F7FA"              # fundalul ferestrei TopoKit
CARD = "#FFFFFF"
CARD_2 = "#EEF2F6"
BORDER = "#DDE5EC"
MUTED = "#5B6B7A"
TEXT = "#1A2733"
AMBER = "#1B6A8F"           # insignele numerotate (teal)
OK_COL = "#2EAD5B"
DIM = "#C5CED6"             # obiecte neexportate
BTN_2 = "#E6EDF3"           # butoane secundare
BTN_2_HOVER = "#D5E1EB"
CANVAS_BG = "#F8FAFC"


def asset(name):
    """Fisier din folderul assets (langa script, inclus in exe PyInstaller (_MEIPASS) sau langa exe-ul
    Nuitka standalone, unde __file__ e in folderul programului)."""
    for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))):
        if base:
            p = os.path.join(base, "assets", name)
            if os.path.isfile(p):
                return p
    return None


def _round_rect(c, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
           x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


def _topokit_band(w, h):
    """Banda antetului TopoKit: degrade bleumarin -> teal, cu curbe de nivel discrete."""
    im = Image.new("RGB", (w, h))
    px = im.load()
    c1, c2 = (15, 61, 94), (30, 111, 147)
    for x in range(w):
        t = x / max(w - 1, 1)
        col = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
        for y in range(h):
            px[x, y] = col
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    for cx, cy, radii, k0 in ((w - 150, h + 10, (40, 75, 110, 145, 180), 0), (w * 0.45, -20, (50, 90, 130), 2)):
        for k, r in enumerate(radii):
            pts = []
            for i in range(97):
                a = 2 * math.pi * i / 96
                rr = r * (1 + 0.12 * math.sin(3 * a + k + k0))
                pts.append((cx + rr * math.cos(a), cy + 0.6 * rr * math.sin(a)))
            dr.line(pts, fill=(255, 255, 255, 34), width=2)
    return Image.alpha_composite(im.convert("RGBA"), ov)


def _mini_pine(c, x, base, h, color, tags=()):
    for k in range(3):
        top = base - h + k * h * 0.22
        w = h * (0.32 + 0.14 * k)
        c.create_polygon(x, top, x - w / 2, top + h * 0.42, x + w / 2, top + h * 0.42, fill=color, tags=tags)
    c.create_rectangle(x - h * 0.05, base - h * 0.14, x + h * 0.05, base, fill=color, outline="", tags=tags)

# Romania (WGS84) pentru autodetectia ordinii X/Y
RO_BBOX = (20.0, 43.4, 30.0, 48.5)


def desktop_dir():
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and os.path.isdir(buf.value):
                return buf.value
        except Exception:
            pass
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return d if os.path.isdir(d) else os.path.expanduser("~")


# --------------------------------------------------------------------------
#  Model + citire DXF
# --------------------------------------------------------------------------
@dataclass
class Feature:
    kind: str                 # polygon | polyline | point | text
    layer: str
    geom: list                # polygon: [ring, ring...]; polyline: [pts]; point/text: [(x, y)]
    name: str = ""
    color: tuple = (255, 255, 255)
    attrs: dict = field(default_factory=dict)
    text: str = ""
    table: list = None        # randuri pentru ACAD_TABLE


def _clean(pts):
    out = []
    for p in pts:
        if not out or abs(out[-1][0] - p[0]) > 1e-9 or abs(out[-1][1] - p[1]) > 1e-9:
            out.append(p)
    return out


def _flatten(p):
    return _clean([(v.x, v.y) for v in p.flattening(distance=FLAT_DIST, segments=16)])


def _ring_area(r):
    a = 0.0
    for i in range(len(r) - 1):
        a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]
    return a / 2.0


def _close_ring(pts):
    if len(pts) and (pts[0][0] != pts[-1][0] or pts[0][1] != pts[-1][1]):
        pts = pts + [pts[0]]
    return pts


def _entity_rgb(e, doc):
    try:
        if e.dxf.hasattr("true_color"):
            return int2rgb(e.dxf.true_color)
    except Exception:
        pass
    aci = e.dxf.get("color", 256)
    if aci in (0, 256):
        lname = e.dxf.get("layer", "0")
        if doc.layers.has_entry(lname):
            layer = doc.layers.get(lname)
            try:
                if layer.rgb:
                    return tuple(layer.rgb)
            except Exception:
                pass
            aci = abs(layer.color)
        else:
            aci = 7
    if not 1 <= aci <= 255:
        aci = 7
    return tuple(aci2rgb(aci))


def _insert_name(e):
    attrs = {}
    try:
        for a in e.attribs:
            attrs[a.dxf.tag] = a.dxf.text
    except Exception:
        pass
    name = ""
    for key in attrs:
        if key.upper() in ("NR", "NUME", "NAME", "PUNCT", "PCT", "ID", "NR_PCT", "NRPCT", "COD"):
            name = attrs[key]
            break
    if not name:
        name = next((v for v in attrs.values() if str(v).strip()), "")
    return name or e.dxf.name, attrs


def _table_insert(e):
    try:
        v = e.get_insert_location()
        if v is not None:
            return (v.x, v.y)
    except Exception:
        pass
    try:
        sub = e.xtags.get_subclass("AcDbBlockReference")
        for tag in sub:
            if tag.code == 10:
                return (tag.value[0], tag.value[1])
    except Exception:
        pass
    return None


def _read_table(e):
    try:
        from ezdxf.entities.acad_table import read_acad_table_content
        rows = read_acad_table_content(e)
        rows = [[str(c or "").strip() for c in r] for r in rows]
        return [r for r in rows if any(r)]
    except Exception:
        return []


def open_dxf(path):
    """Deschide DXF-ul; daca e stricat (ex. scris de LibreDWG), il repara: scoate obiectele
    cu date corupte si sectiunile de care nu avem nevoie, apoi incearca din nou."""
    try:
        return ezdxf.readfile(path)
    except Exception as ex:
        first = ex
    fd, fixed = tempfile.mkstemp(suffix=".dxf", prefix="dwg2kmz_fix_")
    os.close(fd)
    try:
        dwg.repair_dxf(path, fixed, minimal=True)
        for reader in (ezdxf.readfile, lambda p: recover.readfile(p)[0]):
            try:
                return reader(fixed)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        try:
            os.remove(fixed)
        except OSError:
            pass
    try:
        return recover.readfile(path)[0]
    except Exception:
        raise first


def read_dxf(path):
    if path.lower().endswith(".dwg"):
        dxf_path, tmp_dir, _conv = dwg.dwg_to_dxf(path)
        try:
            return read_dxf(dxf_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    doc = open_dxf(path)
    msp = doc.modelspace()
    feats = []
    counters = {"point": 0}
    skipped = 0

    for e in msp:
        t = e.dxftype()
        layer = e.dxf.get("layer", "0")
        try:
            if t in ("LWPOLYLINE", "POLYLINE", "LINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
                if t == "POLYLINE" and (e.is_polygon_mesh or e.is_poly_face_mesh):
                    skipped += 1
                    continue
                closed = False
                if t == "LWPOLYLINE":
                    closed = e.closed
                elif t == "POLYLINE":
                    closed = e.is_closed
                elif t == "CIRCLE":
                    closed = True
                elif t == "ELLIPSE":
                    span = (e.dxf.end_param - e.dxf.start_param) % (2 * math.pi)
                    closed = span < 1e-6
                elif t == "SPLINE":
                    closed = e.closed
                pts = _flatten(ezpath.make_path(e))
                if len(pts) < 2:
                    continue
                if not closed and len(pts) >= 4 and math.dist(pts[0], pts[-1]) < 1e-6:
                    closed = True
                color = _entity_rgb(e, doc)
                if closed and len(_clean(pts)) >= 3:
                    feats.append(Feature("polygon", layer, [_close_ring(pts)],
                                         name=f"{layer}", color=color, attrs={"Tip DXF": t}))
                else:
                    feats.append(Feature("line" if t == "LINE" else "polyline", layer, [pts], name=f"{layer}",
                                         color=color, attrs={"Tip DXF": t}))

            elif t == "HATCH":
                rings = []
                for p in ezpath.from_hatch(e):
                    pts = _flatten(p)
                    if len(pts) >= 3:
                        rings.append(_close_ring(pts))
                if not rings:
                    continue
                rings.sort(key=lambda r: abs(_ring_area(r)), reverse=True)
                feats.append(Feature("polygon", layer, rings, name=f"{layer}",
                                     color=_entity_rgb(e, doc), attrs={"Tip DXF": "HATCH"}))

            elif t == "POINT":
                loc = e.dxf.location
                counters["point"] += 1
                feats.append(Feature("point", layer, [(loc.x, loc.y)],
                                     name=f"Punct {counters['point']}",
                                     color=_entity_rgb(e, doc), attrs={"Z": f"{loc.z:.3f}"}))

            elif t == "INSERT":
                ins = e.dxf.insert
                name, attrs = _insert_name(e)
                attrs = dict(attrs)
                attrs["Bloc"] = e.dxf.name
                if abs(ins.z) > 1e-9:
                    attrs["Z"] = f"{ins.z:.3f}"
                feats.append(Feature("point", layer, [(ins.x, ins.y)], name=str(name),
                                     color=_entity_rgb(e, doc), attrs=attrs))

            elif t in ("TEXT", "MTEXT"):
                txt = e.plain_text() if t == "TEXT" else e.plain_text(split=False)
                txt = (txt or "").strip()
                if not txt:
                    continue
                ins = e.dxf.insert
                feats.append(Feature("text", layer, [(ins.x, ins.y)], name=txt.split("\n")[0][:80],
                                     color=_entity_rgb(e, doc), text=txt))

            elif t == "ACAD_TABLE":
                loc = _table_insert(e)
                rows = _read_table(e)
                if loc is None:
                    continue
                title = rows[0][0] if rows and rows[0] and rows[0][0] else "Tabel"
                feats.append(Feature("text", layer, [loc], name=title[:80],
                                     color=_entity_rgb(e, doc), table=rows,
                                     text="\n".join(" | ".join(r) for r in rows)))
            else:
                skipped += 1
        except Exception:
            skipped += 1

    layers = {}
    for f in feats:
        layers.setdefault(f.layer, f.color)
    for lay in doc.layers:
        if lay.dxf.name in layers:
            try:
                layers[lay.dxf.name] = tuple(lay.rgb) if lay.rgb else tuple(aci2rgb(abs(lay.color) or 7))
            except Exception:
                pass
    return feats, layers, skipped


def _point_in_poly(pt, poly):
    """Ray casting: punctul pt e in interiorul poligonului poly (lista de (x, y))?"""
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _seg_cross(a, b, c, d):
    """Segmentele ab si cd se intersecteaza?"""
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    d1, d2 = orient(c, d, a), orient(c, d, b)
    d3, d4 = orient(a, b, c), orient(a, b, d)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


# --------------------------------------------------------------------------
#  Transformare Stereo 70 -> WGS84
# --------------------------------------------------------------------------
# Transformarea principala: TransDatRO (ANCPI) cu grila de corectii - vezi transdatro.py,
# identica cu programul oficial (testat pe punctele de control ANCPI, < 1 mm).
# Rezerva, doar pentru puncte in afara grilei (la granita / in afara tarii):
# Helmert 7 parametri oficial ANCPI Stereo 70 (Krasovski 1940) -> ETRS89, EPSG:15994
# ("Pulkovo 1942(58) to ETRS89 (4)", Helmert 7 parametri, coordinate frame) -
# consistenta cu TransDatRO la sub 0.5 m. ETRS89 ~ WGS84 pentru Google Earth.
# ATENTIE: EPSG:31700 in PROJ NU aplica nicio schimbare de datum (eroare ~120 m).
STEREO70_PIPELINE = (
    "+proj=pipeline "
    "+step +inv +proj=sterea +lat_0=46 +lon_0=25 +k=0.99975 +x_0=500000 +y_0=500000 +ellps=krass "
    "+step +proj=push +v_3 "
    "+step +proj=cart +ellps=krass "
    "+step +proj=helmert +x=2.3287 +y=-147.0425 +z=-92.0802 "
    "+rx=0.3092483 +ry=-0.32482185 +rz=-0.49729934 +s=5.68906266 +convention=coordinate_frame "
    "+step +inv +proj=cart +ellps=GRS80 "
    "+step +proj=pop +v_3 "
    "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
)
_TR = Transformer.from_pipeline(STEREO70_PIPELINE)


FALLBACK_COUNT = [0]  # varfuri transformate cu Helmert (in afara grilei TransDatRO)


def to_ll(x, y, swap=False):
    """Stereo 70 (x = Est, y = Nord din desen) -> (lon, lat) ETRS89/WGS84."""
    if swap:
        x, y = y, x
    try:
        return stereo70_to_etrs89(x, y)
    except OutsideGrid:
        FALLBACK_COUNT[0] += 1
        return _TR.transform(x, y)


def detect_swap(feats):
    """Returneaza True daca X/Y din desen par inversate (X=Nord)."""
    sample = []
    for f in feats[:: max(1, len(feats) // 50)]:
        sample.append(f.geom[0][0] if f.kind in ("polygon",) + LINEAR else f.geom[0])
    if not sample:
        return False

    def score(swap):
        ok = 0
        for x, y in sample:
            if swap:
                x, y = y, x
            try:
                stereo70_to_etrs89(x, y)   # valid doar daca e in grila Romaniei
                ok += 1
            except (OutsideGrid, ValueError):
                pass
        return ok

    return score(True) > score(False)


# --------------------------------------------------------------------------
#  Scriere KML / KMZ
# --------------------------------------------------------------------------
def kml_color(rgb, alpha=255):
    r, g, b = rgb
    return f"{alpha:02x}{b:02x}{g:02x}{r:02x}"


def esc(s):
    return html.escape(str(s), quote=True)


def _coords(pts, swap):
    return " ".join("{:.8f},{:.8f},0".format(*to_ll(x, y, swap)) for x, y in pts)


def _attr_table(rows):
    if not rows:
        return ""
    body = "".join(f"<tr><td><b>{esc(k)}</b></td><td>{esc(v)}</td></tr>" for k, v in rows)
    return f"<table border='1' cellpadding='3' style='border-collapse:collapse'>{body}</table>"


def _desc(f, swap, coord_table):
    parts = [f"<b>Layer:</b> {esc(f.layer)}<br/>"]
    if f.kind == "polygon":
        outer = f.geom[0]
        area = abs(_ring_area(outer)) - sum(abs(_ring_area(r)) for r in f.geom[1:])
        per = sum(math.dist(outer[i], outer[i + 1]) for i in range(len(outer) - 1))
        parts.append(f"<b>Suprafață:</b> {area:,.2f} mp ({area / 10000:.4f} ha)<br/>"
                     f"<b>Perimetru:</b> {per:,.2f} m<br/>")
        if coord_table and len(outer) <= 400:
            rows = "".join(
                f"<tr><td>{i + 1}</td><td>{(p[0] if swap else p[1]):.3f}</td>"
                f"<td>{(p[1] if swap else p[0]):.3f}</td></tr>"
                for i, p in enumerate(outer[:-1]))
            parts.append("<br/><b>Inventar de coordonate (Stereo 70)</b>"
                         "<table border='1' cellpadding='3' style='border-collapse:collapse'>"
                         "<tr><th>Pct</th><th>X (N)</th><th>Y (E)</th></tr>" + rows + "</table>")
    elif f.kind in LINEAR:
        pts = f.geom[0]
        ln = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        parts.append(f"<b>Lungime:</b> {ln:,.2f} m<br/>")
    elif f.kind == "point":
        x, y = f.geom[0]
        n, e = (x, y) if swap else (y, x)
        parts.append(f"<b>X (N):</b> {n:.3f}<br/><b>Y (E):</b> {e:.3f}<br/>")
        parts.append(_attr_table(list(f.attrs.items())))
    elif f.kind == "text":
        if f.table:
            body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in f.table)
            parts.append("<table border='1' cellpadding='3' style='border-collapse:collapse'>"
                         + body + "</table>")
        else:
            parts.append(esc(f.text).replace("\n", "<br/>"))
    parts.append(f"<br/><i style='color:gray'>Generat cu {APP_NAME} ({TOPOKIT})</i>")
    return "<![CDATA[" + "".join(parts).replace("]]>", "]] >") + "]]>"


def build_kml(feats, doc_name, swap, opts):
    """opts: fill_alpha (0-255), line_width, coord_table, show_labels"""
    styles = {}

    def style_id(kind, rgb):
        key = (kind, rgb)
        if key not in styles:
            sid = f"s_{kind}_{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            c = kml_color(rgb)
            if kind == "polygon":
                body = (f"<LineStyle><color>{c}</color><width>{opts['line_width']}</width></LineStyle>"
                        f"<PolyStyle><color>{kml_color(rgb, opts['fill_alpha'])}</color></PolyStyle>")
            elif kind in LINEAR:
                body = f"<LineStyle><color>{c}</color><width>{opts['line_width']}</width></LineStyle>"
            elif kind == "point":
                lbl = "1" if opts["show_labels"] else "0"
                body = (f"<IconStyle><color>{c}</color><scale>0.8</scale><Icon><href>"
                        "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
                        f"</href></Icon></IconStyle><LabelStyle><scale>{lbl}</scale></LabelStyle>")
            else:
                body = ("<IconStyle><scale>0</scale></IconStyle>"
                        f"<LabelStyle><color>{c}</color><scale>0.9</scale></LabelStyle>")
            styles[key] = (sid, f'<Style id="{sid}">{body}</Style>')
        return styles[key][0]

    folders = []
    for kind, label, _ in CATEGORIES:
        sub = [f for f in feats if f.kind == kind]
        if not sub:
            continue
        by_layer = {}
        for f in sub:
            by_layer.setdefault(f.layer, []).append(f)
        lay_xml = []
        for lname in sorted(by_layer):
            pms = []
            for f in by_layer[lname]:
                sid = style_id(kind, f.color)
                d = _desc(f, swap, opts["coord_table"])
                if kind == "polygon":
                    outer = f"<outerBoundaryIs><LinearRing><coordinates>{_coords(f.geom[0], swap)}" \
                            "</coordinates></LinearRing></outerBoundaryIs>"
                    inner = "".join(f"<innerBoundaryIs><LinearRing><coordinates>{_coords(r, swap)}"
                                    "</coordinates></LinearRing></innerBoundaryIs>" for r in f.geom[1:])
                    g = f"<Polygon><tessellate>1</tessellate>{outer}{inner}</Polygon>"
                elif kind in LINEAR:
                    g = f"<LineString><tessellate>1</tessellate><coordinates>{_coords(f.geom[0], swap)}" \
                        "</coordinates></LineString>"
                else:
                    g = f"<Point><coordinates>{_coords(f.geom, swap)}</coordinates></Point>"
                pms.append(f"<Placemark><name>{esc(f.name)}</name><description>{d}</description>"
                           f"<styleUrl>#{sid}</styleUrl>{g}</Placemark>")
            lay_xml.append(f"<Folder><name>{esc(lname)} ({len(pms)})</name>{''.join(pms)}</Folder>")
        folders.append(f"<Folder><name>{esc(label)} ({len(sub)})</name>{''.join(lay_xml)}</Folder>")

    style_xml = "".join(s for _, s in styles.values())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{esc(doc_name)}</name>"
            f"<description>Convertit din Stereo 70 cu {APP_NAME} ({TOPOKIT})</description>"
            f"{style_xml}{''.join(folders)}</Document></kml>")


def save_kmz(path, kml_text):
    if not tklic.valid():
        raise PermissionError(tklic.text())
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml_text.encode("utf-8"))


# --------------------------------------------------------------------------
#  Previzualizare pe harta (Leaflet in browser)
# --------------------------------------------------------------------------
MAP_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Convertor DXF/DWG - KMZ – previzualizare</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{height:100%;margin:0;font-family:Segoe UI,sans-serif}
.badge{position:absolute;z-index:999;bottom:18px;left:12px;background:#0f172acc;color:#fff;
padding:6px 12px;border-radius:8px;font-size:13px}
.lbl{background:none;border:none;box-shadow:none;color:#fff;font-weight:600;text-shadow:0 0 3px #000}</style>
</head><body><div id="m"></div><div class="badge">__TITLE__ · DWG to KMZ · TopoKit</div>
<script>
const data = __DATA__;
const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {maxZoom: 21, maxNativeZoom: 19, attribution: 'Esri World Imagery'});
const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom: 21, maxNativeZoom: 19, attribution: '&copy; OpenStreetMap'});
const map = L.map('m', {layers: [sat]});
const g = L.geoJSON(data, {
  style: f => ({color: f.properties.color, weight: 2, fillOpacity: f.properties.kind==='polygon'?0.25:0}),
  pointToLayer: (f, ll) => f.properties.kind === 'text'
     ? L.marker(ll, {icon: L.divIcon({className:'lbl', html: f.properties.name, iconSize: null})})
     : L.circleMarker(ll, {radius: 5, color: '#000', weight: 1, fillColor: f.properties.color, fillOpacity: 1}),
  onEachFeature: (f, l) => l.bindPopup('<b>' + f.properties.name + '</b><br>Layer: ' + f.properties.layer)
}).addTo(map);
L.control.layers({'Satelit': sat, 'Hartă': osm}, {'Export': g}).addTo(map);
try { map.fitBounds(g.getBounds(), {padding: [20, 20]}); } catch (e) { map.setView([45.9, 25], 7); }
</script></body></html>"""


def build_geojson(feats, swap):
    out = []
    for f in feats:
        col = "#%02x%02x%02x" % f.color
        if f.kind == "polygon":
            geom = {"type": "Polygon",
                    "coordinates": [[list(to_ll(x, y, swap)) for x, y in r] for r in f.geom]}
        elif f.kind in LINEAR:
            geom = {"type": "LineString", "coordinates": [list(to_ll(x, y, swap)) for x, y in f.geom[0]]}
        else:
            geom = {"type": "Point", "coordinates": list(to_ll(*f.geom[0], swap))}
        out.append({"type": "Feature", "geometry": geom,
                    "properties": {"kind": f.kind, "name": html.escape(f.name), "layer": html.escape(f.layer),
                                   "color": col}})
    return {"type": "FeatureCollection", "features": out}


# --------------------------------------------------------------------------
#  Interfata grafica
# --------------------------------------------------------------------------
if HAS_DND:
    class BaseTk(ctk.CTk, TkinterDnD.DnDWrapper):
        pass
else:
    class BaseTk(ctk.CTk):
        pass


class App(BaseTk):
    def __init__(self):
        super().__init__()
        if HAS_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                pass
        ctk.set_appearance_mode("light")
        self.title(f"TopoKit — {APP_NAME}")
        self.geometry("1320x820")
        self.minsize(1080, 680)
        self.configure(fg_color=BG)
        self._set_icon()

        self.features = []
        self.layers = {}
        self.dxf_path = None
        self.swap = tk.BooleanVar(value=False)
        self.cat_vars = {k: tk.BooleanVar(value=True) for k, _, _ in CATEGORIES}
        self.layer_vars = {}
        self.coord_table = tk.BooleanVar(value=True)
        self.show_labels = tk.BooleanVar(value=True)
        self.open_after = tk.BooleanVar(value=True)
        self.fill_alpha = tk.DoubleVar(value=35)
        self.out_dir = tk.StringVar(value=desktop_dir())
        self.out_name = tk.StringVar(value="")
        self.view = None  # (S, X0, Y0)
        self.excluded = set()      # obiecte scoase manual din previzualizare (indici in self.features)
        self.tool = tk.StringVar(value=TOOL_CLICK)
        self.sel_action = tk.StringVar(value=SEL_OUT)
        self.sel_mode = tk.StringVar(value=MODE_FULL)
        self._poly_world = []
        self._box_mode = None
        self._item_feat = {}

        self._build_ui()
        if HAS_DND:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    # ---------- UI ----------
    def _open_help(self):
        if not open_help():
            messagebox.showinfo(APP_NAME, "Nu am găsit fișierul cu instrucțiuni.")

    def _set_icon(self):
        # PyInstaller: _MEIPASS; Nuitka standalone / sursa: folderul de langa __file__ (= langa exe)
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        try:
            self.iconbitmap(asset("topokit.ico") or os.path.join(base, "topokit.ico"))
        except Exception:
            pass

    def _card(self, parent, title, step, icon=""):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        card.pack(fill="x", pady=(0, 10))
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(head, text=str(step), width=26, height=26, corner_radius=13, fg_color=AMBER,
                     text_color="#FFFFFF", font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(side="left")
        ctk.CTkLabel(head, text=f"{icon}  {title}" if icon else title, text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 15, "bold")).pack(side="left", padx=8)
        return card

    def _build_ui(self):
        # Antet: banda TopoKit (bleumarin, curbe de nivel), desenata pe canvas
        self.header = tk.Canvas(self, height=88, highlightthickness=0, bg=BG)
        self.header.pack(fill="x")
        self.header.bind("<Configure>", self._draw_header)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=12)

        left_col = ctk.CTkFrame(body, fg_color="transparent")
        left_col.pack(side="left", fill="y")
        # bara fixa de export - mereu vizibila, jos in stanga
        dock = ctk.CTkFrame(left_col, fg_color=CARD, corner_radius=14, border_width=2, border_color=ACCENT)
        dock.pack(side="bottom", fill="x", pady=(10, 0))
        left = ctk.CTkScrollableFrame(left_col, fg_color="transparent", width=380)
        left.pack(side="top", fill="both", expand=True)
        self.left_scroll = left
        right = ctk.CTkFrame(body, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        # 1. Fisier
        c1 = self._card(left, "Fișier DXF / DWG", 1, "📂")
        self.drop = ctk.CTkFrame(c1, fg_color=CARD_2, corner_radius=12, border_width=2,
                                 border_color="#B9C8D6", height=120)
        self.drop.pack(fill="x", padx=14, pady=(0, 8))
        self.drop.pack_propagate(False)
        try:
            self._drop_img = ctk.CTkImage(Image.open(asset("dwg2kmz_icon.png")), size=(40, 40))
        except Exception:
            self._drop_img = None
        self.drop_lbl = ctk.CTkLabel(
            self.drop, text="Trage fișierul DXF sau DWG aici\nsau apasă pentru a-l alege", image=self._drop_img,
            compound="top", font=ctk.CTkFont("Segoe UI", 14), text_color="#3B4A58", justify="center")
        self.drop_lbl.pack(expand=True)
        for w in (self.drop, self.drop_lbl):
            w.bind("<Button-1>", lambda e: self._browse_dxf())
            w.bind("<Enter>", lambda e: self.drop.configure(border_color=AMBER))
            w.bind("<Leave>", lambda e: self.drop.configure(border_color="#B9C8D6"))
        self.file_info = ctk.CTkLabel(c1, text="Niciun fișier încărcat", text_color=MUTED,
                                      font=ctk.CTkFont("Segoe UI", 12), wraplength=330, justify="left")
        self.file_info.pack(anchor="w", padx=16, pady=(0, 6))
        ctk.CTkCheckBox(c1, text="Inversează X / Y (X = Nord)", variable=self.swap,
                        command=self._on_swap).pack(anchor="w", padx=16, pady=(0, 12))

        # 2. Ce exporti
        c2 = self._card(left, "Ce exporți în KMZ", 2, "🧭")
        btns = ctk.CTkFrame(c2, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkButton(btns, text="✔ Selectează tot", height=30, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=lambda: self._select_all(True)).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(btns, text="✖ Deselectează", height=30, fg_color=BTN_2, text_color=NAVY, hover_color=BTN_2_HOVER,
                      command=lambda: self._select_all(False)).pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.cat_checks = {}
        for key, label, col in CATEGORIES:
            row = ctk.CTkFrame(c2, fg_color=CARD_2, corner_radius=10)
            row.pack(fill="x", padx=14, pady=3)
            ctk.CTkLabel(row, text="", width=6, fg_color=col, corner_radius=3).pack(side="left", fill="y",
                                                                                     padx=(0, 8))
            cb = ctk.CTkCheckBox(row, text=label, variable=self.cat_vars[key], command=lambda k=key: self._on_cat_toggle(k),
                                 font=ctk.CTkFont("Segoe UI", 13))
            cb.pack(side="left", pady=7)
            cnt = ctk.CTkLabel(row, text="0", text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12, "bold"))
            cnt.pack(side="right", padx=10)
            self.cat_checks[key] = cnt

        ctk.CTkLabel(c2, text="Layere", font=ctk.CTkFont("Segoe UI", 13, "bold")).pack(anchor="w", padx=16,
                                                                                     pady=(10, 2))
        self.layer_box = ctk.CTkScrollableFrame(c2, fg_color=CARD_2, height=150, corner_radius=10)
        self.layer_box.pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkLabel(self.layer_box, text="—", text_color=MUTED).pack(anchor="w")

        opt = ctk.CTkFrame(c2, fg_color="transparent")
        opt.pack(fill="x", padx=14, pady=(4, 12))
        ctk.CTkCheckBox(opt, text="Inventar coordonate + suprafață la poligoane",
                        variable=self.coord_table).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(opt, text="Afișează numele punctelor", variable=self.show_labels).pack(anchor="w", pady=2)
        fr = ctk.CTkFrame(opt, fg_color="transparent")
        fr.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(fr, text="Transparență umplere").pack(side="left")
        self.alpha_lbl = ctk.CTkLabel(fr, text="35%", width=40, text_color=MUTED)
        self.alpha_lbl.pack(side="right")
        ctk.CTkSlider(opt, from_=0, to=100, variable=self.fill_alpha,
                      command=lambda v: self.alpha_lbl.configure(text=f"{int(v)}%")).pack(fill="x", pady=(0, 2))

        # 3. Destinatie
        c3 = self._card(left, "Nume fișier KMZ", 3, "🏷")
        r2 = ctk.CTkFrame(c3, fg_color="transparent")
        r2.pack(fill="x", padx=14, pady=(0, 0))
        ctk.CTkLabel(r2, text="Nume:").pack(side="left")
        ctk.CTkEntry(r2, textvariable=self.out_name, placeholder_text="fisier").pack(side="left", fill="x",
                                                                                   expand=True, padx=6)
        ctk.CTkLabel(r2, text=".kmz", text_color=MUTED).pack(side="left")
        ctk.CTkCheckBox(c3, text="Deschide folderul după export", variable=self.open_after).pack(
            anchor="w", padx=16, pady=(8, 12))

        erow = ctk.CTkFrame(dock, fg_color="transparent")
        erow.pack(fill="x", padx=12, pady=(12, 4))
        self.export_btn = ctk.CTkButton(erow, text="⬇  EXPORTĂ KMZ", height=52, corner_radius=12,
                                        font=ctk.CTkFont("Segoe UI", 17, "bold"), fg_color=ACCENT,
                                        hover_color=ACCENT_HOVER, command=self._export, state="disabled")
        self.export_btn.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(erow, text="📁", width=52, height=52, corner_radius=12,
                      font=ctk.CTkFont("Segoe UI", 20), fg_color=BTN_2, text_color=NAVY, hover_color=BTN_2_HOVER,
                      command=self._browse_out).pack(side="left", padx=(8, 0))
        self.dest_lbl = ctk.CTkLabel(dock, text="", text_color="#3B4A58", anchor="w", justify="left",
                                     font=ctk.CTkFont("Segoe UI", 12), cursor="hand2")
        self.dest_lbl.pack(fill="x", padx=12, pady=(0, 6))
        self.dest_lbl.bind("<Button-1>", lambda e: self._browse_out())
        self.out_dir.trace_add("write", lambda *a: self._update_dest())
        self._update_dest()
        self.progress = ctk.CTkProgressBar(dock, height=6, progress_color=OK_COL, fg_color="#E3EAF0")
        self.progress.set(0)
        self.progress.pack(fill="x", padx=12, pady=(0, 6))
        self.status = ctk.CTkLabel(dock, text="Gata de lucru.", text_color=MUTED, wraplength=360,
                                   justify="left")
        self.status.pack(anchor="w", padx=12, pady=(0, 10))

        # Dreapta: preview
        bar = ctk.CTkFrame(right, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(bar, text="🗺  Previzualizare export", text_color=TEXT,
                     font=ctk.CTkFont("Segoe UI", 15, "bold")).pack(
            side="left")
        ctk.CTkButton(bar, text="🌍 Vezi pe hartă (satelit)", height=34, fg_color="#0E8C7F",
                      hover_color="#0B6F65", command=self._map_preview).pack(side="right")
        ctk.CTkButton(bar, text="⤢ Potrivește", height=30, width=100, fg_color=BTN_2, text_color=NAVY,
                      hover_color=BTN_2_HOVER, command=self._fit).pack(side="right", padx=6)
        ctk.CTkButton(bar, text="↺ Include tot", height=30, width=110, fg_color=BTN_2, text_color=NAVY,
                      hover_color=BTN_2_HOVER, command=self._include_all).pack(side="right")

        tools = ctk.CTkFrame(right, fg_color="transparent")
        tools.pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkLabel(tools, text="Selectare:", text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12)).pack(side="left")
        ctk.CTkSegmentedButton(tools, values=[TOOL_CLICK, TOOL_RECT, TOOL_POLY], variable=self.tool,
                               command=self._on_tool, font=ctk.CTkFont("Segoe UI", 12)).pack(side="left", padx=(6, 14))
        ctk.CTkSegmentedButton(tools, values=[SEL_OUT, SEL_IN], variable=self.sel_action,
                               selected_color="#F8D7D3", selected_hover_color="#F1C0BA",
                               command=lambda v: self._draw_sel_shape(), font=ctk.CTkFont("Segoe UI", 12)).pack(
            side="left", padx=(0, 14))
        ctk.CTkSegmentedButton(tools, values=[MODE_FULL, MODE_TOUCH], variable=self.sel_mode,
                               font=ctk.CTkFont("Segoe UI", 12)).pack(side="left")
        self.canvas = tk.Canvas(right, bg=CANVAS_BG, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True, padx=14, pady=(0, 6))
        self._canvas_hint()
        self.hint_lbl = ctk.CTkLabel(right, text=PREVIEW_HINT, text_color=MUTED, anchor="w",
                                     font=ctk.CTkFont("Segoe UI", 11))
        self.hint_lbl.pack(fill="x", padx=16)

        foot = ctk.CTkFrame(right, fg_color="transparent")
        foot.pack(fill="x", padx=14, pady=(0, 10))
        self.coord_lbl = ctk.CTkLabel(foot, text="Dublu-click = potrivește desenul în fereastră",
                                      text_color=MUTED, font=ctk.CTkFont("Consolas", 12))
        self.coord_lbl.pack(side="left")
        legend = ctk.CTkFrame(foot, fg_color="transparent")
        legend.pack(side="right")
        for _, label, col in CATEGORIES:
            ctk.CTkLabel(legend, text="■", text_color=col).pack(side="left")
            ctk.CTkLabel(legend, text=label.split(" /")[0], text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11)).pack(
                side="left", padx=(2, 8))
        ctk.CTkLabel(legend, text="■", text_color=DIM).pack(side="left")
        ctk.CTkLabel(legend, text="neexportat", text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11)).pack(
            side="left", padx=(2, 10))
        ctk.CTkLabel(legend, text="■", text_color=EXCLUDED_COL).pack(side="left")
        ctk.CTkLabel(legend, text="exclus", text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11)).pack(
            side="left", padx=(2, 0))

        c = self.canvas
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<ButtonPress-1>", self._pan_start)
        c.bind("<B1-Motion>", self._pan_move)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._double_click)
        c.bind("<Button-3>", lambda e: self._finish_poly(e) if self.tool.get() == TOOL_POLY else None)
        c.bind("<ButtonPress-2>", self._mid_start)
        c.bind("<B2-Motion>", self._mid_move)
        self.bind("<Return>", self._on_key)
        self.bind("<Escape>", self._on_key)
        c.bind("<Motion>", self._on_motion)
        self.bind("<Control-e>", lambda e: self._export() if self.features else None)
        c.bind("<Configure>", self._on_resize)
        c.bind("<ButtonRelease-2>", lambda e: self._schedule_redraw(60))

        # Footer
        ft = ctk.CTkFrame(self, fg_color="#EAF0F5", corner_radius=0, height=28)
        ft.pack(fill="x", side="bottom")
        ctk.CTkLabel(ft, text=f"{APP_NAME}  ·  parte din {TOPOKIT}  ·  Stereo 70 → ETRS89 · TransDatRO (ANCPI) cu grilă",
                     text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11)).pack()

    def _draw_header(self, e=None):
        """Antetul in stilul ferestrei TopoKit: banda bleumarin cu curbe de nivel, sigla,
        numele programului, versiunea TopoKit si butonul Ajutor."""
        c = self.header
        w, h = max(c.winfo_width(), 400), 88
        c.delete("all")
        if getattr(self, "_head_w", None) != w:
            self._head_w = w
            self._head_tk = ImageTk.PhotoImage(_topokit_band(w, h))
        c.create_image(0, 0, anchor="nw", image=self._head_tk)
        if not hasattr(self, "_logo_tk"):
            try:
                self._logo_tk = ImageTk.PhotoImage(Image.open(asset("topokit_logo.png")).resize((52, 52), Image.LANCZOS))
            except Exception:
                self._logo_tk = None
        if self._logo_tk:
            c.create_image(18, 18, anchor="nw", image=self._logo_tk)
        c.create_text(84, 36, anchor="w", text=APP_NAME, fill="#FFFFFF", font=("Segoe UI", 22, "bold"))
        c.create_text(85, 63, anchor="w", fill="#CFE3EF", font=("Segoe UI", 11),
                      text="Modul TopoKit  ·  Stereo 70  →  KMZ pentru Google Earth  ·  transformare TransDatRO (ANCPI)")
        x1 = w - 20
        _round_rect(c, x1 - 118, 30, x1, 58, 14, fill="#2C5A78", outline="")
        c.create_text(x1 - 59, 44, text=TOPOKIT, fill="#FFFFFF", font=("Segoe UI", 11, "bold"))
        hb = _round_rect(c, x1 - 226, 28, x1 - 130, 60, 10, fill="#FFFFFF", outline="", tags="help")
        c.create_text(x1 - 178, 44, text="❓ Ajutor", fill=NAVY, font=("Segoe UI", 11, "bold"), tags="help")
        c.tag_bind("help", "<Button-1>", lambda e: self._open_help())
        c.tag_bind("help", "<Enter>", lambda e: (c.itemconfigure(hb, fill="#E3EEF6"), c.configure(cursor="hand2")))
        c.tag_bind("help", "<Leave>", lambda e: (c.itemconfigure(hb, fill="#FFFFFF"), c.configure(cursor="")))

    def _draw_bg(self):
        """Fundal cu curbe de nivel (fix, nu se misca la zoom / mutare)."""
        c = self.canvas
        if not hasattr(self, "_topo_tk"):
            try:
                self._topo_tk = tk.PhotoImage(file=asset("topo_bg.png"))
            except Exception:
                self._topo_tk = None
        if self._topo_tk is None:
            return
        W, H = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        iw, ih = self._topo_tk.width(), self._topo_tk.height()
        for x in range(0, W, iw):
            for y in range(0, H, ih):
                c.create_image(x, y, anchor="nw", image=self._topo_tk, tags="bg")
        c.tag_lower("bg")

    def _draw_overlay(self):
        """Sageata Nordului si scara grafica, ca pe o harta."""
        c = self.canvas
        c.delete("overlay")
        if not self.view:
            return
        W, H = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        # nordul (axa Nord a proiectiei Stereo 70)
        nx, ny = W - 34, 26
        _round_rect(c, nx - 20, ny - 18, nx + 20, ny + 46, 10, fill="#FFFFFF", outline="#C9D6E2", tags="overlay")
        c.create_polygon(nx, ny - 8, nx - 9, ny + 22, nx, ny + 16, fill=TEXT, outline="", tags="overlay")
        c.create_polygon(nx, ny - 8, nx + 9, ny + 22, nx, ny + 16, fill="#9AA5B1", outline="", tags="overlay")
        c.create_text(nx, ny + 34, text="N", fill=AMBER, font=("Segoe UI", 11, "bold"), tags="overlay")
        # scara grafica: 1-2-5 x 10^k, intre ~70 si ~170 px
        S = self.view[0]
        target = 120 / S
        k = 10 ** math.floor(math.log10(target))
        L = min((m * k for m in (1, 2, 5, 10)), key=lambda v: abs(v - target))
        px = L * S
        x0, y0 = 18, H - 22
        _round_rect(c, x0 - 8, y0 - 26, x0 + px + 52, y0 + 12, 8, fill="#FFFFFF", outline="#C9D6E2", tags="overlay")
        for j in range(4):
            c.create_rectangle(x0 + px * j / 4, y0 - 4, x0 + px * (j + 1) / 4, y0 + 2,
                               fill=TEXT if j % 2 == 0 else "#FFFFFF", outline=TEXT, tags="overlay")
        txt = f"{L / 1000:g} km" if L >= 1000 else f"{L:g} m"
        c.create_text(x0 + px + 8, y0 - 1, anchor="w", text=txt, fill=TEXT, font=("Segoe UI", 10, "bold"),
                      tags="overlay")
        c.create_text(x0, y0 - 16, anchor="w", text="Stereo 70", fill=MUTED, font=("Segoe UI", 9), tags="overlay")

    def _canvas_hint(self):
        self.canvas.delete("all")
        self.canvas.update_idletasks()
        self._draw_bg()
        w = max(self.canvas.winfo_width(), 600)
        h = max(self.canvas.winfo_height(), 400)
        if not hasattr(self, "_hint_tk"):
            try:
                self._hint_tk = ImageTk.PhotoImage(Image.open(asset("dwg2kmz_icon.png")).resize((60, 60), Image.LANCZOS))
            except Exception:
                self._hint_tk = None
        if self._hint_tk:
            self.canvas.create_image(w / 2, h / 2 - 46, image=self._hint_tk)
        self.canvas.create_text(w / 2, h / 2 + 4, text="Încarcă un desen DXF sau DWG", fill=TEXT,
                                font=("Segoe UI", 17, "bold"))
        self.canvas.create_text(w / 2, h / 2 + 32, text="trage fișierul în fereastră sau apasă pe zona din stânga",
                                fill=MUTED, font=("Segoe UI", 12))

    # ---------- incarcare ----------
    def _browse_dxf(self):
        p = filedialog.askopenfilename(title="Alege fișierul DXF sau DWG",
                                       filetypes=[("Desene CAD", "*.dxf *.dwg"), ("Fișiere DXF", "*.dxf"),
                                                  ("Fișiere DWG", "*.dwg"), ("Toate fișierele", "*.*")])
        if p:
            self._load(p)

    def _on_drop(self, event):
        files = self.tk.splitlist(event.data)
        for f in files:
            if f.lower().endswith((".dxf", ".dwg")):
                self._load(f)
                return
        messagebox.showwarning(APP_NAME, "Te rog trage un fișier .dxf sau .dwg")

    def _browse_out(self):
        d = filedialog.askdirectory(title="Alege folderul unde se salvează KMZ-ul",
                                    initialdir=self.out_dir.get() or None)
        if d:
            self.out_dir.set(d)

    def _load(self, path):
        self._set_status(f"Se citește {os.path.basename(path)} …")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self._export_state("disabled")

        def work():
            feats, layers, skipped = read_dxf(path)
            return path, feats, layers, skipped, detect_swap(feats)

        self._run_bg(work, lambda r: self._loaded(*r), self._load_failed)

    def _run_bg(self, work, on_ok, on_err):
        """Ruleaza work() in fundal; rezultatul ajunge in interfata doar din firul principal."""
        q = queue.Queue()

        def runner():
            try:
                q.put((True, work()))
            except Exception as ex:
                q.put((False, ex))

        def poll():
            try:
                ok, res = q.get_nowait()
            except queue.Empty:
                self.after(50, poll)
                return
            (on_ok if ok else on_err)(res)

        threading.Thread(target=runner, daemon=True).start()
        self.after(50, poll)

    def _load_failed(self, ex):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self._set_status("Eroare la citire.")
        if isinstance(ex, dwg.DwgError) and not dwg.available():
            if messagebox.askyesno(APP_NAME, f"{ex}\n\nDeschid acum pagina de descărcare?"):
                webbrowser.open(dwg.ODA_DOWNLOAD_URL)
            return
        messagebox.showerror(APP_NAME, f"Nu am putut citi fișierul:\n{ex}")

    def _loaded(self, path, feats, layers, skipped, swap):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1)
        self.dxf_path = path
        self.features = feats
        self.excluded = set()
        self.layers = layers
        self.swap.set(swap)
        self.out_name.set(os.path.splitext(os.path.basename(path))[0])
        if not self.out_dir.get() or not os.path.isdir(self.out_dir.get()):
            self.out_dir.set(desktop_dir())

        self.drop_lbl.configure(text=f"✅  {os.path.basename(path)}\n\napasă sau trage alt fișier",
                                text_color=TEXT)
        counts = {k: sum(1 for f in feats if f.kind == k) for k, _, _ in CATEGORIES}
        for k, lbl in self.cat_checks.items():
            lbl.configure(text=str(counts[k]))
        info = f"{len(feats)} obiecte · {len(layers)} layere"
        if skipped:
            info += f" · {skipped} ignorate"
        if swap:
            info += "\n↻ Am detectat X = Nord, am inversat automat X/Y."
        self.file_info.configure(text=info)

        for w in self.layer_box.winfo_children():
            w.destroy()
        self.layer_vars = {}
        for lname in sorted(layers, key=str.lower):
            v = tk.BooleanVar(value=True)
            self.layer_vars[lname] = v
            n = sum(1 for f in feats if f.layer == lname)
            row = ctk.CTkFrame(self.layer_box, fg_color="transparent")
            row.pack(fill="x")
            ctk.CTkLabel(row, text="■", text_color="#%02x%02x%02x" % layers[lname], width=14).pack(side="left")
            ctk.CTkCheckBox(row, text=f"{lname}", variable=v, command=lambda n=lname: self._on_layer_toggle(n), checkbox_width=18,
                            checkbox_height=18, font=ctk.CTkFont("Segoe UI", 12)).pack(side="left", pady=1)
            ctk.CTkLabel(row, text=str(n), text_color=MUTED, font=ctk.CTkFont("Segoe UI", 11)).pack(
                side="right", padx=6)

        self._export_state("normal")
        for ms in (50, 600):
            self.after(ms, lambda: self.left_scroll._parent_canvas.yview_moveto(0))
        self._set_status("Fișier încărcat. Alege ce exporți și apasă EXPORTĂ.")
        self.view = None
        self._fit()

    # ---------- selectie ----------
    def _select_all(self, val):
        for v in self.cat_vars.values():
            v.set(val)
        for v in self.layer_vars.values():
            v.set(val)
        if val:
            self.excluded.clear()
        self._redraw()

    def _on_cat_toggle(self, key):
        # o categorie bifata fara niciun layer bifat n-ar exporta nimic -> bifam toate layerele
        if self.cat_vars[key].get() and self.layer_vars and not any(v.get() for v in self.layer_vars.values()):
            for v in self.layer_vars.values():
                v.set(True)
        self._redraw()

    def _on_layer_toggle(self, name):
        # la fel: un layer bifat fara nicio categorie bifata -> bifam toate categoriile
        if self.layer_vars[name].get() and not any(v.get() for v in self.cat_vars.values()):
            for v in self.cat_vars.values():
                v.set(True)
        self._redraw()

    def _on_swap(self):
        self.view = None
        self._fit()

    def selected(self):
        cats = {k for k, v in self.cat_vars.items() if v.get()}
        lays = {k for k, v in self.layer_vars.items() if v.get()}
        return [f for i, f in enumerate(self.features)
                if f.kind in cats and f.layer in lays and i not in self.excluded]

    # ---------- preview canvas ----------
    def _pt(self, x, y):
        if self.swap.get():
            x, y = y, x
        return x, y

    def _geo(self):
        """Geometria pregatita o singura data (X/Y inversate deja aplicate, bbox, arie)."""
        key = (id(self.features), len(self.features), self.swap.get())
        if getattr(self, "_geo_key", None) != key:
            swap = self.swap.get()
            geo = []
            for f in self.features:
                if f.kind == "polygon":
                    rings = f.geom
                elif f.kind in LINEAR:
                    rings = f.geom[:1]
                else:
                    rings = [f.geom[:1]]
                if swap:
                    rings = [[(y, x) for x, y in r] for r in rings]
                xs = [p[0] for r in rings for p in r]
                ys = [p[1] for r in rings for p in r]
                bb = (min(xs), min(ys), max(xs), max(ys))
                area = abs(_ring_area(rings[0])) if f.kind == "polygon" else 0.0
                geo.append((rings, bb, area))
            self._geo_cache = geo
            self._geo_key = key
        return self._geo_cache

    def _active_sets(self):
        return ({k for k, v in self.cat_vars.items() if v.get()},
                {k for k, v in self.layer_vars.items() if v.get()})

    def _bbox(self):
        geo = self._geo()
        if not geo:
            return None
        return (min(g[1][0] for g in geo), min(g[1][1] for g in geo),
                max(g[1][2] for g in geo), max(g[1][3] for g in geo))

    def _fit(self):
        if not self.features:
            return
        bb = self._bbox()
        if not bb:
            return
        w = max(self.canvas.winfo_width(), 100)
        h = max(self.canvas.winfo_height(), 100)
        dx = max(bb[2] - bb[0], 1e-3)
        dy = max(bb[3] - bb[1], 1e-3)
        S = min((w - 60) / dx, (h - 60) / dy)
        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        self.view = [S, cx - (w / 2) / S, cy + (h / 2) / S]
        self._user_view = False
        self._redraw()

    def _w2s(self, x, y):
        S, X0, Y0 = self.view
        return (x - X0) * S, (Y0 - y) * S

    def _active(self, i, sets=None):
        """Obiectul i are categoria si layerul bifate (indiferent de excluderea manuala)."""
        cats, lays = sets or self._active_sets()
        f = self.features[i]
        return f.kind in cats and f.layer in lays

    def _schedule_redraw(self, ms=160):
        """Redesenare completa o singura data, dupa ce utilizatorul se opreste din zoom / mutare."""
        job = getattr(self, "_redraw_job", None)
        if job:
            self.after_cancel(job)
        self._redraw_job = self.after(ms, self._redraw)

    def _redraw(self):
        self._redraw_job = None
        c = self.canvas
        c.delete("all")
        self._item_feat = {}
        if not self.features or not self.view:
            self._canvas_hint()
            return
        self._draw_bg()
        geo = self._geo()
        feats = self.features
        S, X0, Y0 = self.view
        W = max(c.winfo_width(), 100)
        H = max(c.winfo_height(), 100)
        # desenam doar ce se vede (+ o margine, ca mutarea sa nu arate goluri)
        m = max(W, H) * 0.6
        vx0, vx1 = X0 - m / S, X0 + (W + m) / S
        vy0, vy1 = Y0 - (H + m) / S, Y0 + m / S
        cats, lays = self._active_sets()
        active = [f.kind in cats and f.layer in lays for f in feats]
        excluded = self.excluded
        cat_col = {k: col for k, _, col in CATEGORIES}
        dim = DIM
        rank = {"polygon": 0, "polyline": 1, "line": 1, "text": 2, "point": 3}
        visible = [i for i, (_, bb, _) in enumerate(geo)
                   if not (bb[2] < vx0 or bb[0] > vx1 or bb[3] < vy0 or bb[1] > vy1)]
        # in spate: neexportate, apoi excluse, apoi cele exportate; obiectele mici deasupra celor mari
        visible.sort(key=lambda i: (active[i], i not in excluded, rank[feats[i].kind]))
        n_texts = sum(1 for i in visible if feats[i].kind == "text" and active[i])
        texts_as_marks = n_texts > 350
        labels = self.show_labels.get() and sum(1 for i in visible if feats[i].kind == "point") < 400
        create_line, create_poly = c.create_line, c.create_polygon
        item_feat = self._item_feat
        for i in visible:
            f = feats[i]
            on = active[i]
            excl = on and i in excluded
            col = dim if not on else (EXCLUDED_COL if excl else cat_col[f.kind])
            tag = (f"f{i}", "geo")
            rings = geo[i][0]
            if f.kind == "polygon" or f.kind in LINEAR:
                for ring in rings:
                    flat = []
                    lx = ly = None
                    for x, y in ring:                   # sarim varfurile mai apropiate de 1 pixel
                        sx = (x - X0) * S
                        sy = (Y0 - y) * S
                        if lx is None or abs(sx - lx) + abs(sy - ly) >= 1.0:
                            flat.append(sx)
                            flat.append(sy)
                            lx, ly = sx, sy
                    if len(flat) < 4:
                        flat = [lx, ly, lx + 1, ly]
                    if f.kind == "polygon" and len(flat) >= 6:
                        it = create_poly(flat, outline=col, fill="", width=2 if on else 1,
                                         dash=(4, 3) if excl else None, tags=tag)
                    else:
                        it = create_line(flat, fill=col, width=2 if on else 1,
                                         dash=(4, 3) if excl else None, tags=tag)
                    item_feat[it] = i
            else:
                x, y = rings[0][0]
                sx, sy = (x - X0) * S, (Y0 - y) * S
                if f.kind == "point":
                    item_feat[c.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, fill=col, outline="", tags=tag)] = i
                    if on and not excl and labels:
                        item_feat[c.create_text(sx + 6, sy - 6, text=f.name[:20], fill="#5B3A00", anchor="w",
                                                font=("Segoe UI", 8), tags=tag)] = i
                elif texts_as_marks or not on:
                    item_feat[c.create_rectangle(sx - 2, sy - 2, sx + 2, sy + 2, outline=col, tags=tag)] = i
                else:
                    item_feat[c.create_text(sx, sy, text=("▦ " if f.table else "") + f.name[:30],
                                            fill=col, anchor="sw", font=("Segoe UI", 9), tags=tag)] = i
        self._draw_sel_shape()
        self._draw_overlay()
        n_sel = sum(1 for i, a in enumerate(active) if a and i not in excluded)
        msg = f"Previzualizare: {n_sel} din {len(feats)} obiecte vor fi exportate."
        if excluded:
            msg += f"\n{len(excluded)} excluse manual din previzualizare."
        self._set_status(msg)

    # ---------- selectie din previzualizare ----------
    def _hit(self, x, y):
        """Obiectul exportabil de sub mouse (cel mai mic / cel de deasupra)."""
        sets = self._active_sets()
        cands = {self._item_feat[it] for it in self.canvas.find_overlapping(x - 4, y - 4, x + 4, y + 4)
                 if it in self._item_feat}
        cands = [i for i in cands if self._active(i, sets)]
        geo = self._geo()
        if not cands and self.view:
            # click in interiorul unui poligon (poligoanele sunt desenate fara umplere)
            wx, wy = self._s2w(x, y)
            for i, (rings, bb, _) in enumerate(geo):
                if (self.features[i].kind == "polygon" and bb[0] <= wx <= bb[2] and bb[1] <= wy <= bb[3]
                        and self._active(i, sets) and _point_in_poly((wx, wy), rings[0])
                        and not any(_point_in_poly((wx, wy), r) for r in rings[1:])):
                    cands.append(i)
        if not cands:
            return None
        rank = {"point": 0, "text": 1, "polyline": 2, "line": 2, "polygon": 3}

        def size(i):
            bb = geo[i][1]
            return (bb[2] - bb[0]) * (bb[3] - bb[1])

        return min(cands, key=lambda i: (rank[self.features[i].kind], size(i)))

    def _toggle(self, i):
        if i in self.excluded:
            self.excluded.discard(i)
        else:
            self.excluded.add(i)
        self._redraw()

    def _include_all(self):
        if self.excluded:
            self.excluded.clear()
            self._redraw()

    def _on_wheel(self, e):
        if not self.view:
            return
        f = 1.25 if e.delta > 0 else 1 / 1.25
        S, X0, Y0 = self.view
        X0 = X0 - e.x * (1 - f) / (f * S)
        Y0 = Y0 + e.y * (1 - f) / (f * S)
        self.view = [S * f, X0, Y0]
        self._user_view = True
        # zoom instant: scalam ce e deja desenat, apoi redesenam o singura data cand te opresti
        self.canvas.scale("geo", e.x, e.y, f, f)
        self.canvas.scale("sel", e.x, e.y, f, f)
        self._draw_overlay()
        self._schedule_redraw()

    # ---------- mouse in previzualizare: click / dreptunghi / poligon ----------
    def _s2w(self, sx, sy):
        S, X0, Y0 = self.view
        return sx / S + X0, Y0 - sy / S

    def _action_out(self, e=None):
        """True = scoate din export, False = pune inapoi (Shift/Ctrl au prioritate)."""
        if e is not None and e.state & 0x0001:
            return True
        if e is not None and e.state & 0x0004:
            return False
        return self.sel_action.get() == SEL_OUT

    def _pan(self, dx, dy):
        self._user_view = True
        self.canvas.move("geo", dx, dy)
        self.canvas.move("sel", dx, dy)
        S = self.view[0]
        self.view[1] -= dx / S
        self.view[2] += dy / S

    def _pan_start(self, e):
        self._last = (e.x, e.y)
        self._press = (e.x, e.y)
        self._dragged = False
        self._box_mode = None
        if not self.view:
            return
        tool = self.tool.get()
        if tool == TOOL_POLY:
            self._poly_world.append(self._s2w(e.x, e.y))
            self._draw_sel_shape(e.x, e.y)
            return
        if tool == TOOL_RECT or e.state & 0x0005:            # dreptunghi (sau Shift/Ctrl + trage)
            self._box_mode = "out" if self._action_out(e) else "in"
            col = EXCLUDED_COL if self._box_mode == "out" else OK_COL
            self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline=col, dash=(4, 3), width=2, tags="sel")

    def _pan_move(self, e):
        if not self.view or self.tool.get() == TOOL_POLY:
            return
        if self._box_mode:
            self.canvas.coords("sel", self._press[0], self._press[1], e.x, e.y)
            return
        if not self._dragged and math.dist(self._press, (e.x, e.y)) < 4:
            return
        self._dragged = True
        self._pan(e.x - self._last[0], e.y - self._last[1])
        self._last = (e.x, e.y)

    def _release(self, e):
        if not self.view or not self.features or self.tool.get() == TOOL_POLY:
            return
        if self._box_mode:
            x0, y0 = self._press
            out = self._box_mode == "out"
            self._box_mode = None
            self.canvas.delete("sel")
            if math.dist((x0, y0), (e.x, e.y)) < 4:
                return
            corners = [self._s2w(x0, y0), self._s2w(e.x, y0), self._s2w(e.x, e.y), self._s2w(x0, e.y)]
            self._apply_shape(corners, out)
        elif not self._dragged:
            i = self._hit(e.x, e.y)
            if i is not None:
                self._toggle(i)
        else:
            self._schedule_redraw(60)       # completam ce a intrat in ecran dupa mutare

    def _mid_start(self, e):
        self._mlast = (e.x, e.y)

    def _mid_move(self, e):
        if self.view:
            self._pan(e.x - self._mlast[0], e.y - self._mlast[1])
            self._mlast = (e.x, e.y)

    def _on_resize(self, e):
        if not self.features:
            return
        if self.view is None or not getattr(self, "_user_view", False):
            self._fit()                    # inca nu ai facut zoom / mutare -> reincadram desenul
        else:
            self._schedule_redraw(120)

    def _double_click(self, e):
        if self.tool.get() == TOOL_POLY:
            self._finish_poly()
        else:
            self._fit()

    def _finish_poly(self, e=None):
        pts = []
        for p in self._poly_world:          # fara puncte dublate (dublu-click)
            if not pts or math.dist(p, pts[-1]) * self.view[0] > 3:
                pts.append(p)
        self._poly_world = []
        self.canvas.delete("sel")
        if len(pts) >= 3:
            self._apply_shape(pts, self._action_out(e))
        elif pts:
            self._set_status("Poligonul de selecție are nevoie de cel puțin 3 puncte.")

    def _cancel_poly(self, e=None):
        self._poly_world = []
        self.canvas.delete("sel")

    def _draw_sel_shape(self, mx=None, my=None):
        """Deseneaza poligonul de selectie in lucru (+ linia elastica pana la mouse)."""
        self.canvas.delete("sel")
        if not self._poly_world or not self.view:
            return
        col = EXCLUDED_COL if self._action_out() else OK_COL
        flat = []
        for p in self._poly_world:
            flat.extend(self._w2s(*p))
        if mx is not None:
            flat.extend((mx, my))
            flat.extend(flat[:2])
        if len(flat) >= 4:
            self.canvas.create_line(flat, fill=col, width=2, dash=(4, 3), tags="sel")
        for k in range(0, 2 * len(self._poly_world), 2):
            x, y = flat[k], flat[k + 1]
            self.canvas.create_rectangle(x - 3, y - 3, x + 3, y + 3, outline=col, fill=CANVAS_BG, tags="sel")

    def _feat_points(self, i):
        return [p for r in self._geo()[i][0] for p in r]

    def _apply_shape(self, shape, out):
        """Scoate / pune inapoi obiectele din forma de selectie (coordonate Stereo 70)."""
        crossing = self.sel_mode.get() == MODE_TOUCH
        sx = [p[0] for p in shape]
        sy = [p[1] for p in shape]
        sbb = (min(sx), min(sy), max(sx), max(sy))
        hit = set()
        sets = self._active_sets()
        for i in range(len(self.features)):
            if not self._active(i, sets):
                continue
            pts = self._feat_points(i)
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if max(xs) < sbb[0] or min(xs) > sbb[2] or max(ys) < sbb[1] or min(ys) > sbb[3]:
                continue
            if not crossing:
                if all(_point_in_poly(p, shape) for p in pts):
                    hit.add(i)
            elif self._touches(i, pts, shape):
                hit.add(i)
        if out:
            self.excluded |= hit
        else:
            self.excluded -= hit
        self._redraw()
        verb = "scoase din" if out else "puse înapoi la"
        self.hint_lbl.configure(text=f"✔ {len(hit)} obiecte {verb} export.", text_color=OK_COL)

    def _touches(self, i, pts, shape):
        if any(_point_in_poly(p, shape) for p in pts):
            return True
        f = self.features[i]
        if len(pts) > 1:
            segs = list(zip(pts, pts[1:]))
            edges = list(zip(shape, shape[1:] + shape[:1]))
            if any(_seg_cross(a, b, c, d) for a, b in segs for c, d in edges):
                return True
        # zona de selectie complet in interiorul unui poligon
        return f.kind == "polygon" and _point_in_poly(shape[0], self._geo()[i][0][0])

    def _on_key(self, e):
        if self.tool.get() == TOOL_POLY:
            if e.keysym in ("Return", "KP_Enter"):
                self._finish_poly()
            elif e.keysym == "Escape":
                self._cancel_poly()

    def _on_tool(self, _value=None):
        self._cancel_poly()
        tool = self.tool.get()
        self.canvas.configure(cursor="crosshair" if tool == TOOL_CLICK else "tcross")
        self.hint_lbl.configure(text=self._hint(), text_color=MUTED)

    def _hint(self):
        tool = self.tool.get()
        if tool == TOOL_RECT:
            return "▭  Trage un dreptunghi peste obiecte   ·   butonul din mijloc = mută   ·   rotița = zoom"
        if tool == TOOL_POLY:
            return ("⬠  Click = adaugă colț   ·   dublu-click / click dreapta / Enter = închide poligonul   ·   "
                    "Esc = anulează   ·   butonul din mijloc = mută")
        return PREVIEW_HINT

    def _on_motion(self, e):
        if not self.view:
            return
        S, X0, Y0 = self.view
        x, y = e.x / S + X0, Y0 - e.y / S
        try:
            lon, lat = stereo70_to_etrs89(x, y)
        except (OutsideGrid, ValueError):
            lon, lat = _TR.transform(x, y)
        txt = f"X {y:,.2f}  Y {x:,.2f}  |  {lat:.6f}N {lon:.6f}E"
        tool = self.tool.get()
        if tool == TOOL_POLY and self._poly_world:
            self._draw_sel_shape(e.x, e.y)
        i = self._hit(e.x, e.y) if self._item_feat and tool == TOOL_CLICK else None
        if i is not None:
            f = self.features[i]
            if i in self.excluded:
                hint, col = "❌ EXCLUS – click pentru a-l pune înapoi la export", EXCLUDED_COL
            else:
                hint, col = "✔ se exportă – click pentru a-l scoate", OK_COL
            self.hint_lbl.configure(text=f"▸ {CAT_LABEL[f.kind]}: {f.name[:40]}   [layer: {f.layer[:30]}]   ·   {hint}",
                                    text_color=col)
            self.canvas.configure(cursor="hand2")
        elif tool == TOOL_CLICK:
            if self.hint_lbl.cget("text").startswith("▸"):
                self.hint_lbl.configure(text=self._hint(), text_color=MUTED)
            self.canvas.configure(cursor="crosshair")
        self.coord_lbl.configure(text=txt)

    # ---------- map preview ----------
    def _map_preview(self):
        feats = self.selected()
        if not feats:
            messagebox.showinfo(APP_NAME, "Nu e nimic selectat pentru previzualizare.")
            return
        gj = build_geojson(feats, self.swap.get())
        title = html.escape(os.path.basename(self.dxf_path or ""))
        page = MAP_HTML.replace("__DATA__", json.dumps(gj)).replace("__TITLE__", title)
        p = os.path.join(tempfile.gettempdir(), "dwg2kmz_preview.html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(page)
        webbrowser.open("file:///" + p.replace("\\", "/"))

    # ---------- export ----------
    def _export(self):
        if not tklic.gate():
            return
        feats = self.selected()
        if not feats:
            messagebox.showwarning(APP_NAME, "Selectează cel puțin o categorie și un layer.")
            return
        out_dir = self.out_dir.get().strip()
        if not out_dir:
            self._browse_out()
            out_dir = self.out_dir.get().strip()
        if not out_dir:
            return
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as ex:
            messagebox.showerror(APP_NAME, f"Nu pot folosi folderul:\n{out_dir}\n\n{ex}")
            return
        name = (self.out_name.get().strip() or "export").removesuffix(".kmz")
        name = "".join("_" if c in '\\/:*?"<>|' else c for c in name).strip(" .") or "export"
        target = os.path.join(out_dir, name + ".kmz")
        if os.path.exists(target) and not messagebox.askyesno(
                APP_NAME, f"Fișierul există deja:\n{target}\n\nÎl suprascriu?"):
            return
        opts = {"fill_alpha": int(self.fill_alpha.get() * 2.55), "line_width": 2,
                "coord_table": self.coord_table.get(), "show_labels": self.show_labels.get()}
        swap = self.swap.get()
        self._export_state("disabled", "Se exportă …")
        self.progress.configure(mode="indeterminate")
        self.progress.start()

        def work():
            FALLBACK_COUNT[0] = 0
            save_kmz(target, build_kml(feats, name, swap, opts))
            return FALLBACK_COUNT[0]

        self._run_bg(work, lambda fb: self._exported(target, len(feats), fb), self._export_failed)

    def _export_done_ui(self):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self._export_state("normal")

    def _exported(self, target, n, fallback=0):
        self._export_done_ui()
        self.progress.set(1)
        self._set_status(f"✅ Exportat {n} obiecte în:\n{target}")
        if self.open_after.get():
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            except Exception:
                pass
        msg = f"Gata! Am creat KMZ-ul cu {n} obiecte:\n\n{target}\n\nTransformare: TransDatRO (ANCPI) cu grilă."
        if fallback:
            msg += (f"\n\nAtenție: {fallback} vârfuri sunt în afara grilei TransDatRO (la graniță sau în afara "
                    "țării) și au fost transformate cu Helmert 7 parametri (precizie ~0.5 m).")
        messagebox.showinfo(APP_NAME, msg)

    def _export_failed(self, ex):
        self._export_done_ui()
        self.progress.set(0)
        self._set_status("Eroare la export.")
        messagebox.showerror(APP_NAME, f"Exportul a eșuat:\n{ex}")

    def _export_state(self, state, text="⬇  EXPORTĂ KMZ"):
        self.export_btn.configure(state=state, text=text)

    def _update_dest(self):
        d = self.out_dir.get().strip()
        if os.path.normcase(os.path.normpath(d)) == os.path.normcase(os.path.normpath(desktop_dir())):
            shown = "Desktop"
        else:
            shown = d if len(d) <= 42 else "…" + d[-41:]
        self.dest_lbl.configure(text=f"📍 Se salvează în:  {shown}")

    def _set_status(self, txt):
        self.status.configure(text=txt)


def open_help():
    """Deschide instructiunile (fisierul de langa program sau cel inclus in exe)."""
    bases = [os.path.dirname(os.path.abspath(sys.executable)), getattr(sys, "_MEIPASS", None),
             os.path.dirname(os.path.abspath(__file__))]
    for base in bases:
        if base:
            p = os.path.join(base, HELP_FILE)
            if os.path.isfile(p):
                os.startfile(p)
                return True
    return False


def main():
    theme = asset("topokit.json")
    if theme:
        ctk.set_default_color_theme(theme)
    if "--ajutor" in sys.argv:          # ghidul programului
        open_help()
        return
    if not tklic.gate():
        return
    app = App()
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith((".dxf", ".dwg")):
        app.after(300, lambda: app._load(sys.argv[1]))
    app.mainloop()


if __name__ == "__main__":
    main()
