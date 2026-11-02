# TopoKit - modul comun (dwg2kmz/tklic.py == inclinare/tklic.py, copie identica)
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes

_VP, _UL = ctypes.c_void_p, ctypes.c_ulong
_AL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_REG = "Software\\TopoKit"
_lib = []


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _bc():
    # SHA-256 cu BCryptCreateHash / HashData / FinishHash (Windows Vista+); BCryptHash exista doar din Windows 10
    if not _lib:
        b, P = ctypes.WinDLL("bcrypt"), ctypes.POINTER
        for n, a in (("BCryptOpenAlgorithmProvider", [P(_VP), ctypes.c_wchar_p, ctypes.c_wchar_p, _UL]),
                     ("BCryptCloseAlgorithmProvider", [_VP, _UL]),
                     ("BCryptGetProperty", [_VP, ctypes.c_wchar_p, ctypes.c_char_p, _UL, P(_UL), _UL]),
                     ("BCryptCreateHash", [_VP, P(_VP), ctypes.c_char_p, _UL, ctypes.c_char_p, _UL, _UL]),
                     ("BCryptHashData", [_VP, ctypes.c_char_p, _UL, _UL]),
                     ("BCryptFinishHash", [_VP, ctypes.c_char_p, _UL, _UL]),
                     ("BCryptDestroyHash", [_VP]),
                     ("BCryptImportKeyPair", [_VP, _VP, ctypes.c_wchar_p, P(_VP), ctypes.c_char_p, _UL, _UL]),
                     ("BCryptVerifySignature", [_VP, _VP, ctypes.c_char_p, _UL, ctypes.c_char_p, _UL, _UL]),
                     ("BCryptDestroyKey", [_VP])):
            f = getattr(b, n)
            f.argtypes, f.restype = a, ctypes.c_long
        _lib.append(b)
    return _lib[0]


def _h(data):
    b, a, hh, out = _bc(), _VP(), _VP(), ctypes.create_string_buffer(32)
    if b.BCryptOpenAlgorithmProvider(ctypes.byref(a), "SHA256", None, 0):
        return None
    try:
        n, got = ctypes.create_string_buffer(4), _UL(0)
        if b.BCryptGetProperty(a, "ObjectLength", n, 4, ctypes.byref(got), 0) or got.value != 4:
            return None
        obj = ctypes.create_string_buffer(max(int.from_bytes(n.raw, "little"), 1))
        if b.BCryptCreateHash(a, ctypes.byref(hh), obj, len(obj), None, 0, 0):
            return None
        try:
            if b.BCryptHashData(hh, data, len(data), 0) or b.BCryptFinishHash(hh, out, 32, 0):
                return None
        finally:
            b.BCryptDestroyHash(hh)
    finally:
        b.BCryptCloseAlgorithmProvider(a, 0)
    return out.raw


def _v(pub, msg, sig):
    if len(pub) != 64 or len(sig) != 64:
        return False
    h = _h(msg)
    if not h:
        return False
    b, a, k = _bc(), _VP(), _VP()
    if b.BCryptOpenAlgorithmProvider(ctypes.byref(a), "ECDSA_P256", None, 0):
        return False
    try:
        blob = (0x31534345).to_bytes(4, "little") + (32).to_bytes(4, "little") + pub
        if b.BCryptImportKeyPair(a, None, "ECCPUBLICBLOB", ctypes.byref(k), blob, len(blob), 0):
            return False
        try:
            return b.BCryptVerifySignature(k, None, h, 32, sig, 64, 0) == 0
        finally:
            b.BCryptDestroyKey(k)
    finally:
        b.BCryptCloseAlgorithmProvider(a, 0)


def _b64(s):
    out, acc, bits = bytearray(), 0, 0
    for i, c in enumerate(s):
        if c == "=":
            if s[i:].strip("="):
                return None
            break
        v = _AL.find(c)
        if v < 0:
            return None
        acc, bits = ((acc << 6) | v) & 0xFFFFFF, bits + 6
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    return bytes(out)


def _int(x):
    return x if type(x) is int else None


def _check(data, pub, kid, mine, now):
    t = data[:4095].split(b"\0", 1)[0].lstrip(b" \r\n\t\xef\xbb\xbf").rstrip(b" \r\n\t")
    if not t:
        return 10
    try:
        t = t.decode("ascii")
    except UnicodeDecodeError:
        return 11
    p = t.split(".")
    if len(p) != 3 or p[0] != "TK1":
        return 11
    body, sig = _b64(p[1]), _b64(p[2])
    if not body or sig is None or len(sig) != 64 or not _v(pub, (p[0] + "." + p[1]).encode("ascii"), sig):
        return 11
    try:
        j = json.loads(body.decode("utf-8"))
    except ValueError:
        return 11
    if not isinstance(j, dict) or _int(j.get("v")) != 1 or not kid or j.get("kid") != kid:
        return 11
    iat, exp, m = _int(j.get("iat")), _int(j.get("exp")), j.get("machine")
    if iat is None or exp is None or not isinstance(m, str):
        return 11
    if len(m) != 24 or len(mine) != 24 or m.upper() != mine.upper():
        return 12
    if now >= exp:
        return 13
    if now + 86400 < iat:
        return 14
    return 0


def _mine():
    g = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            v, ty = winreg.QueryValueEx(k, "MachineGuid")
            if ty == winreg.REG_SZ:
                g = v[:63]
    except OSError:
        pass
    k32 = ctypes.WinDLL("kernel32")
    w = ctypes.create_unicode_buffer(260)
    k32.GetSystemWindowsDirectoryW(w, 260)
    ser = wintypes.DWORD(0)
    k32.GetVolumeInformationW((w.value or "C:\\")[:3], None, 0, ctypes.byref(ser), None, None, None, 0)
    h = _h(f"TopoKit/1|{g.lower()}|{ser.value:08X}".encode("utf-8"))
    return (h or bytes(32))[:12].hex().upper()


def _dp(blob):
    if not blob:
        return 0
    ent = b"TopoKit ora"
    kb, ke = ctypes.create_string_buffer(blob, len(blob)), ctypes.create_string_buffer(ent, len(ent))
    i = _Blob(len(blob), ctypes.cast(kb, ctypes.POINTER(ctypes.c_char)))
    e = _Blob(len(ent), ctypes.cast(ke, ctypes.POINTER(ctypes.c_char)))
    o = _Blob()
    c32 = ctypes.WinDLL("crypt32")
    if not c32.CryptUnprotectData(ctypes.byref(i), None, ctypes.byref(e), None, None, 1, ctypes.byref(o)):
        return 0
    try:
        s = ctypes.string_at(o.pbData, o.cbData) if o.cbData < 40 else b""
    finally:
        ctypes.WinDLL("kernel32").LocalFree(o.pbData)
    m = re.match(rb"TKS1 \s*([+-]?\d+)", s)
    t = int(m.group(1)) if m else 0
    return t if t > 0 else 0


def _seen(d):
    best = 0
    try:
        with open(os.path.join(d, "seen.dat"), "rb") as f:
            best = _dp(f.read(1023))
    except OSError:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG) as k:
            v, ty = winreg.QueryValueEx(k, "LicSeen")
            if ty == winreg.REG_BINARY and len(v) <= 1024:
                best = max(best, _dp(v))
    except OSError:
        pass
    return best


def _dir():
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.WinDLL("shell32").SHGetFolderPathW(None, 0x801C, None, 0, buf) != 0 or not buf.value:
        buf.value = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(buf.value, "TopoKit")


def _key():
    try:
        import _tk_pub as m
        a, b, c = bytes(m.A), bytes(m.B), bytes(m.C)
    except Exception:
        return None
    if not (a or b or c):
        return b"", ""
    if len(a) != 64 or len(b) != 64 or not 0 < len(c) <= 16:
        return None
    return bytes(x ^ y for x, y in zip(a, b)), bytes(x ^ y for x, y in zip(c, b)).decode("ascii", "replace")


def _on():
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())


def _st(now):
    k = _key()
    if k is None:
        return 11
    if not k[0]:
        return 0
    d = _dir()
    try:
        with open(os.path.join(d, "license.lic"), "rb") as f:
            data = f.read(4095)
    except OSError:
        return 10
    now = int(time.time()) if now is None else now
    st = _check(data, k[0], k[1], _mine(), now)
    if st == 0:
        s = _seen(d)
        if s and now + 86400 < s:
            st = 14
    return st


def _status(now=None):
    # orice eroare neasteptata (API Windows lipsa, ctypes etc.) = licenta invalida, nu oprire tacuta
    try:
        return _st(now)
    except Exception:
        return 11


def _exe():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))), "TopoKit.exe")


def _en():
    try:
        with open(os.path.join(_dir(), "language.txt"), encoding="ascii") as f:
            return f.read(2).upper() == "EN"
    except (OSError, ValueError):
        return False


def text():
    if _en():
        return ("TopoKit is not activated on this computer.\n\nIn the TopoKit window enter the activation code "
                "you received from the administrator.")
    return ("TopoKit nu este activat pe acest calculator.\n\nÎn fereastra TopoKit introduceți codul de activare "
            "primit de la administrator.")


def _box(t):
    ctypes.WinDLL("user32").MessageBoxW(None, t, "TopoKit", 0x10030)


def valid():
    return not _on() or _status() == 0


def _gate():
    if valid():
        return True
    exe = _exe()
    try:
        subprocess.run([exe, "/license"], capture_output=True, timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass
    if _status() == 0:
        return True
    _box(text())
    if os.path.exists(exe):
        try:
            os.startfile(exe)
        except OSError:
            pass
    return False


def gate():
    # tklic nu avanseaza ora vazuta (seen.dat / LicSeen): o face lansatorul cand gaseste o licenta buna
    try:
        return _gate()
    except Exception:
        pass
    try:
        _box(text())
    except Exception:
        pass
    return False
