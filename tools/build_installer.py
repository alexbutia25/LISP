#!/usr/bin/env python3
"""Construieste instalatorul Windows TopoKitSetup.exe.

    python3 tools/build_installer.py [--version 1.11.0] [--out dist]

Necesita (Linux: apt install nsis mingw-w64; Windows: NSIS 3 + MinGW-w64 in PATH):
    makensis, x86_64-w64-mingw32-gcc, x86_64-w64-mingw32-windres
    (pe Windows merg si gcc / windres din MSYS2-MinGW64).

Licenta: daca exista installer/licensing.json (facut cu tools/licenta.py: kid, public_key,
server), cheia publica si adresa serverului se compileaza in TopoKit.exe, iar TopoKitLoad.lsp
din pachet primeste *TKL:LICENTA* = T si lista comenzilor modulelor (fara licenta valabila
comenzile doar trimit la activare). Fara fisier, build-ul ramane fara licentiere (ca inainte).

Compilare: modulele AutoLISP (si varianta en/) se compileaza cu tools/compile_lisp.ps1 (accoreconsole,
fara fereastra) in ambele formate .fas, iar sursele modulelor nu mai intra in pachet:
    Contents/fas5/TopoKit*.fas     (FAS5, motorul Unicode, LISPSYS=1)
    Contents/fas4/TopoKit*.fas     (FAS4, motorul vechi LISPSYS=0 si LISPSYS=2)
    Contents/en/fas5/..., Contents/en/fas4/...
Incarcatorul ramane Contents/TopoKitLoad.lsp (PackageContents.xml nu poate alege dupa LISPSYS) si
alege folderul dupa (getvar "LISPSYS") - TKL:Module. In sursa fiecarui format, referintele intre
module devin relative la folderul formatului ("TopoKitAnexe.lsp" -> "fas4\\\\TopoKitAnexe.fas" in
textul LISP), gasite prin calea de suport (Contents/en inaintea Contents). Implicit (--compile auto) se compileaza
cand licentierea e activa - altfel verificarea licentei din .lsp s-ar putea sterge; --compile yes / no
forteaza alegerea.

Pasi:
  1. compileaza lansatorul installer/launcher/topokit.c + ui.c + license.c -> TopoKit.exe;
  2. pregateste build/stage:
       bundle/TopoKit.bundle/PackageContents.xml   (versiunea completata)
       bundle/TopoKit.bundle/Contents/             TopoKitLoad.lsp, module (*.lsp sau fas5/ + fas4/),
                                                   *.dcl, grila .gsb, anexe/, README, VERSION,
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


SECRET_ARGS = ("TK_PROOF",)            # argumente care nu se afiseaza (secretul build-ului / calea lui)


def shown(c):
    """Argumentul asa cum apare in jurnal: cele cu secrete mascate (B3: cheia nu ajunge in loguri)."""
    c = str(c)
    for s in SECRET_ARGS:
        if s in c:
            return c[:c.index(s) + len(s)] + "...=***"
    return c


SECRET_MARKS = ("tk_pk_", "TK_PK_", "tk_proof")    # numele din antetul secretului (lic_gate.proof_header)


def filtered_cc(text, hidden):
    """Iesirea gcc fara nimic din antetul secretului (B5): diagnosticele pentru acel fisier devin o
    linie fara continut, iar liniile de cod citate ("  12 | ...", "     | ^~~") nu se afiseaza deloc
    (gcc citeaza si liniile antetului: octetii mascati ai cheii)."""
    out, masked = [], 0
    hidden = [str(h).replace("\\", "/").lower() for h in hidden]
    for line in text.splitlines():
        norm = line.replace("\\", "/").lower()
        if re.match(r"\s*\d*\s*\|", line):                 # sursa citata / sublinierea ^~~
            continue
        if any(h in norm for h in hidden) or any(m in line for m in SECRET_MARKS):
            masked += 1
            continue
        out.append(line)
    if masked:
        out.append(f"[{masked} linii despre antetul secretului build-ului ascunse]")
    return "\n".join(out)


def run(cmd, hidden=None, **kw):
    """hidden = fisiere secrete folosite de comanda (antetul /proof): iesirea se filtreaza (filtered_cc)."""
    print("+", " ".join(shown(c) for c in cmd))
    if hidden:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, errors="replace", **kw)
        msg = filtered_cc((r.stdout or "") + (r.stderr or ""), hidden)
        if msg.strip():
            print(msg)
        if r.returncode:
            sys.exit(f"Comanda a esuat (cod {r.returncode}): {shown(cmd[0])}")
        return
    try:
        subprocess.run([str(c) for c in cmd], check=True, **kw)
    except subprocess.CalledProcessError as e:      # mesajul implicit ar contine toata linia de comanda
        sys.exit(f"Comanda a esuat (cod {e.returncode}): {shown(cmd[0])}")


def secret_in(path, secret):
    """secret (octeti) apare in fisier: in clar, ca hex (mici / mari, si UTF-16) - B7."""
    data = pathlib.Path(path).read_bytes()
    hx = secret.hex()
    return any(x in data for x in (secret, hx.encode(), hx.upper().encode(), hx.encode("utf-16-le"),
                                    hx.upper().encode("utf-16-le")))


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
    """Comenzile AutoCAD definite in module (defun c:NUME), fara cele ale incarcatorului.
    Foloseste exact acelasi extractor ca poarta de licenta (lic_gate.commands), ca lista
    stub-urilor din incarcator (*TKL:CMDS*) sa nu difere niciodata de cea din footerele modulelor."""
    sys.path.insert(0, str(ROOT / "tools"))
    import lic_gate
    cmds = set()
    for f in LSP:
        if f != "TopoKitLoad.lsp":
            cmds |= set(lic_gate.commands((ROOT / f).read_text(encoding="utf-8")))
    return sorted(cmds)


def licensed_loader(text, cmds):
    """TopoKitLoad.lsp pentru pachetul cu licentiere: *TKL:LICENTA* = T si lista comenzilor."""
    for old in ("(setq *TKL:LICENTA* nil)", "(setq *TKL:CMDS* nil)"):
        if text.count(old) != 1:
            sys.exit(f"TopoKitLoad.lsp: nu gasesc {old}")
    lst = " ".join(f'"{c}"' for c in cmds)
    return (text.replace("(setq *TKL:LICENTA* nil)", "(setq *TKL:LICENTA* T)")
                .replace("(setq *TKL:CMDS* nil)", f"(setq *TKL:CMDS* '({lst}))"))


FAS_FORMATS = ("fas5", "fas4")                       # folderele din Contents (si Contents\en)
FAS_HEADER = {"fas5": b"FAS5-FILE", "fas4": b"FAS4-FILE"}
MODULES = [pathlib.Path(f).stem for f in LSP if f != "TopoKitLoad.lsp"]   # incarcatorul nu se compileaza


def compiled_source(text, fmt):
    """Sursa unui modul pentru formatul fmt (fas5 / fas4): fisierele celorlalte module se cauta
    compilate, in folderul formatului ("TopoKitAnexe.lsp" -> "fas4\\\\TopoKitAnexe.fas"); findfile
    le gaseste prin calea de suport (Contents\\en, apoi Contents)."""
    assert fmt in FAS_FORMATS, fmt
    names = "|".join(sorted(MODULES, key=len, reverse=True))
    return re.sub(rf'"({names})\.lsp"', rf'"{fmt}\\\\\1.fas"', text)


def module_source(text, module, fmt, key):
    """Textul compilat pentru modulul module ("TopoKit", "TopoKitAnexe" ...) in formatul fmt.
    Singurul loc in care se pregateste sursa inainte de compilare. key = secretul build-ului
    (32 de octeti; vezi tools/lic_gate.py) sau None pentru un build fara licentiere (fara poarta)."""
    # ordinea: ofuscare -> poarta de licenta -> referinte compilate. Doar la build-urile licentiate
    # (key != None); la dezvoltare textul ramane neschimbat.
    sys.path.insert(0, str(ROOT / "tools"))
    import lic_gate, obfuscate
    # ofuscarea (tools/obfuscate.py): redenumeste simbolurile interne (defun / globale *...*) in nume
    # fara inteles, consecvent peste toate modulele si variantele en/ (seed = secretul build-ului key),
    # ca .fas-ul sa nu mai pastreze numele lizibile. Inainte de poarta, ca poarta sa pazeasca numele noi.
    if key is not None:
        text = obfuscate.apply(text, key)
    # poarta de licenta (tools/lic_gate.py): fiecare modul compilat isi verifica singur licenta prin
    # provocare-raspuns cu TopoKit.exe (HMAC pe secretul build-ului), pentru ambele formate si en/
    text = lic_gate.inject(text, module, key)
    return compiled_source(text, fmt)


def compile_lisp(files, fmt):
    """Compileaza .lsp -> <dir>/<fmt>/<nume>.fas cu tools/compile_lisp.ps1; opreste build-ul la eroare."""
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(ROOT / "tools" / "compile_lisp.ps1"), "-Format", fmt,
                        "-Files", ",".join(str(f) for f in files)],
                       capture_output=True, text=True)
    print(r.stdout.strip())
    outs = [f.parent / fmt / (f.stem + ".fas") for f in files]
    bad = [o for o in outs if not o.exists() or FAS_HEADER[fmt] not in o.read_bytes()[:64]]
    if r.returncode or bad:
        sys.exit(f"Compilarea modulelor AutoLISP ({fmt}) a esuat" + (": " + r.stderr.strip() if r.stderr.strip() else "") +
                 "\n(trebuie sa existe AutoCAD instalat; sau --compile no pentru un build de test)")
    return outs


def compile_modules(contents, work, key):
    """Modulele din contents (si contents/en) -> contents[/en]/fas5|fas4/*.fas; sursele lor se sterg.
    Incarcatorul TopoKitLoad.lsp ramane necompilat. work = folder temporar pentru sursele pregatite.
    key = secretul build-ului (32 de octeti) incorporat in poarta fiecarui modul."""
    langs = [d for d in (contents, contents / "en") if (d / "TopoKit.lsp").exists()]
    srcs = {d: [d / f"{m}.lsp" for m in MODULES if (d / f"{m}.lsp").exists()] for d in langs}
    n = 0
    try:      # sursele pregatite contin poarta (constantele secretului): sterse si la eroare (B3)
        for fmt in FAS_FORMATS:
            if work.exists():
                shutil.rmtree(work)
            files = []
            for d in langs:
                wd = work / fmt / d.relative_to(contents)
                wd.mkdir(parents=True, exist_ok=True)
                for f in srcs[d]:
                    w = wd / f.name
                    w.write_text(module_source(f.read_text(encoding="utf-8"), f.relative_to(contents).with_suffix("").as_posix(), fmt, key), encoding="utf-8")
                    files.append(w)
            for o in compile_lisp(files, fmt):
                dst = contents / o.parent.parent.relative_to(work / fmt) / fmt / o.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(o, dst)
                n += 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for d in langs:
        for f in srcs[d]:
            f.unlink()
    return n


def public_readme(md_text):
    """README-ul livrat: fara sectiunile pentru administrator / dezvoltare (cum functioneaza
    licentierea, build-ul, testele) - acelea raman doar in proiect."""
    s = md_text
    a = s.find("- **Pentru tine (administrator):**")
    b = s.find("## Detalii tehnice")
    if 0 <= a < b:
        s = s[:a].rstrip() + "\n\n" + s[b:]
    a, b = s.find("**Activarea este opțională.**"), s.find("- **Pentru coleg:**")
    if 0 <= a < b:
        s = s[:a] + s[b:]
    d = s.find("## Dezvoltare")
    if d >= 0:
        s = s[:d].rstrip() + "\n"
    # optiunea /license din lista liniei de comanda e pentru administrator / module (B6)
    s = re.sub(r",?[ \t]*`/license`[ \t]*\([^)\n]*\)", "", s)
    return s


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
    ap.add_argument("--compile", choices=["auto", "yes", "no"], default="auto",
                    help="modulele AutoLISP in .fas (auto = cand licentierea e activa)")
    ap.add_argument("--build", default=str(ROOT / "build"),
                    help="folderul de lucru (pe Windows o cale scurta: makensis nu deschide cai > 260 caractere)")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        sys.exit("Versiunea trebuie sa fie de forma X.Y.Z")
    ver_comma = a.version.replace(".", ",") + ",0"

    build = pathlib.Path(a.build).resolve()
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
    proof_key = None
    proof_h = build / "tk_proof.h"
    if lic:
        # secretul build-ului pentru provocare-raspuns (modulele AutoLISP + TopoKit.exe): 32 de octeti
        # aleatori, niciodata in depozit. In TopoKit.exe intra printr-un antet generat (bucati amestecate
        # si mascate, lic_gate.proof_header), nu prin linia de comanda; antetul se sterge dupa compilare.
        sys.path.insert(0, str(ROOT / "tools"))
        import lic_gate
        proof_key = os.urandom(32)
        lic_defs = [f'-DTK_LIC_PUB="{lic["public_key"].upper()}"', f'-DTK_LIC_KID="{lic["kid"]}"',
                    f'-DTK_LIC_URL="{lic["server"].rstrip("/")}"', f'-DTK_PROOF_FILE="{proof_h.as_posix()}"']
        print(f"Licentiere: DA (kid {lic['kid']}, server {lic['server']})")
    else:
        print("Licentiere: nu (lipseste installer/licensing.json) - TopoKit merge fara activare")
    gcc = tool("x86_64-w64-mingw32-gcc", "gcc")
    windres = tool("x86_64-w64-mingw32-windres", "windres")
    res = build / "topokit_res.o"
    run([windres, f"-DTK_VER_COMMA={ver_comma}", f'-DTK_VER_STR=\\"{a.version}\\"',
         "topokit.rc", "-O", "coff", "-o", res], cwd=INST / "launcher")
    try:
        if proof_key:       # antetul exista doar pe durata compilarii (sters in finally, si la eroare)
            build.mkdir(parents=True, exist_ok=True)
            proof_h.write_text(lic_gate.proof_header(proof_key), encoding="ascii")
        run([gcc, "-municode", "-mwindows", "-O2", "-Wall", "-Wextra", "-s", "-static", f'-DTK_VERSION="{a.version}"',
             *lic_defs, "-o", app / "TopoKit.exe", INST / "launcher" / "topokit.c", INST / "launcher" / "ui.c",
             INST / "launcher" / "license.c", res,
             "-lgdiplus", "-lshlwapi", "-lole32", "-loleaut32", "-luuid", "-lshell32", "-lgdi32", "-luser32",
             "-lbcrypt", "-lwinhttp", "-lcrypt32", "-lcomdlg32"],
            hidden=[proof_h] if proof_key else None)
    finally:
        proof_h.unlink(missing_ok=True)
    if proof_key and secret_in(app / "TopoKit.exe", proof_key):
        sys.exit("Secretul build-ului apare in clar in TopoKit.exe")

    # 2. pachetul AutoCAD
    xml = (INST / "bundle" / "PackageContents.xml").read_text(encoding="utf-8")
    (bundle / "PackageContents.xml").write_text(xml.replace("@VERSION@", a.version), encoding="utf-8")
    for f in LSP + DCL + [GRID, TDGRID]:
        shutil.copy2(ROOT / f, contents / f)
    (contents / "README.md").write_text(public_readme((ROOT / "README.md").read_text(encoding="utf-8")),
                                        encoding="utf-8")
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
    (contents / "VERSION").write_text(a.version + "\n", encoding="ascii")
    if a.compile == "yes" or (a.compile == "auto" and lic):
        if os.name != "nt":
            sys.exit("Compilarea .fas are nevoie de Windows si AutoCAD")
        n = compile_modules(contents, build / "fas_src", proof_key)
        print(f"Module compilate: {n} fisiere .fas in {' / '.join(FAS_FORMATS)} (sursele modulelor nu intra "
              "in pachet; incarcatorul ramane TopoKitLoad.lsp)")
    else:
        print("Module necompilate (.lsp) - build de dezvoltare / test")
    import make_functions                                      # toate functiile (RO / EN)
    make_functions.build(app, a.version)
    (app / "README.html").write_text(readme_html(public_readme((ROOT / "README.md").read_text(encoding="utf-8"))),
                                     encoding="utf-8")
    shutil.copytree(ROOT / "docs", app / "docs")
    shutil.copy2(INST / "launcher" / "topokit.ico", app / "topokit.ico")
    shutil.copytree(INST / "art", stage / "art")

    # 2b. programele Python (Plan Inclinare, DWG to KMZ) ca executabile, fara Python pe calculatorul tinta.
    # Nuitka --standalone: codul Python devine C compilat (fara bytecode .pyc de decompilat); rezulta un
    # folder <nume>.dist cu exe + DLL-uri + date, copiat intreg in PlanInclinare\ si modules\.
    # Fara Nuitka: PyInstaller --onefile (bytecode decompilabil) - doar avertisment, pentru build-uri de test.
    ico = INST / "launcher" / "topokit.ico"
    try:
        import nuitka  # noqa: F401
        use_nuitka = True
    except ImportError:
        use_nuitka = False
        print("ATENTIE: lipseste Nuitka (pip install nuitka) - programele Python se fac cu PyInstaller, "
              "iar bytecode-ul lor se poate decompila. Nu distribui acest build.")
        try:
            import PyInstaller  # noqa: F401
        except ImportError:
            sys.exit("Lipseste Nuitka (pip install nuitka) si PyInstaller - necesare pentru PlanInclinare.exe / DWGtoKMZ.exe")

    def python_app(script, name, dest, data_dirs=(), raw_dirs=(), packages=(), extra=()):
        """Compileaza script (GUI tkinter, fara consola) in folderul dest (dest/<name>.exe + dependinte)."""
        out = build / f"{name}_nuitka" if use_nuitka else build / f"{name}_pyi"
        if use_nuitka:
            cmd = [sys.executable, "-m", "nuitka", "--standalone", "--enable-plugin=tk-inter",
                   "--windows-console-mode=disable", f"--windows-icon-from-ico={ico}",
                   f"--output-dir={out}", f"--output-filename={name}.exe", "--remove-output",
                   "--product-name=TopoKit", f"--file-description={name}",
                   f"--product-version={re.match(r'[0-9.]*', a.version).group().strip('.') or '0'}",
                   "--progress-bar=none", "--include-module=_tk_pub", "--python-flag=no_docstrings"]
            if os.name == "nt":
                # fara descarcari: depends.exe inlocuit cu pefile (inclus in Nuitka), iar daca e gcc
                # (MinGW-w64 / winlibs) in PATH il folosim pe acela in locul gcc-ului descarcat de Nuitka
                cmd.append("--experimental=force-dependencies-pefile")
                if shutil.which("gcc"):
                    cmd += ["--mingw64", "--experimental=force-accept-windows-gcc"]
            cmd += [f"--include-data-dir={d}={d.name}" for d in data_dirs]
            cmd += [f"--include-raw-dir={d}={d.name}" for d in raw_dirs]
            # packages: datele lor (customtkinter/assets, tkinterdnd2/tkdnd, pyproj/proj_dir) le adauga
            # configuratia de pachete din Nuitka; --include-package-data ar copia si sursele .c/.pxd
            cmd += list(extra) + [script]
            # stdin=DEVNULL: daca Nuitka tot vrea sa descarce ceva (compilator etc.) raspunde "no" si se opreste
            run(cmd, stdin=subprocess.DEVNULL)
            dist = out / f"{script.stem}.dist"
            if not (dist / f"{name}.exe").exists():
                sys.exit(f"Nuitka nu a produs {dist / (name + '.exe')}")
            shutil.copytree(dist, dest, dirs_exist_ok=True)
        else:
            sep = ";" if os.name == "nt" else ":"
            cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", name,
                   "--icon", ico, "--distpath", out / "dist", "--workpath", out / "work", "--specpath", out,
                   "--hidden-import", "_tk_pub"]
            for d in list(data_dirs) + list(raw_dirs):
                cmd += ["--add-data", f"{d}{sep}{d.name}"]
            for pk in packages:
                cmd += ["--collect-all" if pk in ("customtkinter", "tkinterdnd2") else "--collect-data", pk]
            run(cmd + [script])
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(out / "dist" / f"{name}.exe", dest / f"{name}.exe")

    # cheia publica pentru verificarea licentei in programele Python (tklic.py): modulul generat
    # _tk_pub.py (mascat) langa fiecare program, doar pe durata compilarii; mereu, si fara licentiere
    # (atunci gol), pentru ca tklic compilat fara el refuza pornirea
    import licenta
    d2k = ROOT / "dwg2kmz"
    pubs = [ROOT / "inclinare" / licenta.PUB_MODULE, d2k / licenta.PUB_MODULE]
    for p in pubs:
        licenta.write_pub_module(p, lic["public_key"] if lic else None, lic["kid"] if lic else None)
    try:
        # Plan Inclinare (calcul inclinatie): doar biblioteca standard + tkinter
        pi = app / "PlanInclinare"
        python_app(ROOT / "inclinare" / "plan_inclinare.py", "PlanInclinare", pi)
        for f in ("PlanInclinareCogo.dll", "exemplu_siloz.csv"):
            shutil.copy2(ROOT / "inclinare" / f, pi / f)

        # 2c. convertorul DXF/DWG -> KMZ "DWG to KMZ" (dwg2kmz/): customtkinter, tkinterdnd2, pyproj (cu
        # datele PROJ), ezdxf; assets/ si grids/ ca date, tools/ (LibreDWG dwg2dxf.exe + DLL-uri) ca atare
        python_app(d2k / "dwg2kmz.py", "DWGtoKMZ", app / "modules",
                   data_dirs=(d2k / "assets", d2k / "grids"), raw_dirs=(d2k / "tools",),
                   packages=("customtkinter", "tkinterdnd2", "pyproj", "ezdxf"))
    finally:
        for p in pubs:
            p.unlink(missing_ok=True)
    if lic:   # cheia publica nu trebuie sa apara in clar (hex sau cei 64 de octeti) in programele compilate
        raw = bytes.fromhex(lic["public_key"])
        for exe in (pi / "PlanInclinare.exe", app / "modules" / "DWGtoKMZ.exe"):
            if secret_in(exe, raw):
                sys.exit(f"Cheia publica apare in clar in {exe}")
    if proof_key:   # secretul build-ului: nici in .fas (acolo sunt doar starile intermediare HMAC)
        for f in contents.rglob("*.fas"):
            if secret_in(f, proof_key):
                sys.exit(f"Secretul build-ului apare in clar in {f}")
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
