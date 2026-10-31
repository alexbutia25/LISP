"""Suport DWG: conversie DWG -> DXF cu ODA File Converter (daca e instalat) sau LibreDWG (inclus)."""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

CREATE_NO_WINDOW = 0x08000000
ODA_DOWNLOAD_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"


class DwgError(RuntimeError):
    pass


def _app_dirs():
    out = []
    for b in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__)),
              os.path.dirname(os.path.abspath(sys.argv[0]))):
        if b and b not in out:
            out.append(b)
    return out


def find_oda():
    pats = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if root:
            pats.append(os.path.join(root, "ODA", "ODAFileConverter*", "ODAFileConverter.exe"))
            pats.append(os.path.join(root, "Programs", "ODA", "ODAFileConverter*", "ODAFileConverter.exe"))
    found = sorted({p for pat in pats for p in glob.glob(pat)}, reverse=True)   # cea mai noua versiune
    return found[0] if found else None


def find_libredwg():
    for b in _app_dirs():
        p = os.path.join(b, "tools", "libredwg", "dwg2dxf.exe")
        if os.path.isfile(p):
            return p
    return shutil.which("dwg2dxf")


def available():
    """Lista convertoarelor gasite, in ordinea preferintei."""
    out = []
    if find_oda():
        out.append("ODA File Converter")
    if find_libredwg():
        out.append("LibreDWG")
    return out


def _convert_oda(exe, src, out_dir):
    in_dir = tempfile.mkdtemp(prefix="dwg2kmz_in_")
    try:
        name = "desen.dwg"
        shutil.copyfile(src, os.path.join(in_dir, name))
        # ODAFileConverter <in> <out> <versiune> <tip> <recursiv> <audit> [filtru]
        r = subprocess.run([exe, in_dir, out_dir, "ACAD2018", "DXF", "0", "1", name],
                           capture_output=True, text=True, errors="replace", timeout=300,
                           creationflags=CREATE_NO_WINDOW)
        dxf = os.path.join(out_dir, "desen.dxf")
        if not os.path.isfile(dxf):
            raise DwgError(f"ODA File Converter nu a putut converti fișierul.\n{(r.stderr or r.stdout)[:300]}")
        return dxf
    finally:
        shutil.rmtree(in_dir, ignore_errors=True)


def _convert_libredwg(exe, src, out_dir):
    dxf = os.path.join(out_dir, "desen.dxf")
    r = subprocess.run([exe, "-y", "-o", dxf, src], capture_output=True, text=True, errors="replace",
                       timeout=300, creationflags=CREATE_NO_WINDOW, cwd=os.path.dirname(exe))
    if not os.path.isfile(dxf) or os.path.getsize(dxf) < 100:
        raise DwgError(f"LibreDWG nu a putut converti fișierul.\n{(r.stderr or r.stdout)[-300:]}")
    return dxf


def dwg_to_dxf(src):
    """Converteste DWG in DXF temporar. Intoarce (cale_dxf, folder_temporar, convertor)."""
    out_dir = tempfile.mkdtemp(prefix="dwg2kmz_dwg_")
    errors = []
    oda = find_oda()
    if oda:
        try:
            return _convert_oda(oda, src, out_dir), out_dir, "ODA File Converter"
        except Exception as ex:
            errors.append(str(ex))
    lib = find_libredwg()
    if lib:
        try:
            return _convert_libredwg(lib, src, out_dir), out_dir, "LibreDWG"
        except Exception as ex:
            errors.append(str(ex))
    shutil.rmtree(out_dir, ignore_errors=True)
    if not errors:
        raise DwgError("Pentru fișiere DWG e nevoie de ODA File Converter (gratuit).\n\n"
                       f"Descarcă-l și instalează-l de aici:\n{ODA_DOWNLOAD_URL}\n\n"
                       "Apoi încarcă din nou fișierul DWG. Alternativ, salvează desenul ca DXF din AutoCAD.")
    if not oda:
        errors.append("Pentru desene DWG foarte noi sau complexe, instalează gratuit ODA File Converter:\n"
                      f"{ODA_DOWNLOAD_URL}\nsau salvează desenul ca DXF din AutoCAD.")
    raise DwgError("\n\n".join(errors))


# --------------------------------------------------------------------------
#  Reparare DXF
# --------------------------------------------------------------------------
# LibreDWG scrie uneori DXF-uri stricate: obiecte (materiale, XRECORD-uri, solide 3D)
# cu text binar si randuri rupte, handle-uri goale sau intrari de dictionar spre
# handle 0. ezdxf refuza atunci tot fisierul ("Invalid group code ..."). Aici
# scoatem doar obiectele stricate; liniile, poliliniile si textele raman.

_NAME = re.compile(rb"^[A-Z_][A-Z0-9_]*$")
_HEX = re.compile(rb"^[0-9A-Fa-f]+$")
_SKIP_SECTIONS_MINIMAL = (b"CLASSES", b"OBJECTS", b"ACDSDATA", b"THUMBNAILIMAGE")


def _kind(code):
    if (10 <= code <= 59 or 110 <= code <= 149 or 210 <= code <= 239 or 460 <= code <= 469
            or 1010 <= code <= 1059):
        return "f"
    if (60 <= code <= 99 or 160 <= code <= 179 or 270 <= code <= 299 or 370 <= code <= 389
            or 400 <= code <= 409 or 420 <= code <= 429 or 440 <= code <= 459 or 1060 <= code <= 1071):
        return "i"
    if code in (5, 105) or 320 <= code <= 369 or 390 <= code <= 399 or 480 <= code <= 481 or code == 1005:
        return "h"
    return "s"


def _value_ok(code, raw):
    v = raw.strip()
    k = _kind(code)
    if k == "s":
        return True
    if k == "h":
        return bool(_HEX.match(v)) and not (code in (5, 105) and int(v, 16) == 0)
    try:
        float(v)
        return True
    except ValueError:
        return False


def _is_start(lines, i):
    return lines[i].strip() == b"0" and i + 1 < len(lines) and bool(_NAME.match(lines[i + 1].strip()))


def _groups(lines):
    """Imparte randurile in grupuri care incep cu codul 0. Intoarce [start, name, ok]."""
    out = []
    n = len(lines)
    i = 0
    while i < n and not _is_start(lines, i):
        i += 1
    cur = None
    while i + 1 < n:
        try:
            code = int(lines[i].strip())
            valid = -5 <= code <= 1071 or code == 999
        except ValueError:
            valid = False
        if valid and code == 0:
            name = lines[i + 1].strip()
            cur = [i, name, bool(_NAME.match(name))]
            out.append(cur)
            i += 2
            continue
        if valid and cur is not None and _value_ok(code, lines[i + 1]):
            i += 2
            continue
        # rand stricat: renuntam la tot obiectul si cautam inceputul urmatorului
        if cur is not None:
            cur[2] = False
        i += 1
        while i + 1 < n and not _is_start(lines, i):
            i += 1
    return out


def _clean_dictionary(chunk):
    """Scoate intrarile de dictionar (3 nume / 350|360 handle) care trimit la handle 0 sau gol."""
    out = []
    i = 0
    while i + 1 < len(chunk):
        c, v = chunk[i].strip(), chunk[i + 1].strip()
        if (c == b"3" and i + 3 < len(chunk) and chunk[i + 2].strip() in (b"350", b"360")
                and (not _HEX.match(chunk[i + 3].strip()) or int(chunk[i + 3].strip(), 16) == 0)):
            i += 4
            continue
        if c in (b"350", b"360") and (not _HEX.match(v) or int(v, 16) == 0):
            i += 2
            continue
        out += chunk[i:i + 2]
        i += 2
    return out + chunk[i:]


def repair_dxf(src, dst, minimal=False):
    """Scrie in dst o copie a lui src fara obiectele stricate. Cu minimal=True scoate
    si sectiunile de care nu avem nevoie (CLASSES, OBJECTS). Intoarce numarul de obiecte scoase."""
    with open(src, "rb") as fh:
        lines = fh.read().split(b"\n")
    groups = _groups(lines)
    starts = [g[0] for g in groups] + [len(lines)]
    out = []
    dropped = 0
    section = None
    skip_section = False
    drop_tail = False
    for k, (start, name, ok) in enumerate(groups):
        chunk = lines[start:starts[k + 1]]
        if name == b"SECTION":
            section = chunk[3].strip() if len(chunk) > 3 else b""
            skip_section = minimal and section in _SKIP_SECTIONS_MINIMAL
            drop_tail = False
        if skip_section:
            if name == b"ENDSEC":
                skip_section = False
            continue
        if name in (b"VERTEX", b"ATTRIB", b"SEQEND") and drop_tail:
            dropped += 1
            continue
        drop_tail = False
        if not ok:
            dropped += 1
            drop_tail = name in (b"POLYLINE", b"INSERT")
            continue
        if name == b"DICTIONARY":
            chunk = _clean_dictionary(chunk)
        out += chunk
    while out and not out[-1].strip():
        out.pop()
    if not out or out[-1].strip() != b"EOF":
        out += [b"  0", b"EOF"]
    out.append(b"")
    with open(dst, "wb") as fh:
        fh.write(b"\n".join(out))
    return dropped
