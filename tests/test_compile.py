#!/usr/bin/env python3
"""Teste offline pentru pachetul compilat (.fas in doua formate), fara AutoCAD.

    python tests/test_compile.py

Verifica:
  - compiled_source (tools/build_installer.py): in fiecare modul (si varianta en/), pentru fiecare
    format (fas5 / fas4), referintele "TopoKitX.lsp" devin "<fmt>\\\\TopoKitX.fas" si nu se schimba
    nimic altceva; locul unic pentru poarta de licenta (module_source);
  - compile_modules: Contents[/en]/fas5 si fas4 cu toate modulele, sursele modulelor sterse,
    incarcatorul TopoKitLoad.lsp pastrat (compilarea simulata, fara AutoCAD);
  - TKL:Module / TKL:Dir / TKL:LangDir (TopoKitLoad.lsp): fas5 cand LISPSYS=1, altfel fas4,
    altfel .lsp langa incarcator; TKL:FileVersion citeste VERSION, altfel TopoKit.lsp;
  - lansatorul (topokit.c) gaseste incarcatorul (.fas sau .lsp); PackageContents.xml ramane pe .lsp;
  - tools/compile_lisp.ps1: accoreconsole, profilul implicit refacut, nu atinge acad.exe.
"""
import os, pathlib, re, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_installer as B
import i18n
from acad_sim import Acad, Sym, call
import autolisp_mini as M


def code_lines(text):
    """Liniile de cod (fara cele care sunt doar comentariu ;;)."""
    return [l for l in text.splitlines() if not l.lstrip().startswith(";")]


# ---------------------------------------------------------------- compiled_source
TMP = pathlib.Path(tempfile.mkdtemp(prefix="topokit_compile_"))
mods = [f for f in B.LSP if f != "TopoKitLoad.lsp"]
assert B.MODULES == [pathlib.Path(f).stem for f in mods], B.MODULES
srcs = {f: (ROOT / f).read_text(encoding="utf-8") for f in mods}
i18n.build(TMP / "en")
srcs.update({"en/" + p.name: p.read_text(encoding="utf-8") for p in sorted((TMP / "en").glob("*.lsp"))})
assert len(srcs) == 2 * len(mods), sorted(srcs)
total = 0
for fmt in B.FAS_FORMATS:
    for name, text in srcs.items():
        out = B.compiled_source(text, fmt)
        left = [l for l in code_lines(out) if re.search(r'TopoKit\w*\.lsp"', l, re.I)]
        assert not left, f"{name} ({fmt}): referinte .lsp ramase: {left[:3]}"
        other = "fas4" if fmt == "fas5" else "fas5"
        assert f'"{other}\\\\' not in out, f"{name}: alt format in sursa {fmt}"
        back = re.sub(rf'"{fmt}\\\\(TopoKit\w*)\.fas"', r'"\1.lsp"', out)      # "fas4\\X.fas" in textul LISP
        assert back == text, f"{name} ({fmt}): compiled_source a schimbat si altceva decat numele modulelor"
        total += len(re.findall(rf'"{fmt}\\\\TopoKit\w*\.fas"', out))
assert total > 20, total
assert B.compiled_source('(load (findfile "TopoKitAnexe.lsp"))', "fas4") == '(load (findfile "fas4\\\\TopoKitAnexe.fas"))'
assert B.compiled_source('(findfile "TopoKit.lsp")', "fas5") == '(findfile "fas5\\\\TopoKit.fas")'
assert B.compiled_source('(findfile "Alt.lsp")', "fas5") == '(findfile "Alt.lsp")'          # doar modulele TopoKit
assert B.compiled_source('(findfile "TopoKitLoad.lsp")', "fas5") == '(findfile "TopoKitLoad.lsp")'  # incarcatorul ramane .lsp
try:
    B.compiled_source("", "fas3")
    raise SystemExit("compiled_source accepta un format necunoscut")
except AssertionError:
    pass
bi = (ROOT / "tools" / "build_installer.py").read_text(encoding="utf-8")
ms = re.search(r"def module_source\(text, module, fmt, key\):(.*?)\n\n\n", bi, re.S)
assert ms and "lic_gate.inject(text, module, key)" in ms.group(1) and "compiled_source(text, fmt)" in ms.group(1), \
    "module_source: locul marcat pentru poarta de licenta"
assert bi.count("module_source(") == 2, "module_source se apeleaza intr-un singur loc"
print(f"compiled_source: {len(srcs)} module x {len(B.FAS_FORMATS)} formate, {total} referinte -> <fmt>\\\\X.fas")

# ---------------------------------------------------------------- compile_modules (compilare simulata)
contents = TMP / "Contents"
contents.mkdir()
for f in B.LSP:
    shutil.copy2(ROOT / f, contents / f)
shutil.copytree(TMP / "en", contents / "en")
calls = []


def fake_compile(files, fmt):
    calls.append((fmt, [pathlib.Path(f) for f in files]))
    outs = []
    for f in files:
        f = pathlib.Path(f)
        txt = f.read_text(encoding="utf-8")
        assert '"fas4\\\\' not in txt if fmt == "fas5" else '"fas5\\\\' not in txt, (f, fmt)
        o = f.parent / fmt / (f.stem + ".fas")
        o.parent.mkdir(exist_ok=True)
        o.write_bytes(b"\r\n " + B.FAS_HEADER[fmt] + b" ; Do not change it!\r\n" + txt.encode("utf-8"))
        outs.append(o)
    return outs


real = B.compile_lisp
B.compile_lisp = fake_compile
try:
    n = B.compile_modules(contents, TMP / "work", os.urandom(32))   # secretul build-ului (poarta de licenta)
finally:
    B.compile_lisp = real
assert [c[0] for c in calls] == ["fas5", "fas4"], "o compilare (o consola) pe format"
assert all(len(c[1]) == 2 * len(mods) for c in calls), [len(c[1]) for c in calls]
assert n == 4 * len(mods), n
for sub in ("", "en"):
    d = contents / sub
    assert not [m for m in mods if (d / m).exists()], f"{d}: sursele modulelor au ramas"
    for fmt in B.FAS_FORMATS:
        got = sorted(p.name for p in (d / fmt).glob("*.fas"))
        assert got == sorted(m.replace(".lsp", ".fas") for m in mods), (d, fmt, got)
        for p in (d / fmt).glob("*.fas"):
            assert B.FAS_HEADER[fmt] in p.read_bytes()[:64], p
assert (contents / "TopoKitLoad.lsp").exists() and not (contents / "en" / "TopoKitLoad.lsp").exists()
assert not list(contents.glob("*.fas")) and not (TMP / "work").exists()
assert '"fas5\\\\TopoKitAnexe.fas"' in (contents / "fas5" / "TopoKit.fas").read_bytes().decode("utf-8", "replace")
assert '"fas4\\\\TopoKit.fas"' in (contents / "en" / "fas4" / "TopoKitAnexe.fas").read_bytes().decode("utf-8", "replace")
print(f"compile_modules: {n} fisiere in Contents[/en]/fas5 + fas4; TopoKitLoad.lsp ramane sursa")

# B3: la o compilare esuata sursele pregatite (cu poarta = constantele secretului) se sterg oricum;
# comenzile afisate nu contin secretul; README-ul livrat nu mai listeaza /license (B6)
c2 = TMP / "Contents2"
c2.mkdir()
for f in B.LSP:
    shutil.copy2(ROOT / f, c2 / f)


def failing_compile(files, fmt):
    assert all(pathlib.Path(f).exists() for f in files)
    sys.exit("compilare esuata (simulat)")


B.compile_lisp = failing_compile
try:
    B.compile_modules(c2, TMP / "work2", os.urandom(32))
    raise AssertionError("compilarea esuata nu a oprit build-ul")
except SystemExit:
    pass
finally:
    B.compile_lisp = real
assert not (TMP / "work2").exists(), "sursele cu poarta au ramas dupa o compilare esuata"
assert B.shown('-DTK_PROOF_FILE="C:/b/tk_proof.h"') == "-DTK_PROOF...=***"
assert B.shown('-DTK_LIC_KID="k1"') == '-DTK_LIC_KID="k1"'
assert "TK_PROOF_KEYX" not in bi and "proof_h.unlink(missing_ok=True)" in bi and "secret_in(" in bi
rd = B.public_readme((ROOT / "README.md").read_text(encoding="utf-8"))
assert "`/license`" not in rd and "`/machine`" in rd and "/snapshot" in rd
sk = os.urandom(32)
(TMP / "s.bin").write_bytes(b"x" + sk.hex().upper().encode("utf-16-le") + b"y")
assert B.secret_in(TMP / "s.bin", sk) and not B.secret_in(TMP / "s.bin", os.urandom(32))
(TMP / "s.bin").write_bytes(b"x" + sk + b"y")
assert B.secret_in(TMP / "s.bin", sk)
# B5: gcc esuat cu antetul secretului: iesirea (care citeaza liniile antetului) se filtreaza
gcc_ = shutil.which("gcc")
if gcc_:
    import contextlib, io  # noqa: E401
    hd = TMP / "tk_proof.h"
    hd.write_text("#define TK_PK_SEED 0x1234ABCDu\nstatic const unsigned char tk_pk_data[32] = {201, 77, MASKEDKEY 13};\n",
                  encoding="ascii")
    (TMP / "pc.c").write_text(f'#include "{hd.as_posix()}"\nint main(void) {{ return undeclared_x; }}\n', encoding="ascii")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            B.run([gcc_, "-fsyntax-only", TMP / "pc.c"], hidden=[hd])
            raise AssertionError("gcc trebuia sa esueze")
        except SystemExit as e:
            assert "Comanda a esuat" in str(e), e
    o = buf.getvalue()
    assert "undeclared_x" in o, o                                   # diagnosticele din alte fisiere raman
    assert not any(s in o for s in ("MASKEDKEY", "201, 77", "1234ABCD", "tk_pk", "tk_proof.h")), o
    assert "ascunse" in o, o
print("build: sursele cu poarta sterse si la eroare, secretul mascat in comenzi, cautat in clar / hex / UTF-16; "
      "README fara /license; iesirea gcc fara antetul secretului")

# ---------------------------------------------------------------- TopoKitLoad.lsp (simulator)
acad = Acad(str(ROOT), str(TMP))
want = {"TKL:FILEVERSION", "TKL:FASDIRS", "TKL:MODULE", "TKL:LANGDIR", "TKL:SLASH"}
forms = [f for f in M.parse(M.tokenize((ROOT / "TopoKitLoad.lsp").read_text(encoding="utf-8")))
         if isinstance(f, list) and len(f) > 1 and f[0] == Sym("DEFUN") and f[1].upper() in want]
assert len(forms) == len(want), [f[1] for f in forms]
for f in forms:
    M.ev(f)
lang = ["RO"]
M.funcs[Sym("TKL:LANG")] = lambda: lang[0]


def fn(name, *a): return call(Sym(name.upper()), [x if x is None else str(x) if isinstance(x, pathlib.Path) else x for x in a])
def norm(p): return None if p is None else os.path.normcase(os.path.normpath(p.replace("\\", "/")))


pk = TMP / "pachet_fas"
for sub in ("", "en"):
    for fmt in B.FAS_FORMATS:
        (pk / sub / fmt).mkdir(parents=True)
        (pk / sub / fmt / "TopoKit.fas").write_bytes(b"x")
for lispsys, fmt in ((1, "fas5"), (0, "fas4"), (2, "fas4"), (None, "fas4")):
    acad.vars["LISPSYS"] = lispsys
    assert norm(fn("TKL:Module", pk, "TopoKit")) == norm(str(pk / fmt / "TopoKit.fas")), (lispsys, fn("TKL:Module", pk, "TopoKit"))
acad.vars["LISPSYS"] = 1
shutil.rmtree(pk / "fas5")
assert norm(fn("TKL:Module", pk, "TopoKit")) == norm(str(pk / "fas4" / "TopoKit.fas"))   # LISPSYS=1 citeste si FAS4
acad.vars["LISPSYS"] = 0
shutil.rmtree(pk / "fas4")
assert fn("TKL:Module", pk, "TopoKit") is None                     # FAS5 nu merge sub LISPSYS=0
(pk / "TopoKit.lsp").write_text(";;", encoding="ascii")
assert norm(fn("TKL:Module", pk, "TopoKit")) == norm(str(pk / "TopoKit.lsp"))  # versiunea de dezvoltare
assert fn("TKL:Module", None, "TopoKit") is None
assert fn("TKL:Module", pk, "TopoKitAnexe") is None
for v in (0, 1):
    acad.vars["LISPSYS"] = v
    assert norm(fn("TKL:Module", str(ROOT), "TopoKit")) == norm(str(ROOT / "TopoKit.lsp"))
# limba: en/ doar daca are modulul in formatul potrivit
acad.vars["LISPSYS"] = 0
lang[0] = "EN"
assert norm(fn("TKL:LangDir", str(pk))) == norm(str(pk / "en"))                 # en/fas4 exista
shutil.rmtree(pk / "en" / "fas4")
assert norm(fn("TKL:LangDir", str(pk))) == norm(str(pk))                         # doar en/fas5: sub LISPSYS=0 nu
acad.vars["LISPSYS"] = 1
assert norm(fn("TKL:LangDir", str(pk))) == norm(str(pk / "en"))
lang[0] = "RO"
assert norm(fn("TKL:LangDir", str(pk))) == norm(str(pk))
lt = (ROOT / "TopoKitLoad.lsp").read_text(encoding="utf-8")
assert lt.count('(TKL:Module (TKL:Slash d) "TopoKit")') == 1, "TKL:Dir cauta modulul (.fas sau .lsp)"
assert "'load (list (TKL:Module ldir \"TopoKit\"))" in lt, "TKL:Load incarca prin TKL:Module"
assert lt.count('(TKL:Module (strcat dir "\\\\en") "TopoKit")') == 1, "TKL:LangDir cauta modulul en (.fas sau .lsp)"
assert "TopoKit.lsp\")))" not in lt.split("(defun TKL:FileVersion")[0], "cale fixa TopoKit.lsp in TKL:Dir / TKL:LangDir"
print("TKL:Module: fas5 (LISPSYS=1, apoi fas4), fas4 (LISPSYS 0/2/nil), altfel .lsp; TKL:LangDir la fel")


def fv(d): return call(Sym("TKL:FILEVERSION"), [d if d is None else str(d)])


d = TMP / "pachet"
d.mkdir()
shutil.copy2(ROOT / "TopoKit.lsp", d / "TopoKit.lsp")
src_ver = re.search(r'\(setq \*TK:VERSION\* "([^"]+)"\)', srcs["TopoKit.lsp"]).group(1)
assert fv(d) == src_ver, (fv(d), src_ver)                  # fara VERSION: din TopoKit.lsp
(d / "VERSION").write_text("9.8.7\r\n", encoding="ascii")
assert fv(d) == "9.8.7", fv(d)                             # VERSION are prioritate
(d / "TopoKit.lsp").unlink()
assert fv(d) == "9.8.7"                                          # pachetul compilat: fara .lsp
(d / "VERSION").unlink()
assert fv(d) is None                                              # nimic de citit
assert fv(None) is None
print(f"TKL:FileVersion: VERSION are prioritate, altfel TopoKit.lsp ({src_ver})")

# ---------------------------------------------------------------- lansatorul si build-ul
c = (ROOT / "installer" / "launcher" / "topokit.c").read_text(encoding="utf-8")
m = re.search(r"static BOOL LoaderIn\([^)]*\)\s*\{(.*?)\n\}", c, re.S)
assert m, "LoaderIn in topokit.c"
assert "TopoKitLoad.lsp" in m.group(1), "LoaderIn gaseste TopoKitLoad.lsp (incarcatorul nu se compileaza)"
assert len(re.findall(r"LoaderIn\(", c)) >= 4, "LoaderIn folosit in FindContents si LispPath"
assert "TopoKitLoad.fas" not in bi, "PackageContents.xml ramane pe TopoKitLoad.lsp"
assert "compile_modules(contents" in bi and "f.unlink()" in bi, "sursele modulelor se sterg dupa compilare"
assert '(contents / "VERSION").write_text' in bi
assert 'choices=["auto", "yes", "no"]' in bi
pc = (ROOT / "installer" / "bundle" / "PackageContents.xml").read_text(encoding="utf-8")
assert 'ModuleName="./Contents/TopoKitLoad.lsp"' in pc
print("Lansatorul si PackageContents.xml folosesc TopoKitLoad.lsp; build-ul scrie VERSION")

# ---------------------------------------------------------------- tools/compile_lisp.ps1
ps = ROOT / "tools" / "compile_lisp.ps1"
t = ps.read_text(encoding="utf-8")
assert all(ord(ch) < 128 for ch in t), "compile_lisp.ps1 ASCII"
assert "accoreconsole.exe" in t and "'/p', $CompileProfile" in t and "'/i'" in t and "'/s'" in t
assert "-WindowStyle Hidden" in t and "WaitForExit($TimeoutSec * 1000)" in t
assert "fas5 = @{ Lispsys = '1'; Header = 'FAS5-FILE' }" in t and "fas4 = @{ Lispsys = '2'; Header = 'FAS4-FILE' }" in t
assert "Copy-Item -LiteralPath \"$profKey\\$BaseProfile\" -Destination \"$profKey\\$CompileProfile\" -Recurse" in t
assert re.search(r"if \(-not \(Test-Path \"\$profKey\\\$CompileProfile\"\)\)", t), "profilul se copiaza doar daca lipseste"
fin = t[t.rindex("finally {"):]
assert "Set-ItemProperty $profKey -Name '(default)' -Value $origDefault" in fin, "profilul implicit refacut in finally"
i_save, i_run = t.find("$origDefault = Get-Default"), t.find("Run-Format $fmt")
assert 0 <= i_save < i_run, "profilul implicit salvat inainte de accoreconsole"
stops = re.findall(r"Stop-Process[^\n]*", t)
assert stops and all("-Id $p.Id" in s for s in stops), stops
assert not re.search(r"Get-Process|AutoCAD\.Application|acad\.exe\b(?!\s+deschise)", t.replace("acad.exe deschise", "")), \
    "nu lucreaza cu procesele acad.exe"
assert not re.search(r"SECURELOAD|TRUSTEDPATHS", t), "nu schimba securitatea AutoCAD"
assert "Remove-Item $tmp -Recurse" in fin
print("compile_lisp.ps1: accoreconsole /p, un proces pe format, antet FAS5/FAS4, profilul implicit refacut")

shutil.rmtree(TMP, ignore_errors=True)
print("\nToate testele compilarii au trecut.")
