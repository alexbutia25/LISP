#!/usr/bin/env python3
"""Copiaza continutul TopoKit.dcl in functia TK:DclLines din TopoKit.lsp.

TopoKit.lsp genereaza dialogul dintr-un fisier temporar daca TopoKit.dcl nu
este gasit. Rulati acest script dupa fiecare modificare a fisierului .dcl:
    python3 tools/embed_dcl.py
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
dcl = (root / "TopoKit.dcl").read_text(encoding="utf-8").splitlines()
lsp_path = root / "TopoKit.lsp"
lsp = lsp_path.read_text(encoding="utf-8")

begin, end = ";;@@DCL-BEGIN@@", ";;@@DCL-END@@"
i, j = lsp.index(begin) + len(begin), lsp.index(end)

def q(line):
    return '"' + line.replace("\\", "\\\\").replace('"', '\\"') + '"'

body = "\n(defun TK:DclLines ()\n  (list\n" + "\n".join("    " + q(l) for l in dcl) + "))\n"
lsp_path.write_text(lsp[:i] + body + lsp[j:], encoding="utf-8")
print(f"TK:DclLines actualizat ({len(dcl)} linii).")
