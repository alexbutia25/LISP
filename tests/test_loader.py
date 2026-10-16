#!/usr/bin/env python3
"""Teste offline pentru incarcatorul TopoKitLoad.lsp si pachetul AutoCAD.

    python3 tests/test_loader.py

Verifica, in simulatorul AutoCAD:
  - gasirea folderului din registru (HKCU\\Software\\TopoKit\\ContentsDir),
    cu revenire la calea de cautare daca valoarea lipseste sau e gresita;
  - adaugarea folderului in calea de suport si in TRUSTEDPATHS o singura data;
  - incarcarea TopoKit + Anexe + Teren si reincarcarea (TOPOKITRELOAD);
  - expresia trimisa de lansatorul TopoKit.exe (installer/launcher/topokit.c);
  - PackageContents.xml: XML valid, modulul incarcat exista, SupportPath.
"""
import os, re, sys, tempfile, xml.dom.minidom
sys.path.insert(0, os.path.dirname(__file__))
from acad_sim import Acad, Sym, call, env, T
import autolisp_mini as M

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = tempfile.mkdtemp(prefix="topokit_loader_")
acad = Acad(ROOT, OUT)

reg = {("HKEY_CURRENT_USER\\Software\\TopoKit", "ContentsDir"): ROOT.replace("/", "\\") + "\\"}
prefs = {"SupportPath": "C:\\Program Files\\Autodesk\\AutoCAD 2024\\support;C:\\Lucru"}
acad.vars["TRUSTEDPATHS"] = ""
M.funcs[Sym("VL-REGISTRY-READ")] = lambda k, v=None: reg.get((k, v))
M.funcs[Sym("VLA-GET-PREFERENCES")] = lambda a: "prefs"
M.funcs[Sym("VLA-GET-FILES")] = lambda p: "files"
M.funcs[Sym("VLA-GET-SUPPORTPATH")] = lambda f: prefs["SupportPath"]
M.funcs[Sym("VLA-PUT-SUPPORTPATH")] = lambda f, v: prefs.__setitem__("SupportPath", v)
loads = []
orig_load = M.funcs[Sym("LOAD")]
M.funcs[Sym("LOAD")] = lambda f, *a: (loads.append(os.path.basename(f.replace("\\", "/"))), orig_load(f, *a))[1]


def fn(name, *a): return call(Sym(name.upper()), list(a))
def defined(sym): return env.get(Sym(sym.upper())) is not None or Sym(sym.upper()) in M.funcs
def run(src):
    for form in M.parse(M.tokenize(src)): M.ev(form)
def dirs(path): return [p for p in path.split(";") if p]


# ---------------------------------------------------------------- prima incarcare (AutoCAD porneste)
M.load(os.path.join(ROOT, "TopoKitLoad.lsp"))
acad.after_load()
win_root = "\\" + ROOT.strip("/").replace("/", "\\")
assert fn("TKL:Dir") == win_root, fn("TKL:Dir")
assert loads == ["TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitTeren.lsp"], loads
for c in ("C:TOPOKIT", "C:ANEXE", "C:TOPOTEREN", "C:TOPOKITRELOAD", "C:EXPKMZ"):
    assert defined(c), c
assert dirs(prefs["SupportPath"])[0] == win_root and len(dirs(prefs["SupportPath"])) == 3, prefs
assert acad.vars["TRUSTEDPATHS"] == win_root + "\\...", acad.vars["TRUSTEDPATHS"]
assert any("TopoKit pregatit" in o for o in acad.out)
print("Prima incarcare: TopoKit, Anexe, Teren; cale de suport si TRUSTEDPATHS actualizate")

# ---------------------------------------------------------------- desen nou: fara dubluri, fara reincarcare
loads.clear()
M.load(os.path.join(ROOT, "TopoKitLoad.lsp"))
assert loads == [], loads
assert len(dirs(prefs["SupportPath"])) == 3 and acad.vars["TRUSTEDPATHS"].count(";") == 0
print("Al doilea desen: folderul nu se adauga din nou, modulele nu se reincarca")

# ---------------------------------------------------------------- TOPOKITRELOAD
loads.clear()
fn("C:TOPOKITRELOAD")
assert loads == ["TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitTeren.lsp"], loads
assert any("TopoKit reincarcat" in o for o in acad.out)
print("TOPOKITRELOAD reincarca toate modulele")

# ---------------------------------------------------------------- registru gresit -> calea de cautare
reg[("HKEY_CURRENT_USER\\Software\\TopoKit", "ContentsDir")] = "C:\\NuExista"
assert fn("TKL:Dir") == win_root
reg.clear()
assert fn("TKL:Dir") == win_root
acad.vars["TRUSTEDPATHS"] = "C:\\Alt;" + ROOT.replace("/", "\\") + "\\..."
assert fn("TKL:AddTrusted", win_root) is None          # deja de incredere (cu "\\...")
assert fn("TKL:InList", win_root.lower() + "\\", "x;" + win_root) is T
print("Folder gasit si fara registru; comparatii fara diferente de litere / separator final")

# ---------------------------------------------------------------- expresia trimisa de TopoKit.exe
src = open(os.path.join(ROOT, "installer", "launcher", "topokit.c"), encoding="utf-8").read()
m = re.search(r'L"\\x03\\x03(\(progn \(if \(not TKL:Load\) \(load \\"%ls\\"\)\) \(if \(not c:TOPOKIT\).*?)\\n%ls%ls"', src)
assert m, "expresia de incarcare din topokit.c"
expr = m.group(1).replace('\\"', '"').replace("%ls", ROOT + "/TopoKitLoad.lsp")
for k in ("TKL:LOAD", "C:TOPOKIT", "TK:START", "TKA:GENERATE", "TKT:MENU"):
    env.pop(Sym(k), None)
loads.clear()
run(expr)
assert loads == ["TopoKitLoad.lsp", "TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitTeren.lsp"], loads
loads.clear()
run(expr)                                             # deja incarcat: nimic
assert loads == [], loads
print("Expresia lansatorului incarca TopoKit doar daca lipseste")

# ---------------------------------------------------------------- PackageContents.xml
doc = xml.dom.minidom.parse(os.path.join(ROOT, "installer", "bundle", "PackageContents.xml"))
ce = doc.getElementsByTagName("ComponentEntry")[0]
mod = ce.getAttribute("ModuleName")
assert mod == "./Contents/TopoKitLoad.lsp" and ce.getAttribute("LoadOnAutoCADStartup") == "True"
assert ce.getAttribute("PerDocument") == "True"
for rr in doc.getElementsByTagName("RuntimeRequirements"):
    assert rr.getAttribute("SupportPath") == "./Contents" and rr.getAttribute("SeriesMin") == "R19.0"
assert "@VERSION@" in doc.documentElement.getAttribute("AppVersion")
print("PackageContents.xml valid")

# ---------------------------------------------------------------- textele LISP sunt ASCII
txt = open(os.path.join(ROOT, "TopoKitLoad.lsp"), encoding="utf-8").read()
assert all(ord(ch) < 128 for ch in txt), "TopoKitLoad.lsp trebuie sa fie ASCII"
print("\nToate testele incarcatorului au trecut.")
