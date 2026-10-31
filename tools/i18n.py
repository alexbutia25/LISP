#!/usr/bin/env python3
"""Varianta in limba engleza a modulelor TopoKit (interfata: mesaje, intrebari, dialoguri).

    python3 tools/i18n.py extract            lista textelor de tradus care lipsesc din lang/en.txt
    python3 tools/i18n.py build OUT          scrie OUT/*.lsp si OUT/*.dcl traduse
    python3 tools/i18n.py check              raport: cate texte sunt traduse

Dictionarul lang/en.txt are cate o pereche pe rand:  romana <TAB> engleza [<TAB> domeniu]
(textul exact al sirului din sursa, cu secventele \\n, \\" etc. asa cum apar in .lsp).
Domeniul (optional): "label" = doar etichetele dialogurilor (textul apare si in planuri,
de ex. "Cod", "Plansa"); "call:functie" = doar ca argument al functiei (ex. call:tkc:submenu);
un nume de fisier (TopoKitCad.lsp) = doar in acel fisier.
Randurile care incep cu # sunt comentarii.

Se traduc DOAR sirurile din dictionar, intregi (nu parti de sir):
  - in .lsp: sirurile literale ("..."), in afara comentariilor;
  - liniile DCL (fisierele .dcl si copiile lor din .lsp): doar label = "..." si
    tabelele de valori din dictionar.
Textele scrise in desen si in documente (planuri, anexe, tabele, straturi) raman in
romana - nu se pun in dictionar. Tastele din getkword / initget nu se traduc.
"""
import pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LSP = ["TopoKitLoad.lsp", "TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitTeren.lsp", "TopoKitInclinare.lsp", "TopoKitCad.lsp", "TopoKitProiect.lsp"]
DCL = ["TopoKit.dcl", "TopoKitAnexe.dcl", "TopoKitTeren.dcl", "TopoKitInclinare.dcl"]
DICT = ROOT / "lang" / "en.txt"

# apeluri ale caror argumente text sunt afisate utilizatorului
UI_CALLS = {"princ", "prompt", "alert", "getstring", "getpoint", "getreal", "getint", "getdist", "getangle",
            "getorient", "getcorner", "getkword", "entsel", "nentsel", "set_tile", "add_list", "mode_tile"}
UI_SUFFIX = (":msg", ":alert", ":warn", ":ask", ":err", ":error", ":info", ":note", ":prompt", ":getpt",
             ":getdist", ":getreal", ":getint", ":getstr", ":getkw", ":sel", ":selpoly", ":selpolys",
             ":yesno", ":confirm", ":status", ":log", ":say", ":report")


def load_dict(path=DICT):
    d = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.strip() or ln.startswith("#") or "\t" not in ln:
                continue
            parts = ln.split("\t")
            ro, en = parts[0], parts[1]
            # spatiile de la sfarsit (prompturi, bucati de strcat) sunt cele din romana;
            # editoarele le sterg adesea de la capatul randului
            en = en.rstrip(" ") + " " * (len(ro) - len(ro.rstrip(" ")))
            d[ro] = (en, parts[2] if len(parts) > 2 and parts[2] else None)
    return d


def pick(d, s, where):
    """Traducerea lui s pentru locul where: numele fisierului .lsp (sir literal),
    "label" (fisier .dcl) sau "label:<fisier .lsp>" (copia DCL din .lsp); None = nu se traduce."""
    v = d.get(s)
    if v is None:
        return None
    en, scope = v
    if scope is None or scope == where:
        return en
    if scope == "label" and where.startswith("label"):
        return en
    if where.startswith("label:") and scope == where[6:]:
        return en
    return None


def literals(src):
    """(start, end, continut) pentru fiecare sir literal din codul LISP, in afara comentariilor."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == ";":
            if src.startswith(";|", i):
                j = src.find("|;", i + 2)
                i = n if j < 0 else j + 2
            else:
                j = src.find("\n", i)
                i = n if j < 0 else j + 1
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            out.append((i + 1, j, src[i + 1:j]))
            i = j + 1
        else:
            i += 1
    return out


def head_before(src, pos):
    """Numele functiei apelate in a carei lista se afla pozitia (pentru context)."""
    depth, i = 0, pos - 1
    while i >= 0:
        c = src[i]
        if c == ")":
            depth += 1
        elif c == "(":
            if depth == 0:
                m = re.match(r"\(\s*([^\s()\"']+)", src[i:])
                return m.group(1).lower() if m else ""
            depth -= 1
        elif c == '"':                  # sare peste sirul anterior
            j = i - 1
            while j >= 0 and not (src[j] == '"' and (j == 0 or src[j - 1] != "\\")):
                j -= 1
            i = j
        i -= 1
    return ""


DCL_LABEL = re.compile(r'(label\s*=\s*)\\"((?:[^"\\]|\\\\.)*?)\\"')
DCL_LABEL_FILE = re.compile(r'(label\s*=\s*)"((?:[^"\\]|\\.)*?)"')


def translate_lsp(src, d, fname=""):
    def lab(m):
        t = pick(d, m.group(2), "label:" + fname)
        return m.group(1) + '\\"' + (m.group(2) if t is None else t) + '\\"'
    out, last = [], 0
    for a, b, s in literals(src):
        t = pick(d, s, fname)
        if t is None and s in d and (d[s][1] or "").startswith("call:") \
                and head_before(src, a - 1) == d[s][1][5:]:
            t = d[s][0]                                      # doar ca argument al functiei date
        if t is None and "label" in s:                       # linie DCL din copia din .lsp
            t2 = DCL_LABEL.sub(lab, s)
            t = t2 if t2 != s else None
        if t is not None:
            out.append(src[last:a])
            out.append(t)
            last = b
    out.append(src[last:])
    return "".join(out)


def translate_dcl(src, d):
    def lab(m):
        t = pick(d, m.group(2), "label")
        return m.group(1) + '"' + (m.group(2) if t is None else t) + '"'
    return DCL_LABEL_FILE.sub(lab, src)


def looks_text(s):
    """Sir care pare text pentru om (nu cod, cale, model wcmatch, nume de strat)."""
    if len(s) < 3 or not re.search(r"[a-z]{3}", s):
        return False
    if re.fullmatch(r"[A-Z0-9_*#@.,:\-]+", s):
        return False
    if s.startswith(("_", "*", "(", "acad", "AcDb", "http", "%")) or "\\\\" in s:
        return False
    return " " in s or s.endswith(":") or s[0].isupper()


def candidates():
    """Textele interfetei (din apelurile UI si etichetele DCL), in ordinea din surse."""
    seen, res = set(), []
    for f in LSP:
        src = (ROOT / f).read_text(encoding="utf-8")
        for a, b, s in literals(src):
            if "label" in s and DCL_LABEL.search(s):
                for m in DCL_LABEL.finditer(s):
                    if m.group(2) and m.group(2) not in seen:
                        seen.add(m.group(2)); res.append((f, "dcl", m.group(2)))
                continue
            h = head_before(src, a - 1)
            ui = h in UI_CALLS or h.endswith(UI_SUFFIX) or h == "strcat"
            if ui and looks_text(s) and s not in seen:
                seen.add(s); res.append((f, h, s))
    for f in DCL:
        for m in DCL_LABEL_FILE.finditer((ROOT / f).read_text(encoding="utf-8")):
            if m.group(2) and m.group(2) not in seen:
                seen.add(m.group(2)); res.append((f, "dcl", m.group(2)))
    return res


def read(p):
    """Textul fisierului, cu sfarsiturile de rand originale (CRLF / LF)."""
    return p.read_bytes().decode("utf-8")


def build(out, d=None):
    """Scrie in folderul out modulele .lsp (fara incarcator) si .dcl traduse."""
    d = load_dict() if d is None else d
    out.mkdir(parents=True, exist_ok=True)
    for f in LSP:
        if f != "TopoKitLoad.lsp":                        # incarcatorul ramane cel din Contents
            (out / f).write_bytes(translate_lsp(read(ROOT / f), d, f).encode("utf-8"))
    for f in DCL:
        (out / f).write_bytes(translate_dcl(read(ROOT / f), d).encode("utf-8"))
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    d = load_dict()
    if cmd == "extract":
        for f, h, s in candidates():
            if s not in d:
                print(f"{f}\t{h}\t{s}")
    elif cmd == "check":
        c = candidates()
        done = sum(1 for _, _, s in c if s in d)
        print(f"{done} din {len(c)} texte traduse; dictionar: {len(d)} intrari")
    elif cmd == "build":
        build(pathlib.Path(sys.argv[2]), d)
        print(f"Varianta in engleza: {sys.argv[2]} ({len(d)} texte in dictionar)")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
