"""Randarea unui layout din simulatorul AutoCAD (acad_sim) intr-o imagine PNG.

Deseneaza entitatile din paper space ale layout-ului si, prin fiecare
viewport, entitatile din model space (polilinii si texte), ca la plotare:
straturile neplotabile sunt omise, grosimile de linie sunt ale straturilor.
Textele folosesc Liberation Sans (metrica identica cu Arial).
"""
import math, re, os
from PIL import Image, ImageDraw, ImageFont
from acad_sim import grp, grps

FONT_DIR = "/usr/share/fonts/truetype/liberation/"
FONTS = {"TK_ARIAL": "LiberationSans-Regular.ttf", "TKA_ARIALB": "LiberationSans-Bold.ttf",
         "TKA_ARIALI": "LiberationSans-Italic.ttf", "BOLD": "LiberationSans-Bold.ttf"}
CAP = 0.716                       # inaltimea majusculelor Arial / em
ACI = {1: (255, 0, 0), 2: (230, 200, 0), 3: (0, 200, 0), 4: (0, 190, 190), 5: (0, 0, 255), 6: (255, 0, 255),
       7: (0, 0, 0), 8: (128, 128, 128), 9: (192, 192, 192)}
_fonts = {}


def font(style, px):
    key = (style, max(4, int(round(px))))
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(FONT_DIR + FONTS.get((style or "TK_ARIAL").upper(), FONTS["TK_ARIAL"]), key[1])
    return _fonts[key]


def plain(s):
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    return s.replace("%%d", "\u00b0").replace("%%c", "\u2300").replace("%%p", "\u00b1").replace("%%%", "%")


class Page:
    def __init__(s, acad, layout, ppm):
        s.acad, s.layout, s.ppm = acad, layout, ppm
        lay = acad.layouts[layout.upper()]
        m = re.search(r"\(([\d.]+)_x_([\d.]+)_MM\)", lay.props.get("CANONICALMEDIANAME", ""))
        s.W, s.H = (float(m.group(1)), float(m.group(2))) if m else (420.0, 297.0)
        s.img = Image.new("RGB", (int(s.W * ppm), int(s.H * ppm)), "white")
        s.d = ImageDraw.Draw(s.img)

    def px(s, p): return (p[0] * s.ppm, (s.H - p[1]) * s.ppm)

    def style_of(s, d):
        lay = s.acad.tables["LAYER"].get((grp(d, 8) or "0").upper(), [])
        col = grp(d, 62) or grp(lay, 62) or 7
        lw = grp(lay, 370) or 18
        return ACI.get(abs(col), (0, 0, 0)), max(1, int(round(lw / 100.0 * s.ppm))), grp(lay, 290) != 0

    def text(s, img, txt, x, y, h, rot, ha, va, style, color, underline=False, ppm=None, tf=None):
        """Text cu ancora (ha: 0 stanga 1 centru 2 dreapta; va: 0 baza 1 jos 2 mijloc 3 sus)."""
        ppm = ppm or s.ppm
        f = font(style, h / CAP * ppm)
        asc, desc = f.getmetrics()
        w = max(1, int(math.ceil(f.getlength(txt))))
        t = Image.new("RGBA", (w + 4, asc + desc + 4), (0, 0, 0, 0))
        td = ImageDraw.Draw(t)
        td.text((2, 2), txt, font=f, fill=color + (255,))
        if underline:
            td.line([(2, 2 + asc + 2), (2 + w, 2 + asc + 2)], fill=color + (255,), width=max(1, int(h * ppm / 12)))
        cap = h * ppm
        ax = 2 + [0, w / 2.0, w][ha]
        ay = 2 + asc - [0, -desc, cap / 2.0, cap][va]
        cx, cy = t.width / 2.0, t.height / 2.0
        dx, dy = ax - cx, ay - cy
        r = t.rotate(math.degrees(rot), expand=True, resample=Image.BICUBIC)
        c, sn = math.cos(rot), math.sin(rot)
        nx = r.width / 2.0 + dx * c + dy * sn
        ny = r.height / 2.0 - dx * sn + dy * c
        X, Y = tf((x, y)) if tf else s.px((x, y))
        img.paste(r, (int(round(X - nx)), int(round(Y - ny))), r)

    def draw_text_ent(s, img, d, tf=None, k=1.0):
        col, _, plot = s.style_of(d)
        if not plot: return
        raw = grp(d, 1)
        und = raw.startswith("%%u")
        txt = plain(raw.replace("%%u", ""))
        h72, v73 = grp(d, 72) or 0, grp(d, 73) or 0
        p = grp(d, 11) if (h72 or v73) else grp(d, 10)
        ha, va = {0: 0, 1: 1, 2: 2, 4: 1}.get(h72, 0), (2 if h72 == 4 else v73)
        s.text(img, txt, p[0], p[1], grp(d, 40) * k, grp(d, 50) or 0.0, ha, va, grp(d, 7), col, und, tf=tf)

    def mtext_runs(s, raw):
        """Textul MTEXT -> lista de randuri, fiecare cu segmente (text, aldin)."""
        raw = plain(raw)
        lines, cur, bold, i = [[]], "", [False], 0
        stack = []
        def flush():
            nonlocal cur
            if cur: lines[-1].append((cur, bold[-1])); cur = ""
        while i < len(raw):
            c = raw[i]
            if c == "{": flush(); stack.append(bold[-1]); bold.append(bold[-1]); i += 1
            elif c == "}": flush(); bold.pop() if len(bold) > 1 else None; i += 1
            elif c == "\\" and i + 1 < len(raw):
                n = raw[i + 1]
                if n == "P": flush(); lines.append([]); i += 2
                elif n in "\\{}": cur += n; i += 2
                elif n == "f":
                    j = raw.index(";", i); flush(); bold[-1] = "|b1" in raw[i:j]; i = j + 1
                elif n in "HCQWTA":
                    i = raw.index(";", i) + 1
                elif n in "LlOoKk~": i += 2
                else: cur += c; i += 1
            else: cur += c; i += 1
        flush()
        return lines

    def draw_mtext_ent(s, img, d):
        col, _, plot = s.style_of(d)
        if not plot: return
        raw = "".join(grps(d, 3)) + grp(d, 1)
        h, wref, att = grp(d, 40), grp(d, 41) or 0.0, grp(d, 71)
        x, y = grp(d, 10)[:2]
        f = lambda b: font("BOLD" if b else "TK_ARIAL", h / CAP * s.ppm)
        # incadrarea pe latimea WREF (cuvant cu cuvant)
        out = []
        for line in s.mtext_runs(raw):
            words = [(w, b) for txt, b in line for w in re.split(r"(?<= )", txt) if w]
            cur, cw = [], 0.0
            for w, b in words:
                ww = f(b).getlength(w) / s.ppm
                if wref > 0 and cur and cw + ww - (f(b).getlength(" ") / s.ppm if w.endswith(" ") else 0) > wref:
                    out.append(cur); cur, cw = [], 0.0
                    w = w.lstrip()
                    ww = f(b).getlength(w) / s.ppm
                cur.append((w, b)); cw += ww
            out.append(cur)
        ls = 5.0 / 3.0 * h
        block = h + (len(out) - 1) * ls
        ytop = y if att in (1, 2, 3) else (y + block / 2.0 if att in (4, 5, 6) else y + block)
        for i, line in enumerate(out):
            lw = sum(f(b).getlength(w) for w, b in line) / s.ppm
            lw -= (f(line[-1][1]).getlength(line[-1][0]) - f(line[-1][1]).getlength(line[-1][0].rstrip())) / s.ppm if line else 0
            xs = x if att in (1, 4, 7) else (x - lw / 2.0 if att in (2, 5, 8) else x - lw)
            yb = ytop - h - i * ls
            for w, b in line:
                s.text(img, w, xs, yb, h, 0.0, 0, 0, "BOLD" if b else "TK_ARIAL", col)
                xs += f(b).getlength(w) / s.ppm

    def draw_geom(s, draw, d, tf, lwmul=1.0):
        col, lw, plot = s.style_of(d)
        if not plot: return
        lw = max(1, int(round(lw * lwmul)))
        typ = grp(d, 0)
        if typ == "LINE":
            draw.line([tf(grp(d, 10)), tf(grp(d, 11))], fill=col, width=lw)
        elif typ == "LWPOLYLINE":
            pts = [tf(p) for p in grps(d, 10)]
            if grp(d, 70) & 1: pts.append(pts[0])
            draw.line(pts, fill=col, width=lw, joint="curve")
        elif typ == "CIRCLE":
            c = tf(grp(d, 10)); r = grp(d, 40) * s.ppm
            draw.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=col, width=1)
        elif typ == "SOLID":
            pts = [tf(grp(d, c)) for c in (10, 11, 13, 12)]
            draw.polygon(pts, fill=col)

    def viewport(s, vd):
        cx, cy = grp(vd, 10)[:2]; w, h = grp(vd, 40), grp(vd, 41)
        k = h / grp(vd, 45)
        tx, ty = grp(vd, 17)[0] + grp(vd, 12)[0], grp(vd, 17)[1] + grp(vd, 12)[1]
        tf = lambda p: s.px((cx + k * (p[0] - tx), cy + k * (p[1] - ty)))
        layer = Image.new("RGBA", s.img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for e in s.acad.entities("Model"):
            d = s.acad.db[e]
            if grp(d, 0) in ("LWPOLYLINE", "LINE"):
                s.draw_geom(ld, d, tf, 0.6)
            elif grp(d, 0) == "TEXT":
                s.draw_text_ent(layer, d, tf=tf, k=k)
        x1, y1 = s.px((cx - w / 2, cy + h / 2)); x2, y2 = s.px((cx + w / 2, cy - h / 2))
        box = tuple(int(round(v)) for v in (x1, y1, x2, y2))
        s.img.paste(layer.crop(box), box[:2], layer.crop(box))

    def render(s):
        s.d.rectangle([0, 0, s.img.width - 1, s.img.height - 1], outline=(200, 200, 200))
        ents = [s.acad.db[e] for e in s.acad.entities(s.layout)]
        for d in ents:
            if grp(d, 0) == "VIEWPORT" and grp(d, 69) != 1 and s.style_of(d) and grp(d, 45):
                s.viewport(d)
        for d in ents:
            t = grp(d, 0)
            if t in ("LINE", "LWPOLYLINE", "CIRCLE", "SOLID"): s.draw_geom(s.d, d, s.px)
        for d in ents:
            t = grp(d, 0)
            if t == "TEXT": s.draw_text_ent(s.img, d)
            elif t == "MTEXT": s.draw_mtext_ent(s.img, d)
        return s.img


def render_layout(acad, layout, png, ppm=5.0):
    img = Page(acad, layout, ppm).render()
    img.save(png)
    return img
