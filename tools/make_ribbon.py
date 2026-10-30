#!/usr/bin/env python3
r"""Genereaza meniul partial AutoCAD TopoKit.cuix: tabul "TopoKit" din ribbon, cu cate un
buton (si o iconita proprie, 16 si 32 px) pentru fiecare comanda TopoKit.

    python3 tools/make_ribbon.py [--out build] [--png folder] [--preview plansa.png]

Scrie TopoKit.cuix (romana) si TopoKit_EN.cuix (engleza); incarcatorul TopoKitLoad.lsp
il incarca pe cel potrivit limbii alese (HKCU\Software\TopoKit\Language).

Fisierul .cuix este o arhiva zip (OPC) cu:
    MenuGroup.cui      macro-urile (numele, comanda, descrierea, iconitele)
    RibbonRoot.cui     panourile si tabul "TopoKit"
    Header.cui, WorkspaceRoot.cui, ToolbarRoot.cui, PopMenuRoot.cui   (goale)
    TK_16_<CMD>.png, TK_32_<CMD>.png
Iconitele sunt desenate pentru ambele teme (culori medii, contur gri).
"""
import argparse, io, math, pathlib, zipfile
from xml.sax.saxutils import escape
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
if not pathlib.Path(FONT).exists():         # Windows: Arial in locul Liberation Sans
    FONT = "arialbd.ttf"

# ------------------------------------------------------------------ paleta
BL, BL2 = (52, 136, 222, 255), (150, 196, 240, 255)
OR, OR2 = (236, 132, 34, 255), (248, 192, 120, 255)
GR, GR2 = (60, 164, 80, 255), (150, 214, 150, 255)
RD = (218, 64, 54, 255)
PU, PU2 = (146, 96, 212, 255), (200, 176, 236, 255)
TE = (24, 156, 156, 255)
GY, GY2 = (122, 136, 150, 255), (190, 198, 206, 255)
YE = (238, 186, 36, 255)
BR, BR2 = (160, 104, 58, 255), (222, 186, 150, 255)
PAPER = (250, 250, 250, 255)
WH = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)


class Canvas:
    """Desen intr-un sistem de 32 x 32 unitati, randat la 8x si redus la n pixeli."""

    def __init__(self, n):
        self.n, self.R = n, n * 8
        self.k = self.R / 32.0
        self.wm = 1.45 if n <= 16 else 1.0         # linii mai groase la 16 px
        self.im = Image.new("RGBA", (self.R, self.R), CLEAR)
        self.d = ImageDraw.Draw(self.im)

    def P(self, pts): return [(x * self.k, y * self.k) for x, y in pts]
    def W(self, u): return max(1, int(round(u * self.k * self.wm)))

    def line(self, pts, col=GY, u=1.5):
        self.d.line(self.P(pts), fill=col, width=self.W(u), joint="curve")
        r = self.W(u) / 2.0                                   # capete rotunjite
        for x, y in self.P([pts[0], pts[-1]]):
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=col)

    def poly(self, pts, fill=None, out=None, u=1.5):
        if fill: self.d.polygon(self.P(pts), fill=fill)
        if out: self.line(list(pts) + [pts[0]], out, u)

    def rect(self, x0, y0, x1, y1, fill=None, out=None, u=1.5, r=0):
        b = (x0 * self.k, y0 * self.k, x1 * self.k, y1 * self.k)
        self.d.rounded_rectangle(b, radius=r * self.k, fill=fill,
                                 outline=out, width=self.W(u) if out else 0)

    def circ(self, x, y, r, fill=None, out=None, u=1.5):
        b = ((x - r) * self.k, (y - r) * self.k, (x + r) * self.k, (y + r) * self.k)
        self.d.ellipse(b, fill=fill, outline=out, width=self.W(u) if out else 0)

    def arc(self, x, y, r, a0, a1, col, u=1.8):
        b = ((x - r) * self.k, (y - r) * self.k, (x + r) * self.k, (y + r) * self.k)
        self.d.arc(b, a0, a1, fill=col, width=self.W(u))

    def text(self, x, y, t, size, col, anchor="mm"):
        f = ImageFont.truetype(FONT, int(size * self.k))
        self.d.text((x * self.k, y * self.k), t, font=f, fill=col, anchor=anchor)

    def hatch(self, pts, col, step=3.2, u=0.9):
        lay = Image.new("RGBA", self.im.size, CLEAR)
        ld = ImageDraw.Draw(lay)
        for i in range(-12, 24):
            x = i * step
            ld.line((x * self.k, 34 * self.k, (x + 34) * self.k, 0), fill=col, width=self.W(u))
        m = Image.new("L", self.im.size, 0)
        ImageDraw.Draw(m).polygon(self.P(pts), fill=255)
        a = Image.composite(lay, Image.new("RGBA", self.im.size, CLEAR), m)
        self.im.alpha_composite(a)
        self.d = ImageDraw.Draw(self.im)

    def arrow(self, x0, y0, x1, y1, col, u=2.0, head=4.5):
        a = math.atan2(y1 - y0, x1 - x0)
        bx, by = x1 - head * 0.8 * math.cos(a), y1 - head * 0.8 * math.sin(a)
        self.line([(x0, y0), (bx, by)], col, u)
        l = (x1 - head * math.cos(a) + head * 0.6 * math.sin(a), y1 - head * math.sin(a) - head * 0.6 * math.cos(a))
        r = (x1 - head * math.cos(a) - head * 0.6 * math.sin(a), y1 - head * math.sin(a) + head * 0.6 * math.cos(a))
        self.poly([(x1, y1), l, r], fill=col)

    def result(self):
        return self.im.resize((self.n, self.n), Image.LANCZOS)


# ------------------------------------------------------------------ elemente comune
PAR = [(3, 25), (6, 6), (21, 3), (29, 14), (25, 29)]           # parcela


def paper(c, x0=5, y0=2, x1=24, y1=29, lines=True):
    c.poly([(x0, y0), (x1 - 5, y0), (x1, y0 + 5), (x1, y1), (x0, y1)], fill=PAPER, out=GY, u=1.3)
    c.poly([(x1 - 5, y0), (x1 - 5, y0 + 5), (x1, y0 + 5)], fill=GY2, out=GY, u=1.0)
    if lines:
        for y in range(int(y0 + 9), int(y1 - 3), 4):
            c.line([(x0 + 3.5, y), (x1 - 3.5, y)], GY2, 1.4)


def sheet(c):                                       # plansa in format landscape
    c.rect(1.5, 5, 30.5, 27, fill=PAPER, out=GY, u=1.3)
    c.rect(20, 21.5, 29, 25.5, fill=BL2)


def pointsym(c, x, y, r=4.5, col=RD):
    c.circ(x, y, r, out=col, u=1.8)
    c.circ(x, y, r * 0.32, fill=col)


def dot(c, x, y, r=2.2, col=RD): c.circ(x, y, r, fill=col)


def gear(c, x, y, r, col):
    pts, n = [], 8
    for i in range(n * 4):
        a = 2 * math.pi * i / (n * 4) + math.pi / (n * 4)
        rr = r if (i % 4) in (0, 1) else r * 0.74
        pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
    c.poly(pts, fill=col)
    c.circ(x, y, r * 0.34, fill=CLEAR)


def badge(c, kind, col=None):
    x, y, r = 24.5, 24.5, 7
    if kind == "plus":
        c.circ(x, y, r, fill=col or GR)
        c.line([(x - 3.5, y), (x + 3.5, y)], WH, 2.0); c.line([(x, y - 3.5), (x, y + 3.5)], WH, 2.0)
    elif kind == "x":
        c.circ(x, y, r, fill=col or RD)
        c.line([(x - 3, y - 3), (x + 3, y + 3)], WH, 2.0); c.line([(x - 3, y + 3), (x + 3, y - 3)], WH, 2.0)
    elif kind == "gear":
        c.circ(x, y, r + 0.6, fill=CLEAR); gear(c, x, y, r, col or OR)
    elif kind == "check":
        c.circ(x, y, r, fill=col or GR)
        c.line([(x - 3.5, y + 0.2), (x - 0.8, y + 3), (x + 3.8, y - 2.6)], WH, 2.0)
    elif kind == "down":
        c.circ(x, y, r, fill=col or GR); c.arrow(x, y - 4.5, x, y + 4.5, WH, 2.0, 4.2)
    elif kind == "up":
        c.circ(x, y, r, fill=col or BL); c.arrow(x - 3.2, y + 3.2, x + 3.6, y - 3.6, WH, 2.0, 4.2)
    elif kind == "info":
        c.circ(x, y, r, fill=col or BL); c.text(x, y + 0.6, "i", 10, WH)
    elif kind == "cursor":
        c.poly([(x - 4, y - 6), (x + 5, y + 1.5), (x + 0.6, y + 2), (x + 3, y + 6.5),
                (x + 0.8, y + 7.4), (x - 1.5, y + 3), (x - 4, y + 5.5)], fill=WH, out=GY, u=1.0)


def globe(c, x, y, r, col=BL):
    c.circ(x, y, r, fill=col)
    c.arc(x, y, r * 0.98, 0, 360, WH, 1.0)
    c.d.ellipse(((x - r * 0.45) * c.k, (y - r) * c.k, (x + r * 0.45) * c.k, (y + r) * c.k),
                outline=WH, width=c.W(1.0))
    c.line([(x - r, y), (x + r, y)], WH, 1.0)
    c.line([(x - r * 0.85, y - r * 0.5), (x + r * 0.85, y - r * 0.5)], WH, 0.8)
    c.line([(x - r * 0.85, y + r * 0.5), (x + r * 0.85, y + r * 0.5)], WH, 0.8)


def silo(c, x, y, ang=10, col=OR):                   # siloz inclinat (baza in x,y)
    a = math.radians(ang)
    ux, uy = math.sin(a), -math.cos(a)
    h, w = 22, 5.5
    pts = [(x - w, y), (x + w, y), (x + w + ux * h, y + uy * h), (x - w + ux * h, y + uy * h)]
    c.poly(pts, fill=col, out=BR, u=1.0)
    c.line([(x, y + 1), (x, y - h - 1)], GY, 1.0)
    c.arc(x, y, 12, -90, -90 + ang, RD, 1.6)


def wavy(c, cx, cy, r, col, u=1.6, k0=0, sx=1.0, sy=0.8):
    pts = []
    for i in range(49):
        a = 2 * math.pi * i / 48
        rr = r * (1 + 0.13 * math.sin(3 * a + k0))
        pts.append((cx + sx * rr * math.cos(a), cy + sy * rr * math.sin(a)))
    c.line(pts, col, u)


# ------------------------------------------------------------------ iconitele comenzilor
def i_topokit(c):
    c.rect(1.5, 1.5, 30.5, 30.5, fill=(27, 106, 143, 255), r=7)
    wavy(c, 15, 17, 6.5, (190, 225, 245, 255), 1.4)
    wavy(c, 15, 17, 11.5, (190, 225, 245, 255), 1.4, 1)
    c.poly([(15, 9.5), (20, 18.5), (10, 18.5)], fill=(228, 72, 58, 255), out=WH, u=0.8)


def i_set(c): gear(c, 16, 16, 13.5, BL)


def i_cadset(c):
    c.poly(PAR, fill=GR2, out=GY, u=1.4)
    badge(c, "gear", OR)


def i_mytopo(c):
    c.rect(2, 3, 30, 29, fill=PAPER, out=GY, u=1.3, r=2)
    c.rect(2, 3, 30, 8, fill=BL)
    for i, col in enumerate((OR, GR, PU)):
        y = 13 + i * 5.5
        c.rect(6, y - 1.8, 9.6, y + 1.8, fill=col)
        c.line([(12.5, y), (26, y)], GY, 1.6)


def i_reload(c):
    c.arc(16, 16, 11, 200, 520 - 40, GR, 3.0)
    c.poly([(26.5, 4), (28.8, 14.5), (18.5, 12)], fill=GR)


def i_tkcad(c):
    paper(c, 4, 2, 23, 29)
    badge(c, "info")


def i_pct(c):
    pointsym(c, 12, 13, 6.5)
    c.text(19, 6, "12", 8.5, GY, "lm")
    badge(c, "plus")


def i_pctcontur(c):
    c.poly(PAR, out=GY, u=1.5)
    for x, y in PAR: dot(c, x, y, 2.6)


def i_imppct(c):
    paper(c, 2, 2, 15, 22)
    c.arrow(12, 24, 20, 24, BL, 2.2, 5)
    for x, y in ((24, 9), (29, 15), (22, 18), (27, 26)): dot(c, x, y, 2.3)


def i_exppct(c):
    for x, y in ((4, 8), (9, 4), (5, 15), (10, 13)): dot(c, x, y, 2.3)
    c.arrow(7, 20, 15, 26, BL, 2.2, 5)
    paper(c, 17, 4, 30, 29)


def i_stergpct(c):
    pointsym(c, 12, 12, 7)
    badge(c, "x")


def i_renum(c):
    c.text(16, 10, "123", 13, BL)
    c.arc(16, 19, 10, 20, 160, OR, 2.2)
    c.poly([(4.5, 21), (8.8, 27.5), (11, 20.5)], fill=OR)


def i_selcod(c):
    for x, y in ((5, 6), (12, 4), (6, 13), (26, 5)): dot(c, x, y, 2.2)
    c.circ(14, 15, 7, fill=(255, 255, 255, 120), out=BL, u=2.2)
    dot(c, 14, 15, 2.2)
    c.line([(19.5, 20.5), (28, 29)], BL, 3.4)


def i_schcod(c):
    c.poly([(3, 9), (9, 3), (21, 3), (21, 15), (9, 15)], fill=OR2, out=OR, u=1.4)
    c.circ(9.5, 9, 1.7, fill=OR)
    c.arc(17, 18, 9, 10, 100, BL, 2.0)
    c.poly([(9.5, 28.5), (14, 24), (14.5, 29.5)], fill=BL)
    c.arc(16, 17, 9, 190, 280, BL, 2.0)
    c.poly([(22.5, 6.5), (18, 11), (17.5, 5.5)], fill=BL)


def i_teren_imp(c):
    paper(c, 2, 2, 14, 19, lines=False)
    c.text(8, 13, "XYZ", 4.6, GY)
    c.arrow(9, 21, 15, 26, GR, 2.0, 4.5)
    pts = [(16, 28), (20, 18), (25, 22), (30, 11)]
    c.line(pts, GR, 1.8)
    for x, y in pts: dot(c, x, y, 2.0, RD)


def i_tabpct(c):
    c.rect(2, 4, 30, 28, fill=PAPER, out=GY, u=1.3)
    c.rect(2, 4, 30, 10, fill=BL)
    for y in (16, 22): c.line([(3, y), (29, y)], GY2, 1.2)
    for x in (10, 20): c.line([(x, 10), (x, 27)], GY2, 1.2)


def i_legenda(c):
    c.rect(2, 2, 30, 30, fill=PAPER, out=GY, u=1.3)
    c.circ(8, 9, 3.2, fill=GR)
    c.rect(4.8, 13.8, 11.2, 19.2, fill=OR)
    c.line([(4.5, 24.5), (11.5, 24.5)], RD, 2.2)
    for y in (9, 16.5, 24.5): c.line([(14.5, y), (26.5, y)], GY, 1.6)


def i_det(c):
    left = [(3, 25), (6, 6), (12, 4.8), (14, 27)]
    c.poly(left, fill=OR2)
    c.hatch(left, OR)
    c.poly(PAR, out=GY, u=1.6)
    c.line([(12, 3.2), (14, 28.6)], RD, 2.2)


def i_detmult(c):
    s1 = [(3, 25), (6, 6), (10, 5.2), (10, 26.27)]
    s2 = [(10, 5.2), (18, 3.6), (18, 27.73), (10, 26.27)]
    s3 = [(18, 3.6), (21, 3), (29, 14), (25, 29), (18, 27.73)]
    c.poly(s1, fill=OR2); c.poly(s2, fill=GR2); c.poly(s3, fill=BL2)
    c.hatch(s1, OR); c.hatch(s2, GR, 3.6)
    c.poly(PAR, out=GY, u=1.6)
    c.line([(10, 3.8), (10, 27.8)], RD, 2.0)
    c.line([(18, 2.2), (18, 29.2)], RD, 2.0)


def i_supraf(c):
    c.poly(PAR, fill=GR2, out=GY, u=1.5)
    c.text(16, 16.5, "S=", 12, (30, 110, 45, 255))


def i_cote(c):
    c.poly([(4, 18), (8, 4), (26, 6), (28, 18)], fill=PAPER, out=GY, u=1.5)
    c.line([(4, 25), (28, 25)], BL, 1.5)
    for x in (4, 28): c.line([(x, 21.5), (x, 28.5)], BL, 1.5)
    c.poly([(4.5, 25), (9, 23), (9, 27)], fill=BL); c.poly([(27.5, 25), (23, 23), (23, 27)], fill=BL)
    c.text(16, 13, "12.5", 7.5, BL)


def i_suma(c):
    c.line([(25, 6), (25, 4), (7, 4), (17, 16), (7, 28), (25, 28), (25, 26)], PU, 3.2)


def i_addvtx(c):
    c.line([(3, 24), (14, 8), (29, 14)], GY, 1.8)
    c.line([(5, 6), (27, 27)], BL, 1.8)
    for x, y in ((3, 24), (14, 8), (29, 14), (5, 6), (27, 27)): c.rect(x - 1.6, y - 1.6, x + 1.6, y + 1.6, fill=GY)
    c.rect(6.8, 8.7, 12.4, 14.3, fill=OR)                 # vertexul nou, la intersectie


def i_anexe(c):
    paper(c, 4, 2, 24, 29)
    c.circ(23, 23, 6.5, fill=PU)
    c.circ(23, 23, 3.4, fill=CLEAR)
    c.circ(23, 23, 2.2, fill=PU2)


def i_imobil(c):
    c.poly([(3, 15), (14, 4), (25, 15), (25, 28), (3, 28)], fill=BL2, out=BL, u=1.6)
    c.rect(11, 18, 17, 28, fill=PAPER, out=BL, u=1.2)
    badge(c, "info", PU)


def i_executant(c):
    c.circ(13, 9, 5.5, fill=TE)
    c.d.pieslice(((3) * c.k, 15 * c.k, 23 * c.k, 37 * c.k), 180, 360, fill=TE)
    c.line([(18, 30), (29, 19)], OR, 3.0)
    c.poly([(16.2, 31.8), (17.2, 28.2), (19.8, 30.8)], fill=GY)


def i_vecini(c):
    for b in ((2, 2, 12, 12), (13, 2, 30, 12), (2, 13, 12, 30), (13, 23, 30, 30), (23, 13, 30, 22)):
        c.rect(*b, fill=PAPER, out=GY, u=1.2)
    c.rect(13, 13, 22, 22, fill=OR, out=BR, u=1.2)


def i_constr(c):
    pts = [(4, 8), (20, 8), (20, 14), (28, 14), (28, 27), (4, 27)]
    c.poly(pts, fill=BR2)
    c.hatch(pts, BR, 3.0, 1.0)
    c.poly(pts, out=BR, u=1.8)
    c.rect(7, 11, 17, 17.5, fill=PAPER)
    c.text(12, 14.4, "C1", 6.0, BR)


def i_word(c):
    paper(c, 3, 2, 22, 29)
    c.line([(15, 28), (28.5, 14.5)], OR, 3.0)
    c.poly([(13.2, 30.2), (13.9, 26.6), (16.6, 29.4)], fill=GY)
    c.line([(26.3, 12.3), (30, 16)], RD, 3.0)


def i_verif(c):
    c.poly([(16, 2), (28, 6), (27, 18), (16, 30), (5, 18), (4, 6)], fill=GR)
    c.line([(10, 16), (14.5, 21), (22.5, 11)], WH, 2.8)


def i_pad(c):
    sheet(c)
    c.poly([(5, 20), (7, 8), (16, 7.5), (18, 19)], fill=OR2, out=OR, u=1.4)


def i_paddez(c):
    sheet(c)
    a, b = [(5, 20), (7, 8), (11.5, 7.75), (12.5, 19.5)], [(11.5, 7.75), (16, 7.5), (18, 19), (12.5, 19.5)]
    c.poly(a, fill=OR2); c.poly(b, fill=GR2)
    c.poly([(5, 20), (7, 8), (16, 7.5), (18, 19)], out=GY, u=1.3)
    c.line([(11.5, 6.6), (12.6, 20.8)], RD, 1.6)


def i_padalip(c):
    sheet(c)
    c.poly([(4, 20), (5, 8.5), (11, 8), (11, 19.5)], fill=OR2, out=OR, u=1.2)
    c.poly([(11, 8), (17, 7.5), (18, 19), (11, 19.5)], fill=OR2, out=OR, u=1.2)
    badge(c, "plus")


def i_releveu(c):
    c.rect(2, 4, 30, 28, fill=PAPER)
    c.rect(2.5, 4.5, 15, 17, fill=BL2)
    c.rect(2, 4, 30, 28, out=GY, u=2.4)
    c.line([(15, 4), (15, 11)], GY, 2.0); c.line([(15, 15), (15, 28)], GY, 2.0)
    c.line([(2, 17), (10, 17)], GY, 2.0); c.line([(15, 17), (22, 17)], GY, 2.0)
    c.line([(26, 17), (30, 17)], GY, 2.0)


def i_pdf(c):
    paper(c, 5, 2, 26, 29, lines=False)
    for y in (8, 12): c.line([(8.5, y), (19, y)], GY2, 1.4)
    c.rect(2, 16, 22, 26, fill=RD, r=1.5)
    c.text(12, 21.2, "PDF", 7.2, WH)


def i_cadru(c):
    c.rect(1.5, 4, 30.5, 28, fill=PAPER, out=GY, u=1.3)
    c.rect(4, 6.5, 28, 25.5, out=GY, u=1.0)
    c.rect(18, 20, 28, 25.5, fill=BL2, out=BL, u=1.0)
    c.line([(18, 22.7), (28, 22.7)], BL, 0.8)


def i_tin(c):
    p = [(3, 27), (9, 9), (18, 4), (29, 12), (27, 28), (16, 18)]
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 4), (4, 0), (5, 0), (5, 1), (5, 2), (5, 3), (5, 4)):
        c.line([p[a], p[b]], GR, 1.5)
    for x, y in p: dot(c, x, y, 1.9)


def i_curbe(c):
    wavy(c, 16, 16, 13, BR, 1.6)
    wavy(c, 16.5, 16, 8.5, OR, 1.6, 1)
    wavy(c, 17, 16, 4, BR, 1.6, 2)


def i_volum(c):
    prof = [(2, 20), (7, 9), (12, 13), (17, 5), (23, 22), (27, 25), (30, 19)]
    c.poly([(2, 16)] + prof[1:4] + [(19.5, 16)], fill=OR2)
    c.poly([(19.5, 16), (23, 22), (27, 25), (30, 19), (30, 16)], fill=BL2)
    c.line(prof, GR, 1.8)
    c.line([(1.5, 16), (30.5, 16)], RD, 1.6)
    c.text(10, 27, "+/-", 7.5, GY)


def i_volum2(c):
    up = [(2, 12), (9, 6), (16, 10), (23, 4), (30, 9)]
    lo = [(2, 22), (9, 19), (16, 24), (23, 20), (30, 25)]
    c.poly(up + lo[::-1], fill=OR2)
    c.hatch(up + lo[::-1], OR)
    c.line(up, GR, 1.8); c.line(lo, BL, 1.8)


def i_teren(c):
    c.poly([(1.5, 27), (11, 9), (16, 16), (21, 6), (30.5, 27)], fill=GR2, out=GR, u=1.6)
    for x, y in ((11, 9), (21, 6), (16, 16), (7, 20)): dot(c, x, y, 1.9)


def i_georef(c):
    c.rect(2, 4, 26, 24, fill=BL2, out=GY, u=1.3)
    c.poly([(3, 23), (11, 13), (16, 18), (20, 14), (25, 23)], fill=GR)
    c.circ(20, 9, 2.4, fill=YE)
    c.circ(24, 24, 5.5, out=RD, u=1.5)
    c.line([(24, 16.5), (24, 31.5)], RD, 1.3); c.line([(16.5, 24), (31.5, 24)], RD, 1.3)


def i_impkml(c):
    globe(c, 13, 13, 11)
    badge(c, "down")


def i_harta(c):
    c.poly([(2, 8), (11, 5), (21, 8), (30, 5), (30, 27), (21, 30), (11, 27), (2, 30)], fill=GR2, out=GY, u=1.2)
    c.line([(11, 5), (11, 27)], GY, 1.0); c.line([(21, 8), (21, 30)], GY, 1.0)
    c.circ(16, 12, 6, fill=RD)
    c.poly([(10.8, 14.5), (21.2, 14.5), (16, 25)], fill=RD)
    c.circ(16, 12, 2.4, fill=WH)


def i_expkmz(c):
    globe(c, 13, 13, 11)
    c.poly([(8, 16), (10, 8), (17, 7), (19, 15)], fill=OR, out=WH, u=1.0)
    badge(c, "up", OR)


def i_dwgkmz(c):
    paper(c, 2, 2, 17, 22, lines=False)
    c.text(9.5, 14, "DWG", 5.0, BL)
    c.arrow(11, 25, 17.5, 25, GY, 1.8, 4)
    globe(c, 24.5, 22, 7)


def i_inclinare(c): silo(c, 14, 28, 12)


def i_planincl(c):
    c.rect(2, 2, 30, 30, fill=PAPER, out=GY, u=1.3, r=2)
    c.rect(2, 2, 30, 7, fill=OR)
    silo(c, 13, 27, 12)


def i_planinclsel(c):
    silo(c, 11, 28, 12)
    for x, y in ((24, 5), (27, 11)): dot(c, x, y, 2.0)
    badge(c, "cursor")


def i_lang(c):
    c.rect(1.5, 3, 19, 17, fill=BL, r=2.5)
    c.poly([(5, 16), (5, 21), (10, 16)], fill=BL)
    c.text(10.2, 10.3, "RO", 8.2, WH)
    c.rect(12.5, 13, 30.5, 27, fill=OR, r=2.5)
    c.poly([(27, 26), (27, 31), (22, 26)], fill=OR)
    c.text(21.5, 20.3, "EN", 8.2, WH)


# ------------------------------------------------------------------ comenzile si ribbonul
# comanda: (eticheta RO, descriere RO, eticheta EN, descriere EN, iconita)
CMDS = {
    "TOPOKIT": ("Fereastra TopoKit", "Deschide fereastra TopoKit cu toate modulele",
                "TopoKit window", "Opens the TopoKit window with all modules", i_topokit),
    "TOPOKITSET": ("Setări module", "Toleranța corecției topologice, opțiunile KMZ, formatul și cadrul planșei",
                   "Module settings", "Topology tolerance, KMZ options, sheet format and frame", i_set),
    "TKCADSET": ("Setări cadastru", "Scara, înălțimile textelor (mm pe hârtie), zecimale, hașură - păstrate în desen",
                 "Cadastre settings", "Scale, text heights (mm on paper), decimals, hatch - saved in the drawing", i_cadset),
    "TOPOKITLANG": ("Limba: română / engleză", "Schimbă limba TopoKit (română / engleză)",
                    "Language: Romanian / English", "Switches the TopoKit language (Romanian / English)", i_lang),
    "MYTOPO": ("Meniul TopoKit", "Meniul cu module direct în AutoCAD (dialog)",
               "TopoKit menu", "Module menu inside AutoCAD (dialog)", i_mytopo),
    "TOPOKITRELOAD": ("Reîncarcă TopoKit", "Reîncarcă modulele TopoKit (după o actualizare)",
                      "Reload TopoKit", "Reloads the TopoKit modules (after an update)", i_reload),
    "TKCAD": ("Comenzi cadastru", "Lista comenzilor de cadastru în fereastra de text",
              "Cadastre commands", "Lists the cadastre commands in the text window", i_tkcad),
    "TKIMPPCT": ("Raportare puncte", "Raportează puncte din fișier (Nr X Y Z Cod), bloc „Punct” compatibil TopoLT",
                 "Draw points", "Draws points from a file (No X Y Z Code), TopoLT-compatible \"Punct\" block", i_imppct),
    "TKPCT": ("Introducere puncte", "Puncte noi cu număr, cotă și cod",
              "Insert points", "New points with number, elevation and code", i_pct),
    "TKPCTCONTUR": ("Puncte pe contur", "Puncte în vârfurile poliliniilor, fără dubluri",
                    "Points on outline", "Points at polyline vertices, without duplicates", i_pctcontur),
    "TKSTERGPCT": ("Șterge puncte", "Șterge punctele împreună cu textele legate",
                   "Delete points", "Deletes points together with their texts", i_stergpct),
    "TKRENUM": ("Renumerotare", "Renumerotează punctele (avertizează la numere dublate)",
                "Renumber points", "Renumbers points (warns about duplicate numbers)", i_renum),
    "TKSELCOD": ("Selecție după cod", "Selectează punctele care au un anumit cod",
                 "Select by code", "Selects the points that have a given code", i_selcod),
    "TKSCHCOD": ("Schimbă codul", "Schimbă codul punctelor selectate",
                 "Change code", "Changes the code of the selected points", i_schcod),
    "TKEXPPCT": ("Fișier coordonate", "Reface fișierul de coordonate din punctele desenului",
                 "Coordinates file", "Rebuilds the coordinates file from the drawing points", i_exppct),
    "IMPPCT": ("Import puncte teren", "Import puncte măsurate din TXT/CSV și desenare pe coduri",
               "Import survey points", "Imports surveyed points from TXT/CSV and draws them by code", i_teren_imp),
    "TABPCT": ("Tabel coordonate", "Tabel cu coordonatele punctelor selectate (Nr, X, Y, Z)",
               "Coordinates table", "Table with the coordinates of the selected points (No, X, Y, Z)", i_tabpct),
    "LEGENDA": ("Legendă", "Legenda semnelor convenționale din desen",
                "Legend", "Legend of the conventional signs in the drawing", i_legenda),
    "TKDETASARE": ("Detașare", "Detașează o suprafață: paralelă cu o latură, după o direcție, perpendiculară, prin punct obligat",
                   "Detachment", "Detaches an area: parallel to a side, along a direction, perpendicular, through a fixed point", i_det),
    "TKDETMULT": ("Detașare multiplă", "Mai multe parcele succesive dintr-un tabel (manual sau Excel / CSV)",
                  "Multiple detachment", "Several successive parcels from a table (manual or Excel / CSV)", i_detmult),
    "TKSUPRAF": ("Suprafețe", "S= în centrul fiecărui poligon închis, opțional hașură",
                 "Areas", "S= at the centre of each closed polygon, optional hatch", i_supraf),
    "TKCOTE": ("Cote laturi", "Lungimea fiecărei laturi, spre exteriorul poligonului",
               "Side lengths", "Length of each side, outside the polygon", i_cote),
    "TKSUMA": ("Suma textelor", "Suma numerelor din textele selectate",
               "Sum of texts", "Sum of the numbers in the selected texts", i_suma),
    "ADDVTX": ("Vertexi la intersecții", "Corecție topologică: vertexi la intersecțiile poliliniilor",
               "Vertices at intersections", "Topology fix: vertices at polyline intersections", i_addvtx),
    "ANEXE": ("Anexe ANCPI", "Generatorul de anexe - Ordinul ANCPI nr. 600/2023",
              "ANCPI annexes", "Annex generator - ANCPI Order no. 600/2023", i_anexe),
    "DATEIMOBIL": ("Date imobil", "Datele imobilului și ale proprietarilor",
                   "Property data", "Property and owner data", i_imobil),
    "EXECUTANT": ("Executant", "Datele persoanei autorizate",
                  "Surveyor", "Data of the authorised surveyor", i_executant),
    "VECINI": ("Vecini", "Vecinii, materializarea și observațiile pentru fiecare latură",
               "Neighbours", "Neighbours, boundary marks and notes for each side", i_vecini),
    "CONSTRUCTIE": ("Construcții", "Datele construcțiilor: cod, destinație, regim de înălțime, Sd",
                    "Buildings", "Building data: code, use, number of floors, built area", i_constr),
    "ANEXEWORD": ("Anexe Word", "Anexele Word 13, 14, 15, 20 și inventarul de coordonate",
                  "Word annexes", "Word annexes 13, 14, 15, 20 and the coordinates inventory", i_word),
    "VERIFICARE": ("Verificare", "Verificarea datelor lucrării și a geometriei imobilului",
                   "Check", "Checks the job data and the property geometry", i_verif),
    "PAD": ("Plan de amplasament", "Anexa 16 - plan de amplasament și delimitare a imobilului",
            "Site plan", "Annex 16 - site and boundary plan of the property", i_pad),
    "PADDEZ": ("PAD dezlipire", "Anexa 17 - dezlipire, plus câte un PAD pentru fiecare lot",
               "Site plan - split", "Annex 17 - split, plus a site plan for each lot", i_paddez),
    "PADALIP": ("PAD alipire", "Anexa 17 pentru alipire, plus PAD-ul imobilului rezultat",
                "Site plan - merge", "Annex 17 for merging, plus the site plan of the result", i_padalip),
    "RELEVEU": ("Releveu", "Anexa 18 - releveul unui nivel",
                "Floor survey", "Annex 18 - survey of one floor", i_releveu),
    "PLANEPDF": ("Planșe PDF", "Plotează în PDF toate planurile generate (PAD_*, RELEVEU_*)",
                 "PDF sheets", "Plots all generated plans to PDF (PAD_*, RELEVEU_*)", i_pdf),
    "INSCADRU": ("Cadru planșă", "Format A4...A0, cadru și indicator la scară",
                 "Sheet frame", "A4...A0 format, frame and title block at scale", i_cadru),
    "TIN": ("Model TIN", "Modelul 3D al terenului: triangulație din puncte 3D și linii de frângere",
            "TIN model", "3D terrain model: triangulation from 3D points and breaklines", i_tin),
    "CURBE": ("Curbe de nivel", "Curbe de nivel principale și secundare din TIN, cu cote",
              "Contour lines", "Major and minor contour lines from the TIN, with labels", i_curbe),
    "VOLUM": ("Volum față de cotă", "Volume de săpătură și umplutură între TIN și un plan de cotă dată",
              "Volume to elevation", "Cut and fill volumes between the TIN and a level plane", i_volum),
    "VOLUM2": ("Volum între TIN-uri", "Volume între două TIN (teren existent - proiect)",
               "Volume between TINs", "Volumes between two TINs (existing ground - design)", i_volum2),
    "TOPOTEREN": ("Modulul teren", "Meniul modulului de teren: puncte, TIN, curbe, volume, imagini",
                  "Terrain module", "Terrain module menu: points, TIN, contours, volumes, images", i_teren),
    "GEOREF": ("Imagine georeferențiată", "Inserează o imagine raster cu fișier world (.jgw, .tfw, .pgw, .wld)",
               "Georeferenced image", "Inserts a raster image with a world file (.jgw, .tfw, .pgw, .wld)", i_georef),
    "IMPKML": ("Import KML/KMZ", "Import din Google Earth (puncte, linii, poligoane), WGS84 → Stereo 70",
               "Import KML/KMZ", "Import from Google Earth (points, lines, polygons), WGS84 → Stereo 70", i_impkml),
    "HARTA": ("Google Maps", "Deschide punctul indicat în Google Maps",
              "Google Maps", "Opens the picked point in Google Maps", i_harta),
    "EXPKMZ": ("Export KMZ", "Export în KMZ/KML pentru Google Earth (TransDatRO)",
               "Export KMZ", "Export to KMZ/KML for Google Earth (TransDatRO)", i_expkmz),
    "DWGKMZ": ("DWG to KMZ", "Convertorul DXF/DWG → KMZ, cu desenul curent",
               "DWG to KMZ", "DXF/DWG → KMZ converter, with the current drawing", i_dwgkmz),
    "INCLINARE": ("Plan înclinare", "Planul de înclinare / verticalitate (silozuri, stâlpi, coșuri) din puncte",
                  "Inclination plan", "Inclination / verticality plan (silos, poles, chimneys) from points", i_inclinare),
    "PLANINCL": ("Programul Plan Înclinare", "Programul de calcul al înclinației (fișiere CSV/TXT/DWG/DXF)",
                 "Plan Înclinare program", "Inclination calculation program (CSV/TXT/DWG/DXF files)", i_planincl),
    "PLANINCLSEL": ("Înclinare din desen", "Calculul înclinației cu punctele selectate din desen",
                    "Inclination from drawing", "Inclination calculation from the points selected in the drawing", i_planinclsel),
}

# comenzi definite in LISP care nu au buton (aliasuri)
ALIASES = {"TKANEXE": "ANEXE"}

L, S1, ST = "LargeWithText", "SmallWithoutText", "SmallWithText"
# panou: (id, titlu RO, titlu EN, lansator dialog, coloane)
# coloana = (L, comanda, text RO, text EN) sau ("rows", stil, [[comenzi pe rand], ...])
PANELS = [
    ("CONFIG", "Configurare", "Configuration", "TOPOKITSET", [
        (L, "TOPOKIT", "Fereastra\nTopoKit", "TopoKit\nwindow"),
        ("rows", S1, [["TOPOKITSET"], ["TKCADSET"], ["MYTOPO"]]),
        ("rows", S1, [["TOPOKITLANG"], ["TOPOKITRELOAD"], ["TKCAD"]]),
    ]),
    ("PUNCTE", "Puncte", "Points", None, [
        (L, "TKIMPPCT", "Raportare\npuncte", "Draw\npoints"),
        ("rows", S1, [["TKPCT", "TKPCTCONTUR", "TKSTERGPCT"],
                      ["TKRENUM", "TKSELCOD", "TKSCHCOD"],
                      ["TKEXPPCT", "IMPPCT", "TABPCT"]]),
    ]),
    ("SUPRAFETE", "Suprafețe", "Areas", "TKCADSET", [
        (L, "TKDETASARE", "Detașare", "Detachment"),
        (L, "TKDETMULT", "Detașare\nmultiplă", "Multiple\ndetachment"),
        ("rows", S1, [["TKSUPRAF", "TKCOTE"], ["TKSUMA", "ADDVTX"]]),
    ]),
    ("ANEXE", "Anexe ANCPI", "ANCPI annexes", None, [
        (L, "ANEXE", "Anexe\nANCPI", "ANCPI\nannexes"),
        ("rows", S1, [["DATEIMOBIL", "EXECUTANT"], ["VECINI", "CONSTRUCTIE"], ["ANEXEWORD", "VERIFICARE"]]),
    ]),
    ("PLANURI", "Planuri", "Plans", None, [
        (L, "PAD", "Plan de\namplasament", "Site\nplan"),
        ("rows", S1, [["PADDEZ", "PADALIP"], ["RELEVEU", "PLANEPDF"], ["INSCADRU", "LEGENDA"]]),
    ]),
    ("MODEL3D", "Model 3D", "3D model", "TOPOTEREN", [
        (L, "TIN", "Model\nTIN", "TIN\nmodel"),
        (L, "CURBE", "Curbe de\nnivel", "Contour\nlines"),
        (L, "VOLUM", "Calcul\nvolum", "Volume\ncalculation"),
        ("rows", S1, [["VOLUM2"], ["TOPOTEREN"]]),
    ]),
    ("IMAGINI", "Imagini și hărți", "Images and maps", None, [
        (L, "GEOREF", "Imagine\ngeoref.", "Georef.\nimage"),
        ("rows", ST, [["IMPKML"], ["HARTA"]]),
    ]),
    ("KMZ", "Google Earth", "Google Earth", None, [
        (L, "EXPKMZ", "Export\nKMZ", "Export\nKMZ"),
        (L, "DWGKMZ", "DWG to\nKMZ", "DWG to\nKMZ"),
    ]),
    ("INCLINARE", "Înclinare", "Inclination", None, [
        (L, "INCLINARE", "Plan\nînclinare", "Inclination\nplan"),
        ("rows", ST, [["PLANINCL"], ["PLANINCLSEL"]]),
    ]),
]

GROUP = "TOPOKIT"
TAB_ID = "TK_RBN_TAB"
STAMP = "2026-10-30T12:00:00"
NS = 'xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
HDR = '<?xml version="1.0" encoding="utf-8"?>\n'


def attr(s):
    """Text pentru atribut XML; sfarsitul de rand devine &#xD; (randul al doilea al butonului)."""
    return escape(s, {'"': "&quot;", "\n": "&#xD;"})


def icon_png(fn, n):
    c = Canvas(n)
    fn(c)
    b = io.BytesIO()
    c.result().save(b, "PNG", optimize=True)
    return b.getvalue()


def menugroup_xml(en=False):
    out = [HDR, f'<MenuGroup {NS} Name="{GROUP}" DisplayName="TopoKit">\n  <MacroGroup Name="TopoKitMacros">\n']
    for cmd, v in CMDS.items():
        lbl, desc = (v[2], v[3]) if en else (v[0], v[1])
        out.append(
            f'    <MenuMacro UID="TK_{cmd}">\n      <Macro type="Any">\n'
            f'        <Name xlate="true" UID="XLS_TK_{cmd}">{escape(lbl)}</Name>\n'
            f'        <Command>^C^C{cmd}</Command>\n'
            f'        <HelpString xlate="true" UID="XLS_TKH_{cmd}">{escape(desc)}</HelpString>\n'
            f'        <SmallImage Name="TK_16_{cmd}.png" />\n        <LargeImage Name="TK_32_{cmd}.png" />\n'
            f'      </Macro>\n    </MenuMacro>\n')
    out.append("  </MacroGroup>\n</MenuGroup>\n")
    return "".join(out)


def ribbon_xml(en=False):
    uid = [0]

    def nid():
        uid[0] += 1
        return f"TK_RBN_{uid[0]:03d}"

    def button(cmd, style, text=None, ind="        "):
        tip = CMDS[cmd][2 if en else 0]
        lbl = text if text is not None else tip
        return (f'{ind}<RibbonCommandButton UID="{nid()}" Id="AcRibbonCommandButton" Text="{attr(lbl)}" '
                f'ButtonStyle="{style}" MenuMacroID="TK_{cmd}" KeyTip="">\n'
                f'{ind}  <TooltipTitle xlate="true">{escape(tip)}</TooltipTitle>\n'
                f'{ind}</RibbonCommandButton>\n')

    out = [HDR, f"<RibbonRoot>\n  <RibbonPanelSourceCollection {NS}>\n"]
    for pid, t_ro, t_en, launcher, cols in PANELS:
        title = t_en if en else t_ro
        out.append(f'    <RibbonPanelSource UID="TK_RBN_P_{pid}" Text="{attr(title)}" HiddenInEditor="false">\n'
                   f'      <Name xlate="true">{escape(title)}</Name>\n      <Alias>TK_RBN_P_{pid}</Alias>\n')
        if launcher:
            out.append(f'      <DialogBoxLauncher CommandID="TK_{launcher}" CommandType="Macro" />\n')
        out.append(f'      <RibbonRow UID="{nid()}">\n')
        for col in cols:
            if col[0] == "rows":
                _, style, rows = col
                out.append(f'        <RibbonRowPanel UID="{nid()}" ResizeStyle="None" TopJustify="True">\n')
                for r in rows:
                    out.append(f'          <RibbonRow UID="{nid()}">\n')
                    for cmd in r:
                        out.append(button(cmd, style, None, "            "))
                    out.append("          </RibbonRow>\n")
                out.append("        </RibbonRowPanel>\n")
            else:
                style, cmd, x_ro, x_en = col
                text = x_en if en else x_ro
                out.append(button(cmd, style, text))
        out.append("      </RibbonRow>\n    </RibbonPanelSource>\n")
    out.append("  </RibbonPanelSourceCollection>\n  <RibbonTabSourceCollection>\n"
               f'    <RibbonTabSource Text="TopoKit" UID="{TAB_ID}" KeyTip="TK">\n'
               f'      <Name xlate="true">TopoKit</Name>\n      <Alias>{TAB_ID}</Alias>\n')
    for pid, *_ in PANELS:
        out.append(f'      <RibbonPanelSourceReference UID="TK_RBN_R_{pid}" PanelId="TK_RBN_P_{pid}" ResizeStyle="Default" />\n')
    out.append("    </RibbonTabSource>\n  </RibbonTabSourceCollection>\n  <RibbonTabSelectors />\n</RibbonRoot>\n")
    return "".join(out)


EMPTY = {
    "Header.cui": (HDR + f"<CustSection {NS}>\n"
                   '  <FileVersion MajorVersion="0" MinorVersion="6" IncrementalVersion="1" UserVersion="1" />\n'
                   "  <Header>\n    <CommonConfiguration>\n      <CommonItems>\n"
                   '        <ModifiedRev MajorVersion="20" MinorVersion="0" UserVersion="1" />\n'
                   "      </CommonItems>\n    </CommonConfiguration>\n  </Header>\n</CustSection>\n"),
    "WorkspaceRoot.cui": HDR + f"<WorkspaceRoot {NS}>\n  <WorkspaceConfigRoot />\n</WorkspaceRoot>\n",
    "ToolbarRoot.cui": HDR + f"<ToolbarRoot {NS} />\n",
    "PopMenuRoot.cui": HDR + f"<PopMenuRoot {NS} />\n",
}


def build(out, png_dir=None, en=False):
    parts = dict(EMPTY)
    parts["MenuGroup.cui"] = menugroup_xml(en)
    parts["RibbonRoot.cui"] = ribbon_xml(en)
    order = ["Header.cui", "WorkspaceRoot.cui", "MenuGroup.cui", "ToolbarRoot.cui", "PopMenuRoot.cui", "RibbonRoot.cui"]
    images = {}
    for cmd, v in CMDS.items():
        fn = v[4]
        for n in (16, 32):
            images[f"TK_{n}_{cmd}.png"] = icon_png(fn, n)
    rels = "".join(f'<Relationship Type="CUI" Target="/{p}" Id="R{i:04d}" />' for i, p in enumerate(order))
    info = ['﻿<?xml version="1.0" encoding="utf-8"?>\n<MenuPackageParts>\n']
    for p in order + ["Menu_Package_Info.xml"] + list(images):
        info.append(f'  <PartData PartData_Name="/{p}" PartData_Modified="{STAMP}" />\n')
    info.append("</MenuPackageParts>\n")
    files = [(p, parts[p].encode("utf-8")) for p in order]
    files += [("_rels/.rels", ('﻿<?xml version="1.0" encoding="utf-8"?><Relationships xmlns='
                               '"http://schemas.openxmlformats.org/package/2006/relationships">'
                               + rels + "</Relationships>").encode("utf-8")),
              ("Menu_Package_Info.xml", "".join(info).encode("utf-8")),
              ("[Content_Types].xml", ('﻿<?xml version="1.0" encoding="utf-8"?><Types xmlns='
                                       '"http://schemas.openxmlformats.org/package/2006/content-types">'
                                       '<Default Extension="cui" ContentType="text/xml" />'
                                       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />'
                                       '<Default Extension="xml" ContentType="text/xml" />'
                                       '<Default Extension="png" ContentType="image/png" /></Types>').encode("utf-8"))]
    files += sorted(images.items())
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            zi = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
    if png_dir:
        pd = pathlib.Path(png_dir)
        pd.mkdir(parents=True, exist_ok=True)
        for name, data in images.items():
            (pd / name).write_bytes(data)
    return out


def preview(path):
    """Plansa cu toate iconitele (32 si 16 px) pe fundal deschis si inchis - pentru verificare."""
    cmds = list(CMDS)
    cols, cw, ch = 7, 150, 64
    rows = (len(cmds) + cols - 1) // cols
    im = Image.new("RGBA", (cols * cw * 2, rows * ch), (245, 245, 245, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((cols * cw, 0, cols * cw * 2, rows * ch), fill=(59, 68, 83, 255))
    f = ImageFont.truetype(FONT, 10)
    for half, tc in ((0, (40, 40, 40, 255)), (1, (230, 230, 230, 255))):
        for i, cmd in enumerate(cmds):
            x, y = half * cols * cw + (i % cols) * cw + 6, (i // cols) * ch + 6
            for n, dx in ((32, 0), (16, 40)):
                c = Canvas(n)
                CMDS[cmd][4](c)
                im.alpha_composite(c.result(), (x + dx, y + (0 if n == 32 else 8)))
            d.text((x + 62, y + 12), cmd, font=f, fill=tc)
    im.save(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build"), help="folderul pentru TopoKit.cuix si TopoKit_EN.cuix")
    ap.add_argument("--png", help="scrie si iconitele PNG in acest folder")
    ap.add_argument("--preview", help="plansa PNG cu toate iconitele")
    a = ap.parse_args()
    for name, en in (("TopoKit.cuix", False), ("TopoKit_EN.cuix", True)):
        print("Meniu:", build(pathlib.Path(a.out) / name, a.png, en), f"({len(CMDS)} comenzi, {len(PANELS)} panouri)")
    if a.preview:
        preview(a.preview)
        print("Previzualizare:", a.preview)
