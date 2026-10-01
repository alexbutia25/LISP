;;; ==========================================================================
;;;  TopoKitAnexe.lsp  -  Generatorul de anexe pentru Ordinul ANCPI nr. 600/2023
;;;  (Regulamentul de recepție și înscriere în evidențele de cadastru și CF)
;;; ==========================================================================
;;;
;;;  Comenzi:
;;;    ANEXE       - meniul generatorului: alegerea anexelor/pachetelor, datele
;;;                  lucrării și generarea pieselor desenate și a celor Word
;;;    PAD         - Anexa 16: plan de amplasament și delimitare (layout nou)
;;;    PADDEZ      - Anexa 17: PAD cu propunerea de dezlipire + PAD pe loturi
;;;    PADALIP     - Anexa 17 (alipire): PAD cu propunerea de alipire + PAD rezultat
;;;    VECINI      - laturile imobilului: vecini, identificatori, materializare
;;;    DATEIMOBIL  - datele imobilului și ale proprietarilor (salvate în desen)
;;;    EXECUTANT   - datele persoanei autorizate (salvate pe calculator)
;;;    CONSTRUCTIE - datele unei construcții (cod C1.., destinație, Sd, an...)
;;;    RELEVEU     - Anexa 18: tabelul încăperilor și cartușul releveului
;;;    ANEXEWORD   - generează anexele Word selectate (.docx/.pdf)
;;;
;;;  Piesele desenate se creează în LAYOUT-uri separate (pagină A4..A0 cu
;;;  setări DWG To PDF): cadrul, tabelele, numerotarea punctelor, cotele
;;;  laturilor și vecinii se desenează în paper space peste un viewport la
;;;  scara aleasă; desenul din model space rămâne neatins.
;;;  Piesele Word se completează din șabloanele din folderul "anexe" (generate
;;;  din textul oficial al ordinului) prin scriptul anexe\TopoKitDocx.ps1.
;;;
;;;  Necesită TopoKit.lsp (încărcat automat dacă este găsit).
;;;  Textele afișate în AutoCAD folosesc coduri \U+XXXX pentru diacritice, iar
;;;  în sursă marcajele: `a=ă `A=Ă ^a=â ^A=Â ^i=î ^I=Î `s=ș `S=Ș `t=ț `T=Ț.
;;; ==========================================================================

(vl-load-com)

;; Dependența: funcțiile comune din TopoKit.lsp (*TKA:LOADING* împiedică
;; reîncărcarea acestui fișier de către TopoKit.lsp)
(setq *TKA:LOADING* T)
(if (and (not TK:Start) (findfile "TopoKit.lsp")) (load (findfile "TopoKit.lsp")))
(if (not TK:Start)
  (alert "TopoKitAnexe.lsp necesita TopoKit.lsp (in acelasi folder, in calea de suport AutoCAD)."))

;;; ==========================================================================
;;;  TEXTE ȘI CODIFICARE
;;; ==========================================================================

;; Tabelul marcajelor de diacritice din sursă -> cod Unicode
(setq *TKA:DIA* '(("`a" . 259) ("`A" . 258) ("^a" . 226) ("^A" . 194) ("^i" . 238)
                  ("^I" . 206) ("`s" . 537) ("`S" . 536) ("`t" . 539) ("`T" . 538)))

;; Tabelele de cod ANSI 1250 / 1252 (octeții 128..255 -> Unicode), folosite
;; doar pe versiunile AutoCAD fără AutoLISP Unicode
(setq *TKA:CP1250*
  '(8364 63 8218 63 8222 8230 8224 8225 63 8240 352 8249 346 356 381 377 63 8216 8217 8220 8221 8226 8211 8212 63
    8482 353 8250 347 357 382 378 160 711 728 321 164 260 166 167 168 169 350 171 172 173 174 379 176 177 731 322
    180 181 182 183 184 261 351 187 317 733 318 380 340 193 194 258 196 313 262 199 268 201 280 203 282 205 206 270
    272 323 327 211 212 336 214 215 344 366 218 368 220 221 354 223 341 225 226 259 228 314 263 231 269 233 281
    235 283 237 238 271 273 324 328 243 244 337 246 247 345 367 250 369 252 253 355 729))
(setq *TKA:CP1252*
  '(8364 63 8218 402 8222 8230 8224 8225 710 8240 352 8249 338 63 381 63 63 8216 8217 8220 8221 8226 8211 8212 732
    8482 353 8250 339 63 382 376 160 161 162 163 164 165 166 167 168 169 170 171 172 173 174 175 176 177 178 179
    180 181 182 183 184 185 186 187 188 189 190 191 192 193 194 195 196 197 198 199 200 201 202 203 204 205 206 207
    208 209 210 211 212 213 214 215 216 217 218 219 220 221 222 223 224 225 226 227 228 229 230 231 232 233 234
    235 236 237 238 239 240 241 242 243 244 245 246 247 248 249 250 251 252 253 254 255))

;; TKA:Hex4 - număr -> 4 cifre hexazecimale (pentru \U+XXXX și \uXXXX)
(defun TKA:Hex4 (n / s)
  (setq s "")
  (repeat 4
    (setq s (strcat (substr "0123456789ABCDEF" (1+ (rem n 16)) 1) s)
          n (/ n 16)))
  s)

;; TKA:R - text românesc pentru entitățile AutoCAD: marcajele de diacritice
;; devin coduri \U+XXXX (afișate corect de TEXT/MTEXT în orice versiune)
(defun TKA:R (s / out i n p)
  (setq out "" i 1 n (strlen s))
  (while (<= i n)
    (if (setq p (assoc (substr s i 2) *TKA:DIA*))
      (setq out (strcat out "\\U+" (TKA:Hex4 (cdr p))) i (+ i 2))
      (setq out (strcat out (substr s i 1)) i (1+ i))))
  out)

;; TKA:Real - text cu diacriticele reale (valori pentru câmpurile dialogurilor
;; și pentru datele salvate): marcajele devin caractere Unicode (AutoCAD 2021+)
;; sau ANSI 1250; pe alte pagini de cod rămân literele fără diacritice
(defun TKA:Real (s / out i n p c)
  (setq out "" i 1 n (strlen s))
  (while (<= i n)
    (if (setq p (assoc (substr s i 2) *TKA:DIA*))
      (setq c (TKA:Chr (cdr p))
            out (strcat out (if (= c "?") (substr (car p) 2 1) c))
            i (+ i 2))
      (setq out (strcat out (substr s i 1)) i (1+ i))))
  out)

;; TKA:Chr - caracterul cu codul Unicode C: direct în AutoLISP Unicode, altfel
;; octetul din pagina de cod ANSI a sistemului (1250 sau 1252) sau "?"
(defun TKA:Chr (c / b)
  (cond ((or (< c 128) (TKA:Unicode?)) (chr c))
        ((setq b (vl-position c (if (wcmatch (strcase (cond ((getvar "SYSCODEPAGE")) (""))) "*1252")
                                  *TKA:CP1252* *TKA:CP1250*)))
         (chr (+ 128 b)))
        (T "?")))

;; TKA:Decode - codurile \U+XXXX dintr-un text din desen devin caractere
(defun TKA:Decode (s / i h)
  (setq i 0)
  (while (setq i (vl-string-search "\\U+" s i))
    (if (setq h (TKA:HexVal (substr s (+ i 4) 4)))
      (setq s (strcat (substr s 1 i) (TKA:Chr h) (substr s (+ i 8))))
      (setq i (1+ i))))
  s)

;; TKA:Unicode? - T dacă AutoLISP lucrează cu șiruri Unicode (AutoCAD 2021+)
(defun TKA:Unicode? ()
  (and (numberp (getvar "LISPSYS")) (> (getvar "LISPSYS") 0)))

;; TKA:CodePoint - codul Unicode al unui caracter returnat de vl-string->list
(defun TKA:CodePoint (c)
  (cond
    ((< c 128) c)
    ((TKA:Unicode?) c)
    ((< c 256)
     (nth (- c 128) (if (wcmatch (strcase (cond ((getvar "SYSCODEPAGE")) (""))) "*1252")
                      *TKA:CP1252* *TKA:CP1250*)))
    (T c)))

;; TKA:HexVal - valoarea unui șir hexazecimal (sau nil dacă nu este valid)
(defun TKA:HexVal (s / v ok c)
  (setq v 0 ok (> (strlen s) 0))
  (foreach c (vl-string->list (strcase s))
    (cond ((<= 48 c 57) (setq v (+ (* v 16) (- c 48))))
          ((<= 65 c 70) (setq v (+ (* v 16) (- c 55))))
          (T (setq ok nil))))
  (if ok v))

;; TKA:Json - șir JSON ASCII: diacriticele (marcaje, \U+XXXX, caractere
;; Unicode sau ANSI) devin secvențe \uXXXX, independent de versiunea AutoCAD
(defun TKA:Json (s / l out c h)
  (setq l (vl-string->list (TKA:R (if s s ""))) out (list 34))
  (while l
    (setq c (car l) l (cdr l))
    (cond
      ((and (= c 92) (= (car l) 85) (= (cadr l) 43) (nth 5 l)
            (setq h (TKA:HexVal (vl-list->string (list (nth 2 l) (nth 3 l) (nth 4 l) (nth 5 l))))))
       (setq out (append (reverse (vl-string->list (strcat "\\u" (TKA:Hex4 h)))) out)
             l (cdddr (cdddr l))))
      ((= c 34) (setq out (append (list 34 92) out)))
      ((= c 92) (setq out (append (list 92 92) out)))
      ((= c 10) (setq out (append (list 110 92) out)))
      ((= c 9) (setq out (cons 32 out)))
      ((< c 32))
      ((> c 126)
       (setq out (append (reverse (vl-string->list (strcat "\\u" (TKA:Hex4 (TKA:CodePoint c))))) out)))
      (T (setq out (cons c out)))))
  (vl-list->string (reverse (cons 34 out))))

;; TKA:Num - număr cu D zecimale și separatorul zecimal ales ("," sau ".")
(defun TKA:Num (x d / s)
  (setq s (rtos x 2 d))
  (if (= *TKA:SEPDEC* ",") (TK:StrReplace s "." ",") s))

;; TKA:Int - rotunjire la întreg (pentru suprafețe în mp)
(defun TKA:Int (x) (if (minusp x) (- (fix (+ (- x) 0.5))) (fix (+ x 0.5))))

;; TKA:Trim - elimină spațiile de la capete (nil -> "")
(defun TKA:Trim (s) (if s (vl-string-trim " \t" s) ""))

;; TKA:Join - concatenează lista L cu separatorul SEP (ignoră elementele vide)
(defun TKA:Join (l sep / out)
  (foreach s l
    (if (and s (/= (TKA:Trim s) ""))
      (setq out (if out (strcat out sep (TKA:Trim s)) (TKA:Trim s)))))
  (if out out ""))

;; TKA:Split - împarte șirul S după caracterul separator SEP
(defun TKA:Split (s sep / i out)
  (while (setq i (vl-string-search sep s))
    (setq out (cons (substr s 1 i) out) s (substr s (+ i 1 (strlen sep)))))
  (reverse (cons s out)))

;; TKA:MtextPlain - textul simplu dintr-un MTEXT (fără coduri de formatare)
(defun TKA:MtextPlain (s / out i n c d)
  (setq out "" i 1 n (strlen s))
  (while (<= i n)
    (setq c (substr s i 1))
    (cond
      ((member c '("{" "}")) (setq i (1+ i)))
      ((and (= c "\\") (< i n))
       (setq d (substr s (1+ i) 1))
       (cond
         ((member d '("P" "~")) (setq out (strcat out " ") i (+ i 2)))
         ((member d '("\\" "{" "}")) (setq out (strcat out d) i (+ i 2)))
         ((= d "U") (setq out (strcat out (TKA:Decode (substr s i 7))) i (+ i 7)))
         ((member d '("L" "l" "O" "o" "K" "k")) (setq i (+ i 2)))
         (T ; \f...; \H...; \C...; etc. până la ";"
          (setq i (+ i 2))
          (while (and (<= i n) (/= (substr s i 1) ";")) (setq i (1+ i)))
          (setq i (1+ i)))))
      (T (setq out (strcat out c) i (1+ i)))))
  (TKA:Trim out))

;;; ==========================================================================
;;;  DATELE LUCRĂRII
;;; ==========================================================================
;;;  - datele imobilului, proprietarilor și ale lucrării: în desen
;;;    (dicționarul TOPOKIT_ANEXE, cheia DATE)
;;;  - datele executantului: pe calculator (registrul AutoCAD, setenv)
;;;  - datele construcțiilor, laturilor și loturilor: pe entitățile din desen
;;;    (vlax-ldata, cheia TOPOKIT)
;;; ==========================================================================

(setq *TKA:DICT* "TOPOKIT_ANEXE")

;; Opțiuni implicite (păstrate pe durata sesiunii)
(foreach p '((*TKA:SEPDEC*  . ",")      ; separatorul zecimal pe planuri/anexe
             (*TKA:FORMAT*  . "AUTO")   ; AUTO, A4P, A3P, A3L, A2L, A1L, A0L
             (*TKA:SCARA*   . 0)        ; 0 = automat, altfel numitorul scării
             (*TKA:NRSTART* . 1)        ; primul număr de punct
             (*TKA:NRMOD*   . "NV")     ; NV = orar din punctul cel mai de N-V; POL = ordinea poliliniei
             (*TKA:INVPAD*  . "0")      ; inventarul de coordonate pe PAD
             (*TKA:PDF*     . "0")      ; conversie PDF a anexelor Word
             (*TKA:OPENDIR* . "1")      ; deschide folderul cu anexele generate
             (*TKA:ANEXA16* . "Anexa nr. 16")
             (*TKA:ANEXA17* . "Anexa nr. 17"))
  (if (null (eval (car p))) (set (car p) (cdr p))))

;; TKA:Data - lista de asociere (CHEIE . "valoare") a lucrării curente
(defun TKA:Data () (vlax-ldata-get *TKA:DICT* "DATE"))

;; TKA:Get - valoarea unui câmp al lucrării ("" dacă lipsește)
(defun TKA:Get (k / v)
  (if (setq v (cdr (assoc k (TKA:Data)))) v ""))

;; TKA:Put - modifică un câmp al lucrării (salvat în desen)
(defun TKA:Put (k v / d)
  (setq d (TKA:Data))
  (setq d (if (assoc k d) (subst (cons k v) (assoc k d) d) (append d (list (cons k v)))))
  (vlax-ldata-put *TKA:DICT* "DATE" d)
  v)

;; TKA:EGet / TKA:EPut - datele executantului (registrul AutoCAD)
(defun TKA:EGet (k / v) (if (setq v (getenv (strcat "TopoKit_" k))) v ""))
(defun TKA:EPut (k v) (setenv (strcat "TopoKit_" k) (if v v "")) v)

;; TKA:LGet / TKA:LPut - datele atașate unei entități (alist CHEIE . valoare)
(defun TKA:LGet (e k) (cdr (assoc k (vlax-ldata-get e "TOPOKIT"))))
(defun TKA:LPut (e k v / d)
  (setq d (vlax-ldata-get e "TOPOKIT"))
  (setq d (if (assoc k d) (subst (cons k v) (assoc k d) d) (append d (list (cons k v)))))
  (vlax-ldata-put e "TOPOKIT" d)
  v)

;; TKA:Handle / TKA:FromHandle - referințe persistente la entități
(defun TKA:Handle (e) (cdr (assoc 5 (entget e))))
(defun TKA:FromHandle (h / e)
  (if (and h (/= h "") (setq e (handent h)) (entget e)) e))

;; Categoriile de folosință (art. 285 din regulament)
(setq *TKA:CATEG*
  '(("A" . "Arabil") ("V" . "Vii") ("L" . "Livezi") ("P" . "P`a`suni") ("F" . "F^ane`te")
    ("PD" . "P`aduri") ("HR" . "Ape curg`atoare") ("HB" . "Ape st`at`atoare")
    ("DR" . "Drumuri") ("CF" . "C`ai ferate") ("CC" . "Cur`ti construc`tii")
    ("C" . "Construc`tii") ("N" . "Neproductiv")))
;; Destinațiile construcțiilor
(setq *TKA:DEST*
  '(("CL" . "Construc`tie de locuin`te") ("CAS" . "Construc`tie administrativ`a `si social-cultural`a")
    ("CIE" . "Construc`tie industrial`a `si edilitar`a") ("CA" . "Construc`tie anex`a")))

;; TKA:CategText - denumirea unei categorii de folosință (după cod)
(defun TKA:CategText (c / p)
  (if (setq p (assoc (strcase (TKA:Trim c)) *TKA:CATEG*)) (cdr p) c))

;;; ==========================================================================
;;;  GEOMETRIE ȘI NUMEROTAREA PUNCTELOR
;;; ==========================================================================

;; TKA:PolyPts - punctele 2D (WCS) ale unei polilinii, fără capătul duplicat
(defun TKA:PolyPts (e / n i pts)
  (setq n (fix (+ 0.5 (vlax-curve-getEndParam e))) i 0)
  (repeat n
    (setq pts (cons (TK:2d (vlax-curve-getPointAtParam e (float i))) pts) i (1+ i)))
  (if (not (vlax-curve-isClosed e)) (setq pts (cons (TK:2d (vlax-curve-getEndPoint e)) pts)))
  (setq pts (TK:DropDup (reverse pts)))
  (if (and (cdr pts) (equal (car pts) (last pts) 1e-6)) (setq pts (reverse (cdr (reverse pts)))))
  pts)

;; TKA:SArea - aria cu semn a poligonului (pozitivă = sens trigonometric)
(defun TKA:SArea (pts / a)
  (setq a 0.0)
  (mapcar '(lambda (p q) (setq a (+ a (- (* (car p) (cadr q)) (* (car q) (cadr p))))))
          pts (append (cdr pts) (list (car pts))))
  (/ a 2.0))

;; TKA:Area - suprafața poliliniei (include eventualele arce)
(defun TKA:Area (e) (abs (vlax-curve-getArea e)))

;; TKA:Perim - perimetrul unui poligon dat prin puncte
(defun TKA:Perim (pts / s)
  (setq s 0.0)
  (mapcar '(lambda (p q) (setq s (+ s (distance p q)))) pts (append (cdr pts) (list (car pts))))
  s)

;; TKA:Centroid - centrul de greutate al poligonului
(defun TKA:Centroid (pts / a cx cy f)
  (setq a 0.0 cx 0.0 cy 0.0)
  (mapcar '(lambda (p q)
             (setq f (- (* (car p) (cadr q)) (* (car q) (cadr p)))
                   a (+ a f) cx (+ cx (* (+ (car p) (car q)) f)) cy (+ cy (* (+ (cadr p) (cadr q)) f))))
          pts (append (cdr pts) (list (car pts))))
  (if (< (abs a) 1e-9)
    (TK:Mid (car pts) (cadr pts))
    (list (/ cx (* 3.0 a)) (/ cy (* 3.0 a)))))

;; TKA:Inside - T dacă punctul P se află în interiorul poligonului PTS
(defun TKA:Inside (p pts / in)
  (mapcar '(lambda (a b)
             (if (and (/= (> (cadr a) (cadr p)) (> (cadr b) (cadr p)))
                      (< (car p) (+ (car a) (/ (* (- (car b) (car a)) (- (cadr p) (cadr a))) (- (cadr b) (cadr a))))))
               (setq in (not in))))
          pts (append (cdr pts) (list (car pts))))
  in)

;; TKA:LabelPoint - un punct interior potrivit pentru etichete (centroidul
;; sau, pentru poligoane concave, un punct de pe linia mediană interioară)
(defun TKA:LabelPoint (pts / c bb y xs best w)
  (setq c (TKA:Centroid pts))
  (if (TKA:Inside c pts)
    c
    (progn
      (setq y (cadr c) xs nil)
      (mapcar '(lambda (a b)
                 (if (/= (> (cadr a) y) (> (cadr b) y))
                   (setq xs (cons (+ (car a) (/ (* (- (car b) (car a)) (- y (cadr a))) (- (cadr b) (cadr a)))) xs))))
              pts (append (cdr pts) (list (car pts))))
      (setq xs (vl-sort xs '<) w 0.0)
      (while (cdr xs)
        (if (> (- (cadr xs) (car xs)) w)
          (setq w (- (cadr xs) (car xs)) best (list (/ (+ (car xs) (cadr xs)) 2.0) y)))
        (setq xs (cddr xs)))
      (if best best c))))

;; TKA:SegDist - distanța de la punctul P la segmentul AB
(defun TKA:SegDist (p a b / l u)
  (setq l (distance a b))
  (if (< l 1e-9)
    (distance p a)
    (progn
      (setq u (max 0.0 (min 1.0 (/ (TK:Dot (TK:v- p a) (TK:v- b a)) (* l l)))))
      (distance p (TK:v+ a (TK:vx (TK:v- b a) u))))))

;; TKA:EdgeDist - distanța minimă de la P la laturile poligoanelor RINGS
(defun TKA:EdgeDist (p rings / d)
  (setq d 1e99)
  (foreach r rings
    (mapcar '(lambda (a b) (setq d (min d (TKA:SegDist p a b)))) r (append (cdr r) (list (car r)))))
  d)

;; TKA:FreePoint - punctul din interiorul poligonului PTS cel mai depărtat de
;; laturile lui și de poligoanele HOLES (de ex. construcțiile), pentru etichete
;; (căutare pe o rețea de 16 x 16 puncte)
(defun TKA:FreePoint (pts holes / bb dx dy i j p d best bd)
  (setq bb (TKA:Bbox pts) dx (/ (- (caddr bb) (car bb)) 16.0) dy (/ (- (cadddr bb) (cadr bb)) 16.0)
        bd -1.0 i 0)
  (repeat 16
    (setq j 0)
    (repeat 16
      (setq p (list (+ (car bb) (* dx (+ i 0.5))) (+ (cadr bb) (* dy (+ j 0.5)))))
      (if (and (TKA:Inside p pts) (not (vl-some '(lambda (h) (TKA:Inside p h)) holes))
               (> (setq d (TKA:EdgeDist p (cons pts holes))) bd))
        (setq bd d best p))
      (setq j (1+ j)))
    (setq i (1+ i)))
  (if best best (TKA:LabelPoint pts)))

;; TKA:Bbox - caseta (xmin ymin xmax ymax) a unei liste de puncte
(defun TKA:Bbox (pts)
  (list (apply 'min (mapcar 'car pts)) (apply 'min (mapcar 'cadr pts))
        (apply 'max (mapcar 'car pts)) (apply 'max (mapcar 'cadr pts))))

;; TKA:Clockwise - poligonul în sens orar, începând din punctul cel mai de
;; nord-vest (cel mai apropiat de colțul N-V al casetei) - convenția uzuală
(defun TKA:Clockwise (pts / bb nw best i k d)
  (if (> (TKA:SArea pts) 0.0) (setq pts (reverse pts)))
  (if (= *TKA:NRMOD* "NV")
    (progn
      (setq bb (TKA:Bbox pts) nw (list (car bb) (cadddr bb)) i 0 k 0 best 1e99)
      (foreach p pts
        (if (< (setq d (distance p nw)) (- best 1e-6)) (setq best d k i))
        (setq i (1+ i)))
      (append (TKA:Nthcdr k pts) (TKA:Firstn k pts)))
    pts))

;; TKA:Nthcdr / TKA:Firstn - restul listei de la poziția K / primele K elemente
(defun TKA:Nthcdr (k l) (repeat k (setq l (cdr l))) l)
(defun TKA:Firstn (k l / out) (repeat k (setq out (cons (car l) out) l (cdr l))) (reverse out))

;; TKA:PtKey - cheie de identificare a unui punct (rotunjit la mm)
(defun TKA:PtKey (p) (strcat (rtos (car p) 2 3) "," (rtos (cadr p) 2 3)))

;; TKA:Numbering - numerotarea globală a punctelor mai multor poligoane:
;; returnează lista de asociere (cheie-punct . număr). Punctele comune
;; primesc același număr; numerotarea continuă de la un poligon la altul.
(defun TKA:Numbering (polys start / tab n)
  (setq n start)
  (foreach pts polys
    (foreach p pts
      (if (not (assoc (TKA:PtKey p) tab))
        (setq tab (cons (cons (TKA:PtKey p) n) tab) n (1+ n)))))
  (reverse tab))

;; TKA:PtNo - numărul punctului P în tabelul de numerotare (sau nil)
(defun TKA:PtNo (p tab) (cdr (assoc (TKA:PtKey p) tab)))

;; TKA:Sides - laturile unui poligon: listă de (i nrA nrB pA pB lungime)
(defun TKA:Sides (pts tab / i out)
  (setq i 0)
  (mapcar '(lambda (a b)
             (setq out (cons (list i (TKA:PtNo a tab) (TKA:PtNo b tab) a b (distance a b)) out)
                   i (1+ i)))
          pts (append (cdr pts) (list (car pts))))
  (reverse out))

;; TKA:OnSegment - T dacă P se află pe segmentul AB (toleranță TOL)
(defun TKA:OnSegment (p a b tol / l u)
  (setq l (distance a b))
  (if (< l 1e-9)
    (< (distance p a) tol)
    (progn
      (setq u (/ (TK:Dot (TK:v- p a) (TK:v- b a)) (* l l)))
      (and (>= u (- (/ tol l))) (<= u (+ 1.0 (/ tol l)))
           (< (abs (/ (TK:Cross (TK:v- b a) (TK:v- p a)) l)) tol)))))

;; TKA:Densify - inserează în poligonul PTS punctele din lista EXTRA aflate pe
;; laturile lui (de ex. punctele noi ale loturilor pe conturul imobilului),
;; astfel încât fiecare punct să fie numerotat și fiecare segment cotat
(defun TKA:Densify (pts extra / out on)
  (mapcar
    '(lambda (a b)
       (setq on nil)
       (foreach p extra
         (if (and (> (distance p a) 0.005) (> (distance p b) 0.005) (TKA:OnSegment p a b 0.005)
                  (not (vl-some '(lambda (q) (equal q p 0.005)) on)))
           (setq on (cons p on))))
       (setq out (append (reverse (vl-sort on '(lambda (p q) (< (distance a p) (distance a q))))) (cons a out))))
    pts (append (cdr pts) (list (car pts))))
  (reverse out))

;; TKA:Ring2 - conturul (orar, din N-V) al poliliniei E, cu punctele din
;; *TKA:SPLIT* inserate pe laturi (variabilă legată de comenzile de
;; dezlipire/alipire: vârfurile tuturor imobilelor implicate)
(defun TKA:Ring2 (e) (TKA:Densify (TKA:Clockwise (TKA:PolyPts e)) *TKA:SPLIT*))

;; TKA:SideOnRing - indicele laturii poligonului RING pe care se află
;; segmentul AB (ambele capete pe aceeași latură), sau nil
(defun TKA:SideOnRing (a b ring / i res)
  (setq i 0)
  (mapcar '(lambda (p q)
             (if (and (null res) (TKA:OnSegment a p q 0.01) (TKA:OnSegment b p q 0.01))
               (setq res i))
             (setq i (1+ i)))
          ring (append (cdr ring) (list (car ring))))
  res)

;; TKA:LargestRemainder - rotunjește valorile VALS la întregi astfel încât
;; suma lor să fie TOTAL (metoda celui mai mare rest)
(defun TKA:LargestRemainder (vals total / fl rest diff idx out i)
  (setq fl (mapcar '(lambda (v) (fix v)) vals)
        diff (- total (apply '+ fl))
        idx (vl-sort (TKA:Range (length vals))
                     '(lambda (a b) (> (- (nth a vals) (nth a fl)) (- (nth b vals) (nth b fl))))))
  (setq i 0 out fl)
  (while (and (> diff 0) idx)
    (setq out (TK:SetNth out (car idx) (1+ (nth (car idx) out))) diff (1- diff) idx (cdr idx)))
  out)

;; TKA:Range - lista 0..N-1
(defun TKA:Range (n / l) (repeat n (setq n (1- n) l (cons n l))) l)

;; TKA:EN - coordonatele (Est Nord) ale unui punct din desen
(defun TKA:EN (p) (TK:PtEN p))


;;; ==========================================================================
;;;  IMOBILUL MĂSURAT: CULEGEREA DATELOR DIN DESEN
;;; ==========================================================================
;;;  Înregistrarea unui imobil (listă de asociere):
;;;    "E"       entitatea (polilinia închisă)       "PTS"   punctele (orar)
;;;    "TAB"     numerotarea punctelor                "SIDES" laturile cu vecinii
;;;    "AREA"    suprafața (mp, întreg)               "PERIM" perimetrul (m)
;;;    "PARCELE" ((nr categorie suprafață puncte) ...)
;;;    "CONSTR"  ((ename cod dest denumire regim an sd mențiuni sc puncte) ...)
;;; ==========================================================================

;; TKA:R1 - valoarea unei chei din înregistrarea REC
(defun TKA:R1 (rec k) (cdr (assoc k rec)))

;; TKA:KeyPt - punctul corespunzător unei chei TKA:PtKey
(defun TKA:KeyPt (k / l) (setq l (TKA:Split k ",")) (list (atof (car l)) (atof (cadr l))))

;; TKA:SideData - datele memorate pentru latura AB a imobilului E:
;; (identificator vecin materializare observații). O latură împărțită ulterior
;; (puncte noi la dezlipire) moștenește datele laturii întregi.
(defun TKA:SideData (e a b / lst ka kb r)
  (setq lst (TKA:LGet e "LATURI") ka (TKA:PtKey a) kb (TKA:PtKey b))
  (foreach x lst
    (if (or (and (= (car x) ka) (= (cadr x) kb)) (and (= (car x) kb) (= (cadr x) ka)))
      (setq r (cddr x))))
  (if (null r)
    (foreach x lst
      (if (and (null r) (TKA:OnSegment a (TKA:KeyPt (car x)) (TKA:KeyPt (cadr x)) 0.01)
               (TKA:OnSegment b (TKA:KeyPt (car x)) (TKA:KeyPt (cadr x)) 0.01))
        (setq r (cddr x)))))
  (if r r (list "" "" "" "")))

;; TKA:SetSideData - memorează datele laturii AB pe imobilul E
(defun TKA:SetSideData (e a b data / lst ka kb out found)
  (setq lst (TKA:LGet e "LATURI") ka (TKA:PtKey a) kb (TKA:PtKey b))
  (foreach x lst
    (if (or (and (= (car x) ka) (= (cadr x) kb)) (and (= (car x) kb) (= (cadr x) ka)))
      (setq out (cons (append (list ka kb) data) out) found T)
      (setq out (cons x out))))
  (if (not found) (setq out (cons (append (list ka kb) data) out)))
  (TKA:LPut e "LATURI" (reverse out)))

;; TKA:ConstrRec - înregistrarea unei construcții (datele din ldata + geometrie):
;; (ename cod destinație denumire regim an Sd mențiuni Sc puncte nr-UI)
(defun TKA:ConstrRec (e i / cod)
  (setq cod (TKA:LGet e "COD"))
  (if (or (null cod) (= cod "")) (setq cod (strcat "C" (itoa i))))
  (list e cod
        (cond ((TKA:LGet e "DEST")) ("CL"))
        (cond ((TKA:LGet e "DENUMIRE")) (""))
        (cond ((TKA:LGet e "REGIM")) (""))
        (cond ((TKA:LGet e "AN")) (""))
        (cond ((TKA:LGet e "SD")) (""))
        (cond ((TKA:LGet e "MENT")) (""))
        (TKA:Int (TKA:Area e))
        (TKA:PolyPts e)
        (cond ((TKA:LGet e "NRUI")) (""))))

;; TKA:ConstrMentiuni - textul coloanei "Mențiuni" din tabelul B (art. 88):
;; destinația, regimul de înălțime, anul construirii, Sc, Sd + alte mențiuni
(defun TKA:ConstrMentiuni (c / s)
  (TKA:Join (list (if (/= (nth 3 c) "") (nth 3 c) (cdr (assoc (nth 2 c) *TKA:DEST*)))
                  (if (/= (nth 4 c) "") (strcat "regim de ^in`al`time " (nth 4 c)))
                  (if (/= (nth 5 c) "") (strcat "construit`a ^in anul " (nth 5 c)))
                  (strcat "Sc=" (itoa (nth 8 c)) " mp")
                  (if (/= (nth 6 c) "") (strcat "Sd=" (nth 6 c) " mp"))
                  (nth 7 c))
            ", "))

;; TKA:Imobil - culege datele imobilului E (cu parcelele de folosință PARC și
;; construcțiile CONSTR, liste de entități) și numerotarea TAB (sau nil =
;; numerotare proprie începând cu *TKA:NRSTART*). AOV = suprafața impusă
;; (loturile, rotunjite astfel încât suma să fie suprafața imobilului) sau nil.
(defun TKA:Imobil (e parc constr tab aov / pts area parcs vals ints i sides cons-recs)
  (setq pts  (TKA:Ring2 e)
        tab  (if tab tab (TKA:Numbering (list pts) *TKA:NRSTART*))
        area (if aov aov (TKA:Int (TKA:Area e))))
  ;; parcelele de folosință: poligoane din interiorul imobilului
  (setq i 0)
  (foreach p parc
    (setq i (1+ i)
          parcs (cons (list i (cond ((TKA:LGet p "CATEG")) ((TKA:Get "CATEG")) ("CC"))
                            (TKA:Area p) (TKA:PolyPts p))
                      parcs)))
  (setq parcs (reverse parcs))
  (if (null parcs)
    (setq parcs (list (list 1 (if (/= (TKA:Get "CATEG") "") (TKA:Get "CATEG") "CC") (float area) pts))))
  ;; suprafețele parcelelor rotunjite astfel încât totalul să fie egal cu imobilul
  (setq vals (mapcar 'caddr parcs)
        vals (mapcar '(lambda (v) (* v (/ area (max 1e-9 (apply '+ vals))))) vals)
        ints (TKA:LargestRemainder vals area))
  (setq parcs (mapcar '(lambda (p s) (list (car p) (cadr p) s (cadddr p))) parcs ints))
  ;; laturile cu datele vecinilor
  (setq sides (mapcar '(lambda (s) (append s (TKA:SideData e (nth 3 s) (nth 4 s)))) (TKA:Sides pts tab)))
  ;; construcțiile
  (setq i 0)
  (foreach c constr (setq i (1+ i) cons-recs (cons (TKA:ConstrRec c i) cons-recs)))
  (list (cons "E" e) (cons "PTS" pts) (cons "TAB" tab) (cons "SIDES" sides)
        (cons "AREA" area) (cons "PERIM" (TKA:Perim pts)) (cons "PARCELE" parcs)
        (cons "CONSTR" (reverse cons-recs))))

;; TKA:Chains - grupează laturile consecutive cu același vecin:
;; ((nrPuncte... lungime id vecin mat obs) ...), pentru PV de vecinătate
(defun TKA:Chains (sides / out cur key)
  (foreach s sides
    (setq key (list (nth 6 s) (nth 7 s)))
    (if (and cur (equal key (list (nth 2 (car cur)) (nth 3 (car cur)))) (/= (apply 'strcat key) ""))
      (setq cur (cons (list (nth 2 s) (+ (cadr (car cur)) (nth 5 s)) (nth 6 s) (nth 7 s) (nth 8 s) (nth 9 s)
                            (append (nth 6 (car cur)) (list (nth 2 s))))
                      (cdr cur)))
      (setq cur (cons (list (nth 2 s) (nth 5 s) (nth 6 s) (nth 7 s) (nth 8 s) (nth 9 s) (list (nth 1 s) (nth 2 s)))
                      cur))))
  ;; ultimul lanț se poate uni cu primul (poligon închis)
  (setq cur (reverse cur))
  (if (and (cdr cur)
           (equal (list (nth 2 (car cur)) (nth 3 (car cur))) (list (nth 2 (last cur)) (nth 3 (last cur))))
           (/= (strcat (nth 2 (car cur)) (nth 3 (car cur))) ""))
    (setq cur (cons (list (car (car cur)) (+ (cadr (car cur)) (cadr (last cur))) (nth 2 (car cur)) (nth 3 (car cur))
                          (nth 4 (car cur)) (nth 5 (car cur))
                          (append (nth 6 (last cur)) (cdr (nth 6 (car cur)))))
                    (reverse (cdr (reverse (cdr cur)))))))
  (mapcar '(lambda (c) (list (TKA:Join (mapcar 'itoa (nth 6 c)) "-") (cadr c) (nth 2 c) (nth 3 c) (nth 4 c) (nth 5 c)))
          cur))

;;; ==========================================================================
;;;  CÂMPURILE ANEXELOR WORD
;;; ==========================================================================

;; Tipurile de lucrare: (cod text bife-cerere-recepție bife-cerere-informații)
(setq *TKA:TIPURI*
  '(("PRIMA"  "Prima ^inregistrare ^in sistemul integrat de cadastru `si carte funciar`a" "CHK_PRIMA")
    ("CONSTR" "Actualizare informa`tii cadastrale - ^inscriere construc`tii" "CHK_ACTUALIZARE")
    ("ACTUAL" "Actualizare informa`tii cadastrale" "CHK_ACTUALIZARE")
    ("DEZ"    "Documenta`tie pentru dezlipire teren" "CHK_DEZALIP")
    ("ALIP"   "Documenta`tie pentru alipire teren" "CHK_DEZALIP")
    ("ATRIB"  "Documenta`tie de atribuire num`ar cadastral" "CHK_ATRIBUIRE")
    ("UI"     "Documenta`tie de prim`a ^inregistrare UI" "CHK_PRIMAUI")
    ("APART"  "Documenta`tie pentru apartamentare" "CHK_APART")
    ("DL115"  "^Inregistrarea ^in planul cadastral (Decretul-lege nr. 115/1938)" "CHK_DL115")))
;; Modalitățile de comunicare a răspunsului
(setq *TKA:COMUNIC* '(("ONLINE" . "CHK_ONLINE") ("POSTA" . "CHK_POSTA") ("SEDIU" . "CHK_SEDIU")
                      ("EMAIL" . "CHK_EMAIL") ("FAX" . "CHK_FAX")))

;; TKA:Adresa - adresa imobilului compusă din câmpurile lucrării
(defun TKA:Adresa (/ loc)
  (setq loc (TKA:Get "LOCALITATE"))
  (TKA:Join
    (list (if (/= loc "") (strcat "loc. " loc))
          (if (/= (TKA:Get "STRADA") "") (strcat "str. " (TKA:Get "STRADA")
                                                 (if (/= (TKA:Get "NR") "") (strcat " nr. " (TKA:Get "NR")) "")))
          (if (/= (TKA:Get "BLOC") "") (strcat "bl. " (TKA:Get "BLOC")))
          (if (/= (TKA:Get "SCARA") "") (strcat "sc. " (TKA:Get "SCARA")))
          (if (/= (TKA:Get "ETAJ") "") (strcat "et. " (TKA:Get "ETAJ")))
          (if (/= (TKA:Get "AP") "") (strcat "ap. " (TKA:Get "AP")))
          (if (/= (TKA:Get "TARLA") "") (strcat "tarla " (TKA:Get "TARLA")))
          (if (/= (TKA:Get "PARCELA") "") (strcat "parcela " (TKA:Get "PARCELA")))
          (if (/= (TKA:Get "JUDET") "") (strcat "jud. " (TKA:Get "JUDET"))))
    ", "))

;; TKA:ExecNume - numele complet al executantului ("ing. Nume Prenume")
(defun TKA:ExecNume ()
  (TKA:Join (list (TKA:EGet "E_TITLU") (TKA:EGet "E_NUME") (TKA:EGet "E_PRENUME")) " "))

;; TKA:ExecAut - autorizația executantului ("seria RO-BV-F nr. 0024")
(defun TKA:ExecAut ()
  (if (/= (TKA:EGet "E_AUT_SERIA") "")
    (strcat "seria " (TKA:EGet "E_AUT_SERIA") " nr. " (TKA:EGet "E_AUT_NR"))
    ""))

;; TKA:DefaultText - textele implicite ale memoriului tehnic (dacă lipsesc)
(defun TKA:DefaultText (k rec / tip)
  (setq tip (TKA:Get "TIP"))
  (cond
    ((= k "SCOP")
     (strcat "Documenta`tia cadastral`a s-a ^intocmit la solicitarea proprietarului, ^in vederea "
             (cond ((= tip "DEZ") "dezlipirii imobilului ^in loturi `si ^inscrierii acestora ^in eviden`tele de cadastru `si carte funciar`a")
                   ((= tip "ALIP") "alipirii imobilelor `si ^inscrierii imobilului rezultat ^in eviden`tele de cadastru `si carte funciar`a")
                   ((= tip "CONSTR") "^inscrierii construc`tiilor ^in eviden`tele de cadastru `si carte funciar`a")
                   (T "^inscrierii imobilului ^in eviden`tele de cadastru `si carte funciar`a `si a intabul`arii dreptului de proprietate"))
             (if (/= (TKA:Get "ACT_PROP") "") (strcat ", ^in baza actului: " (TKA:Get "ACT_PROP")) "")
             "."
             (if (and (= tip "DEZ") *TKA:LOTURI*)
               (strcat " Imobilul se dezlipe`ste ^in " (itoa (length *TKA:LOTURI*)) " loturi: "
                       (TKA:Join (mapcar '(lambda (r) (strcat "Lot " (itoa (1+ (TKA:Index r *TKA:LOTURI*)))
                                                              " - " (itoa (TKA:R1 r "AREA")) " mp"))
                                         *TKA:LOTURI*)
                                 "; ")
                       ".")
               "")))
    ((= k "DOCUMENTARE")
     (strcat "S-au consultat datele din eviden`tele OCPI (extrasul de plan cadastral `si informa`tiile din sistemul "
             "integrat de cadastru `si carte funciar`a) `si actele puse la dispozi`tie de proprietar. Imobilul a fost "
             "identificat ^in teren pe baza actelor de proprietate, iar limitele au fost indicate de proprietar. "
             "Imobilul are suprafa`ta m`asurat`a de " (itoa (TKA:R1 rec "AREA")) " mp"
             (if (/= (TKA:Get "SACT") "") (strcat ", fa`t`a de " (TKA:Get "SACT") " mp din act") "")
             "."))
    ((= k "OPERATIUNI")
     (strcat "M`asur`atorile s-au efectuat prin metoda "
             (if (/= (TKA:Get "METODA") "") (TKA:Get "METODA") "GNSS-RTK, cu corec`tii ^in timp real de la re`teaua ROMPOS")
             (if (/= (TKA:Get "APARATURA") "") (strcat ", cu aparatura " (TKA:Get "APARATURA")) "")
             (if (/= (TKA:Get "SPRIJIN") "") (strcat ". Puncte de sprijin: " (TKA:Get "SPRIJIN")) "")
             (if (/= (TKA:Get "DATA_MAS") "") (strcat ". Data m`asur`atorilor: " (TKA:Get "DATA_MAS")) "")
             ". Coordonatele au fost determinate ^in sistemul de proiec`tie Stereografic 1970, "
             "transformarea din ETRS89 realiz^andu-se cu programul oficial TransDatRO. "
             "Suprafa`ta a fost calculat`a analitic din coordonatele punctelor de contur."))
    (T "")))

;; TKA:Txt - câmp textual al lucrării, cu valoarea implicită dacă lipsește
(defun TKA:Txt (k rec / v)
  (setq v (TKA:Get k))
  (if (= v "") (TKA:DefaultText k rec) v))

;; TKA:Fields - toate câmpurile pentru completarea anexelor Word.
;; REC = imobilul măsurat (sau nil dacă nu s-a selectat geometria)
(defun TKA:Fields (rec / f tip p1 p2 constr chains c1 tp)
  (setq tip (TKA:Get "TIP")
        p1 (TKA:Join (list (TKA:Get "P1_NUME") (TKA:Get "P1_PRENUME")) " ")
        p2 (TKA:Join (list (TKA:Get "P2_NUME") (TKA:Get "P2_PRENUME")) " "))
  ;; câmpurile salvate în desen și ale executantului
  (foreach x (TKA:Data) (setq f (cons x f)))
  (foreach k '("E_TITLU" "E_NUME" "E_PRENUME" "E_CNP" "E_FIRMA" "E_CAT" "E_AUT_SERIA" "E_AUT_NR"
               "E_AUT_EMITENT" "E_AUT_DATA" "E_LOC" "E_STR" "E_NR" "E_JUD" "E_CI_SERIA" "E_CI_NR"
               "E_TEL" "E_EMAIL")
    (setq f (cons (cons k (TKA:EGet k)) f)))
  ;; câmpuri compuse
  (setq f (append
            (list (cons "P1_NUMEC" p1) (cons "P2_NUMEC" p2)
                  (cons "ADRESA" (TKA:Adresa))
                  (cons "STRADA_TARLA" (if (/= (TKA:Get "STRADA") "") (TKA:Get "STRADA")
                                         (if (/= (TKA:Get "TARLA") "") (strcat "T " (TKA:Get "TARLA")) "")))
                  (cons "NR_PARCELA" (if (/= (TKA:Get "NR") "") (TKA:Get "NR")
                                       (if (/= (TKA:Get "PARCELA") "") (strcat "P " (TKA:Get "PARCELA")) "")))
                  (cons "NRCF_NRCAD" (TKA:Join (list (TKA:Get "NRCF") (TKA:Get "NRCAD")) " / "))
                  (cons "E_NUMEC" (TKA:ExecNume))
                  (cons "E_AUT" (TKA:ExecAut))
                  (cons "E_NUMEC_AUT" (TKA:Join (list (TKA:ExecNume)
                                                      (if (/= (TKA:ExecAut) "") (strcat "autorizat ANCPI " (TKA:ExecAut)))
                                                      (TKA:EGet "E_FIRMA"))
                                                ", "))
                  (cons "DATA" (TK:Today))
                  (cons "TIP_LUCRARE" (cadr (assoc tip *TKA:TIPURI*)))
                  (cons "CATEG_TEXT" (TKA:CategText (TKA:Get "CATEG")))
                  (cons "INTAB_OBIECT" (if (/= (TKA:Get "INTAB_OBIECT") "") (TKA:Get "INTAB_OBIECT")
                                         "dreptului de proprietate"))
                  (cons "PV_EXEMPLARE" (if (/= (TKA:Get "PV_EXEMPLARE") "") (TKA:Get "PV_EXEMPLARE") ""))
                  (cons "CHK_INTAB" "[X]")
                  (cons "CHK_D1" "[X]") (cons "CHK_D2" "[X]") (cons "CHK_D4" "[X]"))
            f))
  ;; bifele după tipul lucrării și modul de comunicare
  (if (setq tp (assoc tip *TKA:TIPURI*)) (setq f (cons (cons (caddr tp) "[X]") f)))
  (if (setq tp (assoc (TKA:Get "COMUNICARE") *TKA:COMUNIC*)) (setq f (cons (cons (cdr tp) "[X]") f)))
  (if (= (TKA:Get "POZ_INCERTA") "1") (setq f (cons (cons "CHK_D3" "[X]") f)))
  ;; datele măsurate
  (if rec
    (progn
      (setq constr (TKA:R1 rec "CONSTR") chains (TKA:Chains (TKA:R1 rec "SIDES")))
      (setq f (append
                (list (cons "SMAS" (itoa (TKA:R1 rec "AREA")))
                      (cons "SMAS_MP" (strcat (itoa (TKA:R1 rec "AREA")) " mp"))
                      (cons "PERIM" (TKA:Num (TKA:R1 rec "PERIM") 2))
                      (cons "SCOP" (TKA:Txt "SCOP" rec))
                      (cons "DOCUMENTARE" (TKA:Txt "DOCUMENTARE" rec))
                      (cons "OPERATIUNI" (TKA:Txt "OPERATIUNI" rec))
                      (cons "CONSTR_TEXT"
                            (if constr
                              (strcat "Pe imobil sunt edificate urm`atoarele construc`tii: "
                                      (TKA:Join (mapcar '(lambda (c) (strcat (nth 1 c) " - " (TKA:ConstrMentiuni c))) constr) "; ")
                                      ".")
                              "Pe imobil nu sunt edificate construc`tii."))
                      (cons "VECINATATI" (TKA:Join (mapcar '(lambda (c) (strcat (car c) ": " (TKA:Join (list (nth 2 c) (nth 3 c)) " - "))) chains) "; "))
                      (cons "SEMN_PROP" (TKA:Join (list (if (/= p1 "") (strcat p1 " ..............................."))
                                                        (if (/= p2 "") (strcat p2 " ...............................")))
                                                  "\n"))
                      (cons "SEMN_VECINI" (TKA:Join (mapcar '(lambda (c) (strcat "Latura " (car c)
                                                                                  (if (/= (nth 2 c) "") (strcat " (" (nth 2 c) ")") "")
                                                                                  (if (/= (nth 3 c) "") (strcat " " (nth 3 c)) "")
                                                                                  " ............ (semn`atura) ............"))
                                                            chains)
                                                    "\n")))
                f))
      (if (setq c1 (car constr))
        (setq f (append (list (cons "C1_DEST" (if (/= (nth 3 c1) "") (nth 3 c1) (cdr (assoc (nth 2 c1) *TKA:DEST*))))
                              (cons "C1_REGIM" (nth 4 c1)) (cons "C1_AN" (nth 5 c1))
                              (cons "C1_SC_MP" (strcat (itoa (nth 8 c1)) " mp"))
                              (cons "C1_SD_MP" (if (/= (nth 6 c1) "") (strcat (nth 6 c1) " mp") ""))
                              (cons "C1_NRUI" (nth 10 c1)))
                        f)))))
  ;; foaia colectivă (anexa 19): totalurile calculate din UI memorate
  (if *TKA:UIDATA* (setq f (append (cadr *TKA:UIDATA*) f)))
  ;; inventarul unui lot (dezlipire): lotul nu are încă număr cadastral/CF
  (if (and rec (TKA:R1 rec "LOT"))
    (setq f (append (list (cons "NRCAD" (if (/= (TKA:R1 rec "NRCAD") "") (TKA:R1 rec "NRCAD")
                                          (strcat "- (lot " (itoa (TKA:R1 rec "LOT")) " propus)")))
                          (cons "NRCF" "-"))
                    f)))
  (TKA:Dedupe f))

;; TKA:Dedupe - păstrează prima apariție a fiecărei chei (JSON fără chei duble)
(defun TKA:Dedupe (l / out seen)
  (foreach x l
    (if (not (member (car x) seen)) (setq seen (cons (car x) seen) out (cons x out))))
  (reverse out))

;; TKA:Tables - seturile de rânduri repetabile: PCT (inventar), LAT (laturi
;; PV), PROP (proprietari), VEC (vecini)
(defun TKA:Tables (rec / pct lat prop vec seen en sides)
  (if rec
    (progn
      (setq sides (TKA:R1 rec "SIDES"))
      (foreach s sides
        (setq en (TKA:EN (nth 3 s)))
        (setq pct (cons (list (cons "NR" (itoa (nth 1 s)))
                              (cons "X" (TKA:Num (cadr en) 3))
                              (cons "Y" (TKA:Num (car en) 3))
                              (cons "LAT" (strcat (itoa (nth 1 s)) "-" (itoa (nth 2 s))))
                              (cons "DIST" (TKA:Num (nth 5 s) 2)))
                        pct)))
      (foreach c (TKA:Chains sides)
        (setq lat (cons (list (cons "LATURA" (car c)) (cons "LUNG" (TKA:Num (cadr c) 2))
                              (cons "MAT" (nth 4 c)) (cons "VECIN" (nth 3 c)) (cons "ID" (nth 2 c))
                              (cons "OBS" (nth 5 c)))
                        lat))
        (if (and (/= (nth 3 c) "") (not (member (nth 3 c) seen)))
          (setq seen (cons (nth 3 c) seen)
                vec (cons (list (cons "NUME" (nth 3 c)) (cons "PRENUME" "")
                                (cons "CALITATE" (strcat "proprietar " (nth 2 c)))
                                (cons "CNP" "") (cons "CUI" "") (cons "OBS" ""))
                          vec))))))
  (foreach k '("P1" "P2")
    (if (/= (TKA:Get (strcat k "_NUME")) "")
      (setq prop (cons (list (cons "NUME" (TKA:Get (strcat k "_NUME")))
                             (cons "PRENUME" (TKA:Get (strcat k "_PRENUME")))
                             (cons "CALITATE" (if (/= (TKA:Get (strcat k "_CALITATE")) "")
                                                (TKA:Get (strcat k "_CALITATE")) "proprietar"))
                             (cons "CNP" (TKA:Get (strcat k "_CNP"))))
                       prop))))
  (list (cons "PCT" (reverse pct)) (cons "LAT" (reverse lat))
        (cons "PROP" (reverse prop)) (cons "VEC" (reverse vec))
        (cons "UI" (car *TKA:UIDATA*))))

;; Catalogul anexelor Word: (număr șablon nume-fișier titlu)
(setq *TKA:WORD*
  '((13 "Anexa_13.docx" "Anexa13_Cerere_receptie_inscriere" "Cerere de recep`tie `si ^inscriere")
    (14 "Anexa_14.docx" "Anexa14_Declaratie" "Declara`tie pe proprie r`aspundere")
    (15 "Anexa_15.docx" "Anexa15_Memoriu_tehnic" "Memoriu tehnic")
    (20 "Anexa_20.docx" "Anexa20_PV_vecinatate" "Proces-verbal de vecin`atate")
    (0  "Inventar_coordonate.docx" "Inventar_coordonate" "Inventar de coordonate")
    (19 "Anexa_19.docx" "Anexa19_Foaia_colectiva" "Foaia colectiv`a")
    (12 "Anexa_12.docx" "Anexa12_Cerere_informatii" "Cerere de informa`tii")
    (1  "Anexa_01.docx" "Anexa01_Cerere_copii" "Cerere eliberare copii din arhiv`a")
    (5  "Anexa_05.docx" "Anexa05_Cerere_inscriere" "Cerere de ^inscriere")
    (6  "Anexa_06.docx" "Anexa06_Cerere_extras_CF" "Cerere extras de carte funciar`a")
    (7  "Anexa_07.docx" "Anexa07_Cerere_certificat_sarcini" "Cerere certificat de sarcini")
    (8  "Anexa_08.docx" "Anexa08_Cerere_identificare_CF" "Cerere identificare CF dup`a proprietar")
    (10 "Anexa_10.docx" "Anexa10_Cerere_imobil_neinscris" "Cerere certificat imobil ne^inscris")
    (22 "Anexa_22.docx" "Anexa22_Cerere_anulare_nr_cadastral" "Cerere de anulare num`ar cadastral")
    (23 "Anexa_23.docx" "Anexa23_Cerere_aviz_CNC" "Cerere aviz ^incepere/recep`tie (CNC)")
    (26 "Anexa_26.docx" "Anexa26_Adeverinta_primarie" "Adeverin`t`a prim`arie (posesie)")
    (27 "Anexa_27.docx" "Anexa27_Certificat_registru_agricol" "Certificat registrul agricol")
    (28 "Anexa_28.docx" "Anexa28_Certificat_edificare_cu_AC" "Certificat edificare cu AC")
    (29 "Anexa_29.docx" "Anexa29_Certificat_edificare_fara_AC" "Certificat edificare f`ar`a AC")
    (30 "Anexa_30.docx" "Anexa30_Cerere_info_plan_parcelar" "Cerere informa`tii plan parcelar")
    (32 "Anexa_32.docx" "Anexa32_Tabel_parcelar" "Tabel parcelar")
    (34 "Anexa_34.docx" "Anexa34_Cerere_registru_proprietari" "Cerere consultare registru proprietari")
    (2  "Anexa_02.docx" "Anexa02_Instiintare_OCPI" "^In`stiin`tare (OCPI)")
    (3  "Anexa_03.docx" "Anexa03_Comunicare_OCPI" "Comunicarea ^incheierii (OCPI)")
    (4  "Anexa_04.docx" "Anexa04_Incheieri_OCPI" "^Incheieri (OCPI)")
    (9  "Anexa_09.docx" "Anexa09_Certificat_identificare_OCPI" "Certificat identificare (OCPI)")
    (11 "Anexa_11.docx" "Anexa11_Certificat_neinscris_OCPI" "Certificat imobil ne^inscris (OCPI)")
    (21 "Anexa_21.docx" "Anexa21_Invitatie_OCPI" "Invita`tie l`amuriri (OCPI)")
    (24 "Anexa_24.docx" "Anexa24_Aviz_incepere_CNC" "Aviz de ^incepere (CNC)")
    (25 "Anexa_25.docx" "Anexa25_PV_receptie" "Proces-verbal de recep`tie (CNC/OCPI)")
    (33 "Anexa_33.docx" "Anexa33_PV_receptie_plan_parcelar" "PV recep`tie plan parcelar (OCPI)")
    (35 "Anexa_35.docx" "Anexa35_Certificat_sarcini_OCPI" "Certificat de sarcini (OCPI)")))

;; TKA:AnexeDir - folderul cu șabloanele Word și scriptul de completare
(defun TKA:AnexeDir (/ f lsp)
  (cond
    ((setq f (findfile "anexe\\TopoKitDocx.ps1")) (strcat (vl-filename-directory f) "\\"))
    ((and (setq lsp (findfile "TopoKitAnexe.lsp"))
          (findfile (strcat (vl-filename-directory lsp) "\\anexe\\TopoKitDocx.ps1")))
     (strcat (vl-filename-directory lsp) "\\anexe\\"))
    ((and (setq lsp (findfile "TopoKit.lsp"))
          (findfile (strcat (vl-filename-directory lsp) "\\anexe\\TopoKitDocx.ps1")))
     (strcat (vl-filename-directory lsp) "\\anexe\\"))
    ((setq f (findfile "TopoKitDocx.ps1")) (strcat (vl-filename-directory f) "\\"))))

;; TKA:WorkDir - folderul în care se salvează anexele lucrării curente
(defun TKA:WorkDir (/ base d)
  (setq base (if (/= (TKA:Get "NRCAD") "") (TKA:Get "NRCAD") (vl-filename-base (getvar "DWGNAME")))
        d (strcat (TK:OutDir) "Anexe_" (TK:SafeName base)))
  (if (not (vl-file-directory-p d)) (vl-mkdir d))
  (strcat d "\\"))

;; TKA:WriteJob - scrie fișierul JSON pentru scriptul de completare
(defun TKA:WriteJob (file fields tables docs pdf / fh first)
  (if (setq fh (open file "w"))
    (progn
      (write-line "{" fh)
      (write-line " \"fields\": {" fh)
      (setq first T)
      (foreach x fields
        (write-line (strcat (if first "  " "  ,") (TKA:Json (car x)) ": " (TKA:Json (cdr x))) fh)
        (setq first nil))
      (write-line " }," fh)
      (write-line " \"tables\": {" fh)
      (setq first T)
      (foreach t1 tables
        (write-line (strcat (if first "  " "  ,") (TKA:Json (car t1)) ": [") fh)
        (setq first nil)
        (TKA:JsonRows (cdr t1) fh)
        (write-line "  ]" fh))
      (write-line " }," fh)
      (write-line (strcat " \"pdf\": " (if pdf "true" "false") ",") fh)
      (write-line " \"documents\": [" fh)
      (setq first T)
      (foreach d docs
        (write-line (strcat (if first "  " "  ,") "{\"template\": " (TKA:Json (car d))
                            ", \"output\": " (TKA:Json (cadr d)) "}")
                    fh)
        (setq first nil))
      (write-line " ]" fh)
      (write-line "}" fh)
      (close fh)
      T)))

;; TKA:JsonRows - scrie rândurile unui set de date ({"CHEIE": "valoare", ...})
(defun TKA:JsonRows (rows fh / first)
  (setq first T)
  (foreach r rows
    (write-line (strcat (if first "   {" "   ,{")
                        (TKA:Join (mapcar '(lambda (x) (strcat (TKA:Json (car x)) ": " (TKA:Json (cdr x)))) r) ", ")
                        "}")
                fh)
    (setq first nil)))

;; TKA:ReadLog - liniile fișierului jurnal scris de script
(defun TKA:ReadLog (f / fh l out)
  (if (and (findfile f) (setq fh (open f "r")))
    (progn
      (while (setq l (read-line fh)) (setq out (cons l out)))
      (close fh)))
  (reverse out))

;; TKA:MakeWord - completează anexele Word cu numerele din lista NRS
;; (0 = inventarul de coordonate) pentru imobilul REC; SUFFIX se adaugă la
;; numele fișierelor (de ex. "_lot1"). Returnează lista fișierelor create.
(defun TKA:MakeWord (nrs rec suffix / dir out job docs w res ps)
  (setq dir (TKA:AnexeDir))
  (cond
    ((null dir)
     (TKA:Msg "Nu am g`asit folderul \"anexe\" (`sabloanele Word `si TopoKitDocx.ps1) l^ang`a TopoKit.lsp.")
     nil)
    (T
     (setq out (TKA:WorkDir) job (strcat out "TopoKit_anexe.json"))
     (foreach n nrs
       (if (setq w (assoc n *TKA:WORD*))
         (setq docs (cons (list (strcat dir (cadr w)) (strcat out (caddr w) suffix ".docx")) docs))))
     (setq docs (reverse docs))
     (if (and docs (TKA:WriteJob job (TKA:Fields rec) (TKA:Tables rec) docs (= *TKA:PDF* "1")))
       (progn
         (if (findfile (strcat job ".log")) (vl-file-delete (strcat job ".log")))
         (TKA:Msg (strcat "Se completeaz`a " (itoa (length docs)) " anexe Word..."))
         (setq ps (strcat "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \""
                          dir "TopoKitDocx.ps1\" -Job \"" job "\""))
         (TK:Run ps T)
         (foreach l (TKA:ReadLog (strcat job ".log"))
           (cond ((wcmatch l "OK*") (setq res (cons (substr l 4) res)))
                 ((wcmatch l "PDF*") (setq res (cons (substr l 5) res)))
                 (T (princ (strcat "\n  " l)))))
         (if (null res)
           (TKA:Msg "Scriptul PowerShell nu a creat documente (verifica`ti jurnalul TopoKit_anexe.json.log).")
           (progn
             (TKA:Msg (strcat (itoa (length res)) " fi`siere create ^in " out))
             (if (and (= *TKA:OPENDIR* "1") (= suffix "")) (TK:Run (strcat "explorer.exe \"" out "\"") nil))))
         (reverse res))))))


;;; ==========================================================================
;;;  DESENUL ÎN PAPER SPACE
;;; ==========================================================================
;;;  Toate dimensiunile sunt în mm pe hârtie; originea = colțul stânga-jos
;;;  al foii. Entitățile se creează în layout-ul *TKA:LAY*.
;;; ==========================================================================

(setq *TKA:LAY* nil)
(setq *TKA:TH* 2.1)        ; înălțimea textului din tabele (mm)
(setq *TKA:LH* 1.5)        ; înălțimea etichetelor din desen (mm)

;; Straturile pieselor desenate: (nume culoare grosime plotabil)
(setq *TKA:LAYERS*
  '(("PAD_CADRU" 7 50 1) ("PAD_TABEL" 7 18 1) ("PAD_TEXT" 7 18 1) ("PAD_CONTUR" 6 35 1)
    ("PAD_LOTURI" 6 25 1) ("PAD_PUNCTE" 7 18 1) ("PAD_COTE" 7 13 1) ("PAD_VECINI" 3 13 1)
    ("PAD_CONSTR" 7 25 1) ("PAD_PARCELE" 6 13 1) ("PAD_GRID" 8 13 1) ("PAD_VIEWPORT" 8 13 0)))

;; TKA:Layers - creează straturile pieselor desenate (dacă lipsesc)
(defun TKA:Layers ()
  (foreach l *TKA:LAYERS*
    (if (not (tblsearch "LAYER" (car l)))
      (entmake (list '(0 . "LAYER") '(100 . "AcDbSymbolTableRecord") '(100 . "AcDbLayerTableRecord")
                     (cons 2 (car l)) '(70 . 0) (cons 62 (cadr l)) '(6 . "Continuous")
                     (cons 370 (caddr l)) (cons 290 (cadddr l)))))))

;; TKA:Styles - stilurile de text Arial normal, aldin și cursiv
(defun TKA:Styles ()
  (TK:Style)
  (foreach s '(("TKA_ARIALB" . "arialbd.ttf") ("TKA_ARIALI" . "ariali.ttf"))
    (if (not (tblsearch "STYLE" (car s)))
      (entmake (list '(0 . "STYLE") '(100 . "AcDbSymbolTableRecord") '(100 . "AcDbTextStyleTableRecord")
                     (cons 2 (car s)) '(70 . 0) '(40 . 0.0) '(41 . 1.0) '(50 . 0.0) '(71 . 0)
                     '(42 . 2.5) (cons 3 (cdr s)) '(4 . ""))))))

;; TKA:Make - entmake în layout-ul curent (grupurile 67/410 după AcDbEntity)
(defun TKA:Make (dxf / out done)
  (foreach g dxf
    (setq out (cons g out))
    (if (and (not done) (or (equal g '(100 . "AcDbEntity"))
                            (and (= (car g) 0) (not (assoc 100 dxf)))))
      (setq out (cons (cons 410 *TKA:LAY*) (cons '(67 . 1) out)) done T)))
  (entmake (reverse out)))

;; TKA:L - linie
(defun TKA:L (x1 y1 x2 y2 lay)
  (TKA:Make (list '(0 . "LINE") (cons 8 lay) (list 10 x1 y1 0.0) (list 11 x2 y2 0.0))))

;; TKA:PL - polilinie (LWPOLYLINE) prin punctele PTS
(defun TKA:PL (pts closed lay / d)
  (setq d (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") (cons 8 lay) '(100 . "AcDbPolyline")
                (cons 90 (length pts)) (cons 70 (if closed 1 0))))
  (foreach p pts (setq d (append d (list (list 10 (car p) (cadr p))))))
  (TKA:Make d))

;; TKA:Box - dreptunghi
(defun TKA:Box (x1 y1 x2 y2 lay)
  (TKA:PL (list (list x1 y1) (list x2 y1) (list x2 y2) (list x1 y2)) T lay))

;; TKA:Circle - cerc
(defun TKA:Circle (x y r lay)
  (TKA:Make (list '(0 . "CIRCLE") (cons 8 lay) (list 10 x y 0.0) (cons 40 r))))

;; TKA:Solid - suprafață plină (triunghi sau patrulater)
(defun TKA:Solid (pts lay)
  (TKA:Make (list '(0 . "SOLID") (cons 8 lay)
                  (append '(10) (car pts) '(0.0)) (append '(11) (cadr pts) '(0.0))
                  (append '(12) (caddr pts) '(0.0))
                  (append '(13) (if (cadddr pts) (cadddr pts) (caddr pts)) '(0.0)))))

;; TKA:Just - justificarea textului: "L" "C" "R" "ML" "MC" "MR" "TL" "TC" "TR" -> (72 . 73)
(defun TKA:Just (j)
  (cdr (assoc j '(("L" 0 . 0) ("C" 1 . 0) ("R" 2 . 0) ("ML" 0 . 2) ("MC" 1 . 2) ("MR" 2 . 2)
                  ("TL" 0 . 3) ("TC" 1 . 3) ("TR" 2 . 3) ("BL" 0 . 1) ("BC" 1 . 1) ("BR" 2 . 1)))))

;; TKA:T - text pe un singur rând (S cu marcaje de diacritice)
(defun TKA:T (s x y h rot j lay sty / jj)
  (setq jj (TKA:Just j))
  (TKA:Make (list '(0 . "TEXT") (cons 8 lay) (list 10 x y 0.0) (list 11 x y 0.0) (cons 40 h)
                  (cons 1 (TKA:R s)) (cons 50 rot) (cons 7 (if sty sty "TK_ARIAL"))
                  (cons 72 (car jj)) (cons 73 (cdr jj)))))

;; TKA:MT - text pe mai multe rânduri (MTEXT). ATT = punctul de prindere
;; (1 sus-stânga ... 5 centru ... 9 jos-dreapta); "\P" = rând nou
(defun TKA:MT (s x y h w att lay / d txt)
  (setq txt (TKA:R s)
        d (list '(0 . "MTEXT") '(100 . "AcDbEntity") (cons 8 lay) '(100 . "AcDbMText")
                (list 10 x y 0.0) (cons 40 h) (cons 41 w) (cons 71 att) '(72 . 5) '(7 . "TK_ARIAL")))
  (while (> (strlen txt) 250)
    (setq d (append d (list (cons 3 (substr txt 1 250)))) txt (substr txt 251)))
  (TKA:Make (append d (list (cons 1 txt)))))

;; TKA:Plain - lungimea vizibilă a unui text (marcajele contează un caracter)
(defun TKA:Plain (s / i n c out)
  (setq out "" i 1 n (strlen s))
  (while (<= i n)
    (setq c (substr s i 1))
    (cond ((assoc (substr s i 2) *TKA:DIA*) (setq out (strcat out "a") i (+ i 2)))
          (T (setq out (strcat out c) i (1+ i)))))
  out)

;; TKA:TW - lățimea estimată a unui text Arial cu înălțimea H (mm); un caracter
;; mediu are cca 0,64 din înălțimea majusculelor (măsurat pe planuri plotate)
(setq *TKA:CW* 0.64)
(defun TKA:TW (s h) (* *TKA:CW* h (strlen (TKA:Plain s))))

;; TKA:Lines - numărul estimat de rânduri ale unui text încadrat în lățimea W
(defun TKA:Lines (s h w / n)
  (setq n 0)
  (foreach part (TKA:Split s "\\P")
    (setq n (+ n (max 1 (fix (+ 0.999 (/ (TKA:TW part h) (max 1.0 w))))))))
  n)

;; TKA:Cell - celulă de tabel: chenar + text centrat (pe mai multe rânduri
;; dacă textul conține "\P" sau nu încape pe lățime)
(defun TKA:Cell (x1 y1 x2 y2 s h / w)
  (TKA:Box x1 y1 x2 y2 "PAD_TABEL")
  (setq w (- x2 x1 1.6))
  (if (and s (/= s ""))
    (if (or (vl-string-search "\\P" s) (> (TKA:TW s h) w))
      (TKA:MT s (/ (+ x1 x2) 2.0) (/ (+ y1 y2) 2.0) h w 5 "PAD_TEXT")
      (TKA:T s (/ (+ x1 x2) 2.0) (/ (+ y1 y2) 2.0) h 0.0 "MC" "PAD_TEXT" nil))))

;; TKA:Row - rând de tabel cu celulele de lățimi WIDTHS începând de la X0
(defun TKA:Row (x0 ytop h widths texts th / x)
  (setq x x0)
  (mapcar '(lambda (w s) (TKA:Cell x (- ytop h) (+ x w) ytop s th) (setq x (+ x w))) widths texts)
  (- ytop h))

;;; ==========================================================================
;;;  FORMATE, SCARĂ, LAYOUT ȘI VIEWPORT
;;; ==========================================================================

;; Formatele: (cod lățime înălțime format-hârtie orientare)
(setq *TKA:SHEETS*
  '(("A4P" 210.0 297.0 "A4" "P") ("A3P" 297.0 420.0 "A3" "P") ("A3L" 420.0 297.0 "A3" "L")
    ("A2L" 594.0 420.0 "A2" "L") ("A1L" 841.0 594.0 "A1" "L") ("A0L" 1189.0 841.0 "A0" "L")
    ("A4L" 297.0 210.0 "A4" "L") ("A2P" 420.0 594.0 "A2" "P")))
(setq *TKA:AUTOORDER* '("A4P" "A3P" "A3L" "A2L" "A1L" "A0L"))
(setq *TKA:SCALES* '(200 250 500 1000 2000 2500 5000))
(setq *TKA:BW* 185.0)      ; lățimea coloanei cu tabele (mm)

;; TKA:Sheet - geometria foii: W H x1 y1 x2 y2 (cadrul interior) și coloana
;; tabelelor bx1..bx2; HB = înălțimea tabelelor de jos, HH = înălțimea antetului
(defun TKA:Sheet (code hb / s w h x1 y1 x2 y2 bx1 land)
  (setq s (assoc code *TKA:SHEETS*) w (cadr s) h (caddr s)
        x1 20.0 y1 5.0 x2 (- w 5.0) y2 (- h 5.0)
        land (= (nth 4 s) "L")
        bx1 (if land (- x2 *TKA:BW*) (- (/ (+ x1 x2) 2.0) (/ *TKA:BW* 2.0))))
  (list (cons "CODE" code) (cons "W" w) (cons "H" h) (cons "X1" x1) (cons "Y1" y1) (cons "X2" x2)
        (cons "Y2" y2) (cons "BX1" bx1) (cons "BX2" (+ bx1 *TKA:BW*)) (cons "LAND" land)
        (cons "FMT" (nth 3 s)) (cons "ORI" (nth 4 s))
        ;; zona viewport-ului: la stânga coloanei (orizontal) sau între antet și tabele (vertical)
        (cons "VP" (if land
                     (list x1 y1 bx1 y2)
                     (list x1 (+ y1 hb) x2 (- y2 49.0))))))

;; TKA:SG - valoarea unei chei din geometria foii
(defun TKA:SG (sh k) (cdr (assoc k sh)))

;; TKA:FitScale - cea mai mare scară (numitorul cel mai mic) la care caseta
;; BB (xmin ymin xmax ymax, m) încape în viewport-ul foii SH; sau nil
(defun TKA:FitScale (sh bb fixed / vp vw vh bw bh res)
  (setq vp (TKA:SG sh "VP")
        vw (- (caddr vp) (car vp) 28.0) vh (- (cadddr vp) (cadr vp) 28.0)
        bw (max 1.0 (- (caddr bb) (car bb))) bh (max 1.0 (- (cadddr bb) (cadr bb))))
  (foreach s (if fixed (list fixed) *TKA:SCALES*)
    (if (and (null res) (<= (* bw (/ 1000.0 s)) vw) (<= (* bh (/ 1000.0 s)) vh))
      (setq res s)))
  res)

;; TKA:ChooseSheet - alege formatul și scara pentru caseta BB și tabelele de
;; înălțime HB. Automat: scara cea mai mare (1:200, 1:250, 1:500...) la care
;; imobilul încape pe A4 sau A3 (în această ordine), apoi formatele mari.
;; Formatul și/sau scara pot fi fixate din opțiuni. Returnează (foaie scară).
(defun TKA:ChooseSheet (bb hb / codes sh res)
  (setq codes (if (= *TKA:FORMAT* "AUTO") *TKA:AUTOORDER* (list *TKA:FORMAT*)))
  (foreach grup (if (= *TKA:FORMAT* "AUTO") (list (TKA:Firstn 3 codes) (TKA:Nthcdr 3 codes)) (list codes))
    (foreach s (if (> *TKA:SCARA* 0) (list *TKA:SCARA*) *TKA:SCALES*)
      (foreach c grup
        (if (and (null res) (TKA:FitScale (setq sh (TKA:Sheet c hb)) bb s))
          (setq res (list sh s))))))
  (if (null res)
    (progn
      (setq sh (TKA:Sheet (last codes) hb))
      (TKA:Msg "ATEN`TIE: imobilul nu ^incape pe formatul/scara aleas`a; se folose`ste scara cea mai mic`a.")
      (setq res (list sh (if (> *TKA:SCARA* 0) *TKA:SCARA* (last *TKA:SCALES*))))))
  res)

;; TKA:UniqueLayout - un nume de layout nefolosit (NUME, NUME_2, ...)
(defun TKA:UniqueLayout (name / lays i n)
  (setq lays (vla-get-Layouts *TK:DOC*) i 1 n name)
  (while (not (vl-catch-all-error-p (vl-catch-all-apply 'vla-Item (list lays n))))
    (setq i (1+ i) n (strcat name "_" (itoa i))))
  n)

;; TKA:NewLayout - creează layout-ul NAME cu setările de pagină DWG To PDF
;; pentru foaia SH (ISO full bleed, scara 1:1, mm) și îl activează
(defun TKA:NewLayout (name sh / lay media)
  (setq name (TKA:UniqueLayout name)
        lay (vla-Add (vla-get-Layouts *TK:DOC*) name)
        media (strcat "ISO_full_bleed_" (TKA:SG sh "FMT") "_("
                      (rtos (TKA:SG sh "W") 2 2) "_x_" (rtos (TKA:SG sh "H") 2 2) "_MM)"))
  (vl-catch-all-apply 'vla-put-ConfigName (list lay "DWG To PDF.pc3"))
  (vl-catch-all-apply 'vla-RefreshPlotDeviceInfo (list lay))
  (vl-catch-all-apply 'vla-put-CanonicalMediaName (list lay media))
  (vl-catch-all-apply 'vla-put-PaperUnits (list lay 1))            ; mm
  (vl-catch-all-apply 'vla-put-PlotRotation (list lay 0))
  (vl-catch-all-apply 'vla-put-StandardScale (list lay 16))        ; 1:1
  (vl-catch-all-apply 'vla-put-PlotType (list lay 5))              ; layout
  (vl-catch-all-apply 'vla-put-PlotWithLineweights (list lay :vlax-true))
  (setvar "CTAB" name)
  (setq *TKA:LAY* name)
  name)

;; TKA:Viewport - creează viewport-ul VP (x1 y1 x2 y2, mm) centrat pe
;; punctul CM (model) la scara 1:SCALE și calculează transformarea
;; model -> hârtie din parametrii reali ai viewport-ului
(defun TKA:Viewport (vp cm scale / ss i e vpe ed k c12 c17 c10)
  ;; viewport-urile create automat la activarea layout-ului se șterg
  (if (setq ss (ssget "_X" (list '(0 . "VIEWPORT") (cons 410 *TKA:LAY*))))
    (progn (setq i 0)
      (repeat (sslength ss)
        (setq e (ssname ss i) i (1+ i))
        (if (/= 1 (cdr (assoc 69 (entget e)))) (entdel e)))))
  (command "_.PSPACE")
  (command "_.MVIEW" (list (car vp) (cadr vp)) (list (caddr vp) (cadddr vp)))
  (setq vpe (entlast))
  (vl-catch-all-apply
    '(lambda ()
       (command "_.MSPACE")
       (setvar "CVPORT" (cdr (assoc 69 (entget vpe))))
       (command "_.PLAN" "_W")
       (command "_.ZOOM" "_C" (trans (list (car cm) (cadr cm) 0.0) 0 1) (strcat (rtos (/ 1000.0 scale) 2 8) "XP"))
       (command "_.PSPACE"))
    nil)
  (vl-catch-all-apply 'vla-put-DisplayLocked (list (vlax-ename->vla-object vpe) :vlax-true))
  (vl-catch-all-apply 'vla-put-Layer (list (vlax-ename->vla-object vpe) "PAD_VIEWPORT"))
  ;; transformarea reală: centrul viewport-ului pe hârtie, centrul vederii în model
  (setq ed (entget vpe) c10 (cdr (assoc 10 ed)) c12 (cdr (assoc 12 ed)) c17 (cdr (assoc 17 ed)))
  (setq k (if (and (assoc 41 ed) (assoc 45 ed) (> (cdr (assoc 45 ed)) 0))
            (/ (cdr (assoc 41 ed)) (cdr (assoc 45 ed)))
            (/ 1000.0 scale)))
  (setq *TKA:VPT*
         (if (and c10 c12 c17)
           (list (+ (car c17) (car c12)) (+ (cadr c17) (cadr c12)) (car c10) (cadr c10) k)
           (list (car cm) (cadr cm) (/ (+ (car vp) (caddr vp)) 2.0) (/ (+ (cadr vp) (cadddr vp)) 2.0) k)))
  vpe)

;; TKA:M2P - punct din model (m) -> punct pe hârtie (mm), prin viewport
(defun TKA:M2P (p / v)
  (setq v *TKA:VPT*)
  (list (+ (nth 2 v) (* (nth 4 v) (- (car p) (car v))))
        (+ (nth 3 v) (* (nth 4 v) (- (cadr p) (cadr v))))))

;; TKA:P2M - punct pe hârtie -> punct în model
(defun TKA:P2M (p / v)
  (setq v *TKA:VPT*)
  (list (+ (car v) (/ (- (car p) (nth 2 v)) (nth 4 v)))
        (+ (cadr v) (/ (- (cadr p) (nth 3 v)) (nth 4 v)))))

;;; ==========================================================================
;;;  ELEMENTELE COMUNE ALE PLANURILOR (cadru, antet, semnături)
;;; ==========================================================================

;; TKA:Frame - cadrul interior, eticheta anexei, titlul, scara și codul foii
(defun TKA:Frame (sh anexa titlu scale / x1 y1 x2 y2 bx1 bx2 cx th)
  (setq x1 (TKA:SG sh "X1") y1 (TKA:SG sh "Y1") x2 (TKA:SG sh "X2") y2 (TKA:SG sh "Y2")
        bx1 (TKA:SG sh "BX1") bx2 (TKA:SG sh "BX2") cx (/ (+ bx1 bx2) 2.0)
        th (if (= (TKA:SG sh "CODE") "A4P") 3.5 4.0))
  (TKA:Box x1 y1 x2 y2 "PAD_CADRU")
  (TKA:T (strcat "%%u" anexa) (- x2 3.0) (- y2 4.5) 2.5 0.0 "R" "PAD_TEXT" "TKA_ARIALI")
  ;; titlul (ajustat la lățimea coloanei dacă este lung)
  (if (> (TKA:TW titlu th) (- *TKA:BW* 6.0)) (setq th (/ (- *TKA:BW* 6.0) (* *TKA:CW* (strlen (TKA:Plain titlu))))))
  (TKA:T titlu cx (- y2 11.5) th 0.0 "C" "PAD_TEXT" nil)
  (TKA:T (strcat "Scara 1:" (itoa scale)) cx (- y2 18.0) (if (= (TKA:SG sh "CODE") "A4P") 3.5 4.0) 0.0 "C" "PAD_TEXT" nil)
  (TKA:T (strcat (TKA:SG sh "FMT") "-" (itoa scale)) (- (TKA:SG sh "W") 2.0) 1.2 1.6 0.0 "R" "PAD_TEXT" nil))

;; TKA:Header - tabelele de antet (nr. cadastral, suprafață, adresă; CF, UAT)
(defun TKA:Header (sh nrcad area adresa nrcf uat / x y th)
  (setq x (TKA:SG sh "BX1") y (- (TKA:SG sh "Y2") 20.5) th *TKA:TH*)
  (setq y (TKA:Row x y 5.2 '(54.3 57.3 73.4)
                   '("Num`ar cadastral" "Suprafa`ta m`asurat`a a imobilului (mp)" "Adresa imobilului") th))
  (setq y (TKA:Row x y (if (> (TKA:TW adresa th) 71.0) 8.4 5.2) '(54.3 57.3 73.4)
                   (list nrcad area adresa) th))
  (setq y (- y 3.9))
  (setq y (TKA:Row x y 5.2 '(92.5 92.5) '("Nr. Carte Funciar`a" "Unitatea Administrativ Teritorial`a (UAT)") th))
  (TKA:Row x y 5.2 '(92.5 92.5) (list nrcf uat) th))

;; TKA:Signatures - blocul de semnături Executant / Inspector
(defun TKA:Signatures (sh ytop / x1 x2 xm y1 txt)
  (setq x1 (TKA:SG sh "BX1") x2 (TKA:SG sh "BX2") xm (/ (+ x1 x2) 2.0) y1 (TKA:SG sh "Y1"))
  (TKA:Box x1 y1 xm ytop "PAD_TABEL")
  (TKA:Box xm y1 x2 ytop "PAD_TABEL")
  (setq txt (strcat "{\\fArial|b1|i0|c0|p34;Executant} " (TKA:ExecNume)
                    (if (/= (TKA:EGet "E_AUT_SERIA") "")
                      (strcat "\\Pautorizat ANCPI cu autoriza`tia\\Pseria " (TKA:EGet "E_AUT_SERIA")
                              ", nr. " (TKA:EGet "E_AUT_NR"))
                      "")
                    "\\P\\PConfirm executarea m`asur`atorilor la teren,\\Pcorectitudinea ^intocmirii documenta`tiei cadastrale `si"
                    "\\Pcoresponden`ta acesteia cu realitatea din teren\\P\\PSemn`atura `si `stampila\\P\\PData: " (TK:Today)))
  (TKA:MT txt (/ (+ x1 xm) 2.0) (- ytop 10.0) *TKA:TH* 88.0 2 "PAD_TEXT")
  (TKA:MT (strcat "Inspector\\P\\PConfirm introducerea imobilului ^in baza de date\\Pintegrat`a `si atribuirea num`arului cadastral"
                  "\\P\\PSemn`atura `si parafa\\P\\PData\\P`Stampila BCPI")
          (/ (+ xm x2) 2.0) (- ytop 10.0) *TKA:TH* 88.0 2 "PAD_TEXT"))

;; Înălțimea blocului de semnături (mm)
(setq *TKA:HSIGN* 65.6)


;;; ==========================================================================
;;;  DESENUL IMOBILULUI PE PLAN (paper space, prin transformarea viewport-ului)
;;; ==========================================================================

;; TKA:Unit - vectorul unitar
(defun TKA:Unit (v / l)
  (setq l (sqrt (+ (* (car v) (car v)) (* (cadr v) (cadr v)))))
  (if (> l 1e-12) (list (/ (car v) l) (/ (cadr v) l)) (list 0.0 0.0)))

;; TKA:OutNormal - normala exterioară a laturii AB a unui poligon parcurs orar
(defun TKA:OutNormal (a b) (TKA:Unit (list (- (cadr a) (cadr b)) (- (car b) (car a)))))

;; TKA:Readable - unghiul unui text paralel cu o latură, astfel încât să se citească de jos/stânga
(defun TKA:Readable (a)
  (setq a (TK:Mod2Pi a))
  (if (and (> a (+ (/ pi 2.0) 1e-9)) (<= a (+ (* 1.5 pi) 1e-9))) (- a pi) a))

;; TKA:SegKey - cheia unui segment, independentă de sens
(defun TKA:SegKey (a b / ka kb)
  (setq ka (TKA:PtKey a) kb (TKA:PtKey b))
  (if (< ka kb) (strcat ka "|" kb) (strcat kb "|" ka)))

;; TKA:Ring - poligonul din model desenat pe hârtie
(defun TKA:Ring (pts lay) (TKA:PL (mapcar 'TKA:M2P pts) T lay))

;; TKA:PointNumbers - numerele punctelor (în exteriorul poligonului) și
;; marcajele vertex-urilor; DRAWN = punctele deja etichetate
(defun TKA:PointNumbers (pts tab drawn / n i prev next pp bis)
  (setq n (length pts) i 0)
  (foreach p pts
    (if (and (TKA:PtNo p tab) (not (member (TKA:PtKey p) drawn)))
      (progn
        (setq prev (nth (rem (+ i n -1) n) pts) next (nth (rem (1+ i) n) pts) pp (TKA:M2P p)
              bis (TKA:Unit (TK:v+ (TKA:OutNormal (TKA:M2P prev) pp) (TKA:OutNormal pp (TKA:M2P next)))))
        (if (equal bis '(0.0 0.0) 1e-9) (setq bis (TKA:OutNormal pp (TKA:M2P next))))
        (TKA:Circle (car pp) (cadr pp) 0.35 "PAD_PUNCTE")
        (TKA:T (itoa (TKA:PtNo p tab)) (+ (car pp) (* 2.1 (car bis))) (+ (cadr pp) (* 2.1 (cadr bis)))
               *TKA:LH* 0.0 "MC" "PAD_PUNCTE" nil)
        (setq drawn (cons (TKA:PtKey p) drawn))))
    (setq i (1+ i)))
  drawn)

;; TKA:Lengths - lungimile laturilor (paralele cu latura, spre exterior);
;; DRAWN = segmentele deja cotate (laturile comune se cotează o singură dată)
(defun TKA:Lengths (pts drawn / pa pb mid nn key)
  (mapcar
    '(lambda (a b)
       (setq key (TKA:SegKey a b))
       (if (not (member key drawn))
         (progn
           (setq pa (TKA:M2P a) pb (TKA:M2P b) mid (TK:Mid pa pb) nn (TKA:OutNormal pa pb))
           (TKA:T (strcat (TKA:Num (distance a b) 2) " m")
                  (+ (car mid) (* 1.25 (car nn))) (+ (cadr mid) (* 1.25 (cadr nn)))
                  *TKA:LH* (TKA:Readable (angle pa pb)) "MC" "PAD_COTE" nil)
           (setq drawn (cons key drawn)))))
    pts (append (cdr pts) (list (car pts))))
  drawn)

;; TKA:SideLabel - textul afișat pentru vecinul unei laturi
(defun TKA:SideLabel (s) (if (/= (nth 6 s) "") (nth 6 s) (nth 7 s)))

;; TKA:Neighbors - etichetele vecinilor: o etichetă pentru fiecare șir de
;; laturi consecutive cu același vecin, pe latura cea mai lungă a șirului.
;; Eticheta nu se repetă dacă același text există deja în model lângă latură
;; (este vizibil prin viewport).
(defun TKA:Neighbors (sides / groups cur lab best pa pb mid nn texts dmax)
  (foreach s sides
    (setq lab (TKA:SideLabel s))
    (if (and cur (= lab (car cur)))
      (setq cur (list lab (cons s (cadr cur))))
      (progn (if cur (setq groups (cons cur groups))) (setq cur (list lab (list s))))))
  (if cur (setq groups (cons cur groups)))
  (setq groups (reverse groups))
  (if (and (cdr groups) (= (car (car groups)) (car (last groups))))
    (setq groups (cons (list (car (car groups)) (append (cadr (car groups)) (cadr (last groups))))
                       (reverse (cdr (reverse (cdr groups)))))))
  (setq texts (TKA:Texts) dmax (/ 30.0 (nth 4 *TKA:VPT*)))
  (foreach g groups
    (if (/= (car g) "")
      (progn
        (setq best (car (vl-sort (cadr g) '(lambda (a b) (> (nth 5 a) (nth 5 b))))))
        (if (not (vl-some '(lambda (t1) (and (= (strcase (cadr t1)) (strcase (car g)))
                                             (< (distance (car t1) (TK:Mid (nth 3 best) (nth 4 best))) dmax)))
                          texts))
          (progn
            (setq pa (TKA:M2P (nth 3 best)) pb (TKA:M2P (nth 4 best)) mid (TK:Mid pa pb) nn (TKA:OutNormal pa pb))
            (TKA:T (car g) (+ (car mid) (* 4.3 (car nn))) (+ (cadr mid) (* 4.3 (cadr nn)))
                   *TKA:LH* (TKA:Readable (angle pa pb)) "MC" "PAD_VECINI" nil)))))))

;; TKA:Constructions - conturul construcțiilor și codurile C1, C2...
(defun TKA:Constructions (constr / lp)
  (foreach c constr
    (TKA:Ring (if (> (TKA:SArea (nth 9 c)) 0) (reverse (nth 9 c)) (nth 9 c)) "PAD_CONSTR")
    (setq lp (TKA:M2P (TKA:LabelPoint (nth 9 c))))
    (TKA:T (nth 1 c) (car lp) (cadr lp) 2.0 0.0 "MC" "PAD_CONSTR" "TKA_ARIALB")))

;; TKA:Parcels - parcelele de folosință (dacă imobilul are mai multe)
(defun TKA:Parcels (parcs constr / lp)
  (if (cdr parcs)
    (foreach p parcs
      (TKA:Ring (nth 3 p) "PAD_PARCELE")
      (setq lp (TKA:M2P (TKA:FreePoint (nth 3 p) (mapcar '(lambda (c) (nth 9 c)) constr))))
      (TKA:T (strcat (itoa (car p)) (cadr p)) (car lp) (cadr lp) 1.8 0.0 "MC" "PAD_PARCELE" nil))))

;; TKA:North - săgeata nordului: tija verticală (X,Y)-(X,Y+22), vârful cu
;; jumătatea stângă plină și litera N sub tijă
(defun TKA:North (x y)
  (TKA:L x y x (+ y 22.0) "PAD_TEXT")
  (TKA:Solid (list (list x (+ y 22.0)) (list (- x 2.2) (+ y 12.0)) (list x (+ y 14.5))) "PAD_TEXT")
  (TKA:PL (list (list x (+ y 22.0)) (list (+ x 2.2) (+ y 12.0)) (list x (+ y 14.5))) T "PAD_TEXT")
  (TKA:T "N" x (- y 1.5) 5.0 0.0 "TC" "PAD_TEXT" "TKA_ARIALB"))

;; TKA:Corners - marcajele de colț ale viewport-ului cu coordonatele N= și E=
;; (valori întregi, poziționate exact în viewport)
(defun TKA:Corners (vp / x1 y1 x2 y2 m1 m2 e1 e2 n1 n2 lab p)
  (setq x1 (car vp) y1 (cadr vp) x2 (caddr vp) y2 (cadddr vp)
        m1 (TKA:P2M (list (+ x1 2.0) (+ y1 2.0))) m2 (TKA:P2M (list (- x2 2.0) (- y2 2.0)))
        e1 (float (fix (+ (car m1) 0.999))) e2 (float (fix (car m2)))
        n1 (float (fix (+ (cadr m1) 0.999))) n2 (float (fix (cadr m2))))
  (foreach c (list (list e1 n2 1 -1) (list e2 n2 -1 -1) (list e1 n1 1 1) (list e2 n1 -1 1))
    (setq lab (TKA:EN (list (car c) (cadr c)))
          p (TKA:M2P (list (car c) (cadr c))))
    (TKA:L (car p) (cadr p) (+ (car p) (* 8.0 (caddr c))) (cadr p) "PAD_GRID")
    (TKA:L (car p) (cadr p) (car p) (+ (cadr p) (* 8.0 (cadddr c))) "PAD_GRID")
    (TKA:T (strcat "N=" (rtos (cadr lab) 2 0)) (+ (car p) (* 0.8 (caddr c))) (+ (cadr p) (* 0.9 (cadddr c)))
           1.4 0.0 (if (> (caddr c) 0) (if (> (cadddr c) 0) "BL" "TL") (if (> (cadddr c) 0) "BR" "TR")) "PAD_GRID" nil)
    (TKA:T (strcat "E=" (rtos (car lab) 2 0)) (- (car p) (* 0.9 (caddr c))) (+ (cadr p) (* 0.8 (cadddr c)))
           1.4 (/ pi 2.0) (if (> (cadddr c) 0) (if (> (caddr c) 0) "BL" "TL") (if (> (caddr c) 0) "BR" "TR"))
           "PAD_GRID" nil)))

;; TKA:Overlap - aria comună a două casete (xmin ymin xmax ymax)
(defun TKA:Overlap (a b)
  (* (max 0.0 (- (min (caddr a) (caddr b)) (max (car a) (car b))))
     (max 0.0 (- (min (cadddr a) (cadddr b)) (max (cadr a) (cadr b))))))

;; TKA:Inventar - inventarul de coordonate pe plan (opțional), în colțul
;; viewport-ului cel mai puțin ocupat de imobil (fără marcajele de colț și
;; săgeata nordului)
(defun TKA:Inventar (rec vp / sides n h w x y bb best bo o en)
  (setq sides (TKA:R1 rec "SIDES") n (length sides) h (+ 13.5 (* 3.2 n)) w 52.0
        bb (TKA:Bbox (mapcar 'TKA:M2P (TKA:R1 rec "PTS")))
        bb (list (- (car bb) 8.0) (- (cadr bb) 8.0) (+ (caddr bb) 8.0) (+ (cadddr bb) 8.0))
        bo 1e99)
  (foreach c (list (list (- (caddr vp) w 12.0) (- (cadddr vp) 12.0))
                   (list (- (caddr vp) w 12.0) (+ (cadr vp) h 12.0))
                   (list (+ (car vp) 12.0) (+ (cadr vp) h 12.0))
                   (list (+ (car vp) 26.0) (- (cadddr vp) 12.0)))
    (if (< (setq o (TKA:Overlap (list (car c) (- (cadr c) h) (+ (car c) w) (cadr c)) bb)) (- bo 1e-6))
      (setq bo o best c)))
  (setq x (car best) y (cadr best))
  (setq y (TKA:Row x y 4.5 (list w) '("Inventar de coordonate (Stereo 70)") 1.8))
  (setq y (TKA:Row x y 4.5 '(10.0 21.0 21.0) '("Pct." "X [m]" "Y [m]") 1.8))
  (foreach s sides
    (setq en (TKA:EN (nth 3 s))
          y (TKA:Row x y 3.2 '(10.0 21.0 21.0) (list (itoa (nth 1 s)) (TKA:Num (cadr en) 3) (TKA:Num (car en) 3)) 1.6)))
  (TKA:Row x y 4.5 (list w) (list (strcat "S=" (itoa (TKA:R1 rec "AREA")) " mp  P=" (TKA:Num (TKA:R1 rec "PERIM") 2) " m")) 1.8))

;;; ==========================================================================
;;;  TABELELE PLANURILOR
;;; ==========================================================================

(setq *TKA:WAB* '(15.7 33.3 43.5 92.5))   ; coloanele tabelelor A și B

;; TKA:RowsA - înălțimea rândurilor tabelului A (mențiunile încap în celula comasată)
(defun TKA:RowsA (parcs ment / n need)
  (setq n (length parcs) need (+ 2.5 (* 3.6 (TKA:Lines ment *TKA:TH* 89.0))))
  (max 6.6 (/ (- need 4.7) n)))

;; TKA:RowB - înălțimea rândului unei construcții (după mențiuni)
(defun TKA:RowB (c) (max 6.6 (+ 2.5 (* 3.6 (TKA:Lines (TKA:ConstrMentiuni c) *TKA:TH* 89.0)))))

;; TKA:HeightA16 - înălțimea totală a tabelelor de jos ale anexei 16
(defun TKA:HeightA16 (rec ment / parcs constr)
  (setq parcs (TKA:R1 rec "PARCELE") constr (TKA:R1 rec "CONSTR"))
  (+ 4.8 9.4 (* (length parcs) (TKA:RowsA parcs ment)) 4.7
     4.7 9.5 (if constr (apply '+ (mapcar 'TKA:RowB constr)) 12.0) 4.7
     9.5 *TKA:HSIGN*))

;; TKA:TableA - tabelul A (teren); returnează ordonata de jos
(defun TKA:TableA (x y rec ment / parcs rh ytop th)
  (setq parcs (TKA:R1 rec "PARCELE") rh (TKA:RowsA parcs ment) th *TKA:TH*)
  (setq y (TKA:Row x y 4.8 '(185.0) '("A. Date referitoare la teren") th))
  (setq y (TKA:Row x y 9.4 *TKA:WAB* '("Nr.\\Pparcel`a" "Categoria de\\Pfolosin`t`a" "Suprafa`ta\\P(mp)" "Men`tiuni") th))
  (setq ytop y)
  (foreach p parcs
    (setq y (TKA:Row x y rh '(15.7 33.3 43.5) (list (itoa (car p)) (cadr p) (itoa (caddr p))) th)))
  (setq y (TKA:Row x y 4.7 '(49.0 43.5) (list "Total" (itoa (TKA:R1 rec "AREA"))) th))
  (TKA:Cell (+ x 92.5) y (+ x 185.0) ytop ment th)
  y)

;; TKA:TableB - tabelul B (construcții); returnează ordonata de jos
(defun TKA:TableB (x y rec / constr th ytop)
  (setq constr (TKA:R1 rec "CONSTR") th *TKA:TH*)
  (setq y (TKA:Row x y 4.7 '(185.0) '("B. Date referitoare la construc`tii") th))
  (setq y (TKA:Row x y 9.5 *TKA:WAB* '("Cod" "Destina`tia" "Suprafa`ta construit`a la sol\\P(mp)" "Men`tiuni") th))
  (if constr
    (foreach c constr
      (setq y (TKA:Row x y (TKA:RowB c) *TKA:WAB*
                       (list (nth 1 c) (nth 2 c) (itoa (nth 8 c)) (TKA:ConstrMentiuni c)) th)))
    (setq y (TKA:Row x y 12.0 *TKA:WAB* '("-" "-" "-" "-") th)))
  (TKA:Row x y 4.7 '(49.0 43.5 92.5)
           (list "Total" (if constr (itoa (apply '+ (mapcar '(lambda (c) (nth 8 c)) constr))) "-") "")
           th))

;; TKA:Surfaces - suprafața totală măsurată și suprafața din act
(defun TKA:Surfaces (x y area sact)
  (TKA:Box x (- y 9.5) (+ x 185.0) y "PAD_TABEL")
  (TKA:MT (strcat "Suprafa`ta total`a m`asurat`a a imobilului = " (itoa area) " mp\\PSuprafa`ta din act = "
                  (if (/= sact "") sact "-") " mp")
          (+ x 92.5) (- y 4.75) *TKA:TH* 180.0 5 "PAD_TEXT")
  (- y 9.5))

;; Coloanele tabelului anexei 17 (pentru fiecare jumătate)
(setq *TKA:W17* '(18.5 14.5 19.0 40.5))

;; TKA:Height17 - înălțimea tabelului anexei 17 (fără semnături)
(defun TKA:Height17 (left right) (+ 6.3 7.7 (* 6.1 (max (length left) (length right) 1)) 6.4))

;; TKA:Half17 - o jumătate a tabelului anexei 17. ROWS = ((nrcad supr categ descriere) ...)
;; Dacă jumătatea are un singur rând iar cealaltă mai multe, celulele se comasează.
(defun TKA:Half17 (x y rows n th)
  (if (and (= (length rows) 1) (> n 1))
    (TKA:Row x y (* 6.1 n) *TKA:W17* (car rows) th)
    (progn
      (foreach r rows (setq y (TKA:Row x y 6.1 *TKA:W17* r th)))
      (repeat (- n (length rows)) (setq y (TKA:Row x y 6.1 *TKA:W17* '("" "" "" "") th))))))

;; TKA:SumRows - suma suprafețelor (coloana 2) din rândurile tabelului anexei 17
(defun TKA:SumRows (rows) (apply '+ (mapcar '(lambda (r) (atoi (cadr r))) rows)))

;; TKA:Table17 - tabelul "Situația actuală / Situația viitoare"; MODE = "DEZ"/"ALIP"
(defun TKA:Table17 (x y left right mode / th n yh)
  (setq th *TKA:TH* n (max (length left) (length right) 1))
  (setq y (TKA:Row x y 6.3 '(92.5 92.5)
                   (if (= mode "ALIP")
                     '("Situa`tia actual`a (^inainte de alipire)" "Situa`tia viitoare (dup`a alipire)")
                     '("Situa`tia actual`a (^inainte de dezlipire)" "Situa`tia viitoare (dup`a dezlipire)"))
                   th))
  (setq y (TKA:Row x y 7.7 (append *TKA:W17* *TKA:W17*)
                   '("Nr. cad." "Suprafa`ta\\P(mp)" "Categoria de\\Pfolosin`t`a" "Descrierea imobilului"
                     "Nr. cad." "Suprafa`ta\\P(mp)" "Categoria de\\Pfolosin`t`a" "Descrierea imobilului")
                   th))
  (setq yh y)
  (TKA:Half17 x yh left n th)
  (TKA:Half17 (+ x 92.5) yh right n th)
  (setq y (- yh (* 6.1 n)))
  (TKA:Row x y 6.4 (append *TKA:W17* *TKA:W17*)
           (list "Total" (itoa (TKA:SumRows left)) "-" "-" "Total" (itoa (TKA:SumRows right)) "-" "-") th))

;;; ==========================================================================
;;;  GENERAREA PLANURILOR
;;; ==========================================================================

;; TKA:Ment - mențiunile tabelului A: textul dat de utilizator (datele lucrării
;; sau, pentru un lot, ale entității) ori, dacă lipsește, textul compus din
;; materializarea laturilor. LOT = T pentru loturi și imobilul rezultat.
(defun TKA:Ment (rec lot / m)
  (setq m (if lot (TKA:LGet (TKA:R1 rec "E") "MENT")))
  (cond ((and m (/= m "")) m)
        ((and (not lot) (/= (TKA:Get "MENT_TEREN") "")) (TKA:Get "MENT_TEREN"))
        ((TKA:MentAuto (TKA:R1 rec "SIDES")))
        (T "-")))

;; TKA:MentAuto - mențiunile din materializarea laturilor: "Imobil împrejmuit
;; cu gard de plasă." sau, pentru laturi diferite, "Limite: gard de plasă
;; (1-2, 2-3); nematerializat (3-4)."; nil dacă materializarea nu e completată
(defun TKA:MentAuto (sides / mats)
  (setq mats (TKA:Uniq (mapcar '(lambda (s) (nth 8 s)) sides)))
  (cond
    ((or (null mats) (equal mats '(""))) nil)
    ((null (cdr mats))
     (if (= (car mats) "nematerializat")
       "Imobil ne^imprejmuit."
       (strcat "Imobil ^imprejmuit cu " (car mats) ".")))
    (T
     (strcat "Limite: "
             (TKA:Join
               (mapcar '(lambda (m)
                          (strcat (if (= m "") "nematerializat" m) " ("
                                  (TKA:Join (mapcar '(lambda (s) (strcat (itoa (nth 1 s)) "-" (itoa (nth 2 s))))
                                                    (vl-remove-if-not '(lambda (s) (= (nth 8 s) m)) sides))
                                            ", ")
                                  ")"))
                       mats)
               "; ")
             "."))))

;; TKA:Bounds - caseta modelului care trebuie să încapă pe plan
(defun TKA:Bounds (ptss / all)
  (foreach p ptss (setq all (append p all)))
  (TKA:Bbox all))

;; TKA:Start16 - pregătește foaia: alege formatul/scara, creează layout-ul,
;; viewport-ul, cadrul și antetul. Returnează (foaie scară viewport).
(defun TKA:Sheet16 (name bb hb anexa titlu nrcad area adresa nrcf uat / ch sh sc vp)
  (setq ch (TKA:ChooseSheet bb hb) sh (car ch) sc (cadr ch) vp (TKA:SG sh "VP"))
  (TKA:NewLayout name sh)
  (TKA:Viewport vp (list (/ (+ (car bb) (caddr bb)) 2.0) (/ (+ (cadr bb) (cadddr bb)) 2.0)) sc)
  (TKA:Frame sh anexa titlu sc)
  (TKA:Header sh nrcad area adresa nrcf uat)
  (TKA:North (+ (car vp) 14.0) (- (cadddr vp) 30.0))
  (TKA:Corners vp)
  (list sh sc vp))

;; TKA:Pad16 - Anexa 16 pentru imobilul REC. SUFIX = " - lot 1" etc.,
;; NRCAD/NRCF = numerele afișate în antet (vide pentru loturi noi)
(defun TKA:Pad16 (rec sufix nrcad nrcf name / ment hb s sh x y drawn)
  (setq ment (TKA:Ment rec (/= sufix ""))
        hb (TKA:HeightA16 rec ment))
  (setq s (TKA:Sheet16 name (TKA:Bounds (list (TKA:R1 rec "PTS"))) hb *TKA:ANEXA16*
                       (strcat "Plan de amplasament `si delimitare a imobilului" sufix)
                       nrcad (itoa (TKA:R1 rec "AREA")) (TKA:Adresa) nrcf (TKA:Get "UAT"))
        sh (car s))
  ;; tabelele, de jos în sus
  (setq x (TKA:SG sh "BX1") y (+ (TKA:SG sh "Y1") hb))
  (setq y (TKA:TableA x y rec ment))
  (setq y (TKA:TableB x y rec))
  ;; suprafața din act: a imobilului; pentru loturi/imobilul rezultat, suprafața propusă
  (setq y (TKA:Surfaces x y (TKA:R1 rec "AREA") (if (/= sufix "") (itoa (TKA:R1 rec "AREA")) (TKA:Get "SACT"))))
  (TKA:Signatures sh y)
  ;; desenul
  (TKA:Parcels (TKA:R1 rec "PARCELE") (TKA:R1 rec "CONSTR"))
  (TKA:Constructions (TKA:R1 rec "CONSTR"))
  (TKA:Ring (TKA:R1 rec "PTS") "PAD_CONTUR")
  (TKA:Lengths (TKA:R1 rec "PTS") nil)
  (TKA:PointNumbers (TKA:R1 rec "PTS") (TKA:R1 rec "TAB") nil)
  (TKA:Neighbors (TKA:R1 rec "SIDES"))
  (if (= *TKA:INVPAD* "1") (TKA:Inventar rec (caddr s)))
  (TKA:Msg (strcat "Plan generat ^in layout-ul \"" *TKA:LAY* "\": " (TKA:SG sh "FMT")
                    (if (TKA:SG sh "LAND") " landscape" " portrait") ", scara 1:" (itoa (cadr s)) "."))
  *TKA:LAY*)

;; TKA:LotRows - rândurile tabelului anexei 17 pentru o listă de imobile
(defun TKA:LotRows (recs prefix / i out cats)
  (setq i 0)
  (foreach r recs
    (setq i (1+ i)
          cats (TKA:Uniq (mapcar 'cadr (TKA:R1 r "PARCELE"))))
    (setq out (cons (list (cond ((TKA:R1 r "NRCAD")) (""))
                          (itoa (TKA:R1 r "AREA"))
                          (TKA:Join cats ", ")
                          (TKA:Join (list (if prefix (strcat prefix " " (itoa i)) nil)
                                          (TKA:Join (mapcar 'TKA:CategText cats) ", "))
                                    " - "))
                    out)))
  (reverse out))

;; TKA:Uniq - lista fără duplicate (păstrând ordinea)
(defun TKA:Uniq (l / out) (foreach x l (if (not (member x out)) (setq out (cons x out)))) (reverse out))

;; TKA:Pad17 - Anexa 17: PARENT = imobilul inițial (sau imobilul rezultat la
;; alipire), LOTS = imobilele rezultate (sau inițiale la alipire), MODE "DEZ"/"ALIP"
(defun TKA:Pad17 (parent lots mode name / left right hb s sh x y drawn ptss i lp)
  (if (= mode "ALIP")
    (setq left (TKA:LotRows lots nil)
          right (list (list "" (itoa (TKA:R1 parent "AREA"))
                            (TKA:Join (TKA:Uniq (mapcar 'cadr (TKA:R1 parent "PARCELE"))) ", ")
                            "Imobil rezultat din alipire")))
    (setq left (list (list (TKA:Get "NRCAD") (itoa (TKA:R1 parent "AREA"))
                           (TKA:Join (TKA:Uniq (mapcar 'cadr (TKA:R1 parent "PARCELE"))) ", ")
                           (TKA:Join (mapcar 'TKA:CategText (TKA:Uniq (mapcar 'cadr (TKA:R1 parent "PARCELE")))) ", ")))
          right (TKA:LotRows lots "Lot")))
  (setq hb (+ (TKA:Height17 left right) *TKA:HSIGN*))
  (setq ptss (cons (TKA:R1 parent "PTS") (mapcar '(lambda (r) (TKA:R1 r "PTS")) lots)))
  (setq s (TKA:Sheet16 name (TKA:Bounds ptss) hb *TKA:ANEXA17*
                       (if (= mode "ALIP")
                         "Plan de amplasament `si delimitare a imobilului cu propunerea de alipire"
                         "Plan de amplasament `si delimitare a imobilului cu propunerea de dezlipire")
                       (if (= mode "ALIP") "" (TKA:Get "NRCAD")) (itoa (TKA:R1 parent "AREA")) (TKA:Adresa)
                       (if (= mode "ALIP") "" (TKA:Get "NRCF")) (TKA:Get "UAT"))
        sh (car s))
  (setq x (TKA:SG sh "BX1") y (+ (TKA:SG sh "Y1") hb))
  (TKA:Table17 x y left right mode)
  (TKA:Signatures sh (+ (TKA:SG sh "Y1") *TKA:HSIGN*))
  ;; desenul: imobilul, loturile, numerotarea globală, cotele, vecinii
  (TKA:Constructions (TKA:R1 parent "CONSTR"))
  (foreach r lots (TKA:Ring (TKA:R1 r "PTS") "PAD_LOTURI"))
  (TKA:Ring (TKA:R1 parent "PTS") "PAD_CONTUR")
  (setq drawn (TKA:Lengths (TKA:R1 parent "PTS") nil))
  (foreach r lots (setq drawn (TKA:Lengths (TKA:R1 r "PTS") drawn)))
  (setq drawn (TKA:PointNumbers (TKA:R1 parent "PTS") (TKA:R1 parent "TAB") nil))
  (foreach r lots (setq drawn (TKA:PointNumbers (TKA:R1 r "PTS") (TKA:R1 parent "TAB") drawn)))
  (TKA:Neighbors (TKA:R1 parent "SIDES"))
  (setq i 0)
  (foreach r lots
    (setq i (1+ i)
          lp (TKA:M2P (TKA:FreePoint (TKA:R1 r "PTS") (mapcar '(lambda (c) (nth 9 c)) (TKA:R1 parent "CONSTR")))))
    (TKA:MT (strcat (if (= mode "ALIP") (strcat "Imobil " (itoa i)) (strcat "Lot " (itoa i)))
                    "\\PS=" (itoa (TKA:R1 r "AREA")) " mp")
            (car lp) (cadr lp) 1.8 30.0 5 "PAD_LOTURI"))
  (TKA:Msg (strcat "Plan (anexa 17) generat ^in layout-ul \"" *TKA:LAY* "\", scara 1:" (itoa (cadr s)) "."))
  *TKA:LAY*)


;;; ==========================================================================
;;;  DIALOGURI
;;; ==========================================================================

;; TKA:Ascii - text fără diacritice (pentru dialoguri și linia de comandă)
(defun TKA:Ascii (s / out i n p)
  (setq out "" i 1 n (strlen s))
  (while (<= i n)
    (if (setq p (assoc (substr s i 2) *TKA:DIA*))
      (setq out (strcat out (substr (car p) 2 1)) i (+ i 2))
      (setq out (strcat out (substr s i 1)) i (1+ i))))
  out)

;; TKA:Msg - mesaj în linia de comandă
(defun TKA:Msg (s) (princ (strcat "\n" (TKA:Ascii s))))

;; TKA:DclPath - fișierul TopoKitAnexe.dcl (sau o copie generată din sursă)
(defun TKA:DclPath (/ f lsp fh)
  (cond
    ((findfile "TopoKitAnexe.dcl"))
    ((and (setq lsp (findfile "TopoKitAnexe.lsp"))
          (findfile (setq f (strcat (vl-filename-directory lsp) "\\TopoKitAnexe.dcl"))))
     f)
    ((and *TKA:DCLTMP* (findfile *TKA:DCLTMP*)) *TKA:DCLTMP*)
    ((setq fh (open (setq f (vl-filename-mktemp "TopoKitAnexe" nil ".dcl")) "w"))
     (foreach l (TKA:DclLines) (write-line l fh))
     (close fh)
     (setq *TKA:DCLTMP* f))))

;; TKA:Dialog - deschide dialogul NAME; INIT se execută după new_dialog;
;; returnează rezultatul start_dialog (sau nil)
(defun TKA:Dialog (name init / id res)
  (setq id (load_dialog (TKA:DclPath)))
  (cond
    ((< id 0) (alert "Nu s-a putut incarca TopoKitAnexe.dcl.") nil)
    ((not (new_dialog name id)) (unload_dialog id) (alert (strcat "Dialogul " name " lipseste.")) nil)
    (T
     (eval init)
     (setq res (start_dialog))
     (unload_dialog id)
     res)))

;; TKA:FillList - completează un popup_list/list_box
(defun TKA:FillList (key items)
  (start_list key)
  (foreach i items (add_list (TKA:Ascii i)))
  (end_list))

;; Câmpurile dialogurilor de date
(setq *TKA:F_IMOBIL*
  '("NRCAD" "NRCF" "UAT" "LOCALITATE" "JUDET" "STRADA" "NR" "BLOC" "SCARA" "ETAJ" "AP" "TARLA"
    "PARCELA" "NRTOP" "DENUMIRE_LOC" "SACT" "ACT_PROP" "MENT_TEREN" "OCPI" "BCPI"
    "P1_NUME" "P1_PRENUME" "P1_CNP" "P1_CI_SERIA" "P1_CI_NR" "P1_CI_EMITENT" "P1_LOC" "P1_STR"
    "P1_NR" "P1_BL" "P1_SC" "P1_ET" "P1_AP" "P1_JUD" "P1_CODP" "P1_TEL" "P1_EMAIL" "P1_CALITATE"
    "P2_NUME" "P2_PRENUME" "P2_CNP" "P2_CI_SERIA" "P2_CI_NR" "P2_LOC" "P2_CALITATE"))
(setq *TKA:F_LUCRARE*
  '("INTAB_OBIECT" "E_CONTRACT" "E_CONTRACT_DATA" "DATA_MAS" "PV_EXEMPLARE" "PV_PAGINI" "NRCF_COLECTIVA" "ST_AFERENT"
    "PARTI_COMUNE" "METODA" "APARATURA" "SPRIJIN" "SCOP" "DOCUMENTARE" "OPERATIUNI"))
(setq *TKA:F_EXEC*
  '("E_TITLU" "E_NUME" "E_PRENUME" "E_CNP" "E_FIRMA" "E_CI_SERIA" "E_CI_NR" "E_TEL" "E_EMAIL"
    "E_CAT" "E_AUT_SERIA" "E_AUT_NR" "E_AUT_EMITENT" "E_AUT_DATA" "E_LOC" "E_STR" "E_NR" "E_JUD"))

;; TKA:ImobilDialog - datele imobilului și ale proprietarilor
(defun TKA:ImobilDialog ()
  (TKA:Dialog "tka_imobil"
    '(progn
       (foreach k *TKA:F_IMOBIL* (set_tile k (TKA:Get k)))
       (TKA:FillList "CATEG" (mapcar '(lambda (c) (strcat (car c) " - " (cdr c))) *TKA:CATEG*))
       (set_tile "CATEG" (itoa (max 0 (TKA:Index (if (/= (TKA:Get "CATEG") "") (TKA:Get "CATEG") "CC")
                                                (mapcar 'car *TKA:CATEG*)))))
       (action_tile "accept"
         "(foreach k *TKA:F_IMOBIL* (TKA:Put k (TKA:Trim (get_tile k)))) (TKA:Put \"CATEG\" (car (nth (atoi (get_tile \"CATEG\")) *TKA:CATEG*))) (done_dialog 1)"))))

;; TKA:Index - poziția lui X în lista L (sau -1)
(defun TKA:Index (x l / i r)
  (setq i 0 r -1)
  (foreach y l (if (and (= r -1) (equal x y)) (setq r i)) (setq i (1+ i)))
  r)

;; TKA:LucrareDialog - tipul lucrării și textele memoriului tehnic
(defun TKA:LucrareDialog ()
  (TKA:Dialog "tka_lucrare"
    '(progn
       (foreach k *TKA:F_LUCRARE* (set_tile k (TKA:Get k)))
       (TKA:FillList "TIP" (mapcar 'cadr *TKA:TIPURI*))
       (set_tile "TIP" (itoa (max 0 (TKA:Index (TKA:Get "TIP") (mapcar 'car *TKA:TIPURI*)))))
       (TKA:FillList "COMUNICARE" '("Online in sistemul integrat de cadastru si carte funciara"
                                    "Prin posta" "La sediul BCPI" "Prin e-mail" "Prin fax"))
       (set_tile "COMUNICARE" (itoa (max 0 (TKA:Index (TKA:Get "COMUNICARE") (mapcar 'car *TKA:COMUNIC*)))))
       (set_tile "POZ_INCERTA" (if (= (TKA:Get "POZ_INCERTA") "1") "1" "0"))
       (action_tile "accept"
         (strcat "(foreach k *TKA:F_LUCRARE* (TKA:Put k (TKA:Trim (get_tile k))))"
                 "(TKA:Put \"TIP\" (car (nth (atoi (get_tile \"TIP\")) *TKA:TIPURI*)))"
                 "(TKA:Put \"COMUNICARE\" (car (nth (atoi (get_tile \"COMUNICARE\")) *TKA:COMUNIC*)))"
                 "(TKA:Put \"POZ_INCERTA\" (get_tile \"POZ_INCERTA\")) (done_dialog 1)")))))

;; TKA:ExecDialog - datele persoanei autorizate
(defun TKA:ExecDialog ()
  (TKA:Dialog "tka_exec"
    '(progn
       (foreach k *TKA:F_EXEC* (set_tile k (TKA:EGet k)))
       (action_tile "accept" "(foreach k *TKA:F_EXEC* (TKA:EPut k (TKA:Trim (get_tile k)))) (done_dialog 1)"))))

;; Opțiunile planurilor: formatele și scările din listele derulante
(setq *TKA:FMTLIST* '(("AUTO" . "Automat (cel mai mic format)") ("A4P" . "A4 portrait") ("A3P" . "A3 portrait")
                      ("A3L" . "A3 landscape") ("A2L" . "A2 landscape") ("A1L" . "A1 landscape")
                      ("A0L" . "A0 landscape") ("A4L" . "A4 landscape") ("A2P" . "A2 portrait")))

;; TKA:OptDialog - formatul, scara, numerotarea și etichetele planurilor
(defun TKA:OptDialog ()
  (TKA:Dialog "tka_opt"
    '(progn
       (TKA:FillList "pl_format" (mapcar 'cdr *TKA:FMTLIST*))
       (set_tile "pl_format" (itoa (max 0 (TKA:Index *TKA:FORMAT* (mapcar 'car *TKA:FMTLIST*)))))
       (TKA:FillList "pl_scara" (cons "Automat" (mapcar '(lambda (s) (strcat "1:" (itoa s))) *TKA:SCALES*)))
       (set_tile "pl_scara" (itoa (1+ (TKA:Index *TKA:SCARA* *TKA:SCALES*))))
       (set_tile "eb_start" (itoa *TKA:NRSTART*))
       (set_tile "rc_mod" (if (= *TKA:NRMOD* "NV") "rb_nv" "rb_pol"))
       (set_tile "rr_sep" (if (= *TKA:SEPDEC* ",") "rb_virg" "rb_punct"))
       (set_tile "tg_inv" *TKA:INVPAD*)
       (set_tile "eb_a16" *TKA:ANEXA16*)
       (set_tile "eb_a17" *TKA:ANEXA17*)
       (action_tile "accept"
         (strcat "(setq *TKA:FORMAT* (car (nth (atoi (get_tile \"pl_format\")) *TKA:FMTLIST*))"
                 " *TKA:SCARA* (if (= (get_tile \"pl_scara\") \"0\") 0 (nth (1- (atoi (get_tile \"pl_scara\"))) *TKA:SCALES*))"
                 " *TKA:NRSTART* (max 1 (atoi (get_tile \"eb_start\")))"
                 " *TKA:NRMOD* (if (= (get_tile \"rc_mod\") \"rb_nv\") \"NV\" \"POL\")"
                 " *TKA:SEPDEC* (if (= (get_tile \"rr_sep\") \"rb_virg\") \",\" \".\")"
                 " *TKA:INVPAD* (get_tile \"tg_inv\")"
                 " *TKA:ANEXA16* (get_tile \"eb_a16\") *TKA:ANEXA17* (get_tile \"eb_a17\"))"
                 " (done_dialog 1)")))))

;; TKA:ConstrDialog - datele construcției E (destinație, regim, an, Sd...)
(defun TKA:ConstrDialog (e cod / )
  (setq *TKA:CE* e *TKA:CCOD* cod)
  (= 1 (TKA:Dialog "tka_constr"
         '(progn
            (set_tile "tx_info" (strcat "Suprafata construita la sol masurata: Sc = "
                                        (itoa (TKA:Int (TKA:Area *TKA:CE*))) " mp"))
            (set_tile "COD" (cond ((TKA:LGet *TKA:CE* "COD")) (*TKA:CCOD*)))
            (TKA:FillList "DEST" (mapcar '(lambda (d) (strcat (car d) " - " (cdr d))) *TKA:DEST*))
            (set_tile "DEST" (itoa (max 0 (TKA:Index (cond ((TKA:LGet *TKA:CE* "DEST")) ("CL")) (mapcar 'car *TKA:DEST*)))))
            (foreach k '("DENUMIRE" "REGIM" "AN" "SD" "NRUI" "MENT") (set_tile k (cond ((TKA:LGet *TKA:CE* k)) (""))))
            (action_tile "accept"
              (strcat "(foreach k '(\"COD\" \"DENUMIRE\" \"REGIM\" \"AN\" \"SD\" \"NRUI\" \"MENT\") (TKA:LPut *TKA:CE* k (TKA:Trim (get_tile k))))"
                      "(TKA:LPut *TKA:CE* \"DEST\" (car (nth (atoi (get_tile \"DEST\")) *TKA:DEST*))) (done_dialog 1)"))))))

;; TKA:EnsureConstr - cere datele construcțiilor care nu au fost completate
(defun TKA:EnsureConstr (lst / i)
  (setq i 0)
  (foreach e lst
    (setq i (1+ i))
    (if (null (TKA:LGet e "DEST"))
      (if (not (TKA:ConstrDialog e (strcat "C" (itoa i))))
        (progn (TKA:LPut e "COD" (strcat "C" (itoa i))) (TKA:LPut e "DEST" "CL"))))))

;;; ==========================================================================
;;;  LATURI ȘI VECINĂTĂȚI
;;; ==========================================================================

;; Materializările uzuale ale limitelor
(setq *TKA:MAT* '("" "gard de plas`a" "gard de lemn" "gard de beton" "gard de metal" "gard de zid`arie"
                  "zid construc`tie" "born`a" "`tarus" "nematerializat"))

;; TKA:IsNumber - T dacă textul conține doar cifre și separatori (cote, nr. puncte)
(defun TKA:IsNumber (s)
  (vl-every '(lambda (c) (or (<= 48 c 57) (member c '(32 44 45 46 109 77)))) (vl-string->list s)))

;; TKA:Texts - textele din model space (poziție, conținut), în afara straturilor PAD_*
(defun TKA:Texts (/ ss i e ed s p out)
  (if (setq ss (ssget "_X" '((0 . "TEXT,MTEXT") (410 . "Model"))))
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq e (ssname ss i) i (1+ i) ed (entget e))
        (if (not (wcmatch (strcase (cdr (assoc 8 ed))) "PAD_*"))
          (progn
            (if (= (cdr (assoc 0 ed)) "MTEXT")
              (setq s (TKA:MtextPlain (strcat (apply 'strcat (mapcar 'cdr (vl-remove-if-not '(lambda (g) (= (car g) 3)) ed)))
                                              (cdr (assoc 1 ed))))
                    p (cdr (assoc 10 ed)))
              (setq s (TKA:Decode (cdr (assoc 1 ed)))
                    p (if (and (or (/= 0 (cond ((cdr (assoc 72 ed))) (0))) (/= 0 (cond ((cdr (assoc 73 ed))) (0))))
                               (assoc 11 ed))
                        (cdr (assoc 11 ed)) (cdr (assoc 10 ed)))))
            (setq s (TKA:Trim s))
            (if (and (/= s "") (not (TKA:IsNumber s)))
              (setq out (cons (list (TK:2d p) s) out))))))))
  out)

;; TKA:AutoSides - propune vecinii laturilor fără date: textul cel mai
;; apropiat din exteriorul fiecărei laturi (de ex. "nr. cad. 1234", "str. X")
(defun TKA:AutoSides (pts data / texts out i a b l n w best bs u d sc)
  (setq texts (vl-remove-if '(lambda (t1) (TKA:Inside (car t1) pts)) (TKA:Texts)) i 0)
  (mapcar
    '(lambda (a b)
       (setq best nil bs 1e99 l (distance a b) n (TKA:OutNormal a b) w (max 2.0 (min 25.0 (* 0.6 l))))
       (if (and (> l 0.01) (= (car (nth i data)) ""))
         (foreach t1 texts
           (setq u (/ (TK:Dot (TK:v- (car t1) a) (TK:v- b a)) (* l l))
                 d (TK:Dot (TK:v- (car t1) a) n))
           (if (and (> u 0.0) (< u 1.0) (> d 0.0) (< d w))
             (progn
               (setq sc (+ d (* 0.3 l (abs (- u 0.5)))))
               (if (< sc bs) (setq bs sc best (cadr t1)))))))
       (setq out (cons (if best (TK:SetNth (nth i data) 0 best) (nth i data)) out) i (1+ i)))
    pts (append (cdr pts) (list (car pts))))
  (reverse out))

;; TKA:SideItems - rândurile listei de laturi din dialog
(defun TKA:SideItems (/ i)
  (setq i -1)
  (mapcar '(lambda (s d)
             (setq i (1+ i))
             (TKA:Ascii (strcat (itoa (nth 1 s)) "-" (itoa (nth 2 s)) "\t" (TKA:Num (nth 5 s) 2) " m\t"
                                (car d) "\t" (cadr d) "\t" (caddr d))))
          (TKA:R1 *TKA:SREC* "SIDES") *TKA:SD*))

;; TKA:SidesSel - indicii laturilor selectate în listă
(defun TKA:SidesSel (/ v)
  (setq v (get_tile "lb_lat"))
  (if (/= v "") (read (strcat "(" v ")"))))

;; Câmpurile datelor unei laturi, în ordinea din *TKA:SD*
(setq *TKA:SFIELDS* '("eb_id" "eb_vecin" "eb_mat" "eb_obs"))

;; TKA:SidesDirty - marchează câmpul K (0..3) ca modificat de utilizator
(defun TKA:SidesDirty (k)
  (if (not (member k *TKA:SDIRTY*)) (setq *TKA:SDIRTY* (cons k *TKA:SDIRTY*))))

;; TKA:SidesApply - aplică laturilor selectate câmpurile modificate de la
;; ultima selecție (cu o singură latură selectată: toate câmpurile), astfel
;; încât de ex. materializarea se poate da mai multor laturi fără a le
;; suprascrie vecinii
(defun TKA:SidesApply (/ sel idx)
  (setq sel (TKA:SidesSel)
        idx (cond (*TKA:SDIRTY*) ((= (length sel) 1) '(0 1 2 3))))
  (cond
    ((null sel) (set_tile "error" "Selectati mai intai laturile din lista."))
    ((null idx) (set_tile "error" "Modificati campurile care se aplica laturilor selectate."))
    (T
     (foreach i sel
       (foreach k idx
         (setq *TKA:SD* (TK:SetNth *TKA:SD* i (TK:SetNth (nth i *TKA:SD*) k (TKA:Trim (get_tile (nth k *TKA:SFIELDS*))))))))
     (TKA:FillList "lb_lat" (TKA:SideItems))
     (set_tile "lb_lat" (TKA:Join (mapcar 'itoa sel) " "))
     (set_tile "error" ""))))

;; TKA:SidesShow - afișează în câmpuri datele primei laturi selectate
(defun TKA:SidesShow (/ sel d)
  (setq *TKA:SDIRTY* nil)
  (if (setq sel (TKA:SidesSel))
    (progn
      (setq d (nth (car sel) *TKA:SD*))
      (mapcar 'set_tile *TKA:SFIELDS* d))))

;; TKA:SidesDialog - editarea vecinilor imobilului REC; salvează pe entitate
(defun TKA:SidesDialog (rec / res)
  (setq *TKA:SREC* rec *TKA:SDIRTY* nil
        *TKA:SD* (mapcar '(lambda (s) (list (nth 6 s) (nth 7 s) (nth 8 s) (nth 9 s))) (TKA:R1 rec "SIDES")))
  (setq res
    (TKA:Dialog "tka_laturi"
      '(progn
         (TKA:FillList "lb_lat" (TKA:SideItems))
         (TKA:FillList "pl_mat" *TKA:MAT*)
         (action_tile "lb_lat" "(TKA:SidesShow)")
         (foreach k *TKA:SFIELDS*
           (action_tile k (strcat "(TKA:SidesDirty " (itoa (TKA:Index k *TKA:SFIELDS*)) ")")))
         (action_tile "pl_mat" "(set_tile \"eb_mat\" (TKA:Real (nth (atoi $value) *TKA:MAT*))) (TKA:SidesDirty 2)")
         (action_tile "bt_aplica" "(TKA:SidesApply)")
         (action_tile "bt_auto" "(setq *TKA:SD* (TKA:AutoSides (TKA:R1 *TKA:SREC* \"PTS\") *TKA:SD*)) (TKA:FillList \"lb_lat\" (TKA:SideItems))")
         (action_tile "bt_sterge" "(foreach i (TKA:SidesSel) (setq *TKA:SD* (TK:SetNth *TKA:SD* i (list \"\" \"\" \"\" \"\")))) (TKA:FillList \"lb_lat\" (TKA:SideItems))")
         (action_tile "accept" "(done_dialog 1)"))))
  (if (= res 1)
    (progn
      (mapcar '(lambda (s d) (TKA:SetSideData (TKA:R1 rec "E") (nth 3 s) (nth 4 s) d))
              (TKA:R1 rec "SIDES") *TKA:SD*)
      T)))

;;; ==========================================================================
;;;  SELECȚII ȘI MEMORAREA LUCRĂRII
;;; ==========================================================================

;; TKA:SelPoly - o polilinie închisă (nil la Enter)
(defun TKA:SelPoly (msg / es ok e)
  (TKA:ToModel)
  (while (not ok)
    (setvar "ERRNO" 0)
    (setq es (entsel msg))
    (cond
      ((and (null es) (= 7 (getvar "ERRNO"))) (princ "\nNimic selectat."))
      ((null es) (setq ok T))
      ((or (not (wcmatch (cdr (assoc 0 (entget (car es)))) "LWPOLYLINE,POLYLINE"))
           (/= 0 (logand 80 (cond ((cdr (assoc 70 (entget (car es))))) (0)))))
       (princ "\nObiectul nu este o polilinie."))
      ((not (TK:IsClosed (car es))) (princ "\nPolilinia nu este inchisa."))
      (T (setq ok T e (car es)))))
  e)

;; TKA:SelPolys - mai multe polilinii închise (Enter = niciuna)
(defun TKA:SelPolys (msg / ss i e out)
  (TKA:ToModel)
  (princ msg)
  ;; poliliniile 2D/3D (fără plase: flag 16 = plasă 3D, 64 = polifață)
  (if (setq ss (ssget '((0 . "LWPOLYLINE,POLYLINE") (-4 . "<NOT") (-4 . "&") (70 . 80) (-4 . "NOT>"))))
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq e (ssname ss i) i (1+ i))
        (if (TK:IsClosed e) (setq out (cons e out))))))
  (reverse out))

;; TKA:SelSeries - polilinii selectate pe rând (lotul 1, lotul 2, ...)
(defun TKA:SelSeries (what / e out i)
  (setq i 1)
  (while (setq e (TKA:SelPoly (strcat "\nSelectati " what " " (itoa i) " <Enter = gata>: ")))
    (if (member e out) (princ "\nDeja selectat.") (setq out (cons e out) i (1+ i))))
  (reverse out))

;; TKA:SaveSel / TKA:LoadSel - memorarea selecțiilor în desen (handle-uri)
(defun TKA:SaveSel (k ents) (TKA:Put k (TKA:Join (mapcar 'TKA:Handle ents) ",")))
(defun TKA:LoadSel (k / v) (setq v (TKA:Get k))
  (if (/= v "") (vl-remove nil (mapcar 'TKA:FromHandle (TKA:Split v ",")))))

;; TKA:Categ - categoria unei parcele: din date, din textul din interior sau implicită
(defun TKA:Categ (e / c pts)
  (cond
    ((setq c (TKA:LGet e "CATEG")) c)
    (T
     (setq pts (TKA:PolyPts e))
     (foreach t1 (TKA:Texts)
       (if (and (null c) (TKA:Inside (car t1) pts) (assoc (strcase (cadr t1)) *TKA:CATEG*))
         (setq c (strcase (cadr t1)))))
     (TKA:LPut e "CATEG" (cond (c) ((/= (TKA:Get "CATEG") "") (TKA:Get "CATEG")) ("CC"))))))

;; TKA:Prep - pregătirea comenzilor: model space, straturi, stiluri
(defun TKA:Prep ()
  (TKA:ToModel)
  (setvar "OSMODE" 0)          ; punctele date comenzilor MVIEW/ZOOM nu se agață (restabilit de TK:Stop)
  (TKA:Layers)
  (TKA:Styles))

;; TKA:ToModel - activează model space (selecțiile se fac în model, chiar dacă
;; un plan generat anterior a lăsat curent un layout)
(defun TKA:ToModel ()
  (if (/= (strcase (getvar "CTAB")) "MODEL") (setvar "CTAB" "Model")))

;; TKA:Within - entitățile din lista ENTS al căror centroid este în poligonul PTS
(defun TKA:Within (ents pts)
  (vl-remove-if-not '(lambda (e) (TKA:Inside (TKA:Centroid (TKA:PolyPts e)) pts)) ents))

;; TKA:Tag - eticheta lucrării pentru numele layout-urilor
(defun TKA:Tag () (TK:SafeName (if (/= (TKA:Get "NRCAD") "") (TKA:Get "NRCAD") "imobil")))

;;; ==========================================================================
;;;  GENERATOARELE (folosite de comenzi și de meniul ANEXE)
;;; ==========================================================================

;; TKA:DoPad16 - Anexa 16 pentru un imobil; REUSE = folosește selecția memorată
(defun TKA:DoPad16 (reuse / e constr parc rec)
  (if (and reuse (setq e (car (TKA:LoadSel "H_IMOBIL"))))
    (setq constr (TKA:LoadSel "H_CONSTR") parc (TKA:LoadSel "H_PARC"))
    (if (setq e (TKA:SelPoly "\nSelectati conturul imobilului (polilinie inchisa): "))
      (progn
        (setq constr (TKA:SelPolys "\nSelectati constructiile (Enter = fara constructii): "))
        (setq parc (TKA:SelPolys "\nSelectati parcelele de folosinta (Enter = o singura categorie): "))
        (TKA:SaveSel "H_IMOBIL" (list e)) (TKA:SaveSel "H_CONSTR" constr) (TKA:SaveSel "H_PARC" parc))))
  (if e
    (progn
      (TKA:EnsureConstr constr)
      (foreach p parc (TKA:Categ p))
      (setq rec (TKA:Imobil e parc constr nil nil))
      (if (TKA:SidesDialog rec) (setq rec (TKA:Imobil e parc constr nil nil)))
      (TKA:Pad16 rec "" (TKA:Get "NRCAD") (TKA:Get "NRCF") (strcat "PAD_" (TKA:Tag)))
      rec)))

;; TKA:LotSides - vecinii laturilor unui lot: vecinul imobilului inițial
;; (latura exterioară) sau lotul alăturat (latura interioară)
(defun TKA:LotSides (lot parent lots idx / ppts psides j k lab)
  (setq ppts (TKA:R1 parent "PTS") psides (TKA:R1 parent "SIDES"))
  (mapcar
    '(lambda (s)
       (cond
         ((setq k (TKA:SideOnRing (nth 3 s) (nth 4 s) ppts))
          (append (TKA:Firstn 6 s) (TKA:Nthcdr 6 (nth k psides))))
         (T
          (setq j 0 lab "")
          (foreach o lots
            (setq j (1+ j))
            (if (and (/= j idx) (= lab "") (TKA:SideOnRing (nth 3 s) (nth 4 s) (TKA:R1 o "PTS")))
              (setq lab (strcat "Lot " (itoa j)))))
          (append (TKA:Firstn 6 s) (list lab "" "" "")))))
    (TKA:R1 lot "SIDES")))

;; TKA:SetR1 - înlocuiește valoarea cheii K în înregistrarea REC
(defun TKA:SetR1 (rec k v) (subst (cons k v) (assoc k rec) rec))

;; TKA:DoPadDez - Anexa 17 (dezlipire) + Anexa 16 pentru fiecare lot
(defun TKA:DoPadDez (reuse / e lots constr parc tab parent lrecs areas i lr *TKA:SPLIT*)
  (if (and reuse (setq e (car (TKA:LoadSel "H_IMOBIL"))) (setq lots (TKA:LoadSel "H_LOTURI")))
    (setq constr (TKA:LoadSel "H_CONSTR") parc (TKA:LoadSel "H_PARC"))
    (if (setq e (TKA:SelPoly "\nSelectati conturul imobilului care se dezlipeste: "))
      (progn
        (setq lots (TKA:SelSeries "lotul"))
        (setq constr (TKA:SelPolys "\nSelectati constructiile (Enter = fara constructii): "))
        (setq parc (TKA:SelPolys "\nSelectati parcelele de folosinta (Enter = o singura categorie): "))
        (TKA:SaveSel "H_IMOBIL" (list e)) (TKA:SaveSel "H_LOTURI" lots)
        (TKA:SaveSel "H_CONSTR" constr) (TKA:SaveSel "H_PARC" parc))))
  (cond
    ((null e) nil)
    ((< (length lots) 2) (princ "\nDezlipirea necesita cel putin doua loturi.") nil)
    (T
     (TKA:EnsureConstr constr)
     (foreach p parc (TKA:Categ p))
     ;; numerotarea comună: imobilul, apoi punctele noi ale loturilor
     (setq *TKA:SPLIT* (apply 'append (mapcar 'TKA:PolyPts (cons e lots)))
           tab (TKA:Numbering (mapcar 'TKA:Ring2 (cons e lots)) *TKA:NRSTART*))
     (setq parent (TKA:Imobil e parc constr tab nil))
     (if (TKA:SidesDialog parent) (setq parent (TKA:Imobil e parc constr tab nil)))
     ;; suprafețele loturilor rotunjite cu suma egală cu a imobilului
     (setq areas (TKA:LargestRemainder (mapcar 'TKA:Area lots) (TKA:R1 parent "AREA")))
     (setq i 0)
     (foreach l lots
       (setq lrecs (cons (TKA:Imobil l (TKA:Within parc (TKA:PolyPts l)) (TKA:Within constr (TKA:PolyPts l))
                                     tab (nth i areas))
                         lrecs)
             i (1+ i)))
     (setq lrecs (reverse lrecs) i 0)
     (setq lrecs (mapcar '(lambda (r) (setq i (1+ i))
                            (TKA:SetR1 (append r (list (cons "NRCAD" (cond ((TKA:LGet (TKA:R1 r "E") "NRCAD")) ("")))
                                                 (cons "LOT" i)))
                                       "SIDES"
                                       (TKA:LotSides r parent lrecs i)))
                         lrecs))
     (TKA:Pad17 parent lrecs "DEZ" (strcat "PAD_dezlipire_" (TKA:Tag)))
     (setq i 0)
     (foreach r lrecs
       (setq i (1+ i))
       (TKA:Pad16 r (strcat " - lot " (itoa i)) (TKA:R1 r "NRCAD") "" (strcat "PAD_lot" (itoa i) "_" (TKA:Tag))))
     (setq *TKA:LOTURI* lrecs)
     parent)))

;; TKA:DoPadAlip - Anexa 17 (alipire) + Anexa 16 pentru imobilul rezultat
(defun TKA:DoPadAlip (reuse / ini rez constr tab irecs res i nr *TKA:SPLIT*)
  (if (and reuse (setq ini (TKA:LoadSel "H_INITIALE")) (setq rez (car (TKA:LoadSel "H_IMOBIL"))))
    (setq constr (TKA:LoadSel "H_CONSTR"))
    (progn
      (setq ini (TKA:SelSeries "imobilul initial"))
      (setq i 0)
      (foreach e ini
        (setq i (1+ i) nr (getstring T (strcat "\nNumarul cadastral al imobilului " (itoa i) " <"
                                               (cond ((TKA:LGet e "NRCAD")) ("")) ">: ")))
        (if (/= nr "") (TKA:LPut e "NRCAD" nr)))
      (setq rez (TKA:SelPoly "\nSelectati conturul imobilului rezultat din alipire: "))
      (setq constr (TKA:SelPolys "\nSelectati constructiile (Enter = fara constructii): "))
      (TKA:SaveSel "H_INITIALE" ini) (TKA:SaveSel "H_IMOBIL" (list rez)) (TKA:SaveSel "H_CONSTR" constr)))
  (cond
    ((or (null rez) (< (length ini) 2)) (princ "\nAlipirea necesita cel putin doua imobile initiale si imobilul rezultat.") nil)
    (T
     (TKA:EnsureConstr constr)
     (setq *TKA:SPLIT* (apply 'append (mapcar 'TKA:PolyPts (cons rez ini)))
           tab (TKA:Numbering (mapcar 'TKA:Ring2 (cons rez ini)) *TKA:NRSTART*))
     (setq res (TKA:Imobil rez nil constr tab nil))
     (if (TKA:SidesDialog res) (setq res (TKA:Imobil rez nil constr tab nil)))
     (setq irecs (mapcar '(lambda (e) (append (TKA:Imobil e nil nil tab nil)
                                             (list (cons "NRCAD" (cond ((TKA:LGet e "NRCAD")) (""))))))
                         ini))
     (TKA:Pad17 res irecs "ALIP" (strcat "PAD_alipire_" (TKA:Tag)))
     (TKA:Pad16 res " - imobil rezultat" "" "" (strcat "PAD_rezultat_" (TKA:Tag)))
     res)))

;; TKA:CurrentRec - imobilul pentru anexele Word (selecția memorată sau nouă)
(defun TKA:CurrentRec (/ e)
  (if (not (setq e (car (TKA:LoadSel "H_IMOBIL"))))
    (if (setq e (TKA:SelPoly "\nSelectati conturul imobilului (Enter = anexe fara date masurate): "))
      (TKA:SaveSel "H_IMOBIL" (list e))))
  (if e (TKA:Imobil e (TKA:LoadSel "H_PARC") (TKA:LoadSel "H_CONSTR") nil nil)))

;;; ==========================================================================
;;;  COMENZILE
;;; ==========================================================================

;; TKA:Run - execută FN cu gestionarea erorilor și a variabilelor de sistem
(defun TKA:Run (fn / *error* r)
  (defun *error* (msg) (TK:Error msg))
  (TK:Start)
  (TKA:Prep)
  (setq r (eval fn))
  (TK:Stop)
  r)

(defun c:PAD () (TKA:Run '(TKA:DoPad16 nil)) (princ))
(defun c:PADDEZ () (TKA:Run '(TKA:DoPadDez nil)) (princ))
(defun c:PADALIP () (TKA:Run '(TKA:DoPadAlip nil)) (princ))
(defun c:DATEIMOBIL () (TKA:ImobilDialog) (princ))
(defun c:EXECUTANT () (TKA:ExecDialog) (princ))

;; C:VECINI - editarea vecinilor imobilului selectat
(defun c:VECINI (/ e)
  (TKA:Run '(progn
              (if (setq e (TKA:SelPoly "\nSelectati conturul imobilului: "))
                (TKA:SidesDialog (TKA:Imobil e nil nil nil nil)))))
  (princ))

;; C:CONSTRUCTIE - datele construcțiilor selectate
(defun c:CONSTRUCTIE (/ lst)
  (setq lst (TKA:SelPolys "\nSelectati constructiile: "))
  (foreach e lst (TKA:ConstrDialog e (cond ((TKA:LGet e "COD")) ("C1"))))
  (princ))

;; C:ANEXEWORD - completează anexele Word (cerere, declarație, memoriu,
;; PV de vecinătate, inventar) pentru imobilul memorat sau selectat
(defun c:ANEXEWORD ()
  (TKA:Run '(TKA:MakeWord '(13 14 15 20 0) (TKA:CurrentRec) ""))
  (princ))


;;; ==========================================================================
;;;  RELEVEUL (ANEXA 18) ȘI FOAIA COLECTIVĂ (ANEXA 19)
;;; ==========================================================================
;;;  Încăperile sunt polilinii închise; denumirea = textul din interiorul
;;;  încăperii. Unitățile individuale (UI) sunt contururi închise care conțin
;;;  încăperile; denumirea UI = textul din interiorul conturului, în afara
;;;  încăperilor. Balcoanele, terasele, logiile etc. nu intră în suprafața utilă.
;;; ==========================================================================

;; Cuvintele care marchează încăperile excluse din suprafața utilă
(setq *TKA:NEUTIL* '("BALCON" "TERAS" "LOGI" "LOJI" "COPERTIN" "CASA SCARII" "CASA SC`ARII" "POD" "PRISPA"))

;; TKA:Upper - text cu majuscule, fără diacritice (pentru comparații)
(defun TKA:Upper (s / l)
  (setq s (strcase (TKA:Ascii s)))
  (foreach p '(("\\U+0103" . "A") ("\\U+0102" . "A") ("\\U+00E2" . "A") ("\\U+00C2" . "A") ("\\U+00EE" . "I")
               ("\\U+00CE" . "I") ("\\U+0219" . "S") ("\\U+0218" . "S") ("\\U+021B" . "T") ("\\U+021A" . "T")
               ("\\U+015F" . "S") ("\\U+015E" . "S") ("\\U+0163" . "T") ("\\U+0162" . "T"))
    (setq s (TK:StrReplace s (car p) (cdr p))))
  s)

;; TKA:Util? - T dacă încăperea cu denumirea N intră în suprafața utilă
(defun TKA:Util? (n / u)
  (setq u (TKA:Upper n))
  (not (vl-some '(lambda (k) (vl-string-search (TKA:Upper k) u)) *TKA:NEUTIL*)))

;; TKA:TextIn - primul text (nenumeric) din interiorul poligonului PTS,
;; care nu se află în niciunul dintre poligoanele EXCL
(defun TKA:TextIn (pts excl texts) (cadr (TKA:TextAt pts excl texts)))

;; TKA:TextAt - ca TKA:TextIn, dar returnează (punct text)
(defun TKA:TextAt (pts excl texts / r)
  (foreach t1 texts
    (if (and (null r) (TKA:Inside (car t1) pts)
             (not (vl-some '(lambda (x) (TKA:Inside (car t1) x)) excl)))
      (setq r t1)))
  r)

;; TKA:Rooms - încăperile grupate pe UI (UIS = contururile UI sau nil, caz în
;; care toate încăperile formează unitatea UINAME):
;; ((numeUI ((nr nume supr util? puncte poziția-denumirii) ...)) ...)
(defun TKA:Rooms (rooms uis uiname / texts rpts upts groups i nr lst tr)
  (setq texts (TKA:Texts)
        rpts (mapcar 'TKA:PolyPts rooms)
        upts (mapcar 'TKA:PolyPts uis))
  (if (null upts)
    (setq groups (list (list uiname rpts)))
    (progn
      (setq i 0)
      (foreach u upts
        (setq i (1+ i)
              groups (cons (list (cond ((TKA:TextIn u rpts texts)) ((strcat "UI " (itoa i))))
                                 (vl-remove-if-not '(lambda (r) (TKA:Inside (TKA:Centroid r) u)) rpts))
                           groups)))
      (setq groups (reverse groups))))
  (mapcar
    '(lambda (g)
       (setq nr 0 lst nil)
       (foreach r (cadr g)
         (setq tr (TKA:TextAt r nil texts)
               lst (cons (list (cond ((cadr tr)) ("^Inc`apere"))
                               (/ (TKA:Int (* 10.0 (abs (TKA:SArea r)))) 10.0) r (car tr))
                         lst)))
       ;; încăperile utile primele, apoi celelalte; numerotare în această ordine
       (setq lst (append (vl-remove-if-not '(lambda (x) (TKA:Util? (car x))) (reverse lst))
                         (vl-remove-if '(lambda (x) (TKA:Util? (car x))) (reverse lst))))
       (list (car g) (mapcar '(lambda (x) (setq nr (1+ nr))
                                (list nr (car x) (cadr x) (TKA:Util? (car x)) (caddr x) (cadddr x)))
                             lst)))
    groups))

;; TKA:RoomTable - tabelul încăperilor (colțul stânga-sus X,Y); returnează y-ul de jos
(defun TKA:RoomTable (x y groups / w h th su st ytop n)
  (setq w '(24.0 16.0 52.0 22.0) h 4.2 th 1.8)
  (setq y (TKA:Row x y 5.0 w '("Nr. apartament" "Nr. ^inc`apere" "Denumire ^inc`apere" "Suprafa`ta (m.p.)") th))
  (foreach g groups
    (setq ytop y su 0.0 st 0.0 n 0)
    (foreach r (cadr g)
      (if (and (not (nth 3 r)) (= su st) (> n 0))
        (setq y (TKA:Row (+ x 24.0) y h '(16.0 52.0 22.0) (list "" "Suprafa`ta util`a" (rtos su 2 1)) th)))
      (setq y (TKA:Row (+ x 24.0) y h '(16.0 52.0 22.0) (list (itoa (car r)) (cadr r) (rtos (caddr r) 2 1)) th)
            st (+ st (caddr r)) n (1+ n))
      (if (nth 3 r) (setq su (+ su (caddr r)))))
    (if (= su st)
      (setq y (TKA:Row (+ x 24.0) y h '(16.0 52.0 22.0) (list "" "Suprafa`ta util`a" (rtos su 2 1)) th)))
    (setq y (TKA:Row (+ x 24.0) y h '(16.0 52.0 22.0) (list "" "Suprafa`ta total`a" (rtos st 2 1)) th))
    (TKA:Cell x y (+ x 24.0) ytop (car g) th))
  y)

;; TKA:DoReleveu - Anexa 18: layout cu releveul unui nivel (antet, tabelul
;; încăperilor, numerele încăperilor) și memorarea UI pentru foaia colectivă
(defun TKA:DoReleveu (/ rooms uis uiname nivel groups pts bb sh sc vp x y lst old)
  (setq rooms (TKA:SelPolys "\nSelectati incaperile nivelului (polilinii inchise): "))
  (if rooms
    (progn
      (setq uis (TKA:SelPolys "\nSelectati contururile unitatilor individuale (Enter = o singura UI): "))
      (if (null uis)
        (progn
          (setq uiname (getstring T "\nDenumirea unitatii individuale <Apartament 1>: "))
          (if (= uiname "") (setq uiname "Apartament 1"))))
      (setq nivel (getstring T "\nDenumirea nivelului <parter>: "))
      (if (= nivel "") (setq nivel "parter"))
      (setq groups (TKA:Rooms rooms uis uiname))
      (foreach r rooms (setq pts (append (TKA:PolyPts r) pts)))
      (setq bb (TKA:Bbox pts))
      ;; formatul: A3/A2/A1 orizontal, scara 1:50/1:100/1:200
      (foreach c '("A3L" "A2L" "A1L")
        (if (null sc)
          (progn
            (setq sh (TKA:Sheet c 0.0)
                  sh (subst (cons "VP" (list (+ (TKA:SG sh "X1") 2.0) (+ (TKA:SG sh "Y1") 2.0)
                                             (- (TKA:SG sh "X2") 125.0) (- (TKA:SG sh "Y2") 60.0)))
                            (assoc "VP" sh) sh))
            (foreach s '(50 100 200)
              (if (and (null sc) (TKA:FitScale sh bb s)) (setq sc s))))))
      (if (null sc) (setq sc 200))
      (TKA:NewLayout (strcat "RELEVEU_" (TK:SafeName nivel)) sh)
      (setq vp (TKA:SG sh "VP"))
      (TKA:Viewport vp (list (/ (+ (car bb) (caddr bb)) 2.0) (/ (+ (cadr bb) (cadddr bb)) 2.0)) sc)
      (TKA:Box (TKA:SG sh "X1") (TKA:SG sh "Y1") (TKA:SG sh "X2") (TKA:SG sh "Y2") "PAD_CADRU")
      (TKA:T (strcat "%%u" "Anexa nr. 18") (- (TKA:SG sh "X2") 3.0) (- (TKA:SG sh "Y2") 4.5) 2.5 0.0 "R" "PAD_TEXT" "TKA_ARIALI")
      (TKA:T (strcat (TKA:SG sh "FMT") "-" (itoa sc)) (- (TKA:SG sh "W") 2.0) 1.2 1.6 0.0 "R" "PAD_TEXT" nil)
      ;; titlul și antetul
      (setq x (+ (TKA:SG sh "X1") 10.0) y (- (TKA:SG sh "Y2") 10.0))
      (TKA:T (strcat "Releveu " nivel) (+ x 80.0) y 6.0 0.0 "C" "PAD_TEXT" "TKA_ARIALB")
      (TKA:T (strcat "Scara 1:" (itoa sc)) (+ x 80.0) (- y 6.5) 3.0 0.0 "C" "PAD_TEXT" nil)
      (setq y (- y 10.0))
      (setq y (TKA:Row x y 5.5 '(70.0 90.0) '("Num`ar cadastral" "Adresa imobilului") 2.1))
      (setq y (TKA:Row x y 5.5 '(70.0 90.0) (list (TKA:Get "NRCAD") (TKA:Adresa)) 2.1))
      (setq y (TKA:Row x y 5.5 '(48.0 22.0 25.0 65.0) (list "Carte Funciar`a colectiv`a nr." (TKA:Get "NRCF_COLECTIVA") "UAT" (TKA:Get "UAT")) 2.1))
      (TKA:Row x y 5.5 '(48.0 22.0 25.0 65.0) '("Cod unitate individual`a (U)" "" "CF individual`a" "") 2.1)
      ;; tabelul încăperilor și semnăturile
      (setq x (- (TKA:SG sh "X2") 119.0) y (- (TKA:SG sh "Y2") 30.0))
      (setq y (TKA:RoomTable x y groups))
      (setq y (TKA:Row x (- y 4.0) 5.0 '(80.0 34.0) '("Executant," "Data") 1.8))
      (setq y (TKA:Row x y 9.0 '(80.0 34.0)
                       (list (TKA:Join (list (TKA:ExecNume) (if (/= (TKA:ExecAut) "") (strcat "Aut. " (TKA:ExecAut)))) "\\P")
                             (TK:Today))
                       1.8))
      (setq y (TKA:Row x y 5.0 '(80.0 34.0) '("Recep`tionat," "Data") 1.8))
      (TKA:Row x y 9.0 '(80.0 34.0) '("" "") 1.8)
      ;; numerele încăperilor (în cerc) pe plan, sub denumirea încăperii
      (foreach g groups
        (foreach r (cadr g)
          (setq pts (if (nth 5 r) (TK:v- (TKA:M2P (nth 5 r)) '(0.0 3.6)) (TKA:M2P (TKA:LabelPoint (nth 4 r)))))
          (TKA:Circle (car pts) (cadr pts) 1.6 "PAD_TEXT")
          (TKA:T (itoa (car r)) (car pts) (cadr pts) 1.8 0.0 "MC" "PAD_TEXT" nil)))
      ;; memorarea UI ale nivelului (pentru foaia colectivă)
      (setq old (vl-remove-if '(lambda (u) (= (car u) nivel)) (vlax-ldata-get *TKA:DICT* "UI")))
      (foreach g groups
        (setq lst (cons (list nivel (car g)
                              (apply '+ (mapcar '(lambda (r) (if (nth 3 r) (caddr r) 0.0)) (cadr g)))
                              (TKA:RoomsText (cadr g)))
                        lst)))
      (vlax-ldata-put *TKA:DICT* "UI" (append old (reverse lst)))
      (TKA:Msg (strcat "Releveu generat ^in layout-ul \"" *TKA:LAY* "\" (" (itoa (length groups)) " UI)."))
      groups)))

;; TKA:RoomsText - descrierea unei UI din denumirile încăperilor
;; ("Living, Dormitor, Baie (2) și Balcon"), pentru coloana Observații
(defun TKA:RoomsText (rooms / names p out)
  (foreach r rooms
    (if (setq p (assoc (cadr r) names))
      (setq names (subst (cons (car p) (1+ (cdr p))) p names))
      (setq names (cons (cons (cadr r) 1) names))))
  (setq out (mapcar '(lambda (x) (if (> (cdr x) 1) (strcat (car x) " (" (itoa (cdr x)) ")") (car x)))
                    (reverse names)))
  (if (cdr out)
    (strcat (TKA:Join (reverse (cdr (reverse out))) ", ") " `si " (last out))
    (cond ((car out)) (""))))

;; TKA:UiTable - rândurile foii colective (anexa 19) din UI memorate de RELEVEU,
;; cu cotele-părți calculate conform notei din anexă (ca în foile colective
;; uzuale): Cpc = Suap/Stuap (în zecimi de mp), Cpt = Suap/Stuap x St (în
;; sutimi de mp din St, cu suma egală cu terenul aferent). ST = suprafața
;; terenului; ST_AFERENT (date lucrare) = terenul aferent construcției, dacă
;; terenul este comun mai multor construcții.
(defun TKA:UiTable (st / uis stot staf den ns k)
  (setq uis (vlax-ldata-get *TKA:DICT* "UI")
        stot (apply '+ (mapcar 'caddr uis))
        staf (if (> (atof (TKA:Get "ST_AFERENT")) 0) (atof (TKA:Get "ST_AFERENT")) st)
        den (TKA:Int (* 100.0 st)) k 0)
  (if (> stot 0)
    (progn
      (setq ns (TKA:LargestRemainder (mapcar '(lambda (u) (* 100.0 (/ (caddr u) stot) staf)) uis)
                                     (TKA:Int (* 100.0 staf))))
      (list
        (mapcar '(lambda (u n)
                   (setq k (1+ k))
                   (list (cons "TRONSON" "-") (cons "SCARA" "-") (cons "NIVEL" (car u)) (cons "NRAP" (cadr u))
                         (cons "COD" (if (/= (TKA:Get "NRCAD") "") (strcat (TKA:Get "NRCAD") "-C1-U" (itoa k)) ""))
                         (cons "CF" "") (cons "SU" (rtos (caddr u) 2 1))
                         (cons "CPC" (strcat (itoa (TKA:Int (* 10.0 (caddr u)))) "/" (itoa (TKA:Int (* 10.0 stot)))))
                         (cons "CPT" (if (> den 0) (strcat (itoa n) "/" (itoa den)) ""))
                         (cons "OBS" (cond ((cadddr u)) ("")))))
                uis ns)
        (list (cons "TOT_SU" (rtos stot 2 1))
              (cons "TOT_CPC" (strcat (itoa (TKA:Int (* 10.0 stot))) "/" (itoa (TKA:Int (* 10.0 stot)))))
              (cons "TOT_CPT" (if (> den 0) (strcat (itoa (TKA:Int (* 100.0 staf))) "/" (itoa den)) "")))))))

;;; ==========================================================================
;;;  MENIUL GENERATORULUI (comanda ANEXE)
;;; ==========================================================================

;; Elementele listei: (id tip număr titlu)
(setq *TKA:ITEMS*
  '(("16"  "DWG" "16" "Plan de amplasament si delimitare a imobilului (PAD)")
    ("17D" "DWG" "17" "PAD cu propunerea de dezlipire + PAD pentru fiecare lot")
    ("17A" "DWG" "17" "PAD cu propunerea de alipire + PAD al imobilului rezultat")
    ("18"  "DWG" "18" "Releveu - tabelul incaperilor si cartusul (pe nivel)")
    (13 "DOC" "13" "Cerere de receptie si inscriere")
    (14 "DOC" "14" "Declaratie pe proprie raspundere (proprietar)")
    (15 "DOC" "15" "Memoriu tehnic (cu inventarul de coordonate)")
    (20 "DOC" "20" "Proces-verbal de vecinatate")
    (0  "DOC" "-"  "Inventar de coordonate")
    (19 "DOC" "19" "Foaia colectiva (cote-parti calculate)")
    (12 "DOC" "12" "Cerere de informatii (persoana autorizata)")
    (1  "DOC" "1"  "Cerere eliberare copii din arhiva")
    (5  "DOC" "5"  "Cerere de inscriere")
    (6  "DOC" "6"  "Cerere extras de carte funciara pentru informare")
    (7  "DOC" "7"  "Cerere certificat de sarcini")
    (8  "DOC" "8"  "Cerere identificare CF dupa numele proprietarului")
    (10 "DOC" "10" "Cerere certificat imobil neinscris")
    (22 "DOC" "22" "Cerere de anulare numar cadastral")
    (23 "DOC" "23" "Cerere aviz de incepere / receptie (CNC)")
    (26 "DOC" "26" "Adeverinta primarie (posesie) - pentru primarie")
    (27 "DOC" "27" "Certificat registrul agricol - pentru primarie")
    (28 "DOC" "28" "Certificat edificare constructie cu AC - pentru primarie")
    (29 "DOC" "29" "Certificat edificare constructie fara AC - pentru primarie")
    (30 "DOC" "30" "Cerere de informatii pentru planul parcelar")
    (32 "DOC" "32" "Tabel parcelar")
    (34 "DOC" "34" "Cerere consultare registru proprietari (ANCPI)")
    (2  "DOC" "2"  "Instiintare / comunicare incheiere (formular OCPI)")
    (3  "DOC" "3"  "Comunicarea incheierii (formular OCPI)")
    (4  "DOC" "4"  "Incheieri (formular OCPI)")
    (9  "DOC" "9"  "Certificat identificare CF (formular OCPI)")
    (11 "DOC" "11" "Certificat imobil neinscris (formular OCPI)")
    (21 "DOC" "21" "Invitatie pentru lamuriri (formular OCPI)")
    (24 "DOC" "24" "Aviz de incepere a lucrarii (formular CNC)")
    (25 "DOC" "25" "Proces-verbal de receptie (formular CNC/OCPI)")
    (33 "DOC" "33" "PV receptie plan parcelar (formular OCPI)")
    (35 "DOC" "35" "Certificat de sarcini (formular OCPI)")))

;; Pachetele: (cheie tip-lucrare elemente)
(setq *TKA:PACHETE*
  '(("pk_prima"  "PRIMA"  ("16" 13 14 15 20 0))
    ("pk_constr" "CONSTR" ("16" 13 14 15 0))
    ("pk_dez"    "DEZ"    ("17D" 13 14 15 0))
    ("pk_alip"   "ALIP"   ("17A" 13 14 15 0))
    ("pk_ui"     "UI"     ("18" 19 13 15))))

;; TKA:Status - textul de stare din meniul generatorului
(defun TKA:Status (/ h)
  (setq h (TKA:LoadSel "H_IMOBIL"))
  (TKA:Ascii
    (strcat "Imobil: " (if (/= (TKA:Get "NRCAD") "") (strcat "nr. cad. " (TKA:Get "NRCAD")) "nr. cad. -")
            ", UAT " (if (/= (TKA:Get "UAT") "") (TKA:Get "UAT") "-")
            "   |   Proprietar: " (if (/= (TKA:Get "P1_NUME") "") (strcat (TKA:Get "P1_NUME") " " (TKA:Get "P1_PRENUME")) "-")
            "   |   Executant: " (if (/= (TKA:ExecNume) "") (TKA:ExecNume) "- (completati datele)")
            "   |   Selectie memorata: " (if h "da" "nu"))))

;; TKA:MainSel - indicii elementelor selectate în listă
(defun TKA:MainSel (/ v) (setq v (get_tile "lb_anexe")) (if (/= v "") (read (strcat "(" v ")"))))

;; TKA:MainSetSel - selectează în listă elementele cu identificatorii IDS
(defun TKA:MainSetSel (ids / i out)
  (setq i 0)
  (foreach it *TKA:ITEMS* (if (member (car it) ids) (setq out (cons (itoa i) out))) (setq i (1+ i)))
  (set_tile "lb_anexe" (TKA:Join (reverse out) " ")))

;; TKA:MainInfo - descrierea primului element selectat
(defun TKA:MainInfo (/ sel it)
  (if (setq sel (TKA:MainSel))
    (progn
      (setq it (nth (car sel) *TKA:ITEMS*))
      (set_tile "tx_info"
                (strcat (if (= (cadr it) "DWG") "Piesa desenata (layout AutoCAD): " "Document Word completat automat: ")
                        "Anexa " (caddr it) " - " (cadddr it)
                        "   (" (itoa (length sel)) " selectate)")))))

;; TKA:MainDialog - meniul generatorului; returnează lista elementelor alese
(defun TKA:MainDialog (/ res)
  (setq *TKA:SEL* nil)
  (setq res
    (TKA:Dialog "tka_main"
      '(progn
         (TKA:FillList "lb_anexe" (mapcar '(lambda (it) (strcat (cadr it) "\t" (caddr it) "\t" (cadddr it))) *TKA:ITEMS*))
         (set_tile "tx_stare" (TKA:Status))
         (set_tile "tg_pdf" *TKA:PDF*)
         (set_tile "tg_open" *TKA:OPENDIR*)
         (action_tile "lb_anexe" "(TKA:MainInfo)")
         (action_tile "bt_toate" "(TKA:MainSetSel (vl-remove-if-not 'numberp (mapcar 'car *TKA:ITEMS*))) (TKA:MainInfo)")
         (action_tile "bt_nimic" "(set_tile \"lb_anexe\" \"\")")
         (foreach p *TKA:PACHETE*
           (action_tile (car p) (strcat "(TKA:Put \"TIP\" \"" (cadr p) "\") (TKA:MainSetSel '"
                                        (vl-prin1-to-string (caddr p)) ") (TKA:MainInfo)")))
         (action_tile "bt_imobil" "(done_dialog 11)")
         (action_tile "bt_lucrare" "(done_dialog 12)")
         (action_tile "bt_exec" "(done_dialog 13)")
         (action_tile "bt_opt" "(done_dialog 14)")
         (action_tile "accept"
           (strcat "(setq *TKA:PDF* (get_tile \"tg_pdf\") *TKA:OPENDIR* (get_tile \"tg_open\")"
                   " *TKA:SEL* (mapcar '(lambda (i) (car (nth i *TKA:ITEMS*))) (TKA:MainSel)))"
                   " (if *TKA:SEL* (done_dialog 1) (set_tile \"error\" \"Selectati cel putin o anexa sau un pachet.\"))"))
         (action_tile "cancel" "(done_dialog 0)"))))
  res)

;; TKA:AskReuse - folosirea selecției memorate a imobilului (Da/Nu)
(defun TKA:AskReuse (/ k)
  (if (TKA:LoadSel "H_IMOBIL")
    (progn
      (initget "Da Nu")
      (setq k (getkword "\nFolositi imobilul (si loturile/constructiile) selectat anterior? [Da/Nu] <Da>: "))
      (/= k "Nu"))))

;; TKA:Generate - generează elementele alese în meniu
(defun TKA:Generate (sel / rec docs i st ui)
  (cond
    ((member "17D" sel) (setq rec (TKA:DoPadDez (TKA:AskReuse))))
    ((member "17A" sel) (setq rec (TKA:DoPadAlip (TKA:AskReuse))))
    ((member "16" sel) (setq rec (TKA:DoPad16 (TKA:AskReuse)))))
  (if (member "18" sel) (TKA:DoReleveu))
  (setq docs (vl-remove-if-not 'numberp sel))
  (if docs
    (progn
      (if (and (null rec) (vl-some '(lambda (n) (member n '(13 14 15 20 0 19 7 26 27 28 29))) docs))
        (setq rec (TKA:CurrentRec)))
      ;; foaia colectivă: cotele-părți calculate din UI memorate
      (setq *TKA:UIDATA* (if (member 19 docs) (TKA:UiTable (if rec (float (TKA:R1 rec "AREA")) (atof (TKA:Get "SACT"))))))
      (TKA:MakeWord docs rec "")
      ;; inventarul de coordonate pentru fiecare lot (dezlipire)
      (if (and (member "17D" sel) (member 0 docs) *TKA:LOTURI*)
        (progn
          (setq i 0)
          (foreach r *TKA:LOTURI*
            (setq i (1+ i))
            (TKA:MakeWord '(0) r (strcat "_lot" (itoa i)))))))))

;; C:ANEXE - meniul generatorului de anexe
(defun c:ANEXE (/ r)
  (while (and (setq r (TKA:MainDialog)) (> r 10))
    (cond ((= r 11) (TKA:ImobilDialog))
          ((= r 12) (TKA:LucrareDialog))
          ((= r 13) (TKA:ExecDialog))
          ((= r 14) (TKA:OptDialog))))
  (if (= r 1) (TKA:Run '(TKA:Generate *TKA:SEL*)))
  (princ))

;; C:TKANEXE - alias
(defun c:TKANEXE () (c:ANEXE))

;; C:RELEVEU - comanda directă pentru anexa 18
(defun c:RELEVEU () (TKA:Run '(TKA:DoReleveu)) (princ))

;;; ==========================================================================
;;;  DIALOGUL (COPIE PENTRU GENERAREA AUTOMATĂ)
;;; ==========================================================================
;; TKA:DclLines - conținutul fișierului TopoKitAnexe.dcl
;; (Secțiune generată din TopoKitAnexe.dcl cu tools/embed_dcl.py - nu editați manual.)
;;@@DCL-BEGIN@@
(defun TKA:DclLines ()
  (list
    "// ==========================================================================="
    "//  TopoKitAnexe.dcl - dialogurile generatorului de anexe (Ordinul ANCPI 600/2023)"
    "//  Fisierul este optional: daca lipseste, TopoKitAnexe.lsp genereaza automat"
    "//  o copie identica intr-un fisier temporar."
    "// ==========================================================================="
    ""
    "tka_ed : edit_box { edit_width = 26; edit_limit = 250; }"
    "tka_btn : button { width = 30; fixed_width = true; }"
    ""
    "// ---------------------------------------------------------------------------"
    "//  Meniul generatorului de anexe (comanda ANEXE)"
    "// ---------------------------------------------------------------------------"
    "tka_main : dialog {"
    "  label = \"TopoKit - Generator anexe (Ordinul ANCPI nr. 600/2023)\";"
    "  : row {"
    "    : boxed_column {"
    "      label = \"Anexe (selectie multipla: Ctrl / Shift + clic)\";"
    "      : list_box { key = \"lb_anexe\"; multiple_select = true; width = 78; height = 26; tabs = \"7 12\"; }"
    "      : row {"
    "        : button { key = \"bt_toate\"; label = \"Toate anexele Word\"; }"
    "        : button { key = \"bt_nimic\"; label = \"Deselecteaza\"; }"
    "      }"
    "    }"
    "    : column {"
    "      : boxed_column {"
    "        label = \"Pachete (documentatie completa)\";"
    "        : tka_btn { key = \"pk_prima\";  label = \"Prima inregistrare\"; }"
    "        : tka_btn { key = \"pk_constr\"; label = \"Inscriere constructie\"; }"
    "        : tka_btn { key = \"pk_dez\";    label = \"Dezlipire teren\"; }"
    "        : tka_btn { key = \"pk_alip\";   label = \"Alipire teren\"; }"
    "        : tka_btn { key = \"pk_ui\";     label = \"Prima inregistrare UI / apartamentare\"; }"
    "      }"
    "      : boxed_column {"
    "        label = \"Datele lucrarii\";"
    "        : tka_btn { key = \"bt_imobil\";  label = \"Imobil si proprietari...\"; }"
    "        : tka_btn { key = \"bt_lucrare\"; label = \"Lucrare si memoriu tehnic...\"; }"
    "        : tka_btn { key = \"bt_exec\";    label = \"Executant (persoana autorizata)...\"; }"
    "        : tka_btn { key = \"bt_opt\";     label = \"Optiuni planuri (format, scara)...\"; }"
    "      }"
    "      : boxed_column {"
    "        label = \"Rezultat\";"
    "        : toggle { key = \"tg_pdf\";  label = \"Converteste anexele Word in PDF\"; }"
    "        : toggle { key = \"tg_open\"; label = \"Deschide folderul cu anexele\"; }"
    "      }"
    "    }"
    "  }"
    "  : boxed_column {"
    "    label = \"Stare\";"
    "    : text { key = \"tx_info\";  label = \"\"; width = 120; }"
    "    : text { key = \"tx_stare\"; label = \"\"; width = 120; }"
    "  }"
    "  : row {"
    "    fixed_width = true;"
    "    alignment = centered;"
    "    : button { key = \"accept\"; label = \"Genereaza\"; is_default = true; width = 18; }"
    "    : button { key = \"cancel\"; label = \"Inchide\"; is_cancel = true; width = 18; }"
    "  }"
    "  errtile;"
    "}"
    ""
    "// ---------------------------------------------------------------------------"
    "//  Datele imobilului si ale proprietarilor (salvate in desen)"
    "// ---------------------------------------------------------------------------"
    "tka_imobil : dialog {"
    "  label = \"TopoKit - Date imobil si proprietari\";"
    "  : row {"
    "    : boxed_column {"
    "      label = \"Imobil\";"
    "      : tka_ed { key = \"NRCAD\";      label = \"Numar cadastral:\"; }"
    "      : tka_ed { key = \"NRCF\";       label = \"Nr. carte funciara:\"; }"
    "      : tka_ed { key = \"UAT\";        label = \"UAT:\"; }"
    "      : tka_ed { key = \"LOCALITATE\"; label = \"Localitate:\"; }"
    "      : tka_ed { key = \"JUDET\";      label = \"Judet:\"; }"
    "      : tka_ed { key = \"STRADA\";     label = \"Strada:\"; }"
    "      : row {"
    "        : edit_box { key = \"NR\";    label = \"Nr.:\";  edit_width = 5; }"
    "        : edit_box { key = \"BLOC\";  label = \"Bl.:\";  edit_width = 4; }"
    "        : edit_box { key = \"SCARA\"; label = \"Sc.:\";  edit_width = 3; }"
    "      }"
    "      : row {"
    "        : edit_box { key = \"ETAJ\";  label = \"Et.:\";  edit_width = 3; }"
    "        : edit_box { key = \"AP\";    label = \"Ap.:\";  edit_width = 4; }"
    "      }"
    "      : tka_ed { key = \"TARLA\";    label = \"Tarla:\"; }"
    "      : tka_ed { key = \"PARCELA\";  label = \"Parcela:\"; }"
    "      : tka_ed { key = \"NRTOP\";    label = \"Nr. topografic:\"; }"
    "      : tka_ed { key = \"DENUMIRE_LOC\"; label = \"Denumirea locului:\"; }"
    "      : popup_list { key = \"CATEG\"; label = \"Categoria de folosinta:\"; edit_width = 24; }"
    "      : tka_ed { key = \"SACT\";     label = \"Suprafata din act (mp):\"; }"
    "      : tka_ed { key = \"ACT_PROP\"; label = \"Act de proprietate:\"; }"
    "      : tka_ed { key = \"MENT_TEREN\"; label = \"Mentiuni teren (PAD):\"; }"
    "      : tka_ed { key = \"OCPI\";     label = \"OCPI (judet):\"; }"
    "      : tka_ed { key = \"BCPI\";     label = \"BCPI:\"; }"
    "    }"
    "    : boxed_column {"
    "      label = \"Proprietar 1 (solicitant)\";"
    "      : tka_ed { key = \"P1_NUME\";     label = \"Nume:\"; }"
    "      : tka_ed { key = \"P1_PRENUME\";  label = \"Prenume:\"; }"
    "      : tka_ed { key = \"P1_CNP\";      label = \"CNP/CUI:\"; }"
    "      : row {"
    "        : edit_box { key = \"P1_CI_SERIA\"; label = \"CI seria:\"; edit_width = 4; }"
    "        : edit_box { key = \"P1_CI_NR\";    label = \"nr.:\"; edit_width = 9; }"
    "      }"
    "      : tka_ed { key = \"P1_CI_EMITENT\"; label = \"CI eliberata de:\"; }"
    "      : tka_ed { key = \"P1_LOC\";      label = \"Domiciliu - localitate:\"; }"
    "      : tka_ed { key = \"P1_STR\";      label = \"Strada:\"; }"
    "      : row {"
    "        : edit_box { key = \"P1_NR\"; label = \"Nr.:\"; edit_width = 4; }"
    "        : edit_box { key = \"P1_BL\"; label = \"Bl.:\"; edit_width = 4; }"
    "        : edit_box { key = \"P1_SC\"; label = \"Sc.:\"; edit_width = 3; }"
    "      }"
    "      : row {"
    "        : edit_box { key = \"P1_ET\"; label = \"Et.:\"; edit_width = 3; }"
    "        : edit_box { key = \"P1_AP\"; label = \"Ap.:\"; edit_width = 4; }"
    "      }"
    "      : tka_ed { key = \"P1_JUD\";      label = \"Judet/sector:\"; }"
    "      : tka_ed { key = \"P1_CODP\";     label = \"Cod postal:\"; }"
    "      : tka_ed { key = \"P1_TEL\";      label = \"Telefon:\"; }"
    "      : tka_ed { key = \"P1_EMAIL\";    label = \"E-mail:\"; }"
    "      : tka_ed { key = \"P1_CALITATE\"; label = \"Calitatea:\"; }"
    "    }"
    "    : boxed_column {"
    "      label = \"Proprietar 2 (optional)\";"
    "      : tka_ed { key = \"P2_NUME\";     label = \"Nume:\"; }"
    "      : tka_ed { key = \"P2_PRENUME\";  label = \"Prenume:\"; }"
    "      : tka_ed { key = \"P2_CNP\";      label = \"CNP:\"; }"
    "      : row {"
    "        : edit_box { key = \"P2_CI_SERIA\"; label = \"CI seria:\"; edit_width = 4; }"
    "        : edit_box { key = \"P2_CI_NR\";    label = \"nr.:\"; edit_width = 9; }"
    "      }"
    "      : tka_ed { key = \"P2_LOC\";      label = \"Domiciliu - localitate:\"; }"
    "      : tka_ed { key = \"P2_CALITATE\"; label = \"Calitatea:\"; }"
    "      spacer_1;"
    "      : text { label = \"Datele se salveaza in desen si\"; }"
    "      : text { label = \"completeaza automat cererile,\"; }"
    "      : text { label = \"declaratiile, PV de vecinatate,\"; }"
    "      : text { label = \"memoriul tehnic si planurile.\"; }"
    "    }"
    "  }"
    "  ok_cancel;"
    "  errtile;"
    "}"
    ""
    "// ---------------------------------------------------------------------------"
    "//  Datele lucrarii si textele memoriului tehnic"
    "// ---------------------------------------------------------------------------"
    "tka_lucrare : dialog {"
    "  label = \"TopoKit - Date lucrare si memoriu tehnic\";"
    "  : row {"
    "    : boxed_column {"
    "      label = \"Lucrare\";"
    "      : popup_list { key = \"TIP\"; label = \"Tipul lucrarii:\"; edit_width = 46; }"
    "      : popup_list { key = \"COMUNICARE\"; label = \"Comunicarea raspunsului:\"; edit_width = 46; }"
    "      : tka_ed { key = \"INTAB_OBIECT\"; label = \"Intabularea (obiect):\"; edit_width = 46; }"
    "      : tka_ed { key = \"E_CONTRACT\"; label = \"Contract/angajament nr.:\"; }"
    "      : tka_ed { key = \"E_CONTRACT_DATA\"; label = \"din data:\"; }"
    "      : tka_ed { key = \"DATA_MAS\"; label = \"Data masuratorilor:\"; }"
    "      : row {"
    "        : edit_box { key = \"PV_EXEMPLARE\"; label = \"PV vecinatate - exemplare:\"; edit_width = 4; }"
    "        : edit_box { key = \"PV_PAGINI\"; label = \"pagini:\"; edit_width = 4; }"
    "      }"
    "      : toggle { key = \"POZ_INCERTA\"; label = \"Pozitionare incerta (declaratia anexa 14)\"; }"
    "      : tka_ed { key = \"NRCF_COLECTIVA\"; label = \"CF colectiva (UI):\"; }"
    "      : tka_ed { key = \"ST_AFERENT\"; label = \"Teren aferent cladirii (mp):\"; }"
    "      : tka_ed { key = \"PARTI_COMUNE\"; label = \"Parti comune (UI):\"; edit_width = 46; }"
    "    }"
    "    : boxed_column {"
    "      label = \"Memoriu tehnic (gol = text generat automat)\";"
    "      : edit_box { key = \"METODA\";      label = \"Metoda:\";     edit_width = 60; edit_limit = 400; }"
    "      : edit_box { key = \"APARATURA\";   label = \"Aparatura:\";  edit_width = 60; edit_limit = 400; }"
    "      : edit_box { key = \"SPRIJIN\";     label = \"Puncte de sprijin:\"; edit_width = 60; edit_limit = 400; }"
    "      : edit_box { key = \"SCOP\";        label = \"4. Scop:\";    edit_width = 60; edit_limit = 2000; }"
    "      : edit_box { key = \"DOCUMENTARE\"; label = \"5. Documentare:\"; edit_width = 60; edit_limit = 2000; }"
    "      : edit_box { key = \"OPERATIUNI\";  label = \"6. Operatiuni:\";  edit_width = 60; edit_limit = 2000; }"
    "      spacer_1;"
    "      : text { label = \"Textele lungi se pot ajusta si in documentul Word generat.\"; }"
    "    }"
    "  }"
    "  ok_cancel;"
    "  errtile;"
    "}"
    ""
    "// ---------------------------------------------------------------------------"
    "//  Datele persoanei autorizate (salvate pe calculator)"
    "// ---------------------------------------------------------------------------"
    "tka_exec : dialog {"
    "  label = \"TopoKit - Executant (persoana autorizata)\";"
    "  : row {"
    "    : boxed_column {"
    "      label = \"Identificare\";"
    "      : tka_ed { key = \"E_TITLU\";   label = \"Titlu (ing., dr. ing.):\"; }"
    "      : tka_ed { key = \"E_NUME\";    label = \"Nume:\"; }"
    "      : tka_ed { key = \"E_PRENUME\"; label = \"Prenume:\"; }"
    "      : tka_ed { key = \"E_CNP\";     label = \"CNP/CUI:\"; }"
    "      : tka_ed { key = \"E_FIRMA\";   label = \"Firma (PFA/PJA):\"; }"
    "      : row {"
    "        : edit_box { key = \"E_CI_SERIA\"; label = \"CI seria:\"; edit_width = 4; }"
    "        : edit_box { key = \"E_CI_NR\";    label = \"nr.:\"; edit_width = 9; }"
    "      }"
    "      : tka_ed { key = \"E_TEL\";     label = \"Telefon:\"; }"
    "      : tka_ed { key = \"E_EMAIL\";   label = \"E-mail:\"; }"
    "    }"
    "    : boxed_column {"
    "      label = \"Autorizatie si adresa\";"
    "      : tka_ed { key = \"E_CAT\";         label = \"Categoria/clasa:\"; }"
    "      : tka_ed { key = \"E_AUT_SERIA\";   label = \"Seria (ex. RO-BV-F):\"; }"
    "      : tka_ed { key = \"E_AUT_NR\";      label = \"Numar:\"; }"
    "      : tka_ed { key = \"E_AUT_EMITENT\"; label = \"Emisa de:\"; }"
    "      : tka_ed { key = \"E_AUT_DATA\";    label = \"Data emiterii:\"; }"
    "      : tka_ed { key = \"E_LOC\";         label = \"Localitate:\"; }"
    "      : tka_ed { key = \"E_STR\";         label = \"Strada:\"; }"
    "      : tka_ed { key = \"E_NR\";          label = \"Nr.:\"; }"
    "      : tka_ed { key = \"E_JUD\";         label = \"Judet:\"; }"
    "    }"
    "  }"
    "  ok_cancel;"
    "  errtile;"
    "}"
    ""
    "// ---------------------------------------------------------------------------"
    "//  Optiunile planurilor (format, scara, numerotare)"
    "// ---------------------------------------------------------------------------"
    "tka_opt : dialog {"
    "  label = \"TopoKit - Optiuni planuri\";"
    "  : boxed_column {"
    "    label = \"Pagina\";"
    "    : popup_list { key = \"pl_format\"; label = \"Format:\"; edit_width = 26; }"
    "    : popup_list { key = \"pl_scara\";  label = \"Scara:\";  edit_width = 26; }"
    "  }"
    "  : boxed_column {"
    "    label = \"Numerotare si cote\";"
    "    : edit_box { key = \"eb_start\"; label = \"Primul numar de punct:\"; edit_width = 6; }"
    "    : radio_column {"
    "      key = \"rc_mod\";"
    "      : radio_button { key = \"rb_nv\";  label = \"Sens orar, din punctul cel mai de nord-vest\"; }"
    "      : radio_button { key = \"rb_pol\"; label = \"Ordinea vertex-urilor poliliniei\"; }"
    "    }"
    "    : radio_row {"
    "      key = \"rr_sep\";"
    "      : radio_button { key = \"rb_virg\"; label = \"Zecimale cu virgula (12,34)\"; }"
    "      : radio_button { key = \"rb_punct\"; label = \"cu punct (12.34)\"; }"
    "    }"
    "    : toggle { key = \"tg_inv\"; label = \"Inventar de coordonate pe plan\"; }"
    "  }"
    "  : boxed_column {"
    "    label = \"Etichete\";"
    "    : edit_box { key = \"eb_a16\"; label = \"Eticheta anexei 16:\"; edit_width = 20; }"
    "    : edit_box { key = \"eb_a17\"; label = \"Eticheta anexei 17:\"; edit_width = 20; }"
    "  }"
    "  ok_cancel;"
    "  errtile;"
    "}"
    ""
    "// ---------------------------------------------------------------------------"
    "//  Laturile imobilului: vecini, identificatori, materializare"
    "// ---------------------------------------------------------------------------"
    "tka_laturi : dialog {"
    "  label = \"TopoKit - Laturi si vecinatati\";"
    "  : list_box { key = \"lb_lat\"; multiple_select = true; width = 110; height = 16; tabs = \"8 18 48 80\"; }"
    "  : text { label = \"Selectati una sau mai multe laturi, completati campurile si apasati Aplica.\"; }"
    "  : boxed_column {"
    "    label = \"Date latura\";"
    "    : edit_box { key = \"eb_id\";    label = \"Identificator vecin (pe plan):\"; edit_width = 50; edit_limit = 120; }"
    "    : edit_box { key = \"eb_vecin\"; label = \"Vecin (nume si prenume / denumire):\"; edit_width = 50; edit_limit = 120; }"
    "    : row {"
    "      : popup_list { key = \"pl_mat\"; label = \"Materializare:\"; edit_width = 22; }"
    "      : edit_box { key = \"eb_mat\"; edit_width = 26; edit_limit = 120; }"
    "    }"
    "    : edit_box { key = \"eb_obs\";   label = \"Observatii:\"; edit_width = 50; edit_limit = 120; }"
    "    : row {"
    "      : button { key = \"bt_aplica\"; label = \"Aplica la laturile selectate\"; }"
    "      : button { key = \"bt_auto\";   label = \"Detecteaza din desen\"; }"
    "      : button { key = \"bt_sterge\"; label = \"Sterge datele selectiei\"; }"
    "    }"
    "  }"
    "  ok_cancel;"
    "  errtile;"
    "}"
    ""
    "// ---------------------------------------------------------------------------"
    "//  Datele unei constructii"
    "// ---------------------------------------------------------------------------"
    "tka_constr : dialog {"
    "  label = \"TopoKit - Date constructie\";"
    "  : text { key = \"tx_info\"; label = \"\"; width = 60; }"
    "  : boxed_column {"
    "    label = \"Constructie\";"
    "    : edit_box { key = \"COD\";      label = \"Cod (C1, C2...):\"; edit_width = 8; }"
    "    : popup_list { key = \"DEST\";   label = \"Destinatia:\"; edit_width = 40; }"
    "    : edit_box { key = \"DENUMIRE\"; label = \"Denumire (ex. Casa de locuit):\"; edit_width = 40; edit_limit = 120; }"
    "    : edit_box { key = \"REGIM\";    label = \"Regim de inaltime (ex. P+1E):\"; edit_width = 12; }"
    "    : edit_box { key = \"AN\";       label = \"Anul construirii:\"; edit_width = 8; }"
    "    : edit_box { key = \"SD\";       label = \"Suprafata desfasurata (mp):\"; edit_width = 10; }"
    "    : edit_box { key = \"NRUI\";     label = \"Numar unitati individuale:\"; edit_width = 6; }"
    "    : edit_box { key = \"MENT\";     label = \"Alte mentiuni:\"; edit_width = 40; edit_limit = 250; }"
    "  }"
    "  ok_cancel;"
    "  errtile;"
    "}"))
;;@@DCL-END@@

(setq *TKA:LOADING* nil)
(princ "\nTopoKit Anexe incarcat. Comenzi: ANEXE, PAD, PADDEZ, PADALIP, VECINI, DATEIMOBIL, EXECUTANT, CONSTRUCTIE, RELEVEU, ANEXEWORD.")
(princ)
