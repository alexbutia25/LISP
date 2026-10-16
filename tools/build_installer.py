#!/usr/bin/env python3
"""Construieste instalatorul Windows TopoKitSetup.exe.

    python3 tools/build_installer.py [--version 1.0.0] [--out dist]

Necesita (Linux: apt install nsis mingw-w64; Windows: NSIS 3 + MinGW-w64 in PATH):
    makensis, x86_64-w64-mingw32-gcc, x86_64-w64-mingw32-windres
    (pe Windows merg si gcc / windres din MSYS2-MinGW64).

Pasi:
  1. compileaza lansatorul installer/launcher/topokit.c -> TopoKit.exe;
  2. pregateste build/stage:
       bundle/TopoKit.bundle/PackageContents.xml   (versiunea completata)
       bundle/TopoKit.bundle/Contents/             *.lsp, *.dcl, grila .gsb, anexe/, README
       app/                                        TopoKit.exe, README.html, docs/
  3. ruleaza makensis installer/TopoKit.nsi -> dist/TopoKitSetup.exe
"""
import argparse, html, pathlib, re, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INST = ROOT / "installer"
LSP = ["TopoKitLoad.lsp", "TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitTeren.lsp"]
DCL = ["TopoKit.dcl", "TopoKitAnexe.dcl", "TopoKitTeren.dcl"]
GRID = "stereo70_etrs89A.gsb"


def tool(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    sys.exit("Lipseste: " + " / ".join(names) + " (Linux: apt install nsis mingw-w64)")


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


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

    # 1. lansatorul
    gcc = tool("x86_64-w64-mingw32-gcc", "gcc")
    windres = tool("x86_64-w64-mingw32-windres", "windres")
    res = build / "topokit_res.o"
    run([windres, f"-DTK_VER_COMMA={ver_comma}", f'-DTK_VER_STR=\\"{a.version}\\"',
         "topokit.rc", "-O", "coff", "-o", res], cwd=INST / "launcher")
    run([gcc, "-municode", "-mwindows", "-O2", "-Wall", "-Wextra", "-s", "-static",
         "-o", app / "TopoKit.exe", INST / "launcher" / "topokit.c", res,
         "-lole32", "-loleaut32", "-luuid", "-lshell32", "-luser32"])

    # 2. pachetul AutoCAD
    xml = (INST / "bundle" / "PackageContents.xml").read_text(encoding="utf-8")
    (bundle / "PackageContents.xml").write_text(xml.replace("@VERSION@", a.version), encoding="utf-8")
    for f in LSP + DCL + [GRID, "README.md"]:
        shutil.copy2(ROOT / f, contents / f)
    shutil.copytree(ROOT / "anexe", contents / "anexe")
    shutil.copy2(INST / "launcher" / "topokit.ico", contents / "topokit.ico")
    (app / "README.html").write_text(readme_html((ROOT / "README.md").read_text(encoding="utf-8")),
                                     encoding="utf-8")
    shutil.copytree(ROOT / "docs", app / "docs")
    shutil.copy2(INST / "launcher" / "topokit.ico", app / "topokit.ico")

    # 3. instalatorul
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    setup = out / "TopoKitSetup.exe"
    makensis = tool("makensis")
    run([makensis, "-V2", "-INPUTCHARSET", "UTF8", f"-DVERSION={a.version}", f"-DSTAGE={stage}",
         f"-DOUTFILE={setup}", INST / "TopoKit.nsi"])
    print(f"\nInstalator: {setup} ({setup.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
