#!/usr/bin/env python3
"""Teste pentru tklic.py: verificarea licentei in DWG to KMZ si Plan Inclinare (fara TopoKit.exe).

    python tests/test_tklic.py

Cu o cheie de test generata aici (doar in memorie; cheia adevarata nu se foloseste):
  - dwg2kmz/tklic.py si inclinare/tklic.py sunt identice;
  - licente bune / pentru alt calculator / expirate / semnatura gresita / payload modificat /
    base64 stricat / fara iat sau exp / alt kid / alta versiune / ceasul dat inapoi: aceleasi
    rezultate ca tools/licenta.py license_status (si ca lansatorul: tests/test_licenta.py);
  - ora cea mai mare vazuta (seen.dat, DPAPI): ceasul dat inapoi cu mai mult de o zi = refuz;
  - cheia publica vine doar din modulul generat _tk_pub.py (licenta.write_pub_module): fara el exe-ul
    compilat refuza, cu modulul gol (build fara licentiere) porneste, cheia nu apare in clar;
  - gate(): licenta buna -> fara TopoKit.exe; licenta lipsa -> TopoKit.exe /license o singura data
    (codul de iesire nu conteaza: un TopoKit.exe fals care iese cu 0 nu deschide programul), apoi
    mesaj + fereastra TopoKit; o reinnoire facuta de /license e acceptata;
  - programele: verificarea la pornire, la export si in functiile care scriu fisierele.
Nu se ruleaza niciun TopoKit.exe si nu se atinge %LOCALAPPDATA%\\TopoKit sau registrul.
"""
import ast, ctypes, hashlib, importlib.util, json, os, pathlib, re, secrets, shutil, sys, tempfile, time, types
from ctypes import wintypes

if os.name != "nt":
    print("tklic are nevoie de Windows (CNG, DPAPI) - omis.")
    sys.exit(0)

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "dwg2kmz"))
import licenta as L          # noqa: E402
import tklic as T            # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="tklic_app_"))
NOW = int(time.time())
n_ok = 0


def check(cond, msg=""):
    global n_ok
    if not cond:
        raise AssertionError(msg)
    n_ok += 1


# ---------------------------------------------------------------- copii identice
src = (ROOT / "dwg2kmz" / "tklic.py").read_bytes()
check(src == (ROOT / "inclinare" / "tklic.py").read_bytes(), "dwg2kmz/tklic.py != inclinare/tklic.py")

# ---------------------------------------------------------------- licente de test
key = L.gen_key("t1")
pub = L.public_hex(key)
PUB = bytes.fromhex(pub)
mid = L.machine_id()
check(T._mine() == mid, (T._mine(), mid))                       # acelasi cod ca licenta.py / TopoKit.exe /machine
# SHA-256 cu BCryptCreateHash/HashData/FinishHash (BCryptHash = doar Windows 10+, nu se foloseste)
for n in (0, 1, 55, 56, 64, 1000, 70000):
    x = secrets.token_bytes(n)
    check(T._h(x) == hashlib.sha256(x).digest(), ("sha256", n))
check(b'"BCryptHash"' not in src, "BCryptHash (Windows 10+) in tklic.py")


def payload(**kw):
    p = {"v": 1, "kid": "t1", "typ": "internal", "lid": "d_1", "uid": 1, "name": "Ion Popescu ăîșț \"x\"",
         "machine": mid, "features": ["all"], "iat": NOW, "exp": NOW + 14 * 86400}
    p.update(kw)
    return {k: v for k, v in p.items() if v is not None}


def lic(**kw):
    return L.make_license(key, payload(**kw))


good = lic()
head, body, sig = good.split(".")
other = L.gen_key("t1")
tampered_body = L.b64u(json.dumps(payload(exp=NOW + 3650 * 86400), separators=(",", ":")).encode())
CODES = {"ok": 0, "format": 11, "semnatura": 11, "kid": 11, "calculator": 12, "expirata": 13, "ceas": 14}
corpus = {
    "buna": (good, 0),
    "buna_bom_spatii": ("﻿  " + good + " \r\n\r\n", 0),
    "buna_egal_final": (good + "==", 0),
    "buna_egal_multe": (good + "=====", 0),
    "egal_in_payload": (f"{head}.{body}==.{sig}", 11),           # semnatura e peste textul exact
    "egal_la_mijloc": (f"{head}.{body[:8]}={body[8:]}.{sig}", 11),
    "spatiu_in_interior": (f"{head}. {body}.{sig}", 11),
    "alt_calculator": (lic(machine="0" * 24), 12),
    "calculator_mic": (lic(machine=mid.lower()), 0),
    "calculator_lung": (lic(machine=mid + "00"), 12),
    "calculator_lipsa": (L.make_license(key, {k: v for k, v in payload().items() if k != "machine"}), 11),
    "expirata": (lic(exp=NOW - 5), 13),
    "expira_acum": (lic(exp=NOW), 13),
    "ceas": (lic(iat=NOW + 3 * 86400), 14),
    "ceas_toleranta": (lic(iat=NOW + 3600), 0),
    "semnatura_gresita": (good[:-6] + "AAAAAA", 11),
    "alta_cheie": (L.make_license(other, payload()), 11),
    "payload_modificat": (f"{head}.{tampered_body}.{sig}", 11),
    "base64_stricat": (f"{head}.{body[:10]}*{body[11:]}.{sig}", 11),
    "gunoi_dupa_egal": (good + "=x", 11),
    "semnatura_scurta": (f"{head}.{body}.{sig[:-4]}", 11),
    "punct_in_plus": (good + ".AAAA", 11),
    "fara_iat": (lic(iat=None), 11),
    "fara_exp": (lic(exp=None), 11),
    "iat_text": (lic(iat=str(NOW)), 11),
    "alt_kid": (lic(kid="zz"), 11),
    "versiune_2": (lic(v=2), 11),
    "versiune_true": (lic(v=True), 11),
    "nu_e_licenta": ("TK1.nu-e-licenta", 11),
    "alt_prefix": ("TK2." + good[4:], 11),
    "payload_gol": (f"{head}..{sig}", 11),
    "non_ascii": (good[:-3] + "ș" + good[-2:], 11),
    "payload_lista": ("TK1." + L.b64u(b"[1,2]") + "." + L.b64u(L.sign(key, ("TK1." + L.b64u(b"[1,2]")).encode())), 11),
}
for name, (text, want) in corpus.items():
    got = T._check(text.encode("utf-8"), PUB, "t1", mid, NOW)
    check(got == want, (name, got, want))
    st = L.license_status(text, pub, "t1", mid, NOW)[0]       # aceleasi reguli ca tools/licenta.py
    check(CODES[st] == got, ("paritate licenta.py", name, st, got))
check(T._check(b"", PUB, "t1", mid, NOW) == 10 and T._check(b" \r\n", PUB, "t1", mid, NOW) == 10)
check(T._check(good.encode(), PUB, "", mid, NOW) == 11)                 # fara kid: niciodata buna
check(T._check(good.encode() + b"\0gunoi", PUB, "t1", mid, NOW) == 0)    # ca lansatorul (sir C)
check(T._check(good.encode(), PUB, "t1", "0" * 24, NOW) == 12)
print(f"tklic._check: {len(corpus)} licente, aceleasi rezultate ca licenta.py")


# ---------------------------------------------------------------- _tk_pub.py generat
def sub(name):
    d = TMP / name
    d.mkdir(exist_ok=True)
    return d / "_tk_pub.py"


def load_pub(path):
    spec = importlib.util.spec_from_file_location("_tk_pub", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    sys.modules["_tk_pub"] = m
    return m


pubmod = L.write_pub_module(TMP / "_tk_pub.py", pub, "t1")
text = pubmod.read_text(encoding="ascii")
check(pub.upper() not in text.upper(), "cheia in clar in _tk_pub.py")
check(b"kidtest9" not in L.write_pub_module(sub("kid"), pub, "kidtest9").read_bytes(), "kid in clar in _tk_pub.py")
check(not re.search(r"[0-9A-Fa-f]{32}", text))
check(PUB not in text.encode("latin-1") and PUB not in pubmod.read_bytes())
m = load_pub(pubmod)
check(T._key() == (PUB, "t1"))
m2 = L.write_pub_module(sub("b"), pub, "t1")
check(m2.read_bytes() != pubmod.read_bytes(), "masca trebuie sa fie aleatoare la fiecare build")
for bad in (("ab", "t1"), (pub, ""), (pub, "x" * 17), (pub, "k\"1")):
    try:
        L.write_pub_module(TMP / "x.py", *bad)
        check(False, ("write_pub_module a acceptat", bad))
    except ValueError:
        check(True)

# tklic.py nu contine nicio cheie si o ia doar din _tk_pub (fara docstring-uri care explica mecanismul)
tree = ast.parse(src.decode("utf-8"))
check(not re.search(rb"[0-9A-Fa-f]{32}", src), "sir hex lung in tklic.py")
for word in (b"licensing.json", b"public_key", b"TK_LIC_PUB", b"returncode"):
    check(word not in src, word)
check(all(ast.get_docstring(n) is None for n in [tree] + [x for x in ast.walk(tree)
          if isinstance(x, (ast.FunctionDef, ast.ClassDef))]), "docstring in tklic.py")
imports = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
check("_tk_pub" in imports)
print("cheia publica: doar din _tk_pub.py generat (mascata XOR, aleator la fiecare build)")

# ---------------------------------------------------------------- _status / valid / gate (folder temporar)
LD = TMP / "lic"
LD.mkdir()
T._dir = lambda: str(LD)
T._REG = "Software\\TopoKitTest-absent-" + secrets.token_hex(6)       # cheie inexistenta: registrul real nu conteaza
licf = LD / "license.lic"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def seen_blob(t):
    d, e = b"TKS1 %d" % t, b"TopoKit ora"
    bd, be = ctypes.create_string_buffer(d, len(d)), ctypes.create_string_buffer(e, len(e))
    i = _Blob(len(d), ctypes.cast(bd, ctypes.POINTER(ctypes.c_char)))
    en = _Blob(len(e), ctypes.cast(be, ctypes.POINTER(ctypes.c_char)))
    o = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(i), None, ctypes.byref(en), None, None, 1, ctypes.byref(o)):
        raise OSError("CryptProtectData")
    r = ctypes.string_at(o.pbData, o.cbData)
    ctypes.windll.kernel32.LocalFree(o.pbData)
    return r


check(not T._on() and T.valid())                                      # din sursa: fara verificare
T.__compiled__ = types.SimpleNamespace(standalone=True)               # ca in exe-ul Nuitka
try:
    check(T._on())
    check(T._status() == 10 and not T.valid())                        # fara license.lic
    licf.write_text(good + "\r\n", encoding="ascii")
    check(T._status() == 0 and T.valid())
    for name, (txt, want) in corpus.items():
        licf.write_bytes(txt.encode("utf-8"))
        check(T._status() == want, (name, T._status(), want))
    licf.write_text(good + "\r\n", encoding="ascii")
    # ora vazuta (seen.dat): cateva ore inainte = toleranta; 3 zile inainte = ceasul dat inapoi; fisier stricat ignorat
    (LD / "seen.dat").write_bytes(seen_blob(NOW + 3 * 3600))
    check(T._status() == 0)
    (LD / "seen.dat").write_bytes(seen_blob(NOW + 3 * 86400))
    check(T._status() == 14 and not T.valid())
    check(T._seen(str(LD)) == NOW + 3 * 86400)
    (LD / "seen.dat").write_bytes(b"stricat")
    check(T._status() == 0)
    (LD / "seen.dat").unlink()
    print("tklic._status: license.lic din folderul licentei, ora vazuta (seen.dat) ca in lansator")

    # cheia: modul lipsa -> refuz (exe compilat fara _tk_pub); modul gol -> fara licentiere; alta cheie -> refuz
    sys.modules["_tk_pub"] = None                                      # import _tk_pub -> ImportError
    check(T._key() is None and T._status() == 11 and not T.valid())
    load_pub(L.write_pub_module(sub("gol")))
    licf.unlink()
    check(T._key() == (b"", "") and T.valid())                         # build fara licentiere
    load_pub(L.write_pub_module(sub("alta"), L.public_hex(other), "t1"))
    licf.write_text(good + "\r\n", encoding="ascii")
    check(T._status() == 11)
    bad = types.ModuleType("_tk_pub")
    bad.A, bad.B, bad.C = b"\1" * 63, b"\2" * 63, b"x"                 # modul stricat: refuz, nu "fara licentiere"
    sys.modules["_tk_pub"] = bad
    check(T._key() is None and not T.valid())
    load_pub(pubmod)
    check(T._status() == 0)
    print("tklic._key: fara _tk_pub refuza, _tk_pub gol = build fara licentiere, alta cheie refuza")

    # gate(): TopoKit.exe /license doar ca reinnoire, codul de iesire ignorat
    calls, boxes, opened = [], [], []
    fake_exe = TMP / "app" / "TopoKit.exe"
    fake_exe.parent.mkdir()
    fake_exe.write_bytes(b"MZ")                                        # nu se ruleaza niciodata
    T._exe = lambda: str(fake_exe)
    T._box = lambda t: boxes.append(t)
    renew = []

    def fake_run(args, **kw):
        calls.append(list(args))
        if renew:
            licf.write_text(renew.pop() + "\r\n", encoding="ascii")
        return types.SimpleNamespace(returncode=0, stdout=b"0", stderr=b"")

    old_run, old_sf = T.subprocess.run, T.os.startfile
    T.subprocess.run, T.os.startfile = fake_run, (lambda p: opened.append(p))
    try:
        check(T.gate() and not calls and not boxes)                    # licenta buna: TopoKit.exe nu porneste
        licf.unlink()
        check(not T.gate())                                            # TopoKit.exe "iese cu 0" - nu ajunge
        check(calls == [[str(fake_exe), "/license"]] and len(boxes) == 1 and opened == [str(fake_exe)])
        check("nu este activat" in boxes[0] or "not activated" in boxes[0])
        licf.write_text(lic(exp=NOW - 60) + "\r\n", encoding="ascii")  # expirata, /license o reinnoieste
        renew.append(lic(iat=NOW, exp=NOW + 14 * 86400))
        check(T.gate() and len(calls) == 2 and len(boxes) == 1)
        renew.append(lic(machine="0" * 24))                              # "reinnoire" pentru alt calculator
        licf.write_text(lic(exp=NOW - 60) + "\r\n", encoding="ascii")
        check(not T.gate() and len(calls) == 3 and len(boxes) == 2)
        licf.write_text(good + "\r\n", encoding="ascii")

        # eroare neasteptata (ex. functie CNG lipsa pe un Windows vechi): licenta invalida + mesaj, nu iesire tacuta
        old_h = T._h

        def no_api(_data):
            raise AttributeError("function 'BCryptX' not found")

        T._h = no_api
        try:
            check(T._status() == 11 and not T.valid())
            check(not T.gate() and len(boxes) == 3 and len(calls) == 4)
            old_exe, T._exe = T._exe, (lambda: (_ for _ in ()).throw(OSError("x")))
            try:
                check(not T.gate() and len(boxes) == 4)                    # si cand gate() insasi se strica
            finally:
                T._exe = old_exe
        finally:
            T._h = old_h
        check(T._status() == 0 and T.gate())
    finally:
        T.subprocess.run, T.os.startfile = old_run, old_sf
    print("tklic.gate: TopoKit.exe /license doar pentru reinnoire (o data), codul lui de iesire nu conteaza;")
    print("  o eroare neasteptata (API Windows lipsa) = licenta invalida, cu mesaj")

    # ---------------------------------------------------------------- programele
    for f, writer, action in (("dwg2kmz/dwg2kmz.py", "save_kmz", "_export"),
                              ("inclinare/plan_inclinare.py", "write_dxf", "export")):
        s = (ROOT / f).read_text(encoding="utf-8")
        t = ast.parse(s)
        fns = {n.name: ast.get_source_segment(s, n) for n in ast.walk(t) if isinstance(n, ast.FunctionDef)}
        check("tklic.valid()" in fns[writer] and "PermissionError" in fns[writer], (f, writer))
        check(fns[action].split("\n")[1].strip() == "if not tklic.gate():", (f, action))
        check("licenta_ok" not in s and "/license" not in s, f)
    pi = (ROOT / "inclinare" / "plan_inclinare.py").read_text(encoding="utf-8")
    main = pi[pi.index('if __name__ == "__main__":'):]
    check(main.index("tklic.gate()") < main.index("run_cli"), "--test inaintea licentei")
    d2k = (ROOT / "dwg2kmz" / "dwg2kmz.py").read_text(encoding="utf-8")
    m_ = d2k[d2k.index("def main():"):]
    check(m_.index("tklic.gate()") < m_.index("App()"))

    sys.path.insert(0, str(ROOT / "inclinare"))
    import plan_inclinare as PI                                         # acelasi modul tklic (copii identice)
    check(PI.tklic is T)
    out = TMP / "plan.dxf"
    geo = types.SimpleNamespace(items=[])
    PI.write_dxf(geo, str(out), "0")                                   # licenta buna: se scrie
    check(out.exists())
    licf.unlink()
    out.unlink()
    try:
        PI.write_dxf(geo, str(out), "0")
        check(False, "write_dxf fara licenta")
    except PermissionError:
        check(not out.exists())
    print("programele: licenta la pornire (si --test), la export si in functiile care scriu fisierele")
finally:
    del T.__compiled__
    sys.modules.pop("_tk_pub", None)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nToate testele tklic au trecut ({n_ok} verificari).")
