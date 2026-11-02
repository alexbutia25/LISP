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
//   /api/request    {machine, pc, name, winuser, version} → {request, token, status: "pending"}
//   /api/request/status {request, token, machine}    → {status: "pending" | "denied"} sau
//                                                       {status: "approved", device, license}
//   erori: {error: code_invalid | code_used | code_expired | user_disabled | too_many_devices |
//                  rate_limited | revoked | unknown_device | machine | bad_request |
//                  name_required | requests_full | unknown_request}
//
// Cererea de acces (de la 1.11.0): colegul apasă „Cere acces” în TopoKit, cererea apare în /admin, iar
// administratorul o acceptă (pentru un coleg existent sau unul nou) sau o respinge. Tokenul cererii
// (32 de octeți aleatori, păstrat doar ca hash) devine, la aprobare, secretul dispozitivului: serverul
// nu ține niciun secret în clar, iar răspunsul „approved” se poate cere de câte ori e nevoie (același
// dispozitiv, fără dubluri). Clientul folosește tokenul ca „secret” la /api/refresh și /api/deactivate.
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
  // 1.11.0 (doar adăugări: bazele de date existente primesc tabela la prima cerere)
  `CREATE TABLE IF NOT EXISTS requests (
     id TEXT PRIMARY KEY, machine TEXT NOT NULL, pc TEXT, name TEXT NOT NULL, winuser TEXT, version TEXT,
     country TEXT, ip TEXT, token_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
     created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, polled_at INTEGER, decided_at INTEGER,
     user_id INTEGER, device_id TEXT, delivered_at INTEGER)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS requests_pending ON requests (machine) WHERE status = 'pending'`,
  `CREATE INDEX IF NOT EXISTS requests_status ON requests (status, decided_at)`,
];

const Q = {
  codeByHash: `SELECT hash, user_id, expires_at, used_at FROM codes WHERE hash = ?`,
  useCode: `UPDATE codes SET used_at = ?, device_id = ? WHERE hash = ? AND used_at IS NULL AND expires_at >= ?`,
  releaseCode: `UPDATE codes SET used_at = NULL, device_id = NULL WHERE hash = ? AND device_id = ?`,
  insertCode: `INSERT INTO codes (hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)`,
  pruneCodes: `DELETE FROM codes WHERE used_at IS NULL AND expires_at < ?`,
  userById: `SELECT id, name, email, max_devices, features, disabled FROM users WHERE id = ?`,
  insertUser: `INSERT INTO users (name, email, max_devices, created_at) VALUES (?, ?, ?, ?)`,
  setDisabled: `UPDATE users SET disabled = ? WHERE id = ?`,
  setMaxDevices: `UPDATE users SET max_devices = ? WHERE id = ?`,
  countOther: `SELECT COUNT(*) AS n FROM devices WHERE user_id = ? AND revoked = 0 AND machine <> ?`,
  // cea mai nouă activare a calculatorului: ordinea e (created_at, id), nu rowid-ul implicit (tabelă cu
  // cheie TEXT: rowid-ul se poate renumerota la VACUUM / export-import)
  deviceByUserMachine: `SELECT id, created_at FROM devices WHERE user_id = ? AND machine = ? AND revoked = 0
                        ORDER BY created_at DESC, id DESC LIMIT 1`,
  deviceById: `SELECT id, user_id, machine, secret_hash, revoked, last_seen, last_ip FROM devices WHERE id = ?`,
  insertDevice: `INSERT INTO devices (id, user_id, machine, pc, secret_hash, version, created_at, last_seen, last_ip)
                 SELECT ?, u.id, ?, ?, ?, ?, ?, ?, ? FROM users u WHERE u.id = ? AND u.disabled = 0 AND (
                   EXISTS (SELECT 1 FROM devices WHERE user_id = u.id AND machine = ? AND revoked = 0) OR
                   (SELECT COUNT(*) FROM devices WHERE user_id = u.id AND revoked = 0) < u.max_devices)`,
  // rămâne activă doar cea mai nouă activare (created_at, id) a calculatorului; fiecare activare rulează
  // instrucțiunea după INSERT-ul ei, deci ultima rulată le vede pe toate -> exact una rămâne
  revokeOlderSame: `UPDATE devices SET revoked = 1 WHERE user_id = ? AND machine = ? AND revoked = 0
                    AND id <> (SELECT id FROM devices WHERE user_id = ? AND machine = ? AND revoked = 0
                               ORDER BY created_at DESC, id DESC LIMIT 1)`,
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
  // cererile de acces
  requestById: `SELECT id, machine, pc, name, version, token_hash, status, user_id, device_id, delivered_at
                FROM requests WHERE id = ?`,
  pendingByMachine: `SELECT id FROM requests WHERE machine = ? AND status = 'pending'`,
  // o singură cerere în așteptare pe calculator (indexul unic requests_pending) și cel mult MAX_PENDING
  // în total, ambele verificate în aceeași instrucțiune (atomic în D1)
  insertRequest: `INSERT OR IGNORE INTO requests (id, machine, pc, name, winuser, version, country, ip, token_hash, status,
                    created_at, updated_at)
                  SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?
                  WHERE (SELECT COUNT(*) FROM requests WHERE status = 'pending') < ?`,
  renewRequest: `UPDATE requests SET pc = ?, name = ?, winuser = ?, version = ?, country = ?, ip = ?, token_hash = ?,
                   updated_at = ? WHERE id = ? AND status = 'pending'`,
  pollRequest: `UPDATE requests SET polled_at = ? WHERE id = ? AND (polled_at IS NULL OR polled_at < ?)`,
  deliverRequest: `UPDATE requests SET delivered_at = ? WHERE id = ? AND delivered_at IS NULL`,
  // aprobarea „ia” cererea doar dacă e tot în așteptare și cu același token (o cerere reînnoită între
  // timp are alt token: dispozitivul ar primi hash-ul vechi)
  claimRequest: `UPDATE requests SET status = 'approved', decided_at = ?, user_id = ?, device_id = ?
                 WHERE id = ? AND status = 'pending' AND token_hash = ?`,
  unclaimRequest: `UPDATE requests SET status = 'pending', decided_at = NULL, user_id = NULL, device_id = NULL
                   WHERE id = ? AND device_id = ?`,
  setRequestUser: `UPDATE requests SET user_id = ? WHERE id = ?`,
  denyRequest: `UPDATE requests SET status = 'denied', decided_at = ? WHERE id = ? AND status = 'pending'`,
  pruneRequests: `DELETE FROM requests WHERE (status = 'pending' AND updated_at < ?) OR (status <> 'pending' AND decided_at < ?)`,
  listRequests: `SELECT id, machine, pc, name, winuser, version, country, ip, status, created_at, updated_at, polled_at,
                   decided_at, user_id, device_id, delivered_at FROM requests
                 WHERE status = 'pending' OR decided_at >= ?
                 ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, COALESCE(decided_at, updated_at) DESC LIMIT 300`,
};

// ------------------------------------------------------------------ utilitare
const now = () => Math.floor(Date.now() / 1000);
const num = (v, def) => (Number.isFinite(+v) && +v > 0 ? Math.floor(+v) : def);

const EVENT_DAYS = 180;                 // jurnalul de activitate și codurile expirate se șterg după 180 de zile
const REQUEST_DAYS = 30;                // o cerere de acces nerezolvată expiră după 30 de zile
const MAX_PENDING = 200;                // cel mult 200 de cereri în așteptare (o cerere / calculator)
const REQUEST_LIMIT = 20;               // cereri de acces pe oră de la aceeași adresă (IPv4 sau rețea IPv6 /64)

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store",
               "x-content-type-options": "nosniff" },
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

// corpul cererii: cel mult 8 KiB, citit pe bucăți (fără content-length nu se încarcă tot în memorie)
const MAX_BODY = 8192;
async function readBody(request) {
  const len = +(request.headers.get("content-length") || 0);
  if (!(len <= MAX_BODY)) return null;
  let text = "";
  if (request.body) {
    const reader = request.body.getReader();
    const parts = [];
    let n = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      n += value.byteLength;
      if (n > MAX_BODY) {
        try { await reader.cancel(); } catch { /* nimic */ }
        return null;
      }
      parts.push(value);
    }
    const buf = new Uint8Array(n);
    let o = 0;
    for (const p of parts) { buf.set(p, o); o += p.byteLength; }
    try { text = new TextDecoder("utf-8", { fatal: true }).decode(buf); } catch { return null; }
  }
  try {
    const b = JSON.parse(text || "{}");
    return b && typeof b === "object" && !Array.isArray(b) ? b : null;
  } catch {
    return null;
  }
}

// Singura adresă de încredere e CF-Connecting-IP (pusă de Cloudflare; X-Forwarded-For & co. le poate
// trimite oricine). Pentru limitarea încercărilor IPv6 contează rețeaua /64: un atacator are de obicei
// un /64 întreg, deci altfel ar primi câte 20 de încercări pentru fiecare adresă.
const clientIp = (request) => request.headers.get("cf-connecting-ip") || "";
function ipKey(ip) {
  ip = String(ip || "").split("%")[0];
  if (!ip.includes(":")) return ip;
  const v4 = ip.match(/^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/i);
  if (v4) return v4[1];
  const [head, tail] = ip.split("::");
  const h = head ? head.split(":") : [];
  const t = tail === undefined ? [] : tail ? tail.split(":") : [];
  const g = tail === undefined ? h : [...h, ...Array(Math.max(0, 8 - h.length - t.length)).fill("0"), ...t];
  return g.slice(0, 4).map((x) => (parseInt(x, 16) || 0).toString(16)).join(":") + "::/64";
}

// text de la client: fără caractere de control / de direcție (ar păcăli afișarea din /admin),
// tăiat la n caractere întregi (nu la jumătatea unei perechi surogat) și, opțional, la maxBytes UTF-8
const BAD_CHARS = /[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff\ufff9-\ufffb]/g;
function clip(v, n, maxBytes = Infinity) {
  let out = "", bytes = 0, k = 0;
  for (const ch of String(v ?? "").replace(BAD_CHARS, "")) {
    const b = ch.length > 1 ? 4 : ch.charCodeAt(0) < 0x80 ? 1 : ch.charCodeAt(0) < 0x800 ? 2 : 3;
    if (k >= n || bytes + b > maxBytes) break;
    out += ch.length > 1 || (ch.charCodeAt(0) & 0xf800) !== 0xd800 ? ch : String.fromCharCode(0xfffd);  // surogat singur
    bytes += b;
    k++;
  }
  return out;
}
// numele din licență: TopoKit.exe îl citește într-un tampon de 160 de octeți (license.c, CheckText)
const NAME_CHARS = 80, NAME_BYTES = 150;

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

// limitarea încercărilor: evenimentele *_fail se scriu cu ipKey(ip) (adresa IPv4 sau rețeaua IPv6 /64)
async function tooMany(env, ip, kind, limit) {
  const r = await one(env.DB, Q.failures, ipKey(ip), kind, now() - 3600);
  return (r?.n || 0) >= limit;
}

async function prune(env) {
  const old = now() - EVENT_DAYS * 86400;
  await env.DB.batch([env.DB.prepare(Q.pruneEvents).bind(old), env.DB.prepare(Q.pruneCodes).bind(old),
                      env.DB.prepare(Q.pruneRequests).bind(now() - REQUEST_DAYS * 86400, old)]);
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
    v: 1, kid, typ: "internal", lid: device.id, uid: user.id, name: clip(user.name, NAME_CHARS, NAME_BYTES),
    machine: device.machine,
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
  const bad = async (error, userId) => {
    await event(env, "activate_fail", userId, null, ipKey(ip), error);
    return fail(error);
  };
  if (!code) return bad("code_invalid");
  const hash = await sha256hex(code);
  const c = await one(env.DB, Q.codeByHash, hash);
  if (!c) return bad("code_invalid");
  if (c.used_at) return bad("code_used");
  if (c.expires_at < now()) return bad("code_expired");
  const user = await one(env.DB, Q.userById, c.user_id);
  if (!user || user.disabled) return bad("user_disabled");
  // același calculator activat din nou (reinstalare): înlocuim activarea veche, fără loc nou
  // (se numără doar celelalte calculatoare: o reactivare simultană pe același calculator nu schimbă nimic)
  const same = await one(env.DB, Q.deviceByUserMachine, user.id, machine);
  const { n } = await one(env.DB, Q.countOther, user.id, machine);
  if (!same && n >= user.max_devices) return bad("too_many_devices", user.id);
  const device = { id: "d_" + hex(randomBytes(8)), machine };
  const secret = b64u(randomBytes(32));
  const pc = clip(b.pc, 64), version = clip(b.version, 20);
  const t = now();
  // reactivare în aceeași secundă: activarea nouă trebuie să fie „mai nouă” decât cea veche
  // (ordinea (created_at, id)), altfel id-ul aleator ar putea păstra activarea veche
  const created = same ? Math.max(t, Number(same.created_at) + 1) : t;
  // 1) codul se consumă atomic (UPDATE ... WHERE used_at IS NULL): două activări simultane cu
  //    același cod → doar una trece
  const used = await run(env.DB, Q.useCode, t, device.id, hash, t);
  if (!used?.meta?.changes) return bad("code_used");                  // folosit în paralel
  // 2) calculatorul se adaugă doar dacă încă e loc, verificat în aceeași instrucțiune (atomic în D1):
  //    două activări simultane cu coduri diferite nu pot depăși max_devices
  const ins = await run(env.DB, Q.insertDevice, device.id, machine, pc, await sha256hex(secret), version, created, t, ip,
                        user.id, machine);
  if (!ins?.meta?.changes) {
    await run(env.DB, Q.releaseCode, hash, device.id);                // codul rămâne valabil
    return bad("too_many_devices", user.id);
  }
  // 3) activările mai vechi de pe același calculator se opresc (rămâne doar cea mai nouă după
  //    (created_at, id): la reactivări simultane rămâne exact una)
  await run(env.DB, Q.revokeOlderSame, user.id, machine, user.id, machine);
  await event(env, "activate", user.id, device.id, ip, `${pc} ${version}`.trim());
  await prune(env);
  return json({ license: await makeLicense(env, user, device), device: device.id, secret });
}

async function deviceAuth(env, b) {
  const id = typeof b?.device === "string" && /^d_[0-9a-f]{16}$/.test(b.device) ? b.device : null;
  const d = id ? await one(env.DB, Q.deviceById, id) : null;
  const secret = typeof b?.secret === "string" && b.secret.length <= 128 ? b.secret : "";
  if (!d || !secret || !sameHash(await sha256hex(secret), d.secret_hash)) return { error: "unknown_device" };
  return { d };
}

// O activare copiată pe alt PC (MachineGuid + seria discului falsificate, secretul scos din DPAPI) se
// vede doar prin reînnoiri de la adrese diferite. Lansatorul reînnoiește la 6 h (1.11.0; înainte la 20 h),
// deci două reînnoiri la mai puțin de 4 h, din rețele diferite, apar în jurnal ca „posibilă copiere”.
const CLONE_WINDOW = 4 * 3600;

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
  const t = now();
  if (d.last_ip && ip && ipKey(d.last_ip) !== ipKey(ip) && t - d.last_seen < CLONE_WINDOW) {
    await event(env, "clone_suspect", d.user_id, d.id, ip, `${d.last_ip} → ${ip}`);
  }
  await run(env.DB, Q.seenDevice, t, clip(b.version, 20), ip, d.id);
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

// ------------------------------------------------------------------ cererea de acces („Cere acces” în TopoKit)
const str = (v) => (typeof v === "string" ? v : "");

async function requestAccess(request, env) {
  const ip = clientIp(request);
  const b = await readBody(request);
  const machine = clip(b?.machine, 64).toUpperCase();
  if (!b || !/^[0-9A-F]{24}$/.test(machine)) return fail("bad_request", 400);
  if (await tooMany(env, ip, "request", REQUEST_LIMIT)) return fail("rate_limited", 429);
  const winuser = clip(str(b.winuser), 64).trim();
  const name = clip(str(b.name).trim() || winuser, NAME_CHARS, NAME_BYTES).trim();
  if (!name) return fail("name_required", 400);
  const pc = clip(str(b.pc), 64), version = clip(str(b.version), 20);
  const country = clip(str(request.cf?.country), 2).toUpperCase() || null;
  const token = b64u(randomBytes(32));
  const th = await sha256hex(token);
  const t = now();
  // fiecare cerere (și cea repetată) intră în limita pe oră: evenimentul se scrie cu ipKey(ip)
  await event(env, "request", null, null, ipKey(ip), `${name} · ${pc}`.trim());
  // același calculator cere din nou (reinstalare, alt nume): aceeași cerere, cu token nou
  const renew = async () => {
    const p = await one(env.DB, Q.pendingByMachine, machine);
    if (!p) return null;
    const r = await run(env.DB, Q.renewRequest, pc, name, winuser, version, country, ip, th, t, p.id);
    return r?.meta?.changes ? p.id : null;
  };
  let id = await renew();
  if (!id) {
    const nid = "r_" + hex(randomBytes(8));
    const ins = await run(env.DB, Q.insertRequest, nid, machine, pc, name, winuser, version, country, ip, th, t, t, MAX_PENDING);
    id = ins?.meta?.changes ? nid : await renew();          // cerere simultană de pe același calculator
    if (!id) return fail("requests_full", 503);
    if (id === nid) await prune(env);
  }
  return json({ request: id, token, status: "pending" });
}

async function requestStatus(request, env) {
  const ip = clientIp(request);
  const b = await readBody(request);
  if (!b) return fail("bad_request", 400);
  if (await tooMany(env, ip, "request_fail", 20)) return fail("rate_limited", 429);
  const bad = async (error) => {
    await event(env, "request_fail", null, null, ipKey(ip), error);
    return fail(error);
  };
  const id = typeof b.request === "string" && /^r_[0-9a-f]{16}$/.test(b.request) ? b.request : null;
  const token = typeof b.token === "string" && b.token.length <= 128 ? b.token : "";
  const r = id ? await one(env.DB, Q.requestById, id) : null;
  if (!r || !token || !sameHash(await sha256hex(token), r.token_hash)) return bad("unknown_request");
  if (clip(b.machine, 64).toUpperCase() !== r.machine) return bad("machine");
  const t = now();
  if (r.status === "denied") return json({ status: "denied" });
  if (r.status === "approved") {
    // dispozitivul lipsește doar cât timp aprobarea e în curs (cerere „luată”, dispozitiv încă nescris)
    const d = r.device_id ? await one(env.DB, Q.deviceById, r.device_id) : null;
    if (d) {
      if (d.revoked) return fail("revoked");
      const user = await one(env.DB, Q.userById, d.user_id);
      if (!user || user.disabled) return fail("user_disabled");
      if ((await run(env.DB, Q.deliverRequest, t, r.id))?.meta?.changes) {
        await event(env, "request_delivered", d.user_id, d.id, ip, `${r.pc || ""} ${r.version || ""}`.trim());
      }
      await run(env.DB, Q.seenDevice, t, r.version, ip, d.id);
      // același dispozitiv la fiecare întrebare (idempotent); secretul lui este tokenul cererii
      return json({ status: "approved", device: d.id, license: await makeLicense(env, user, d) });
    }
  }
  await run(env.DB, Q.pollRequest, t, r.id, t - 600);      // „văzut” în /admin, scris cel mult o dată la 10 min
  return json({ status: "pending" });
}

// Aprobarea din /admin: dispozitivul se creează ca la activarea cu cod (aceleași reguli: un loc pe
// calculator, max_devices verificat atomic, activarea mai veche a aceluiași calculator se oprește),
// cu hash-ul tokenului cererii ca secret.
async function approveRequest(env, ip, r, b) {
  const t = now();
  let user = null, same = null, newName = null, newMax = 0;
  const maxIn = b.max_devices ?? b.max;
  if (b.user_id != null && b.user_id !== "" && b.user_id !== "new") {
    user = await one(env.DB, Q.userById, num(b.user_id, 0));
    if (!user) return fail("not_found", 404);
    if (user.disabled) return fail("user_disabled", 409);
    const max = maxIn == null ? 0 : Math.min(num(maxIn, user.max_devices), 10);
    if (max > user.max_devices) {                             // administratorul a mărit limita la aprobare
      await run(env.DB, Q.setMaxDevices, max, user.id);
      await event(env, "user_max", user.id, null, ip, String(max));
      user.max_devices = max;
    }
    same = await one(env.DB, Q.deviceByUserMachine, user.id, r.machine);
    const { n } = await one(env.DB, Q.countOther, user.id, r.machine);
    if (!same && n >= user.max_devices) return fail("too_many_devices", 409);
  } else {
    newName = clip(str(b.new_name).trim() || r.name, NAME_CHARS, NAME_BYTES).trim();
    if (!newName) return fail("name_required", 400);
    newMax = Math.min(num(maxIn, num(env.MAX_DEVICES, 2)), 10);
  }
  const device = { id: "d_" + hex(randomBytes(8)), machine: r.machine };
  // 1) cererea se „ia” atomic: două aprobări simultane → doar una trece (și doar ea face colegul nou)
  const c = await run(env.DB, Q.claimRequest, t, user ? user.id : null, device.id, r.id, r.token_hash);
  if (!c?.meta?.changes) {
    const now2 = await one(env.DB, Q.requestById, r.id);
    return fail(now2?.status === "pending" ? "changed" : "not_pending", 409);
  }
  if (!user) {
    const nu = await run(env.DB, Q.insertUser, newName, null, newMax, t);
    user = await one(env.DB, Q.userById, nu.meta.last_row_id);
    await run(env.DB, Q.setRequestUser, user.id, r.id);
    await event(env, "user_add", user.id, null, ip, newName);
  }
  const created = same ? Math.max(t, Number(same.created_at) + 1) : t;
  // 2) dispozitivul, doar dacă încă e loc (aceeași instrucțiune ca la activare)
  const ins = await run(env.DB, Q.insertDevice, device.id, r.machine, r.pc, r.token_hash, r.version, created, t, null,
                        user.id, r.machine);
  if (!ins?.meta?.changes) {
    await run(env.DB, Q.unclaimRequest, r.id, device.id);     // cererea rămâne în așteptare
    return fail(user.disabled ? "user_disabled" : "too_many_devices", 409);
  }
  // 3) activarea mai veche a aceluiași calculator (același coleg) se oprește
  await run(env.DB, Q.revokeOlderSame, user.id, r.machine, user.id, r.machine);
  await event(env, "request_approve", user.id, device.id, ip, `${r.name} · ${r.pc || ""}`.trim());
  return json({ ok: true, user_id: user.id, device: device.id });
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
    await event(env, "admin_fail", null, null, ipKey(ip), null);
    return fail("unauthorized", 401);
  }
  const m = request.method;
  if (m === "GET" && path === "/api/admin/state") {
    const t = now();
    await prune(env);
    const [users, devices, codes, events, requests] = await Promise.all([
      all(env.DB, Q.listUsers), all(env.DB, Q.listDevices), all(env.DB, Q.listCodes, t), all(env.DB, Q.listEvents),
      all(env.DB, Q.listRequests, t - REQUEST_DAYS * 86400)]);
    for (const u of users) {
      u.devices = devices.filter((d) => d.user_id === u.id);
      u.open_codes = codes.filter((c) => c.user_id === u.id).length;
    }
    return json({ now: t, users, events, requests, license_days: num(env.LICENSE_DAYS, 14) });
  }
  if (m === "GET" && path === "/api/admin/requests") {
    const t = now();
    return json({ now: t, requests: await all(env.DB, Q.listRequests, t - REQUEST_DAYS * 86400) });
  }
  if (m !== "POST") return fail("not_found", 404);
  const b = (await readBody(request)) || {};
  if (path === "/api/admin/users") {
    const name = clip(b.name, NAME_CHARS, NAME_BYTES).trim();
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
      const max = Math.min(num(b.max_devices, user.max_devices), 10);
      await run(env.DB, Q.setMaxDevices, max, id);
      await event(env, "user_max", id, null, ip, String(max));
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
  mm = path.match(/^\/api\/admin\/requests\/(r_[0-9a-f]{16})\/(approve|deny)$/);
  if (mm) {
    const r = await one(env.DB, Q.requestById, mm[1]);
    if (!r) return fail("not_found", 404);
    if (r.status !== "pending") return fail("not_pending", 409);
    if (mm[2] === "approve") return approveRequest(env, ip, r, b);
    const x = await run(env.DB, Q.denyRequest, now(), r.id);
    if (!x?.meta?.changes) return fail("not_pending", 409);
    await event(env, "request_deny", null, null, ip, `${r.name} · ${r.pc || ""}`.trim());
    return json({ ok: true });
  }
  return fail("not_found", 404);
}

// ------------------------------------------------------------------ rutare
async function route(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  if (request.method === "GET" && path === "/admin") {
    // scriptul paginii rulează doar cu nonce-ul acestei cereri (un eventual <script> injectat nu rulează)
    const nonce = b64u(randomBytes(16));
    return new Response(ADMIN_HTML.replace("<script>", `<script nonce="${nonce}">`), {
      headers: {
        "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-frame-options": "DENY",
        "referrer-policy": "no-referrer", "x-content-type-options": "nosniff",
        "content-security-policy": `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; ` +
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
  if (path === "/api/request") return requestAccess(request, env);
  if (path === "/api/request/status") return requestStatus(request, env);
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
  // opțional (Settings → Triggers → Cron, de ex. zilnic): curăță jurnalul și când nu intră nimeni în /admin
  async scheduled(event, env, ctx) {
    if (!env.DB) return;
    ctx.waitUntil(ensureSchema(env.DB).then(() => prune(env)));
  },
};

// pentru teste (tests/server_harness.py)
export const _test = { SCHEMA, Q, normCode, showCode, newCode, ipKey, clip };

// ------------------------------------------------------------------ pagina de administrare
const ADMIN_HTML = `<!doctype html>
<html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TopoKit – licențe</title>
<style>
:root{--bg:#f4f7fa;--card:#fff;--text:#1a2733;--muted:#5b6b7a;--line:#dde5ec;--accent:#1b6a8f;--ok:#23874a;--bad:#c8443a;--warn:#b7791f;--hl:#fff7e6}
@media (prefers-color-scheme:dark){:root{--bg:#161b21;--card:#1f262e;--text:#e6edf3;--muted:#9aa8b5;--line:#2f3a45;--accent:#5fb3dc;--ok:#4cc27a;--bad:#ef7468;--warn:#e0a84a;--hl:#2b2618}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 "Segoe UI",Arial,sans-serif}
header{background:linear-gradient(120deg,#0f3d5e,#1b6a8f);color:#fff;padding:20px 24px}header h1{margin:0;font-size:22px;font-weight:600}
main{max-width:1100px;margin:0 auto;padding:16px}section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}
h2{font-size:15px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
input,button,select{font:inherit}input,select{padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--text)}
button{padding:7px 12px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
button.ghost{background:transparent;color:var(--accent)}button.danger{border-color:var(--bad);background:transparent;color:var(--bad)}
button.cancel{border-color:var(--bad);background:var(--bad);color:#fff;font-weight:600}button.okb{border-color:var(--ok);background:var(--ok);color:#fff;font-weight:600}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 6px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.small{font-size:13px}
.code{font:600 20px Consolas,monospace;letter-spacing:.06em;padding:10px 14px;border:2px dashed var(--accent);border-radius:8px;display:inline-block;margin:6px 0}
.msg{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:13.5px}
.dev{font-size:13px;margin:4px 0}.hidden{display:none}.wrap{overflow-x:auto}
.badge{display:inline-block;min-width:22px;padding:0 7px;border-radius:11px;background:var(--bad);color:#fff;font-size:13px;text-align:center;letter-spacing:0}
.req{border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:8px;padding:10px 12px;margin:10px 0;background:var(--hl)}
.req .who{font-size:16px;font-weight:600}.mono{font-family:Consolas,monospace}
#reqsec{border-color:var(--warn)}
</style></head><body>
<header><h1>TopoKit – licențe</h1></header>
<main>
<section id="login"><h2>Autentificare</h2>
 <div class="row"><input id="tok" type="password" placeholder="Parola de administrare (ADMIN_TOKEN)" size="40" autocomplete="current-password">
 <button id="go">Intră</button></div><p id="lerr" class="bad"></p></section>
<div id="app" class="hidden">
<section id="reqsec"><h2>Cereri de acces <span id="reqn" class="badge hidden"></span></h2>
 <p class="muted small" id="reqnone">Nicio cerere în așteptare. Când cineva instalează TopoKit și apasă „Cere acces”, cererea apare aici.</p>
 <div id="reqs"></div>
 <details id="recent"><summary class="muted">Cereri rezolvate recent (<span id="recentn">0</span>)</summary>
 <div class="wrap"><table><thead><tr><th>Când</th><th>Cine</th><th>Calculator</th><th>Decizie</th><th>Licență</th></tr></thead><tbody id="reqdone"></tbody></table></div></details>
 <p class="row muted small"><label><input type="checkbox" id="auto" checked> Actualizare automată (30 s)</label> <span id="upd"></span></p></section>
<section><h2>Coleg nou (cu cod de activare)</h2>
 <div class="row"><input id="nm" placeholder="Nume (apare în TopoKit și în documente)" size="34">
 <input id="em" placeholder="E-mail (opțional)" size="24"><label class="muted">Calculatoare <input id="mx" type="number" min="1" max="10" value="2" style="width:64px"></label>
 <button id="add">Adaugă și creează cod</button></div>
 <div id="newcode" class="hidden"><p>Codul de activare pentru <b id="ncname"></b> (o singură folosire, valabil <span id="ncdays"></span> zile):</p>
 <div class="code" id="nccode"></div> <button class="ghost" id="nccopy">Copiază mesajul</button>
 <p class="muted">Mesaj de trimis colegului:</p><div class="msg" id="ncmsg"></div></div></section>
<section><h2>Colegi</h2><div class="wrap"><table><thead><tr><th>Nume</th><th>Stare</th><th>Calculatoare (licențe)</th><th></th></tr></thead><tbody id="users"></tbody></table></div></section>
<section><h2>Activitate</h2><div class="wrap"><table><thead><tr><th>Când</th><th>Ce</th><th>Cine</th><th>Detalii</th><th>IP</th></tr></thead><tbody id="events"></tbody></table></div>
 <p><button class="ghost" id="out">Ieșire</button></p></section>
</div></main>
<script>
const $ = (id) => document.getElementById(id);
let token = ""; try { token = sessionStorage.getItem("tk") || ""; } catch (e) {}
const KIND = {activate:"Activare",activate_fail:"Activare refuzată",refresh_fail:"Reînnoire refuzată",deactivate:"Dezactivare",
  user_add:"Coleg adăugat",user_disable:"Acces oprit",user_enable:"Acces repornit",user_max:"Nr. calculatoare schimbat",code:"Cod nou",
  device_revoke:"Licență anulată",admin_fail:"Parolă admin greșită",clone_suspect:"Posibilă copiere (alt IP)",
  request:"Cerere de acces",request_fail:"Cerere: token greșit",request_approve:"Cerere acceptată",request_deny:"Cerere respinsă",
  request_delivered:"Licență preluată de TopoKit"};
const ERR = {too_many_devices:"Colegul a atins numărul maxim de calculatoare. Măriți numărul sau anulați licența altui calculator.",
  not_pending:"Cererea a fost deja rezolvată.",changed:"Cererea tocmai a fost retrimisă de pe calculator – încercați din nou.",
  user_disabled:"Accesul colegului este oprit – reporniți-l întâi.",name_required:"Scrieți numele colegului.",not_found:"Nu mai există."};
const fmt = (t) => t ? new Date(t * 1000).toLocaleString("ro-RO", {dateStyle:"short", timeStyle:"short"}) : "–";
const grp = (m) => (m || "").replace(/(.{6})(?=.)/g, "$1-");
function ago(s, t) { const d = Math.max(0, s - t); return d < 90 ? "acum" : d < 5400 ? "acum " + Math.round(d / 60) + " min" : d < 172800 ? "acum " + Math.round(d / 3600) + " h" : "acum " + Math.round(d / 86400) + " zile"; }
function el(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }
async function api(path, body, quiet) {
  const r = await fetch(path, {method: body ? "POST" : "GET", headers: {"authorization": "Bearer " + token, "content-type": "application/json"},
    body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) { logout("Parolă greșită."); throw new Error("401"); }
  if (!r.ok) { if (!quiet) alert(ERR[j.error] || ("Eroare: " + (j.error || r.status))); throw new Error(j.error || String(r.status)); }
  return j;
}
function logout(msg) { token = ""; try { sessionStorage.removeItem("tk"); } catch (e) {} $("app").classList.add("hidden"); $("login").classList.remove("hidden"); $("lerr").textContent = msg || ""; document.title = "TopoKit – licențe"; }
function showCode(name, c, days) {
  $("newcode").classList.remove("hidden"); $("ncname").textContent = name; $("nccode").textContent = c.code; $("ncdays").textContent = days;
  $("ncmsg").textContent = "Bună,\\n\\nCodul tău de activare TopoKit este:\\n\\n    " + c.code +
    "\\n\\n1. Instalează TopoKit (TopoKitSetup.exe).\\n2. Deschide fereastra TopoKit și apasă „Activați TopoKit” (sus, dreapta).\\n" +
    "3. Scrie codul și apasă Activează. Ai nevoie de internet doar la activare și măcar o dată la două săptămâni.\\n\\n" +
    "Codul merge o singură dată, până la " + fmt(c.expires_at) + ". Te rog să nu-l dai mai departe.";
  $("newcode").scrollIntoView({behavior: "smooth"});
}
// ce a ales administratorul la fiecare cerere rămâne la actualizarea automată
const drafts = {};
async function revoke(d, who, days) {
  if (!confirm("Anulați licența calculatorului " + (d.pc || "?") + (who ? " (" + who + ")" : "") + "?\\n\\nTopoKit se oprește pe acel calculator la următoarea verificare: de obicei în câteva ore, cel târziu în " + days + " zile dacă nu are internet.")) return;
  await api("/api/admin/devices/" + d.id + "/revoke", {}); load();
}
function renderRequests(s) {
  const pend = s.requests.filter((r) => r.status === "pending"), done = s.requests.filter((r) => r.status !== "pending");
  const devs = {}, active = {};
  for (const u of s.users) for (const d of u.devices) { devs[d.id] = {d, u}; if (!d.revoked && !u.disabled) (active[d.machine] = active[d.machine] || []).push(u); }
  $("reqn").textContent = pend.length; $("reqn").classList.toggle("hidden", !pend.length); $("reqnone").classList.toggle("hidden", pend.length > 0);
  document.title = (pend.length ? "(" + pend.length + ") " : "") + "TopoKit – licențe";
  const box = $("reqs"); box.textContent = "";
  for (const r of pend) {
    const dr = drafts[r.id] || (drafts[r.id] = {});
    const card = el("div", null, "req");
    const top = el("div", null, "row"); top.append(el("span", r.name, "who"));
    if (r.winuser) top.append(el("span", "Windows: " + r.winuser, "muted"));
    card.append(top);
    card.append(el("div", "Calculator: " + (r.pc || "?") + " · cod " + grp(r.machine) + " · TopoKit " + (r.version || "?"), "small"));
    card.append(el("div", "Trimisă " + fmt(r.updated_at) + (r.created_at !== r.updated_at ? " (prima dată " + fmt(r.created_at) + ")" : "") +
      (r.country ? " · țara " + r.country : "") + (r.ip ? " · IP " + r.ip : "") + (r.polled_at ? " · TopoKit a verificat " + ago(s.now, r.polled_at) : ""), "muted small"));
    const has = active[r.machine];
    if (has) card.append(el("div", "Acest calculator are deja licență activă pentru: " + has.map((u) => u.name).join(", ") + ".", "warn small"));
    const act = el("div", null, "row"); act.style.marginTop = "8px";
    act.append(el("span", "Acceptă pentru:", "small"));
    const sel = el("select"); const onew = el("option", "➕ Coleg nou"); onew.value = "new"; sel.append(onew);
    let pre = "new"; const lname = r.name.trim().toLowerCase();
    for (const u of s.users) {
      if (u.disabled) continue;
      const n = u.devices.filter((d) => !d.revoked).length, full = n >= u.max_devices && !u.devices.some((d) => !d.revoked && d.machine === r.machine);
      const o = el("option", u.name + " (" + n + "/" + u.max_devices + " calculatoare" + (full ? " – plin" : "") + ")"); o.value = String(u.id); sel.append(o);
      if (u.devices.some((d) => !d.revoked && d.machine === r.machine) || (pre === "new" && u.name.trim().toLowerCase() === lname)) pre = String(u.id);
    }
    sel.value = dr.sel || pre;
    const nm = el("input"); nm.size = 24; nm.value = dr.name != null ? dr.name : r.name; nm.placeholder = "Numele colegului";
    const mxl = el("label", "Calculatoare ", "muted small"); const mx = el("input"); mx.type = "number"; mx.min = "1"; mx.max = "10"; mx.style.width = "60px"; mx.value = dr.max || "2"; mxl.append(mx);
    const sync = () => { const isNew = sel.value === "new"; nm.classList.toggle("hidden", !isNew); mxl.classList.toggle("hidden", !isNew); };
    sel.onchange = () => { dr.sel = sel.value; sync(); }; nm.oninput = () => { dr.name = nm.value; }; mx.oninput = () => { dr.max = mx.value; };
    sync();
    const ba = el("button", "✔ Acceptă", "okb");
    ba.onclick = async () => {
      let body;
      if (sel.value === "new") { const name = nm.value.trim(); if (!name) { nm.focus(); return; } body = {new_name: name, max_devices: +mx.value || 2}; }
      else {
        const u = s.users.find((x) => String(x.id) === sel.value); body = {user_id: +sel.value};
        const n = u.devices.filter((d) => !d.revoked).length;
        if (n >= u.max_devices && !u.devices.some((d) => !d.revoked && d.machine === r.machine)) {
          if (!confirm(u.name + " are deja " + n + "/" + u.max_devices + " calculatoare.\\nMăriți la " + (u.max_devices + 1) + " și acceptați?")) return;
          body.max_devices = u.max_devices + 1;
        }
      }
      ba.disabled = true;
      try { await api("/api/admin/requests/" + r.id + "/approve", body); delete drafts[r.id]; } catch (e) {} finally { ba.disabled = false; }
      load();
    };
    const bn = el("button", "✖ Respinge", "danger");
    bn.onclick = async () => { if (!confirm("Respingeți cererea lui " + r.name + " (" + (r.pc || "?") + ")?")) return;
      try { await api("/api/admin/requests/" + r.id + "/deny", {}); delete drafts[r.id]; } catch (e) {} load(); };
    act.append(sel, nm, mxl, ba, bn); card.append(act); box.append(card);
  }
  $("recentn").textContent = done.length;
  const tb = $("reqdone"); tb.textContent = "";
  for (const r of done) {
    const tr = el("tr"); const who = el("td"); who.append(el("b", r.name)); if (r.winuser) who.append(el("div", "Windows: " + r.winuser, "muted small"));
    const dv = r.device_id ? devs[r.device_id] : null;
    const dec = r.status === "approved" ? el("td", "Acceptată" + (dv ? " → " + dv.u.name : ""), "ok") : el("td", "Respinsă", "bad");
    const lic = el("td");
    if (r.status === "approved" && dv) {
      if (dv.d.revoked) lic.append(el("span", "anulată", "muted"));
      else if (dv.u.disabled) lic.append(el("span", "acces oprit", "bad"));
      else {
        lic.append(el("div", r.delivered_at ? "activă (preluată " + fmt(r.delivered_at) + ")" : "așteaptă preluarea de către TopoKit", r.delivered_at ? "ok small" : "warn small"));
        const b = el("button", "Anulează licența", "cancel"); b.onclick = () => revoke(dv.d, dv.u.name, s.license_days); lic.append(b);
      }
    }
    tr.append(el("td", fmt(r.decided_at)), who, el("td", (r.pc || "?") + " · " + grp(r.machine), "small"), dec, lic); tb.append(tr);
  }
}
async function load(quiet) {
  const s = await api("/api/admin/state", null, quiet);
  $("login").classList.add("hidden"); $("app").classList.remove("hidden");
  renderRequests(s);
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
      dv.append(el("span", (d.pc || "?") + " · v" + (d.version || "?") + " · văzut " + fmt(d.last_seen) + (d.revoked ? " · licență anulată" : ""), old ? "warn" : ""));
      if (!d.revoked && !u.disabled) { const b = el("button", "Anulează licența", "cancel"); b.style.marginLeft = "8px"; b.style.padding = "3px 10px";
        b.onclick = () => revoke(d, u.name, s.license_days); dv.append(b); }
      c3.append(dv);
    }
    const c4 = el("td"); const row = el("div", null, "row");
    const bc = el("button", "Cod nou", "ghost"); bc.onclick = async () => { const c = await api("/api/admin/users/" + u.id + "/code", {}); showCode(u.name, c, Math.round((c.expires_at - Date.now() / 1000) / 86400)); }; row.append(bc);
    const bm = el("button", "Nr. calculatoare", "ghost"); bm.onclick = async () => { const v = prompt("Câte calculatoare poate activa " + u.name + "?", u.max_devices); if (v) { await api("/api/admin/users/" + u.id + "/max", {max_devices: +v}); load(); } }; row.append(bm);
    const bd = el("button", u.disabled ? "Repornește accesul" : "Oprește accesul (toate licențele)", u.disabled ? "ghost" : "danger");
    bd.onclick = async () => { if (u.disabled || confirm("Opriți accesul lui " + u.name + "? Licențele de pe toate calculatoarele lui se anulează la următoarea verificare (de obicei în câteva ore, cel târziu în " + s.license_days + " zile fără internet).")) { await api("/api/admin/users/" + u.id + (u.disabled ? "/enable" : "/disable"), {}); load(); } };
    row.append(bd); c4.append(row);
    tr.append(c1, st, c3, c4); tb.append(tr);
  }
  if (!s.users.length) { const tr = el("tr"); const td = el("td", "Niciun coleg încă – acceptați o cerere de acces sau adăugați un coleg mai sus.", "muted"); td.colSpan = 4; tr.append(td); tb.append(tr); }
  const te = $("events"); te.textContent = "";
  for (const e of s.events) { const tr = el("tr"); tr.append(el("td", fmt(e.at)), el("td", KIND[e.kind] || e.kind, /fail|clone/.test(e.kind) ? "bad" : ""), el("td", e.name || "–"), el("td", e.detail || ""), el("td", e.ip || "", "muted")); te.append(tr); }
  $("upd").textContent = "actualizat la " + new Date().toLocaleTimeString("ro-RO");
}
// actualizare automată la 30 s, doar cu pagina vizibilă și fără un câmp în lucru (o listă deschisă)
function busy() { const a = document.activeElement; return a && (a.tagName === "SELECT" || (a.tagName === "INPUT" && a.type !== "checkbox")) && $("app").contains(a); }
setInterval(() => { if (token && $("auto").checked && !document.hidden && !busy() && !$("app").classList.contains("hidden"))
  load(true).catch(() => { $("upd").textContent = "actualizarea automată a eșuat – reîncerc"; }); }, 30000);
document.addEventListener("visibilitychange", () => { if (!document.hidden && token && $("auto").checked && !$("app").classList.contains("hidden")) load(true).catch(() => {}); });
$("go").onclick = async () => { token = $("tok").value.trim(); try { sessionStorage.setItem("tk", token); } catch (e) {} try { await load(); } catch (e) {} };
$("tok").onkeydown = (e) => { if (e.key === "Enter") $("go").click(); };
$("add").onclick = async () => { const name = $("nm").value.trim(); if (!name) { $("nm").focus(); return; }
  const c = await api("/api/admin/users", {name, email: $("em").value.trim(), max_devices: +$("mx").value || 2}); $("nm").value = ""; $("em").value = "";
  showCode(name, c, Math.round((c.expires_at - Date.now() / 1000) / 86400)); load(); };
$("nccopy").onclick = () => navigator.clipboard && navigator.clipboard.writeText($("ncmsg").textContent);
$("out").onclick = () => logout();
if (token) load().catch(() => {});
</script></body></html>`;
