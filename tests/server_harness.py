#!/usr/bin/env python3
"""Test complet al serverului de licente: TopoKit.exe <-> server/worker.js <-> SQLite.

    python tests/server_harness.py                       (cheie de test + TopoKit.exe compilate aici, Edge/Chrome headless)
    python tests/server_harness.py --launcher C:\\cale\\TopoKit.exe --key cheie_test.json [--port 8766]
    python tests/server_harness.py --browser none        (deschideti voi http://127.0.0.1:PORT/__harness)
    python tests/server_harness.py --api-only            (fara TopoKit.exe: doar API-ul, fara gcc)

Nu exista Node.js / wrangler pe calculatorul de dezvoltare, asa ca worker.js ruleaza intr-un
browser (Chromium, cu WebCrypto adevarat). Pagina /__harness importa worker.js, ii da o baza D1 falsa
care trimite SQL-ul aici (SQLite in memorie - D1 este SQLite) si preia cererile HTTP primite de acest
server (releu). Cererile se trateaza in paralel, ca pe Cloudflare: intre doua interogari SQL ale unei
cereri pot rula interogarile alteia, deci cursele (doua activari simultane) se vad si aici.
Astfel TopoKit.exe (compilat cu cheia publica de test) vorbeste prin HTTP cu codul real al serverului.

Scenariul: activare, cod refolosit, prea multe calculatoare, reinstalare pe acelasi calculator,
reinnoire, acces oprit, calculator scos, dezactivare, limitarea incercarilor (si prin IPv6 /64, si cu
antete X-Forwarded-For falsificate), activari simultane (cod folosit o singura data, limita de
calculatoare), cereri stricate, campurile licentei, antetele de securitate, curatarea jurnalului,
posibila copiere a unei activari. Codul de iesire 0 = toate verificarile au trecut.
"""
import argparse, base64, concurrent.futures, json, os, pathlib, queue, shutil, sqlite3, subprocess, sys, tempfile
import threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import licenta  # noqa: E402

ADMIN = "parola-test-admin"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>TopoKit - test server</title></head>
<body style="font:14px Segoe UI,sans-serif"><h3>Serverul de licente ruleaza aici (releu)</h3><pre id="log"></pre>
<script type="module">
import worker from "/__worker.js";
const log = (t) => { const p = document.getElementById("log"); p.textContent = (t + "\\n" + p.textContent).slice(0, 20000); };
const q = async (body) => { const r = await fetch("/__sql", {method: "POST", body: JSON.stringify(body)}); const j = await r.json(); if (j.error) throw new Error(j.error); return j; };
class Stmt {
  constructor(sql, params) { this.sql = sql; this.params = params || []; }
  bind(...p) { return new Stmt(this.sql, p); }
  async first() { return (await q({sql: this.sql, params: this.params, mode: "first"})).row; }
  async all() { return {success: true, results: (await q({sql: this.sql, params: this.params, mode: "all"})).results}; }
  async run() { return {success: true, meta: (await q({sql: this.sql, params: this.params, mode: "run"})).meta}; }
}
const DB = { prepare: (sql) => new Stmt(sql), batch: async (st) => { const out = []; for (const s of st) out.push(await s.run()); return out; } };
const cfg = await (await fetch("/__config")).json();
const env = { DB, SIGNING_KEY: cfg.signing_key, ADMIN_TOKEN: cfg.admin, LICENSE_DAYS: "14", CODE_DAYS: "14" };
const ctx = { waitUntil: (p) => p.catch((e) => log("waitUntil: " + e)), passThroughOnException() {} };
async function handle(job) {
  let out;
  try {
    const req = new Request("https://licente.test" + job.path, {method: job.method, headers: job.headers,
                            body: job.method === "GET" || job.method === "HEAD" ? undefined : job.body});
    const res = await worker.fetch(req, env, ctx);
    out = {id: job.id, status: res.status, headers: Object.fromEntries(res.headers), body: await res.text()};
  } catch (e) { out = {id: job.id, status: 599, headers: {"content-type": "text/plain"}, body: String(e && e.stack || e)}; }
  log(job.method + " " + job.path + " -> " + out.status);
  await fetch("/__relay/done", {method: "POST", body: JSON.stringify(out)});
}
if (cfg.unit) {                                   // functiile mici din worker.js, direct
  const { _test } = await import("/__worker.js");
  const r = {ipKey: cfg.unit.ips.map(_test.ipKey), clip: cfg.unit.clips.map(([s, n, b]) => _test.clip(s, n, b ?? Infinity))};
  await fetch("/__unit", {method: "POST", body: JSON.stringify(r)});
}
log("pregatit");
for (;;) {
  let r;
  try { r = await fetch("/__relay/next"); } catch (e) { await new Promise((ok) => setTimeout(ok, 1000)); continue; }
  if (r.status !== 200) continue;
  handle(await r.json());                         // fara await: cererile ruleaza in paralel
}
</script></body></html>"""

# cereri trimise mai departe catre worker; antetele hop-by-hop si cele interzise in fetch() raman aici
SKIP_HEADERS = {"host", "connection", "content-length", "accept-encoding", "transfer-encoding", "keep-alive",
                "cf-connecting-ip", "x-test-ip", "origin", "referer", "cookie", "te", "upgrade", "via", "expect"}

UNIT = {
    "ips": ["203.0.113.7", "2001:db8:1:2:aaaa::1", "2001:0db8:0001:0002:ffff:0:0:9", "2001:db8:1:3::1", "::ffff:10.1.2.3",
            "::1", "fe80::1%eth0", ""],
    "clips": [["ab\u0000c\u202eDEF\u200bg", 64], ["\U0001F600" * 3, 2], ["x\ud800y", 10], ["\u0103" * 100, 80, 150]],
}
UNIT_WANT = {
    "ipKey": ["203.0.113.7", "2001:db8:1:2::/64", "2001:db8:1:2::/64", "2001:db8:1:3::/64", "10.1.2.3",
              "0:0:0:0::/64", "fe80:0:0:0::/64", ""],
    "clip": ["abcDEFg", "\U0001F600" * 2, "x\ufffdy", "\u0103" * 75],
}


class Harness:
    def __init__(self, signing_key, worker_path):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.jobs = queue.Queue()
        self.waiting = {}
        self.next_id = 0
        self.key = signing_key
        self.worker_path = worker_path
        self.last_poll = 0.0
        self.unit = None

    def sql(self, body):
        with self.lock:
            cur = self.db.execute(body["sql"], body.get("params") or [])
            if body["mode"] == "first":
                row = cur.fetchone()
                return {"row": dict(row) if row else None}
            if body["mode"] == "all":
                return {"results": [dict(r) for r in cur.fetchall()]}
            self.db.commit()
            return {"meta": {"changes": cur.rowcount, "last_row_id": cur.lastrowid}}

    def query(self, sql, *params):
        with self.lock:
            rows = [dict(r) for r in self.db.execute(sql, params).fetchall()]
            self.db.commit()
            return rows

    def relay(self, job, timeout=60):
        with self.lock:
            self.next_id += 1
            job["id"] = self.next_id
            ev = threading.Event()
            self.waiting[job["id"]] = [ev, None]
        self.jobs.put(job)
        if not ev.wait(timeout):
            return {"status": 504, "headers": {"content-type": "text/plain"}, "body": "browserul nu a raspuns"}
        return self.waiting.pop(job["id"])[1]


def make_handler(h: Harness):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, status, body, ctype="application/json; charset=utf-8", headers=None):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            hdr = {"content-type": ctype, "cache-control": "no-store"}
            hdr.update({k.lower(): v for k, v in (headers or {}).items() if k.lower() not in ("content-length", "content-encoding")})
            for k, v in hdr.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def handle_any(self, method):
            p = self.path
            if p == "/favicon.ico":
                return self.send(404, b"", "text/plain")
            if p == "/__harness":
                return self.send(200, PAGE, "text/html; charset=utf-8")
            if p == "/__worker.js":
                return self.send(200, h.worker_path.read_text(encoding="utf-8"), "text/javascript; charset=utf-8")
            if p == "/__config":
                return self.send(200, json.dumps({"signing_key": json.dumps(h.key), "admin": ADMIN, "unit": UNIT}))
            if p == "/__unit":
                h.unit = json.loads(self.body())
                return self.send(200, "{}")
            if p == "/__sql":
                try:
                    return self.send(200, json.dumps(h.sql(json.loads(self.body()))))
                except sqlite3.Error as e:
                    return self.send(200, json.dumps({"error": f"SQLite: {e}"}))
            if p == "/__relay/next":
                h.last_poll = time.time()
                try:
                    job = h.jobs.get(timeout=15)
                except queue.Empty:
                    return self.send(204, b"")
                return self.send(200, json.dumps(job))
            if p == "/__relay/done":
                out = json.loads(self.body())
                with h.lock:
                    w = h.waiting.get(out["id"])
                    if w:
                        w[1] = out
                        w[0].set()
                return self.send(200, "{}")
            # orice altceva ajunge la worker.js (prin browser). Ca pe Cloudflare: CF-Connecting-IP e pus de
            # "retea" (aici: X-Test-Ip sau adresa clientului), iar antetele trimise de client trec mai departe.
            headers = {k: v for k, v in self.headers.items() if k.lower() not in SKIP_HEADERS}
            headers["cf-connecting-ip"] = self.headers.get("X-Test-Ip") or self.client_address[0]
            res = h.relay({"method": method, "path": p, "headers": headers,
                           "body": self.body().decode("utf-8", "replace")})
            hdr = res.get("headers") or {}
            return self.send(res["status"], res["body"], hdr.get("content-type") or "text/plain", hdr)

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")

        def do_OPTIONS(self):
            self.handle_any("OPTIONS")

        def do_PUT(self):
            self.handle_any("PUT")
    return H


# ---------------------------------------------------------------- scenariul
class Scenario:
    def __init__(self, base, exe, key, harness):
        self.base, self.exe, self.key, self.h = base, exe, key, harness
        self.pub, self.kid = licenta.public_hex(key), key.get("kid", "k1")
        self.tmp = tempfile.mkdtemp(prefix="tklic_")
        self.ok = 0

    def check(self, cond, what):
        if not cond:
            raise AssertionError(what)
        self.ok += 1

    def call(self, path, body=None, token=ADMIN, ip=None, method=None, raw=None, headers=None):
        """-> (status, json sau text, antete)"""
        data = raw if raw is not None else json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method or ("POST" if data is not None else "GET"))
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        if ip:
            req.add_header("X-Test-Ip", ip)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw_out, st, hdr = r.read().decode("utf-8"), r.status, r.headers
        except urllib.error.HTTPError as e:
            raw_out, st, hdr = e.read().decode("utf-8"), e.code, e.headers
        return st, (json.loads(raw_out) if raw_out.startswith("{") else raw_out), {k.lower(): v for k, v in hdr.items()}

    def api(self, path, body=None, token=ADMIN, ip=None, **kw):
        st, r, _ = self.call(path, body, token, ip, **kw)
        return st, r

    def parallel(self, calls):
        with concurrent.futures.ThreadPoolExecutor(len(calls)) as ex:
            return list(ex.map(lambda c: self.api(*c[0], **c[1]), calls))

    def exe_run(self, folder, *args):
        env = dict(os.environ, TOPOKIT_LICDIR=folder, TOPOKIT_LICSERVER=self.base)
        r = subprocess.run([self.exe, *args], capture_output=True, env=env, timeout=60)
        return r.returncode, r.stdout.decode("utf-8", "replace").strip()

    def folder(self, name):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        return d

    def lic_text(self, folder):
        p = os.path.join(folder, "license.lic")
        return open(p, encoding="ascii").read() if os.path.exists(p) else None

    def state(self):
        st, s = self.api("/api/admin/state")
        self.check(st == 200, f"stare admin {st}")
        return s

    def user(self, name, max_devices=1):
        st, u = self.api("/api/admin/users", {"name": name, "max_devices": max_devices})
        self.check(st == 200 and u["code"].startswith("TKIT-"), f"coleg nou {st} {u}")
        return u

    def new_code(self, uid):
        st, c = self.api(f"/api/admin/users/{uid}/code", {})
        self.check(st == 200, f"cod nou {st} {c}")
        return c["code"]

    def activate(self, code, machine, ip="192.0.2.1", pc="PC", version="1.9.0"):
        return self.api("/api/activate", {"code": code, "machine": machine, "pc": pc, "version": version}, token=None, ip=ip)

    def active(self, uid):
        return [d for x in self.state()["users"] if x["id"] == uid for d in x["devices"] if not d["revoked"]]

    def run(self):
        self.unit()
        self.basics()
        if self.exe:
            self.with_launcher()
        self.races()
        self.rate_limits()
        self.bad_requests()
        self.license_and_lifecycle()
        self.headers_and_admin_page()
        self.pruning_and_clone()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------ functii mici
    def unit(self):
        t0 = time.time()
        while self.h.unit is None and time.time() - t0 < 30:
            time.sleep(0.2)
        self.check(self.h.unit is not None, "rezultatele testelor de unitate lipsesc")
        for k, want in UNIT_WANT.items():
            self.check(self.h.unit[k] == want, f"{k}: {self.h.unit[k]} != {want}")
        print("ipKey (IPv4, IPv6 /64, IPv4 in IPv6) si clip (caractere de control/directie, surogate, octeti)")

    # ------------------------------------------------------------ server
    def basics(self):
        st, r = self.api("/api/ping", token=None)
        self.check(st == 200 and r["ok"], f"ping {st} {r}")
        st, r = self.api("/api/admin/state", token="gresit")
        self.check(st == 401, f"parola admin gresita -> {st}")
        st, r = self.api("/admin", token=None)
        self.check(st == 200 and "TopoKit – licențe" in r, "pagina /admin")
        print("server: ping, parola admin, pagina /admin")

    # ------------------------------------------------------------ scenariul cu TopoKit.exe
    def with_launcher(self):
        name = 'Ion Popescu ăîșț "test"'
        u = self.user(name, 1)
        self.check(len(u["code"]) == 22, f"format cod {u}")
        a = self.folder("a")
        code, out = self.exe_run(a, "/activate", u["code"].lower().replace("-", " "))
        self.check(code == 0, f"activare {code} {out}")
        code, out = self.exe_run(a, "/license")
        self.check(code == 0 and name in out, f"/license dupa activare {code} {out}")
        self.check(os.path.exists(os.path.join(a, "state.dat")), "state.dat lipseste")
        stat, p = licenta.license_status(self.lic_text(a), self.pub, self.kid, licenta.machine_id())
        self.check(stat == "ok" and p["name"] == name and p["exp"] - p["iat"] == 14 * 86400, f"licenta (Python/CNG) {stat} {p}")
        dev = self.active(u["user_id"])
        self.check(len(dev) == 1 and dev[0]["version"] and dev[0]["machine"] == licenta.machine_id(), f"dispozitiv {dev}")
        print("activare cu TopoKit.exe: licenta semnata in browser (WebCrypto), verificata in C si in Python")

        code, out = self.exe_run(self.folder("b"), "/activate", u["code"])
        self.check(code == 2 and ("folosit" in out or "used" in out), f"cod refolosit {code} {out}")
        c2 = self.new_code(u["user_id"])
        st, r = self.activate(c2, "A" * 24, ip=None)
        self.check(st == 403 and r["error"] == "too_many_devices", f"prea multe calculatoare {st} {r}")
        old = a
        a = self.folder("a2")                       # reinstalare pe acelasi calculator: acelasi loc
        code, out = self.exe_run(a, "/activate", c2)
        self.check(code == 0, f"reactivare acelasi calculator {code} {out}")
        code, out = self.exe_run(old, "/refresh")
        self.check(code == 2 and self.lic_text(old) is None, f"activarea veche oprita {code} {out}")
        print("cod refolosit refuzat; limita de calculatoare; reinstalarea inlocuieste activarea veche")

        before = self.lic_text(a)
        time.sleep(1.1)
        code, out = self.exe_run(a, "/refresh")
        self.check(code == 0 and self.lic_text(a) != before, f"reinnoire {code} {out}")
        self.api(f"/api/admin/users/{u['user_id']}/disable", {})
        code, out = self.exe_run(a, "/refresh")
        self.check(code == 2 and self.lic_text(a) is None, f"acces oprit -> licenta stearsa {code} {out}")
        code, out = self.exe_run(a, "/license")
        self.check(code == 10, f"/license dupa oprire {code} {out}")
        self.api(f"/api/admin/users/{u['user_id']}/enable", {})
        print("reinnoire; acces oprit de administrator -> licenta dispare la urmatoarea verificare")

        c3 = self.new_code(u["user_id"])
        a = self.folder("a3")
        self.check(self.exe_run(a, "/activate", c3)[0] == 0, "activare dupa repornire")
        devid = self.active(u["user_id"])[0]["id"]
        self.api(f"/api/admin/devices/{devid}/revoke", {})
        code, out = self.exe_run(a, "/refresh")
        self.check(code == 2 and self.lic_text(a) is None, f"calculator scos {code} {out}")
        c4 = self.new_code(u["user_id"])
        a = self.folder("a4")
        self.check(self.exe_run(a, "/activate", c4)[0] == 0, "activare 4")
        code, out = self.exe_run(a, "/deactivate")
        self.check(code == 0 and self.lic_text(a) is None and not os.path.exists(os.path.join(a, "state.dat")), f"dezactivare {code} {out}")
        self.check(not self.active(u["user_id"]), "toate activarile oprite")

        long_name = "Ăă" * 40                       # 80 de caractere, 160 de octeti UTF-8
        u2 = self.user(long_name, 1)
        a = self.folder("a5")
        self.check(self.exe_run(a, "/activate", u2["code"])[0] == 0, "activare cu nume lung")
        code, out = self.exe_run(a, "/license")
        self.check(code == 0 and "Ăă" * 37 in out, f"nume lung afisat de TopoKit.exe {code} {out}")
        self.exe_run(a, "/deactivate")
        print("calculator scos din pagina de administrare; dezactivare din TopoKit (locul se elibereaza);")
        print("  nume lung (diacritice) taiat la 150 de octeti, cat incape in TopoKit.exe")

    # ------------------------------------------------------------ curse (cereri simultane)
    def races(self):
        u = self.user("Cursa Unu", 3)
        res = self.parallel([(("/api/activate", {"code": u["code"], "machine": f"{i:024X}", "pc": "P"}),
                              {"token": None, "ip": "198.51.100.1"}) for i in range(1, 6)])
        ok = [r for st, r in res if st == 200]
        self.check(len(ok) == 1 and all(r["error"] == "code_used" for st, r in res if st != 200),
                   f"acelasi cod, 5 activari simultane: {res}")
        self.check(len(self.active(u["user_id"])) == 1, "un singur calculator dupa cursa")

        u = self.user("Cursa Doi", 1)
        codes = [u["code"]] + [self.new_code(u["user_id"]) for _ in range(3)]
        res = self.parallel([(("/api/activate", {"code": c, "machine": f"{0xC0 + i:024X}", "pc": "P"}),
                              {"token": None, "ip": "198.51.100.2"}) for i, c in enumerate(codes)])
        ok = [r for st, r in res if st == 200]
        self.check(len(ok) == 1 and all(r["error"] == "too_many_devices" for st, r in res if st != 200),
                   f"coduri diferite, max 1 calculator, 4 activari simultane: {res}")
        self.check(len(self.active(u["user_id"])) == 1, f"limita de calculatoare depasita: {self.active(u['user_id'])}")
        st_u = [x for x in self.state()["users"] if x["id"] == u["user_id"]][0]
        self.check(st_u["open_codes"] == 3, f"codurile refuzate raman valabile: {st_u['open_codes']}")

        u = self.user("Cursa Trei", 1)
        codes = [u["code"]] + [self.new_code(u["user_id"]) for _ in range(3)]
        res = self.parallel([(("/api/activate", {"code": c, "machine": "D" * 24, "pc": "P"}),
                              {"token": None, "ip": "198.51.100.3"}) for c in codes])
        self.check(all(st == 200 for st, _ in res), f"reactivari simultane pe acelasi calculator: {res}")
        act = self.active(u["user_id"])
        self.check(len(act) == 1, f"acelasi calculator, reactivari simultane -> o activare: {act}")
        survivor = [r for _, r in res if r["device"] == act[0]["id"]][0]
        st, r = self.api("/api/refresh", {"device": survivor["device"], "secret": survivor["secret"], "machine": "D" * 24},
                         token=None, ip="198.51.100.3")
        self.check(st == 200, f"activarea ramasa merge {st} {r}")

        # ordinea activarilor e (created_at, id), nu rowid: o activare veche din aceeasi secunda, cu id
        # "mai mare" decat orice id nou, nu ramane in locul celei noi (created_at nou = vechi + 1)
        u = self.user("Cursa Patru", 1)
        m = "E" * 24
        st, first = self.activate(u["code"], m, ip="198.51.100.4")
        self.check(st == 200, f"prima activare {st} {first}")
        self.h.query("UPDATE devices SET revoked = 1 WHERE id = ?", first["device"])
        old = self.h.query("SELECT * FROM devices WHERE id = ?", first["device"])[0]
        t = int(time.time()) + 5                                   # "aceeasi secunda" cu activarea noua
        self.h.query("INSERT INTO devices (id, user_id, machine, pc, secret_hash, version, created_at, last_seen) "
                     "VALUES ('d_ffffffffffffffff', ?, ?, 'P', ?, '1.9.0', ?, ?)", u["user_id"], m, old["secret_hash"], t, t)
        st, r = self.activate(self.new_code(u["user_id"]), m, ip="198.51.100.4")
        self.check(st == 200, f"reactivare in aceeasi secunda {st} {r}")
        act = self.active(u["user_id"])
        self.check([d["id"] for d in act] == [r["device"]], f"ramane activarea noua, nu cea cu id/rowid mai mare: {act}")
        row = self.h.query("SELECT created_at FROM devices WHERE id = ?", r["device"])[0]
        self.check(row["created_at"] == t + 1, f"created_at dupa activarea veche: {row} {t}")
        print("curse: acelasi cod de 5 ori simultan -> 1 activare; coduri diferite simultan nu depasesc limita")
        print("  (codurile refuzate raman nefolosite); reactivari simultane pe acelasi calculator -> 1 activare;")
        print("  reactivare in aceeasi secunda -> ramane cea noua (ordinea created_at, id; fara rowid)")

    # ------------------------------------------------------------ limitarea incercarilor
    def rate_limits(self):
        bad = {"code": "TKIT-AAAAA-AAAAA-AAAAA", "machine": "B" * 24}
        for i in range(20):
            st, r = self.api("/api/activate", bad, token=None, ip="10.0.0.9")
            self.check(st == 403 and r["error"] == "code_invalid", f"cod gresit {i} {st} {r}")
        st, r = self.api("/api/activate", bad, token=None, ip="10.0.0.9")
        self.check(st == 429 and r["error"] == "rate_limited", f"limita incercari {st} {r}")
        for hdr in ({"X-Forwarded-For": "1.2.3.4"}, {"X-Real-IP": "1.2.3.5"}, {"True-Client-IP": "1.2.3.6"},
                    {"CF-Connecting-IP": "1.2.3.7"}, {"Forwarded": "for=1.2.3.8"}):
            st, r = self.api("/api/activate", bad, token=None, ip="10.0.0.9", headers=hdr)
            self.check(st == 429, f"antet falsificat {hdr} ocoleste limita: {st} {r}")
        st, r = self.api("/api/activate", bad, token=None, ip="10.0.0.10")
        self.check(st == 403 and r["error"] == "code_invalid", f"alt IP nu e blocat {st} {r}")
        for i in range(20):                          # IPv6: alta adresa la fiecare incercare, aceeasi retea /64
            st, r = self.api("/api/activate", bad, token=None, ip=f"2001:db8:aa:bb::{i + 1:x}")
            self.check(st == 403, f"IPv6 {i} {st} {r}")
        st, r = self.api("/api/activate", bad, token=None, ip="2001:db8:aa:bb:1234:5678:9abc:def0")
        self.check(st == 429, f"IPv6 /64 rotit ocoleste limita {st} {r}")
        st, r = self.api("/api/activate", bad, token=None, ip="2001:db8:aa:bc::1")
        self.check(st == 403, f"alt /64 nu e blocat {st} {r}")
        # pagina de administrare: 10 parole gresite pe ora, apoi nici parola buna nu mai intra (de la acel IP)
        for i in range(10):
            st, _ = self.api("/api/admin/state", token=f"ghicit{i}", ip="10.0.0.20")
            self.check(st == 401, f"admin gresit {i} {st}")
        st, r = self.api("/api/admin/state", token=ADMIN, ip="10.0.0.20")
        self.check(st == 429, f"limita admin {st} {r}")
        st, r = self.api("/api/admin/state", token=ADMIN, ip="10.0.0.20", headers={"X-Forwarded-For": "9.9.9.9"})
        self.check(st == 429, f"limita admin ocolita cu X-Forwarded-For {st}")
        st, _ = self.api("/api/admin/state", token=ADMIN, ip="10.0.0.21")
        self.check(st == 200, f"admin de la alt IP {st}")
        st, _ = self.api("/api/admin/state", token=None, ip="10.0.0.22")
        self.check(st == 401, f"admin fara antet {st}")
        st, _ = self.api("/api/admin/state", token=ADMIN + "x", ip="10.0.0.22")
        self.check(st == 401, f"admin cu parola + un caracter {st}")
        st, _ = self.api("/api/admin/state", token=ADMIN[:-1], ip="10.0.0.22")
        self.check(st == 401, f"admin cu parola fara un caracter {st}")
        print("limita de 20 de coduri gresite pe ora / IP (nu se ocoleste cu X-Forwarded-For & co. si nici cu")
        print("  adrese IPv6 diferite din acelasi /64); 10 parole admin gresite pe ora")

    # ------------------------------------------------------------ cereri stricate
    def bad_requests(self):
        ip = "10.0.1.1"
        cases = [
            ("json stricat", "/api/activate", b"{nu e json", 400, "bad_request"),
            ("lista", "/api/activate", b"[1,2]", 400, "bad_request"),
            ("null", "/api/refresh", b"null", 400, "bad_request"),
            ("prea mare", "/api/activate", json.dumps({"code": "x", "machine": "A" * 24, "pc": "p" * 9000}).encode(), 400, "bad_request"),
            ("masina gresita", "/api/activate", json.dumps({"code": "x", "machine": "nu"}).encode(), 400, "bad_request"),
            ("masina numar", "/api/activate", json.dumps({"code": "x", "machine": 123}).encode(), 400, "bad_request"),
            ("cod obiect", "/api/activate", json.dumps({"code": {"a": 1}, "machine": "A" * 24}).encode(), 403, "code_invalid"),
            ("cod numar", "/api/activate", json.dumps({"code": 123456789012345, "machine": "A" * 24}).encode(), 403, "code_invalid"),
            ("dispozitiv necunoscut", "/api/refresh", json.dumps({"device": "d_0000000000000000", "secret": "x", "machine": "A" * 24}).encode(), 403, "unknown_device"),
            ("dispozitiv obiect", "/api/refresh", json.dumps({"device": {"x": 1}, "secret": "x"}).encode(), 403, "unknown_device"),
            ("secret lipsa", "/api/deactivate", json.dumps({"device": "d_0000000000000000"}).encode(), 403, "unknown_device"),
            ("id SQL", "/api/refresh", json.dumps({"device": "d_' OR '1'='1", "secret": "x"}).encode(), 403, "unknown_device"),
        ]
        for what, path, raw, want_st, want_err in cases:
            st, r = self.api(path, token=None, ip=ip, raw=raw)
            self.check(st == want_st and isinstance(r, dict) and r.get("error") == want_err and len(r) == 1,
                       f"{what}: {st} {r}")
        for method, path in (("GET", "/api/activate"), ("OPTIONS", "/api/activate"), ("PUT", "/api/refresh"),
                             ("GET", "/api/nimic"), ("GET", "/nimic"), ("POST", "/api/admin/users/abc/code"),
                             ("GET", "/api/admin/users")):
            st, r = self.api(path, token=ADMIN, method=method, raw=b"{}" if method != "GET" else None)
            self.check(st == 404 and r == {"error": "not_found"}, f"{method} {path}: {st} {r}")
        st, r = self.api("/api/admin/users", {"name": "   "})
        self.check(st == 400 and r["error"] == "name_required", f"nume gol {st} {r}")
        st, r = self.api("/api/admin/users/999999/code", {})
        self.check(st == 404, f"coleg inexistent {st} {r}")
        st, r = self.api("/api/admin/devices/d_0000000000000000/revoke", {})
        self.check(st == 404, f"calculator inexistent {st} {r}")
        st, r = self.api("/api/admin/users", raw=b"{stricat")
        self.check(st == 400, f"admin json stricat {st} {r}")
        print("cereri stricate (JSON, tipuri, marime, metode, rute) -> erori scurte, fara detalii interne")

    # ------------------------------------------------------------ licenta si ciclul de viata (fara TopoKit.exe)
    def license_and_lifecycle(self):
        ip = "10.0.2.1"
        u = self.user('Ana <img src=x onerror=alert(1)> \u202eevil', 2)
        m1, m2, m3 = "E1" * 12, "E2" * 12, "E3" * 12
        t0 = int(time.time())
        st, a = self.activate(u["code"].replace("-", "").lower(), m1.lower(), ip=ip, pc="<b>PC</b>\u0000", version="1.9.0")
        self.check(st == 200 and set(a) == {"license", "device", "secret"}, f"activare API {st} {a}")
        p, why = licenta.read_license(a["license"], self.pub, self.kid)
        self.check(why is None, f"semnatura licentei {why}")
        self.check(set(p) == {"v", "kid", "typ", "lid", "uid", "name", "machine", "features", "iat", "exp"}, f"campuri {p}")
        self.check(p["v"] == 1 and p["kid"] == self.kid and p["typ"] == "internal" and p["lid"] == a["device"]
                   and p["uid"] == u["user_id"] and p["machine"] == m1 and p["features"] == ["all"], f"licenta {p}")
        self.check(abs(p["iat"] - t0) <= 5 and p["exp"] - p["iat"] == 14 * 86400, f"iat/exp {p}")
        self.check("\u202e" not in p["name"] and p["name"].startswith("Ana <img"), f"nume curatat {p['name']!r}")
        dev = self.active(u["user_id"])[0]
        self.check(dev["pc"] == "<b>PC</b>" and dev["machine"] == m1, f"pc / machine salvate {dev}")
        auth = {"device": a["device"], "secret": a["secret"]}
        st, r = self.api("/api/refresh", {**auth, "machine": m2}, token=None, ip=ip)
        self.check(st == 403 and r["error"] == "machine", f"reinnoire de pe alt calculator {st} {r}")
        wrong = a["secret"][:-1] + ("B" if a["secret"].endswith("A") else "A")
        st, r = self.api("/api/refresh", {**auth, "secret": wrong, "machine": m1}, token=None, ip=ip)
        self.check(st == 403 and r["error"] == "unknown_device", f"secret gresit {st} {r}")
        st, r = self.api("/api/refresh", {**auth, "machine": m1, "version": "1.9.0"}, token=None, ip=ip)
        self.check(st == 200 and licenta.read_license(r["license"], self.pub, self.kid)[1] is None, f"reinnoire {st} {r}")
        st, r = self.api("/api/refresh", {**auth, "machine": m1}, token=None, ip=ip)      # repetata: aceeasi licenta, nimic mai mult
        self.check(st == 200, f"reinnoire repetata {st}")

        st, b = self.activate(self.new_code(u["user_id"]), m2, ip=ip)
        self.check(st == 200, f"al doilea calculator {st} {b}")
        st, r = self.activate(self.new_code(u["user_id"]), m3, ip=ip)
        self.check(st == 403 and r["error"] == "too_many_devices", f"al treilea calculator {st} {r}")
        self.api(f"/api/admin/users/{u['user_id']}/max", {"max_devices": 1})
        st, r = self.api("/api/refresh", {**auth, "machine": m1}, token=None, ip=ip)
        self.check(st == 200, f"scaderea limitei nu opreste calculatoarele existente {st} {r}")
        st, r = self.activate(self.new_code(u["user_id"]), m1, ip=ip)
        self.check(st == 200, f"reinstalare pe acelasi calculator peste limita {st} {r}")
        st, r = self.api("/api/refresh", {**auth, "machine": m1}, token=None, ip=ip)
        self.check(st == 403 and r["error"] == "revoked", f"activarea veche e oprita {st} {r}")
        st, r = self.api("/api/admin/users/{}/max".format(u["user_id"]), {"max_devices": 0})
        self.check(st == 200 and [x for x in self.state()["users"] if x["id"] == u["user_id"]][0]["max_devices"] == 1,
                   "max 0 ignorat")
        self.api(f"/api/admin/users/{u['user_id']}/max", {"max_devices": 99})
        self.check([x for x in self.state()["users"] if x["id"] == u["user_id"]][0]["max_devices"] == 10, "max plafonat la 10")

        auth_b = {"device": b["device"], "secret": b["secret"]}
        self.api(f"/api/admin/users/{u['user_id']}/disable", {})
        st, r = self.api("/api/refresh", {**auth_b, "machine": m2}, token=None, ip=ip)
        self.check(st == 403 and r["error"] == "user_disabled", f"reinnoire cu acces oprit {st} {r}")
        st, r = self.activate(self.new_code(u["user_id"]), m3, ip=ip)
        self.check(st == 403 and r["error"] == "user_disabled", f"activare cu acces oprit {st} {r}")
        self.api(f"/api/admin/users/{u['user_id']}/enable", {})
        st, r = self.api("/api/deactivate", {**auth_b, "secret": "gresit"}, token=None, ip=ip)
        self.check(st == 403 and r["error"] == "unknown_device", f"dezactivare cu secret gresit {st} {r}")
        st, r = self.api("/api/deactivate", auth_b, token=None, ip=ip)
        self.check(st == 200 and r == {"ok": True}, f"dezactivare {st} {r}")
        st, r = self.api("/api/deactivate", auth_b, token=None, ip=ip)
        self.check(st == 200, f"dezactivare repetata {st} {r}")
        st, r = self.api("/api/refresh", {**auth_b, "machine": m2}, token=None, ip=ip)
        self.check(st == 403 and r["error"] == "revoked", f"reinnoire dupa dezactivare {st} {r}")

        u3 = self.user("Cod Expirat", 1)
        self.h.query("UPDATE codes SET expires_at = ? WHERE user_id = ?", int(time.time()) - 1, u3["user_id"])
        st, r = self.activate(u3["code"], m3, ip=ip)
        self.check(st == 403 and r["error"] == "code_expired", f"cod expirat {st} {r}")
        print("licenta: campuri, semnatura, 14 zile; reinnoire (alt calculator / secret gresit / oprit / scos);")
        print("  limita schimbata din /admin; dezactivare (si repetata); cod expirat")

    # ------------------------------------------------------------ antete, pagina /admin
    def headers_and_admin_page(self):
        st, page, hdr = self.call("/admin", token=None)
        csp = hdr.get("content-security-policy", "")
        nonce = csp.split("'nonce-")[1].split("'")[0] if "'nonce-" in csp else ""
        script_src = csp.split("script-src")[1].split(";")[0] if "script-src" in csp else ""
        self.check(st == 200 and len(nonce) >= 16 and f'<script nonce="{nonce}">' in page and
                   script_src.strip() == f"'nonce-{nonce}'", f"CSP cu nonce {csp}")
        self.check(page.count("<script") == 1, "un singur script in /admin")
        self.check(hdr.get("x-frame-options") == "DENY" and "frame-ancestors 'none'" in csp and
                   hdr.get("x-content-type-options") == "nosniff", f"antete /admin {hdr}")
        _, page2, hdr2 = self.call("/admin", token=None)
        self.check(hdr2.get("content-security-policy") != csp, "nonce nou la fiecare cerere")
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.check(bad not in page, f"/admin foloseste {bad}")
        for path, body, token in (("/api/ping", None, None), ("/api/activate", {"code": "x", "machine": "nu"}, None),
                                  ("/api/admin/state", None, ADMIN)):
            st, r, hdr = self.call(path, body, token=token, headers={"Origin": "https://rau.example"})
            self.check(not any(k.startswith("access-control-") for k in hdr), f"CORS deschis pe {path}: {hdr}")
            self.check(hdr.get("cache-control") == "no-store" and hdr.get("x-content-type-options") == "nosniff",
                       f"antete {path} {hdr}")
        st, s = self.api("/api/admin/state")
        flat = json.dumps(s)
        self.check("secret_hash" not in flat and '"hash"' not in flat, "starea admin nu contine hash-uri")
        print("antete: CSP cu nonce pe /admin, fara CORS, no-store, nosniff; /admin doar cu textContent")

    # ------------------------------------------------------------ jurnal, posibila copiere
    def pruning_and_clone(self):
        old = int(time.time()) - 200 * 86400
        self.h.query("INSERT INTO events (at, kind, ip) VALUES (?, 'vechi', '1.1.1.1')", old)
        self.h.query("INSERT INTO codes (hash, user_id, created_at, expires_at) VALUES ('vechi', 1, ?, ?)", old, old + 10)
        u = self.user("Copiere", 1)
        m = "F0" * 12
        st, a = self.activate(u["code"], m, ip="203.0.113.1")
        self.check(st == 200, f"activare {st} {a}")
        self.check(not self.h.query("SELECT 1 FROM events WHERE kind = 'vechi'"), "evenimentele de peste 180 de zile raman")
        self.check(not self.h.query("SELECT 1 FROM codes WHERE hash = 'vechi'"), "codurile expirate de peste 180 de zile raman")
        auth = {"device": a["device"], "secret": a["secret"], "machine": m}
        st, _ = self.api("/api/refresh", auth, token=None, ip="203.0.113.1")
        self.check(st == 200, "reinnoire de la acelasi IP")
        st, _ = self.api("/api/refresh", auth, token=None, ip="198.51.100.77")
        self.check(st == 200, "reinnoire de la alt IP (copia merge, dar se vede)")
        ev = [e for e in self.state()["events"] if e["kind"] == "clone_suspect" and e["device_id"] == a["device"]]
        self.check(len(ev) == 1 and "203.0.113.1" in ev[0]["detail"], f"posibila copiere in jurnal {ev}")
        st, _ = self.api("/api/refresh", auth, token=None, ip="2001:db8:5:6::1")
        st, _ = self.api("/api/refresh", auth, token=None, ip="2001:db8:5:6::2")    # acelasi /64: nu e alt loc
        ev = [e for e in self.state()["events"] if e["kind"] == "clone_suspect" and e["device_id"] == a["device"]]
        self.check(len(ev) == 2, f"IPv6 din acelasi /64 nu e copiere {ev}")
        kinds = {e["kind"] for e in self.h.query("SELECT DISTINCT kind FROM events")}
        self.check({"activate", "activate_fail", "user_disable", "deactivate", "user_max", "clone_suspect", "admin_fail"} <= kinds,
                   f"evenimente {kinds}")
        fails = self.h.query("SELECT ip FROM events WHERE kind IN ('activate_fail', 'admin_fail') AND ip LIKE '%:%'")
        self.check(fails and all(e["ip"].endswith("::/64") for e in fails), f"IPv6 in jurnal ca /64 {fails[:2]}")
        print("jurnal: evenimentele si codurile expirate de peste 180 de zile se sterg; reinnoiri din retele")
        print("  diferite la mai putin de 6 ore -> 'posibila copiere' in jurnal")


# ---------------------------------------------------------------- lansator si browser
def build_launcher(tmp, key, src=None):
    """TopoKit.exe cu cheia de test; -DTK_LIC_TESTENV: TOPOKIT_LICDIR / TOPOKIT_LICSERVER (si http://) functioneaza.
    src: alt folder cu sursele lansatorului (de ex. o copie a versiunii 1.9.0, pentru compatibilitate)."""
    gcc, windres = shutil.which("gcc"), shutil.which("windres")
    if os.name != "nt" or not gcc or not windres:
        return None
    ld = pathlib.Path(tmp) / "src"                # copie: cale scurta si o versiune fixa a surselor
    shutil.copytree(pathlib.Path(src) if src else ROOT / "installer" / "launcher", ld)
    res = pathlib.Path(tmp) / "res.o"
    subprocess.run([windres, "-DTK_VER_COMMA=9,9,9,0", '-DTK_VER_STR=\\"9.9.9\\"', "topokit.rc", "-O", "coff", "-o", str(res)],
                   cwd=ld, check=True)
    exe = pathlib.Path(tmp) / "TopoKit_test.exe"
    libs = ["-lgdiplus", "-lshlwapi", "-lole32", "-loleaut32", "-luuid", "-lshell32", "-lgdi32", "-luser32",
            "-lbcrypt", "-lwinhttp", "-lcrypt32", "-lcomdlg32"]
    r = subprocess.run([gcc, "-municode", "-mwindows", "-O1", "-static", '-DTK_VERSION="9.9.9"',
                        f'-DTK_LIC_PUB="{licenta.public_hex(key)}"', f'-DTK_LIC_KID="{key.get("kid", "k1")}"',
                        '-DTK_LIC_URL="https://licente.invalid"', "-DTK_LIC_TESTENV", "-o", str(exe), "topokit.c", "ui.c", "license.c", str(res), *libs],
                       cwd=ld, capture_output=True, text=True)
    if r.returncode:
        sys.exit("compilarea TopoKit.exe a esuat:\n" + r.stdout + r.stderr)
    return str(exe)


def find_browser():
    # Chrome sau Edge (TK_BROWSER = alt browser Chromium)
    for p in (os.environ.get("TK_BROWSER"), shutil.which("chrome"), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("msedge"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if p and os.path.exists(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--launcher", help="TopoKit.exe compilat cu cheia publica de test (implicit: se compileaza aici)")
    ap.add_argument("--key", help="cheia de test (JWK); implicit: una noua")
    ap.add_argument("--launcher-src", help="folderul cu sursele lansatorului (implicit installer/launcher)")
    ap.add_argument("--worker", default=str(ROOT / "server" / "worker.js"))
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--browser", default="auto", help="auto (Edge/Chrome headless), none (deschideti voi pagina) sau calea")
    ap.add_argument("--api-only", action="store_true", help="fara TopoKit.exe")
    ap.add_argument("--serve", action="store_true", help="doar serverul (pentru a vedea /admin), fara scenariu")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="tkharness_")
    key = json.loads(pathlib.Path(a.key).read_text(encoding="utf-8")) if a.key else licenta.gen_key("hk")
    exe = None
    if not a.api_only and not a.serve:
        exe = a.launcher or build_launcher(tmp, key, a.launcher_src)
        if not exe:
            print("fara gcc/windres: doar testele API (--launcher pentru TopoKit.exe)")
    h = Harness(key, pathlib.Path(a.worker))
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(h))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{a.port}"
    proc, prof = None, os.path.join(tmp, "profil")
    browser = find_browser() if a.browser == "auto" else None if a.browser == "none" else a.browser
    if browser:
        proc = subprocess.Popen([browser, "--headless=new", f"--user-data-dir={prof}", "--no-first-run",
                                 "--no-default-browser-check", "--disable-extensions", "--disable-gpu",
                                 f"{base}/__harness"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"browser headless: {browser}", flush=True)
    else:
        print(f"Deschideti {base}/__harness in browser...", flush=True)
    code = 0
    try:
        t0 = time.time()
        while time.time() - h.last_poll > 2:
            if time.time() - t0 > (60 if proc else 600):
                sys.exit("browserul nu s-a conectat")
            time.sleep(0.5)
        print("browser conectat", flush=True)
        if a.serve:
            while True:
                time.sleep(3600)
        sc = Scenario(base, exe, key, h)
        try:
            sc.run()
            print(f"Toate cele {sc.ok} verificari ale serverului de licente au trecut.", flush=True)
        except AssertionError as e:
            print(f"ESEC dupa {sc.ok} verificari: {e}", flush=True)
            code = 1
    finally:
        if proc:
            proc.kill()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                pass
            if os.name == "nt":                   # browserul poate porni procese care nu mai sunt copiii lui
                subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
                                f"$_.CommandLine.Contains('{prof}') }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"],
                               capture_output=True, timeout=60)
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
