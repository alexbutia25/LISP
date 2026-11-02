# -*- coding: utf-8 -*-
"""
Plan Inclinare - planuri de verticalitate / inclinare (silozuri, stalpi, cosuri, turnuri)
din puncte masurate pe randuri (ex. cod "stanga" si cod "dreapta").

- Fiecare rand are verticala lui de referinta (linia verde), dusa prin punctul cel mai de jos al randului.
- Linia rosie uneste punctele masurate (pozitia reala); linia gri = abaterea pe orizontala, cu valoarea scrisa.
- Planul se pune pe format A4...A0 la scara 1:100...1:2000, ales manual sau automat (autofit), cu cartus.
- Puncte din CSV/TXT, din clipboard, sau direct din DWG/DXF (puncte COGO Civil 3D si puncte AutoCAD).
- Drag & drop de fisiere in fereastra.
- Punctele din desenul deschis in AutoCAD / Civil 3D (butonul "Puncte din AutoCAD", prin TopoKit:
  comanda PLANINCLSEL cere selectia in desen si trimite punctele programului).
- Export DXF (direct) si DWG (prin AutoCAD Core Console, fara sa deschida AutoCAD).

Doar biblioteca standard Python. Rulare: python plan_inclinare.py [fisier_puncte]
"""
import datetime
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import tklic

# ca .exe setarile si PlanInclinareCogo.dll stau langa executabil: PyInstaller (sys.frozen) -> folderul
# exe-ului; Nuitka standalone -> __file__ e in folderul exe-ului (PlanInclinare.dist), la fel ca din sursa
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
CONFIG_FILE = os.path.join(APP_DIR, "setari_plan_inclinare.json")
COGO_DLL = os.path.join(APP_DIR, "PlanInclinareCogo.dll")

FORMATE = {"A4": (210, 297), "A3": (297, 420), "A2": (420, 594), "A1": (594, 841), "A0": (841, 1189)}
SCARI = [100, 200, 500, 1000, 2000]
MARGINE_STANGA, MARGINE = 20.0, 10.0      # mm, chenar plansa
CARTUS_L, CARTUS_H = 120.0, 30.0          # mm
# latimea unui caracter / inaltimea textului (fontul Standard din AutoCAD ajunge la ~0.98)
TEXT_W = 1.0
PUNCTE_EXT = (".csv", ".txt", ".pnt", ".dat", ".xyz")
CAD_EXT = (".dwg", ".dxf")

DEFAULT_CONFIG = {
    # --- citire fisier puncte ---
    "coloane": "N,X,Y,Z,COD",
    "separator": "auto",
    "potrivire_cod": "incepe cu",
    # --- randuri ---
    "randuri": [
        {"cod": "stanga", "titlu": "PARTEA STANGA", "directie": "auto"},
        {"cod": "dreapta", "titlu": "PARTEA DREAPTA", "directie": "auto"},
    ],
    # --- calcul ---
    "tip_abatere": "totala",
    "exagerare": 1.0,
    "unitate": "cm",
    "zecimale": 1,
    # --- plansa ---
    "format": "auto",            # auto / fara / A4 ... A0
    "orientare": "auto",         # auto / portret / peisaj
    "scara": "auto",             # auto / 1:100 ... 1:2000
    "prioritate_autofit": "scara mare",   # scara mare / format mic
    "cartus": True,
    "beneficiar": "",
    "obiectiv": "",
    "intocmit": "",
    "plansa_nr": "1",
    # --- desen (marimi in mm pe hartie) ---
    "titlu_plan": "PLAN INCLINARE SILOZ",
    "text_mm": 1.8,
    "titlu_mm": 4.0,
    "raza_punct_mm": 0.35,
    "grosime_rosu_mm": 0.0,
    "spatiu_etichete_mm": 18.0,
    "distanta_randuri_mm": 15.0,
    "arata_H": True,
    "arata_cote_Z": False,
    "evita_suprapunere": True,
    "arata_legenda": True,
    "arata_rama": True,
    "culoare_verde": 3,
    "culoare_rosu": 1,
    "culoare_gri": 8,
    "culoare_text": 7,
    "strat": "PLAN_INCLINARE",
    # --- export ---
    "accoreconsole": "",
    "folder_export": "",
}

# punctele selectate in AutoCAD (scrise de comanda PLANINCLSEL din TopoKitInclinare.lsp)
ACAD_POINTS = os.path.join(tempfile.gettempdir(), "TopoKit_PlanInclinare_puncte.csv")


def topokit_exe():
    """Lansatorul TopoKit.exe (folderul de instalare din registru sau folderul parinte)."""
    cands = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\TopoKit") as k:
            cands.append(os.path.join(winreg.QueryValueEx(k, "InstallDir")[0], "TopoKit.exe"))
    except OSError:
        pass
    cands.append(os.path.join(os.path.dirname(APP_DIR), "TopoKit.exe"))
    return next((c for c in cands if os.path.exists(c)), "")


ACI_RGB = {1: "#ff3030", 2: "#ffff40", 3: "#30d030", 4: "#40ffff", 5: "#4060ff", 6: "#ff40ff",
           7: "#ffffff", 8: "#909090", 9: "#c0c0c0"}


# ============================================================================ utilitare
def ascii_text(s):
    s = str(s)
    for a, b in (("ș", "s"), ("ş", "s"), ("Ș", "S"), ("Ş", "S"), ("ț", "t"), ("ţ", "t"), ("Ț", "T"), ("Ţ", "T")):
        s = s.replace(a, b)
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def load_config(path=CONFIG_FILE):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULT_CONFIG})
        except Exception:
            pass
    return cfg


def find_accoreconsole():
    cands = []
    for drive in "CDEFG":
        for base in (rf"{drive}:\Program Files\Autodesk", rf"{drive}:\autocad", rf"{drive}:\Autodesk"):
            if os.path.isdir(base):
                try:
                    subdirs = os.listdir(base)
                except OSError:
                    continue
                for d in subdirs:
                    p = os.path.join(base, d, "accoreconsole.exe")
                    if os.path.exists(p):
                        cands.append(p)
    cands.sort(reverse=True)
    return cands[0] if cands else ""


def read_text_file(path):
    for enc in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            with open(path, encoding=enc) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
    return ""


# ============================================================================ citire puncte
def parse_points(text, cfg, cols=None, sep=None):
    cols = [c.strip().upper() for c in (cols or cfg["coloane"]).split(",")]
    sep = sep or cfg["separator"]
    pts = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if sep == "auto":
            if ";" in line:
                parts = line.split(";")
            elif "\t" in line:
                parts = line.split("\t")
            elif "," in line:
                parts = line.split(",")
            else:
                parts = line.split()
        elif sep == "tab":
            parts = line.split("\t")
        elif sep == "spatiu":
            parts = line.split()
        else:
            parts = line.split(sep)
        parts = [p.strip() for p in parts]
        rec = {c: parts[i] for i, c in enumerate(cols) if i < len(parts)}
        try:
            num = lambda s: float(s.replace(",", "."))
            pts.append({"n": rec.get("N", ""), "x": num(rec["X"]), "y": num(rec["Y"]), "z": num(rec["Z"]),
                        "cod": rec.get("COD", "")})
        except (KeyError, ValueError):
            continue  # antet sau rand invalid
    return pts


def parse_dxf_points(path):
    """Puncte AutoCAD (POINT) dintr-un DXF, fara AutoCAD. Codul = stratul."""
    txt = read_text_file(path)
    lines = txt.splitlines()
    pts = []
    i, in_ent = 0, False
    cur = None
    while i + 1 < len(lines):
        code, val = lines[i].strip(), lines[i + 1].strip()
        i += 2
        if code == "0":
            if cur is not None and {"x", "y", "z"} <= cur.keys():
                pts.append({"n": f"P{len(pts) + 1}", "x": cur["x"], "y": cur["y"], "z": cur["z"], "cod": cur.get("cod", "")})
            cur = {} if (val == "POINT" and in_ent) else None
            if val == "SECTION":
                in_ent = False
            continue
        if code == "2" and val == "ENTITIES":
            in_ent = True
        if cur is not None:
            try:
                if code == "8":
                    cur["cod"] = val
                elif code == "10":
                    cur["x"] = float(val)
                elif code == "20":
                    cur["y"] = float(val)
                elif code == "30":
                    cur["z"] = float(val)
            except ValueError:
                pass
    return pts


def script_path(path):
    """Cale scrisa intr-un script .scr (citit de AutoCAD in codepage-ul ANSI): cu diacritice sau alte
    caractere ne-ASCII (ex. numele utilizatorului in %TEMP%) se foloseste numele scurt 8.3 al
    folderului existent. Fara nume scurt (dezactivat pe volum) -> RuntimeError cu un mesaj clar."""
    path = os.path.abspath(path)
    if path.isascii():
        return path
    folder, name = os.path.split(path)
    if os.path.exists(path):
        folder, name = path, ""
    short = folder
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(folder, buf, 1024):
                short = buf.value
        except Exception:
            pass
    out = os.path.join(short, name) if name else short
    if not out.isascii():
        raise RuntimeError(f"Calea conține caractere pe care AutoCAD Core Console nu le poate citi:\n{path}")
    return out


def import_cad(path, acc):
    """Citeste punctele COGO (Civil 3D) si punctele AutoCAD dintr-un DWG/DXF prin AutoCAD Core Console."""
    if not os.path.exists(COGO_DLL):
        raise RuntimeError("Lipseste PlanInclinareCogo.dll langa program.")
    tmp = tempfile.mkdtemp(prefix="planincl_")
    try:
        src = os.path.join(tmp, "sursa" + os.path.splitext(path)[1].lower())
        shutil.copy2(path, src)  # lucram pe o copie: fisierul original poate fi deschis in AutoCAD
        out = os.path.join(tmp, "puncte.txt")
        scr = os.path.join(tmp, "imp.scr")
        with open(scr, "w", encoding="ascii", newline="\r\n") as fh:
            fh.write('(setq *pi_sl* (getvar "SECURELOAD") *pi_fd* (getvar "FILEDIA"))\n')
            fh.write('(setvar "SECURELOAD" 0)\n(setvar "FILEDIA" 0)\n')
            fh.write(f'_.NETLOAD\n"{script_path(COGO_DLL)}"\n')
            fh.write(f"PLANINCL_EXPORTPUNCTE\n{script_path(out)}\n")
            fh.write('(setvar "SECURELOAD" *pi_sl*)\n(setvar "FILEDIA" *pi_fd*)\n')
            fh.write("_.QUIT\n_Y\n")
        r = subprocess.run([acc, "/i", src, "/s", scr, "/product", "C3D", "/l", "en-US"], cwd=tmp,
                           capture_output=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log = r.stdout.decode("utf-16-le", "ignore").replace("\x00", "") if r.stdout else ""
        if not os.path.exists(out):
            raise RuntimeError("AutoCAD nu a putut citi punctele.\n\n" + log[-1200:])
        return parse_points(read_text_file(out), {}, cols="N,X,Y,Z,COD", sep=";")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_points_from(path, cfg, acc):
    ext = os.path.splitext(path)[1].lower()
    if ext in CAD_EXT:
        if acc and os.path.exists(acc):
            return import_cad(path, acc)
        if ext == ".dxf":
            return parse_dxf_points(path)
        raise RuntimeError("Pentru DWG e nevoie de AutoCAD / Civil 3D (accoreconsole.exe). Alege-l in Setari.")
    return parse_points(read_text_file(path), cfg)


def match_code(cod, wanted, mode):
    """'wanted' poate contine mai multe coduri separate prin virgula: 'stanga, s_sina'."""
    a = str(cod).strip().lower()
    for b in str(wanted).split(","):
        b = b.strip().lower()
        if not b:
            continue
        if (mode == "exact" and a == b) or (mode == "contine" and b in a) or \
                (mode not in ("exact", "contine") and a.startswith(b)):
            return True
    return False


def guess_codes(codes):
    """Propune codul pentru stanga, dreapta si un eventual al treilea rand (ex. spate)."""
    left = right = third = ""
    for c in codes:
        l = c.lower()
        if "spate" in l or "back" in l:
            third = third or c
        elif l.startswith(("stanga", "stg", "st_", "s_", "s-", "left", "l_")):
            left = left or c
        elif l.startswith(("dreapta", "dr", "d_", "d-", "right", "r_")):
            right = right or c
    return left, right, third


# ============================================================================ calcul
def compute(points, cfg):
    msgs, rows = [], []
    for r in cfg["randuri"]:
        sel = [p for p in points if match_code(p["cod"], r["cod"], cfg["potrivire_cod"])]
        if len(sel) < 2:
            msgs.append(f"Randul '{r['cod']}': {len(sel)} puncte (minim 2) - ignorat.")
            continue
        sel.sort(key=lambda p: p["z"])
        rows.append({"cfg": r, "pts": sel, "base": sel[0]})  # baza = punctul cel mai de jos
    if not rows:
        return [], msgs

    axis = None  # axa rand stanga -> rand dreapta (prin punctele de baza)
    if len(rows) >= 2:
        b0, b1 = rows[0]["base"], rows[-1]["base"]
        dx, dy = b1["x"] - b0["x"], b1["y"] - b0["y"]
        L = math.hypot(dx, dy)
        if L > 1e-6:
            axis = (dx / L, dy / L)

    for row in rows:
        b = row["base"]
        data = []
        for p in row["pts"]:
            dx, dy = p["x"] - b["x"], p["y"] - b["y"]
            proj = (dx * axis[0] + dy * axis[1]) if axis else 0.0
            data.append({"p": p, "H": p["z"] - b["z"], "tot": math.hypot(dx, dy), "proj": proj})
        auto_sign = 1 if axis is None or sum(x["proj"] for x in data) >= 0 else -1
        d = row["cfg"].get("directie", "auto")
        sign = 1 if d == "dreapta" else (-1 if d == "stanga" else auto_sign)
        if d == "auto" and axis is None:
            msgs.append(f"Randul '{row['cfg']['cod']}': directia nu se poate deduce dintr-un singur rand - "
                        f"am pus 'dreapta'. Alege directia in Setari.")
        flip = sign * auto_sign
        for x in data:
            if cfg["tip_abatere"] == "proiectata" and axis is not None:
                x["val"], x["draw"] = abs(x["proj"]), x["proj"] * flip
            else:
                x["val"], x["draw"] = x["tot"], sign * x["tot"]
        row.update(data=data, sign=sign, top=data[-1])
    if cfg["tip_abatere"] == "proiectata" and axis is None:
        msgs.append("Abaterea proiectata cere doua randuri; am folosit abaterea totala.")
    return rows, msgs


def fmt_val(v, cfg):
    k = {"cm": 100.0, "mm": 1000.0, "m": 1.0}[cfg["unitate"]]
    return f"{v * k:.{int(cfg['zecimale'])}f} {cfg['unitate']}"


# ============================================================================ geometrie
class Geo:
    def __init__(self, items=None):
        self.items = items or []

    def line(self, a, b, color):
        self.items.append(("line", a, b, color))

    def pline(self, pts, color, width=0.0):
        self.items.append(("pline", pts, color, width))

    def circle(self, c, r, color):
        self.items.append(("circle", c, r, color))

    def text(self, p, s, h, color, just="L"):
        self.items.append(("text", p, s, h, color, just))

    def rect(self, x0, y0, x1, y1, color, width=0.0):
        self.pline([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], color, width)

    def moved(self, dx, dy):
        mv = lambda p: (p[0] + dx, p[1] + dy)
        out = []
        for it in self.items:
            k = it[0]
            if k == "line":
                out.append((k, mv(it[1]), mv(it[2]), it[3]))
            elif k == "pline":
                out.append((k, [mv(p) for p in it[1]], it[2], it[3]))
            elif k == "circle":
                out.append((k, mv(it[1]), it[2], it[3]))
            else:
                out.append((k, mv(it[1]), it[2], it[3], it[4], it[5]))
        return Geo(out)

    def bbox(self):
        xs, ys = [], []
        for it in self.items:
            if it[0] == "line":
                xs += [it[1][0], it[2][0]]; ys += [it[1][1], it[2][1]]
            elif it[0] == "pline":
                xs += [p[0] for p in it[1]]; ys += [p[1] for p in it[1]]
            elif it[0] == "circle":
                xs += [it[1][0] - it[2], it[1][0] + it[2]]; ys += [it[1][1] - it[2], it[1][1] + it[2]]
            elif it[0] == "text":
                w = TEXT_W * it[3] * len(it[2])
                x = it[1][0]
                x0 = x - w if it[5] == "R" else (x - w / 2 if it[5] == "C" else x)
                xs += [x0, x0 + w]; ys += [it[1][1] - it[3] * 0.6, it[1][1] + it[3] * 0.6]
        if not xs:
            return (0.0, 0.0, 1.0, 1.0)
        return (min(xs), min(ys), max(xs), max(ys))


def build_content(rows, cfg, k):
    """Desenul randurilor. k = metri in model pentru 1 mm pe hartie (scara/1000)."""
    g = Geo()
    if not rows:
        return g
    EX = 1.0  # desenul e mereu 1:1: linia gri are exact lungimea abaterii scrise
    th = float(cfg["text_mm"]) * k
    lab = float(cfg["spatiu_etichete_mm"]) * k
    gap = float(cfg["distanta_randuri_mm"]) * k
    rpt = float(cfg["raza_punct_mm"]) * k
    wred = float(cfg["grosime_rosu_mm"]) * k
    cg, cr, cy, ct = (int(cfg[c]) for c in ("culoare_verde", "culoare_rosu", "culoare_gri", "culoare_text"))
    Hmax = max(x["H"] for r in rows for x in r["data"])
    top = Hmax + 5 * th
    x0 = 0.0
    for row in rows:
        pos = max(0.0, max(x["draw"] for x in row["data"])) * EX
        neg = max(0.0, -min(x["draw"] for x in row["data"])) * EX
        t = row["top"]
        pct = t["val"] / t["H"] * 100 if t["H"] > 0 else 0
        titlu = ascii_text(row["cfg"].get("titlu") or row["cfg"]["cod"])
        rez1 = f"Abatere la varf: {fmt_val(t['val'], cfg)}"
        rez2 = f"la H={t['H']:.2f} m - {pct:.2f}% ({pct * 10:.1f} mm/m)"
        text_w = max(TEXT_W * th * 1.7 * len(titlu), TEXT_W * th * 1.1 * max(len(rez1), len(rez2))) + 2 * th
        width = max(2 * lab + pos + neg, text_w)
        gx = x0 + (width - (pos + neg)) / 2 + neg
        g.line((gx - 4 * th, 0), (gx + 4 * th, 0), cy)          # baza
        g.line((gx, -1.5 * th), (gx, top), cg)                   # verticala verde
        red = [(gx + x["draw"] * EX, x["H"]) for x in row["data"]]
        g.pline(red, cr, wred)                                   # pozitia reala
        n, last_h, h_top = len(red), None, red[-1][1]
        s_lab = row["sign"]  # valorile pe partea spre care se apleaca randul, H pe partea opusa
        ext_out = pos if s_lab > 0 else neg
        ext_in = neg if s_lab > 0 else pos
        col_out = gx + s_lab * (ext_out + 1.5 * th)  # coloana aliniata pentru valori (nu atinge linia rosie)
        col_in = gx - s_lab * (ext_in + 1.5 * th)    # coloana aliniata pentru H / Z
        for i, (x, (rx, ry)) in enumerate(zip(row["data"], red)):
            g.circle((rx, ry), rpt, cr)
            if abs(rx - gx) > 1e-9:
                g.line((gx, ry), (rx, ry), cy)                   # abaterea, la lungimea reala
            if cfg["evita_suprapunere"] and 0 < i < n - 1 and (
                    (last_h is not None and ry - last_h < 1.25 * th) or h_top - ry < 1.25 * th):
                continue
            last_h = ry
            g.text((col_out, ry), fmt_val(x["val"], cfg), th, ct, "L" if s_lab > 0 else "R")
            info = []
            if cfg["arata_H"]:
                info.append(f"H={x['H']:.2f}")
            if cfg["arata_cote_Z"]:
                info.append(f"Z={x['p']['z']:.3f}")
            if info:
                g.text((col_in, ry), "  ".join(info), th * 0.85, cy, "R" if s_lab > 0 else "L")
        cx = x0 + width / 2
        g.text((cx, top + 9 * th), titlu, th * 1.7, ct, "C")
        g.text((cx, top + 5.8 * th), rez1, th * 1.1, 2, "C")
        g.text((cx, top + 4.0 * th), rez2, th * 1.1, 2, "C")
        x0 += width + gap
    total_w = x0 - gap
    g.text((total_w / 2, top + 14 * th), ascii_text(cfg["titlu_plan"]), float(cfg["titlu_mm"]) * k, ct, "C")
    if cfg["arata_legenda"]:
        y = -5 * th
        scl = "abaterile sunt desenate la lungimea reala" if abs(EX - 1) < 1e-9 else             f"abaterile sunt marite de {EX:g} ori (valorile scrise sunt reale)"
        rows_leg = [
            (cg, 0, "Linia verde - verticala de referinta,"),
            (None, 0, "dusa prin punctul cel mai de jos al randului"),
            (cr, wred, "Linia rosie - pozitia reala masurata"),
            (cy, 0, f"Linia gri - abaterea pe orizontala ({cfg['unitate']})"),
        ]
        for i, (col, w, txt) in enumerate(rows_leg):
            yy = y - i * 2.2 * th
            if col is not None:
                g.pline([(0, yy), (5 * th, yy)], col, w)
            g.text((6.2 * th, yy), txt, th, ct)
        yy = y - len(rows_leg) * 2.2 * th - 0.5 * th
        g.text((0, yy), f"Cote in metri, desen la scara 1:1; {scl}.", th * 0.9, cy)
        g.text((0, yy - 1.9 * th), "H = inaltimea fata de punctul de baza al randului.", th * 0.9, cy)
    return g


def draw_sheet(g, fmt, orient, scale, cfg):
    """Chenar plansa + cartus, in coordonate model (0,0 = coltul stanga-jos al foii)."""
    k = scale / 1000.0
    w, h = FORMATE[fmt]
    if orient == "peisaj":
        w, h = h, w
    W, H = w * k, h * k
    ct = int(cfg["culoare_text"])
    g.rect(0, 0, W, H, 8)                                                   # marginea foii
    fx0, fy0, fx1, fy1 = MARGINE_STANGA * k, MARGINE * k, W - MARGINE * k, H - MARGINE * k
    g.rect(fx0, fy0, fx1, fy1, ct, 0.5 * k)                                 # chenar
    if cfg["cartus"]:
        cx0, cy0 = fx1 - CARTUS_L * k, fy0
        g.rect(cx0, cy0, fx1, cy0 + CARTUS_H * k, ct)
        today = datetime.date.today().strftime("%d.%m.%Y")
        rows = [("Intocmit", f"{cfg['intocmit']}", "Data", today),
                ("Scara", f"1:{scale}", "Format", f"{fmt} {orient}"),
                ("Plansa", ascii_text(cfg["titlu_plan"]), "Nr.", str(cfg["plansa_nr"])),
                ("Obiectiv", ascii_text(cfg["obiectiv"]), "", ""),
                ("Beneficiar", ascii_text(cfg["beneficiar"]), "", "")]
        rh = CARTUS_H / len(rows)
        for i, (l1, v1, l2, v2) in enumerate(rows):
            y = cy0 + i * rh * k
            if i:
                g.line((cx0, y), (fx1, y), ct)
            ym = y + rh * k / 2
            fit = lambda txt, h, w: min(h, w / (TEXT_W * max(len(txt), 1)))
            g.text((cx0 + 2 * k, ym), l1, fit(l1, 1.8, 17) * k, 8)
            w1 = (59 if l2 else 96)
            g.text((cx0 + 22 * k, ym), ascii_text(v1), fit(ascii_text(v1), 2.2, w1) * k, ct)
            if l2:
                g.text((cx0 + 84 * k, ym), l2, fit(l2, 1.8, 10) * k, 8)
                g.text((cx0 + 95 * k, ym), ascii_text(v2), fit(ascii_text(v2), 2.2, 23) * k, ct)
        g.line((cx0 + 20 * k, cy0), (cx0 + 20 * k, cy0 + CARTUS_H * k), ct)
        g.line((cx0 + 82 * k, cy0), (cx0 + 82 * k, cy0 + 3 * rh * k), ct)
    avail = (fx0 + 5 * k, fy0 + ((CARTUS_H + 5) * k if cfg["cartus"] else 5 * k), fx1 - 5 * k, fy1 - 5 * k)
    return avail


def fits(content_bbox, fmt, orient, scale, cfg):
    k = scale / 1000.0
    w, h = FORMATE[fmt]
    if orient == "peisaj":
        w, h = h, w
    aw = w - MARGINE_STANGA - MARGINE - 10
    ah = h - 2 * MARGINE - 10 - ((CARTUS_H + 5) if cfg["cartus"] else 0)
    cw = (content_bbox[2] - content_bbox[0]) / k
    ch = (content_bbox[3] - content_bbox[1]) / k
    return cw <= aw and ch <= ah


def layout(rows, cfg):
    """Alege formatul / scara si intoarce (Geo final, info)."""
    if not rows:
        return Geo(), {}
    sc_cfg = str(cfg["scara"])
    scales = SCARI if sc_cfg == "auto" else [int(sc_cfg.split(":")[1])]
    fmt_cfg = cfg["format"]
    if fmt_cfg == "fara":
        scale = scales[0]
        g = build_content(rows, cfg, scale / 1000.0)
        if cfg["arata_rama"]:
            x0, y0, x1, y1 = g.bbox()
            m = 5 * scale / 1000.0
            g.rect(x0 - m, y0 - m, x1 + m, y1 + m, int(cfg["culoare_text"]))
        return g, {"format": "fara", "scale": scale, "ok": True}
    fmts = list(FORMATE) if fmt_cfg == "auto" else [fmt_cfg]
    orients = ["portret", "peisaj"] if cfg["orientare"] == "auto" else [cfg["orientare"]]
    if cfg["prioritate_autofit"] == "format mic":
        combos = [(f, s) for f in fmts for s in scales]
    else:
        combos = [(f, s) for s in scales for f in fmts]
    cache = {}
    chosen = None
    for f, s in combos:
        if s not in cache:
            cache[s] = build_content(rows, cfg, s / 1000.0)
        bb = cache[s].bbox()
        for o in orients:
            if fits(bb, f, o, s, cfg):
                chosen = (f, o, s)
                break
        if chosen:
            break
    ok = chosen is not None
    if not ok:
        chosen = (fmts[-1], orients[0], scales[-1])
    f, o, s = chosen
    content = cache.get(s) or build_content(rows, cfg, s / 1000.0)
    sheet = Geo()
    ax0, ay0, ax1, ay1 = draw_sheet(sheet, f, o, s, cfg)
    bx0, by0, bx1, by1 = content.bbox()
    dx = (ax0 + ax1) / 2 - (bx0 + bx1) / 2
    dy = (ay0 + ay1) / 2 - (by0 + by1) / 2
    final = Geo(sheet.items + content.moved(dx, dy).items)
    return final, {"format": f, "orient": o, "scale": s, "ok": ok}


# ============================================================================ export DXF / DWG
def write_dxf(g, path, layer):
    if not tklic.valid():
        raise PermissionError(tklic.text())
    layer = ascii_text(layer) or "0"
    out = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "0", "ENDSEC",
           "0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", "1",
           "0", "LAYER", "2", layer, "70", "0", "62", "7", "6", "CONTINUOUS",
           "0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    f = lambda v: f"{v:.6f}"
    for it in g.items:
        k = it[0]
        if k == "line":
            _, a, b, c = it
            out += ["0", "LINE", "8", layer, "62", str(c), "10", f(a[0]), "20", f(a[1]), "30", "0.0",
                    "11", f(b[0]), "21", f(b[1]), "31", "0.0"]
        elif k == "pline":
            _, pts, c, w = it
            out += ["0", "POLYLINE", "8", layer, "62", str(c), "66", "1", "10", "0.0", "20", "0.0", "30", "0.0",
                    "70", "0", "40", f(w), "41", f(w)]
            for p in pts:
                out += ["0", "VERTEX", "8", layer, "10", f(p[0]), "20", f(p[1]), "30", "0.0", "40", f(w), "41", f(w)]
            out += ["0", "SEQEND", "8", layer]
        elif k == "circle":
            _, c0, r, c = it
            out += ["0", "CIRCLE", "8", layer, "62", str(c), "10", f(c0[0]), "20", f(c0[1]), "30", "0.0", "40", f(r)]
        elif k == "text":
            _, p, s, h, c, j = it
            out += ["0", "TEXT", "8", layer, "62", str(c), "10", f(p[0]), "20", f(p[1]), "30", "0.0",
                    "40", f(h), "1", ascii_text(s), "72", str({"L": 0, "C": 1, "R": 2}[j]),
                    "11", f(p[0]), "21", f(p[1]), "31", "0.0", "73", "2"]
    out += ["0", "ENDSEC", "0", "EOF"]
    with open(path, "w", encoding="ascii", newline="\r\n") as fh:
        fh.write("\n".join(out) + "\n")


def dxf_to_dwg(dxf_path, dwg_path, acc):
    """DXF -> DWG cu AutoCAD Core Console. Desenul se salveaza intai in folderul temporar, cu nume
    ASCII (scriptul .scr e citit in codepage-ul ANSI: un nume ca "Plan înclinare ș.dwg" nu ar
    ajunge intreg), apoi se muta la destinatie."""
    tmp = tempfile.mkdtemp(prefix="planincl_")
    try:
        scr = os.path.join(tmp, "s.scr")
        tmp_dwg = os.path.join(tmp, "plan.dwg")
        with open(scr, "w", encoding="ascii", newline="\r\n") as fh:
            fh.write("_.ZOOM\n_E\n")
            fh.write(f'_.SAVEAS\n2018\n"{script_path(tmp_dwg).replace(os.sep, "/")}"\n')
            fh.write("_.QUIT\n_Y\n")
        r = subprocess.run([acc, "/i", dxf_path, "/s", scr, "/l", "en-US"], cwd=tmp, capture_output=True,
                           timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log = r.stdout.decode("utf-16-le", "ignore").replace("\x00", "") if r.stdout else ""
        if not os.path.exists(tmp_dwg):
            return False, log
        try:
            os.replace(tmp_dwg, dwg_path)
        except OSError:
            try:
                shutil.move(tmp_dwg, dwg_path)       # alt volum
            except OSError as ex:                     # destinatia e deschisa in AutoCAD / fara drept de scriere
                return False, f"{log}\n{ex}"
        return os.path.exists(dwg_path), log
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================================ drag & drop (Windows)
def enable_file_drop(win, callback):
    """Accepta fisiere trase din Explorer in fereastra Tk (fara biblioteci externe)."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    win.update_idletasks()
    hwnd = int(win.wm_frame(), 16)
    state = {}

    def proc(h, msg, wp, lp):
        if msg == 0x0233:  # WM_DROPFILES
            n = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
            files = []
            for i in range(n):
                ln = shell32.DragQueryFileW(wp, i, None, 0)
                buf = ctypes.create_unicode_buffer(ln + 1)
                shell32.DragQueryFileW(wp, i, buf, ln + 1)
                files.append(buf.value)
            shell32.DragFinish(wp)
            win.after(10, lambda: callback(files))
            return 0
        return user32.CallWindowProcW(state["old"], h, msg, wp, lp)

    cb = WNDPROC(proc)
    state["old"] = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p))
    shell32.DragAcceptFiles(hwnd, True)
    win._drop_proc = cb  # pastram referinta
    return True


# ============================================================================ GUI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Plan Inclinare - verticalitate pe randuri de puncte")
        self.geometry("1400x860")
        self.minsize(1050, 680)
        self.cfg = load_config()
        if not self.cfg.get("accoreconsole") or not os.path.exists(self.cfg["accoreconsole"]):
            self.cfg["accoreconsole"] = find_accoreconsole()
        self.points, self.rows, self.sources = [], [], []
        self.geo, self.info = Geo(), {}
        self.view = None
        self._pending = 0
        self.jobs = queue.Queue()
        self._build()
        self.refresh()
        self.after(200, self._poll_jobs)
        try:
            self.dnd = enable_file_drop(self, self.on_drop)
        except Exception:
            self.dnd = False

    # ---------------------------------------------------------------- interfata
    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")
        ttk.Button(top, text="Deschide puncte...", command=self.open_file).pack(side="left")
        ttk.Button(top, text="Lipește din clipboard", command=self.paste_points).pack(side="left", padx=4)
        ttk.Button(top, text="Puncte din AutoCAD...", command=self.pick_from_acad).pack(side="left")
        ttk.Button(top, text="Reîncarcă", command=self.reload_sources).pack(side="left")
        ttk.Button(top, text="Golește", command=self.clear_points).pack(side="left", padx=4)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(top, text="Export DWG...", command=lambda: self.export("dwg")).pack(side="left")
        ttk.Button(top, text="Export DXF...", command=lambda: self.export("dxf")).pack(side="left", padx=4)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(top, text="Salvează setări", command=self.save_cfg).pack(side="left")
        ttk.Button(top, text="Încarcă setări...", command=self.load_cfg_file).pack(side="left", padx=4)
        ttk.Button(top, text="Setări implicite", command=self.reset_cfg).pack(side="left")
        self.lbl_file = ttk.Label(top, text="Niciun fișier încărcat", foreground="#555")
        self.lbl_file.pack(side="right")
        self.status = ttk.Label(self, text="", anchor="w", padding=(8, 3))
        self.status.pack(side="bottom", fill="x")

        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True)
        left = ttk.Notebook(pw, width=450)
        pw.add(left, weight=0)
        right = ttk.Frame(pw)
        pw.add(right, weight=1)

        self.vars = {}
        self.code_boxes = []
        for title, builder in (("Date", self._tab_date), ("Planșă", self._tab_plansa), ("Desen", self._tab_desen)):
            outer = ttk.Frame(left)
            left.add(outer, text=title)
            cnv = tk.Canvas(outer, highlightthickness=0, bg=style.lookup("TFrame", "background") or "#dcdad5")
            sb = ttk.Scrollbar(outer, orient="vertical", command=cnv.yview)
            frm = ttk.Frame(cnv, padding=8)
            frm.bind("<Configure>", lambda e, c=cnv: c.configure(scrollregion=c.bbox("all")))
            cnv.create_window((0, 0), window=frm, anchor="nw")
            cnv.configure(yscrollcommand=sb.set)
            cnv.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            cnv.bind("<Enter>", lambda e, c=cnv: self.bind_all("<MouseWheel>",
                                                               lambda ev: c.yview_scroll(-1 * (ev.delta // 120), "units")))
            cnv.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))
            builder(frm)

        tab_p = ttk.Frame(left, padding=4)
        left.add(tab_p, text="Rezultate")
        cols = ("rand", "n", "cod", "H", "abatere", "z")
        self.tree = ttk.Treeview(tab_p, columns=cols, show="headings")
        for c, t, w in zip(cols, ("Rând", "Nr", "Cod", "H (m)", "Abatere", "Z"), (80, 45, 80, 60, 75, 70)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center")
        vs = ttk.Scrollbar(tab_p, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

        tab_h = ttk.Frame(left, padding=8)
        left.add(tab_h, text="Ajutor")
        t = tk.Text(tab_h, wrap="word", relief="flat", font=("Segoe UI", 9))
        t.insert("1.0", HELP_TEXT)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)

        bar = ttk.Frame(right, padding=(6, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Previzualizare", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.lbl_sheet = ttk.Label(bar, text="", foreground="#0b5")
        self.lbl_sheet.pack(side="left", padx=12)
        ttk.Button(bar, text="Încadrează", command=self.fit).pack(side="right")
        ttk.Label(bar, text="Rotiță = zoom · trage = mută · trage fișiere aici", foreground="#666").pack(side="right", padx=10)
        self.cv = tk.Canvas(right, bg="#1e2329", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.draw(fit=self.view is None))
        self.cv.bind("<MouseWheel>", self.on_wheel)
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)

    # ---- campuri
    def _grid_helpers(self, f):
        st = {"r": 0}

        def section(title):
            ttk.Label(f, text=title, font=("Segoe UI", 10, "bold")).grid(row=st["r"], column=0, columnspan=3,
                                                                         sticky="w", pady=(10, 3))
            st["r"] += 1

        def note(text):
            ttk.Label(f, text=text, foreground="#666", wraplength=400, justify="left").grid(
                row=st["r"], column=0, columnspan=3, sticky="w", pady=(0, 4))
            st["r"] += 1

        def field(key, label, kind="entry", values=None, width=14):
            ttk.Label(f, text=label).grid(row=st["r"], column=0, sticky="w", padx=(0, 6), pady=2)
            if kind == "check":
                v = tk.BooleanVar(value=bool(self.cfg[key]))
                w = ttk.Checkbutton(f, variable=v, command=self.on_change)
            elif kind == "combo":
                v = tk.StringVar(value=str(self.cfg[key]))
                w = ttk.Combobox(f, textvariable=v, values=values, width=width, state="readonly")
                w.bind("<<ComboboxSelected>>", lambda e: self.on_change())
            else:
                v = tk.StringVar(value=str(self.cfg[key]))
                w = ttk.Entry(f, textvariable=v, width=width)
                w.bind("<Return>", lambda e: self.on_change())
                w.bind("<FocusOut>", lambda e: self.on_change())
            w.grid(row=st["r"], column=1, columnspan=2, sticky="w", pady=2)
            self.vars[key] = v
            st["r"] += 1
            return w

        return st, section, note, field

    def _tab_date(self, f):
        st, section, note, field = self._grid_helpers(f)
        section("Fișier puncte (CSV / TXT)")
        field("coloane", "Ordinea coloanelor", width=22)
        field("separator", "Separator", "combo", ["auto", ",", ";", "tab", "spatiu"])
        note("DWG / DXF: se citesc automat punctele COGO (Civil 3D) și punctele AutoCAD. "
             "Poți trage mai multe fișiere deodată în fereastră; punctele se adună.")
        section("Rânduri (de la stânga la dreapta)")
        field("potrivire_cod", "Potrivire cod", "combo", ["exact", "incepe cu", "contine"])
        r = st["r"]
        for c, t in enumerate(("Cod", "Titlu în plan", "Aplecare")):
            ttk.Label(f, text=t, foreground="#555").grid(row=r, column=c, sticky="w")
        r += 1
        self.row_vars = []
        rows_cfg = list(self.cfg["randuri"]) + [{"cod": "", "titlu": "", "directie": "auto"}] * 4
        for rc in rows_cfg[:4]:
            vc, vt, vd = tk.StringVar(value=rc["cod"]), tk.StringVar(value=rc["titlu"]), tk.StringVar(value=rc.get("directie", "auto"))
            e1 = ttk.Combobox(f, textvariable=vc, width=16)
            e2 = ttk.Entry(f, textvariable=vt, width=17)
            cb = ttk.Combobox(f, textvariable=vd, values=["auto", "stanga", "dreapta"], width=8, state="readonly")
            e1.grid(row=r, column=0, sticky="w", pady=2)
            e2.grid(row=r, column=1, sticky="w", pady=2)
            cb.grid(row=r, column=2, sticky="w", pady=2)
            for e in (e1, e2):
                e.bind("<Return>", lambda ev: self.on_change())
                e.bind("<FocusOut>", lambda ev: self.on_change())
            e1.bind("<<ComboboxSelected>>", lambda ev: self.on_change())
            cb.bind("<<ComboboxSelected>>", lambda ev: self.on_change())
            self.code_boxes.append(e1)
            self.row_vars.append((vc, vt, vd))
            r += 1
        st["r"] = r
        note("Codul se poate alege din lista cu codurile găsite în puncte. "
             "Verticala fiecărui rând trece prin punctul lui cel mai de jos. "
             "'auto' = direcția se deduce pe axa rândul din stânga → rândul din dreapta.")
        section("Calcul")
        field("tip_abatere", "Abatere", "combo", ["totala", "proiectata"])
        field("unitate", "Unitate etichete", "combo", ["cm", "mm", "m"])
        field("zecimale", "Zecimale")
        section("Export DWG / citire DWG")
        field("accoreconsole", "accoreconsole.exe", width=34)
        ttk.Button(f, text="Caută...", command=self.pick_acc).grid(row=st["r"], column=1, sticky="w")
        st["r"] += 1

    def _tab_plansa(self, f):
        st, section, note, field = self._grid_helpers(f)
        section("Format și scară")
        field("format", "Format", "combo", ["auto", "fara"] + list(FORMATE))
        field("orientare", "Orientare", "combo", ["auto", "portret", "peisaj"])
        field("scara", "Scară", "combo", ["auto"] + [f"1:{s}" for s in SCARI])
        field("prioritate_autofit", "Autofit preferă", "combo", ["scara mare", "format mic"])
        note("auto = programul alege singur. 'scara mare' = cea mai detaliată scară care încape "
             "(1:100 înainte de 1:200), pe cel mai mic format posibil. 'format mic' = cel mai mic format, "
             "apoi scara care încape. 'fara' = fără planșă (doar desenul, cu scara pentru mărimea textelor).")
        section("Cartuș")
        field("cartus", "Desenează cartuș", "check")
        field("beneficiar", "Beneficiar", width=30)
        field("obiectiv", "Obiectiv", width=30)
        field("intocmit", "Întocmit", width=30)
        field("plansa_nr", "Nr. planșă", width=8)
        field("titlu_plan", "Titlu plan", width=30)

    def _tab_desen(self, f):
        st, section, note, field = self._grid_helpers(f)
        section("Mărimi (mm pe hârtie)")
        field("text_mm", "Înălțime text")
        field("titlu_mm", "Înălțime titlu")
        field("raza_punct_mm", "Rază cerc punct")
        field("grosime_rosu_mm", "Grosime linie roșie")
        field("spatiu_etichete_mm", "Spațiu etichete")
        field("distanta_randuri_mm", "Distanță între rânduri")
        section("Ce se afișează")
        field("arata_H", "Înălțimea H la fiecare punct", "check")
        field("arata_cote_Z", "Cota Z la fiecare punct", "check")
        field("evita_suprapunere", "Ascunde etichetele care se suprapun", "check")
        field("arata_legenda", "Legendă", "check")
        field("arata_rama", "Ramă (doar fără format)", "check")
        section("Culori (index AutoCAD) și strat")
        field("culoare_verde", "Verticală referință")
        field("culoare_rosu", "Poziție reală")
        field("culoare_gri", "Abatere")
        field("culoare_text", "Text")
        field("strat", "Strat (layer)")

    # ---------------------------------------------------------------- setari
    def read_vars(self):
        c = self.cfg
        for k, v in self.vars.items():
            val = v.get()
            d = DEFAULT_CONFIG.get(k)
            if isinstance(d, bool):
                c[k] = bool(val)
            elif isinstance(d, (int, float)):
                try:
                    num = float(str(val).replace(",", "."))
                    c[k] = int(num) if isinstance(d, int) else num
                except ValueError:
                    pass
            else:
                c[k] = val
        c["randuri"] = [{"cod": a.get().strip(), "titlu": b.get().strip(), "directie": d.get()}
                        for a, b, d in self.row_vars if a.get().strip()]

    def write_vars(self):
        for k, v in self.vars.items():
            v.set(self.cfg[k])
        rows = list(self.cfg["randuri"]) + [{"cod": "", "titlu": "", "directie": "auto"}] * 4
        for (a, b, d), rc in zip(self.row_vars, rows):
            a.set(rc["cod"]); b.set(rc["titlu"]); d.set(rc.get("directie", "auto"))

    def save_cfg(self):
        self.read_vars()
        path = filedialog.asksaveasfilename(title="Salvează setările", defaultextension=".json", initialdir=APP_DIR,
                                            initialfile=os.path.basename(CONFIG_FILE), filetypes=[("Setări", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.cfg, fh, indent=2, ensure_ascii=False)
        except OSError as ex:
            messagebox.showerror("Setări", f"Nu pot salva setările:\n{path}\n\n{ex}")
            return
        auto = os.path.abspath(path) == os.path.abspath(CONFIG_FILE)
        self.set_status(f"Setări salvate: {path}" + ("  (se încarcă automat la pornire)" if auto else ""))

    def load_cfg_file(self, path=None):
        path = path or filedialog.askopenfilename(title="Încarcă setări", initialdir=APP_DIR, filetypes=[("Setări", "*.json")])
        if not path:
            return
        acc = self.cfg.get("accoreconsole", "")
        self.cfg = load_config(path)
        if not self.cfg.get("accoreconsole"):
            self.cfg["accoreconsole"] = acc
        self.write_vars()
        self.reload_sources()

    def reset_cfg(self):
        acc = self.cfg.get("accoreconsole", "")
        self.cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        self.cfg["accoreconsole"] = acc
        self.write_vars()
        self.reload_sources()

    def pick_acc(self):
        p = filedialog.askopenfilename(title="accoreconsole.exe", filetypes=[("accoreconsole", "accoreconsole.exe")])
        if p:
            self.vars["accoreconsole"].set(p)
            self.on_change()

    # ---------------------------------------------------------------- date
    def open_file(self):
        ps = filedialog.askopenfilenames(title="Fișiere puncte",
                                         filetypes=[("Puncte și desene", "*.csv *.txt *.pnt *.dat *.xyz *.dwg *.dxf"),
                                                    ("Toate", "*.*")])
        if ps:
            self.load_files(list(ps), replace=True)

    def on_drop(self, files):
        settings = [f for f in files if f.lower().endswith(".json")]
        if settings:
            self.load_cfg_file(settings[0])
        data = [f for f in files if f.lower().endswith(PUNCTE_EXT + CAD_EXT)]
        if data:
            self.load_files(data, replace=True)
        elif not settings:
            messagebox.showinfo("Drag & drop", "Accept fișiere CSV, TXT, PNT, DAT, DWG, DXF (puncte) sau JSON (setări).")

    def load_files(self, files, replace=True):
        self.read_vars()
        if replace:
            self.sources, self.points = [], []
        self.sources += [os.path.abspath(f) for f in files]
        self.reload_sources()

    def reload_sources(self):
        self.read_vars()
        if not self.sources:
            self.refresh()
            return
        self.points = []
        acc = self.cfg.get("accoreconsole")
        cad = [s for s in self.sources if s.lower().endswith(CAD_EXT)]
        for s in self.sources:
            if s in cad:
                continue
            try:
                self.points += load_points_from(s, self.cfg, acc)
            except Exception as ex:
                messagebox.showerror("Citire", f"{os.path.basename(s)}:\n{ex}")
        if cad:
            self.set_status("Citesc punctele din " + ", ".join(os.path.basename(c) for c in cad) +
                            " cu AutoCAD Core Console (durează ~20-40 s)...")
            self.config(cursor="watch")
            for s in cad:
                threading.Thread(target=self._cad_worker, args=(s, acc), daemon=True).start()
            self._pending = len(cad)
        else:
            self._after_load()

    def _cad_worker(self, path, acc):
        try:
            self.jobs.put(("ok", path, load_points_from(path, self.cfg, acc)))
        except Exception as ex:
            self.jobs.put(("err", path, str(ex)))

    def _poll_jobs(self):
        try:
            while True:
                kind, path, data = self.jobs.get_nowait()
                if kind == "ok":
                    self.points += data
                else:
                    messagebox.showerror("Citire DWG/DXF", f"{os.path.basename(path)}:\n{data}")
                self._pending -= 1
                if self._pending <= 0:
                    self.config(cursor="")
                    self._after_load()
        except queue.Empty:
            pass
        self.after(200, self._poll_jobs)

    def _after_load(self):
        names = ", ".join(os.path.basename(s) for s in self.sources) or "clipboard"
        self.lbl_file.configure(text=f"{names}  ({len(self.points)} puncte)")
        codes = sorted({str(p["cod"]) for p in self.points if str(p["cod"]).strip()})
        for cb in self.code_boxes:
            cb.configure(values=codes)
        self.view = None
        self.refresh()
        if self.points and not self.rows and codes:
            self.after(50, lambda: self.ask_codes(codes))

    def ask_codes(self, codes):
        """Codurile din fisier nu se potrivesc cu randurile: utilizatorul alege codurile."""
        left, right, third = guess_codes(codes)
        dlg = tk.Toplevel(self)
        dlg.title("Alege codurile rândurilor")
        dlg.transient(self)
        dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"Am încărcat {len(self.points)} puncte, dar codurile lor nu se potrivesc cu rândurile din setări.\n"
                            f"Alege ce cod are fiecare rând (am completat o propunere):",
                  justify="left").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        vals = [""] + codes
        entries = []
        for i, (lbl, guess, title, d) in enumerate((("Rândul din stânga", left, "PARTEA STANGA", "auto"),
                                                    ("Rândul din dreapta", right, "PARTEA DREAPTA", "auto"),
                                                    ("Al treilea rând (opțional)", "", "SPATE", "dreapta"))):
            ttk.Label(frm, text=lbl).grid(row=i + 1, column=0, sticky="w", pady=3, padx=(0, 8))
            v = tk.StringVar(value=guess)
            ttk.Combobox(frm, textvariable=v, values=vals, state="readonly", width=16).grid(row=i + 1, column=1, sticky="w")
            entries.append((v, title, d))
        if third:
            ttk.Label(frm, text=f"(„{third}” arată ca puncte din spate; le poți pune\n"
                                f"aici sau, mai bine, într-un plan separat doar cu ele)",
                      foreground="#666", justify="left").grid(row=3, column=2, sticky="w", padx=8)
        keep = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Păstrează și codurile vechi (stanga / dreapta) pentru fișierele viitoare",
                        variable=keep).grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 4))

        def ok():
            old = list(self.cfg["randuri"]) + [{"cod": "", "titlu": "", "directie": "auto"}] * 3
            new = []
            for i, (v, title, d) in enumerate(entries):
                code = v.get().strip()
                if not code:
                    continue
                prev = old[i] if i < 2 else {"cod": "", "titlu": title, "directie": d}
                parts = [c.strip() for c in prev["cod"].split(",") if c.strip()] if keep.get() else []
                if code not in parts:
                    parts.append(code)
                new.append({"cod": ", ".join(parts), "titlu": prev.get("titlu") or title,
                            "directie": prev.get("directie", d)})
            if new:
                self.cfg["randuri"] = new
                self.write_vars()
                self.view = None
                self.refresh()
            dlg.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Anulează", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="OK", command=ok).pack(side="right", padx=6)
        dlg.bind("<Return>", lambda e: ok())
        dlg.update_idletasks()
        dlg.geometry(f"+{self.winfo_rootx() + 300}+{self.winfo_rooty() + 200}")
        dlg.deiconify()
        dlg.lift()
        dlg.attributes("-topmost", True)  # sa nu ramana ascunsa in spatele ferestrei principale
        dlg.focus_force()
        try:
            dlg.grab_set()
        except tk.TclError:
            pass

    def pick_from_acad(self):
        """Selectia punctelor in desenul deschis: TopoKit trimite comanda PLANINCLSEL in AutoCAD,
        care scrie punctele alese (COGO, puncte AutoCAD, blocuri) intr-un fisier citit aici."""
        self.read_vars()
        try:
            if os.path.exists(ACAD_POINTS):
                os.remove(ACAD_POINTS)
        except OSError:
            pass
        exe = topokit_exe()
        if exe:
            subprocess.Popen([exe, "/cmd", "PLANINCLSEL"])
            self.set_status("Selectați punctele în AutoCAD (puncte COGO, puncte AutoCAD sau blocuri), apoi Enter...")
        else:
            messagebox.showinfo("Puncte din AutoCAD",
                                "Nu am găsit TopoKit.exe. În AutoCAD scrieți comanda PLANINCLSEL, "
                                "selectați punctele și apăsați Enter; programul le preia automat.")
        self._acad_wait = 0
        self.after(500, self._poll_acad)

    def _poll_acad(self):
        if os.path.exists(ACAD_POINTS):
            pts = parse_points(read_text_file(ACAD_POINTS), self.cfg, cols="N,X,Y,Z,COD", sep=";")
            if not pts:
                self.set_status("Niciun punct selectat în AutoCAD.")
                return
            self.sources, self.points = [], pts
            self._after_load()
            self.lbl_file.configure(text=f"AutoCAD - desenul deschis  ({len(pts)} puncte)")
            self.deiconify()
            self.lift()
            self.focus_force()
            return
        self._acad_wait += 1
        if self._acad_wait < 600:                      # cel mult 5 minute
            self.after(500, self._poll_acad)
        else:
            self.set_status("Nu au venit puncte din AutoCAD (selecția a fost anulată?).")

    def paste_points(self):
        try:
            txt = self.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Clipboard", "Clipboard-ul nu conține text.")
            return
        self.read_vars()
        pts = parse_points(txt, self.cfg)
        if not pts:
            messagebox.showwarning("Clipboard", "Nu am găsit puncte în text. Verifică ordinea coloanelor (tab Date).")
            return
        self.sources, self.points = [], pts
        self._after_load()

    def clear_points(self):
        self.sources, self.points = [], []
        self._after_load()

    def on_change(self):
        self.read_vars()
        txt_sources = [s for s in self.sources if not s.lower().endswith(CAD_EXT)]
        if txt_sources and len(txt_sources) == len(self.sources):
            self.reload_sources()  # recitim (se poate fi schimbat formatul coloanelor)
        else:
            self.refresh()

    def refresh(self):
        self.rows, msgs = compute(self.points, self.cfg)
        self.geo, self.info = layout(self.rows, self.cfg)
        self.tree.delete(*self.tree.get_children())
        for row in self.rows:
            for x in reversed(row["data"]):
                self.tree.insert("", "end", values=(row["cfg"]["cod"], x["p"]["n"], x["p"]["cod"], f"{x['H']:.3f}",
                                                    fmt_val(x["val"], self.cfg), f"{x['p']['z']:.3f}"))
        if self.info:
            if self.info["format"] == "fara":
                s = f"Fără format · mărimi pentru scara 1:{self.info['scale']}"
            else:
                s = f"Format {self.info['format']} {self.info['orient']} · scara 1:{self.info['scale']}"
            if not self.info.get("ok", True):
                s += "  ⚠ nu încape - mărește formatul/scara sau micșorează textele"
            self.lbl_sheet.configure(text=s, foreground="#0a5" if self.info.get("ok", True) else "#c30")
        else:
            self.lbl_sheet.configure(text="")
        if not self.points:
            self.set_status("Trage în fereastră fișiere CSV/TXT/DWG/DXF cu puncte, sau folosește 'Deschide puncte'.")
        else:
            parts = []
            for row in self.rows:
                t = row["top"]
                parts.append(f"{row['cfg']['cod']}: {len(row['data'])} pct, vârf {fmt_val(t['val'], self.cfg)} la "
                             f"H={t['H']:.2f} m, spre {'dreapta' if row['sign'] > 0 else 'stânga'}")
            codes = sorted({str(p['cod']) for p in self.points})
            if not self.rows:
                parts.append("Niciun rând potrivit. Coduri găsite: " + ", ".join(codes[:15]))
            self.set_status(" | ".join(parts + msgs))
        self.draw(fit=self.view is None)

    def set_status(self, s):
        self.status.configure(text=s)

    # ---------------------------------------------------------------- previzualizare
    def fit(self):
        self.view = None
        self.draw(fit=True)

    def draw(self, fit=False):
        cv = self.cv
        cv.delete("all")
        W, H = max(cv.winfo_width(), 50), max(cv.winfo_height(), 50)
        if not self.geo.items:
            if self.points:
                codes = sorted({str(p["cod"]) for p in self.points if str(p["cod"]).strip()})
                msg = (f"Am încărcat {len(self.points)} puncte, dar niciun cod nu se potrivește cu rândurile.\n\n"
                       f"Coduri găsite: {', '.join(codes[:20])}\n\n"
                       f"Alege codurile în tabul Date → Rânduri (lista de lângă „Cod”),\n"
                       f"sau mai multe coduri pe un rând, separate prin virgulă (ex. stanga, s_sina).")
            elif self._pending > 0:
                msg = "Citesc punctele din desen..."
            else:
                msg = "Trage aici fișierele cu puncte\n(CSV, TXT, DWG, DXF)\n\nsau folosește „Deschide puncte...”"
            cv.create_text(W / 2, H / 2, fill="#8a9099", font=("Segoe UI", 12), justify="center", text=msg,
                           width=max(W - 60, 200))
            return
        if fit or self.view is None:
            x0, y0, x1, y1 = self.geo.bbox()
            s = min((W - 30) / max(x1 - x0, 1e-6), (H - 30) / max(y1 - y0, 1e-6))
            self.view = (s, (W - (x1 - x0) * s) / 2 - x0 * s, (H + (y1 - y0) * s) / 2 + y0 * s)
        s, ox, oy = self.view
        P = lambda p: (ox + p[0] * s, oy - p[1] * s)
        for it in self.geo.items:
            k = it[0]
            if k == "line":
                cv.create_line(*P(it[1]), *P(it[2]), fill=ACI_RGB.get(it[3], "#fff"))
            elif k == "pline":
                pts = [c for p in it[1] for c in P(p)]
                if len(pts) >= 4:
                    cv.create_line(*pts, fill=ACI_RGB.get(it[2], "#fff"), width=max(1, it[3] * s))
            elif k == "circle":
                cx, cy = P(it[1])
                r = max(it[2] * s, 1.0)
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=ACI_RGB.get(it[3], "#fff"))
            elif k == "text":
                _, p, txt, h, c, j = it
                px = h * s
                if px < 3:
                    continue
                cv.create_text(*P(p), text=txt, fill=ACI_RGB.get(c, "#fff"), anchor={"L": "w", "C": "center", "R": "e"}[j],
                               font=("Arial", -max(int(px * 1.15), 4)))

    def on_wheel(self, e):
        if not self.view:
            return
        s, ox, oy = self.view
        f = 1.2 if e.delta > 0 else 1 / 1.2
        self.view = (s * f, e.x - (e.x - ox) * f, e.y - (e.y - oy) * f)
        self.draw()

    def on_press(self, e):
        self._drag = (e.x, e.y)

    def on_drag(self, e):
        if not self.view:
            return
        s, ox, oy = self.view
        self.view = (s, ox + e.x - self._drag[0], oy + e.y - self._drag[1])
        self._drag = (e.x, e.y)
        self.draw()

    # ---------------------------------------------------------------- export
    def export(self, kind):
        if not tklic.gate():
            return
        self.read_vars()
        self.refresh()
        if not self.geo.items:
            messagebox.showwarning("Export", "Nu există nimic de exportat. Încarcă întâi punctele.")
            return
        first = self.sources[0] if self.sources else ""
        init_dir = self.cfg.get("folder_export") or (os.path.dirname(first) if first else APP_DIR)
        base = os.path.splitext(os.path.basename(first))[0] if first else "plan"
        path = filedialog.asksaveasfilename(title=f"Salvează {kind.upper()}", defaultextension="." + kind,
                                            initialdir=init_dir, initialfile=f"Plan_inclinare_{base}.{kind}",
                                            filetypes=[(kind.upper(), "*." + kind)])
        if not path:
            return
        path = os.path.abspath(path)
        self.cfg["folder_export"] = os.path.dirname(path)
        if kind == "dxf":
            try:
                write_dxf(self.geo, path, self.cfg["strat"])
            except OSError as ex:                     # fisier deschis in alt program / fara drept de scriere
                messagebox.showerror("Export DXF", f"Nu pot scrie fișierul:\n{path}\n\n{ex}")
                return
            self.set_status(f"DXF salvat: {path}")
            self.ask_open(path)
            return
        acc = self.cfg.get("accoreconsole") or find_accoreconsole()
        if not acc or not os.path.exists(acc):
            messagebox.showerror("Export DWG", "Nu găsesc accoreconsole.exe (vine cu AutoCAD / Civil 3D).\n"
                                               "Alege-l în tabul Date, sau folosește Export DXF.")
            return
        tmpdir = tempfile.mkdtemp(prefix="planincl_")
        tmpdxf = os.path.join(tmpdir, "plan.dxf")
        self.set_status("Se creează DWG-ul cu AutoCAD Core Console...")
        self.config(cursor="watch")
        self.update()
        try:
            write_dxf(self.geo, tmpdxf, self.cfg["strat"])
            ok, log = dxf_to_dwg(tmpdxf, path, acc)
        except Exception as ex:
            ok, log = False, str(ex)
        finally:
            self.config(cursor="")
            shutil.rmtree(tmpdir, ignore_errors=True)
        if ok:
            self.set_status(f"DWG salvat: {path}")
            self.ask_open(path)
        else:
            messagebox.showerror("Export DWG", "Conversia în DWG nu a reușit (fișierul e deschis în AutoCAD?).\n"
                                               "Poți folosi Export DXF.\n\n" + log[-800:])

    def ask_open(self, path):
        if messagebox.askyesno("Gata", f"Fișier salvat:\n{path}\n\nÎl deschid acum?"):
            try:
                os.startfile(path)
            except Exception as ex:
                messagebox.showerror("Deschidere", str(ex))


HELP_TEXT = """CUM SE FOLOSEȘTE

1. PUNCTELE
   • Trage în fereastră unul sau mai multe fișiere: CSV / TXT / PNT / DAT, sau DWG / DXF.
   • Din DWG / DXF se citesc punctele COGO (Civil 3D) și punctele AutoCAD (POINT), fără să deschizi AutoCAD
     (durează ~20-40 s, se folosește AutoCAD Core Console).
   • Fișier text: un punct pe rând, implicit Nr, X, Y, Z, Cod. Altă ordine → tab Date, „Ordinea coloanelor”
     (ex. N,Y,X,Z,COD). Ordinea X/Y nu schimbă abaterile.
   • Poți și copia punctele (ex. din Excel) și apăsa „Lipește din clipboard”.
   • „Puncte din AutoCAD...”: selectezi punctele direct în desenul deschis în AutoCAD / Civil 3D
     (puncte COGO, puncte AutoCAD sau blocuri) și apeși Enter; programul le preia automat.
     Codul punctului: descrierea (COGO) sau stratul (puncte AutoCAD, blocuri).

2. RÂNDURILE
   • Codul punctului spune rândul: „stanga” = partea stângă, „dreapta” = partea dreaptă.
     Cu „incepe cu”, merg și stanga1, dreapta_sus etc. După încărcare, codurile găsite apar în listă.
   • Până la 4 rânduri (ex. și „spate”), în ordinea în care apar în plan, de la stânga la dreapta.
   • Verticala de referință (linia verde) a fiecărui rând trece prin punctul lui cel mai de jos.
   • Abaterea = distanța pe orizontală de la punct la verticală (linia gri, la lungime reală).

3. DIRECȚIA DE APLECARE
   • auto: se calculează pe axa rândul din stânga → rândul din dreapta (privind fațada).
   • stanga / dreapta: o alegi tu (necesar când ai un singur rând, ex. „spate”).

4. PLANȘA (tab Planșă)
   • Format A4…A0 și scara 1:100…1:2000, alese de tine sau „auto”.
   • Autofit „scara mare”: cea mai detaliată scară care încape, pe cel mai mic format.
     Autofit „format mic”: cel mai mic format, apoi scara care încape.
   • Textele se dau în mm pe hârtie, deci arată la fel la orice scară.
   • Desenul e mereu 1:1, în metri: fiecare linie gri are exact lungimea abaterii scrise lângă ea.
     Scara aleasă mărește doar chenarul, cartușul și textele, ca planul să se ploteze corect.
   • Tot conținutul (desen, texte, legendă) încape în interiorul chenarului; dacă nu încape la
     formatul/scara aleasă, apare un avertisment roșu deasupra previzualizării.
   • La plotare alegi fereastra chenarului și scara din cartuș.

5. PREVIZUALIZARE: se actualizează la fiecare modificare (Enter sau click în alt câmp).
   Rotiță = zoom, trage cu mouse-ul = mută, „Încadrează” = vedere completă.

6. EXPORT
   • DWG: prin accoreconsole.exe (din AutoCAD / Civil 3D), fără să deschidă AutoCAD.
   • DXF: merge oricând, se deschide în orice program CAD.

7. SETĂRI REFOLOSIBILE
   • „Salvează setări” cu numele setari_plan_inclinare.json lângă program → se încarcă la pornire.
   • Poți păstra mai multe fișiere de setări (ex. silozuri, stâlpi, coșuri) și le încarci
     cu „Încarcă setări” sau trăgând fișierul .json în fereastră.
"""


def run_cli(argv):
    """python plan_inclinare.py --test puncte.csv|desen.dwg [iesire.dxf|iesire.dwg] [setari.json]"""
    cfg = load_config(argv[4]) if len(argv) >= 5 else load_config()
    acc = cfg.get("accoreconsole") or find_accoreconsole()
    pts = load_points_from(argv[2], cfg, acc)
    print(len(pts), "puncte citite")
    rows, msgs = compute(pts, cfg)
    for row in rows:
        t = row["top"]
        print(row["cfg"]["cod"], len(row["data"]), "pct; varf", fmt_val(t["val"], cfg), "H", round(t["H"], 3),
              "spre", "dreapta" if row["sign"] > 0 else "stanga")
    for m in msgs:
        print("!", m)
    g, info = layout(rows, cfg)
    print("plansa:", info)
    if len(argv) >= 4:
        out = os.path.abspath(argv[3])
        if out.lower().endswith(".dwg"):
            tmpdir = tempfile.mkdtemp(prefix="planincl_")
            try:
                tmpdxf = os.path.join(tmpdir, "plan.dxf")
                write_dxf(g, tmpdxf, cfg["strat"])
                print("dwg ok:", dxf_to_dwg(tmpdxf, out, acc)[0])
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        else:
            write_dxf(g, out, cfg["strat"])
            print("scris", out)


if __name__ == "__main__":
    if not tklic.gate():
        sys.exit(1)
    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        run_cli(sys.argv)
    else:
        app = App()
        files = [a for a in sys.argv[1:] if os.path.exists(a)]
        if files:
            app.after(150, lambda: app.load_files(files))
        app.mainloop()
