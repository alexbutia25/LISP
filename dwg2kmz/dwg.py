"""Suport DWG: conversie DWG -> DXF cu ODA File Converter (daca e instalat) sau LibreDWG (inclus)."""
import glob
import os
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
