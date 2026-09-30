# TopoKit – instrumente AutoLISP pentru topografie și cadastru

Suită modulară AutoLISP + DCL pentru AutoCAD (în stilul TopoLT):

| Comandă | Modul |
|---|---|
| `TOPOKIT` / `MYTOPO` | Meniul grafic (DCL) cu cele 3 module și setările lor |
| `ADDVTX` | Corecție topologică – vertex-uri la intersecțiile poliliniilor |
| `EXPKMZ` | Export parcelă închisă în KMZ/KML (Stereo 70 → WGS84) + deschidere în Google Earth Pro |
| `INSCADRU` | Format A4…A0 (portrait/landscape), cadru și indicator la scară |

## Interfața

![Meniul principal TopoKit](docs/macheta_topokit.png)

*Machetă aproximativă a dialogului `TOPOKIT`. Imaginile sunt desenate de codul LISP real, prin
simularea funcțiilor `vector_image` / `fill_image`. Fonturile și dimensiunile exacte diferă în AutoCAD.*

- **Antet:** siglă (teodolit și rețea de triangulație) și o linie de separare colorată.
- **Pictograme pentru fiecare modul.** Pictograma corecției topologice marchează cu verde punctele de
  intersecție, calculate chiar cu funcțiile din `ADDVTX`.
- **Previzualizarea planșei:** proporțiile formatului, orientarea, cadrul interior, indicatorul și caroiajul
  se redesenează la orice modificare, atât în meniul principal, cât și în dialogul `INSCADRU`:

  ![Previzualizare A4 portrait, A3 landscape cu caroiaj, A0 landscape cu caroiaj](docs/previzualizare_plansa.png)
- **Opțiuni grupate pe module**, taste rapide (Alt+C / E / I / D) și o bară de stare cu toleranța,
  metoda de transformare (grilă sau Helmert) și planșa curentă.

## Instalare

1. Copiați `TopoKit.lsp`, `TopoKit.dcl` și `stereo70_etrs89A.gsb` în același folder (de preferat unul din *Support File Search Path*).
2. În AutoCAD: `APPLOAD` → `TopoKit.lsp` (sau adăugați-l în *Startup Suite*).
3. Rulați `TOPOKIT`.

Fișierul `.dcl` este opțional: dacă nu este găsit, `TopoKit.lsp` generează automat o copie
identică într-un fișier temporar. Funcționează în AutoCAD 2013+ (Windows), inclusiv versiunile
cu `LISPSYS = 1`. Mesajele din AutoCAD nu folosesc diacritice, ca să se afișeze corect indiferent de codificarea sistemului.

**Convenții:** unitatea desenului este metrul. Implicit, X din AutoCAD = Est (Y Stereo 70) și
Y din AutoCAD = Nord (X Stereo 70). Pentru desenele cu axele inversate bifați *Axe inversate*.

## 1. Corecție topologică – `ADDVTX`

- Selectați oricâte `LWPOLYLINE` / `POLYLINE` (2D sau 3D).
- Intersecțiile se calculează **în plan (XY)** între toate perechile de polilinii: segment–segment,
  segment–arc și arc–arc (arcele sunt tratate exact, pe baza bulge-ului).
- Opțional (*Include punctele de contact*, activ implicit), sunt tratate și punctele de contact:
  îmbinări în „T”, capete situate pe alt segment și capetele suprapunerilor colineare.
- Vertex-ul nou este proiectat exact pe segmentul fiecărei polilinii, astfel:
  - forma segmentelor nu se schimbă: la arce, bulge-ul se împarte exact în sub-arce;
  - cota Z se interpolează pe segmentul propriu (polilinii 3D); elevația LWPOLYLINE rămâne aceeași;
  - lățimile de segment se interpolează.
- Punctele aflate la o distanță mai mică decât toleranța (implicit 0.001 m) de un vertex existent sau
  de un alt punct nou sunt ignorate, ca să nu se creeze duplicate.
- Mesaj final: `S-au procesat X polilinii si s-au adaugat Y vertex-uri noi.`

Ce nu se procesează: plasele 3D, polifețele, poliliniile netezite (spline/curve-fit) și cele
neparalele cu planul XY, precum și poliliniile de pe straturi blocate (sunt raportate separat).
LWPOLYLINE își păstrează handle-ul. POLYLINE 2D/3D „clasice” se reconstruiesc (proprietățile și
datele extinse sunt copiate), deci primesc un handle nou.

## 2. Export KMZ – `EXPKMZ`

1. Selectați o polilinie închisă (flag *Closed* sau capete care coincid).
2. Vertex-urile sunt transformate din Stereo 70 în ETRS89/WGS84 direct în LISP:
   - **inversa proiecției stereografice oblice** (EPSG metoda 9809, sferă conformă Gauss) pe
     elipsoidul Krasovsky 1940: φ₀ = 46°N, λ₀ = 25°E, k₀ = 0.99975, FE = FN = 500 000 m;
   - **grila de distorsiuni NTv2** `stereo70_etrs89A.gsb` (metoda implicită, **precizie centimetrică**).
     Este sub-grila „ANCPI+TN”, derivată din grila oficială ANCPI/TransDatRO, cu pas de 35″ × 50″ (~1 km).
     Deplasările se interpolează biliniar, exact ca în PROJ `hgridshift`. Fișierul binar este citit
     direct din LISP (prin `ADODB.Stream`), așa că nu e nevoie de alte programe;
   - **Helmert 7 parametri** (rezervă) S-42 → WGS84 (EPSG:15994, *Coordinate Frame*):
     tx = 2.329 m, ty = −147.042 m, tz = −92.080 m, rx = 0.309″, ry = −0.325″, rz = −0.497″, ds = 5.69 ppm.
     Se folosește dacă grila lipsește sau pentru punctele din afara zonei acoperite de grilă, de exemplu
     la graniță. Numărul punctelor transformate astfel este raportat.

   | Metodă | Precizie |
   |---|---|
   | Grila NTv2 – față de cele 11 puncte de control ETRS89 publicate cu grila | 2–13 mm |
   | Grila NTv2 din LISP – față de PROJ `hgridshift` (296 de puncte aleatoare) | < 0.01 mm |
   | Helmert – față de grilă, pe teritoriul României | 0.3 m median, ~1.5 m (p99) |

   **Grila este inclusă în depozit** (`stereo70_etrs89A.gsb`, 5.7 MB). Păstrați-o în același folder cu
   `TopoKit.lsp`; se caută și în căile de suport AutoCAD și în folderul desenului. Dialogul `TOPOKIT` arată
   dacă a fost găsită. Sursa este [tudorbarascu/stereo70-etrs89](https://github.com/tudorbarascu/stereo70-etrs89),
   iar grila a fost generată de Daniel Urdă ([ntv2generator](https://github.com/danieluct/ntv2generator)) din grila
   ANCPI. Sursa nu precizează o licență. Punctele de control folosite la testare sunt în
   `tests/data/verification_points/`.

   Coordonatele rezultate sunt în ETRS89. Față de WGS84 actual (ITRF), ETRS89 diferă cu ~0.8 m în 2026
   din cauza derivei plăcii eurasiatice. Diferența este sub precizia imaginilor Google Earth, care au de
   regulă erori de 1–5 m, dar contează dacă folosiți coordonatele pentru măsurători GNSS. Pentru lucrări
   oficiale, TransDatRO rămâne referința.
3. Fișierul `NumeDesen_NumeParcela_AAAAMMZZ_hhmmss.kmz` se salvează în folderul desenului
   (sau în `C:\Temp` dacă desenul nu a fost salvat). Conține poligonul (contur roșu, umplere
   semitransparentă), suprafața, perimetrul și, opțional, punctele de contur numerotate.
   Arcele sunt densificate (16 sub-segmente).
4. KMZ-ul (arhiva ZIP cu `doc.kml`) este creat cu PowerShell `Compress-Archive`. Dacă PowerShell nu
   este disponibil, se salvează un fișier `.kml`.
5. Fișierul se deschide automat în Google Earth Pro, dacă aplicația este găsită (în registru sau în
   `Program Files`). Altfel se deschide cu aplicația asociată extensiei.

La coordonate în afara domeniului Stereo 70 (de exemplu axe inversate sau un sistem local) programul
cere confirmare înainte de export.

## 3. Format, cadru și indicator – `INSCADRU`

- Sub-dialogul permite alegerea formatului (A4, A3, A2, A1, A0), a orientării (Portrait/Landscape), a scării
  (1:100, 1:200, 1:500, 1:1000, 1:2000, 1:5000), a caroiajului și a textelor din indicator.
- Indicați colțul stânga-jos al formatului în Model Space.
- Factorul de scară este **f = scara / 1000** (mm pe hârtie → m în teren). Exemplu: A3 landscape
  420 × 297 mm la 1:500 → 210 × 148.5 m.
- Se desenează pe stratul **`L_CADRU`**:
  - cadrul exterior (marginea foii, grosime 0.25);
  - cadrul interior / spațiul util (grosime 0.50), cu margini de 20 mm la stânga și 5 mm (A4, A3)
    sau 10 mm (A2–A0) în rest;
  - indicatorul: blocul cu atribute `TK_CARTUS`, de 180 × 50 mm, în colțul dreapta-jos. Câmpurile
    sunt beneficiar, lucrare, titlu, executant, scară, format, întocmit, dată și nr. planșă.
    Scara, formatul și data se completează automat, iar câmpurile se pot edita cu `EATTEDIT`;
  - opțional, caroiajul de coordonate: cruci la 10 cm pe hârtie, la valori rotunde, cu gradații și
    etichete X/Y pe cadrul interior.

## Detalii tehnice

- Fiecare comandă are propriul `*error*`: variabilele de sistem `CMDECHO`, `OSMODE`, `ATTREQ` și
  `DIMZIN` se salvează la pornire și se restabilesc la final sau la anulare/eroare.
- Fișierul grilă se închide automat la sfârșitul exportului sau la eroare/anulare.
- Toate modificările unei comenzi formează un singur grup **UNDO**.
- Setările din dialog se păstrează pe toată durata sesiunii AutoCAD și sunt folosite și de comenzile directe.

## Dezvoltare

- După modificarea fișierului `TopoKit.dcl`, rulați `python3 tools/embed_dcl.py` ca să actualizați copia
  inclusă în `TopoKit.lsp`.
- `python3 tests/run_tests.py` rulează testele offline, fără AutoCAD, printr-un interpretor AutoLISP
  minimal. Testele acoperă conversia Stereo 70 → WGS84 comparată cu PROJ (dacă `pyproj` este instalat),
  comanda `ADDVTX` pe entități simulate (linii, arce, contacte în T, suprapuneri, polilinii 3D),
  caroiajul, validitatea XML a KML-ului și citirea grilei NTv2 față de punctele de control și față de PROJ. Interfața DCL și apelurile ActiveX pot fi testate
  doar în AutoCAD.
