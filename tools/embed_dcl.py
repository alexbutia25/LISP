#!/usr/bin/env python3
"""Copiaza dialogurile .dcl in fisierele .lsp corespunzatoare:

    TopoKit.dcl      -> functia TK:DclLines  din TopoKit.lsp
    TopoKitAnexe.dcl -> functia TKA:DclLines din TopoKitAnexe.lsp
    TopoKitTeren.dcl -> functia TKT:DclLines din TopoKitTeren.lsp

Programele genereaza dialogul dintr-un fisier temporar daca fisierul .dcl nu
este gasit. Rulati acest script dupa fiecare modificare a unui fisier .dcl:
    python3 tools/embed_dcl.py
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
begin, end = ";;@@DCL-BEGIN@@", ";;@@DCL-END@@"


def q(line):
    return '"' + line.replace("\\", "\\\\").replace('"', '\\"') + '"'


for dcl_name, lsp_name, fn in (("TopoKit.dcl", "TopoKit.lsp", "TK:DclLines"),
                               ("TopoKitAnexe.dcl", "TopoKitAnexe.lsp", "TKA:DclLines"),
                               ("TopoKitTeren.dcl", "TopoKitTeren.lsp", "TKT:DclLines")):
    dcl = (root / dcl_name).read_text(encoding="utf-8").splitlines()
    lsp_path = root / lsp_name
    lsp = lsp_path.read_text(encoding="utf-8")
    i, j = lsp.index(begin) + len(begin), lsp.index(end)
    body = f"\n(defun {fn} ()\n  (list\n" + "\n".join("    " + q(l) for l in dcl) + "))\n"
    lsp_path.write_text(lsp[:i] + body + lsp[j:], encoding="utf-8")
    print(f"{fn} actualizat ({len(dcl)} linii).")
