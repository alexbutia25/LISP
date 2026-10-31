#!/usr/bin/env python3
"""Genereaza pagina cu toate functiile TopoKit (Functii.html si Functii_EN.html).

    python3 tools/make_functions.py [--out FOLDER]

Pagina se construieste din aceeasi lista ca ribbonul (tools/make_ribbon.py: CMDS, PANELS):
fiecare comanda cu iconita, numele, descrierea si comanda AutoCAD, grupate pe panourile
ribbonului. E un singur fisier HTML (iconitele sunt incluse), deschis de instalator la final,
din fereastra TopoKit („Toate funcțiile”) si din meniul Start.
"""
import base64, html, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_ribbon as R

T = {
    "ro": {"title": "Funcțiile TopoKit", "lang": "ro",
           "intro": "Toate comenzile TopoKit, grupate ca în tabul <b>TopoKit</b> din ribbonul AutoCAD. "
                    "Rulați o comandă scriind-o în linia de comandă AutoCAD sau apăsând butonul din ribbon; "
                    "cele principale sunt și în fereastra TopoKit.",
           "cmd": "Comanda", "other": "Alte comenzi", "count": "comenzi"},
    "en": {"title": "TopoKit functions", "lang": "en",
           "intro": "All TopoKit commands, grouped as in the <b>TopoKit</b> tab of the AutoCAD ribbon. "
                    "Run a command by typing it on the AutoCAD command line or with its ribbon button; "
                    "the main ones are also in the TopoKit window.",
           "cmd": "Command", "other": "Other commands", "count": "commands"},
}


def panel_commands(items, launcher):
    out = []
    for it in items:
        if it[0] == "rows":
            for row in it[2]:
                out += row
        else:
            out.append(it[1])
    if launcher:
        out.append(launcher)
    seen, res = set(), []
    for c in out:
        c = R.ALIASES.get(c, c)
        if c in R.CMDS and c not in seen:
            seen.add(c); res.append(c)
    return res


def icon_uri(cmd):
    return "data:image/png;base64," + base64.b64encode(R.icon_png(R.CMDS[cmd][4], 32)).decode("ascii")


def page(lang, version):
    t, en = T[lang], lang == "en"
    groups, used = [], set()
    for pid, tro, ten, launcher, items in R.PANELS:
        cmds = [c for c in panel_commands(items, launcher) if c not in used]   # o comanda apare o singura data
        used.update(cmds)
        if cmds:
            groups.append((ten if en else tro, cmds))
    rest = [c for c in R.CMDS if c not in used]
    if rest:
        groups.append((t["other"], rest))
    total = sum(len(g[1]) for g in groups)
    cards = []
    for title, cmds in groups:
        cards.append(f'<section><h2>{html.escape(title)}</h2><div class="grid">')
        for c in cmds:
            v = R.CMDS[c]
            lbl, desc = (v[2], v[3]) if en else (v[0], v[1])
            cards.append(
                f'<div class="card"><img src="{icon_uri(c)}" alt="" width="32" height="32">'
                f'<div><div class="name">{html.escape(lbl.replace(chr(10), " "))}</div>'
                f'<div class="desc">{html.escape(desc)}</div>'
                f'<div class="cmd">{t["cmd"]}: <code>{html.escape(c)}</code></div></div></div>')
        cards.append("</div></section>")
    return f"""<!doctype html>
<html lang="{t['lang']}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t['title']} {version}</title>
<style>
:root {{ --bg:#f4f7fa; --card:#fff; --text:#1a2733; --text2:#5b6b7a; --border:#dde5ec; --accent:#1b6a8f; --head:#0f3d5e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161b21; --card:#1f262e; --text:#e6edf3; --text2:#9aa8b5; --border:#2f3a45; --accent:#5fb3dc; --head:#0f3d5e; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.45 "Segoe UI", Arial, sans-serif; }}
header {{ background:linear-gradient(120deg, var(--head), #1b6a8f); color:#fff; padding:28px 32px; }}
header h1 {{ margin:0; font-size:26px; font-weight:600; }}
header p {{ margin:8px 0 0; max-width:880px; color:#d8e8f2; }}
main {{ max-width:1200px; margin:0 auto; padding:8px 24px 40px; }}
h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:.06em; color:var(--text2); margin:28px 0 10px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); gap:12px; }}
.card {{ display:flex; gap:12px; background:var(--card); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }}
.card img {{ flex:none; margin-top:2px; }}
.name {{ font-weight:600; }}
.desc {{ color:var(--text2); font-size:13.5px; margin-top:2px; }}
.cmd {{ font-size:12.5px; color:var(--text2); margin-top:6px; }}
code {{ font:600 12.5px Consolas, monospace; color:var(--accent); }}
</style></head>
<body><header><h1>{t['title']} {version}</h1><p>{t['intro']} ({total} {t['count']})</p></header>
<main>{''.join(cards)}</main></body></html>
"""


def build(out_dir, version=None):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    version = version or (ROOT / "installer" / "VERSION").read_text().strip()
    files = []
    for lang, name in (("ro", "Functii.html"), ("en", "Functii_EN.html")):
        (out_dir / name).write_text(page(lang, version), encoding="utf-8")
        files.append(out_dir / name)
    return files


if __name__ == "__main__":
    args = sys.argv[1:]
    out = args[args.index("--out") + 1] if "--out" in args else str(ROOT / "build")
    for f in build(out):
        print(f)
