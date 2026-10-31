#!/usr/bin/env python3
"""Teste offline pentru limba interfetei (romana / engleza) si ribbonul TopoKit.

    python3 tests/test_lang.py

Verifica:
  - dictionarul lang/en.txt: fiecare intrare e folosita, traducerile nu strica sirurile
    LISP (ghilimele), tastele getkword raman cele globale, domeniile sunt valide;
  - varianta in engleza (tools/i18n.py): aceeasi structura LISP ca originalul, textele din
    planuri si numele de straturi raman in romana;
  - in simulatorul AutoCAD: cu language.txt = EN, incarcatorul pune folderul "en" in calea de
    suport inaintea folderului Contents, incarca modulele traduse si meniul TopoKit_EN.cuix;
    TOPOKITLANG / TKL:SetLang revine la romana (cale de suport, meniu, mesaje);
  - meniul ribbon (tools/make_ribbon.py): XML valid, fiecare comanda TopoKit are buton si
    iconite 16/32, fiecare buton trimite o comanda definita in LISP.
"""
import os, re, shutil, sys, tempfile, zipfile, xml.dom.minidom
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from acad_sim import Acad, Sym, call, env
import autolisp_mini as M
import i18n
import make_ribbon

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP = tempfile.mkdtemp(prefix="topokit_lang_")
REG = "HKEY_CURRENT_USER\\Software\\TopoKit"

# ---------------------------------------------------------------- dictionarul
d = i18n.load_dict()
used = set()
for f in i18n.LSP:
    src = i18n.read(pathlib_path := __import__("pathlib").Path(ROOT) / f)
    for a, b, s in i18n.literals(src):
        if s in d:
            used.add(s)
        for m in i18n.DCL_LABEL.finditer(s):
            used.add(m.group(2))
for f in i18n.DCL:
    for m in i18n.DCL_LABEL_FILE.finditer(i18n.read(__import__("pathlib").Path(ROOT) / f)):
        used.add(m.group(2))
unused = [k for k in d if k not in used]
assert not unused, f"intrari nefolosite in lang/en.txt: {unused[:5]}"
for ro, (en, scope) in d.items():
    assert not re.search(r'(?<!\\)"', en.replace('\\\\', '')), f"ghilimele neprotejate: {en}"
    assert ro.count("\\n") == en.count("\\n"), f"randuri diferite: {ro!r} -> {en!r}"
    assert scope in (None, "label") or scope.startswith("call:") or scope in i18n.LSP, scope
    if "[" in ro and "<" in ro:                       # prompt cu taste: aceleasi optiuni
        assert ro.count("/") == en.count("/"), (ro, en)
# initget: tastele locale (engleza) + cele globale (romana), ca getkword sa intoarca tot "Da" / "Nu"
for ro, (en, _) in d.items():
    if ro in ("Da Nu", "PAralela DirectieParalela PErpendiculara PUnctObligat"):
        loc, glob = en.split(" _")
        assert glob.split() == ro.split() and len(loc.split()) == len(ro.split()), en
print(f"Dictionarul: {len(d)} intrari, toate folosite; ghilimele, randuri si taste corecte")

# ---------------------------------------------------------------- varianta tradusa
contents = os.path.join(TMP, "Contents")
os.makedirs(contents)
for f in i18n.LSP + i18n.DCL:
    shutil.copy2(os.path.join(ROOT, f), contents)
en_dir = os.path.join(contents, "en")
i18n.build(__import__("pathlib").Path(en_dir), d)
assert sorted(os.listdir(en_dir)) == sorted([f for f in i18n.LSP if f != "TopoKitLoad.lsp"] + i18n.DCL)
for f in i18n.LSP[1:]:
    ro_src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    en_src = open(os.path.join(en_dir, f), encoding="utf-8").read()
    # aceeasi structura: aceleasi forme, doar sirurile difera
    def strip(s):                                  # codul fara continutul sirurilor
        out, last = [], 0
        for a, b, _ in i18n.literals(s):
            out.append(s[last:a]); last = b
        out.append(s[last:])
        return "".join(out)
    assert strip(ro_src) == strip(en_src), f"{f}: structura LISP difera"
    assert len(M.parse(M.tokenize(ro_src))) == len(M.parse(M.tokenize(en_src))), f
    assert ro_src.count("\r\n") == en_src.count("\r\n"), f"{f}: sfarsituri de rand"
cad_en = open(os.path.join(en_dir, "TopoKitCad.lsp"), encoding="utf-8").read()
assert '*TKC:LAYSUP* "Suprafete"' in cad_en, "numele stratului nu se traduce"
assert '(TKC:SubMenu pm "Areas")' in cad_en and "Select the closed polylines" in cad_en
ter_en = open(os.path.join(en_dir, "TopoKitTeren.lsp"), encoding="utf-8").read()
assert '(append \'("Nr." "X [m]" "Y [m]")' in ter_en, "capul tabelului din plan ramane in romana"
anx_en = open(os.path.join(en_dir, "TopoKitAnexe.lsp"), encoding="utf-8").read()
assert '"Cod" "Destina`tia"' in anx_en and "Plan de amplasament `si delimitare a imobilului" in anx_en
assert '(wcmatch m "A:*")' in anx_en and '"A: Side "' in anx_en, "prefixele E:/A:/I: ale verificarii"
dcl_en = open(os.path.join(en_dir, "TopoKitAnexe.dcl"), encoding="utf-8").read()
assert 'label = "Generate"' in dcl_en and 'key = "' in dcl_en
print("Varianta in engleza: aceeasi structura LISP; planurile, anexele si straturile raman in romana")

# ---------------------------------------------------------------- ribbonul
for name, en in (("TopoKit.cuix", False), ("TopoKit_EN.cuix", True)):
    make_ribbon.build(os.path.join(contents, name), None, en)
    z = zipfile.ZipFile(os.path.join(contents, name))
    names = set(z.namelist())
    mg = xml.dom.minidom.parseString(z.read("MenuGroup.cui"))
    rb = xml.dom.minidom.parseString(z.read("RibbonRoot.cui"))
    for p in ("Header.cui", "WorkspaceRoot.cui", "[Content_Types].xml", "_rels/.rels", "Menu_Package_Info.xml"):
        assert p in names, p
        if p.endswith((".cui", ".xml", ".rels")):
            xml.dom.minidom.parseString(z.read(p))
    macros = {m.getAttribute("UID"): m for m in mg.getElementsByTagName("MenuMacro")}
    assert mg.documentElement.getAttribute("Name") == "TOPOKIT"
    for uid, m in macros.items():
        cmd = m.getElementsByTagName("Command")[0].firstChild.data
        assert cmd == "^C^C" + uid[3:], cmd
        for tag in ("SmallImage", "LargeImage"):
            assert m.getElementsByTagName(tag)[0].getAttribute("Name") in names
    btns = [b.getAttribute("MenuMacroID") for b in rb.getElementsByTagName("RibbonCommandButton")]
    btns += [b.getAttribute("CommandID") for b in rb.getElementsByTagName("DialogBoxLauncher")]
    assert set(btns) <= set(macros), set(btns) - set(macros)
    assert {"TK_" + c for c in make_ribbon.CMDS} <= set(btns), "comenzi fara buton"
    panels = {p.getAttribute("UID") for p in rb.getElementsByTagName("RibbonPanelSource")}
    refs = {r.getAttribute("PanelId") for r in rb.getElementsByTagName("RibbonPanelSourceReference")}
    assert panels == refs and len(panels) == len(make_ribbon.PANELS)
    tab = rb.getElementsByTagName("RibbonTabSource")[0]
    assert tab.getAttribute("Text") == "TopoKit"
    det = [b for b in rb.getElementsByTagName("RibbonCommandButton") if b.getAttribute("MenuMacroID") == "TK_TKDETMULT"][0]
    assert det.getAttribute("ButtonStyle") == "LargeWithText"
    # randul al doilea al butonului: &#xD; in XML (citit ca \r)
    assert det.getAttribute("Text") == ("Multiple\rdetachment" if en else "Detașare\rmultiplă")
# fiecare comanda LISP (in afara aliasurilor) are buton; fiecare buton are o comanda LISP
lisp_cmds = set()
for f in i18n.LSP:
    lisp_cmds |= {c.upper() for c in re.findall(r"\(defun c:([A-Za-z0-9_-]+)", open(os.path.join(ROOT, f), encoding="utf-8").read())}
assert lisp_cmds - set(make_ribbon.ALIASES) == set(make_ribbon.CMDS), (lisp_cmds ^ set(make_ribbon.CMDS))
print(f"Ribbon RO / EN: {len(make_ribbon.CMDS)} comenzi, {len(make_ribbon.PANELS)} panouri, iconite 16/32, XML valid")

# ---------------------------------------------------------------- in simulator: incarcare in engleza
OUT = os.path.join(TMP, "out")
os.makedirs(OUT)
acad = Acad(contents, OUT)
win = lambda p: p.replace("/", "\\")
# limba din fisierul %LOCALAPPDATA%\TopoKit\language.txt; registrul (care poate fi o copie
# virtualizata, diferita de a ferestrei TopoKit) spune altceva si nu conteaza
reg = {(REG, "ContentsDir"): win(contents) + "\\", (REG, "Language"): "RO", (REG, "Version"): "1.0.0"}
local = os.path.join(TMP, "local")
os.makedirs(os.path.join(local, "TopoKit"))
lang_file = os.path.join(local, "TopoKit", "language.txt")
open(lang_file, "w").write("EN\n")
acad.envs["LOCALAPPDATA"] = win(local)
prefs = {"SupportPath": "C:\\Program Files\\Autodesk\\AutoCAD 2026\\support"}
M.funcs[Sym("VL-REGISTRY-READ")] = lambda k, v=None: reg.get((k, v))
M.funcs[Sym("VL-REGISTRY-WRITE")] = lambda k, v, x: reg.__setitem__((k, v), x) or x
M.funcs.setdefault(Sym("VL-PRINC-TO-STRING"), lambda x: str(x))
M.funcs[Sym("VLA-GET-PREFERENCES")] = lambda a: "prefs"
M.funcs[Sym("VLA-GET-FILES")] = lambda p: "files"
M.funcs[Sym("VLA-GET-SUPPORTPATH")] = lambda f: prefs["SupportPath"]
M.funcs[Sym("VLA-PUT-SUPPORTPATH")] = lambda f, v: prefs.__setitem__("SupportPath", v)


def findfile(f):                                   # calea de suport, in ordine, ca in AutoCAD
    p = f.replace("\\", "/")
    if os.path.isabs(p) or re.match(r"^[A-Za-z]:", p):
        return f if os.path.exists(p) else None
    for d_ in prefs["SupportPath"].split(";"):
        q = os.path.join(d_.replace("\\", "/"), p)
        if os.path.exists(q):
            return win(q)
    return None


M.funcs[Sym("FINDFILE")] = findfile
loads = []
orig_load = M.funcs[Sym("LOAD")]
M.funcs[Sym("LOAD")] = lambda f, *a: (loads.append(os.path.relpath(f.replace("\\", "/"), contents).replace("\\", "/")),
                                      orig_load(f, *a))[1]
# grupurile de meniu AutoCAD (MenuGroups): incarcare / descarcare meniu partial
menus = {}
orig_item = M.funcs[Sym("VLA-ITEM")]


def vla_item(c, n):
    if c == "menugroups":
        if n.upper() not in menus:
            raise KeyError(n)
        return ("menugroup", n.upper())
    return orig_item(c, n)


M.funcs[Sym("VLA-GET-MENUGROUPS")] = lambda a: "menugroups"
M.funcs[Sym("VLA-ITEM")] = vla_item
M.funcs[Sym("VLA-GET-MENUFILENAME")] = lambda g: menus[g[1]]
M.funcs[Sym("VLA-UNLOAD")] = lambda g: menus.pop(g[1])
orig_invoke = M.funcs.get(Sym("VLAX-INVOKE"))


menu_loads = []


def invoke(o, m, *a):
    if o == "menugroups" and str(m).upper() == "LOAD":
        menus["TOPOKIT"] = a[0][:-5]                   # AutoCAD raporteaza fisierul fara extensie
        menu_loads.append(a[0])
        return ("menugroup", "TOPOKIT")
    return orig_invoke(o, m, *a)


M.funcs[Sym("VLAX-INVOKE")] = invoke
for k in ("TKL:LOAD", "C:TOPOKIT", "TK:START", "TKA:GENERATE", "TKT:MENU", "TKI:RUN", "C:TKDETASARE", "C:TKPROIECT"):
    env.pop(Sym(k), None)
M.load(os.path.join(contents, "TopoKitLoad.lsp"))
acad.after_load()
sp = prefs["SupportPath"].split(";")
assert sp[0] == win(en_dir) and sp[1] == win(contents), sp
assert loads == ["en/TopoKit.lsp", "en/TopoKitAnexe.lsp", "en/TopoKitTeren.lsp", "en/TopoKitInclinare.lsp",
                 "en/TopoKitCad.lsp", "en/TopoKitProiect.lsp"], loads
assert menus == {"TOPOKIT": win(contents) + "\\TopoKit_EN"}, menus
assert any("TopoKit Cadastre loaded" in o for o in acad.out), acad.out[-4:]
assert any("TopoKit Terrain loaded" in o for o in acad.out)
acad.out.clear()
M.funcs.setdefault(Sym("TEXTSCR"), lambda: None)
call(Sym("C:TKCAD"), [])
assert any("=== TopoKit - cadastre ===" in o for o in acad.out), acad.out[:3]
print("Engleza: folderul en inaintea Contents, modulele traduse, meniul TopoKit_EN.cuix")

# al doilea desen: nimic nou (aceeasi cale, acelasi meniu)
loads.clear()
n_menu = len(menu_loads)
M.load(os.path.join(contents, "TopoKitLoad.lsp"))
assert loads == [] and prefs["SupportPath"].split(";")[:2] == sp[:2] and len(menus) == 1
call(Sym("TKL:RIBBON"), [win(contents)])
assert len(menu_loads) == n_menu, "acelasi .cuix: meniul nu se reincarca"
# dupa o actualizare (alt fisier .cuix, acelasi nume): meniul se reincarca, ca sa apara panourile noi
with open(os.path.join(contents, "TopoKit_EN.cuix"), "ab") as fh:
    fh.write(bytes(16))
call(Sym("TKL:RIBBON"), [win(contents)])
assert len(menu_loads) == n_menu + 1 and menus == {"TOPOKIT": win(contents) + r"\TopoKit_EN"}, (menu_loads, menus)
call(Sym("TKL:RIBBON"), [win(contents)])
assert len(menu_loads) == n_menu + 1, "o singura reincarcare pe sesiune"
# meniul ramas incarcat din sesiunea trecuta (blackboard gol): se reincarca o data
acad.bb.clear()
call(Sym("TKL:RIBBON"), [win(contents)])
assert len(menu_loads) == n_menu + 2
print("Ribbon: meniul se reincarca doar cand fisierul .cuix s-a schimbat (o data pe sesiune)")

# ---------------------------------------------------------------- inapoi la romana
loads.clear()
acad.out.clear()
call(Sym("TKL:SETLANG"), ["RO"])
assert open(lang_file).read().strip() == "RO" and reg[(REG, "Language")] == "RO"
sp = prefs["SupportPath"].split(";")
assert sp[0] == win(contents) and win(en_dir) not in sp, sp
assert loads == ["TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitTeren.lsp", "TopoKitInclinare.lsp", "TopoKitCad.lsp", "TopoKitProiect.lsp"], loads
assert menus == {"TOPOKIT": win(contents) + "\\TopoKit"}, menus
assert any("TopoKit Cadastru incarcat" in o for o in acad.out)
assert any("interfata in limba romana" in o for o in acad.out)
# alt desen deschis inainte de schimbare: TKL:Stale vede limba diferita
env[Sym("*TKL:LANGLOADED*")] = "EN"
assert call(Sym("TKL:STALE"), []) is not None
env[Sym("*TKL:LANGLOADED*")] = "RO"
# versiunea: din TopoKit.lsp instalat, nu din registru (acolo e "1.0.0")
assert call(Sym("TKL:FILEVERSION"), [win(contents)]) == open(os.path.join(ROOT, "installer", "VERSION")).read().strip()
assert call(Sym("TKL:STALE"), []) is None
env[Sym("*TK:VERSION*")] = "1.2.0"
assert call(Sym("TKL:STALE"), []) is not None
env[Sym("*TK:VERSION*")] = call(Sym("TKL:FILEVERSION"), [win(contents)])
print("TKL:SetLang RO: calea de suport fara en, meniul TopoKit.cuix, mesajele in romana")

# ---------------------------------------------------------------- pagina cu toate functiile
import make_functions
fdir = os.path.join(TMP, "functii")
ro_f, en_f = make_functions.build(fdir, "9.9.9")
for f, word in ((ro_f, "Comanda"), (en_f, "Command")):
    txt = open(f, encoding="utf-8").read()
    for c in make_ribbon.CMDS:
        assert f"<code>{c}</code>" in txt, (os.path.basename(f), c)          # fiecare comanda apare
    assert txt.count("<code>") == len(make_ribbon.CMDS), "fiecare comanda o singura data"
    assert f"({len(make_ribbon.CMDS)} " in txt and "9.9.9" in txt and word in txt
assert "Funcțiile TopoKit" in open(ro_f, encoding="utf-8").read() and "TopoKit functions" in open(en_f, encoding="utf-8").read()
print(f"Pagina cu functiile: {len(make_ribbon.CMDS)} comenzi, romana si engleza")

shutil.rmtree(TMP, ignore_errors=True)
print("\nToate testele de limba si ribbon au trecut.")
