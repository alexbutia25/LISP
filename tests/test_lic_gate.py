#!/usr/bin/env python3
"""Teste offline pentru tools/lic_gate.py (poarta de licenta din modulele compilate).

    python tests/test_lic_gate.py

Verifica, pentru fiecare modul (si varianta en/, daca tools/i18n.py o poate genera):
  - textul modulului ramane acelasi (doar fiecare forma de nivel de sus e pazita (if *G:OK* ...));
    codul adaugat e ASCII, parantezele se inchid, inject e idempotenta si determinista;
  - Check apeleaza doar forme speciale si functii incorporate; toate cele din TRUSTED si doar ele
    (plus vlax-* / vl-load-com) - acoperire completa a verificarii de tip / nume;
  - stub-urile sunt forme statice (fara eval / read / foreach); comenzile = lic_gate.commands, ajutatoarele
    = functiile de nivel de sus (fara c:, *error*, S::*); cheia nu apare in sursa generata;
  - SHA-256 / HMAC (stari intermediare) / codul calculatorului in AutoLISP pur = Python, la granitele de bloc;
  - in simulator (acad_sim; ca in AutoCAD 2026: (type <defun>) = SUBR, apelurile prin simbol):
      * TopoKit.exe adevarat -> modulul se incarca exact ca fara poarta, nimic afisat; dupa incarcare nu
        ramane nicio functie / variabila TKG-* (fara oracol HMAC, fara cheie);
      * exe fals (mac gresit), nonce gresit, exe tacut, fara WScript, raspuns de pe alt calculator (releu),
        exp in trecut, cod 10 -> TOT modulul neutralizat, iar corpul modulului NU ruleaza;
      * ocolirile gasite de verificator: eval / read / princ redefinite (C1), <= / type / = redefinite (C3),
        un "carlig" care pune *G:OK* in timpul verificarii -> fara licenta (sau incarcarea se opreste);
      * MILLISECS negativ (dupa ~24,9 zile) -> nonce valid, licenta buna (B2);
      * o comanda-stub afiseaza mesajul si deschide TopoKit.
"""
import ast, hashlib, hmac, os, pathlib, re, shutil, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import lic_gate as G   # noqa: E402

MODULES = ["TopoKit.lsp", "TopoKitAnexe.lsp", "TopoKitCad.lsp", "TopoKitInclinare.lsp",
           "TopoKitProiect.lsp", "TopoKitTeren.lsp"]
KEY = bytes((i * 7 + 3) & 0xFF for i in range(32))   # cheie de test fixa (build-ul foloseste os.urandom)

# ---------------------------------------------------------------- cititorul din test_lint.py
_lint = ast.parse((ROOT / "tests" / "test_lint.py").read_text(encoding="utf-8"))
_ns = {}
exec(compile(ast.Module([n for n in _lint.body if isinstance(n, (ast.Import, ast.ImportFrom)) or
                         (isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in ("Sym", "Node", "read"))],
                        type_ignores=[]), "test_lint.py", "exec"), _ns)
lread, LSym, LNode = _ns["read"], _ns["Sym"], _ns["Node"]
SPECIAL = {"DEFUN", "LAMBDA", "SETQ", "IF", "COND", "WHILE", "REPEAT", "FOREACH", "PROGN", "AND", "OR",
           "QUOTE", "FUNCTION"}


def heads(x, out, defs=()):
    """Toate functiile apelate (simbol in pozitia de functie), inclusiv in lambda-uri citate / aplicate,
    plus functiile date citat lui vl-catch-all-apply / mapcar."""
    if not isinstance(x, LNode) or not x:
        return
    h = x[0]
    if h == "QUOTE":
        if isinstance(x[1], LNode) and x[1] and x[1][0] == "LAMBDA":
            heads(x[1], out, defs)
        return
    if h in ("VL-CATCH-ALL-APPLY", "MAPCAR", "APPLY") and isinstance(x[1], LNode) and len(x[1]) == 2 \
            and x[1][0] == "QUOTE" and isinstance(x[1][1], LSym):
        out.add(str(x[1][1]))                        # 'functie data ca argument
    if h in ("DEFUN", "LAMBDA"):
        for y in x[(3 if h == "DEFUN" else 2):]:
            heads(y, out, defs)
        return
    if h == "FOREACH":
        for y in x[2:]:
            heads(y, out, defs)
        return
    if isinstance(h, LSym):
        if h not in SPECIAL:
            out.add(str(h))
    else:
        heads(h, out, defs)
    for y in x[1:]:
        heads(y, out, defs)


sources = {m: (ROOT / m).read_text(encoding="utf-8") for m in MODULES}
try:
    import i18n
    en = i18n.build(pathlib.Path(tempfile.mkdtemp(prefix="tkgate_en_")) / "en")
    sources.update({f"en/{m}": (en / m).read_text(encoding="utf-8") for m in MODULES})
except Exception as e:                                   # noqa: BLE001
    print(f"varianta en/ omisa ({e})")

# fara cheie: build de dezvoltare, poarta dezactivata (textul ramane neschimbat)
assert G.inject(sources["TopoKit.lsp"], "TopoKit.lsp") == sources["TopoKit.lsp"]
assert G.inject(sources["TopoKit.lsp"], "TopoKit.lsp", None) == sources["TopoKit.lsp"]
for bad in (b"scurt", b"x" * 31, b"x" * 33, "text"):
    try:
        G.inject(sources["TopoKit.lsp"], "TopoKit.lsp", bad)
        raise AssertionError("cheie gresita acceptata")
    except (ValueError, TypeError):
        pass

# ---------------------------------------------------------------- analiza statica
IS, OS = G.midstates(KEY)
KEY_MARKS = [KEY.hex(), KEY.hex().upper(), " ".join(str(b) for b in KEY[:8])]
prefixes = {}
for name, src in sources.items():
    out = G.inject(src, name, KEY)
    body = src if src.endswith("\n") else src + "\n"
    assert G.unguard(out, name) == body, f"{name}: textul modulului s-a schimbat"
    head, tail = out.split(G.BODY_MARK, 1)
    assert out.isascii() or (head.isascii() and out.endswith(G.footer(name))), name
    assert head.isascii() and G.footer(name).isascii(), f"{name}: cod adaugat ne-ASCII"
    assert G.inject(out, name, KEY) == out, f"{name}: inject nu e idempotenta"
    assert G.inject(src, name, KEY) == out, f"{name}: inject nu e determinista"
    assert not any(k in out for k in KEY_MARKS), f"{name}: cheia apare in sursa"
    lread(out, name)                                     # SyntaxError la paranteze nepereche
    hforms = lread(head, name)
    g, s = G.module_id(name).upper(), G.stub_id(name).upper()
    # fiecare forma a modulului e pazita de decizie
    bspan = G.top_forms(tail[tail.index("\n") + 1:tail.rindex(G.END_MARK)])
    btext = tail[tail.index("\n") + 1:tail.rindex(G.END_MARK)]
    assert all(btext[a:b].startswith(f"(if *{G.module_id(name)}:OK* ") for a, b in bspan), name
    assert len(bspan) == len(G.top_forms(body)), name
    # header: doar functii TKG-*/TKS-*; Check: doar forme speciale + TRUSTED + UNCHECKED (+ TKS:Exe)
    defs = [f[1] for f in hforms if isinstance(f, LNode) and f and f[0] == "DEFUN"]
    assert all(d.startswith((g + ":", s + ":")) for d in defs), defs
    dec = [f for f in hforms if isinstance(f, LNode) and f and f[0] == "SETQ" and f[1] == f"*{g}:OK*"
           and isinstance(f[2], LNode)]
    assert len(dec) == 1 and dec[0][2][0] == "IF" and dec[0][2][1][0][0] == "LAMBDA", "decizia = lambda aplicata"
    check = dec[0][2][1][0]
    used = set()
    heads(check, used)
    allowed = set(G.TRUSTED) | set(G.UNCHECKED) | {s + ":EXE"}
    assert used <= allowed, f"{name}: Check apeleaza functii neverificate: {sorted(used - allowed)}"
    assert set(G.TRUSTED) <= used, f"{name}: TRUSTED are functii nefolosite: {sorted(set(G.TRUSTED) - used)}"
    assert not any(str(u).startswith(g + ":") for u in used), f"{name}: Check apeleaza ajutatoare globale"
    assert not [d for d in defs if d.startswith(g + ":")], "nicio functie TKG-* (Check e lambda)"
    # stub-urile: forme statice
    stubtxt = out[out.index(";;; end of licence gate header"):out.index(G.BODY_MARK)]
    assert not re.search(r"\((eval|read|foreach|mapcar|apply)\b", stubtxt, re.I), f"{name}: stub-uri dinamice"
    stub_cmds = set(re.findall(r"\(defun C:(\S+) \(\) \(" + re.escape(G.stub_id(name)) + r":Stub\)\)", stubtxt))
    assert stub_cmds == set(G.commands(src)) and stub_cmds, (name, stub_cmds ^ set(G.commands(src)))
    stub_h = re.findall(r"\(defun (\S+) \(([^()]*)\) nil\)", stubtxt)
    tops_src = G.top_defuns(src)
    want_h = [(n, " ".join(a)) for n, a in tops_src if not n.upper().startswith(("C:", "S::")) and n.upper() != "*ERROR*"]
    assert stub_h == want_h, name
    assert "*ERROR*" not in {n.upper() for n, _ in stub_h}
    assert f"{G.stub_id(name)}:Exe (/ k l f fh)" in out, "build-ul cauta TopoKit.exe normal (fara cale de test)"
    prefixes.setdefault(pathlib.PurePath(name).name, g)
    print(f"{name}: {len(stub_cmds)} comenzi, {len(stub_h)} ajutatoare neutralizabile, {len(bspan)} forme pazite, "
          f"{len(used)} functii in Check, {len(head)} caractere poarta")
assert len(set(prefixes.values())) == len(MODULES), prefixes
assert "lipsa sau expirata" in G.inject(sources["TopoKit.lsp"], "TopoKit.lsp", KEY)
assert "licence missing" in G.inject(sources["TopoKit.lsp"], "en/TopoKit.lsp", KEY)
small = G.inject("(princ)", "x.lsp", KEY)
assert small.endswith("(princ)\n") and G.unguard(small, "x.lsp") == "(princ)\n"
lread(small, "x.lsp")
assert G.inject("(princ)", "x.lsp", KEY, test_exe=r"C:\t\TopoKit.exe") != small    # doar testele

# ---------------------------------------------------------------- referinte Python
for msg in (b"", b"x", b"TKP2|tk|0|1|ABC", b"a" * 100):
    inner = hashlib.sha256(bytes(b ^ 0x36 for b in KEY + bytes(32)) + msg).digest()
    assert hmac.new(KEY, msg, hashlib.sha256).digest() == hashlib.sha256(bytes(b ^ 0x5C for b in KEY + bytes(32)) + inner).digest()
assert G._compress(G._SHA_H, bytes(b ^ 0x36 for b in KEY + bytes(32))) == IS
import licenta  # noqa: E402
for guid, ser in (("ABCdef-12", 0x1A2B), ("x", 0xEC493166), ("", 0)):
    assert G.machine_code(guid, ser) == licenta.machine_id(guid, ser), guid
assert G.machine_code("g", -330747546) == G.machine_code("g", 0xEC493166)   # seria negativa (INT pe 32 de biti)
import random  # noqa: E402
hdr = G.proof_header(KEY, random.Random(5))
assert G.proof_key_from_header(hdr) == KEY and KEY.hex() not in hdr.lower()
assert ", ".join(str(b) for b in KEY[:4]) not in hdr
assert G.proof_header(KEY, random.Random(5)) != G.proof_header(KEY, random.Random(6))
print("referinte: HMAC = stari intermediare, codul calculatorului = licenta.py, antetul C se inverseaza")

# ---------------------------------------------------------------- SHA-256 in linie (AutoLISP) vs Python
from acad_sim import Acad, Sym, call, env   # noqa: E402
import autolisp_mini as M                   # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="tkgate_"))
acad = Acad(str(ROOT), tempfile.mkdtemp(prefix="tkgate_acad_"))
cf = TMP / "sha.lsp"
cf.write_text(f"""(defun T:SHA (sm sh sp / pad bits i j w a b c d e f g hh t1 t2 kk sd)
  (setq kk '{G._wl(G._SHA_K)})
  {G._sha_block()}
  sd)
(defun T:HX (src / hn hs i) {G._hex8u("hs", "src")} hs)
(defun T:H7 (src / hn hs) {G._hex("hs", "src", 7)} hs)""", encoding="utf-8")
M.load(str(cf))
for msg in (b"", b"abc", b"a" * 55, b"a" * 56, b"a" * 63, b"a" * 64, b"a" * 119, b"a" * 120, bytes(range(100))):
    got = bytes(call(Sym("T:SHA"), [list(msg) or None, [[w >> 16, w & 0xFFFF] for w in G._SHA_H], 0])).hex()
    assert got == hashlib.sha256(msg).hexdigest(), (len(msg), got)
    st = [[w >> 16, w & 0xFFFF] for w in IS]                      # HMAC interior din starea intermediara
    got = bytes(call(Sym("T:SHA"), [list(msg) or None, st, 64])).hex()
    assert got == hashlib.sha256(bytes(b ^ 0x36 for b in KEY + bytes(32)) + msg).hexdigest(), len(msg)
for v in (0, 1, 0x1A2B, -1, -330747546, 2147483647, -2147483648):
    assert call(Sym("T:HX"), [v]) == f"{v & 0xFFFFFFFF:08X}", v
for v in (0, 5, -5, -1, 268435455, 268435456, 2147483647, -2147483648):
    assert call(Sym("T:H7"), [v]) == f"{v & 0xFFFFFFF:07x}", v
print("SHA-256 in linie (si din starea intermediara HMAC) = hashlib, la granitele de bloc; hex pentru numere negative")

# ---------------------------------------------------------------- simulator: poarta completa
cont, inst = TMP / "Contents", TMP / "inst"
cont.mkdir(); inst.mkdir()
(cont / "install.txt").write_text(str(inst) + "\r\n", encoding="ascii")
(inst / "TopoKit.exe").write_bytes(b"MZ")
EXE = f"{inst}\\TopoKit.exe"
GUID, SERIAL = "6f1e2d3c-aaaa-bbbb-cccc-0123456789ab", -330747546      # seria negativa, ca pe calculatorul de test
MACH = G.machine_code(GUID, SERIAL)
reg = {("HKEY_CURRENT_USER\\Software\\TopoKit", "ContentsDir"): str(cont),
       (G.REG_GUID, "MachineGuid"): GUID.upper()}                       # license.c foloseste litere mici
started, runs = [], []
SIM = {"mode": "ok", "code": 0, "exp": 1999999999, "wscript": True, "fso": True, "regerr": False}


def reg_read(k, v=None):
    if SIM["regerr"] and v == "MachineGuid":
        raise RuntimeError("registry")
    return reg.get((k, v))


M.funcs[Sym("VL-REGISTRY-READ")] = reg_read
M.funcs[Sym("VLAX-RELEASE-OBJECT")] = lambda o: None
M.funcs[Sym("STARTAPP")] = lambda *a: started.append(a) or 33
M.funcs[Sym("VLAX-GET-PROPERTY")] = lambda o, p: (SERIAL if o == "drive:C:" else 0x5EED) \
    if (str(o).startswith("drive:") and str(p).upper() == "SERIALNUMBER") else None
acad.envs["SystemRoot"] = "C:\\WINDOWS"
reg[(G.REG_WINNT, "SystemRoot")] = "C:\\WINDOWS"
acad.vars.update({"MILLISECS": 123456, "DATE": 2461346.75})


def create(name):
    if name == "Scripting.FileSystemObject":
        if not SIM["fso"]:
            raise RuntimeError("no FSO")
        return "fso"
    if not SIM["wscript"]:
        raise RuntimeError("no WScript")
    return "WScript.Shell"


def invoke(o, m, *a):
    if o == "fso" and str(m).upper() == "GETDRIVE":
        assert re.fullmatch(r"[A-Z]:", a[0]), a
        return "drive:" + a[0]
    if str(m).upper() != "RUN":
        return 0
    runs.append(a[0])
    mm = re.search(r'^"([^"]+)" /license /proof (\S+) "([^"]+)"$', a[0])
    exe, nonce, out = mm.group(1), mm.group(2), mm.group(3)
    assert re.fullmatch(r"[0-9A-Za-z]{16,64}", nonce), nonce        # Lic_NonceOk din license.c
    if SIM["mode"] == "silent":                       # exe care nu scrie nimic
        return 0
    code, exp, mach = SIM["code"], SIM["exp"], MACH
    alt = G.machine_code("alt", 7)
    if SIM["mode"] == "fakemac":                       # exe fals: iese 0, dar nu stie secretul
        line = f"{code} {exp} {nonce} {'0' * 64} {mach}"
    elif SIM["mode"] == "wrongnonce":                  # raspuns de la alta rulare
        n2 = "tk00000000000000"
        line = f"{code} {exp} {n2} {G.proof_mac(KEY, n2, code, exp, mach)} {mach}"
    elif SIM["mode"] == "relay":                       # releu: exe-ul licentiat al altui calculator semneaza
        line = f"{code} {exp} {nonce} {G.proof_mac(KEY, nonce, code, exp, alt)} {alt}"
    elif SIM["mode"] == "relay4":                      # acelasi releu, raspuns cu 4 campuri
        line = f"{code} {exp} {nonce} {G.proof_mac(KEY, nonce, code, exp, alt)}"
    elif SIM["mode"] == "relaylie":                    # releu care pretinde codul local (mac pe codul lui)
        line = f"{code} {exp} {nonce} {G.proof_mac(KEY, nonce, code, exp, alt)} {mach}"
    elif SIM["mode"] == "oldproto":                    # protocolul vechi TKP1 (fara calculator)
        line = f"{code} {exp} {nonce} " + hmac.new(KEY, f"TKP1|{nonce}|{code}|{exp}".encode(), hashlib.sha256).hexdigest()
    elif SIM["mode"] == "ok4":                         # TopoKit.exe mai vechi: 4 campuri, fara calculator
        line = f"{code} {exp} {nonce} {G.proof_mac(KEY, nonce, code, exp, mach)}"
    elif SIM["mode"] == "expandsz":                    # license.c: MachineGuid nu e REG_SZ -> guid ""
        m0 = G.machine_code("", SERIAL)
        line = f"{code} {exp} {nonce} {G.proof_mac(KEY, nonce, code, exp, m0)} {m0}"
    else:
        line = f"{code} {exp} {nonce} {G.proof_mac(KEY, nonce, code, exp, mach)} {mach}"
    pathlib.Path(out).write_text(line + "\n")
    return 0


M.funcs[Sym("VLAX-CREATE-OBJECT")] = create
M.funcs[Sym("VLAX-INVOKE")] = invoke
BUILTIN_SNAPSHOT = dict(M.funcs)


def reset_env():
    """Fara redefinirile unui test anterior (functiile incorporate redefinite stau in env)."""
    for k in list(env):
        if k in BUILTIN_SNAPSHOT:
            env.pop(k)


def load(name, predefun=""):
    """Incarca modulul injectat; intoarce None sau exceptia care a oprit incarcarea."""
    for c in G.commands(sources[name]):
        env[Sym("C:" + c)] = None
    for h, _ in G.top_defuns(sources[name]):
        env[Sym(h.upper())] = None
    f = TMP / pathlib.PurePath(name).name
    f.write_text(predefun + G.inject(sources[name], name, KEY), encoding="utf-8")
    try:
        M.load(str(f))
        return None
    except Exception as e:                                 # noqa: BLE001
        return e
    finally:
        reset_env()


def is_stub(name, c):
    fn = env.get(Sym("C:" + c))
    return isinstance(fn, M.UFun) and fn.body == [[Sym(G.stub_id(name).upper() + ":STUB")]]


def is_neutral(h):
    fn = env.get(Sym(h.upper()))
    return isinstance(fn, M.UFun) and fn.body == [Sym("NIL")]


def gate_left(name):
    g = G.module_id(name).upper()
    return [k for k, v in env.items() if str(k).startswith((g + ":", "*" + g + ":")) and v is not None]


def neutral(name, why):
    cmds = G.commands(sources[name])
    helpers = [h for h, _ in G.stub_helpers(sources[name])]
    assert all(is_stub(name, c) for c in cmds), (name, why, "comenzi")
    assert all(is_neutral(h) for h in helpers), (name, why, "ajutatoare")
    assert not gate_left(name), (name, why, gate_left(name))


for name in MODULES:
    cmds = G.commands(sources[name])
    helpers = [h for h, _ in G.stub_helpers(sources[name])]
    # 0. referinta: modulul fara poarta (ce defineste la incarcare)
    SIM.update(mode="ok", wscript=True, fso=True, code=0, exp=1999999999)
    before = dict(env)
    plain = TMP / ("plain_" + pathlib.PurePath(name).name)
    plain.write_text(sources[name], encoding="utf-8")
    M.load(str(plain))
    ref = {k: type(v).__name__ for k, v in env.items() if before.get(k) is not v}
    # 1. TopoKit.exe adevarat: licenta buna, modulul ca fara poarta, nimic afisat, nimic din poarta ramas
    acad.out.clear(); runs.clear()
    err = load(name)
    assert err is None, (name, err)
    got = {k: type(v).__name__ for k, v in env.items() if before.get(k) is not v}
    for k, t in ref.items():
        assert got.get(k) == t or str(k).startswith("*TKS-"), (name, k, t, got.get(k))
    assert not any(is_stub(name, c) for c in cmds) and not any(is_neutral(h) for h in helpers), name
    assert not any("licenta" in o or "licence" in o for o in acad.out), (name, acad.out)
    assert len(runs) == 1 and runs[0].startswith(f'"{EXE}" /license /proof tk'), runs
    assert not gate_left(name), (name, gate_left(name))
    # 2. exe fals / nonce gresit / tacut / fara WScript / releu / exp trecut / cod 10 / protocol vechi
    for case in ({"mode": "fakemac"}, {"mode": "wrongnonce"}, {"mode": "silent"}, {"wscript": False},
                 {"mode": "relay"}, {"mode": "relay4"}, {"mode": "relaylie"}, {"exp": 1500000000},
                 {"code": 10, "exp": 0}, {"mode": "oldproto"}, {"fso": False, "mode": "relaylie"},
                 {"fso": False, "mode": "fakemac"}, {"fso": False, "mode": "ok4"}):
        SIM.update(mode="ok", wscript=True, fso=True, code=0, exp=1999999999, regerr=False); SIM.update(case)
        err = load(name)
        assert err is None, (name, case, err)
        neutral(name, case)
    SIM.update(mode="ok", wscript=True, fso=True, code=0, exp=1999999999, regerr=False)
    print(f"simulator {name}: licenta buna -> modul ca fara poarta; fals / releu / expirat -> "
          f"{len(cmds)} stub-uri + {len(helpers)} ajutatoare nil, corpul nerulat")

name = "TopoKitInclinare.lsp"
cmds = G.commands(sources[name])
helpers = [h for h, _ in G.stub_helpers(sources[name])]
g = G.module_id(name).upper()
# 3. C1: eval / read / princ redefinite inainte de incarcare (exe tacut) -> nimic din modul nu ruleaza
for pre in ["(defun eval (x) nil)\n", "(defun read (s) 'TKJUNK)\n", "(defun princ (x) x)\n",
            "(defun TK:Start () nil)\n(defun princ (x) x)\n"]:
    SIM.update(mode="silent")
    err = load(name, predefun=pre)
    # eval / princ cu aritate fixa: sondele sau (princ) de la sfarsit opresc incarcarea - dar stub-urile exista
    if err is None or "princ" in pre:
        neutral(name, pre)
    print(f"C1 {pre.strip()!r}: {'oprita (' + str(err)[:40] + ')' if err else 'neutralizat'}")
# 4. C3: <= / type / = / nth / car redefinite (exe fals) -> sondele opresc incarcarea sau fara licenta
for pre in ["(defun <= (a b) nil)\n", "(defun type (x) 'SUBR)\n(defun = (a b) T)\n", "(setq = equal)\n",
            "(setq <= (lambda (a b) T))\n", "(setq og nth)\n(defun nth (n l) (og n l))\n",
            "(setq oc car)\n(defun car (x) (oc x))\n", "(setq ost strlen)\n(defun strlen (s) 0)\n",
            "(setq osu substr)\n(setq substr strcat)\n"]:
    SIM.update(mode="fakemac")
    env.pop(Sym("*" + g + ":OK*"), None)
    err = load(name, predefun=pre)
    assert env.get(Sym("*" + g + ":OK*")) is None
    if err is None:
        neutral(name, pre)
    else:
        assert not any(env.get(Sym(h.upper())) is not None and not is_neutral(h) for h in helpers), (pre, "corp rulat")
    print(f"C3 {pre.strip()!r}: {'incarcare oprita' if err else 'neutralizat'}")
# 5. un "carlig" (getvar) care pune decizia / redefineste Check in timpul verificarii -> fara efect
SIM.update(mode="fakemac")
err = load(name, predefun=f"(setq ogv getvar)\n(defun getvar (v) (setq *{g}:OK* T) (defun {g}:CHECK () T) (ogv v))\n")
assert err is None, err
assert isinstance(env.pop(Sym(g + ":CHECK")), M.UFun)     # functia atacatorului: nimeni nu o foloseste
neutral(name, "carlig getvar")
SIM.update(mode="silent")
assert load(name) is None                                    # fara carlig: nimic TKG-* ramas
neutral(name, "fara carlig")
# 6. C2: dupa incarcarea fara licenta nu ramane nicio functie TKG-* (vechiul (TKG-..:key) intorcea cheia)
assert env.get(Sym(g + ":KEY")) is None and env.get(Sym(g + ":CHECK")) is None and not gate_left(name)
# si dupa o incarcare oprita (sonda): nimic TKG-* definit
SIM.update(mode="fakemac")
assert load(name, predefun="(defun <= (a b) nil)\n") is not None and not gate_left(name)
assert not any(isinstance(v, list) and v[:4] == list(KEY[:4]) for v in env.values())
# 7. B2: MILLISECS negativ (dupa ~24,9 zile) / foarte mare -> nonce valid, licenta buna
for ms in (-5, -2147483648, 2147483647, 1.5e10):
    SIM.update(mode="ok"); acad.vars["MILLISECS"] = ms; runs.clear()
    assert load(name) is None and not any(is_stub(name, c) for c in cmds), ms
    assert re.search(r"/proof tk[0-9a-f]{26} ", runs[-1]), runs[-1]
acad.vars["MILLISECS"] = 123456


# 7b. codul calculatorului: fara blocari false. Licenta buna (nu stub-uri) cand:
def licensed(case, why):
    SIM.update(mode="ok", wscript=True, fso=True, code=0, exp=1999999999, regerr=False); SIM.update(case)
    runs.clear()
    err = load(name)
    assert err is None and len(runs) == 1, (why, err, runs)
    assert not any(is_stub(name, c) for c in cmds) and not any(is_neutral(h) for h in helpers), why


licensed({"mode": "ok4"}, "TopoKit.exe mai vechi (4 campuri): codul local")
licensed({"mode": "expandsz"}, "MachineGuid REG_EXPAND_SZ: license.c foloseste guid gol")
licensed({"fso": False}, "FSO indisponibil: codul raportat de exe")
licensed({"regerr": True}, "registrul da eroare la MachineGuid: codul raportat de exe")
licensed({"fso": False, "mode": "relay"}, "FSO indisponibil: releul nu se mai poate deosebi (documentat)")
licensed({"exp": 4102444800}, "exp dupa 2038 (atof, nu atoi)")
saved_sr = reg.pop((G.REG_WINNT, "SystemRoot"))                  # fara SystemRoot in registru: %SystemRoot%
licensed({}, "SystemRoot din mediu")
reg[(G.REG_WINNT, "SystemRoot")] = "D:\\Windows"                  # alta unitate: alta serie -> exe-ul are alt cod
SIM.update(mode="ok"); assert load(name) is None; neutral(name, "unitatea sistemului diferita")
reg[(G.REG_WINNT, "SystemRoot")] = saved_sr
# releul cu calculul local reusit: refuzat (si cu 4 campuri, si cand pretinde codul local)
for mode in ("relay", "relay4", "relaylie"):
    SIM.update(mode=mode, fso=True); acad.out.clear(); assert load(name) is None; neutral(name, mode)
    # codul raportat difera de cel local: refuzat, dar cu mesaj (o diferenta de calcul nu blocheaza in tacere)
    shown = [o for o in acad.out if "difera de cel al TopoKit.exe" in o]
    assert bool(shown) == (mode == "relay"), (mode, acad.out[-3:])
    assert mode != "relay" or (MACH in shown[0] and G.machine_code("alt", 7) in shown[0]), shown
SIM.update(mode="ok", wscript=True, fso=True, code=0, exp=1999999999, regerr=False)
print("codul calculatorului: exe vechi / REG_EXPAND_SZ / FSO sau registru indisponibil -> licenta buna (fara blocare "
      "falsa); releu cu calculul local reusit -> refuzat; exp dupa 2038 ok")
# 8. comanda-stub: mesaj + deschide TopoKit
SIM.update(mode="fakemac"); load(name); started.clear(); acad.out.clear()
call(Sym("C:" + cmds[0]), [])
assert started == [(EXE,)] and any("lipsa sau expirata" in o for o in acad.out), (started, acad.out[-3:])
# 9. TopoKit.exe negasit: fail closed
saved = dict(reg); reg.pop(("HKEY_CURRENT_USER\\Software\\TopoKit", "ContentsDir"))
SIM.update(mode="ok"); runs.clear()
assert load(name) is None and not runs
neutral(name, "fara exe")
reg.update(saved)
print("ocoliri: eval/read/princ (C1), <=/type/=/nth/car/strlen/substr (C3), carlig getvar -> fara licenta / "
      "incarcare oprita; nimic TKG-* dupa incarcare (C2); MILLISECS negativ -> nonce bun (B2)")

shutil.rmtree(TMP, ignore_errors=True)
print("\nlic_gate: toate testele au trecut")
