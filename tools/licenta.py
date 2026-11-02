#!/usr/bin/env python3
"""Licentele TopoKit: cheia de semnare, licente de rezerva (offline), verificare.

    python tools/licenta.py cheie --out FOLDER_SIGUR [--kid k1]   cheia de semnare (o singura data)
    python tools/licenta.py server https://topokit-licente.EXEMPLU.workers.dev
    python tools/licenta.py calculator                            codul acestui calculator
    python tools/licenta.py emite --cheie FOLDER_SIGUR/topokit_cheie_semnare.json \
                                  --nume "Ion Popescu" --calculator A1B2C3-... [--zile 90]
    python tools/licenta.py verifica licenta.lic [--calculator COD]
    python tools/licenta.py secret                                parola paginii de administrare

Formatul licentei (acelasi pentru server, lansatorul C si acest script):

    TK1.<payload>.<semnatura>        (o singura linie, in %LOCALAPPDATA%\\TopoKit\\license.lic)

  payload    = base64url( JSON UTF-8 ), de ex. {"v":1,"kid":"k1","typ":"internal","lid":"d_...",
               "uid":3,"name":"Ion Popescu","machine":"A1B2C3D4E5F6A1B2C3D4E5F6","features":["all"],
               "iat":1761900000,"exp":1763109600}
  semnatura  = base64url( ECDSA P-256 / SHA-256, r||s pe 64 de octeti ) peste textul ASCII "TK1.<payload>"

Codul calculatorului = primii 12 octeti din SHA-256("TopoKit/1|<MachineGuid cu litere mici>|<seria
volumului de sistem, 8 cifre hex>") – 24 de cifre hex (afisat in grupe de cate 6).

Criptografia este cea din Windows (CNG, bcrypt.dll) – fara pachete Python suplimentare.
Cheia privata NU intra in depozit: o pastrati intr-un folder sigur (si o copie offline);
pe server ajunge ca secret (SIGNING_KEY). Cheia publica se scrie in installer/licensing.json
si se compileaza in TopoKit.exe.
"""
import argparse, base64, ctypes, hashlib, json, os, pathlib, re, secrets, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "installer" / "licensing.json"
KEYFILE = "topokit_cheie_semnare.json"

# ---------------------------------------------------------------- CNG (bcrypt.dll)
if os.name == "nt":
    _bc = ctypes.WinDLL("bcrypt")
    _VP, _UL = ctypes.c_void_p, ctypes.c_ulong
    for _n, _a in (("BCryptOpenAlgorithmProvider", [ctypes.POINTER(_VP), ctypes.c_wchar_p, ctypes.c_wchar_p, _UL]),
                   ("BCryptCloseAlgorithmProvider", [_VP, _UL]),
                   ("BCryptGenerateKeyPair", [_VP, ctypes.POINTER(_VP), _UL, _UL]),
                   ("BCryptFinalizeKeyPair", [_VP, _UL]),
                   ("BCryptExportKey", [_VP, _VP, ctypes.c_wchar_p, ctypes.c_char_p, _UL, ctypes.POINTER(_UL), _UL]),
                   ("BCryptImportKeyPair", [_VP, _VP, ctypes.c_wchar_p, ctypes.POINTER(_VP), ctypes.c_char_p, _UL, _UL]),
                   ("BCryptSignHash", [_VP, _VP, ctypes.c_char_p, _UL, ctypes.c_char_p, _UL, ctypes.POINTER(_UL), _UL]),
                   ("BCryptVerifySignature", [_VP, _VP, ctypes.c_char_p, _UL, ctypes.c_char_p, _UL, _UL]),
                   ("BCryptDestroyKey", [_VP])):
        getattr(_bc, _n).argtypes = _a
        getattr(_bc, _n).restype = ctypes.c_long

MAGIC_PUB, MAGIC_PRIV = 0x31534345, 0x32534345          # BCRYPT_ECDSA_PUBLIC/PRIVATE_P256_MAGIC


def _ok(st, what):
    if st:
        raise OSError(f"{what}: NTSTATUS 0x{st & 0xFFFFFFFF:08X}")


def _alg():
    h = _VP()
    _ok(_bc.BCryptOpenAlgorithmProvider(ctypes.byref(h), "ECDSA_P256", None, 0), "ECDSA_P256")
    return h


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64u_dec(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def gen_key(kid="k1"):
    """Cheie noua P-256: dict JWK (cu "d" = partea privata) + kid."""
    a, k = _alg(), _VP()
    try:
        _ok(_bc.BCryptGenerateKeyPair(a, ctypes.byref(k), 256, 0), "GenerateKeyPair")
        _ok(_bc.BCryptFinalizeKeyPair(k, 0), "FinalizeKeyPair")
        n = _UL()
        _ok(_bc.BCryptExportKey(k, None, "ECCPRIVATEBLOB", None, 0, ctypes.byref(n), 0), "ExportKey")
        buf = ctypes.create_string_buffer(n.value)
        _ok(_bc.BCryptExportKey(k, None, "ECCPRIVATEBLOB", buf, n, ctypes.byref(n), 0), "ExportKey")
        raw = buf.raw[:n.value]
    finally:
        if k: _bc.BCryptDestroyKey(k)
        _bc.BCryptCloseAlgorithmProvider(a, 0)
    x, y, d = raw[8:40], raw[40:72], raw[72:104]
    return {"kty": "EC", "crv": "P-256", "x": b64u(x), "y": b64u(y), "d": b64u(d), "kid": kid}


def public_hex(jwk):
    return (b64u_dec(jwk["x"]) + b64u_dec(jwk["y"])).hex().upper()


def _key(blob_type, blob):
    a, k = _alg(), _VP()
    _ok(_bc.BCryptImportKeyPair(a, None, blob_type, ctypes.byref(k), blob, len(blob), 0), "ImportKeyPair")
    return a, k


def sign(jwk, data: bytes) -> bytes:
    blob = (MAGIC_PRIV.to_bytes(4, "little") + (32).to_bytes(4, "little") +
            b64u_dec(jwk["x"]) + b64u_dec(jwk["y"]) + b64u_dec(jwk["d"]))
    a, k = _key("ECCPRIVATEBLOB", blob)
    try:
        h, sig, n = hashlib.sha256(data).digest(), ctypes.create_string_buffer(64), _UL()
        _ok(_bc.BCryptSignHash(k, None, h, 32, sig, 64, ctypes.byref(n), 0), "SignHash")
        return sig.raw[:n.value]
    finally:
        _bc.BCryptDestroyKey(k)
        _bc.BCryptCloseAlgorithmProvider(a, 0)


def verify(pub_hex, data: bytes, sig: bytes) -> bool:
    pub = bytes.fromhex(pub_hex)
    if len(pub) != 64 or len(sig) != 64:
        return False
    a, k = _key("ECCPUBLICBLOB", MAGIC_PUB.to_bytes(4, "little") + (32).to_bytes(4, "little") + pub)
    try:
        return _bc.BCryptVerifySignature(k, None, hashlib.sha256(data).digest(), 32, sig, 64, 0) == 0
    finally:
        _bc.BCryptDestroyKey(k)
        _bc.BCryptCloseAlgorithmProvider(a, 0)


# ---------------------------------------------------------------- licenta
def make_license(jwk, payload: dict) -> str:
    body = "TK1." + b64u(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return body + "." + b64u(sign(jwk, body.encode("ascii")))


_B64U = re.compile(r"[A-Za-z0-9_-]+=*")


def read_license(text, pub_hex, kid=None):
    """(payload, motiv): motiv None = semnatura buna si kid potrivit."""
    text = text.lstrip(" \r\n\t\ufeff").rstrip(" \r\n\t")   # ca Trim() din lansator
    parts = text.split(".")
    # base64url strict, ca lansatorul (B64uDec): alte caractere = licenta stricata, nu ignorate
    if len(parts) != 3 or parts[0] != "TK1" or not all(_B64U.fullmatch(x) for x in parts[1:]):
        return None, "format"
    try:
        payload = json.loads(b64u_dec(parts[1].rstrip("=")).decode("utf-8"))
        sig = b64u_dec(parts[2].rstrip("="))
    except ValueError:                      # si UnicodeDecodeError / binascii.Error
        return None, "format"
    if not isinstance(payload, dict):
        return None, "format"
    if not verify(pub_hex, (parts[0] + "." + parts[1]).encode("ascii"), sig):
        return payload, "semnatura"
    if kid and payload.get("kid") != kid:
        return payload, "kid"
    return payload, None


def license_status(text, pub_hex, kid, machine, now=None):
    """Aceleasi reguli ca lansatorul: ok / format / semnatura / kid / calculator / expirata / ceas."""
    now = int(time.time()) if now is None else now
    p, why = read_license(text, pub_hex, kid)
    if why:
        return why, p
    if type(p.get("v")) is not int or p["v"] != 1:  # true nu este versiunea 1 (ca in lansator)
        return "format", p
    exp, iat = p.get("exp"), p.get("iat")          # obligatorii, numere intregi (ca in lansator)
    if not all(isinstance(x, int) and not isinstance(x, bool) for x in (exp, iat)):
        return "format", p
    if not isinstance(p.get("machine"), str):       # lipsa / nu e sir: licenta stricata (lansatorul: LIC_BAD)
        return "format", p
    if len(p["machine"]) != 24 or p["machine"].upper() != machine_plain(machine):
        return "calculator", p
    if now >= exp:
        return "expirata", p
    if now + 86400 < iat:
        return "ceas", p
    return "ok", p


# ---------------------------------------------------------------- cheia publica pentru programele Python
PUB_MODULE = "_tk_pub.py"


def write_pub_module(path, pub_hex=None, kid=None):
    """Scrie modulul generat _tk_pub.py (langa dwg2kmz.py / plan_inclinare.py, inainte de Nuitka) din
    care tklic.py ia cheia publica si kid-ul. Cheia nu apare in clar: A = cheie XOR B, B aleator, C =
    kid XOR B. Fara pub_hex (build fara licentiere): A = B = C = b"" -> programele pornesc fara licenta.
    Un exe compilat FARA acest modul refuza sa porneasca (nu se deschide in tacere)."""
    if pub_hex is None:
        a = b = c = b""
    else:
        pub = bytes.fromhex(pub_hex)
        k = str(kid or "").encode("ascii")
        if len(pub) != 64 or not re.fullmatch(rb"[A-Za-z0-9_-]{1,16}", k):
            raise ValueError("cheie publica (128 cifre hex) sau kid gresit")
        b = secrets.token_bytes(64)
        a = bytes(x ^ y for x, y in zip(pub, b))
        c = bytes(x ^ y for x, y in zip(k, b))
    path = pathlib.Path(path)
    path.write_text(f"A = {a!r}\nB = {b!r}\nC = {c!r}\n", encoding="ascii")
    return path


# ---------------------------------------------------------------- codul calculatorului
def machine_plain(code):
    return "".join(ch for ch in str(code).upper() if ch in "0123456789ABCDEF")


def machine_group(code):
    c = machine_plain(code)
    return "-".join(c[i:i + 6] for i in range(0, len(c), 6))


def machine_id(guid=None, serial=None):
    if guid is None or serial is None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            guid = winreg.QueryValueEx(k, "MachineGuid")[0]
        windir = ctypes.create_unicode_buffer(260)
        ctypes.windll.kernel32.GetSystemWindowsDirectoryW(windir, 260)
        ser = ctypes.c_ulong()
        ctypes.windll.kernel32.GetVolumeInformationW(windir.value[:3], None, 0, ctypes.byref(ser), None, None, None, 0)
        serial = ser.value
    src = f"TopoKit/1|{guid.lower()}|{serial:08X}".encode("utf-8")
    return hashlib.sha256(src).hexdigest()[:24].upper()


# ---------------------------------------------------------------- configurare (installer/licensing.json)
def load_config(path=CONFIG):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_config(cfg, path=CONFIG):
    pathlib.Path(path).write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _inside_repo(path):
    """Folderul e in depozit (sau chiar depozitul)? Cheia privata nu are voie acolo: ar ajunge in
    git, in arhive sau in folderul de build al instalatorului."""
    p = pathlib.Path(path).resolve()
    return p == ROOT or ROOT in p.parents


def _protect(path):
    """Fisierul cheii: doar utilizatorul curent si SYSTEM, fara drepturile mostenite (radacina unui
    disc ca D:\\ da implicit "Authenticated Users: Modify"). Pe alte sisteme: chmod 600."""
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    sid = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
                         check=True).stdout.strip().split(",")[-1].strip('"')
    if not sid.startswith("S-1-"):
        raise OSError(f"SID necunoscut: {sid!r}")
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:F", "*S-1-5-18:F"],
                   capture_output=True, check=True)


def _cmd_cheie(a):
    out = pathlib.Path(a.out)
    if _inside_repo(out):
        sys.exit(f"Cheia privata nu se pune in depozit ({ROOT}). Alegeti un folder sigur in afara lui "
                 "(ex. D:\\TopoKit-chei).")
    out.mkdir(parents=True, exist_ok=True)
    f = out / KEYFILE
    cfg = load_config()
    if f.exists():
        if not a.force:
            sys.exit(f"Exista deja {f}. O cheie noua invalideaza licentele emise cu cea veche (folositi alt --kid si --force).")
        try:
            old_kid = json.loads(f.read_text(encoding="utf-8")).get("kid")
        except (OSError, ValueError, AttributeError):
            old_kid = None
        if a.kid in (old_kid, cfg.get("kid")):
            sys.exit(f"--kid {a.kid} este deja folosit; o cheie noua are nevoie de alt kid (ex. k2).")
        # cheia veche nu se pierde (inainte --force o suprascria): se muta langa, cu kid-ul si data
        backup = out / f"topokit_cheie_semnare.{old_kid or 'vechi'}.{time.strftime('%Y%m%d-%H%M%S')}.json"
        f.replace(backup)
        print(f"Cheia veche pastrata in {backup}")
    jwk = gen_key(a.kid)
    # fisierul se creeaza gol, primeste drepturile restranse si abia apoi cheia
    f.touch(exist_ok=False)
    try:
        _protect(f)
    except (OSError, subprocess.SubprocessError) as ex:
        f.unlink()
        sys.exit(f"Nu pot restrange drepturile pe {f}: {ex}")
    f.write_text(json.dumps(jwk, indent=2) + "\n", encoding="utf-8")
    cfg.update({"kid": a.kid, "public_key": public_hex(jwk)})
    save_config(cfg)
    print(f"Cheia privata: {f}\n  -> pastrati-o in siguranta (si o copie offline); NU o puneti in depozit.")
    print(f"Cheia publica (kid {a.kid}) scrisa in {CONFIG}")
    print("Pe server: SIGNING_KEY = continutul fisierului de mai sus (wrangler secret put SIGNING_KEY < fisier).")


def _cmd_server(a):
    from urllib.parse import urlsplit
    u = urlsplit(a.url)
    local = u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")
    if not (u.scheme == "https" or local) or not u.hostname or u.query or u.fragment:
        sys.exit("Adresa serverului trebuie sa inceapa cu https:// (fara ?parametri)")
    cfg = load_config()
    cfg["server"] = a.url.rstrip("/")
    save_config(cfg)
    print(f"Server de licente: {cfg['server']} (in {CONFIG})")


def _cmd_emite(a):
    try:
        jwk = json.loads(pathlib.Path(a.cheie).read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        sys.exit(f"Nu pot citi cheia de semnare {a.cheie}: {ex}")
    if not isinstance(jwk, dict) or not all(isinstance(jwk.get(k), str) for k in ("x", "y", "d")):
        sys.exit(f"{a.cheie} nu este cheia privata de semnare (lipseste x / y / d).")
    pub = load_config().get("public_key")
    if pub and public_hex(jwk) != pub.upper():
        sys.exit(f"Cheia {a.cheie} nu corespunde cheii publice din {CONFIG}: licenta nu ar fi acceptata.")
    if not 1 <= a.zile <= 3650:
        sys.exit("--zile intre 1 si 3650.")
    if not a.nume.strip():
        sys.exit("--nume nu poate fi gol.")
    now = int(time.time())
    payload = {"v": 1, "kid": jwk.get("kid", "k1"), "typ": "offline", "lid": "offline-" + secrets.token_hex(4),
               "uid": 0, "name": a.nume, "machine": machine_plain(a.calculator), "features": ["all"],
               "iat": now, "exp": now + a.zile * 86400}
    if len(payload["machine"]) != 24:
        sys.exit("Codul calculatorului are 24 de cifre hex (de ex. A1B2C3-D4E5F6-A1B2C3-D4E5F6).")
    lic = make_license(jwk, payload)
    out = pathlib.Path(a.out or f"TopoKit_{''.join(c for c in a.nume if c.isalnum())}.lic")
    out.write_text(lic + "\r\n", encoding="ascii")
    print(f"Licenta pentru {a.nume} ({machine_group(payload['machine'])}), {a.zile} zile: {out}")
    print("Colegul o importa din fereastra TopoKit: Licenta -> Importa fisier.")


def _cmd_verifica(a):
    cfg = load_config()
    if not cfg.get("public_key"):
        sys.exit(f"Lipseste cheia publica in {CONFIG} (rulati intai: licenta.py cheie).")
    text = pathlib.Path(a.fisier).read_text(encoding="utf-8-sig") if os.path.exists(a.fisier) else a.fisier
    st, p = license_status(text, cfg["public_key"], cfg.get("kid"), a.calculator or machine_id())
    print(json.dumps(p, indent=2, ensure_ascii=False) if p else "(continut ilizibil)")
    print("Stare:", st)
    sys.exit(0 if st == "ok" else 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Licentele TopoKit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("cheie", help="genereaza cheia de semnare")
    p.add_argument("--out", required=True)
    p.add_argument("--kid", default="k1")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("server", help="adresa serverului de licente")
    p.add_argument("url")
    sub.add_parser("calculator", help="codul acestui calculator")
    p = sub.add_parser("emite", help="licenta de rezerva, fara internet")
    p.add_argument("--cheie", required=True)
    p.add_argument("--nume", required=True)
    p.add_argument("--calculator", required=True)
    p.add_argument("--zile", type=int, default=90)
    p.add_argument("--out")
    p = sub.add_parser("verifica", help="verifica un fisier de licenta")
    p.add_argument("fisier")
    p.add_argument("--calculator")
    sub.add_parser("secret", help="parola pentru pagina de administrare (ADMIN_TOKEN)")
    a = ap.parse_args(argv)
    if a.cmd == "cheie": _cmd_cheie(a)
    elif a.cmd == "server": _cmd_server(a)
    elif a.cmd == "calculator": print(machine_group(machine_id()))
    elif a.cmd == "emite": _cmd_emite(a)
    elif a.cmd == "verifica": _cmd_verifica(a)
    elif a.cmd == "secret": print(secrets.token_urlsafe(32))


if __name__ == "__main__":
    main()
