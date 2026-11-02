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
  - DWG to KMZ si Plan Inclinare (tklic.py): aceleasi rezultate ca TopoKit.exe pe aceleasi licente.
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
import lic_gate as GATE      # noqa: E402
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


EXE, DEV, REL = TMP / "lic.exe", TMP / "dev.exe", TMP / "rel.exe"
LICDEFS = (f'-DTK_LIC_PUB="{pub}"', '-DTK_LIC_KID="t1"', '-DTK_LIC_URL="https://licente.invalid"')
# secretul build-ului pentru provocare-raspuns (/proof): antetul generat ca la build (lic_gate.proof_header)
PROOF_KEY = bytes((i * 11 + 5) & 0xFF for i in range(32))
PROOF_H = TMP / "tk_proof.h"
PROOF_H.write_text(GATE.proof_header(PROOF_KEY), encoding="ascii")
PROOFDEFS = (f'-DTK_PROOF_FILE="{PROOF_H.as_posix()}"',)
compile_exe(EXE, *LICDEFS, *PROOFDEFS, "-DTK_LIC_TESTENV")   # build de test: TOPOKIT_LICDIR / LICSERVER / LICREG
compile_exe(DEV)
compile_exe(REL, *LICDEFS, *PROOFDEFS)               # ca build-ul de livrare: variabilele de mediu ignorate
# REL nu se ruleaza cu /license (ar citi licenta adevarata a utilizatorului): doar se verifica
# ca variabilele de test nu exista in program
for exe, present in ((EXE, True), (REL, False)):
    data = exe.read_bytes()
    for var in ("TOPOKIT_LICDIR", "TOPOKIT_LICSERVER", "TOPOKIT_LICREG"):
        assert (var.encode("utf-16-le") in data) == present, (exe.name, var)
    # secretul /proof nu apare in program: nici octetii, nici hex-ul (B7 / C2)
    assert not B.secret_in(exe, PROOF_KEY), exe.name
    assert not any(PROOF_KEY[i:i + 8] in data for i in range(0, 25, 4)), exe.name
try:                                                  # cheie publica de alta lungime: eroare la compilare
    compile_exe(TMP / "bad.exe", '-DTK_LIC_PUB="ABCD"')
    raise AssertionError("TK_LIC_PUB gresit acceptat la compilare")
except AssertionError as e:
    assert "TK_LIC_PUB" in str(e) and "acceptat" not in str(e), e


def run(exe, *args, licdir=None, server=None, reg=None):
    env = {k: v for k, v in os.environ.items() if k not in ("TOPOKIT_LICDIR", "TOPOKIT_LICSERVER", "TOPOKIT_LICREG")}
    if licdir:
        env["TOPOKIT_LICDIR"] = str(licdir)
    if server:
        env["TOPOKIT_LICSERVER"] = server
    if reg:
        env["TOPOKIT_LICREG"] = reg
    r = subprocess.run([str(exe), *args], capture_output=True, env=env, timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


# ---------------------------------------------------------------- DPAPI (ora vazuta: seen.dat / registru)
import ctypes                     # noqa: E402
from ctypes import wintypes       # noqa: E402


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(b):
    buf = ctypes.create_string_buffer(b, len(b))
    return _Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


SEEN_ENT = b"TopoKit ora"


def dpapi(data, protect=True):
    i, k1 = _blob(data)
    e, k2 = _blob(SEEN_ENT)
    o = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    assert fn(ctypes.byref(i), None, ctypes.byref(e), None, None, 1, ctypes.byref(o))
    r = ctypes.string_at(o.pbData, o.cbData)
    ctypes.windll.kernel32.LocalFree(o.pbData)
    return r


def seen_blob(t):
    return dpapi(b"TKS1 %d" % t)


def seen_read(d):
    f = pathlib.Path(d) / "seen.dat"
    return int(dpapi(f.read_bytes(), False)[5:]) if f.exists() else None


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
assert "Ion Popescu ăîșț \"x\" \\ y" in run(EXE, "/license", str(TMP / "ok.lic"), licdir=folder("x"))[1]
assert not (TMP / "x" / "seen.dat").exists()                          # fisier dat: ora vazuta nu se scrie
assert run(EXE, "/license", licdir=folder("gol"))[0] == 10
assert run(DEV, "/license", licdir=folder("gol"))[0] == 0              # build fara licentiere
print("TopoKit.exe /license: aceleasi rezultate ca licenta.py (C / CNG); build de dezvoltare fara verificare")

# licente ciudate: base64 cu gunoi dupa "=", fara iat / exp, nume foarte lung, \u0000 in nume
no_iat = L.make_license(key, {k: v for k, v in json.loads(L.b64u_dec(good.split(".")[1])).items() if k != "iat"})
odd = {"gunoi_dupa_egal": (good + "=x", 11), "egal_final": (good + "==", 0), "fara_iat": (no_iat, 11),
       "nume_lung": (lic(name="ș" * 700), 0), "nul_in_nume": (lic(name="a\u0000b"), 0),
       "machine_lung": (lic(machine=mid + "00"), 12)}
for name, (text, code) in odd.items():
    f = TMP / f"{name}.lic"
    f.write_text(text + "\r\n", encoding="utf-8")
    got = run(EXE, "/license", str(f), licdir=folder("x"))
    assert got[0] == code, (name, got)
print("licente ciudate: base64 strict, iat obligatoriu, nume lung / cu \\u0000, cod de calculator lung")

# ---------------------------------------------------------------- /license /proof <nonce> <fisier> (modulele AutoLISP)
def proof(exe, nonce, licdir, **kw):
    o = TMP / "proof.txt"
    if o.exists():
        o.unlink()
    code = run(exe, "/license", "/proof", nonce, str(o), licdir=licdir, **kw)[0]
    return code, (o.read_text().strip() if o.exists() else None)

pd = folder("proof")
(pd / "license.lic").write_text(good + "\r\n")
NONCE = "tkABCdef0123456789"
code, line = proof(EXE, NONCE, pd)                          # licenta buna
assert code == 0 and line, (code, line)
t = line.split(" ")
assert len(t) == 5 and t[0] == "0" and t[2] == NONCE and t[4] == mid, t   # al 5-lea: codul calculatorului
assert int(t[1]) == NOW + 14 * 86400                        # exp = expirarea licentei
assert t[3] == GATE.proof_mac(PROOF_KEY, NONCE, 0, t[1], mid)    # HMAC-SHA256 pe secretul build-ului
assert t[3] != GATE.proof_mac(PROOF_KEY, NONCE, 0, "0", mid)     # legat de exp (nu se poate schimba)
assert t[3] != GATE.proof_mac(PROOF_KEY, NONCE, 0, t[1], "0" * 24)   # legat de calculator (releu)
code, line = proof(EXE, NONCE, folder("proofgol"))          # fara licenta: cod 10, exp 0, tot semnat
t = line.split(" ")
assert code == 10 and t[0] == "10" and t[1] == "0" and t[2] == NONCE and t[4] == mid
assert t[3] == GATE.proof_mac(PROOF_KEY, NONCE, 10, 0, mid)
# nonce invalid (prea scurt / caracter nepermis / prea lung) -> niciun fisier, cod de eroare
for bad in ("short", "tk 123456789012345", "tkABC!def01234567", "a" * 65):
    code, line = proof(EXE, bad, pd)
    assert line is None, (bad, line)
assert proof(EXE, "a" * 64, pd)[1] is not None             # 64 e permis
assert proof(EXE, "a" * 16, pd)[1] is not None             # 16 e permis
# build fara secret (dezvoltare): /proof nu scrie nimic (nu are ce semna)
assert proof(DEV, NONCE, folder("proofdev"))[1] is None
print("/proof: mac = HMAC-SHA256(secret, \"TKP2|nonce|cod|exp|calculator\"), legat de exp si de calculator; "
      "nonce verificat 16..64 [0-9A-Za-z]")

# ceasul dat inapoi: ora cea mai mare vazuta (seen.dat + copia din registru, DPAPI)
s = folder("seen")
(s / "license.lic").write_text(good + "\r\n")
assert run(EXE, "/license", licdir=s)[0] == 0 and abs(seen_read(s) - time.time()) < 120   # scrisa la prima citire
(s / "seen.dat").write_bytes(seen_blob(int(time.time()) + 3 * 3600))
assert run(EXE, "/license", licdir=s)[0] == 0                          # cateva ore: toleranta (fus orar, NTP)
(s / "seen.dat").write_bytes(seen_blob(int(time.time()) + 3 * 86400))
code, out = run(EXE, "/license", licdir=s)
assert code == 14 and seen_read(s) > time.time() + 2 * 86400, (code, out)   # ceasul cu 3 zile in urma
(s / "seen.dat").write_bytes(b"stricat")
assert run(EXE, "/license", licdir=s)[0] == 0                          # fisier stricat: ignorat, rescris
assert abs(seen_read(s) - time.time()) < 120
REG = f"Software\\TopoKitTest_{os.getpid()}"                           # cheie de test, stearsa la sfarsit
import winreg  # noqa: E402
try:
    (s / "seen.dat").unlink()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG) as k:
        winreg.SetValueEx(k, "LicSeen", 0, winreg.REG_BINARY, seen_blob(int(time.time()) + 3 * 86400))
    assert run(EXE, "/license", licdir=s, reg=REG)[0] == 14            # seen.dat sters: ramane copia din registru
    assert run(EXE, "/license", licdir=s)[0] == 0                      # (fara TOPOKIT_LICREG registrul nu e folosit)
    (s / "seen.dat").unlink()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG) as k:
        winreg.DeleteValue(k, "LicSeen")
    assert run(EXE, "/license", licdir=s, reg=REG)[0] == 0
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG) as k:           # scrisa si in registru
        assert abs(int(dpapi(winreg.QueryValueEx(k, "LicSeen")[0], False)[5:]) - time.time()) < 120
finally:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG)
    except OSError:
        pass
# alt proces tine mutex-ul licentei (Local\TopoKitLicense): ora vazuta avanseaza totusi (inainte: inghetata)
(s / "seen.dat").write_bytes(seen_blob(int(time.time()) - 2 * 3600))
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = wintypes.HANDLE
_mx = _k32.CreateMutexW(None, True, "Local\\TopoKitLicense")
try:
    assert _mx and _k32.WaitForSingleObject(wintypes.HANDLE(_mx), 0) in (0, 0x80)
    t0 = time.time()
    assert run(EXE, "/license", licdir=s)[0] == 0
    assert abs(seen_read(s) - time.time()) < 120, "ora vazuta inghetata de mutex-ul tinut de alt proces"
    assert time.time() - t0 < 30
finally:
    _k32.ReleaseMutex(wintypes.HANDLE(_mx)); _k32.ReleaseMutex(wintypes.HANDLE(_mx))
    _k32.CloseHandle(wintypes.HANDLE(_mx))
print("ceas dat inapoi: ora cea mai mare vazuta (seen.dat si registru, DPAPI), toleranta de o zi; "
      "avanseaza si cand alt proces tine mutex-ul")

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
        if SRV["mode"] == "slow":                       # server care tace (retea proasta / proxy blocat)
            time.sleep(25)
            return self.reply(500, {"error": "slow"})
        if SRV["mode"] == "500":
            return self.reply(500, {"error": "server"})
        if self.path == "/api/activate":
            if b.get("code") != "TKITABCDE12345FGHJK":
                return self.reply(403, {"error": "code_used"})
            if SRV["mode"] == "badsecret":                  # secret cu caractere nepermise
                return self.reply(200, {"license": lic(machine=b["machine"]), "device": "d_1", "secret": 'a"b\nc'})
            iat = int(time.time()) + 3 * 86400 if SRV["mode"] == "ceas" else NOW   # ceasul calculatorului in urma
            return self.reply(200, {"license": lic(machine=b["machine"], name="Maria Ionescu", iat=iat), "device": "d_1",
                                    "secret": "secret-de-test"})
        if self.path == "/api/refresh":
            if b.get("device") != "d_1" or b.get("secret") != "secret-de-test":
                return self.reply(403, {"error": "unknown_device"})
            if SRV["mode"] == "revoked":
                return self.reply(403, {"error": "revoked"})
            new = lic(machine=b["machine"], name="Maria Ionescu", iat=int(time.time()) + 1)
            if SRV["mode"] == "altpc":                      # server fals: licenta (semnata) pentru alt calculator
                new = lic(machine="0" * 24)
            elif SRV["mode"] == "garbage":                  # portal captiv / proxy
                data = b"<html>login</html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            elif SRV["mode"] == "pad":                      # licenta buna cu spatii pana la 4095 octeti
                n = 4095 - len(new)
                new = " " * (n // 2) + new + " " * (n - n // 2)     # (vechiul cod scria 2 octeti peste buffer)
            SRV["last"] = new.strip()
            return self.reply(200, {"license": new})
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
# raspunsuri ciudate / false la reinnoire: licenta veche ramane, nimic nu se strica
for mode in ("altpc", "garbage"):
    SRV["mode"] = mode
    kept = (a / "license.lic").read_text()
    assert run(EXE, "/refresh", licdir=a, server=URL)[0] == 1 and (a / "license.lic").read_text() == kept, mode
SRV["mode"] = "pad"                                     # 4095 octeti cu spatii: se salveaza doar licenta
assert run(EXE, "/refresh", licdir=a, server=URL)[0] == 0
assert (a / "license.lic").read_text() == SRV["last"] + "\n", len((a / "license.lic").read_text())
# ora vazuta ramasa din viitor (ceasul fusese dus inainte): /license reinnoieste si o corecteaza
SRV["mode"] = "ok"
(a / "seen.dat").write_bytes(seen_blob(int(time.time()) + 5 * 86400))
code, out = run(EXE, "/license", licdir=a, server=URL)
assert code == 0 and SRV["calls"][-1][0] == "/api/refresh" and seen_read(a) < time.time() + 3600, (code, out)
(a / "seen.dat").write_bytes(seen_blob(int(time.time()) + 5 * 86400))
assert run(EXE, "/license", licdir=a)[0] == 14                         # fara server: ramane LIC_CLOCK
assert run(EXE, "/deactivate", licdir=a, server=URL)[0] == 0 and not (a / "license.lic").exists()
assert SRV["calls"][-1][0] == "/api/deactivate"
assert (a / "seen.dat").exists()                                        # ora vazuta ramane si dupa dezactivare
# activare: secret cu caractere nepermise -> nimic salvat
SRV["mode"] = "badsecret"
c = folder("c")
code, out = run(EXE, "/activate", "TKITABCDE12345FGHJK", licdir=c, server=URL)
assert code == 2 and not (c / "license.lic").exists() and not (c / "state.dat").exists(), (code, out)
# activare cu ceasul calculatorului in urma: codul e consumat, dispozitivul se pastreaza; dupa
# corectare (aici: serverul da o licenta cu data buna) /license o ia singur, fara cod nou
SRV["mode"] = "ceas"
code, out = run(EXE, "/activate", "TKITABCDE12345FGHJK", licdir=c, server=URL)
assert code == 2 and "data calculatorului" in out.lower(), (code, out)
assert (c / "state.dat").exists() and not (c / "license.lic").exists()
SRV["mode"] = "ok"
code, out = run(EXE, "/license", licdir=c, server=URL)
assert code == 0 and (c / "license.lic").exists(), (code, out)
# B8: fara internet, aproape de expirare - dupa o reinnoire esuata, /license si /proof nu mai incearca
# reteaua o ora (refresh.dat); /refresh explicit incearca oricand; reusita sterge pauza
bo = folder("backoff")
assert run(EXE, "/activate", "TKITABCDE12345FGHJK", licdir=bo, server=URL)[0] == 0
(bo / "license.lic").write_text(lic(exp=int(time.time()) + 86400, iat=int(time.time()) - 2 * 86400) + "\r\n")
SRV["mode"] = "500"
n0 = len(SRV["calls"])
assert run(EXE, "/license", licdir=bo, server=URL)[0] == 0 and len(SRV["calls"]) == n0 + 1   # incercare, esuata
assert (bo / "refresh.dat").exists()
assert run(EXE, "/license", licdir=bo, server=URL)[0] == 0 and len(SRV["calls"]) == n0 + 1   # pauza
assert proof(EXE, NONCE, bo, server=URL)[0] == 0 and len(SRV["calls"]) == n0 + 1           # si /proof
(bo / "refresh.dat").write_text(f"TKR1 {int(time.time()) - 3700}\r\n")                       # ora a trecut
assert run(EXE, "/license", licdir=bo, server=URL)[0] == 0 and len(SRV["calls"]) == n0 + 2
(bo / "refresh.dat").write_text(f"TKR1 {int(time.time()) + 5 * 86400}\r\n")                  # din viitor: ignorat
assert run(EXE, "/license", licdir=bo, server=URL)[0] == 0 and len(SRV["calls"]) == n0 + 3
assert run(EXE, "/refresh", licdir=bo, server=URL)[0] == 1 and len(SRV["calls"]) == n0 + 4   # explicit: oricand
SRV["mode"] = "ok"
assert run(EXE, "/refresh", licdir=bo, server=URL)[0] == 0 and not (bo / "refresh.dat").exists()
# licenta buna, emisa de curand (< 20 h), care expira curand: /license nu reinnoieste
(bo / "license.lic").write_text(lic(exp=int(time.time()) + 86400, iat=int(time.time()) - 3600) + "\r\n")
n1 = len(SRV["calls"])
assert run(EXE, "/license", licdir=bo, server=URL)[0] == 0 and len(SRV["calls"]) == n1


# Dupa asteptarea mutex-ului (alt proces reinnoia / esua): /license verifica din nou pauza si licenta
def held_mutex_run(during, *args):
    """/license pornit cat timp alt proces tine Local\\TopoKitLicense; during() ruleaza intre timp."""
    env = dict(os.environ, TOPOKIT_LICDIR=str(bo), TOPOKIT_LICSERVER=URL)
    env.pop("TOPOKIT_LICREG", None)
    mx = _k32.CreateMutexW(None, True, "Local\\TopoKitLicense")
    try:
        assert mx and _k32.WaitForSingleObject(wintypes.HANDLE(mx), 0) in (0, 0x80)
        p = subprocess.Popen([str(EXE), "/license", *args], stdout=subprocess.PIPE, env=env)
        time.sleep(1.5)
        assert p.poll() is None, "nu a asteptat mutex-ul"
        during()
    finally:
        _k32.ReleaseMutex(wintypes.HANDLE(mx)); _k32.ReleaseMutex(wintypes.HANDLE(mx))
        _k32.CloseHandle(wintypes.HANDLE(mx))
    return p.wait(timeout=60)


soon = lic(exp=int(time.time()) + 86400, iat=int(time.time()) - 2 * 86400)     # de reinnoit
SRV["mode"] = "500"
(bo / "license.lic").write_text(soon + "\r\n")
(bo / "refresh.dat").unlink(missing_ok=True)
n2 = len(SRV["calls"])
assert held_mutex_run(lambda: (bo / "refresh.dat").write_text(f"TKR1 {int(time.time())}\r\n")) == 0
assert len(SRV["calls"]) == n2, "reteaua incercata desi alt proces tocmai esuase (pauza)"
(bo / "refresh.dat").unlink()
fresh = lic(exp=int(time.time()) + 14 * 86400, iat=int(time.time()) - 60)
assert held_mutex_run(lambda: (bo / "license.lic").write_text(fresh + "\r\n")) == 0
assert len(SRV["calls"]) == n2, "reteaua incercata desi alt proces tocmai reinnoise licenta"
# server care nu raspunde (accepta conexiunea, tace): /license si /proof raman sub 10 s, apoi pauza
SRV["mode"] = "slow"
(bo / "license.lic").write_text(soon + "\r\n")
t0 = time.time()
assert run(EXE, "/license", licdir=bo, server=URL)[0] == 0
dt = time.time() - t0
assert dt < 10 and (bo / "refresh.dat").exists() and SRV["calls"][-1][0] == "/api/refresh", dt
t0 = time.time()
assert proof(EXE, NONCE, bo, server=URL)[0] == 0 and time.time() - t0 < 3        # pauza: fara retea
(bo / "refresh.dat").unlink()
t0 = time.time()
assert proof(EXE, NONCE, bo, server=URL)[0] == 0 and time.time() - t0 < 10
SRV["mode"] = "ok"
print(f"  linia de comanda: dupa mutex verifica din nou pauza / licenta; server tacut -> {dt:.1f} s (limita 8 s)")
srv.shutdown()
print("activare, cod refolosit, reinnoire, server cazut / fara retea (licenta ramane), acces oprit (licenta stearsa),")
print("  reinnoire automata la /license, dezactivare; secretul dispozitivului e protejat cu DPAPI;")
print("  raspunsuri false / ciudate respinse, ora vazuta corectata de server, activare cu ceasul gresit;")
print("  fara internet: pauza de o ora intre reinnoirile din linia de comanda (refresh.dat)")

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

# ---------------------------------------------------------------- programele Python: tklic
# DWG to KMZ si Plan Inclinare verifica singure licenta (tklic.py, testul complet: tests/test_tklic.py);
# aici: aceleasi coduri ca TopoKit.exe (de mai sus) pe aceleasi licente
sys.path.insert(0, str(ROOT / "dwg2kmz"))
import tklic  # noqa: E402
for f in ("dwg2kmz/dwg2kmz.py", "inclinare/plan_inclinare.py"):
    src = (ROOT / f).read_text(encoding="utf-8")
    assert "tklic.gate()" in src and "licenta_ok" not in src and "returncode == 0" not in src, f
corpus = [(n, t, c) for n, (t, _, c) in cases.items()] + [(n, t, c) for n, (t, c) in odd.items()]
for name, text, code in corpus:
    got = tklic._check(text.encode("utf-8") + b"\r\n", bytes.fromhex(pub), "t1", mid, int(time.time()))
    assert got == code, (name, got, code)
print("DWG to KMZ / Plan Inclinare (tklic.py): aceleasi rezultate ca TopoKit.exe /license")

shutil.rmtree(TMP, ignore_errors=True)
shutil.rmtree(OUT, ignore_errors=True)
print("\nToate testele licentei au trecut.")
