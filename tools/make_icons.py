#!/usr/bin/env python3
"""Genereaza iconitele lansatorului TopoKit (installer/launcher/*.ico):

    topokit.ico      iconita programului / instalatorului
    tray_on.ico      bara de sistem - conectat la AutoCAD (punct verde)
    tray_off.ico     bara de sistem - AutoCAD nepornit (punct gri)

    python3 tools/make_icons.py
"""
import math, pathlib
from PIL import Image, ImageDraw

out = pathlib.Path(__file__).resolve().parent.parent / "installer" / "launcher"
S = 256


def base():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=48, fill=(18, 78, 120, 255))
    # curbe de nivel
    for k, r in enumerate((30, 58, 86, 114)):
        pts = []
        for i in range(73):
            a = 2 * math.pi * i / 72
            rr = r * (1 + 0.12 * math.sin(3 * a + k))
            pts.append((118 + rr * math.cos(a), 132 + 0.78 * rr * math.sin(a)))
        d.line(pts, fill=(150, 205, 235, 255), width=9 if k == 0 else 7, joint="curve")
    # punct de statie (triunghi rosu)
    d.polygon([(118, 92), (150, 150), (86, 150)], fill=(228, 60, 48, 255), outline=(255, 255, 255, 255))
    d.ellipse((110, 118, 126, 134), fill=(255, 255, 255, 255))
    return im


def with_dot(im, color):
    im = im.copy()
    d = ImageDraw.Draw(im)
    d.ellipse((150, 150, 246, 246), fill=color, outline=(255, 255, 255, 255), width=12)
    return im


sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
b = base()
b.save(out / "topokit.ico", sizes=sizes)
with_dot(b, (46, 190, 80, 255)).save(out / "tray_on.ico", sizes=sizes[:7])
with_dot(b, (150, 150, 150, 255)).save(out / "tray_off.ico", sizes=sizes[:7])
b.resize((128, 128), Image.LANCZOS).save(out.parent.parent / "docs" / "topokit_icon.png")
print("Iconite generate in", out)
