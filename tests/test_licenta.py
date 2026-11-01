#!/usr/bin/env python3
"""Teste offline pentru licenta TopoKit (Windows: criptografia CNG si gcc / windres).

    python tests/test_licenta.py

Verifica:
  - tools/licenta.py: cheie, semnare, verificare, codul calculatorului, licente stricate;
  - TopoKit.exe compilat cu o cheie de test: /machine (acelasi cod ca in Python), /license pe
    licente bune / pentru alt calculator / expirate / cu ceasul dat inapoi / cu alt kid / stricate;
    fara cheie (build de dezvoltare) /license iese cu 0;
  - activare, reinnoire, acces oprit, server care nu raspunde, dezactivare - contra unui server
    simulat aici (serverul adevarat, server/worker.js, are testul complet tests/server_harness.py);
  - server/worker.js: fiecare interogare SQL e valida pe schema (SQLite = D1);
  - TopoKitLoad.lsp din pachetul cu licentiere: fara licenta modulele nu se incarca si comenzile
    trimit la activare; cu licenta se incarca, iar verificarea ruleaza o data pe sesiune;
  - tools/build_installer.py: lista comenzilor, installer/licensing.json;
  - DWG to KMZ si Plan Inclinare: aceeasi functie licenta_ok, care foloseste TopoKit.exe /license.
"""
import ast, json, os, pathlib, re, shutil, socket, sqlite3, subprocess, sys, tempfile, threading, time, types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if os.name != "nt":
    print("Testul licentei are nevoie de Windows (CNG, bcrypt.dll) - omis.")
    sys.exit(0)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import licenta as L          # noqa: E402
import build_installer as B  # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="tklic_"))
NOW = int(time.time())

# ---------------------------------------------------------------- tools/licenta.py
key = L.gen_key("t1")
pub = L.public_hex(key)
mid = L.machine_id()
assert re.fullmatch(r"[0-9A-F]{24}", mid) and L.machine_group(mid).count("-") == 3
assert L.machine_id("ABC-def", 0x1A2B) == L.machine_id("abc-DEF", 0x1A2B) != L.machine_id("abc-def", 0x1A2C)


def lic(**kw):
    p = {"v": 1, "kid": "t1", "typ": "internal", "lid": "d_1", "uid": 1, "name": 'Ion Popescu ăîșț "x" \\ y',
         "machine": mid, "features": ["all"], "iat": NOW, "exp": NOW + 14 * 86400}
    p.update(kw)
    return L.make_license(key, p)


good = lic()
cases = {"ok": (good, "ok", 0), "alt_pc": (lic(machine="0" * 24), "calculator", 12),
         "expirata": (lic(exp=NOW - 5), "expirata", 13), "ceas": (lic(iat=NOW + 3 * 86400), "ceas", 14),
         "kid": (lic(kid="zz"), "kid", 11), "semnatura": (good[:-6] + "AAAAAA", "semnatura", 11),
         "format": ("TK1.nu-e-licenta", "format", 11), "versiune": (lic(v=2), "format", 11)}
for name, (text, want, _) in cases.items():
    assert L.license_status(text, pub, "t1", mid)[0] == want, (name, L.license_status(text, pub, "t1", mid))
assert L.license_status(good, L.public_hex(L.gen_key("t1")), "t1", mid)[0] == "semnatura"   # alta cheie
print("licenta.py: cheie P-256 (CNG), semnare / verificare, codul calculatorului, licente stricate")

# ---------------------------------------------------------------- TopoKit.exe compilat cu cheia de test
gcc, windres = shutil.which("gcc"), shutil.which("windres")
if not gcc or not windres:
    print("Lipseste gcc / windres - testele lansatorului sunt omise.")
    sys.exit(0)
LD = ROOT / "installer" / "launcher"
res = TMP / "res.o"
subprocess.run([windres, "-DTK_VER_COMMA=9,9,9,0", '-DTK_VER_STR=\\"9.9.9\\"', "topokit.rc", "-O", "coff", "-o", str(res)],
               cwd=LD, check=True)
LIBS = ["-lgdiplus", "-lshlwapi", "-lole32", "-loleaut32", "-luuid", "-lshell32", "-lgdi32", "-luser32",
        "-lbcrypt", "-lwinhttp", "-lcrypt32", "-lcomdlg32"]


def compile_exe(out, *defs):
    r = subprocess.run([gcc, "-municode", "-mwindows", "-O1", "-Wall", "-Wextra", "-static", '-DTK_VERSION="9.9.9"', *defs,
                        "-o", str(out), "topokit.c", "ui.c", "license.c", str(res), *LIBS],
                       cwd=LD, capture_output=True, text=True)
    warn = [l for l in (r.stdout + r.stderr).splitlines() if "warning" in l and "manifest" not in l]
    assert r.returncode == 0 and not warn, r.stdout + r.stderr


EXE, DEV = TMP / "lic.exe", TMP / "dev.exe"
compile_exe(EXE, f'-DTK_LIC_PUB="{pub}"', '-DTK_LIC_KID="t1"', '-DTK_LIC_URL="https://licente.invalid"')
compile_exe(DEV)


def run(exe, *args, licdir=None, server=None):
    env = {k: v for k, v in os.environ.items() if k not in ("TOPOKIT_LICDIR", "TOPOKIT_LICSERVER")}
    if licdir:
        env["TOPOKIT_LICDIR"] = str(licdir)
    if server:
        env["TOPOKIT_LICSERVER"] = server
    r = subprocess.run([str(exe), *args], capture_output=True, env=env, timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def folder(name):
    d = TMP / name
    d.mkdir(exist_ok=True)
    return d


assert run(EXE, "/machine") == (0, L.machine_group(mid)), run(EXE, "/machine")
for name, (text, _, code) in cases.items():
    f = TMP / f"{name}.lic"
    f.write_text(text + "\r\n", encoding="utf-8")
    got = run(EXE, "/license", str(f), licdir=folder("x"))
    assert got[0] == code, (name, got)
assert "Ion Popescu ăîșț \"x\" \\ y" in run(EXE, "/license", str(TMP / "ok.lic"))[1]
assert run(EXE, "/license", licdir=folder("gol"))[0] == 10
assert run(DEV, "/license", licdir=folder("gol"))[0] == 0              # build fara licentiere
print("TopoKit.exe /license: aceleasi rezultate ca licenta.py (C / CNG); build de dezvoltare fara verificare")

# ---------------------------------------------------------------- activare / reinnoire contra unui server simulat
SRV = {"mode": "ok", "calls": []}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, status, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        SRV["calls"].append((self.path, b))
        if SRV["mode"] == "500":
            return self.reply(500, {"error": "server"})
        if self.path == "/api/activate":
            if b.get("code") != "TKITABCDE12345FGHJK":
                return self.reply(403, {"error": "code_used"})
            return self.reply(200, {"license": lic(machine=b["machine"], name="Maria Ionescu"), "device": "d_1",
                                    "secret": "secret-de-test"})
        if self.path == "/api/refresh":
            if b.get("device") != "d_1" or b.get("secret") != "secret-de-test":
                return self.reply(403, {"error": "unknown_device"})
            if SRV["mode"] == "revoked":
                return self.reply(403, {"error": "revoked"})
            return self.reply(200, {"license": lic(machine=b["machine"], name="Maria Ionescu", iat=int(time.time()) + 1)})
        if self.path == "/api/deactivate":
            return self.reply(200, {"ok": True})
        self.reply(404, {"error": "not_found"})


sock = socket.socket()
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
sock.close()
srv = ThreadingHTTPServer(("127.0.0.1", port), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{port}"
a = folder("a")
code, out = run(EXE, "/activate", "tkit-abcde-12345-fghjk", licdir=a, server=URL)
assert code == 0 and (a / "license.lic").exists() and (a / "state.dat").exists(), (code, out)
sent = SRV["calls"][-1][1]
assert sent["code"] == "TKITABCDE12345FGHJK" and sent["machine"] == mid and sent["version"] == "9.9.9" and sent["pc"], sent
assert b"secret-de-test" not in (a / "state.dat").read_bytes()               # protejat cu DPAPI
assert run(EXE, "/license", licdir=a)[1].startswith("0 Maria Ionescu")
code, out = run(EXE, "/activate", "TKIT-ZZZZZ-ZZZZZ-ZZZZZ", licdir=folder("b"), server=URL)
assert code == 2 and "folosit" in out and not (TMP / "b" / "license.lic").exists(), (code, out)
before = (a / "license.lic").read_text()
assert run(EXE, "/refresh", licdir=a, server=URL)[0] == 0 and (a / "license.lic").read_text() != before
assert SRV["calls"][-1][1]["secret"] == "secret-de-test"                     # secretul citit inapoi (DPAPI)
SRV["mode"] = "500"
kept = (a / "license.lic").read_text()
assert run(EXE, "/refresh", licdir=a, server=URL)[0] == 1 and (a / "license.lic").read_text() == kept
assert run(EXE, "/refresh", licdir=a)[0] == 1 and (a / "license.lic").exists()   # https://licente.invalid: fara retea
SRV["mode"] = "revoked"
assert run(EXE, "/refresh", licdir=a, server=URL)[0] == 2
assert not (a / "license.lic").exists() and not (a / "state.dat").exists()
assert run(EXE, "/license", licdir=a, server=URL)[0] == 10
SRV["mode"] = "ok"
assert run(EXE, "/activate", "TKITABCDE12345FGHJK", licdir=a, server=URL)[0] == 0
# licenta care expira: /license o reinnoieste singur inainte de raspuns
(a / "license.lic").write_text(lic(exp=NOW - 1) + "\r\n")
code, out = run(EXE, "/license", licdir=a, server=URL)
assert code == 0 and SRV["calls"][-1][0] == "/api/refresh", (code, out)
assert run(EXE, "/deactivate", licdir=a, server=URL)[0] == 0 and not (a / "license.lic").exists()
assert SRV["calls"][-1][0] == "/api/deactivate"
srv.shutdown()
print("activare, cod refolosit, reinnoire, server cazut / fara retea (licenta ramane), acces oprit (licenta stearsa),")
print("  reinnoire automata la /license, dezactivare; secretul dispozitivului e protejat cu DPAPI")

# ---------------------------------------------------------------- server/worker.js: SQL pe schema
src = (ROOT / "server" / "worker.js").read_text(encoding="utf-8")
schema = re.findall(r"`(.*?)`", re.search(r"const SCHEMA = \[(.*?)\];", src, re.S).group(1), re.S)
queries = dict(re.findall(r"(\w+):\s*`(.*?)`", re.search(r"const Q = \{(.*?)\n\};", src, re.S).group(1), re.S))
db = sqlite3.connect(":memory:")
for s in schema:
    db.execute(s)
for s in schema:                                   # IF NOT EXISTS: a doua rulare nu strica nimic
    db.execute(s)
for name, sql in queries.items():
    db.execute("EXPLAIN " + sql, [None] * sql.count("?"))
used = set(re.findall(r"\bQ\.(\w+)", src))
assert used <= set(queries) and set(queries) <= used, (used ^ set(queries))
admin = re.search(r"const ADMIN_HTML = `(.*)`;\s*$", src, re.S).group(1)
assert "`" not in admin and "${" not in admin, "pagina /admin nu poate contine ` sau ${"
assert "innerHTML" not in admin, "pagina /admin construieste DOM-ul doar cu textContent"
print(f"worker.js: {len(schema)} instructiuni de schema si {len(queries)} interogari valide in SQLite")

# ---------------------------------------------------------------- TopoKitLoad.lsp cu licentiere (simulator)
from acad_sim import Acad, Sym, call, env   # noqa: E402
import autolisp_mini as M                   # noqa: E402

cont = TMP / "Contents"
inst = TMP / "inst"
cont.mkdir()
inst.mkdir()
for f in B.LSP + B.DCL:
    shutil.copy2(ROOT / f, cont / f)
cmds = B.module_commands()
(cont / "TopoKitLoad.lsp").write_text(B.licensed_loader((ROOT / "TopoKitLoad.lsp").read_text(encoding="utf-8"), cmds),
                                      encoding="utf-8")
(cont / "install.txt").write_text(str(inst) + "\r\n", encoding="ascii")
(inst / "TopoKit.exe").write_bytes(b"MZ")
OUT = tempfile.mkdtemp(prefix="tklic_acad_")
acad = Acad(str(ROOT), OUT)
reg = {("HKEY_CURRENT_USER\\Software\\TopoKit", "ContentsDir"): str(cont)}
prefs = {"SupportPath": "C:\\Lucru"}
acad.vars["TRUSTEDPATHS"] = ""
M.funcs[Sym("VL-REGISTRY-READ")] = lambda k, v=None: reg.get((k, v))
M.funcs[Sym("VL-REGISTRY-WRITE")] = lambda k, v, d: d
M.funcs.setdefault(Sym("VL-PRINC-TO-STRING"), lambda x: str(x))
M.funcs[Sym("VLA-GET-PREFERENCES")] = lambda a: "prefs"
M.funcs[Sym("VLA-GET-FILES")] = lambda p: "files"
M.funcs[Sym("VLA-GET-SUPPORTPATH")] = lambda f: prefs["SupportPath"]
M.funcs[Sym("VLA-PUT-SUPPORTPATH")] = lambda f, v: prefs.__setitem__("SupportPath", v)
loads, shell, started = [], {"rc": 10, "runs": []}, []
orig_load = M.funcs[Sym("LOAD")]
M.funcs[Sym("LOAD")] = lambda f, *a: (loads.append(os.path.basename(f.replace("\\", "/"))), orig_load(f, *a))[1]
M.funcs[Sym("VLAX-CREATE-OBJECT")] = lambda name: "WScript.Shell" if name == "WScript.Shell" else None
M.funcs[Sym("VLAX-INVOKE")] = lambda o, m, *a: (shell["runs"].append((str(m), a)), shell["rc"])[1]
M.funcs[Sym("VLAX-RELEASE-OBJECT")] = lambda o: None
M.funcs[Sym("STARTAPP")] = lambda *a: started.append(a) or 33


def fn(name, *a): return call(Sym(name.upper()), list(a))


def defined(sym): return env.get(Sym(sym.upper())) is not None or Sym(sym.upper()) in M.funcs


M.load(str(cont / "TopoKitLoad.lsp"))
acad.after_load()
assert loads == [], loads                                             # fara licenta: niciun modul
assert len(shell["runs"]) == 1 and shell["runs"][0][0].upper() == "RUN", shell["runs"]
assert shell["runs"][0][1][0] == f'"{inst}\\TopoKit.exe" /license', shell["runs"][0]
assert all(defined("C:" + c) for c in cmds) and not defined("TK:START")
assert any("neactivat pe acest calculator" in o for o in acad.out), acad.out[-3:]
fn("C:TOPOKIT")
assert started and started[-1][0] == f"{inst}\\TopoKit.exe" and any("nu este activat" in o for o in acad.out)
shell["rc"] = 0                                                         # colegul a activat TopoKit
assert fn("TKL:Load", Sym("T")) and loads[0] == "TopoKit.lsp" and len(loads) == 6, loads
assert defined("TK:START") and len(shell["runs"]) == 2
loads.clear()
M.load(str(cont / "TopoKitLoad.lsp"))                                   # alt desen: fara alta verificare
assert loads == [] and len(shell["runs"]) == 2, (loads, shell["runs"])
print(f"TopoKitLoad.lsp cu licentiere: fara licenta {len(cmds)} comenzi trimit la activare; cu licenta "
      "modulele se incarca, verificare o data pe sesiune")

# fara licentiere (sursa / build de dezvoltare): nu ruleaza TopoKit.exe deloc
src_loader = (ROOT / "TopoKitLoad.lsp").read_text(encoding="utf-8")
assert "(setq *TKL:LICENTA* nil)" in src_loader and "(setq *TKL:CMDS* nil)" in src_loader

# ---------------------------------------------------------------- build_installer: comenzi si licensing.json
lsp_cmds = set()
for f in B.LSP[1:]:
    lsp_cmds |= {m.upper() for m in re.findall(r"\(defun c:([A-Za-z0-9_-]+)", (ROOT / f).read_text(encoding="utf-8"), re.I)}
assert set(cmds) == lsp_cmds and "TKLEGENDA" in cmds and "TOPOKITRELOAD" not in cmds and len(cmds) >= 50
old_inst = B.INST
try:
    B.INST = TMP / "cfg"
    B.INST.mkdir()
    assert B.licensing_config() is None
    (B.INST / "licensing.json").write_text(json.dumps({"kid": "k1", "public_key": "zz"}))
    try:
        B.licensing_config()
        raise AssertionError("cheie publica gresita acceptata")
    except SystemExit:
        pass
    (B.INST / "licensing.json").write_text(json.dumps({"kid": "k1", "public_key": pub, "server": "https://x.workers.dev"}))
    assert B.licensing_config()["public_key"] == pub
finally:
    B.INST = old_inst
print("build_installer: lista comenzilor din module, installer/licensing.json validat")

# ---------------------------------------------------------------- programele Python: licenta_ok
funcs = []
for f in ("dwg2kmz/dwg2kmz.py", "inclinare/plan_inclinare.py"):
    tree = ast.parse((ROOT / f).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "licenta_ok")
    funcs.append(ast.get_source_segment((ROOT / f).read_text(encoding="utf-8"), node))
assert funcs[0] == funcs[1], "licenta_ok trebuie sa fie aceeasi in ambele programe"
app = TMP / "app"
(app / "modules").mkdir(parents=True)
shutil.copy2(EXE, app / "TopoKit.exe")
okdir = folder("okdir")
(okdir / "license.lic").write_text(good + "\r\n")
import ctypes  # noqa: E402
msgs, opened = [], []
old_mb, old_sf, old_env = ctypes.windll.user32.MessageBoxW, os.startfile, os.environ.get("TOPOKIT_LICDIR")
ctypes.windll.user32.MessageBoxW = lambda h, t, c, f: msgs.append(t) or 1
os.startfile = lambda p: opened.append(p)
try:
    def check(frozen, licdir, nuitka=False):
        # frozen = exe PyInstaller (sys.frozen); nuitka = exe Nuitka (fara sys.frozen, cu __compiled__ global)
        ns = {"os": os, "subprocess": subprocess,
              "sys": types.SimpleNamespace(frozen=frozen, executable=str(app / "modules" / "DWGtoKMZ.exe"))}
        if not frozen:
            del ns["sys"].frozen
        if nuitka:
            ns["__compiled__"] = types.SimpleNamespace(standalone=True)
        exec(funcs[0], ns)
        os.environ["TOPOKIT_LICDIR"] = str(licdir)
        return ns["licenta_ok"]()
    assert check(False, folder("gol")) is True and not msgs                   # din sursa: fara verificare
    assert check(True, okdir) is True and not msgs
    assert check(True, folder("gol")) is False and len(msgs) == 1 and opened == [str(app / "TopoKit.exe")]
    assert check(False, okdir, nuitka=True) is True and len(msgs) == 1        # Nuitka: se verifica si aici
    assert check(False, folder("gol"), nuitka=True) is False and len(msgs) == 2 and len(opened) == 2
finally:
    ctypes.windll.user32.MessageBoxW, os.startfile = old_mb, old_sf
    if old_env is None:
        os.environ.pop("TOPOKIT_LICDIR", None)
    else:
        os.environ["TOPOKIT_LICDIR"] = old_env
print("DWG to KMZ / Plan Inclinare: pornesc doar cu licenta (TopoKit.exe /license), altfel mesaj + fereastra TopoKit")

shutil.rmtree(TMP, ignore_errors=True)
shutil.rmtree(OUT, ignore_errors=True)
print("\nToate testele licentei au trecut.")
