#!/usr/bin/env python3
"""Construieste instalatorul Windows TopoKitSetup.exe.

    python3 tools/build_installer.py [--version 1.8.0] [--out dist]

Necesita (Linux: apt install nsis mingw-w64; Windows: NSIS 3 + MinGW-w64 in PATH):
    makensis, x86_64-w64-mingw32-gcc, x86_64-w64-mingw32-windres
    (pe Windows merg si gcc / windres din MSYS2-MinGW64).

Licenta: daca exista installer/licensing.json (facut cu tools/licenta.py: kid, public_key,
server), cheia publica si adresa serverului se compileaza in TopoKit.exe, iar TopoKitLoad.lsp
din pachet primeste *TKL:LICENTA* = T si lista comenzilor modulelor (fara licenta valabila
comenzile doar trimit la activare). Fara fisier, build-ul ramane fara licentiere (ca inainte).

Pasi:
  1. compileaza lansatorul installer/launcher/topokit.c + ui.c + license.c -> TopoKit.exe;
  2. pregateste build/stage:
       bundle/TopoKit.bundle/PackageContents.xml   (versiunea completata)
       bundle/TopoKit.bundle/Contents/             *.lsp, *.dcl, grila .gsb, anexe/, README,
                                                   TopoKit.cuix / TopoKit_EN.cuix (ribbon), en/ (engleza)
       app/                                        TopoKit.exe, README.html, Functii(_EN).html, docs/,
                                                   PlanInclinare/ (PlanInclinare.exe, PyInstaller),
                                                   modules/ (DWG to KMZ, modulul TopoKit, PyInstaller)
  3. ruleaza makensis installer/TopoKit.nsi -> dist/TopoKitSetup-<versiune>.exe
"""
import argparse, html, os, pathlib, re, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INST = ROOT / "installer"
LSP = ["TopoKitLoad.lsp", "TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitTeren.lsp", "TopoKitInclinare.lsp", "TopoKitCad.lsp", "TopoKitProiect.lsp"]
DCL = ["TopoKit.dcl", "TopoKitAnexe.dcl", "TopoKitTeren.dcl", "TopoKitInclinare.dcl"]
GRID = "stereo70_etrs89A.gsb"
TDGRID = "ETRS89_KRASOVSCHI42_2DJ.GRD"   # grila oficiala ANCPI TransDatRO


def tool(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    sys.exit("Lipseste: " + " / ".join(names) + " (Linux: apt install nsis mingw-w64)")


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def licensing_config():
    """installer/licensing.json -> dict cu kid, public_key, server (sau None = fara licentiere)."""
    f = INST / "licensing.json"
    if not f.exists():
        return None
    import json
    cfg = json.loads(f.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[0-9A-Fa-f]{128}", cfg.get("public_key", "")) or not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", cfg.get("kid", "")):
        sys.exit(f"{f}: lipseste cheia publica sau kid (rulati tools/licenta.py cheie ...)")
    if not str(cfg.get("server", "")).startswith("https://"):
        sys.exit(f"{f}: lipseste adresa serverului de licente (tools/licenta.py server https://...)")
    return cfg


def module_commands():
    """Comenzile AutoCAD definite in module (defun c:NUME), fara cele ale incarcatorului."""
    cmds = set()
    for f in LSP:
        if f != "TopoKitLoad.lsp":
            cmds |= {m.upper() for m in re.findall(r"\(defun\s+c:([A-Za-z0-9_-]+)", (ROOT / f).read_text(encoding="utf-8"), re.I)}
    return sorted(cmds)


def licensed_loader(text, cmds):
    """TopoKitLoad.lsp pentru pachetul cu licentiere: *TKL:LICENTA* = T si lista comenzilor."""
    for old in ("(setq *TKL:LICENTA* nil)", "(setq *TKL:CMDS* nil)"):
        if text.count(old) != 1:
            sys.exit(f"TopoKitLoad.lsp: nu gasesc {old}")
    lst = " ".join(f'"{c}"' for c in cmds)
    return (text.replace("(setq *TKL:LICENTA* nil)", "(setq *TKL:LICENTA* T)")
                .replace("(setq *TKL:CMDS* nil)", f"(setq *TKL:CMDS* '({lst}))"))


def readme_html(md_text):
    """README.md -> README.html (modulul markdown daca exista, altfel text preformatat)."""
    try:
        import markdown
        body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    except ImportError:
        body = "<pre>" + html.escape(md_text) + "</pre>"
    return ("<!doctype html>\n<html lang=\"ro\"><head><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>TopoKit - ghid de utilizare</title>\n<style>\n"
            "body{font:15px/1.55 'Segoe UI',Arial,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;"
            "color:#1d2733;background:#fff}\n"
            "h1,h2,h3{color:#124e78}h2{border-bottom:1px solid #d8e2ea;padding-bottom:4px}\n"
            "code,pre{background:#f2f5f8;border-radius:4px}pre{padding:10px;overflow:auto}code{padding:1px 4px}\n"
            "table{border-collapse:collapse}td,th{border:1px solid #c9d4de;padding:4px 8px}\n"
            "img{max-width:100%;border:1px solid #d8e2ea}\n"
            "</style></head><body>\n" + body + "\n</body></html>\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=(INST / "VERSION").read_text().strip())
    ap.add_argument("--out", default=str(ROOT / "dist"))
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        sys.exit("Versiunea trebuie sa fie de forma X.Y.Z")
    ver_comma = a.version.replace(".", ",") + ",0"

    build = ROOT / "build"
    stage = build / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    bundle = stage / "bundle" / "TopoKit.bundle"
    contents = bundle / "Contents"
    app = stage / "app"
    contents.mkdir(parents=True)
    app.mkdir(parents=True)

    # 1. lansatorul (cu cheia publica a licentelor, daca exista installer/licensing.json)
    lic = licensing_config()
    lic_defs = []
    if lic:
        lic_defs = [f'-DTK_LIC_PUB="{lic["public_key"].upper()}"', f'-DTK_LIC_KID="{lic["kid"]}"',
                    f'-DTK_LIC_URL="{lic["server"].rstrip("/")}"']
        print(f"Licentiere: DA (kid {lic['kid']}, server {lic['server']})")
    else:
        print("Licentiere: nu (lipseste installer/licensing.json) - TopoKit merge fara activare")
    gcc = tool("x86_64-w64-mingw32-gcc", "gcc")
    windres = tool("x86_64-w64-mingw32-windres", "windres")
    res = build / "topokit_res.o"
    run([windres, f"-DTK_VER_COMMA={ver_comma}", f'-DTK_VER_STR=\\"{a.version}\\"',
         "topokit.rc", "-O", "coff", "-o", res], cwd=INST / "launcher")
    run([gcc, "-municode", "-mwindows", "-O2", "-Wall", "-Wextra", "-s", "-static", f'-DTK_VERSION="{a.version}"',
         *lic_defs, "-o", app / "TopoKit.exe", INST / "launcher" / "topokit.c", INST / "launcher" / "ui.c",
         INST / "launcher" / "license.c", res,
         "-lgdiplus", "-lshlwapi", "-lole32", "-loleaut32", "-luuid", "-lshell32", "-lgdi32", "-luser32",
         "-lbcrypt", "-lwinhttp", "-lcrypt32", "-lcomdlg32"])

    # 2. pachetul AutoCAD
    xml = (INST / "bundle" / "PackageContents.xml").read_text(encoding="utf-8")
    (bundle / "PackageContents.xml").write_text(xml.replace("@VERSION@", a.version), encoding="utf-8")
    for f in LSP + DCL + [GRID, TDGRID, "README.md"]:
        shutil.copy2(ROOT / f, contents / f)
    if lic:
        loader = contents / "TopoKitLoad.lsp"
        loader.write_text(licensed_loader(loader.read_text(encoding="utf-8"), module_commands()), encoding="utf-8")
    shutil.copytree(ROOT / "anexe", contents / "anexe")
    shutil.copy2(INST / "launcher" / "topokit.ico", contents / "topokit.ico")
    # ribbonul TopoKit (TopoKit.cuix romana, TopoKit_EN.cuix engleza) si modulele in engleza
    # (Contents\en); TopoKitLoad.lsp alege dupa HKCU\Software\TopoKit\Language
    sys.path.insert(0, str(ROOT / "tools"))
    import i18n, make_ribbon
    for name, en in (("TopoKit.cuix", False), ("TopoKit_EN.cuix", True)):
        make_ribbon.build(contents / name, None, en)
    i18n.build(contents / "en")
    import make_functions                                      # toate functiile (RO / EN)
    make_functions.build(app, a.version)
    (app / "README.html").write_text(readme_html((ROOT / "README.md").read_text(encoding="utf-8")),
                                     encoding="utf-8")
    shutil.copytree(ROOT / "docs", app / "docs")
    shutil.copy2(INST / "launcher" / "topokit.ico", app / "topokit.ico")
    shutil.copytree(INST / "art", stage / "art")

    # 2b. programul Plan Inclinare (calcul inclinatie) ca executabil, fara Python pe calculatorul tinta
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("Lipseste PyInstaller (pip install pyinstaller) - necesar pentru PlanInclinare.exe")
    pi = app / "PlanInclinare"
    pi.mkdir()
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", "PlanInclinare",
         "--icon", INST / "launcher" / "topokit.ico", "--distpath", build / "pi_dist", "--workpath", build / "pi_work",
         "--specpath", build, ROOT / "inclinare" / "plan_inclinare.py"])
    shutil.copy2(build / "pi_dist" / "PlanInclinare.exe", pi / "PlanInclinare.exe")
    for f in ("PlanInclinareCogo.dll", "exemplu_siloz.csv"):
        shutil.copy2(ROOT / "inclinare" / f, pi / f)

    # 2c. convertorul DXF/DWG -> KMZ "DWG to KMZ" (dwg2kmz/), compilat cu PyInstaller
    d2k = ROOT / "dwg2kmz"
    sep = ";" if os.name == "nt" else ":"
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", "DWGtoKMZ",
         "--icon", INST / "launcher" / "topokit.ico",
         "--add-data", f"{d2k / 'assets'}{sep}assets", "--add-data", f"{d2k / 'grids'}{sep}grids",
         "--add-data", f"{d2k / 'tools'}{sep}tools",
         "--collect-all", "customtkinter", "--collect-all", "tkinterdnd2",
         "--collect-data", "pyproj", "--collect-data", "ezdxf",
         "--distpath", build / "d2k_dist", "--workpath", build / "d2k_work", "--specpath", build,
         d2k / "dwg2kmz.py"])
    (app / "modules").mkdir()
    shutil.copy2(build / "d2k_dist" / "DWGtoKMZ.exe", app / "modules" / "DWGtoKMZ.exe")
    shutil.copy2(d2k / "Instructiuni DWG to KMZ.html", app / "modules" / "Instructiuni DWG to KMZ.html")

    # 3. instalatorul
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    setup = out / f"TopoKitSetup-{a.version}.exe"
    makensis = tool("makensis")
    run([makensis, "-V2", "-INPUTCHARSET", "UTF8", f"-DVERSION={a.version}", f"-DSTAGE={stage}",
         f"-DOUTFILE={setup}", INST / "TopoKit.nsi"])
    print(f"\nInstalator: {setup} ({setup.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
