# Serverul de licențe TopoKit

Un server mic pe **Cloudflare Workers** (gratuit pentru numărul de utilizatori al unei firme). El dă
licențe colegilor și le reînnoiește, iar din pagina de administrare oprești accesul cuiva. Codul e
tot în [`worker.js`](worker.js): un singur fișier, fără dependențe.

**Cum funcționează pentru coleg:**
1. Instalează TopoKit.
2. În fereastra TopoKit apasă **„⚠ Activați TopoKit”** și scrie codul primit de la tine.
3. TopoKit primește o licență semnată, valabilă **14 zile**, legată de calculatorul lui.
4. Licența se reînnoiește singură, zilnic, când există internet. Fără internet merge până la 14 zile.

**Ce poți face tu din pagina `/admin`:**
- adaugi colegi și creezi coduri de activare (fiecare cod merge o singură dată și expiră în 14 zile);
- vezi calculatoarele fiecăruia, versiunea TopoKit și când au fost văzute ultima dată;
- scoți un calculator sau oprești accesul unui coleg; licența dispare la următoarea verificare,
  cel târziu în 14 zile.

## Punerea în funcțiune (o singură dată, ~20 de minute)

### 1. Cheia de semnare și parola de administrare

Pe calculatorul tău, din folderul proiectului:

```bash
python tools/licenta.py cheie --out D:\TopoKit-chei
```

```bash
python tools/licenta.py secret
```

- Prima comandă face `D:\TopoKit-chei\topokit_cheie_semnare.json` (**cheia privată**) și scrie cheia
  publică în `installer/licensing.json`.
- **Cheia privată nu se pune niciodată în proiect, pe GitHub sau pe un folder partajat.** Folderul
  `D:\TopoKit-chei` e doar un exemplu; alege unul în afara proiectului. Fă și o copie pe un stick
  păstrat separat. Cine are cheia poate face licențe.
- A doua comandă afișează o parolă lungă pentru pagina de administrare. Păstreaz-o, de exemplu
  într-un manager de parole.

### 2. Contul Cloudflare

- Fă-ți cont pe [dash.cloudflare.com](https://dash.cloudflare.com) (planul gratuit e suficient).
- **Activează autentificarea în doi pași** (My Profile → Authentication). Contul ține cheia de semnare.

### 3a. Serverul, direct din browser (fără instalări)

1. **Storage & Databases → D1 → Create database**, nume `topokit-licente`.
2. **Compute (Workers) → Create → Worker**, nume `topokit-licente` → **Deploy**.
3. **Edit code** → șterge tot → lipește conținutul lui `server/worker.js` → **Deploy**.
4. Worker → **Settings → Bindings → Add → D1 database**: variabila `DB`, baza `topokit-licente`.
5. Worker → **Settings → Variables and Secrets → Add**, tip **Secret**:
   - `SIGNING_KEY` = tot conținutul fișierului `topokit_cheie_semnare.json`;
   - `ADMIN_TOKEN` = parola de la pasul 1.
6. Tabelele bazei de date se creează singure la prima cerere.
7. Opțional: Worker → **Settings → Triggers → Cron Triggers → Add**, de exemplu `17 3 * * *` (zilnic).
   Curăță jurnalul (180 de zile) și când nimeni nu intră în `/admin` și nu se face nicio activare.

### Actualizarea serverului

Lipește din nou `server/worker.js` în **Edit code** → **Deploy**. Baza de date rămâne cum e:
versiunile noi nu schimbă tabelele, iar TopoKit-ul deja instalat (1.9.0) merge mai departe.
(De la 1.10.0, la reactivarea aceluiași calculator rămâne activarea cu cel mai nou `created_at`, apoi
`id`; nu se mai folosește `rowid`-ul implicit, care se poate renumerota. Rândurile existente rămân valabile.)

### 3b. Sau cu wrangler (dacă ai Node.js)

```bash
npx wrangler login
```

```bash
npx wrangler d1 create topokit-licente
```

```bash
npx wrangler secret put SIGNING_KEY < D:\TopoKit-chei\topokit_cheie_semnare.json
```

```bash
npx wrangler secret put ADMIN_TOKEN
```

```bash
npx wrangler deploy
```

- Rulează comenzile din folderul `server/`.
- Între a doua și a treia comandă copiază `database_id` afișat de `d1 create` în `wrangler.toml`.

### 4. Verificarea și legarea de TopoKit

1. Deschide `https://topokit-licente.<subdomeniul-tău>.workers.dev/api/ping`. Trebuie să apară `{"ok":true,...}`.
2. Deschide `.../admin` și intră cu parola de administrare.
3. Rulează comanda de mai jos. Adresa se scrie în `installer/licensing.json`.

```bash
python tools/licenta.py server https://topokit-licente.<subdomeniul-tău>.workers.dev
```

4. Construiește instalatorul. Ieșirea trebuie să arate `Licentiere: DA`:

```bash
python tools/build_installer.py
```

Din acest moment, **orice instalare TopoKit cere activarea, inclusiv pe calculatorul tău**. Adaugă-te
și pe tine în pagina `/admin`.

## Utilizarea zilnică

- **Coleg nou:** în `/admin` → nume → **Adaugă și creează cod**. Copiază mesajul gata scris și
  trimite-l colegului, împreună cu instalatorul, pe un canal privat.
- **Calculator nou sau reinstalare:** **Cod nou** pentru colegul respectiv.
  - Pe același calculator, activarea veche se înlocuiește și nu ocupă un loc în plus.
  - Pe alt calculator, se ocupă al doilea loc; implicit sunt 2 calculatoare de coleg (butonul
    **Nr. calculatoare**).
- **Coleg plecat:** **Oprește accesul**.
- **Calculator pierdut:** **Scoate** la calculatorul respectiv.
- **Coleg fără internet:** emite o licență de rezervă (90 de zile) pentru codul lui de calculator,
  afișat în fereastra de activare. El o importă cu **Importă fișier…**.

```bash
python tools/licenta.py emite --cheie D:\TopoKit-chei\topokit_cheie_semnare.json --nume "Ion Popescu" --calculator A1B2C3-D4E5F6-A1B2C3-D4E5F6
```

## Siguranță

- **Licența:** e semnată ECDSA P-256. TopoKit verifică semnătura cu cheia publică compilată în
  `TopoKit.exe`, deci fără cheia privată nu se pot face licențe.
- **Pe calculatorul colegului:** secretul dispozitivului e protejat cu DPAPI, adică doar acel
  utilizator Windows îl poate citi.
- **Ceasul dat înapoi:** `TopoKit.exe` ține minte cea mai nouă oră văzută (`seen.dat` și registrul) și
  refuză o licență dacă ceasul a fost dat înapoi cu peste o zi. Programele Python (DWG to KMZ, Plan
  Înclinare, `tklic.py`) doar citesc această oră, nu o avansează; o avansează lansatorul, de fiecare
  dată când găsește o licență bună (rulează în fundal și la `TopoKit.exe /license` din AutoCAD).
- **Codurile de activare:** se păstrează doar ca hash. Un cod are ~73 de biți aleatori, deci nu se
  poate ghici. Fiecare cod merge o singură dată, și la activări simultane. Nici activările simultane
  cu coduri diferite nu trec de numărul maxim de calculatoare.
- **Încercări:** după 20 de coduri greșite pe oră de la aceeași adresă se refuză orice încercare.
  La pagina de administrare limita e 10 parole greșite pe oră.
  - Adresa e cea dată de Cloudflare (`CF-Connecting-IP`). Antete ca `X-Forwarded-For` nu contează.
  - La IPv6 se numără toată rețeaua `/64`, nu fiecare adresă din ea.
  - Pentru atacuri din multe rețele, poți adăuga o regulă gratuită în Cloudflare: **Security → WAF →
    Rate limiting rules**, de exemplu 30 de cereri pe minut / IP pentru `/api/`.
- **Parola de administrare:** folosește-o pe cea dată de `licenta.py secret` (256 de biți), nu una
  aleasă de mână.
- **Copierea unei activări pe alt calculator:** licența e legată de codul calculatorului. Cineva cu
  drepturi de administrator poate totuși copia pe alt PC codul calculatorului (MachineGuid și seria
  discului) și secretul din `state.dat`. Serverul nu poate opri asta, dar o arată: două reînnoiri ale
  aceluiași calculator, din rețele diferite, la mai puțin de 6 ore, apar în jurnal ca **„Posibilă
  copiere (alt IP)”**. Atunci scoate calculatorul și dă-i colegului un cod nou.
- **Cheia pierdută sau compromisă:**
  1. Fă o cheie nouă: `licenta.py cheie --out ... --kid k2 --force`.
  2. Pune-o ca `SIGNING_KEY` pe server.
  3. Construiește și distribuie un instalator nou.
  4. Licențele vechi nu mai sunt acceptate de instalatorul nou. Colegii activați primesc licența
     nouă la prima reînnoire.
- **Ce date se păstrează:** numele colegului, codul calculatorului (un hash, nu date personale),
  numele calculatorului, versiunea TopoKit și adresa IP. Evenimentele mai vechi de 180 de zile se
  șterg singure.
- **Limitare:** fără compilarea modulelor (pasul următor din plan: FAS/VLX și Nuitka), verificarea
  din fișierele `.lsp` se poate ocoli de cineva care știe AutoLISP. Licența oprește copierea
  ocazională, nu un programator hotărât.

## Teste

- `python tests/test_licenta.py` (offline): formatul licenței, `TopoKit.exe` compilat cu o cheie de
  test, contra unui server simulat, interogările SQL, încărcătorul AutoCAD, programele Python.
- `python tests/server_harness.py`: testul complet cu `worker.js` real, rulat într-un browser
  (Chrome/Edge headless), pentru că pe calculatorul de dezvoltare nu există Node.js.
  - Compilează singur `TopoKit.exe` cu o cheie de test.
  - Verifică activări simultane, limitele de încercări, cereri stricate, antetele și jurnalul.
  - Variante: `--api-only` (fără gcc), `--browser none` (deschizi tu pagina), `--launcher-src DIR`
    (altă versiune a lansatorului, de ex. 1.9.0, pentru compatibilitate).
