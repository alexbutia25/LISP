"""Macheta (imagine PNG) a unui dialog DCL, pentru documentatie.

Asezarea tile-urilor este aproximativa (randuri/coloane cu dimensiunile
naturale ale elementelor); valorile, listele si imaginile sunt cele completate
de codul AutoLISP in simulator (acad_sim.Dcl.snapshots).
"""
import re
from PIL import Image, ImageDraw, ImageFont
from acad_sim import parse_dcl, KNOWN_TILES

CW, LH, GAP = 7, 15, 6
BG, LINE, WHITE, SEL = (240, 240, 240), (160, 160, 160), (255, 255, 255), (0, 120, 215)
F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
FB = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
ACI = {1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255), 5: (0, 0, 255), 6: (255, 0, 255),
       7: (0, 0, 0), 8: (128, 128, 128), 9: (192, 192, 192), 250: (51, 51, 51), 251: (80, 80, 80),
       252: (105, 105, 105), 253: (130, 130, 130), 254: (190, 190, 190), 255: (255, 255, 255)}


def aci(c):
    if c == -15: return BG
    if c in (-2, -16): return (0, 0, 0)
    if c in ACI: return ACI[c]
    import colorsys
    h = (c // 10 - 1) * 15 / 360.0
    v = [1, 1, .65, .65, .5, .5, .3, .3, .15, .15][c % 10]
    r, g, b = colorsys.hsv_to_rgb(h % 1, 1 if c % 2 == 0 else .5, v)
    return int(r * 255), int(g * 255), int(b * 255)


def tw(s): return int(F.getlength(s))


class Node:
    def __init__(s, typ, attrs, kids): s.typ, s.a, s.kids = typ, attrs, kids
    def num(s, k, d=0.0):
        try: return float(s.a.get(k, d))
        except ValueError: return d


def build(defs, items):
    out = []
    for it in items:
        if it[0] == "tile":
            typ, attrs, kids = it[1], {}, list(it[2])
            while typ not in KNOWN_TILES:
                for a in defs[typ][1]:
                    if a[0] == "attr": attrs.setdefault(a[1], a[2].strip('"'))
                kids = [k for k in defs[typ][1] if k[0] != "attr"] + kids
                typ = defs[typ][0]
            for a in it[2]:
                if a[0] == "attr": attrs[a[1]] = a[2].strip('"')
            out.append(Node(typ, attrs, build(defs, [k for k in kids if k[0] != "attr"])))
        elif it[0] == "ref":
            if it[1] == "ok_cancel":
                out.append(Node("row", {"alignment": "centered"},
                                [Node("button", {"key": "accept", "label": "OK", "width": "12"}, []),
                                 Node("button", {"key": "cancel", "label": "Cancel", "width": "12"}, [])]))
            elif it[1] == "spacer_1":
                out.append(Node("spacer", {"height": "1"}, []))
    return out


class Mockup:
    def __init__(s, dcl_text, name, snap):
        defs = parse_dcl(dcl_text)
        typ, body = defs[name]
        s.root = Node("dialog", {a[1]: a[2].strip('"') for a in body if a[0] == "attr"},
                      build(defs, [b for b in body if b[0] != "attr"]))
        s.tiles, s.lists, s.images = snap["tiles"], snap["lists"], snap.get("images", {})
        s.radio = {}

    def val(s, n): return s.tiles.get(n.a.get("key", ""), n.a.get("value", ""))

    def size(s, n):
        t = n.typ
        if t in ("text", "text_part", "errtile"):
            txt = s.val(n) or n.a.get("label", "")
            return max(tw(txt), int(n.num("width") * CW)), 17
        if t == "button":
            return max(tw(n.a.get("label", "")) + 24, int(n.num("width") * CW)), max(24, int(n.num("height") * LH * 0.8))
        if t in ("edit_box", "popup_list"):
            lw = tw(n.a.get("label", "")) + 6 if n.a.get("label") else 0
            return lw + int(n.num("edit_width", 12) * CW) + (16 if t == "popup_list" else 6), 22
        if t == "list_box":
            return int(n.num("width", 30) * CW), int(n.num("height", 10) * LH) + (16 if n.a.get("label") else 0)
        if t in ("toggle", "radio_button"):
            return 22 + tw(n.a.get("label", "")), 19
        if t in ("image", "image_button"):
            return int(n.num("width") * CW), int(n.num("height") * LH)
        if t == "spacer":
            return int(n.num("width") * CW), int(n.num("height", 0.4) * LH)
        sizes = [s.size(k) for k in n.kids]
        horiz = t in ("row", "boxed_row", "radio_row", "boxed_radio_row", "concatenation")
        if horiz:
            w = sum(x[0] for x in sizes) + GAP * max(0, len(sizes) - 1); h = max([x[1] for x in sizes] or [0])
        else:
            w = max([x[0] for x in sizes] or [0]); h = sum(x[1] for x in sizes) + (0 if t == "paragraph" else GAP) * max(0, len(sizes) - 1)
        if t.startswith("boxed"):
            w, h = max(w + 18, tw(n.a.get("label", "")) + 30), h + 28
        if t == "dialog":
            w, h = w + 24, h + 48
        return max(w, int(n.num("width") * CW)), h

    def draw(s, n, x, y, w, h):
        d, t = s.d, n.typ
        if t in ("text", "text_part", "errtile"):
            txt = s.val(n) or n.a.get("label", "")
            tx = x + (w - tw(txt)) // 2 if n.a.get("alignment") == "centered" else x
            d.text((tx, y + 2), txt, font=F, fill=(0, 0, 0) if t != "errtile" else (200, 0, 0))
        elif t == "button":
            bw = s.size(n)[0]; bx = x + (w - bw) // 2 if n.a.get("alignment") == "centered" or n.a.get("fixed_width") else x
            bw = min(bw, w) if not n.a.get("fixed_width") else bw
            d.rounded_rectangle([bx, y, bx + bw, y + h - 1], 3, fill=(225, 225, 225),
                                outline=SEL if n.a.get("is_default") == "true" else LINE)
            lab = n.a.get("label", "")
            d.text((bx + (bw - tw(lab)) // 2, y + (h - 13) // 2), lab, font=F, fill=(0, 0, 0))
        elif t in ("edit_box", "popup_list"):
            lab = n.a.get("label", ""); lw = tw(lab) + 6 if lab else 0
            d.text((x, y + 4), lab, font=F, fill=(0, 0, 0))
            ew = int(n.num("edit_width", 12) * CW) + (16 if t == "popup_list" else 6)
            ex = x + max(lw, w - ew) if t == "edit_box" or True else x + lw
            d.rectangle([ex, y + 1, x + w - 1, y + 20], fill=WHITE, outline=LINE)
            v = s.val(n)
            if t == "popup_list":
                items = s.lists.get(n.a.get("key"), [])
                v = items[int(v)] if v.isdigit() and int(v) < len(items) else ""
                d.text((x + w - 13, y + 3), "▾", font=F, fill=(0, 0, 0))
            d.text((ex + 4, y + 4), v[: max(1, (x + w - ex - 22) // 6)], font=F, fill=(0, 0, 0))
        elif t == "list_box":
            yy = y
            if n.a.get("label"):
                d.text((x, y), n.a["label"], font=F, fill=(0, 0, 0)); yy += 16
            d.rectangle([x, yy, x + w - 1, y + h - 1], fill=WHITE, outline=LINE)
            sel = set(int(v) for v in s.val(n).split()) if s.val(n).strip() else set()
            tabs = [int(float(v) * CW) for v in n.a.get("tabs", "").split()]
            for i, it in enumerate(s.lists.get(n.a.get("key"), [])):
                ly = yy + 2 + i * 14
                if ly + 14 > y + h - 2: break
                if i in sel: d.rectangle([x + 1, ly, x + w - 2, ly + 13], fill=SEL)
                for j, part in enumerate(it.split("\t")):
                    px = x + 4 + (tabs[j - 1] if 0 < j <= len(tabs) else 0)
                    d.text((px, ly), part, font=F, fill=WHITE if i in sel else (0, 0, 0))
        elif t in ("toggle", "radio_button"):
            on = (s.val(n) == "1") if t == "toggle" else s.radio.get(id(n), False)
            if t == "toggle":
                d.rectangle([x, y + 3, x + 12, y + 15], fill=WHITE, outline=(90, 90, 90))
                if on: d.line([(x + 2, y + 9), (x + 5, y + 12), (x + 10, y + 5)], fill=(0, 0, 0), width=2)
            else:
                d.ellipse([x, y + 3, x + 12, y + 15], fill=WHITE, outline=(90, 90, 90))
                if on: d.ellipse([x + 3, y + 6, x + 9, y + 12], fill=(0, 0, 0))
            d.text((x + 18, y + 2), n.a.get("label", ""), font=F, fill=(0, 0, 0))
        elif t in ("image", "image_button"):
            iw, ih = int(n.num("width") * CW), int(n.num("height") * LH)
            ix = x + (w - iw) // 2 if n.a.get("alignment") == "centered" else x
            im = Image.new("RGB", (max(1, iw), max(1, ih)), BG); idr = ImageDraw.Draw(im)
            for op in s.images.get(n.a.get("key"), []):
                if op[0] == "v": idr.line([op[1], op[2], op[3], op[4]], fill=aci(op[5]))
                else: idr.rectangle([op[1], op[2], op[1] + op[3] - 1, op[2] + op[4] - 1], fill=aci(op[5]))
            s.img.paste(im, (ix, y))
        elif t == "spacer":
            pass
        else:
            horiz = t in ("row", "boxed_row", "radio_row", "boxed_radio_row", "concatenation")
            if t in ("radio_row", "radio_column", "boxed_radio_row", "boxed_radio_column"):
                cur = s.val(n)
                for k in n.kids: s.radio[id(k)] = k.a.get("key") == cur
            ox, oy, iw = x, y, w
            if t.startswith("boxed"):
                d.rectangle([x, y + 6, x + w - 1, y + h - 1], outline=LINE)
                lab = n.a.get("label", "")
                if lab:
                    d.rectangle([x + 8, y, x + 14 + tw(lab), y + 12], fill=BG)
                    d.text((x + 11, y), lab, font=FB, fill=(0, 0, 0))
                ox, oy, iw = x + 9, y + 20, w - 18
            if t == "dialog":
                d.rectangle([x, y, x + w - 1, y + 26], fill=WHITE)
                d.text((x + 10, y + 7), n.a.get("label", ""), font=F, fill=(0, 0, 0))
                d.text((x + w - 20, y + 6), "✕", font=F, fill=(0, 0, 0))
                ox, oy, iw = x + 12, y + 36, w - 24
            sizes = [s.size(k) for k in n.kids]
            if horiz:
                tot = sum(z[0] for z in sizes) + GAP * max(0, len(sizes) - 1)
                cx = ox + ((iw - tot) // 2 if n.a.get("alignment") == "centered" or n.a.get("fixed_width") == "true" else 0)
                extra = max(0, iw - tot) if not (n.a.get("alignment") == "centered" or n.a.get("fixed_width") == "true") else 0
                flex = [k for k in n.kids if k.typ not in ("button", "toggle", "radio_button", "text", "image", "spacer")
                        and k.a.get("fixed_width") != "true"]
                for k, z in zip(n.kids, sizes):
                    kw = z[0] + (extra // len(flex) if k in flex else 0)
                    s.draw(k, cx, oy, kw, max(z[1], 1) if k.typ not in ("column", "boxed_column", "paragraph") else
                           max(z[1], h - (oy - y) - (6 if t.startswith("boxed") else 0)))
                    cx += kw + GAP
            else:
                cy = oy
                for k, z in zip(n.kids, sizes):
                    kw = iw if k.typ not in ("button", "toggle", "radio_button") else z[0]
                    if k.typ == "button" and k.a.get("alignment") == "centered": kw = iw
                    s.draw(k, ox, cy, kw, z[1])
                    cy += z[1] + (0 if t == "paragraph" else GAP)

    def render(s, path):
        w, h = s.size(s.root)
        s.img = Image.new("RGB", (w + 2, h + 2), BG); s.d = ImageDraw.Draw(s.img)
        s.draw(s.root, 0, 0, w, h)
        s.d.rectangle([0, 0, w + 1, h + 1], outline=(110, 110, 110))
        s.img.save(path)
        return s.img
