#!/usr/bin/env python3
"""Genereaza grafica lansatorului si a instalatorului TopoKit.

    python3 tools/make_icons.py

installer/launcher/:
    topokit.ico, tray_on.ico, tray_off.ico   iconitele programului / barei de sistem
    logo.png                                 sigla din antetul ferestrei TopoKit
    icons/m1.png ... m20.png                 iconitele modulelor (cardurile ferestrei)
installer/art/:
    welcome.bmp (164x314), header.bmp (150x57)   paginile instalatorului NSIS
docs/topokit_icon.png
"""
import math, pathlib
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "installer" / "launcher"
ART = ROOT / "installer" / "art"
(OUT / "icons").mkdir(parents=True, exist_ok=True)
ART.mkdir(parents=True, exist_ok=True)
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
if not pathlib.Path(FONT).exists():         # Windows: Arial in locul Liberation Sans
    FONT, FONT_R = "arialbd.ttf", "arial.ttf"

NAVY, TEAL, RED = (15, 61, 94), (27, 106, 143), (228, 72, 58)
S = 256


def hexc(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def contours(d, cx, cy, radii, color, width, k0=0):
    for k, r in enumerate(radii):
        pts = []
        for i in range(97):
            a = 2 * math.pi * i / 96
            rr = r * (1 + 0.12 * math.sin(3 * a + k + k0))
            pts.append((cx + rr * math.cos(a), cy + 0.78 * rr * math.sin(a)))
        d.line(pts, fill=color, width=width, joint="curve")


def logo():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=56, fill=NAVY + (255,))
    contours(d, 118, 132, (30, 58, 86, 114), (150, 205, 235, 255), 8)
    d.polygon([(118, 88), (154, 152), (82, 152)], fill=RED + (255,), outline=(255, 255, 255, 255))
    d.ellipse((110, 120, 126, 136), fill=(255, 255, 255, 255))
    return im


def with_dot(im, color):
    im = im.copy()
    d = ImageDraw.Draw(im)
    d.ellipse((150, 150, 246, 246), fill=color, outline=(255, 255, 255, 255), width=12)
    return im


# ------------------------------------------------------------------ iconitele modulelor
W = (255, 255, 255, 255)


def g_menu(d):          # sigla: curbe de nivel + statie
    contours(d, 128, 134, (52, 92), W, 12)
    d.polygon([(128, 108), (150, 148), (106, 148)], fill=W)


def g_doc(d):           # anexe: document cu randuri si stampila
    d.rounded_rectangle((70, 46, 186, 210), radius=14, outline=W, width=13)
    for y in (90, 118, 146):
        d.line((96, y, 160, y), fill=W, width=12)
    d.ellipse((132, 158, 196, 222), fill=W)
    d.ellipse((148, 174, 180, 206), fill=(0, 0, 0, 0))


def g_tin(d):           # teren: retea de triunghiuri
    p = [(52, 190), (112, 70), (176, 112), (206, 196), (128, 160), (84, 128)]
    for a, b in ((0, 5), (5, 1), (1, 2), (2, 3), (3, 4), (4, 0), (5, 4), (4, 2), (1, 4), (5, 0)):
        d.line(p[a] + p[b], fill=W, width=10)
    for x, y in p:
        d.ellipse((x - 14, y - 14, x + 14, y + 14), fill=W)


def g_check(d):         # verificare: scut cu bifa
    d.polygon([(128, 40), (204, 70), (196, 150), (128, 216), (60, 150), (52, 70)], outline=W, width=13)
    d.line([(90, 128), (118, 158), (170, 100)], fill=W, width=18, joint="curve")


def g_pdf(d):           # planse PDF
    d.polygon([(70, 40), (156, 40), (190, 74), (190, 216), (70, 216)], outline=W, width=13)
    d.line([(150, 40), (150, 80), (190, 80)], fill=W, width=12)
    f = ImageFont.truetype(FONT, 50)
    d.text((130, 160), "PDF", font=f, fill=W, anchor="mm")


def g_globe(d):         # KMZ: glob cu marcaj
    d.ellipse((46, 66, 190, 210), outline=W, width=12)
    d.ellipse((90, 66, 146, 210), outline=W, width=9)
    d.line((46, 138, 190, 138), fill=W, width=9)
    d.ellipse((150, 30, 222, 102), fill=W)
    d.polygon([(158, 86), (214, 86), (186, 130)], fill=W)
    d.ellipse((174, 54, 198, 78), fill=(0, 0, 0, 0))


def g_frame(d):         # cadru plansa cu indicator
    d.rectangle((44, 58, 212, 198), outline=W, width=12)
    d.rectangle((66, 78, 190, 178), outline=W, width=6)
    d.rectangle((132, 146, 190, 178), fill=W)


def g_dwgkmz(d):        # transformator DWG -> KMZ: foaie de desen, sageata, glob
    d.rectangle((30, 58, 112, 168), outline=W, width=10)
    d.line((48, 140, 70, 96, 94, 128), fill=W, width=8, joint="curve")
    f = ImageFont.truetype(FONT, 26)
    d.text((71, 196), "DWG", font=f, fill=W, anchor="mm")
    d.line((122, 112, 150, 112), fill=W, width=10)
    d.polygon([(146, 96), (166, 112), (146, 128)], fill=W)
    d.ellipse((168, 76, 238, 146), outline=W, width=9)
    d.ellipse((190, 76, 216, 146), outline=W, width=6)
    d.line((168, 111, 238, 111), fill=W, width=6)
    d.text((203, 196), "KMZ", font=f, fill=W, anchor="mm")


def g_incl(d):          # calcul inclinatie: siloz aplecat fata de verticala
    d.line((96, 36, 96, 214), fill=W, width=8)                     # verticala de referinta
    d.line((70, 214, 200, 214), fill=W, width=10)                  # baza
    d.polygon([(104, 206), (160, 206), (194, 60), (138, 60)], outline=W, width=11)   # corpul aplecat
    d.line((138, 60, 166, 34, 194, 60), fill=W, width=10, joint="curve")             # acoperisul
    for y in (110, 160):
        x = 104 + (206 - y) * (138 - 104) / (206 - 60)
        d.line((96, y, x, y), fill=W, width=6)                     # abaterile
    d.ellipse((88, 198, 104, 214), fill=W)


def g_det(d):           # detasare: parcela taiata de o linie, partea detasata hasurata
    poly = [(40, 196), (52, 60), (210, 48), (220, 200)]
    d.polygon(poly, outline=W, width=11)
    for k in range(5):                                   # hasura pe partea detasata (stanga)
        x = 62 + k * 18
        d.line((x, 186, x + 40, 78), fill=W, width=5)
    for k in range(6):                                   # linia de detasare, punctata
        y0 = 40 + k * 30
        d.line((150 - (y0 - 40) * 0.05, y0, 150 - (y0 - 22) * 0.05, y0 + 18), fill=W, width=10)


def g_sup(d):           # suprafete: poligon cu "S=" si cote pe laturi
    d.polygon([(44, 190), (60, 70), (200, 52), (214, 196)], outline=W, width=11)
    f = ImageFont.truetype(FONT, 54)
    d.text((130, 132), "S=", font=f, fill=W, anchor="mm")
    d.line((60, 222, 200, 222), fill=W, width=7)
    for x in (60, 200):
        d.line((x, 210, x, 234), fill=W, width=7)


def g_vertex(d):        # vertexuri pe polilinie
    p = [(44, 176), (98, 92), (152, 156), (212, 72)]
    d.line(p, fill=W, width=12, joint="curve")
    for i, (x, y) in enumerate(p):
        r = 20 if i in (1, 2) else 14
        d.rectangle((x - r, y - r, x + r, y + r), fill=W)


def g_detmult(d):       # detasare multipla: parcela taiata in fasii, fasiile alternative hasurate
    d.polygon([(36, 200), (50, 58), (214, 46), (222, 204)], outline=W, width=11)
    for x0 in (58, 160):                                 # hasura pe fasiile 1 si 3
        for k in range(3):
            x = x0 + 8 + k * 14
            d.line((x, 190, x + 22, 66), fill=W, width=5)
    for xc in (104, 152):                                # liniile de detasare, punctate
        for k in range(6):
            y0 = 40 + k * 30
            d.line((xc, y0, xc + 1, y0 + 18), fill=W, width=10)


def g_points(d):        # raportare puncte: fisier cu randuri si puncte raportate
    d.rounded_rectangle((34, 44, 120, 176), radius=10, outline=W, width=11)
    for y in (82, 110, 138):
        d.line((56, y, 98, y), fill=W, width=10)
    d.line((132, 112, 168, 112), fill=W, width=10)
    d.polygon([(166, 96), (190, 112), (166, 128)], fill=W)
    for x, y in ((206, 62), (186, 168), (226, 132), (206, 210)):
        d.ellipse((x - 15, y - 15, x + 15, y + 15), outline=W, width=8)
        d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=W)


def g_cote(d):          # cote laturi: poligon cu linie de cota si capete
    d.polygon([(46, 150), (66, 52), (206, 64), (214, 150)], outline=W, width=11)
    d.line((46, 200, 214, 200), fill=W, width=8)
    for x in (46, 214):
        d.line((x, 178, x, 222), fill=W, width=8)
    d.polygon([(50, 200), (80, 188), (80, 212)], fill=W)
    d.polygon([(210, 200), (180, 188), (180, 212)], fill=W)
    d.text((130, 108), "12.5", font=ImageFont.truetype(FONT, 44), fill=W, anchor="mm")


def g_gear(d):          # setari cadastru: roata dintata peste o parcela
    cx, cy, r = 128, 128, 92
    pts = []
    for i in range(48):
        a = 2 * math.pi * i / 48 + math.pi / 48
        rr = r if (i % 4) in (0, 1) else r * 0.76
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=W)
    d.ellipse((cx - 44, cy - 44, cx + 44, cy + 44), fill=(0, 0, 0, 0))
    d.polygon([(cx - 22, cy + 18), (cx - 14, cy - 22), (cx + 22, cy - 18), (cx + 18, cy + 20)], fill=W)


def g_proiect(d):       # proiect nou: foaie cu straturile standard (benzi) si plus
    d.rounded_rectangle((40, 30, 170, 214), radius=12, outline=W, width=11)
    for i, y in enumerate((70, 104, 138, 172)):
        d.rectangle((62, y - 9, 80, y + 9), fill=W)
        d.line((94, y, 148, y), fill=W, width=9)
    d.ellipse((150, 140, 238, 228), fill=W)
    d.line((194, 158, 194, 210), fill=(0, 0, 0, 0), width=12)
    d.line((168, 184, 220, 184), fill=(0, 0, 0, 0), width=12)


def g_scara(d):         # scara planului: rigla si 1:500
    d.text((128, 80), "1:500", font=ImageFont.truetype(FONT, 66), fill=W, anchor="mm")
    d.rounded_rectangle((26, 140, 230, 214), radius=8, outline=W, width=10)
    for i, x in enumerate(range(52, 214, 26)):
        d.line((x, 140, x, 168 if i % 2 else 184), fill=W, width=8)


def g_caroiaj(d):       # caroiaj: colturi in L cu coordonate si cruciulite
    for x, y, sx, sy in ((40, 40, 1, 1), (216, 40, -1, 1), (40, 216, 1, -1), (216, 216, -1, -1)):
        d.line((x + sx * 62, y, x, y, x, y + sy * 62), fill=W, width=11, joint="curve")
    for x, y in ((100, 100), (156, 100), (100, 156), (156, 156)):
        d.line((x - 20, y, x + 20, y), fill=W, width=9)
        d.line((x, y - 20, x, y + 20), fill=W, width=9)


def g_pct(d):           # introducere puncte: simbol de punct cu numar si plus
    d.ellipse((46, 70, 146, 170), outline=W, width=12)
    d.ellipse((84, 108, 108, 132), fill=W)
    d.text((176, 74), "12", font=ImageFont.truetype(FONT, 56), fill=W, anchor="mm")
    d.line((190, 150, 190, 226), fill=W, width=14)
    d.line((152, 188, 228, 188), fill=W, width=14)


# aceeasi ordine ca TILES din installer/launcher/ui.c
MODULES = [("#0F7C6E", g_proiect), ("#B07D12", g_scara), ("#5A6B7C", g_caroiaj),
           ("#1B6A8F", g_menu), ("#6A4FB6", g_doc), ("#2E8B57", g_tin), ("#D08A12", g_check),
           ("#C8443A", g_pdf), ("#1F8FBF", g_globe), ("#0E8C7F", g_dwgkmz), ("#3B5B92", g_frame),
           ("#A3478F", g_vertex), ("#E0662A", g_incl), ("#B5562E", g_det), ("#4F7A2A", g_sup),
           ("#C0392B", g_detmult), ("#2F6FB5", g_points), ("#D0453A", g_pct), ("#8A6A2E", g_cote),
           ("#55657A", g_gear)]


def module_icon(color, glyph):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = hexc(color)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=64, fill=c + (255,))
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glyph(ImageDraw.Draw(layer))
    # "gaurile" (alfa 0) din glifa devin culoarea fundalului
    mask = layer.split()[3]
    im.paste(Image.new("RGBA", (S, S), W), (0, 0), mask)
    return im.resize((96, 96), Image.LANCZOS)


def gradient(w, h, c1, c2, vertical=True):
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            t = (y / (h - 1)) if vertical else (x / (w - 1))
            px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    return im


def installer_art(lg):
    # pagina de bun venit / final (164x314), desenata la 2x
    w, h = 328, 628
    im = gradient(w, h, NAVY, TEAL).convert("RGBA")
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    contours(od, 250, 520, (60, 110, 160, 210, 260), (255, 255, 255, 38), 4)
    contours(od, 40, 110, (50, 95, 140), (255, 255, 255, 26), 4, k0=2)
    im = Image.alpha_composite(im, ov)
    im.alpha_composite(lg.resize((132, 132), Image.LANCZOS), (98, 150))
    d = ImageDraw.Draw(im)
    d.text((w // 2, 330), "TopoKit", font=ImageFont.truetype(FONT, 50), fill=W, anchor="mm")
    sub = ImageFont.truetype(FONT_R, 22)
    for i, t in enumerate(("Topografie și cadastru", "pentru AutoCAD")):
        d.text((w // 2, 378 + 30 * i), t, font=sub, fill=(220, 236, 246, 255), anchor="mm")
    d.line((w // 2 - 40, 446, w // 2 + 40, 446), fill=RED + (255,), width=4)
    im.convert("RGB").resize((164, 314), Image.LANCZOS).save(ART / "welcome.bmp")
    # antetul paginilor (150x57), la dreapta pe fundal alb
    w, h = 300, 114
    im = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    contours(ImageDraw.Draw(ov), 250, 60, (30, 56, 82, 108), TEAL + (40,), 3)
    im = Image.alpha_composite(im, ov)
    im.alpha_composite(lg.resize((76, 76), Image.LANCZOS), (206, 19))
    im.convert("RGB").resize((150, 57), Image.LANCZOS).save(ART / "header.bmp")


import sys
if "--modules" in sys.argv:          # doar iconitele modulelor (m1..m20), restul graficii ramane
    for i, (c, g) in enumerate(MODULES, 1):
        module_icon(c, g).save(OUT / "icons" / f"m{i}.png")
    print("Iconitele modulelor generate in", OUT / "icons")
    sys.exit(0)

sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
b = logo()
b.save(OUT / "topokit.ico", sizes=sizes)
with_dot(b, (46, 190, 80, 255)).save(OUT / "tray_on.ico", sizes=sizes[:7])
with_dot(b, (150, 150, 150, 255)).save(OUT / "tray_off.ico", sizes=sizes[:7])
b.resize((128, 128), Image.LANCZOS).save(OUT / "logo.png")
b.resize((128, 128), Image.LANCZOS).save(ROOT / "docs" / "topokit_icon.png")
for i, (c, g) in enumerate(MODULES, 1):
    module_icon(c, g).save(OUT / "icons" / f"m{i}.png")
installer_art(b)
print("Grafica generata in", OUT, "si", ART)
