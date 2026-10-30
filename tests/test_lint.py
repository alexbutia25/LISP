"""Analiza statica a modulelor TopoKit (AutoLISP), fara AutoCAD.

Gaseste: paranteze nepereche, functii definite de doua ori (ca eroarea ct:sub
din CadTopo), apeluri catre functii inexistente, numar gresit de argumente (la
functiile TopoKit si la functiile AutoCAD uzuale), functii transmise citat ('F)
inexistente, chei si dialoguri DCL folosite din LISP dar nedefinite.
Lista functiilor AutoCAD (tests/data/acad_builtins.txt) e extrasa din
Civil 3D 2026 cu (atoms-family 1).
"""
import collections
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = sorted(ROOT.glob("*.lsp"))
BUILTINS = {l.strip().upper() for l in (ROOT / "tests" / "data" / "acad_builtins.txt").read_text().splitlines() if l.strip()}
SPECIAL = {"DEFUN", "DEFUN-Q", "LAMBDA", "SETQ", "IF", "COND", "WHILE", "REPEAT", "FOREACH", "PROGN",
           "AND", "OR", "QUOTE", "FUNCTION", "NOT", "VLAX-FOR"}
# numarul de argumente (minim, maxim; None = oricate) pentru functiile AutoCAD uzuale
AR = {
    "SUBSTR": (2, 3), "NTH": (2, 2), "ASSOC": (2, 2), "CONS": (2, 2), "MEMBER": (2, 2), "SUBST": (3, 3),
    "STRCASE": (1, 2), "ATOI": (1, 1), "ATOF": (1, 1), "ITOA": (1, 1), "RTOS": (1, 3), "DISTOF": (1, 2),
    "ANGTOS": (1, 3), "POLAR": (3, 3), "DISTANCE": (2, 2), "ANGLE": (2, 2), "INTERS": (4, 5),
    "ENTGET": (1, 2), "ENTMOD": (1, 1), "ENTMAKE": (0, 1), "ENTDEL": (1, 1), "ENTNEXT": (0, 1),
    "SSNAME": (2, 2), "SSLENGTH": (1, 1), "SSADD": (0, 2), "SSDEL": (2, 2), "SSMEMB": (2, 2),
    "VL-STRING-SEARCH": (2, 3), "VL-STRING-SUBST": (3, 4), "VL-STRING-TRANSLATE": (3, 3),
    "VL-STRING-POSITION": (2, 4), "VL-STRING-TRIM": (2, 2), "VL-STRING-LEFT-TRIM": (2, 2),
    "VL-STRING-RIGHT-TRIM": (2, 2), "VL-SORT": (2, 2), "VL-REMOVE": (2, 2), "VL-REMOVE-IF": (2, 2),
    "VL-REMOVE-IF-NOT": (2, 2), "VL-POSITION": (2, 2), "VL-FILE-COPY": (2, 3), "VL-FILE-RENAME": (2, 2),
    "VL-FILE-DELETE": (1, 1), "VL-FILENAME-BASE": (1, 1), "VL-FILENAME-DIRECTORY": (1, 1),
    "VL-FILENAME-EXTENSION": (1, 1), "VL-FILENAME-MKTEMP": (0, 3), "VL-DIRECTORY-FILES": (0, 3),
    "VL-CATCH-ALL-APPLY": (1, 2), "VL-CATCH-ALL-ERROR-P": (1, 1), "VL-CATCH-ALL-ERROR-MESSAGE": (1, 1),
    "OPEN": (2, 3), "CLOSE": (1, 1), "READ-LINE": (0, 1), "WRITE-LINE": (1, 2), "FINDFILE": (1, 1),
    "GETFILED": (4, 4), "LOAD_DIALOG": (1, 1), "NEW_DIALOG": (2, 4), "START_DIALOG": (0, 0),
    "DONE_DIALOG": (0, 1), "ACTION_TILE": (2, 2), "SET_TILE": (2, 2), "GET_TILE": (1, 1),
    "MODE_TILE": (2, 2), "START_LIST": (1, 3), "ADD_LIST": (1, 1), "END_LIST": (0, 0),
    "UNLOAD_DIALOG": (1, 1), "WCMATCH": (2, 2), "MAPCAR": (2, None), "APPLY": (2, 2), "IF": (2, 3),
    "VLAX-ENAME->VLA-OBJECT": (1, 1), "VLAX-GET-PROPERTY": (2, None), "VLAX-PUT-PROPERTY": (3, None),
    "VLAX-INVOKE-METHOD": (2, None), "VLAX-INVOKE": (2, None), "VLAX-CURVE-GETAREA": (1, 1),
    "VLAX-CURVE-GETPOINTATDIST": (2, 2), "VLAX-CURVE-GETCLOSESTPOINTTO": (2, 3),
    "VLAX-LDATA-GET": (2, 3), "VLAX-LDATA-PUT": (3, 4), "VLAX-3D-POINT": (1, 3),
    "VL-REGISTRY-READ": (1, 2), "VL-REGISTRY-WRITE": (2, 3), "GETVAR": (1, 1), "SETVAR": (2, 2),
    "TRANS": (3, 4), "STARTAPP": (1, 2), "INITGET": (0, 2), "GETKWORD": (0, 1), "GETPOINT": (0, 2),
    "GETREAL": (0, 1), "GETINT": (0, 1), "GETSTRING": (0, 2), "GETDIST": (0, 2), "ENTSEL": (0, 1),
    "SSGET": (0, 4), "GRDRAW": (3, 4), "ALERT": (1, 1), "VL-PRINC-TO-STRING": (1, 1),
    "VL-PRIN1-TO-STRING": (1, 1), "ABS": (1, 1), "FIX": (1, 1), "FLOAT": (1, 1), "SQRT": (1, 1),
    "SIN": (1, 1), "COS": (1, 1), "ATAN": (1, 2), "EXPT": (2, 2), "LAST": (1, 1), "REVERSE": (1, 1),
    "LENGTH": (1, 1), "CAR": (1, 1), "CDR": (1, 1), "CADR": (1, 1), "CADDR": (1, 1), "EQUAL": (2, 3),
    "EQ": (2, 2), "NULL": (1, 1), "ASCII": (1, 1), "CHR": (1, 1), "ACAD_STRLSORT": (1, 1),
    "TBLSEARCH": (2, 3), "TBLOBJNAME": (2, 2), "HANDENT": (1, 1), "REGAPP": (1, 1), "PROMPT": (1, 1),
    "PRINC": (0, 2), "PRIN1": (0, 2), "VL-MEMBER-IF": (2, 2), "SET": (2, 2), "VLAX-RELEASE-OBJECT": (1, 1),
    "VLAX-CREATE-OBJECT": (1, 1), "VLAX-GET-OBJECT": (1, 1), "VLAX-VARIANT-VALUE": (1, 1),
    "VLAX-SAFEARRAY->LIST": (1, 1), "VLA-ADDHATCH": (4, 5), "VLA-APPENDOUTERLOOP": (2, 2),
    "VLA-ITEM": (2, 2), "VLA-DELETE": (1, 1), "VLA-ADDMENUITEM": (4, 4), "VLA-ADDSEPARATOR": (2, 2),
    "VLA-ADDSUBMENU": (3, 3),
}
FUNARG = {"MAPCAR": 1, "APPLY": 1, "VL-CATCH-ALL-APPLY": 1, "VL-SORT": 2, "VL-REMOVE-IF": 1,
          "VL-REMOVE-IF-NOT": 1, "VL-SOME": 1, "VL-EVERY": 1, "VL-MEMBER-IF": 1}
DLGFN = ("ACTION_TILE", "SET_TILE", "GET_TILE", "MODE_TILE", "START_LIST", "GET_ATTR", "START_IMAGE")


class Sym(str):
    pass


class Node(list):
    line = 0
    file = ""


def read(src, fname):
    toks, i, n, line = [], 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1
        elif c.isspace():
            i += 1
        elif c == ";":
            if src.startswith(";|", i):
                j = src.index("|;", i) + 2
            else:
                j = src.find("\n", i); j = n if j < 0 else j
            line += src.count("\n", i, j); i = j
        elif c in "()'":
            toks.append((c, line)); i += 1
        elif c == '"':
            j = i + 1
            while src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            toks.append((("str", src[i + 1:j]), line)); line += src.count("\n", i, j); i = j + 1
        else:
            j = i
            while j < n and not src[j].isspace() and src[j] not in "()';\"":
                j += 1
            toks.append((src[i:j], line)); i = j
    pos = [0]

    def rd():
        t, ln = toks[pos[0]]; pos[0] += 1
        if t == "(":
            l = Node(); l.line = ln; l.file = fname
            while True:
                if pos[0] >= len(toks):
                    raise SyntaxError(f"{fname}:{ln}: '(' fara pereche")
                if toks[pos[0]][0] == ")":
                    break
                l.append(rd())
            pos[0] += 1
            return l
        if t == ")":
            raise SyntaxError(f"{fname}:{ln}: ')' in plus")
        if t == "'":
            q = Node([Sym("QUOTE"), rd()]); q.line = ln; q.file = fname
            return q
        if isinstance(t, tuple):
            return t
        if re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", t):
            return float(t)
        return Sym(t.upper())

    out = []
    while pos[0] < len(toks):
        out.append(rd())
    return out


issues = []
forms = {}
for f in FILES:
    try:
        forms[f.name] = read(f.read_text(encoding="utf-8", errors="replace"), f.name)
    except SyntaxError as e:
        issues.append(("PARANTEZE", f.name, 0, str(e)))
        forms[f.name] = []


def split_args(a):
    a = list(a) if isinstance(a, list) else []
    if "/" in a:
        k = a.index("/"); return a[:k], a[k + 1:]
    return a, []


defs = collections.defaultdict(list)


def walk_defs(x):
    if isinstance(x, Node) and x:
        if x[0] in ("DEFUN", "DEFUN-Q") and len(x) > 2 and isinstance(x[1], Sym):
            defs[x[1]].append((x.file, x.line, len(split_args(x[2])[0])))
        for y in x:
            walk_defs(y)


for fl in forms.values():
    for x in fl:
        walk_defs(x)
for name, dl in defs.items():
    if len(dl) > 1 and name != "*ERROR*":        # *error* se redefineste local, intentionat
        issues.append(("DUBLURA", dl[0][0], dl[0][1], f"{name}: " + ", ".join(f"{a}:{b}" for a, b, _ in dl)))


def nargs(s):
    return defs[s][-1][2]


def check(x, scope, defname):
    if not isinstance(x, Node) or not x:
        return
    h = x[0]
    if h == "QUOTE":
        q = x[1] if len(x) > 1 else None
        if isinstance(q, Node) and q and q[0] == "LAMBDA":
            check(q, scope, defname)
        return
    if h in ("DEFUN", "DEFUN-Q"):
        p, l = split_args(x[2])
        for y in x[3:]:
            check(y, set(p) | set(l), x[1])
        return
    if h == "LAMBDA":
        p, l = split_args(x[1])
        for y in x[2:]:
            check(y, scope | set(p) | set(l), defname)
        return
    if h in ("FOREACH", "VLAX-FOR"):
        for y in x[2:]:
            check(y, scope | {x[1]}, defname)
        return
    if h == "COND":
        for cl in x[1:]:
            for y in (cl if isinstance(cl, Node) else []):
                check(y, scope, defname)
        return
    if isinstance(h, Sym):
        n = len(x) - 1
        if h not in SPECIAL and h not in BUILTINS and h not in defs and h not in scope:
            issues.append(("NEDEFINIT", x.file, x.line, f"apel {h} in {defname}"))
        if h in defs and h not in BUILTINS and n != nargs(h):
            issues.append(("ARGUMENTE", x.file, x.line, f"{h} cere {nargs(h)}, primeste {n} (in {defname})"))
        if h in AR and h not in defs:
            mn, mx = AR[h]
            if n < mn or (mx is not None and n > mx):
                issues.append(("ARG-ACAD", x.file, x.line, f"{h} cu {n} argumente (in {defname})"))
        k = FUNARG.get(h)
        if k and k < len(x):
            a = x[k]
            if isinstance(a, Node) and len(a) == 2 and a[0] in ("QUOTE", "FUNCTION") and isinstance(a[1], Sym):
                s = a[1]
                if s not in BUILTINS and s not in defs:
                    issues.append(("NEDEFINIT", x.file, x.line, f"'{s} transmis lui {h} in {defname}"))
                elif s in defs and h == "MAPCAR" and nargs(s) != n - 1:
                    issues.append(("ARGUMENTE", x.file, x.line, f"mapcar '{s}: {nargs(s)} argumente, {n - 1} liste"))
                elif s in defs and h in ("APPLY", "VL-CATCH-ALL-APPLY") and len(x) > 2:
                    a2 = x[2]
                    if isinstance(a2, Node) and a2 and a2[0] == "LIST" and len(a2) - 1 != nargs(s):
                        issues.append(("ARGUMENTE", x.file, x.line, f"{h} '{s}: cere {nargs(s)}, primeste {len(a2) - 1}"))
        for y in x[1:]:
            check(y, scope, defname)
    else:
        for y in x:
            check(y, scope, defname)


for fl in forms.values():
    for x in fl:
        check(x, set(), "<fisier>")

# DCL: cheile si dialogurile folosite din LISP trebuie sa existe (in .dcl sau in DCL-ul scris din LISP)
text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in list(ROOT.glob("*.dcl")) + FILES)
keys = set(re.findall(r'key\s*=\s*\\?"([^"\\]+)\\?"', text))
dialogs = set(re.findall(r'([A-Za-z0-9_]+)\s*:\s*dialog\b', text))


def check_dcl(x):
    if isinstance(x, Node) and x:
        h = x[0]
        if h in DLGFN and len(x) > 1 and isinstance(x[1], tuple):
            k = x[1][1]
            if k not in keys and k not in ("accept", "cancel", "help", "info", "error"):
                issues.append(("DCL-CHEIE", x.file, x.line, f"{h} \"{k}\""))
        if h == "NEW_DIALOG" and len(x) > 1 and isinstance(x[1], tuple) and x[1][1] not in dialogs:
            issues.append(("DCL-DIALOG", x.file, x.line, f"new_dialog \"{x[1][1]}\""))
        for y in x:
            check_dcl(y)


for fl in forms.values():
    for x in fl:
        check_dcl(x)

for k, f, l, m in sorted(issues):
    print(f"{k:10} {f}:{l}  {m}")
assert not issues, f"{len(issues)} probleme gasite"
print(f"Analiza statica: {len(FILES)} module, {len(defs)} functii, {len(keys)} chei DCL - fara probleme.")
