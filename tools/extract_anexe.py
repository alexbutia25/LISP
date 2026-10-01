#!/usr/bin/env python3
"""Extrage textul anexelor 1-35 din Ordinul ANCPI nr. 600/2023 (HTML consolidat)
intr-o structura JSON (paragrafe si tabele), folosita de build_anexe.py.

    python3 tools/extract_anexe.py <ordin600.html> tools/ordin600_anexe.json

Notele de consolidare ("La data de ... a fost modificata de ...") si imaginile
(facsimile) sunt omise; textul oficial al formularelor este pastrat integral.
"""
import json, re, sys
from bs4 import BeautifulSoup, NavigableString, Tag

BLOCK_CLASSES = {"S_PCT", "S_LIT", "S_LIN", "S_ALN", "S_PAR", "A_ELEMENT_CENTER",
                 "A_ELEMENT_RIGHT", "S_NTA", "S_NTA_PAR"}

def classes(el):
    return set(el.get("class") or []) if isinstance(el, Tag) else set()

def is_block(el):
    if not isinstance(el, Tag):
        return False
    if el.name in ("table", "div", "p", "pre", "img", "tr", "td"):
        return True
    return bool(classes(el) & BLOCK_CLASSES)

def norm(t):
    t = t.replace("\xa0", " ").replace("…", "...")
    t = re.sub(r"\s+", " ", t)
    return t.strip()

def inline_text(el):
    """Textul propriu al elementului, fara descendentii de tip bloc."""
    out = []
    for c in el.children:
        if isinstance(c, NavigableString):
            out.append(str(c))
        elif not is_block(c):
            out.append(inline_text(c))
    return "".join(out)

def is_note(t):
    return bool(re.match(r"^La data de \d", t)) and ("modificat" in t or "completat" in t or "abrogat" in t)

def walk(el, blocks, align="left", level=0, prefix=""):
    for c in el.children:
        if isinstance(c, NavigableString):
            t = norm(str(c))
            if t:
                blocks.append({"t": "p", "text": prefix + t, "align": align, "lvl": level})
                prefix = ""
            continue
        if not isinstance(c, Tag):
            continue
        cl = classes(c)
        if c.name in ("pre", "img", "script", "style"):
            continue
        if c.name == "table":
            blocks.append(table_block(c))
            continue
        if "A_ELEMENT_CENTER" in cl:
            walk(c, blocks, "center", level)
            continue
        if "A_ELEMENT_RIGHT" in cl:
            walk(c, blocks, "right", level)
            continue
        ttl = None
        for k in ("S_PCT", "S_LIT", "S_LIN", "S_ALN"):
            if k in cl:
                ttl = c.find(class_=k + "_TTL")
                bdy = c.find(class_=k + "_BDY")
                pre = norm(ttl.get_text()) + " " if ttl else ""
                if bdy is not None:
                    own = norm(inline_text(bdy))
                    if own:
                        blocks.append({"t": "p", "text": pre + own, "align": align, "lvl": level + 1})
                    elif pre.strip():
                        # numerotarea punctului precede direct un tabel sau o lista
                        blocks.append({"t": "p", "text": pre.strip(), "align": align, "lvl": level + 1})
                    walk_blocks_only(bdy, blocks, align, level + 1)
                break
        if ttl is not None or cl & {"S_PCT", "S_LIT", "S_LIN", "S_ALN"}:
            continue
        if "S_PAR" in cl or c.name == "p" or "S_NTA_PAR" in cl:
            own = norm(inline_text(c))
            if own and not is_note(own) and not (c.name == "p" and not cl and own.startswith("Punctul")):
                blocks.append({"t": "p", "text": prefix + own, "align": align, "lvl": level})
                prefix = ""
            walk_blocks_only(c, blocks, align, level)
            continue
        if c.name in ("div", "span"):
            walk(c, blocks, align, level, prefix)
            prefix = ""
            continue
        t = norm(c.get_text())
        if t:
            blocks.append({"t": "p", "text": prefix + t, "align": align, "lvl": level})
            prefix = ""

class _Single:
    """Container minimal cu un singur copil (pentru a refolosi walk)."""
    def __init__(self, child):
        self.children = [child]

def walk_blocks_only(el, blocks, align, level):
    """Parcurge doar descendentii de tip bloc (textul inline a fost deja preluat)."""
    for c in el.children:
        if isinstance(c, Tag) and is_block(c):
            walk(_Single(c), blocks, align, level)

def table_block(tb):
    rows = []
    for tr in tb.find_all("tr"):
        if tr.find_parent("table") is not tb:
            continue
        cells = []
        for td in tr.find_all(["td", "th"]):
            if td.find_parent("tr") is not tr:
                continue
            paras = []
            sub = []
            walk(td, sub, "center" if "S_TD_H_ALIGN_CENTER" in classes(td) else "left", 0)
            for b in sub:
                if b["t"] == "p":
                    paras.append(b["text"])
            cells.append({"text": "\n".join(paras),
                          "colspan": int(td.get("colspan", 1) or 1),
                          "rowspan": int(td.get("rowspan", 1) or 1),
                          "center": "S_TD_H_ALIGN_CENTER" in classes(td),
                          "noborder": "S_TD_NO_BORDER" in classes(td)})
        rows.append(cells)
    return {"t": "table", "rows": rows}

def main(src, dst):
    soup = BeautifulSoup(open(src, encoding="utf-8", errors="replace").read(), "lxml")
    anexe = {}
    for ttl in soup.find_all("p", class_="S_ANX_TTL"):
        m = re.match(r"Anexa nr\.\s*(\d+)", ttl.get_text(strip=True))
        if not m:
            continue
        nr = int(m.group(1))
        bdy = ttl.find_next_sibling(class_="S_ANX_BDY")
        blocks = []
        if bdy is not None:
            walk(bdy, blocks)
        # elimina dublurile consecutive si notele de consolidare
        clean = []
        for b in blocks:
            if b["t"] == "p" and (is_note(b["text"]) or re.match(r"^Punctul \d+\.? ?, Articolul", b["text"])):
                continue
            if clean and b["t"] == "p" and clean[-1]["t"] == "p" and clean[-1]["text"] == b["text"]:
                continue
            clean.append(b)
        anexe[nr] = clean
    json.dump(anexe, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(anexe)} anexe extrase in {dst}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
