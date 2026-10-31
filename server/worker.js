// TopoKit – serverul de licențe (Cloudflare Worker + baza de date D1).
//
// Un singur fișier, fără dependențe: se poate lipi și în editorul Cloudflare din browser.
// Variabile (Settings → Variables): DB (legătura D1), SIGNING_KEY (secret: conținutul fișierului
// topokit_cheie_semnare.json făcut cu tools/licenta.py), ADMIN_TOKEN (secret: parola paginii /admin),
// opțional LICENSE_DAYS (14), CODE_DAYS (14), MAX_DEVICES (2).
//
// Protocolul (JSON, POST):
//   /api/activate   {code, machine, pc, version}     → {license, device, secret}
//   /api/refresh    {device, secret, machine, version} → {license}
//   /api/deactivate {device, secret}                 → {ok}
//   erori: {error: code_invalid | code_used | code_expired | user_disabled | too_many_devices |
//                  rate_limited | revoked | unknown_device | machine | bad_request}
// Licența: "TK1.<payload>.<semnătură>" – formatul complet în tools/licenta.py.
// Administrare: pagina /admin și /api/admin/* (antet Authorization: Bearer ADMIN_TOKEN).

const enc = new TextEncoder();

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS users (
     id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT,
     max_devices INTEGER NOT NULL DEFAULT 2, features TEXT NOT NULL DEFAULT '["all"]',
     disabled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS codes (
     hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL,
     expires_at INTEGER NOT NULL, used_at INTEGER, device_id TEXT)`,
  `CREATE TABLE IF NOT EXISTS devices (
     id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), machine TEXT NOT NULL, pc TEXT,
     secret_hash TEXT NOT NULL, version TEXT, created_at INTEGER NOT NULL, last_seen INTEGER NOT NULL,
     last_ip TEXT, revoked INTEGER NOT NULL DEFAULT 0)`,
  `CREATE INDEX IF NOT EXISTS devices_user ON devices (user_id, revoked)`,
  `CREATE TABLE IF NOT EXISTS events (
     id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, kind TEXT NOT NULL, user_id INTEGER,
     device_id TEXT, ip TEXT, detail TEXT)`,
  `CREATE INDEX IF NOT EXISTS events_at ON events (at)`,
  `CREATE INDEX IF NOT EXISTS events_ip ON events (ip, kind, at)`,
];

const Q = {
  codeByHash: `SELECT hash, user_id, expires_at, used_at FROM codes WHERE hash = ?`,
  useCode: `UPDATE codes SET used_at = ?, device_id = ? WHERE hash = ? AND used_at IS NULL AND expires_at >= ?`,
  insertCode: `INSERT INTO codes (hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)`,
  userById: `SELECT id, name, email, max_devices, features, disabled FROM users WHERE id = ?`,
  insertUser: `INSERT INTO users (name, email, max_devices, created_at) VALUES (?, ?, ?, ?)`,
  setDisabled: `UPDATE users SET disabled = ? WHERE id = ?`,
  setMaxDevices: `UPDATE users SET max_devices = ? WHERE id = ?`,
  countDevices: `SELECT COUNT(*) AS n FROM devices WHERE user_id = ? AND revoked = 0`,
  deviceByUserMachine: `SELECT id FROM devices WHERE user_id = ? AND machine = ? AND revoked = 0`,
  deviceById: `SELECT id, user_id, machine, secret_hash, revoked FROM devices WHERE id = ?`,
  insertDevice: `INSERT INTO devices (id, user_id, machine, pc, secret_hash, version, created_at, last_seen, last_ip)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  seenDevice: `UPDATE devices SET last_seen = ?, version = ?, last_ip = ? WHERE id = ?`,
  revokeDevice: `UPDATE devices SET revoked = 1 WHERE id = ?`,
  failures: `SELECT COUNT(*) AS n FROM events WHERE ip = ? AND kind = ? AND at > ?`,
  insertEvent: `INSERT INTO events (at, kind, user_id, device_id, ip, detail) VALUES (?, ?, ?, ?, ?, ?)`,
  pruneEvents: `DELETE FROM events WHERE at < ?`,
  listUsers: `SELECT id, name, email, max_devices, disabled, created_at FROM users ORDER BY disabled, name COLLATE NOCASE`,
  listDevices: `SELECT id, user_id, machine, pc, version, created_at, last_seen, last_ip, revoked FROM devices
                ORDER BY revoked, last_seen DESC`,
  listCodes: `SELECT user_id, created_at, expires_at, used_at FROM codes WHERE used_at IS NULL AND expires_at >= ?`,
  listEvents: `SELECT e.at, e.kind, e.detail, e.ip, e.device_id, u.name FROM events e LEFT JOIN users u ON u.id = e.user_id
               ORDER BY e.id DESC LIMIT 150`,
};

// ------------------------------------------------------------------ utilitare
const now = () => Math.floor(Date.now() / 1000);
const num = (v, def) => (Number.isFinite(+v) && +v > 0 ? Math.floor(+v) : def);

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}
const fail = (error, status = 403) => json({ error }, status);

function b64u(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const hex = (bytes) => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");

async function sha256hex(text) {
  return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(text))));
}

// comparație în timp constant (pentru hash-uri de aceeași lungime)
function sameHash(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

function randomBytes(n) {
  return crypto.getRandomValues(new Uint8Array(n));
}

// cod de activare: 15 caractere fără 0/O, 1/I/L, U (≈ 73 de biți), afișat TKIT-XXXXX-XXXXX-XXXXX
const ALPHA = "ABCDEFGHJKMNPQRSTVWXYZ23456789";
function newCode() {
  let c = "";
  while (c.length < 15) for (const b of randomBytes(32)) if (b < 240 && c.length < 15) c += ALPHA[b % 30];
  return c;
}
const showCode = (c) => `TKIT-${c.slice(0, 5)}-${c.slice(5, 10)}-${c.slice(10)}`;
function normCode(raw) {
  let c = String(raw || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (c.length === 19 && c.startsWith("TKIT")) c = c.slice(4);
  return /^[A-Z0-9]{15}$/.test(c) ? c : null;
}

async function readBody(request) {
  const len = +(request.headers.get("content-length") || 0);
  if (len > 8192) return null;
  const text = await request.text();
  if (text.length > 8192) return null;
  try {
    const b = JSON.parse(text || "{}");
    return b && typeof b === "object" && !Array.isArray(b) ? b : null;
  } catch {
    return null;
  }
}

const clientIp = (request) => request.headers.get("cf-connecting-ip") || "";
const clip = (v, n) => String(v ?? "").replace(/[\u0000-\u001f]/g, "").slice(0, n);

// ------------------------------------------------------------------ baza de date
let schemaReady = null;
function ensureSchema(db) {
  if (!schemaReady) schemaReady = db.batch(SCHEMA.map((s) => db.prepare(s))).catch((e) => { schemaReady = null; throw e; });
  return schemaReady;
}

const one = (db, sql, ...args) => db.prepare(sql).bind(...args).first();
const all = async (db, sql, ...args) => (await db.prepare(sql).bind(...args).all()).results || [];
const run = (db, sql, ...args) => db.prepare(sql).bind(...args).run();

function event(env, kind, userId, deviceId, ip, detail) {
  return run(env.DB, Q.insertEvent, now(), kind, userId ?? null, deviceId ?? null, ip || null, detail ?? null);
}

async function tooMany(env, ip, kind, limit) {
  const r = await one(env.DB, Q.failures, ip, kind, now() - 3600);
  return (r?.n || 0) >= limit;
}

// ------------------------------------------------------------------ semnarea licenței (ECDSA P-256)
let keyCache = { src: null, key: null, kid: null };
async function signingKey(env) {
  if (keyCache.src !== env.SIGNING_KEY) {
    const jwk = JSON.parse(env.SIGNING_KEY);
    const key = await crypto.subtle.importKey(
      "jwk", { kty: "EC", crv: "P-256", x: jwk.x, y: jwk.y, d: jwk.d, ext: true },
      { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
    keyCache = { src: env.SIGNING_KEY, key, kid: jwk.kid || "k1" };
  }
  return keyCache;
}

async function makeLicense(env, user, device) {
  const { key, kid } = await signingKey(env);
  let features = ["all"];
  try { features = JSON.parse(user.features || '["all"]'); } catch { /* implicit */ }
  const t = now();
  const payload = {
    v: 1, kid, typ: "internal", lid: device.id, uid: user.id, name: user.name, machine: device.machine,
    features, iat: t, exp: t + num(env.LICENSE_DAYS, 14) * 86400,
  };
  const body = "TK1." + b64u(enc.encode(JSON.stringify(payload)));
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(body)));
  return body + "." + b64u(sig);
}

// ------------------------------------------------------------------ API pentru TopoKit.exe
async function activate(request, env) {
  const ip = clientIp(request);
  const b = await readBody(request);
  const machine = clip(b?.machine, 64).toUpperCase();
  const code = normCode(b?.code);
  if (!b || !/^[0-9A-F]{24}$/.test(machine)) return fail("bad_request", 400);
  if (await tooMany(env, ip, "activate_fail", 20)) return fail("rate_limited", 429);
  const bad = async (error) => { await event(env, "activate_fail", null, null, ip, error); return fail(error); };
  if (!code) return bad("code_invalid");
  const hash = await sha256hex(code);
  const c = await one(env.DB, Q.codeByHash, hash);
  if (!c) return bad("code_invalid");
  if (c.used_at) return bad("code_used");
  if (c.expires_at < now()) return bad("code_expired");
  const user = await one(env.DB, Q.userById, c.user_id);
  if (!user || user.disabled) return bad("user_disabled");
  // același calculator activat din nou (reinstalare): înlocuim activarea veche, fără loc nou
  const same = await one(env.DB, Q.deviceByUserMachine, user.id, machine);
  const { n } = await one(env.DB, Q.countDevices, user.id);
  if (!same && n >= user.max_devices) {
    await event(env, "activate_fail", user.id, null, ip, "too_many_devices");
    return fail("too_many_devices");
  }
  const device = { id: "d_" + hex(randomBytes(8)), machine };
  const secret = b64u(randomBytes(32));
  const t = now();
  const used = await run(env.DB, Q.useCode, t, device.id, hash, t);
  if (!used?.meta?.changes) return bad("code_used");                  // folosit în paralel
  if (same) await run(env.DB, Q.revokeDevice, same.id);
  await run(env.DB, Q.insertDevice, device.id, user.id, machine, clip(b.pc, 64), await sha256hex(secret),
            clip(b.version, 20), t, t, ip);
  await event(env, "activate", user.id, device.id, ip, `${clip(b.pc, 64)} ${clip(b.version, 20)}`.trim());
  return json({ license: await makeLicense(env, user, device), device: device.id, secret });
}

async function deviceAuth(env, b) {
  const d = typeof b?.device === "string" ? await one(env.DB, Q.deviceById, clip(b.device, 40)) : null;
  if (!d || !sameHash(await sha256hex(String(b.secret || "")), d.secret_hash)) return { error: "unknown_device" };
  return { d };
}

async function refresh(request, env) {
  const ip = clientIp(request);
  const b = await readBody(request);
  if (!b) return fail("bad_request", 400);
  const { d, error } = await deviceAuth(env, b);
  if (error) return fail(error);
  if (d.revoked) return fail("revoked");
  if (clip(b.machine, 64).toUpperCase() !== d.machine) {
    await event(env, "refresh_fail", d.user_id, d.id, ip, "machine " + clip(b.machine, 64));
    return fail("machine");
  }
  const user = await one(env.DB, Q.userById, d.user_id);
  if (!user || user.disabled) return fail("user_disabled");
  await run(env.DB, Q.seenDevice, now(), clip(b.version, 20), ip, d.id);
  return json({ license: await makeLicense(env, user, d) });
}

async function deactivate(request, env) {
  const b = await readBody(request);
  if (!b) return fail("bad_request", 400);
  const { d, error } = await deviceAuth(env, b);
  if (error) return fail(error);
  if (!d.revoked) {
    await run(env.DB, Q.revokeDevice, d.id);
    await event(env, "deactivate", d.user_id, d.id, clientIp(request), null);
  }
  return json({ ok: true });
}

// ------------------------------------------------------------------ administrare
async function isAdmin(request, env) {
  const h = request.headers.get("authorization") || "";
  if (!env.ADMIN_TOKEN || !h.startsWith("Bearer ")) return false;
  return sameHash(await sha256hex(h.slice(7)), await sha256hex(env.ADMIN_TOKEN));
}

async function issueCode(env, userId) {
  const code = newCode();
  const t = now();
  const expires = t + num(env.CODE_DAYS, 14) * 86400;
  await run(env.DB, Q.insertCode, await sha256hex(code), userId, t, expires);
  return { code: showCode(code), expires_at: expires };
}

async function admin(request, env, path) {
  const ip = clientIp(request);
  if (!env.ADMIN_TOKEN) return fail("admin_disabled", 503);
  if (await tooMany(env, ip, "admin_fail", 10)) return fail("rate_limited", 429);
  if (!(await isAdmin(request, env))) {
    await event(env, "admin_fail", null, null, ip, null);
    return fail("unauthorized", 401);
  }
  const m = request.method;
  if (m === "GET" && path === "/api/admin/state") {
    const t = now();
    await run(env.DB, Q.pruneEvents, t - 180 * 86400);
    const [users, devices, codes, events] = await Promise.all([
      all(env.DB, Q.listUsers), all(env.DB, Q.listDevices), all(env.DB, Q.listCodes, t), all(env.DB, Q.listEvents)]);
    for (const u of users) {
      u.devices = devices.filter((d) => d.user_id === u.id);
      u.open_codes = codes.filter((c) => c.user_id === u.id).length;
    }
    return json({ now: t, users, events, license_days: num(env.LICENSE_DAYS, 14) });
  }
  if (m !== "POST") return fail("not_found", 404);
  const b = (await readBody(request)) || {};
  if (path === "/api/admin/users") {
    const name = clip(b.name, 80).trim();
    if (!name) return fail("name_required", 400);
    const max = Math.min(num(b.max_devices, num(env.MAX_DEVICES, 2)), 10);
    const r = await run(env.DB, Q.insertUser, name, clip(b.email, 120) || null, max, now());
    const id = r.meta.last_row_id;
    await event(env, "user_add", id, null, ip, name);
    return json({ user_id: id, ...(await issueCode(env, id)) });
  }
  let mm = path.match(/^\/api\/admin\/users\/(\d+)\/(code|disable|enable|max)$/);
  if (mm) {
    const id = +mm[1];
    const user = await one(env.DB, Q.userById, id);
    if (!user) return fail("not_found", 404);
    if (mm[2] === "code") {
      await event(env, "code", id, null, ip, null);
      return json(await issueCode(env, id));
    }
    if (mm[2] === "max") {
      await run(env.DB, Q.setMaxDevices, Math.min(num(b.max_devices, user.max_devices), 10), id);
      return json({ ok: true });
    }
    await run(env.DB, Q.setDisabled, mm[2] === "disable" ? 1 : 0, id);
    await event(env, mm[2] === "disable" ? "user_disable" : "user_enable", id, null, ip, null);
    return json({ ok: true });
  }
  mm = path.match(/^\/api\/admin\/devices\/(d_[0-9a-f]{16})\/revoke$/);
  if (mm) {
    const d = await one(env.DB, Q.deviceById, mm[1]);
    if (!d) return fail("not_found", 404);
    await run(env.DB, Q.revokeDevice, d.id);
    await event(env, "device_revoke", d.user_id, d.id, ip, null);
    return json({ ok: true });
  }
  return fail("not_found", 404);
}

// ------------------------------------------------------------------ rutare
async function route(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  if (request.method === "GET" && path === "/admin") {
    return new Response(ADMIN_HTML, {
      headers: {
        "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
        "content-security-policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; " +
          "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
      },
    });
  }
  if (request.method === "GET" && (path === "/" || path === "/api/ping")) {
    return json({ ok: true, service: "TopoKit licente", time: now() });
  }
  if (!path.startsWith("/api/")) return fail("not_found", 404);
  if (!env.DB || !env.SIGNING_KEY) return fail("server_not_configured", 503);
  await ensureSchema(env.DB);
  if (path.startsWith("/api/admin/")) return admin(request, env, path);
  if (request.method !== "POST") return fail("not_found", 404);
  if (path === "/api/activate") return activate(request, env);
  if (path === "/api/refresh") return refresh(request, env);
  if (path === "/api/deactivate") return deactivate(request, env);
  return fail("not_found", 404);
}

export default {
  async fetch(request, env) {
    try {
      return await route(request, env);
    } catch (e) {
      console.error(e && e.stack ? e.stack : e);
      return fail("server", 500);
    }
  },
};

// pentru teste (tests/server_harness.py)
export const _test = { SCHEMA, Q, normCode, showCode, newCode };

// ------------------------------------------------------------------ pagina de administrare
const ADMIN_HTML = `<!doctype html>
<html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TopoKit – licențe</title>
<style>
:root{--bg:#f4f7fa;--card:#fff;--text:#1a2733;--muted:#5b6b7a;--line:#dde5ec;--accent:#1b6a8f;--ok:#23874a;--bad:#c8443a;--warn:#b7791f}
@media (prefers-color-scheme:dark){:root{--bg:#161b21;--card:#1f262e;--text:#e6edf3;--muted:#9aa8b5;--line:#2f3a45;--accent:#5fb3dc;--ok:#4cc27a;--bad:#ef7468;--warn:#e0a84a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 "Segoe UI",Arial,sans-serif}
header{background:linear-gradient(120deg,#0f3d5e,#1b6a8f);color:#fff;padding:20px 24px}header h1{margin:0;font-size:22px;font-weight:600}
main{max-width:1100px;margin:0 auto;padding:16px}section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}
h2{font-size:15px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
input,button{font:inherit}input{padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--text)}
button{padding:7px 12px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
button.ghost{background:transparent;color:var(--accent)}button.danger{border-color:var(--bad);background:transparent;color:var(--bad)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.code{font:600 20px Consolas,monospace;letter-spacing:.06em;padding:10px 14px;border:2px dashed var(--accent);border-radius:8px;display:inline-block;margin:6px 0}
.msg{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:13.5px}
.dev{font-size:13px;margin:2px 0}.hidden{display:none}.wrap{overflow-x:auto}
</style></head><body>
<header><h1>TopoKit – licențe</h1></header>
<main>
<section id="login"><h2>Autentificare</h2>
 <div class="row"><input id="tok" type="password" placeholder="Parola de administrare (ADMIN_TOKEN)" size="40" autocomplete="current-password">
 <button id="go">Intră</button></div><p id="lerr" class="bad"></p></section>
<div id="app" class="hidden">
<section><h2>Coleg nou</h2>
 <div class="row"><input id="nm" placeholder="Nume (apare în TopoKit și în documente)" size="34">
 <input id="em" placeholder="E-mail (opțional)" size="24"><label class="muted">Calculatoare <input id="mx" type="number" min="1" max="10" value="2" style="width:64px"></label>
 <button id="add">Adaugă și creează cod</button></div>
 <div id="newcode" class="hidden"><p>Codul de activare pentru <b id="ncname"></b> (o singură folosire, valabil <span id="ncdays"></span> zile):</p>
 <div class="code" id="nccode"></div> <button class="ghost" id="nccopy">Copiază mesajul</button>
 <p class="muted">Mesaj de trimis colegului:</p><div class="msg" id="ncmsg"></div></div></section>
<section><h2>Colegi</h2><div class="wrap"><table><thead><tr><th>Nume</th><th>Stare</th><th>Calculatoare</th><th></th></tr></thead><tbody id="users"></tbody></table></div></section>
<section><h2>Activitate</h2><div class="wrap"><table><thead><tr><th>Când</th><th>Ce</th><th>Cine</th><th>Detalii</th><th>IP</th></tr></thead><tbody id="events"></tbody></table></div>
 <p><button class="ghost" id="out">Ieșire</button></p></section>
</div></main>
<script>
const $ = (id) => document.getElementById(id);
let token = ""; try { token = sessionStorage.getItem("tk") || ""; } catch (e) {}
const KIND = {activate:"Activare",activate_fail:"Activare refuzată",refresh_fail:"Reînnoire refuzată",deactivate:"Dezactivare",
  user_add:"Coleg adăugat",user_disable:"Acces oprit",user_enable:"Acces repornit",code:"Cod nou",device_revoke:"Calculator scos",admin_fail:"Parolă admin greșită"};
const fmt = (t) => t ? new Date(t * 1000).toLocaleString("ro-RO", {dateStyle:"short", timeStyle:"short"}) : "–";
function el(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
async function api(path, body) {
  const r = await fetch(path, {method: body ? "POST" : "GET", headers: {"authorization": "Bearer " + token, "content-type": "application/json"},
    body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) { logout("Parolă greșită."); throw new Error("401"); }
  if (!r.ok) { alert("Eroare: " + (j.error || r.status)); throw new Error(j.error); }
  return j;
}
function logout(msg) { token = ""; try { sessionStorage.removeItem("tk"); } catch (e) {} $("app").classList.add("hidden"); $("login").classList.remove("hidden"); $("lerr").textContent = msg || ""; }
function showCode(name, c, days) {
  $("newcode").classList.remove("hidden"); $("ncname").textContent = name; $("nccode").textContent = c.code; $("ncdays").textContent = days;
  $("ncmsg").textContent = "Bună,\\n\\nCodul tău de activare TopoKit este:\\n\\n    " + c.code +
    "\\n\\n1. Instalează TopoKit (TopoKitSetup.exe).\\n2. Deschide fereastra TopoKit și apasă „Activați TopoKit” (sus, dreapta).\\n" +
    "3. Scrie codul și apasă Activează. Ai nevoie de internet doar la activare și măcar o dată la două săptămâni.\\n\\n" +
    "Codul merge o singură dată, până la " + fmt(c.expires_at) + ". Te rog să nu-l dai mai departe.";
  $("newcode").scrollIntoView({behavior: "smooth"});
}
async function load() {
  const s = await api("/api/admin/state");
  $("login").classList.add("hidden"); $("app").classList.remove("hidden");
  const tb = $("users"); tb.textContent = "";
  for (const u of s.users) {
    const tr = el("tr"); const c1 = el("td"); c1.append(el("b", u.name)); if (u.email) c1.append(el("div", u.email, "muted"));
    const act = u.devices.filter((d) => !d.revoked);
    const st = el("td", u.disabled ? "Acces oprit" : act.length ? "Activ" : "Neactivat", u.disabled ? "bad" : act.length ? "ok" : "warn");
    if (u.open_codes) st.append(el("div", u.open_codes + " cod nefolosit", "muted"));
    const c3 = el("td"); c3.append(el("div", act.length + " / " + u.max_devices, "muted"));
    for (const d of u.devices) {
      const dv = el("div", null, "dev" + (d.revoked ? " muted" : ""));
      const old = !d.revoked && s.now - d.last_seen > s.license_days * 86400;
      dv.append(el("span", (d.pc || "?") + " · v" + (d.version || "?") + " · văzut " + fmt(d.last_seen) + (d.revoked ? " · scos" : ""), old ? "warn" : ""));
      if (!d.revoked) { const b = el("button", "Scoate", "danger"); b.style.marginLeft = "8px"; b.style.padding = "2px 8px";
        b.onclick = async () => { if (confirm("Scoateți calculatorul " + (d.pc || "") + "? Licența lui se oprește la următoarea verificare.")) { await api("/api/admin/devices/" + d.id + "/revoke", {}); load(); } }; dv.append(b); }
      c3.append(dv);
    }
    const c4 = el("td"); const row = el("div", null, "row");
    const bc = el("button", "Cod nou", "ghost"); bc.onclick = async () => { const c = await api("/api/admin/users/" + u.id + "/code", {}); showCode(u.name, c, Math.round((c.expires_at - Date.now() / 1000) / 86400)); }; row.append(bc);
    const bm = el("button", "Nr. calculatoare", "ghost"); bm.onclick = async () => { const v = prompt("Câte calculatoare poate activa " + u.name + "?", u.max_devices); if (v) { await api("/api/admin/users/" + u.id + "/max", {max_devices: +v}); load(); } }; row.append(bm);
    const bd = el("button", u.disabled ? "Repornește accesul" : "Oprește accesul", u.disabled ? "ghost" : "danger");
    bd.onclick = async () => { if (u.disabled || confirm("Opriți accesul lui " + u.name + "? TopoKit se oprește pe calculatoarele lui la următoarea verificare (cel târziu în " + s.license_days + " zile fără internet).")) { await api("/api/admin/users/" + u.id + (u.disabled ? "/enable" : "/disable"), {}); load(); } };
    row.append(bd); c4.append(row);
    tr.append(c1, st, c3, c4); tb.append(tr);
  }
  if (!s.users.length) { const tr = el("tr"); const td = el("td", "Niciun coleg încă – adăugați primul mai sus.", "muted"); td.colSpan = 4; tr.append(td); tb.append(tr); }
  const te = $("events"); te.textContent = "";
  for (const e of s.events) { const tr = el("tr"); tr.append(el("td", fmt(e.at)), el("td", KIND[e.kind] || e.kind, /fail/.test(e.kind) ? "bad" : ""), el("td", e.name || "–"), el("td", e.detail || ""), el("td", e.ip || "", "muted")); te.append(tr); }
}
$("go").onclick = async () => { token = $("tok").value.trim(); try { sessionStorage.setItem("tk", token); } catch (e) {} try { await load(); } catch (e) {} };
$("tok").onkeydown = (e) => { if (e.key === "Enter") $("go").click(); };
$("add").onclick = async () => { const name = $("nm").value.trim(); if (!name) { $("nm").focus(); return; }
  const c = await api("/api/admin/users", {name, email: $("em").value.trim(), max_devices: +$("mx").value || 2}); $("nm").value = ""; $("em").value = "";
  showCode(name, c, Math.round((c.expires_at - Date.now() / 1000) / 86400)); load(); };
$("nccopy").onclick = () => navigator.clipboard && navigator.clipboard.writeText($("ncmsg").textContent);
$("out").onclick = () => logout();
if (token) load().catch(() => {});
</script></body></html>`;
