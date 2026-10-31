#!/usr/bin/env python3
"""Test complet al serverului de licente: TopoKit.exe <-> server/worker.js <-> SQLite.

    python tests/server_harness.py --launcher C:\\cale\\TopoKit.exe --key cheie_test.json [--port 8766]

Nu exista Node.js / wrangler pe calculatorul de dezvoltare, asa ca worker.js ruleaza intr-un
browser (Chromium, cu WebCrypto adevarat): deschideti http://127.0.0.1:PORT/__harness in browserul
din aplicatie. Pagina importa worker.js, ii da o baza D1 falsa care trimite SQL-ul aici (SQLite in
memorie - D1 este SQLite) si preia cererile HTTP primite de acest server (releu). Astfel
TopoKit.exe (compilat cu cheia publica de test) vorbeste prin HTTP cu codul real al serverului.

Dupa ce pagina se conecteaza, scenariul ruleaza singur: activare, cod refolosit, prea multe
calculatoare, reinstalare pe acelasi calculator, reinnoire, acces oprit, calculator scos,
dezactivare, limitarea incercarilor, pagina /admin. Cheia si lansatorul trebuie sa fie aceleasi
(kid si cheia publica). Codul de iesire 0 = toate verificarile au trecut.
"""
import argparse, json, os, pathlib, queue, shutil, sqlite3, subprocess, sys, tempfile, threading, time, urllib.request
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
const DB = { prepare: (sql) => new Stmt(sql), batch: async (st) => { for (const s of st) await s.run(); return st.map(() => ({success: true})); } };
const cfg = await (await fetch("/__config")).json();
const env = { DB, SIGNING_KEY: cfg.signing_key, ADMIN_TOKEN: cfg.admin, LICENSE_DAYS: "14", CODE_DAYS: "14" };
log("pregatit");
for (;;) {
  let r;
  try { r = await fetch("/__relay/next"); } catch (e) { await new Promise((ok) => setTimeout(ok, 1000)); continue; }
  if (r.status !== 200) continue;
  const job = await r.json();
  let out;
  try {
    const req = new Request("https://licente.test" + job.path, {method: job.method, headers: job.headers,
                            body: job.method === "GET" ? undefined : job.body});
    const res = await worker.fetch(req, env);
    out = {id: job.id, status: res.status, type: res.headers.get("content-type") || "", body: await res.text()};
  } catch (e) { out = {id: job.id, status: 599, type: "text/plain", body: String(e && e.stack || e)}; }
  log(job.method + " " + job.path + " -> " + out.status);
  await fetch("/__relay/done", {method: "POST", body: JSON.stringify(out)});
}
</script></body></html>"""


class Harness:
    def __init__(self, signing_key):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.jobs = queue.Queue()
        self.waiting = {}
        self.next_id = 0
        self.key = signing_key
        self.last_poll = 0.0

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

    def relay(self, job, timeout=30):
        with self.lock:
            self.next_id += 1
            job["id"] = self.next_id
            ev = threading.Event()
            self.waiting[job["id"]] = [ev, None]
        self.jobs.put(job)
        if not ev.wait(timeout):
            return {"status": 504, "type": "text/plain", "body": "browserul nu a raspuns"}
        return self.waiting.pop(job["id"])[1]


def make_handler(h: Harness):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, status, body, ctype="application/json; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def handle_any(self, method):
            p = self.path
            if p == "/__harness":
                return self.send(200, PAGE, "text/html; charset=utf-8")
            if p == "/__worker.js":
                return self.send(200, (ROOT / "server" / "worker.js").read_text(encoding="utf-8"), "text/javascript; charset=utf-8")
            if p == "/__config":
                return self.send(200, json.dumps({"signing_key": json.dumps(h.key), "admin": ADMIN}))
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
            # orice altceva ajunge la worker.js (prin browser)
            headers = {k: v for k, v in self.headers.items() if k.lower() in ("authorization", "content-type")}
            headers["cf-connecting-ip"] = self.headers.get("X-Test-Ip") or self.client_address[0]
            res = h.relay({"method": method, "path": p, "headers": headers, "body": self.body().decode("utf-8")})
            return self.send(res["status"], res["body"], res.get("type") or "text/plain")

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")
    return H


# ---------------------------------------------------------------- scenariul
class Scenario:
    def __init__(self, base, exe, key):
        self.base, self.exe, self.key = base, exe, key
        self.pub, self.kid = licenta.public_hex(key), key.get("kid", "k1")
        self.tmp = tempfile.mkdtemp(prefix="tklic_")
        self.ok = 0

    def check(self, cond, what):
        if not cond:
            raise AssertionError(what)
        self.ok += 1

    def api(self, path, body=None, token=ADMIN, ip=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data is not None else "GET")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        if ip:
            req.add_header("X-Test-Ip", ip)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read().decode("utf-8")
                return r.status, (json.loads(raw) if raw.startswith("{") else raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            return e.code, (json.loads(raw) if raw.startswith("{") else raw)

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

    def run(self):
        st, r = self.api("/api/ping", token=None)
        self.check(st == 200 and r["ok"], f"ping {st} {r}")
        st, r = self.api("/api/admin/state", token="gresit")
        self.check(st == 401, f"parola admin gresita -> {st}")
        st, r = self.api("/admin", token=None)
        self.check(st == 200 and "TopoKit – licențe" in r, "pagina /admin")
        print("server: ping, parola admin, pagina /admin")

        name = 'Ion Popescu ăîșț "test"'
        st, u = self.api("/api/admin/users", {"name": name, "max_devices": 1})
        self.check(st == 200 and u["code"].startswith("TKIT-") and len(u["code"]) == 22, f"coleg nou {st} {u}")
        a = self.folder("a")
        code, out = self.exe_run(a, "/activate", u["code"].lower().replace("-", " "))
        self.check(code == 0, f"activare {code} {out}")
        code, out = self.exe_run(a, "/license")
        self.check(code == 0 and name in out, f"/license dupa activare {code} {out}")
        self.check(os.path.exists(os.path.join(a, "state.dat")), "state.dat lipseste")
        stat, p = licenta.license_status(self.lic_text(a), self.pub, self.kid, licenta.machine_id())
        self.check(stat == "ok" and p["name"] == name and p["exp"] - p["iat"] == 14 * 86400, f"licenta (Python/CNG) {stat} {p}")
        s = self.state()
        dev = [d for x in s["users"] for d in x["devices"]]
        self.check(len(dev) == 1 and dev[0]["version"] and dev[0]["machine"] == licenta.machine_id(), f"dispozitiv {dev}")
        print("activare cu TopoKit.exe: licenta semnata in browser (WebCrypto), verificata in C si in Python")

        code, out = self.exe_run(self.folder("b"), "/activate", u["code"])
        self.check(code == 2 and ("folosit" in out or "used" in out), f"cod refolosit {code} {out}")
        st, c2 = self.api(f"/api/admin/users/{u['user_id']}/code", {})
        st, r = self.api("/api/activate", {"code": c2["code"], "machine": "A" * 24, "pc": "ALT", "version": "1.8.0"}, token=None)
        self.check(st == 403 and r["error"] == "too_many_devices", f"prea multe calculatoare {st} {r}")
        old = a
        a = self.folder("a2")                       # reinstalare pe acelasi calculator: acelasi loc
        code, out = self.exe_run(a, "/activate", c2["code"])
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

        st, c3 = self.api(f"/api/admin/users/{u['user_id']}/code", {})
        a = self.folder("a3")
        self.check(self.exe_run(a, "/activate", c3["code"])[0] == 0, "activare dupa repornire")
        devid = [d["id"] for x in self.state()["users"] for d in x["devices"] if not d["revoked"]][0]
        self.api(f"/api/admin/devices/{devid}/revoke", {})
        code, out = self.exe_run(a, "/refresh")
        self.check(code == 2 and self.lic_text(a) is None, f"calculator scos {code} {out}")
        st, c4 = self.api(f"/api/admin/users/{u['user_id']}/code", {})
        a = self.folder("a4")
        self.check(self.exe_run(a, "/activate", c4["code"])[0] == 0, "activare 4")
        code, out = self.exe_run(a, "/deactivate")
        self.check(code == 0 and self.lic_text(a) is None and not os.path.exists(os.path.join(a, "state.dat")), f"dezactivare {code} {out}")
        self.check(all(d["revoked"] for x in self.state()["users"] for d in x["devices"]), "toate activarile oprite")
        print("calculator scos din pagina de administrare; dezactivare din TopoKit (locul se elibereaza)")

        for i in range(20):
            st, r = self.api("/api/activate", {"code": "TKIT-AAAAA-AAAAA-AAAAA", "machine": "B" * 24}, token=None, ip="10.0.0.9")
            self.check(st == 403 and r["error"] == "code_invalid", f"cod gresit {i} {st} {r}")
        st, r = self.api("/api/activate", {"code": "TKIT-AAAAA-AAAAA-AAAAA", "machine": "B" * 24}, token=None, ip="10.0.0.9")
        self.check(st == 429 and r["error"] == "rate_limited", f"limita incercari {st} {r}")
        st, r = self.api("/api/activate", {"code": "x", "machine": "nu"}, token=None)
        self.check(st == 400, f"cerere gresita {st}")
        st, r = self.api("/api/refresh", {"device": "d_0000000000000000", "secret": "x", "machine": "A" * 24}, token=None)
        self.check(st == 403 and r["error"] == "unknown_device", f"dispozitiv necunoscut {st} {r}")
        kinds = {e["kind"] for e in self.state()["events"]}
        self.check({"activate", "activate_fail", "user_disable", "device_revoke", "deactivate"} <= kinds, f"evenimente {kinds}")
        print("limita de 20 de incercari gresite pe ora; cereri gresite; jurnalul de activitate")
        shutil.rmtree(self.tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--launcher", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--serve", action="store_true", help="doar serverul (pentru a vedea /admin), fara scenariu")
    a = ap.parse_args()
    key = json.loads(pathlib.Path(a.key).read_text(encoding="utf-8"))
    h = Harness(key)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(h))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{a.port}"
    print(f"Deschideti {base}/__harness in browser...", flush=True)
    t0 = time.time()
    while time.time() - h.last_poll > 2:
        if time.time() - t0 > 600:
            sys.exit("browserul nu s-a conectat in 10 minute")
        time.sleep(0.5)
    print("browser conectat", flush=True)
    if a.serve:
        while True:
            time.sleep(3600)
    sc = Scenario(base, a.launcher, key)
    try:
        sc.run()
    except AssertionError as e:
        print(f"ESEC dupa {sc.ok} verificari: {e}", flush=True)
        sys.exit(1)
    print(f"Toate cele {sc.ok} verificari ale serverului de licente au trecut.", flush=True)


if __name__ == "__main__":
    main()
