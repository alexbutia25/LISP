# Serverul de licențe TopoKit

Un server mic pe **Cloudflare Workers** (gratuit pentru numărul de utilizatori al unei firme). El dă
licențe colegilor și le reînnoiește, iar din pagina de administrare oprești accesul cuiva. Codul e
tot în [`worker.js`](worker.js): un singur fișier, fără dependențe.

**Cum funcționează pentru coleg (de la 1.11.0, fără cod):**
1. Instalează TopoKit. Fereastra licenței se deschide singură.
2. Își scrie numele (propus din Windows) și apasă **Cere acces**.
3. Cererea apare la tine în `/admin`, la **Cereri de acces**. Apeși **Acceptă** sau **Respinge**.
4. TopoKit verifică singur cererea (la 2 minute cu fereastra licenței deschisă, altfel la 20 de
   minute și la fiecare pornire). La aprobare primește licența și anunță „Licența TopoKit a fost
   aprobată”; eticheta din fereastră devine **„✔ Numele lui”**.
5. Licența e semnată, valabilă **14 zile**, legată de calculatorul lui și se reînnoiește singură la
   6 ore când există internet. Fără internet merge până la 14 zile.

Activarea cu cod (**„⚠ Activați TopoKit”** → codul primit de la tine → **Activează**) merge în
continuare, de exemplu pentru cineva care nu poate aștepta aprobarea.

**Ce poți face tu din pagina `/admin`:**
- **Cereri de acces** (sus, cu numărul lor în titlul paginii): numele scris de coleg, utilizatorul
  Windows, numele și codul calculatorului, versiunea, țara și IP-ul, când a fost trimisă și când a
  verificat TopoKit ultima dată. **Acceptă pentru:** un coleg existent (propus automat dacă numele
  sau calculatorul se potrivesc) sau **➕ Coleg nou** (cu numele din cerere, pe care îl poți schimba,
  și numărul de calculatoare). Limita de calculatoare se respectă; dacă e plină, pagina te întreabă
  dacă o mărești. **Respinge** e definitiv pentru acea cerere (colegul poate trimite alta).
- **Cereri rezolvate recent** (30 de zile): cine, ce s-a decis, dacă TopoKit a preluat licența, și
  butonul **Anulează licența**.
- adaugi colegi și creezi coduri de activare (fiecare cod merge o singură dată și expiră în 14 zile);
- vezi calculatoarele fiecăruia, versiunea TopoKit și când au fost văzute ultima dată;
- **Anulează licența** (roșu, la fiecare calculator) sau **Oprește accesul (toate licențele)** la un
  coleg. TopoKit șterge licența la următoarea reînnoire: **cel mult ~6 ore** dacă lansatorul
  TopoKit rulează și are internet (implicit pornește cu Windows); fără internet sau fără lansator,
  cel târziu când expiră licența, **în 14 zile**. Un AutoCAD deja deschis cu TopoKit încărcat
  merge până la închidere.
- Pagina se actualizează singură la 30 de secunde cât e deschisă (se poate opri).

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

**1.11.0 (cererile de acces):** nicio variabilă, niciun secret și nicio legătură nouă. La prima
cerere după actualizare serverul adaugă singur tabela `requests` și indexurile ei (doar
`CREATE ... IF NOT EXISTS`, nimic nu se modifică sau se șterge). TopoKit 1.9 / 1.10 merge mai
departe neschimbat (activare cu cod, reînnoire). Pagina `/admin` nouă vine odată cu `worker.js`.

| Cerere (POST, JSON) | Răspuns |
|---|---|
| `/api/request` `{machine, pc, name, winuser, version}` | `{request, token, status: "pending"}` |
| `/api/request/status` `{request, token, machine}` | `{status: "pending"}`, `{status: "denied"}` sau `{status: "approved", device, license}` |
| `/api/admin/requests` (GET, cu parola) | `{now, requests}` (și în `/api/admin/state`) |
| `/api/admin/requests/<id>/approve` `{user_id}` sau `{new_name, max_devices}` | `{ok, user_id, device}` |
| `/api/admin/requests/<id>/deny` `{}` | `{ok}` |

- O singură cerere în așteptare pe calculator: o cerere repetată (reinstalare) o actualizează și
  primește un token nou; cel vechi nu mai merge.
- Tokenul (32 de octeți aleatori) e păstrat pe server doar ca hash. La aprobare devine secretul
  dispozitivului, deci serverul nu ține niciun secret în clar, iar `approved` se poate cere de mai
  multe ori (același dispozitiv, fără dubluri).
- Erori: `bad_request`, `name_required`, `rate_limited` (20 de cereri pe oră / IP sau rețea IPv6
  `/64`), `requests_full` (peste 200 în așteptare), `unknown_request` (token greșit, cerere
  înlocuită sau expirată), `machine`, `revoked` / `user_disabled` (licență anulată înainte de
  preluare); la administrare `not_pending`, `changed`, `too_many_devices`, `user_disabled`.
- Cererile nerezolvate expiră după 30 de zile; cele rezolvate se șterg după 180 de zile.
- „Posibilă copiere (alt IP)” se scrie acum pentru două reînnoiri din rețele diferite la mai puțin
  de **4 ore** (lansatorul 1.11.0 reînnoiește la 6 ore).

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

- **Coleg nou (simplu):** trimite-i instalatorul. El apasă **Cere acces**, tu apeși **Acceptă** în
  `/admin` (secțiunea **Cereri de acces**). Atenție: oricine are instalatorul poate trimite o
  cerere; acceptă doar nume și calculatoare pe care le recunoști.
- **Instalare automată:** `TopoKit.exe /request "Nume Prenume"` trimite cererea din linia de comandă
  (0 = trimisă, 1 = serverul nu răspunde, 2 = refuzată, 3 = licența e deja activă);
  `TopoKit.exe /request-status` o verifică (0 = aprobată / licență activă, 1 = fără răspuns,
  2 = respinsă, 3 = nicio cerere, 4 = în așteptare).
- **Coleg nou (cu cod):** în `/admin` → nume → **Adaugă și creează cod**. Copiază mesajul gata scris și
  trimite-l colegului, împreună cu instalatorul, pe un canal privat.
- **Calculator nou sau reinstalare:** **Cod nou** pentru colegul respectiv.
  - Pe același calculator, activarea veche se înlocuiește și nu ocupă un loc în plus.
  - Pe alt calculator, se ocupă al doilea loc; implicit sunt 2 calculatoare de coleg (butonul
    **Nr. calculatoare**).
- **Coleg plecat:** **Oprește accesul (toate licențele)**.
- **Calculator pierdut:** **Anulează licența** la calculatorul respectiv.
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
  aceluiași calculator, din rețele diferite, la mai puțin de 4 ore, apar în jurnal ca **„Posibilă
  copiere (alt IP)”**. Atunci anulează licența calculatorului și lasă colegul să ceară acces din nou.
- **Cererile de acces:** oricine are instalatorul poate trimite o cerere, dar nu primește nimic
  până nu o accepți. Tokenul cererii (`request.dat`, DPAPI pe calculatorul colegului) se păstrează
  pe server doar ca hash. Se primesc cel mult 20 de cereri pe oră de la aceeași adresă și cel mult
  200 în așteptare.
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
  - Cererile de acces: `TopoKit.exe /request` → aprobare / respingere în API-ul de administrare →
    `/request-status`, plus coleg existent / nou, limita de calculatoare, curse, limite și expirare.
  - `--serve`: doar serverul, ca să vezi pagina `/admin` la `http://127.0.0.1:8766/admin`
    (parola de test e în `tests/server_harness.py`).
  - Variante: `--api-only` (fără gcc), `--browser none` (deschizi tu pagina), `--launcher-src DIR`
    (altă versiune a lansatorului, de ex. 1.9.0, pentru compatibilitate).
