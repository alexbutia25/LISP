#!/usr/bin/env python3
"""Teste pentru citirea DXF-urilor stricate in DWG to KMZ (dwg.repair_dxf / dwg2kmz.open_dxf).

    python tests/test_dwg.py [fisier.dwg ...]

LibreDWG scrie uneori DXF-uri pe care ezdxf nu le poate citi: materiale si solide 3D
cu text binar si randuri rupte ("Invalid group code ..."), handle-uri goale si intrari
de dictionar spre handle 0. Testul construieste un astfel de fisier si verifica ca
toate entitatile din desen se citesc. Cu fisiere DWG ca argumente le citeste si pe ele.
"""
import os, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "dwg2kmz"))
import ezdxf
from ezdxf import recover
import dwg
import dwg2kmz

OUT = tempfile.mkdtemp(prefix="topokit_dwg_")
ok_count = 0


def check(cond, msg):
    global ok_count
    if not cond:
        raise AssertionError(msg)
    ok_count += 1


# ---------------------------------------------------------------- desen curat
doc = ezdxf.new("R2018")
doc.layers.add("CONTUR", color=1)
doc.layers.add("PUNCTE", color=3)
msp = doc.modelspace()
E0, N0 = 545000.0, 458000.0
msp.add_lwpolyline([(E0, N0), (E0 + 50, N0), (E0 + 50, N0 + 40), (E0, N0 + 40)], close=True,
                   dxfattribs={"layer": "CONTUR"})
msp.add_line((E0, N0), (E0 + 50, N0 + 40), dxfattribs={"layer": "CONTUR"})
for i in range(5):
    msp.add_point((E0 + i * 10, N0 + 5), dxfattribs={"layer": "PUNCTE"})
    msp.add_text(f"P{i + 1}", dxfattribs={"layer": "PUNCTE", "insert": (E0 + i * 10, N0 + 6)})
blk = doc.blocks.new("BORNA")
blk.add_circle((0, 0), 0.5)
msp.add_blockref("BORNA", (E0 + 25, N0 + 20), dxfattribs={"layer": "PUNCTE"})
clean = os.path.join(OUT, "curat.dxf")
doc.saveas(clean)
expected = sorted(e.dxftype() for e in doc.modelspace())

# ---------------------------------------------------------------- stricam fisierul ca LibreDWG
text = open(clean, "rb").read().decode("utf-8")
lines = text.split("\n")


def insert_before(marker_pair, new_lines, after_section=None):
    """Insereaza new_lines inaintea primei perechi (0, marker) dupa sectiunea data."""
    start = 0
    if after_section:
        for i in range(len(lines) - 1):
            if lines[i].strip() == "2" and lines[i + 1].strip() == after_section:
                start = i
                break
    for i in range(start, len(lines) - 1):
        if lines[i].strip() == "0" and lines[i + 1].strip() == marker_pair:
            lines[i:i] = new_lines
            return
    raise AssertionError(f"nu am gasit {marker_pair}")


# material cu XML binar si randuri rupte (exact ce produce LibreDWG)
insert_before("ENDSEC", [
    "  0", "XRECORD", "  5", "FFF1", "330", "0", "100", "AcDbXrecord", "280", "     1",
    "  3", '<Material id="{759404B3}" app="3DSVIZ">',
    "nTranslucCoo F F F F F #",
    "\tRGB\\U+CDCD\\U+FDFD",
    "  3", "0.273249 0.203 -0.440199 0.280618",
    "300", "coedgeD",
    "231.3.1.65535",
], after_section="OBJECTS")
# solid 3D stricat intr-un bloc
insert_before("ENDBLK", [
    "  0", "3DSOLID", "  5", "FFF2", "330", "1F", "100", "AcDbEntity", "  8", "0",
    "100", "AcDbModelerGeometry", " 70", "1", "  1", "ACIS 21800",
    "coedge $-1 -1 $-1 $3 $4",
    "-0.0581329 0.203 0.514791 -0.0666999",
], after_section="BLOCKS")
# obiect cu handle gol
insert_before("ENDSEC", [
    "  0", "DICTIONARYVAR", "  5", "", "330", "0", "100", "DictionaryVariables", "280", "0", "  1", "x",
], after_section="OBJECTS")
broken = os.path.join(OUT, "stricat.dxf")
open(broken, "wb").write("\n".join(lines).encode("utf-8"))

# intrare in dictionarul radacina spre handle 0 ("Invalid handle 0.")
raw = open(broken, "rb").read().split(b"\n")
for i in range(len(raw) - 3):
    if raw[i].strip() == b"3" and raw[i + 1].strip() == b"ACAD_MATERIAL" and raw[i + 2].strip() == b"350":
        raw[i + 3] = b"0"
        break
else:
    raise AssertionError("nu am gasit ACAD_MATERIAL in dictionarul radacina")
open(broken, "wb").write(b"\n".join(raw))

failed = 0
for reader in (ezdxf.readfile, lambda p: recover.readfile(p)[0]):
    try:
        reader(broken)
    except Exception:
        failed += 1
check(failed == 2, "fisierul de test ar trebui sa nu poata fi citit direct de ezdxf")

# ---------------------------------------------------------------- reparare
fixed = os.path.join(OUT, "reparat.dxf")
n = dwg.repair_dxf(broken, fixed, minimal=False)
check(n == 3, f"repair_dxf ar trebui sa scoata cele 3 obiecte stricate (a scos {n})")
n = dwg.repair_dxf(broken, fixed, minimal=True)     # fara OBJECTS ramane doar solidul din bloc
check(n == 1, f"varianta minimala ar trebui sa scoata solidul 3D din bloc (a scos {n})")
d = ezdxf.readfile(fixed)
check(sorted(e.dxftype() for e in d.modelspace()) == expected, "entitatile din desen trebuie sa ramana toate")
check("BORNA" in d.blocks and len(list(d.blocks["BORNA"])) == 1, "blocul BORNA trebuie sa ramana intreg")
check(d.layers.get("CONTUR").color == 1, "culoarea stratului trebuie pastrata")

# fisier curat: reparatia nu schimba nimic din desen
n = dwg.repair_dxf(clean, fixed, minimal=False)
check(n == 0, "un fisier curat nu are nimic de scos")
check(sorted(e.dxftype() for e in ezdxf.readfile(fixed).modelspace()) == expected, "fisier curat neschimbat")

# ---------------------------------------------------------------- citirea completa din program
d = dwg2kmz.open_dxf(broken)
check(len(d.modelspace()) == len(expected), "open_dxf citeste fisierul stricat")
feats, layers, skipped = dwg2kmz.read_dxf(broken)
kinds = sorted(f.kind for f in feats)
check(kinds.count("point") == 6 and kinds.count("text") == 5, f"puncte/texte gresite: {kinds}")
check(kinds.count("polygon") == 1 and kinds.count("line") == 1, f"poligon/linie gresite: {kinds}")
check(set(layers) == {"CONTUR", "PUNCTE"}, f"straturi gresite: {layers}")
check(skipped == 0, "nicio entitate sarita")
check(len(dwg2kmz.read_dxf(clean)[0]) == len(feats), "acelasi rezultat ca pe fisierul curat")

# ---------------------------------------------------------------- fisiere DWG reale (optional)
for path in sys.argv[1:]:
    feats, layers, skipped = dwg2kmz.read_dxf(path)
    check(feats, f"{path}: niciun obiect citit")
    print(f"  {os.path.basename(path)}: {len(feats)} obiecte, {len(layers)} straturi")

print(f"test_dwg: {ok_count} verificari OK")
