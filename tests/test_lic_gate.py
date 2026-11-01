#!/usr/bin/env python3
"""Teste offline pentru tools/lic_gate.py (verificarea licentei din modulele compilate).

    python tests/test_lic_gate.py

Verifica, pentru fiecare modul (si varianta en/, daca tools/i18n.py o poate genera):
  - parantezele se inchid (cititorul din tests/test_lint.py), codul adaugat e ASCII;
  - codul adaugat apeleaza doar functii AutoCAD (tests/data/acad_builtins.txt) sau functii proprii;
  - toate comenzile c: ale modulului sunt in lista stub-urilor; inject e idempotenta si determinista;
  - prefixele functiilor adaugate sunt diferite intre module;
  - in simulator (acad_sim): cu licenta (cod 0) comenzile raman ale modulului si nu se afiseaza
    nimic; cu cod 10, fara TopoKit.exe, fara WScript.Shell sau cu eroare la rulare toate comenzile
    devin stub-uri care afiseaza mesajul si deschid TopoKit.exe.
"""
import ast, os, pathlib, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import lic_gate as G   # noqa: E402

MODULES = ["TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitCad.lsp", "TopoKitInclinare.lsp",
           "TopoKitProiect.lsp", "TopoKitTeren.lsp"]

# ---------------------------------------------------------------- cititorul din test_lint.py
# (test_lint.py ruleaza analiza la import; se iau doar clasele Sym, Node si functia read)
_lint = ast.parse((ROOT / "tests" / "test_lint.py").read_text(encoding="utf-8"))
_ns = {}
exec(compile(ast.Module([n for n in _lint.body if isinstance(n, (ast.Import, ast.ImportFrom)) or
                         (isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in ("Sym", "Node", "read"))],
                        type_ignores=[]), "test_lint.py", "exec"), _ns)
lread, LSym, LNode = _ns["read"], _ns["Sym"], _ns["Node"]
BUILTINS = {l.strip().upper() for l in (ROOT / "tests" / "data" / "acad_builtins.txt").read_text().splitlines() if l.strip()}
SPECIAL = {"DEFUN", "LAMBDA", "SETQ", "IF", "COND", "WHILE", "REPEAT", "FOREACH", "PROGN", "AND", "OR",
           "QUOTE", "FUNCTION", "NOT"}


def calls(x, scope, defs, out):
    """Apelurile catre functii necunoscute din formele x."""
    if not isinstance(x, LNode) or not x:
        return
    h = x[0]
    if h == "QUOTE":
        if isinstance(x[1], LNode) and x[1] and x[1][0] == "LAMBDA":
            calls(x[1], scope, defs, out)
        return
    if h in ("DEFUN", "LAMBDA"):
        args = x[2] if h == "DEFUN" else x[1]
        for y in x[(3 if h == "DEFUN" else 2):]:
            calls(y, scope | {a for a in args if a != "/"}, defs, out)
        return
    if h == "FOREACH":
        for y in x[2:]:
            calls(y, scope | {x[1]}, defs, out)
        return
    if isinstance(h, LSym) and h not in SPECIAL and h not in BUILTINS and h not in defs and h not in scope:
        out.append(h)
    for y in x[1:]:
        calls(y, scope, defs, out)


def lisp_cmds(forms):
    """Comenzile C: definite cu defun oriunde in formele citite."""
    out = set()

    def walk(x):
        if isinstance(x, LNode) and x:
            if x[0] == "DEFUN" and len(x) > 1 and isinstance(x[1], LSym) and x[1].startswith("C:"):
                out.add(x[1][2:])
            for y in x:
                walk(y)
    for f in forms:
        walk(f)
    return out


sources = {m: (ROOT / m).read_text(encoding="utf-8") for m in MODULES}
try:
    import i18n
    en = i18n.build(pathlib.Path(tempfile.mkdtemp(prefix="tkgate_en_")) / "en")
    sources.update({f"en/{m}": (en / m).read_text(encoding="utf-8") for m in MODULES})
except Exception as e:                                   # noqa: BLE001
    print(f"varianta en/ omisa ({e})")

prefixes = {}
for name, src in sources.items():
    out = G.inject(src, name)
    head, tail = out.split(src if src.endswith("\n") else src + "\n", 1) if src in out else (None, None)
    assert head is not None and out.startswith(head) and out.endswith(tail), f"{name}: textul modulului s-a schimbat"
    added = head + tail
    assert added.isascii(), f"{name}: cod adaugat ne-ASCII"
    assert G.inject(out, name) == out, f"{name}: inject nu e idempotenta"
    assert G.inject(src, name) == out, f"{name}: inject nu e determinista"
    forms = lread(out, name)                             # SyntaxError la paranteze nepereche
    gate_forms = lread(head, name) + lread(tail, name)   # header si footer sunt complete separat
    assert out.count("(") - src.count("(") == added.count("(") and added.count("(") == added.count(")")
    defs = {f[1] for f in gate_forms if isinstance(f, LNode) and f and f[0] == "DEFUN"}
    p = G.module_id(name)
    assert all(d.startswith(p.upper() + ":") for d in defs), defs
    unknown = []
    for f in gate_forms:
        calls(f, set(), defs, unknown)
    assert not unknown, f"{name}: functii necunoscute in codul adaugat: {unknown}"
    cmds = lisp_cmds(lread(src, name))
    stub = gate_forms[-2]                                # (if (not *P:OK*) (foreach c '(...) ...))
    listed = {s[1] for s in stub[2][2][1]}
    assert cmds and cmds <= listed and listed == set(G.commands(src)), (name, cmds ^ listed)
    prefixes.setdefault(pathlib.PurePath(name).name, p)
    print(f"{name}: {len(cmds)} comenzi in stub-uri, {len(defs)} functii {p}:*, {len(added)} caractere adaugate")
assert len(set(prefixes.values())) == len(MODULES), prefixes
assert "lipsa sau expirata" in G.inject(sources["TopoKit.lsp"], "TopoKit.lsp")
assert "licence missing" in G.inject(sources["TopoKit.lsp"], "en/TopoKit.lsp")
assert G.inject("(princ)", "x.lsp").endswith("(princ)\n")  # fara comenzi: tot valid
lread(G.inject("(princ)", "x.lsp"), "x.lsp")

# ---------------------------------------------------------------- simulator
from acad_sim import Acad, Sym, call, env   # noqa: E402
import autolisp_mini as M                   # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="tkgate_"))
cont, inst = TMP / "Contents", TMP / "inst"
cont.mkdir(); inst.mkdir()
(cont / "install.txt").write_text(str(inst) + "\r\n", encoding="ascii")
(inst / "TopoKit.exe").write_bytes(b"MZ")
EXE = f"{inst}\\TopoKit.exe"
acad = Acad(str(ROOT), tempfile.mkdtemp(prefix="tkgate_acad_"))
reg = {("HKEY_CURRENT_USER\\Software\\TopoKit", "ContentsDir"): str(cont)}
shell = {"rc": 0, "runs": [], "create": True, "fail": False}
started = []


def run(o, m, *a):
    if shell["fail"]:
        raise RuntimeError("Run")
    shell["runs"].append((str(m), a)); return shell["rc"]


def create(name):
    if not shell["create"]:
        raise RuntimeError("no WScript")
    return "WScript.Shell"


M.funcs[Sym("VL-REGISTRY-READ")] = lambda k, v=None: reg.get((k, v))
M.funcs[Sym("VLAX-CREATE-OBJECT")] = create
M.funcs[Sym("VLAX-INVOKE")] = run
M.funcs[Sym("VLAX-RELEASE-OBJECT")] = lambda o: None
M.funcs[Sym("STARTAPP")] = lambda *a: started.append(a) or 33
M.funcs[Sym("LOAD")] = lambda f, *a: None               # submodulele incarcate din TopoKit.lsp: nu aici


def load_injected(name):
    f = TMP / pathlib.PurePath(name).name
    f.write_text(G.inject(sources[name], name), encoding="utf-8")
    for c in G.commands(sources[name]):
        env[Sym("C:" + c)] = None
    M.load(str(f))
    acad.after_load()


def is_stub(name, c):
    fn = env.get(Sym("C:" + c))
    return isinstance(fn, M.UFun) and fn.params == [] and fn.body == [[Sym(G.module_id(name).upper() + ":STUB")]]


for name in MODULES:
    cmds = G.commands(sources[name])
    # cu licenta: o rulare /license, ascuns si cu asteptare, nimic afisat, comenzile reale
    shell.update(rc=0, create=True, fail=False); shell["runs"].clear(); acad.out.clear()
    load_injected(name)
    assert shell["runs"] == [("RUN", (f'"{EXE}" /license', 0, None))], shell["runs"]
    assert not any(is_stub(name, c) for c in cmds) and all(env.get(Sym("C:" + c)) for c in cmds), name
    assert not any("licenta" in o for o in acad.out), acad.out
    # fara licenta / erori: toate comenzile sunt stub-uri
    for case in ({"rc": 10}, {"rc": 13}, {"rc": 0, "create": False}, {"rc": 0, "fail": True}, {"rc": 0.5}):
        shell.update(rc=0, create=True, fail=False); shell.update(case)
        load_injected(name)
        assert all(is_stub(name, c) for c in cmds), (name, case)
    shell.update(rc=0, create=True, fail=False)
    reg_saved = dict(reg); reg.clear(); shell["runs"].clear()
    load_injected(name)                                  # TopoKit.exe negasit: fail closed, fara rulare
    assert shell["runs"] == [] and all(is_stub(name, c) for c in cmds), name
    reg.update(reg_saved)
    started.clear(); acad.out.clear()
    call(Sym("C:" + cmds[0]), [])
    assert started == [(EXE,)], started
    assert any("licenta lipsa sau expirata" in o for o in acad.out), acad.out
    print(f"simulator {name}: licenta buna -> comenzile modulului; fara licenta -> {len(cmds)} stub-uri")

print("lic_gate: toate testele au trecut")
