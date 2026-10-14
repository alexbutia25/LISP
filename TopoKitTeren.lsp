;;; ==========================================================================
;;;  TopoKitTeren.lsp  -  Modulul de teren TopoKit
;;; ==========================================================================
;;;
;;;  Comenzi:
;;;    TOPOTEREN - meniul modulului (opțiuni și toate comenzile de mai jos)
;;;    IMPPCT    - import puncte măsurate (Nr, X, Y, Z, Cod) din TXT/CSV:
;;;                puncte 2D/3D, numere, cote, linii pe coduri (desenare rapidă)
;;;    TABPCT    - tabel cu coordonatele punctelor selectate
;;;    LEGENDA   - legenda semnelor convenționale folosite în desen
;;;    TIN       - modelul 3D al terenului: rețea de triunghiuri (Delaunay) din
;;;                puncte 3D și linii de frângere, ca entități 3DFACE
;;;    CURBE     - curbe de nivel din TIN (principale/secundare, cu cote)
;;;    VOLUM     - volume de săpătură/umplutură între TIN și un plan de cotă dată
;;;    VOLUM2    - volume între două TIN (teren existent - proiect)
;;;    GEOREF    - inserare raster georeferențiat (fișier world: .jgw .tfw .pgw .wld)
;;;    IMPKML    - import KML/KMZ (Google Earth) cu transformare WGS84 -> Stereo 70
;;;    HARTA     - deschide punctul indicat în Google Maps (hartă online)
;;;
;;;  Convenții: unitatea desenului este metrul; X desen = Est, Y desen = Nord
;;;  (opțiunea "Axe inversate" din TOPOKIT schimbă ordinea). Necesită TopoKit.lsp.
;;; ==========================================================================

(vl-load-com)
(setq *TKT:LOADING* T)
(if (and (not TK:Start) (findfile "TopoKit.lsp")) (load (findfile "TopoKit.lsp")))
(if (not TK:Start)
  (alert "TopoKitTeren.lsp necesita TopoKit.lsp (in acelasi folder, in calea de suport AutoCAD)."))

;; Opțiuni (păstrate pe durata sesiunii)
(foreach p '((*TKT:COLS*    . "NXYZC")  ; NXYZC = Nr X(N) Y(E) Z Cod; NYXZC = Nr Y(E) X(N) Z Cod; XYZ
             (*TKT:3D*      . "1")      ; punctele la cota Z (altfel la Z = 0, cu cota scrisă)
             (*TKT:CODURI*  . "1")      ; unește punctele consecutive cu același cod
             (*TKT:SCARA*   . 500)      ; scara planului (înălțimea textelor)
             (*TKT:LMAX*    . 0.0)      ; latura maximă a triunghiurilor TIN (0 = fără limită)
             (*TKT:ECHID*   . 1.0)      ; echidistanța curbelor de nivel (m)
             (*TKT:PRINC*   . 5)        ; curbă principală la fiecare N curbe
             (*TKT:COTAREF* . 0.0)      ; cota planului de referință pentru volume
             (*TKT:CELULA*  . 1.0))     ; pasul grilei la volumele între două TIN
  (if (null (eval (car p))) (set (car p) (cdr p))))

(setq *TKT:SCALES* '(100 200 500 1000 2000 5000))
(setq *TKT:COLLIST* '(("NXYZC" . "Nr, X (Nord), Y (Est), Z, Cod")
                      ("NYXZC" . "Nr, Y (Est), X (Nord), Z, Cod")
                      ("XYZ"   . "X (Nord), Y (Est), Z (fara numar)")))

;;; ==========================================================================
;;;  UTILITARE
;;; ==========================================================================

;; TKT:Msg - mesaj în linia de comandă
(defun TKT:Msg (s) (princ (strcat "\n" s)))

;; TKT:K - metri în teren pentru 1 mm pe hârtie, la scara planului
(defun TKT:K () (/ *TKT:SCARA* 1000.0))

;; TKT:H - înălțimea textelor din plan (1,8 mm la scară)
(defun TKT:H () (* 1.8 (TKT:K)))

;; TKT:ToDwg - punctul din desen pentru coordonatele Stereo 70 (E N Z)
(defun TKT:ToDwg (e n z) (if (= *TK:SWAPXY* "1") (list n e z) (list e n z)))

;; TKT:Layers - straturile modulului
(defun TKT:Layers ()
  (foreach l '(("PUNCTE" . 7) ("PCT_NR" . 7) ("PCT_COTA" . 8) ("TIN" . 8) ("CURBE_PRINC" . 30)
               ("CURBE_SEC" . 32) ("CURBE_COTE" . 30) ("TABEL_PCT" . 7) ("LEGENDA" . 7) ("VOLUME" . 7)
               ("KML" . 1) ("RASTER" . 7))
    (TK:MakeLayer (car l) (cdr l))))

;; TKT:Txt - text cu justificarea J ("L" "MC" "ML" "MR")
(defun TKT:Txt (s p h rot j lay / jj)
  (setq jj (cdr (assoc j '(("L" 0 . 0) ("MC" 1 . 2) ("ML" 0 . 2) ("MR" 2 . 2) ("C" 1 . 0)))))
  (entmake (list '(0 . "TEXT") (cons 8 lay) (list 10 (car p) (cadr p) 0.0) (list 11 (car p) (cadr p) 0.0)
                 (cons 40 h) (cons 1 s) (cons 50 rot) (cons 7 (TK:Style)) (cons 72 (car jj)) (cons 73 (cdr jj)))))

;; TKT:Ln - linie 2D
(defun TKT:Ln (a b lay)
  (entmake (list '(0 . "LINE") (cons 8 lay) (list 10 (car a) (cadr a) 0.0) (list 11 (car b) (cadr b) 0.0))))

;; TKT:Readable - unghiul unui text paralel cu o direcție, citibil
(defun TKT:Readable (a)
  (setq a (TK:Mod2Pi a))
  (if (and (> a (/ pi 2.0)) (<= a (* 1.5 pi))) (- a pi) a))

;; TKT:Inside - T dacă punctul P este în interiorul poligonului PTS (2D)
(defun TKT:Inside (p pts / in)
  (mapcar '(lambda (a b)
             (if (and (/= (> (cadr a) (cadr p)) (> (cadr b) (cadr p)))
                      (< (car p) (+ (car a) (/ (* (- (car b) (car a)) (- (cadr p) (cadr a))) (- (cadr b) (cadr a))))))
               (setq in (not in))))
          pts (append (cdr pts) (list (car pts))))
  in)

;; TKT:Area2 - aria cu semn a unui poligon (pozitivă = sens trigonometric)
(defun TKT:Area2 (pts / a)
  (setq a 0.0)
  (mapcar '(lambda (p q) (setq a (+ a (- (* (car p) (cadr q)) (* (car q) (cadr p))))))
          pts (append (cdr pts) (list (car pts))))
  (/ a 2.0))

;; TKT:Verts - vârfurile 3D ale unei polilinii (WCS, cu elevația)
(defun TKT:Verts (e / n i out)
  (setq n (fix (+ 0.5 (vlax-curve-getEndParam e))) i 0)
  (repeat (if (vlax-curve-isClosed e) n (1+ n))
    (setq out (cons (vlax-curve-getPointAtParam e (float i)) out) i (1+ i)))
  (reverse out))

;; TKT:Split - câmpurile unui rând din fișierul de puncte: (separator câmpuri).
;; Separatorul se detectează: ";", tab, "," sau spații.
(defun TKT:Split (s / sep out cur c)
  (setq sep (cond ((vl-string-search ";" s) ";") ((vl-string-search "\t" s) "\t")
                  ((vl-string-search "," s) ",") (T " "))
        cur "")
  (foreach c (vl-string->list s)
    (if (= (chr c) sep)
      (setq out (cons cur out) cur "")
      (setq cur (strcat cur (chr c)))))
  (setq out (mapcar '(lambda (x) (vl-string-trim " \t\r" x)) (reverse (cons cur out))))
  (list sep (if (= sep " ") (vl-remove "" out) out)))

;; TKT:Val - valoarea numerică a unui câmp (virgula zecimală acceptată dacă
;; separatorul nu este virgula); nil dacă nu este număr
(defun TKT:Val (s sep)
  (if (and s (/= s ""))
    (distof (if (/= sep ",") (vl-string-translate "," "." s) s) 2)))

;; TKT:Words - cuvintele unui text (separate prin spații, tab-uri, rânduri noi)
(defun TKT:Words (s / out cur)
  (setq cur "")
  (foreach c (vl-string->list s)
    (if (member c '(32 9 10 13))
      (progn (if (/= cur "") (setq out (cons cur out))) (setq cur ""))
      (setq cur (strcat cur (chr c)))))
  (reverse (if (/= cur "") (cons cur out) out)))

;; TKT:Ceil / TKT:Floor - rotunjire la întreg în sus / în jos
(defun TKT:Ceil (x) (if (> x (+ (fix x) 1e-9)) (1+ (fix x)) (fix x)))
(defun TKT:Floor (x) (if (< x (- (fix x) 1e-9)) (1- (fix x)) (fix x)))

;; TKT:Fmt - număr cu D zecimale
(defun TKT:Fmt (x d) (rtos x 2 d))

;;; ==========================================================================
;;;  IMPORT PUNCTE ȘI DESENARE PE CODURI (IMPPCT)
;;; ==========================================================================

;; TKT:ParseLine - (nr E N Z cod) dintr-un rând, după formatul *TKT:COLS*; nil pentru antete
(defun TKT:ParseLine (l i / r sep f n e z)
  (setq r (TKT:Split l) sep (car r) f (cadr r))
  (cond
    ((= *TKT:COLS* "XYZ")
     (setq n (TKT:Val (nth 0 f) sep) e (TKT:Val (nth 1 f) sep) z (TKT:Val (nth 2 f) sep))
     (if (and n e) (list (itoa i) e n z "")))
    (T
     (if (= *TKT:COLS* "NYXZC")
       (setq e (TKT:Val (nth 1 f) sep) n (TKT:Val (nth 2 f) sep))
       (setq n (TKT:Val (nth 1 f) sep) e (TKT:Val (nth 2 f) sep)))
     (setq z (TKT:Val (nth 3 f) sep))
     (if (and n e (nth 0 f) (/= (nth 0 f) ""))
       (list (nth 0 f) e n z (if (nth 4 f) (strcase (nth 4 f)) ""))))))

;; TKT:ReadPoints - punctele dintr-un fișier
(defun TKT:ReadPoints (f / fh l r out i)
  (setq i 0)
  (if (setq fh (open f "r"))
    (progn
      (while (setq l (read-line fh))
        (if (setq r (TKT:ParseLine l (1+ i))) (setq out (cons r out) i (1+ i))))
      (close fh)))
  (reverse out))

;; TKT:DrawPoint - punctul (POINT), numărul și cota lui
(defun TKT:DrawPoint (r / p h)
  (setq p (TKT:ToDwg (nth 1 r) (nth 2 r) (if (and (nth 3 r) (= *TKT:3D* "1")) (nth 3 r) 0.0))
        h (TKT:H))
  (entmake (list '(0 . "POINT") '(8 . "PUNCTE") (list 10 (car p) (cadr p) (caddr p))))
  (TKT:Txt (car r) (list (+ (car p) (* 0.6 h)) (+ (cadr p) (* 0.4 h))) h 0.0 "L" "PCT_NR")
  (if (nth 3 r)
    (TKT:Txt (TKT:Fmt (nth 3 r) 2) (list (+ (car p) (* 0.6 h)) (- (cadr p) (* 1.3 h))) (* 0.8 h) 0.0 "L" "PCT_COTA"))
  p)

;; TKT:CodeLine - linia prin punctele cu același cod (3D sau 2D), pe stratul COD_<cod>
(defun TKT:CodeLine (pts cod / lay)
  (setq lay (TK:MakeLayer (strcat "COD_" (TK:SafeName cod)) 7))
  (if (= *TKT:3D* "1")
    (progn
      (entmake (list '(0 . "POLYLINE") (cons 8 lay) '(66 . 1) '(10 0.0 0.0 0.0) '(70 . 8)))
      (foreach p pts (entmake (list '(0 . "VERTEX") (cons 8 lay) (list 10 (car p) (cadr p) (caddr p)) '(70 . 32))))
      (entmake (list '(0 . "SEQEND") (cons 8 lay))))
    (entmake (append (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") (cons 8 lay) '(100 . "AcDbPolyline")
                           (cons 90 (length pts)) '(70 . 0))
                     (mapcar '(lambda (p) (list 10 (car p) (cadr p))) pts)))))

;; TKT:ImportPoints - comanda IMPPCT
(defun TKT:ImportPoints (/ f recs pts cur cod n nl)
  (if (setq f (getfiled "Fisierul cu puncte masurate" (getvar "DWGPREFIX") "txt;csv;xyz;dat;pts" 0))
    (progn
      (setq recs (TKT:ReadPoints f) n 0 nl 0)
      (if (null recs)
        (TKT:Msg "Fisierul nu contine puncte in formatul ales (verificati ordinea coloanelor).")
        (progn
          (foreach r recs (setq pts (cons (cons (TKT:DrawPoint r) (nth 4 r)) pts) n (1+ n)))
          (setq pts (reverse pts))
          ;; liniile pe coduri: punctele consecutive cu același cod
          (if (= *TKT:CODURI* "1")
            (progn
              (foreach p (append pts '((nil . "")))
                (if (and cur (= (cdr p) cod))
                  (setq cur (cons (car p) cur))
                  (progn
                    (if (cdr cur) (progn (TKT:CodeLine (reverse cur) cod) (setq nl (1+ nl))))
                    (setq cur (if (/= (cdr p) "") (list (car p))) cod (cdr p)))))))
          (vl-catch-all-apply 'vla-ZoomExtents (list (vlax-get-acad-object)))
          (TKT:Msg (strcat "S-au importat " (itoa n) " puncte si " (itoa nl) " linii pe coduri din " f)))))))

;;; ==========================================================================
;;;  MODELUL 3D AL TERENULUI (TIN) - triangulație Delaunay
;;; ==========================================================================

;; TKT:Circum - centrul și raza² cercului circumscris triunghiului ABC
(defun TKT:Circum (a b c / ax ay bx by cx cy d ux uy)
  (setq ax (car a) ay (cadr a) bx (car b) by (cadr b) cx (car c) cy (cadr c)
        d (* 2.0 (+ (* ax (- by cy)) (* bx (- cy ay)) (* cx (- ay by)))))
  (if (> (abs d) 1e-12)
    (progn
      (setq ux (/ (+ (* (+ (* ax ax) (* ay ay)) (- by cy)) (* (+ (* bx bx) (* by by)) (- cy ay))
                     (* (+ (* cx cx) (* cy cy)) (- ay by)))
                  d)
            uy (/ (+ (* (+ (* ax ax) (* ay ay)) (- cx bx)) (* (+ (* bx bx) (* by by)) (- ax cx))
                     (* (+ (* cx cx) (* cy cy)) (- bx ax)))
                  d))
      (list ux uy (+ (* (- ax ux) (- ax ux)) (* (- ay uy) (- ay uy)))))
    ;; triunghi degenerat: cerc "infinit", eliminat la punctul următor
    (list (/ (+ ax bx cx) 3.0) (/ (+ ay by cy) 3.0) 1e30)))

;; TKT:Tri - triunghiul (a b c centru-raza²)
(defun TKT:Tri (a b c) (list a b c (TKT:Circum a b c)))

;; TKT:SameEdge - T dacă muchiile E și F sunt aceeași (în orice sens)
(defun TKT:SameEdge (e f)
  (or (and (equal (car e) (car f)) (equal (cadr e) (cadr f)))
      (and (equal (car e) (cadr f)) (equal (cadr e) (car f)))))

;; TKT:Boundary - muchiile care apar o singură dată (conturul cavității)
(defun TKT:Boundary (edges / out)
  (foreach e edges
    (if (= 1 (length (vl-remove-if-not '(lambda (f) (TKT:SameEdge e f)) edges)))
      (setq out (cons e out))))
  out)

;; TKT:Delaunay - triangulația Delaunay (Bowyer-Watson cu baleiere după X) a
;; punctelor PTS (x y z), fără duplicate. Returnează ((a b c) ...).
;; Calculele geometrice folosesc coordonate locale ușor perturbate (micrometri,
;; determinist), ca punctele coliniare (de ex. pe o latură dreaptă) să nu dea
;; triunghiuri degenerate; triunghiurile rezultate au coordonatele originale.
(defun TKT:Delaunay (pts / x0 y0 loc xs ys dm mx my eps i s1 s2 s3 open closed keep edges cc dx out tri)
  (setq x0 (apply 'min (mapcar 'car pts)) y0 (apply 'min (mapcar 'cadr pts))
        xs (mapcar 'car pts) ys (mapcar 'cadr pts)
        dm (max 1.0 (- (apply 'max xs) (apply 'min xs)) (- (apply 'max ys) (apply 'min ys)))
        eps (* 1e-7 dm) i 0
        ;; punct local: (x y z x-original y-original)
        loc (vl-sort (mapcar '(lambda (p)
                                (setq i (1+ i))
                                (list (+ (- (car p) x0) (* eps (sin (* 1.7 i)))) (+ (- (cadr p) y0) (* eps (cos (* 2.3 i))))
                                      (caddr p) (- (car p) x0) (- (cadr p) y0)))
                             pts)
                     '(lambda (a b) (< (car a) (car b))))
        xs (mapcar 'car loc) ys (mapcar 'cadr loc)
        mx (/ (+ (apply 'max xs) (apply 'min xs)) 2.0) my (/ (+ (apply 'max ys) (apply 'min ys)) 2.0)
        ;; vârfurile triunghiului inițial sunt marcate cu "S"
        s1 (list (- mx (* 20.0 dm)) (- my dm) 0.0 0.0 0.0 "S") s2 (list mx (+ my (* 20.0 dm)) 0.0 0.0 0.0 "S")
        s3 (list (+ mx (* 20.0 dm)) (- my dm) 0.0 0.0 0.0 "S")
        open (list (TKT:Tri s1 s2 s3)))
  (foreach p loc
    (setq keep nil edges nil)
    (foreach t1 open
      (setq cc (nth 3 t1) dx (- (car p) (car cc)))
      (cond
        ;; cercul este complet la stânga punctului: triunghiul este definitiv
        ((and (> dx 0.0) (> (* dx dx) (caddr cc))) (setq closed (cons t1 closed)))
        ((< (+ (* dx dx) (expt (- (cadr p) (cadr cc)) 2)) (caddr cc))
         (setq edges (append (list (list (car t1) (cadr t1)) (list (cadr t1) (caddr t1)) (list (caddr t1) (car t1)))
                             edges)))
        (T (setq keep (cons t1 keep)))))
    (foreach e (TKT:Boundary edges) (setq keep (cons (TKT:Tri (car e) (cadr e) p) keep)))
    (setq open keep))
  (foreach t1 (append open closed)
    (if (not (or (nth 5 (car t1)) (nth 5 (cadr t1)) (nth 5 (caddr t1))))
      (progn
        (setq tri (mapcar '(lambda (v) (list (+ (nth 3 v) x0) (+ (nth 4 v) y0) (caddr v)))
                          (list (car t1) (cadr t1) (caddr t1))))
        ;; triunghiurile de arie nulă (puncte coliniare pe contur) se omit
        (if (> (abs (TKT:Area2 tri)) (* 1e-9 dm dm)) (setq out (cons tri out))))))
  out)

;; TKT:Densify - punctele segmentului AB la cel mult D unul de altul (fără A)
(defun TKT:Densify (a b d / n i out)
  (setq n (max 1 (fix (+ 0.999 (/ (distance (TK:2d a) (TK:2d b)) d)))) i 1)
  (repeat n
    (setq out (cons (mapcar '(lambda (u v) (+ u (* (/ (float i) n) (- v u)))) a b) out) i (1+ i)))
  (reverse out))

;; TKT:TinInput - punctele 3D ale selecției: punctele (POINT, INSERT) și
;; vârfurile liniilor de frângere (LINE, polilinii), densificate pe linii
(defun TKT:TinInput (ss / i e ed typ v pts brk bb d)
  (setq i 0)
  (repeat (sslength ss)
    (setq e (ssname ss i) i (1+ i) ed (entget e) typ (cdr (assoc 0 ed)))
    (cond
      ((member typ '("POINT" "INSERT")) (setq pts (cons (cdr (assoc 10 ed)) pts)))
      ((= typ "LINE") (setq brk (cons (list (cdr (assoc 10 ed)) (cdr (assoc 11 ed))) brk)))
      (T (setq brk (cons (TKT:Verts e) brk)))))
  ;; densificarea liniilor de frângere (pasul: 1/100 din extinderea datelor, 0,5-5 m)
  (setq v (append pts (apply 'append brk))
        bb (list (apply 'min (mapcar 'car v)) (apply 'min (mapcar 'cadr v))
                 (apply 'max (mapcar 'car v)) (apply 'max (mapcar 'cadr v)))
        d (max 0.5 (min 5.0 (/ (distance (list (car bb) (cadr bb)) (list (caddr bb) (cadddr bb))) 100.0))))
  (foreach l brk
    (setq pts (cons (car l) pts))
    (mapcar '(lambda (a b) (setq pts (append (TKT:Densify a b d) pts))) l (cdr l)))
  ;; duplicatele (aceeași poziție în plan, la 1 mm) se elimină
  (setq v nil)
  (foreach p (vl-sort pts '(lambda (a b) (if (equal (car a) (car b) 1e-9) (< (cadr a) (cadr b)) (< (car a) (car b)))))
    (if (not (and v (< (distance (TK:2d p) (TK:2d (car v))) 0.001))) (setq v (cons p v))))
  v)

;; TKT:MakeTin - comanda TIN: triangulația punctelor selectate, cu filtrul
;; laturii maxime și conturul opțional al modelului
(defun TKT:MakeTin (/ ss pts tris es bnd n)
  (princ "\nSelectati punctele 3D si liniile de franger (POINT, INSERT, LINE, polilinii): ")
  (if (setq ss (ssget '((0 . "POINT,INSERT,LINE,LWPOLYLINE,POLYLINE"))))
    (progn
      (setq pts (TKT:TinInput ss))
      (if (< (length pts) 3)
        (TKT:Msg "Sunt necesare cel putin 3 puncte.")
        (progn
          (setq es (entsel "\nSelectati conturul modelului (polilinie inchisa) <Enter = fara contur>: "))
          (if (and es (wcmatch (cdr (assoc 0 (entget (car es)))) "*POLYLINE")) (setq bnd (TKT:Verts (car es))))
          (TKT:Msg (strcat "Triangulatie pentru " (itoa (length pts)) " puncte..."))
          (setq tris (TKT:Delaunay pts) n 0)
          (foreach t1 tris
            (if (and (or (<= *TKT:LMAX* 0.0)
                         (vl-every '(lambda (a b) (<= (distance (TK:2d a) (TK:2d b)) *TKT:LMAX*))
                                   t1 (list (cadr t1) (caddr t1) (car t1))))
                     (or (null bnd)
                         (TKT:Inside (mapcar '(lambda (u v w) (/ (+ u v w) 3.0)) (car t1) (cadr t1) (caddr t1)) bnd)))
              (progn
                (entmake (list '(0 . "3DFACE") '(8 . "TIN") (cons 10 (car t1)) (cons 11 (cadr t1))
                               (cons 12 (caddr t1)) (cons 13 (caddr t1))))
                (setq n (1+ n)))))
          (TKT:Msg (strcat "Modelul TIN are " (itoa n) " triunghiuri (stratul TIN)."))
          n)))))

;; TKT:Faces - triunghiurile entităților 3DFACE din selecție (patrulaterele în două)
(defun TKT:Faces (ss / i ed a b c d out)
  (setq i 0)
  (if ss
    (repeat (sslength ss)
      (setq ed (entget (ssname ss i)) i (1+ i)
            a (cdr (assoc 10 ed)) b (cdr (assoc 11 ed)) c (cdr (assoc 12 ed)) d (cdr (assoc 13 ed)))
      (setq out (cons (list a b c) out))
      (if (and d (not (equal c d 1e-9)) (not (equal a d 1e-9))) (setq out (cons (list a c d) out)))))
  out)

;; TKT:SelTin - selecția unui TIN (3DFACE)
(defun TKT:SelTin (msg / ss)
  (princ msg)
  (if (setq ss (ssget '((0 . "3DFACE")))) (TKT:Faces ss)))

;;; ==========================================================================
;;;  CURBE DE NIVEL (CURBE)
;;; ==========================================================================

;; TKT:Zh - cota fără egalitate cu nivelul H (vârfurile de pe curbă se ridică
;; foarte puțin, la fel în toate triunghiurile - curbe continue)
(defun TKT:Zh (z h) (if (equal z h 1e-7) (+ h 1e-6) z))

;; TKT:Cross - punctul de cotă H pe muchia UV (calculat în ordinea canonică a
;; capetelor, deci identic în cele două triunghiuri vecine)
(defun TKT:Cross (u v h / t1 zu zv)
  (if (or (< (car v) (car u)) (and (= (car v) (car u)) (< (cadr v) (cadr u)))) (setq t1 u u v v t1))
  (setq zu (TKT:Zh (caddr u) h) zv (TKT:Zh (caddr v) h))
  (if (< (* (- zu h) (- zv h)) 0.0)
    (mapcar '(lambda (a b) (+ a (* (/ (- h zu) (- zv zu)) (- b a)))) (TK:2d u) (TK:2d v))))

;; TKT:Key - cheia unui punct (pentru unirea segmentelor)
(defun TKT:Key (p) (strcat (rtos (car p) 2 6) "," (rtos (cadr p) 2 6)))

;; TKT:Segments - segmentele curbei de nivel H: ((cheie1 p1 cheie2 p2) ...)
(defun TKT:Segments (tris h / out ps)
  (foreach t1 tris
    (if (and (<= (apply 'min (mapcar 'caddr t1)) (+ h 1e-6)) (>= (apply 'max (mapcar 'caddr t1)) (- h 1e-6)))
      (progn
        (setq ps (vl-remove nil (list (TKT:Cross (car t1) (cadr t1) h) (TKT:Cross (cadr t1) (caddr t1) h)
                                      (TKT:Cross (caddr t1) (car t1) h))))
        (if (= (length ps) 2)
          (setq out (cons (list (TKT:Key (car ps)) (car ps) (TKT:Key (cadr ps)) (cadr ps)) out))))))
  out)

;; TKT:Chain - unește segmentele în polilinii: ((închisă? p1 p2 ...) ...)
(defun TKT:Chain (segs / out line head tail found s rest)
  (while segs
    (setq s (car segs) segs (cdr segs)
          line (list (cadr s) (cadddr s)) head (car s) tail (caddr s) found T)
    (while (and found segs)
      (setq found nil rest nil)
      (foreach x segs
        (cond
          (found (setq rest (cons x rest)))
          ((= (car x) tail) (setq line (append line (list (cadddr x))) tail (caddr x) found T))
          ((= (caddr x) tail) (setq line (append line (list (cadr x))) tail (car x) found T))
          ((= (car x) head) (setq line (cons (cadddr x) line) head (caddr x) found T))
          ((= (caddr x) head) (setq line (cons (cadr x) line) head (car x) found T))
          (T (setq rest (cons x rest)))))
      (setq segs (reverse rest)))
    (setq out (cons (if (= head tail) (cons T (cdr line)) (cons nil line)) out)))
  out)

;; TKT:Contours - comanda CURBE: curbele de nivel ale TIN-ului selectat
(defun TKT:Contours (tris / zmin zmax h n k lay lines nc dec longest a b)
  (setq zmin (apply 'min (mapcar '(lambda (t1) (apply 'min (mapcar 'caddr t1))) tris))
        zmax (apply 'max (mapcar '(lambda (t1) (apply 'max (mapcar 'caddr t1))) tris))
        k (TKT:Ceil (- (/ zmin *TKT:ECHID*) 1e-9)) nc 0
        dec (if (< *TKT:ECHID* 1.0) 2 (if (equal *TKT:ECHID* (fix *TKT:ECHID*) 1e-9) 0 1)))
  (while (<= (setq h (* k *TKT:ECHID*)) zmax)
    (setq lay (if (= 0 (rem k (max 1 *TKT:PRINC*))) "CURBE_PRINC" "CURBE_SEC"))
    (foreach l (TKT:Chain (TKT:Segments tris h))
      (if (cddr l)
        (progn
          (entmake (append (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") (cons 8 lay) '(100 . "AcDbPolyline")
                                 (cons 90 (length (cdr l))) (cons 70 (if (car l) 1 0)) (cons 38 h))
                           (mapcar '(lambda (p) (list 10 (car p) (cadr p))) (cdr l))))
          (setq nc (1+ nc))
          ;; cota pe curbele principale, pe segmentul cel mai lung
          (if (= lay "CURBE_PRINC")
            (progn
              (setq longest 0.0)
              (mapcar '(lambda (p q) (if (> (distance p q) longest) (setq longest (distance p q) a p b q)))
                      (cdr l) (cddr l))
              (TKT:Txt (TKT:Fmt h dec) (TK:Mid a b) (* 0.8 (TKT:H)) (TKT:Readable (angle a b)) "MC" "CURBE_COTE"))))))
    (setq k (1+ k)))
  (TKT:Msg (strcat "S-au generat " (itoa nc) " curbe de nivel intre cotele " (TKT:Fmt zmin 2) " si "
                   (TKT:Fmt zmax 2) " (echidistanta " (TKT:Fmt *TKT:ECHID* 2) " m)."))
  nc)

;;; ==========================================================================
;;;  VOLUME (VOLUM, VOLUM2)
;;; ==========================================================================

;; TKT:ClipPos - partea poligonului (puncte cu diferența de cotă DZ) unde DZ >= 0
(defun TKT:ClipPos (poly / out)
  (mapcar '(lambda (p q)
             (if (>= (cadr p) 0.0) (setq out (cons p out)))
             (if (< (* (cadr p) (cadr q)) 0.0)
               (setq out (cons (list (mapcar '(lambda (u v) (+ u (* (/ (cadr p) (- (cadr p) (cadr q))) (- v u))))
                                             (car p) (car q))
                                     0.0)
                               out))))
          poly (append (cdr poly) (list (car poly))))
  (reverse out))

;; TKT:PrismVol - volumul de deasupra planului DZ = 0 pe poligonul convex POLY
;; (aria fiecărui triunghi al evantaiului x media diferențelor - exact pentru o față plană)
(defun TKT:PrismVol (poly / v a)
  (setq v 0.0 a 0.0)
  (if (cddr poly)
    (mapcar '(lambda (p q)
               (setq a (+ a (abs (TKT:Area2 (list (car (car poly)) (car p) (car q)))))
                     v (+ v (* (abs (TKT:Area2 (list (car (car poly)) (car p) (car q))))
                               (/ (+ (cadr (car poly)) (cadr p) (cadr q)) 3.0)))))
            (cdr poly) (cddr poly)))
  (list v a))

;; TKT:VolPlane - volumele TIN-ului față de planul de cotă H:
;; (săpătură umplutură aria-săpătură aria-umplutură aria-totală).
;; Săpătură = terenul deasupra planului, umplutură = terenul sub plan.
(defun TKT:VolPlane (tris h / cut fill ac af poly r)
  (setq cut 0.0 fill 0.0 ac 0.0 af 0.0)
  (foreach t1 tris
    (setq poly (mapcar '(lambda (p) (list (TK:2d p) (- (caddr p) h))) t1))
    (setq r (TKT:PrismVol (TKT:ClipPos poly)) cut (+ cut (car r)) ac (+ ac (cadr r)))
    (setq r (TKT:PrismVol (TKT:ClipPos (mapcar '(lambda (x) (list (car x) (- (cadr x)))) poly)))
          fill (+ fill (car r)) af (+ af (cadr r))))
  (list cut fill ac af (apply '+ (mapcar '(lambda (t1) (abs (TKT:Area2 t1))) tris))))

;; TKT:Plane - planul z = a x + b y + d al triunghiului (nil dacă este vertical)
(defun TKT:Plane (p q r / u v nx ny nz)
  (setq u (mapcar '- q p) v (mapcar '- r p)
        nx (- (* (cadr u) (caddr v)) (* (caddr u) (cadr v)))
        ny (- (* (caddr u) (car v)) (* (car u) (caddr v)))
        nz (- (* (car u) (cadr v)) (* (cadr u) (car v))))
  (if (> (abs nz) 1e-12)
    (list (/ (- nx) nz) (/ (- ny) nz)
          (+ (caddr p) (* (/ nx nz) (car p)) (* (/ ny nz) (cadr p))))))

;; TKT:Raster - cotele TIN-ului în centrele celulelor grilei (origine X0 Y0,
;; pas C): ((cheie z) ...) ordonate după cheie
(defun TKT:Raster (tris x0 y0 c / out pl ymin ymax iy iy1 yc xs xl xr ix ix1 a b)
  (foreach t1 tris
    (if (setq pl (TKT:Plane (car t1) (cadr t1) (caddr t1)))
      (progn
        (setq ymin (apply 'min (mapcar 'cadr t1)) ymax (apply 'max (mapcar 'cadr t1))
              iy (TKT:Ceil (- (/ (- ymin y0) c) 0.5)) iy1 (TKT:Floor (- (/ (- ymax y0) c) 0.5)))
        (while (<= iy iy1)
          (setq yc (+ y0 (* (+ iy 0.5) c)) xs nil)
          (mapcar '(lambda (a b)
                     (if (and (/= (cadr a) (cadr b)) (<= (min (cadr a) (cadr b)) yc) (<= yc (max (cadr a) (cadr b))))
                       (setq xs (cons (+ (car a) (* (/ (- yc (cadr a)) (- (cadr b) (cadr a))) (- (car b) (car a)))) xs))))
                  t1 (list (cadr t1) (caddr t1) (car t1)))
          (if xs
            (progn
              (setq xl (apply 'min xs) xr (apply 'max xs)
                    ix (TKT:Ceil (- (/ (- xl x0) c) 0.5)) ix1 (TKT:Floor (- (/ (- xr x0) c) 0.5)))
              (while (<= ix ix1)
                (setq out (cons (list (+ (* ix 1000000.0) iy)
                                      (+ (* (car pl) (+ x0 (* (+ ix 0.5) c))) (* (cadr pl) yc) (caddr pl)))
                                out)
                      ix (1+ ix)))))
          (setq iy (1+ iy))))))
  (vl-sort out '(lambda (a b) (< (car a) (car b)))))

;; TKT:VolTins - volumele dintre TIN-ul existent T1 și proiectul T2 (grilă de
;; pas C): (săpătură umplutură aria-comună). Umplutură = proiectul deasupra terenului.
(defun TKT:VolTins (t1 t2 c / all x0 y0 r1 r2 cut fill n d)
  (setq all (apply 'append (append t1 t2))
        x0 (apply 'min (mapcar 'car all)) y0 (apply 'min (mapcar 'cadr all))
        r1 (TKT:Raster t1 x0 y0 c) r2 (TKT:Raster t2 x0 y0 c) cut 0.0 fill 0.0 n 0)
  (while (and r1 r2)
    (cond
      ((< (caar r1) (caar r2)) (setq r1 (cdr r1)))
      ((> (caar r1) (caar r2)) (setq r2 (cdr r2)))
      (T
       (setq d (- (cadar r2) (cadar r1)) n (1+ n))
       (if (> d 0) (setq fill (+ fill (* d c c))) (setq cut (- cut (* d c c))))
       ;; celulele din centru aflate pe o muchie comună apar de două ori
       (while (and (cdr r1) (= (caadr r1) (caar r1))) (setq r1 (cdr r1)))
       (while (and (cdr r2) (= (caadr r2) (caar r2))) (setq r2 (cdr r2)))
       (setq r1 (cdr r1) r2 (cdr r2)))))
  (list cut fill (* n c c)))

;; TKT:VolTable - tabelul volumelor la punctul P (rândurile ROWS = (text valoare))
(defun TKT:VolTable (p title rows / h y w1 w2)
  (setq h (TKT:H) w1 (* 45.0 (TKT:K)) w2 (* 28.0 (TKT:K)) y (cadr p))
  (TKT:Txt title (list (+ (car p) (/ (+ w1 w2) 2.0)) (+ y (* 1.2 h))) (* 1.2 h) 0.0 "C" "VOLUME")
  (foreach r rows
    (TKT:Ln (list (car p) y) (list (+ (car p) w1 w2) y) "VOLUME")
    (TKT:Txt (car r) (list (+ (car p) (* 0.8 h)) (- y (* 1.4 h))) h 0.0 "ML" "VOLUME")
    (TKT:Txt (cadr r) (list (+ (car p) w1 w2 (* -0.8 h)) (- y (* 1.4 h))) h 0.0 "MR" "VOLUME")
    (setq y (- y (* 2.8 h))))
  (TKT:Ln (list (car p) y) (list (+ (car p) w1 w2) y) "VOLUME")
  (TKT:Ln (list (car p) (cadr p)) (list (car p) y) "VOLUME")
  (TKT:Ln (list (+ (car p) w1) (cadr p)) (list (+ (car p) w1) y) "VOLUME")
  (TKT:Ln (list (+ (car p) w1 w2) (cadr p)) (list (+ (car p) w1 w2) y) "VOLUME"))

;; TKT:VolReport - afișează volumele și, la cerere, tabelul în desen
(defun TKT:VolReport (title rows / p)
  (TKT:Msg title)
  (foreach r rows (TKT:Msg (strcat "  " (car r) ": " (cadr r))))
  (if (setq p (getpoint "\nPunctul pentru tabelul volumelor <Enter = fara tabel>: "))
    (TKT:VolTable p title rows)))

;; TKT:CmdVolPlane - comanda VOLUM
(defun TKT:CmdVolPlane (ask / tris h r)
  (if (setq tris (TKT:SelTin "\nSelectati triunghiurile TIN (3DFACE): "))
    (progn
      (setq h (if ask (getreal (strcat "\nCota planului de referinta <" (TKT:Fmt *TKT:COTAREF* 2) ">: "))))
      (if h (setq *TKT:COTAREF* h))
      (setq r (TKT:VolPlane tris *TKT:COTAREF*))
      (TKT:VolReport (strcat "Volume fata de cota " (TKT:Fmt *TKT:COTAREF* 2))
                     (list (list "Sapatura (mc)" (TKT:Fmt (car r) 2)) (list "Umplutura (mc)" (TKT:Fmt (cadr r) 2))
                           (list "Arie sapatura (mp)" (TKT:Fmt (caddr r) 2)) (list "Arie umplutura (mp)" (TKT:Fmt (cadddr r) 2))
                           (list "Arie totala (mp)" (TKT:Fmt (nth 4 r) 2))))
      r)))

;; TKT:CmdVolTins - comanda VOLUM2
(defun TKT:CmdVolTins (/ t1 t2 r)
  (if (and (setq t1 (TKT:SelTin "\nSelectati TIN-ul terenului existent (3DFACE): "))
           (setq t2 (TKT:SelTin "\nSelectati TIN-ul proiectat (3DFACE): ")))
    (progn
      (setq r (TKT:VolTins t1 t2 *TKT:CELULA*))
      (TKT:VolReport (strcat "Volume teren existent - proiect (grila " (TKT:Fmt *TKT:CELULA* 2) " m)")
                     (list (list "Sapatura (mc)" (TKT:Fmt (car r) 2)) (list "Umplutura (mc)" (TKT:Fmt (cadr r) 2))
                           (list "Arie comuna (mp)" (TKT:Fmt (caddr r) 2))))
      r)))

;;; ==========================================================================
;;;  TABEL DE COORDONATE (TABPCT) ȘI LEGENDĂ (LEGENDA)
;;; ==========================================================================

;; TKT:NumTexts - textele întregi din model: ((punct număr) ...)
(defun TKT:NumTexts (/ ss i ed s out)
  (if (setq ss (ssget "_X" '((0 . "TEXT") (410 . "Model"))))
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ed (entget (ssname ss i)) i (1+ i) s (vl-string-trim " " (cdr (assoc 1 ed))))
        (if (and (> (strlen s) 0) (vl-every '(lambda (c) (<= 48 c 57)) (vl-string->list s)))
          (setq out (cons (list (TK:2d (cdr (assoc 10 ed))) s) out))))))
  out)

;; TKT:AttNum - primul atribut numeric al unui bloc (sau nil)
(defun TKT:AttNum (e / a ad v r)
  (setq a (entnext e))
  (while (and a (null r) (= (cdr (assoc 0 (setq ad (entget a)))) "ATTRIB"))
    (setq v (vl-string-trim " " (cdr (assoc 1 ad))))
    (if (and (> (strlen v) 0) (vl-every '(lambda (c) (<= 48 c 57)) (vl-string->list v))) (setq r v))
    (setq a (entnext a)))
  r)

;; TKT:PointRows - punctele selectate cu numerele lor: ((nr E N Z) ...), după număr
(defun TKT:PointRows (ss / nums i e ed p nr best bd d rows k en)
  (setq nums (TKT:NumTexts) i 0 k 0)
  (repeat (sslength ss)
    (setq e (ssname ss i) i (1+ i) ed (entget e) p (cdr (assoc 10 ed)) nr nil)
    (if (= (cdr (assoc 0 ed)) "INSERT") (setq nr (TKT:AttNum e)))
    (if (null nr)
      (progn
        (setq best nil bd (* 3.0 (TKT:H)))
        (foreach x nums (if (< (setq d (distance (TK:2d p) (car x))) bd) (setq bd d best (cadr x))))
        (setq nr best)))
    (setq en (TK:PtEN p) rows (cons (list (if nr nr (strcat "?" (itoa (setq k (1+ k))))) (car en) (cadr en) (caddr p)) rows)))
  (vl-sort rows '(lambda (a b) (< (atoi (vl-string-left-trim "?" (car a))) (atoi (vl-string-left-trim "?" (car b)))))))

;; TKT:CoordTable - tabelul coordonatelor la punctul P, pe coloane de 40 de rânduri
(defun TKT:CoordTable (rows p / h k ws wt rowh hasz x y n cols)
  (setq h (TKT:H) k (TKT:K) hasz (vl-some '(lambda (r) (not (equal (nth 3 r) 0.0 1e-9))) rows)
        ws (if hasz (list (* 14 k) (* 28 k) (* 28 k) (* 20 k)) (list (* 14 k) (* 28 k) (* 28 k)))
        wt (apply '+ ws) rowh (* 5.0 k) x (car p))
  (while rows
    (setq cols (TKT:Firstn 40 rows) rows (TKT:Nthcdr 40 rows) y (cadr p))
    (TKT:Txt "Inventar de coordonate - Stereo 70" (list (+ x (/ wt 2.0)) (+ y (* 1.2 h))) h 0.0 "C" "TABEL_PCT")
    (setq n 0)
    (foreach r (cons (append '("Nr." "X [m]" "Y [m]") (if hasz '("Z [m]"))) cols)
      (TKT:Ln (list x y) (list (+ x wt) y) "TABEL_PCT")
      (TKT:RowTexts x (- y (/ rowh 2.0)) ws
                    (if (= n 0) r
                      (append (list (car r) (TKT:Fmt (caddr r) 3) (TKT:Fmt (cadr r) 3)) (if hasz (list (TKT:Fmt (cadddr r) 3))))))
      (setq y (- y rowh) n (1+ n)))
    (TKT:Ln (list x y) (list (+ x wt) y) "TABEL_PCT")
    (TKT:ColLines x (cadr p) y ws)
    (setq x (+ x wt (* 5.0 k)))))

;; TKT:RowTexts - textele unui rând, centrate în celule
(defun TKT:RowTexts (x y ws txts)
  (mapcar '(lambda (w s) (TKT:Txt s (list (+ x (/ w 2.0)) y) (TKT:H) 0.0 "MC" "TABEL_PCT") (setq x (+ x w))) ws txts))

;; TKT:ColLines - liniile verticale ale tabelului
(defun TKT:ColLines (x ytop ybot ws)
  (TKT:Ln (list x ytop) (list x ybot) "TABEL_PCT")
  (foreach w ws (setq x (+ x w)) (TKT:Ln (list x ytop) (list x ybot) "TABEL_PCT")))

;; TKT:Firstn / TKT:Nthcdr
(defun TKT:Firstn (k l / out) (repeat (min k (length l)) (setq out (cons (car l) out) l (cdr l))) (reverse out))
(defun TKT:Nthcdr (k l) (repeat k (setq l (cdr l))) l)

;; TKT:CmdTable - comanda TABPCT
(defun TKT:CmdTable (/ ss rows p)
  (princ "\nSelectati punctele (POINT sau blocuri de punct): ")
  (if (and (setq ss (ssget '((0 . "POINT,INSERT"))))
           (setq rows (TKT:PointRows ss))
           (setq p (getpoint "\nColtul stanga-sus al tabelului: ")))
    (progn (TKT:CoordTable rows p) (TKT:Msg (strcat "Tabel cu " (itoa (length rows)) " puncte.")) rows)))

;; TKT:Count - lista de asociere (nume . număr de apariții)
(defun TKT:Count (names / out p)
  (foreach n names
    (if (setq p (assoc n out)) (setq out (subst (cons n (1+ (cdr p))) p out)) (setq out (cons (cons n 1) out))))
  (vl-sort out '(lambda (a b) (< (car a) (car b)))))

;; TKT:LegendItems - blocurile și straturile cu linii din model: (("B" nume nr) ("L" strat nr) ...)
(defun TKT:LegendItems (/ ss i ed n blks lays)
  (if (setq ss (ssget "_X" '((0 . "INSERT") (410 . "Model"))))
    (progn (setq i 0)
      (repeat (sslength ss)
        (setq n (cdr (assoc 2 (entget (ssname ss i)))) i (1+ i))
        (if (/= (substr n 1 1) "*") (setq blks (cons n blks))))))     ; fără blocurile anonime
  (if (setq ss (ssget "_X" '((0 . "LINE,LWPOLYLINE,POLYLINE,ARC") (410 . "Model"))))
    (progn (setq i 0)
      (repeat (sslength ss)
        (setq n (cdr (assoc 8 (entget (ssname ss i)))) i (1+ i))
        (if (not (wcmatch (strcase n) "0,DEFPOINTS,TIN,CURBE_*,PAD_*,L_CADRU,LEGENDA,TABEL_PCT,VOLUME,KML"))
          (setq lays (cons n lays))))))
  (append (mapcar '(lambda (x) (list "B" (car x) (cdr x))) (TKT:Count blks))
          (mapcar '(lambda (x) (list "L" (car x) (cdr x))) (TKT:Count lays))))

;; TKT:BlockDesc - descrierea blocului (din definiția lui) sau numele
(defun TKT:BlockDesc (n / d)
  (setq d (cdr (assoc 4 (tblsearch "BLOCK" n))))
  (if (and d (/= d "")) d n))

;; TKT:FitBlock - inserează blocul N la punctul P, scalat în caseta W x H
(defun TKT:FitBlock (n p w h / e o mn mx s r)
  (entmake (list '(0 . "INSERT") '(8 . "LEGENDA") (cons 2 n) (list 10 (car p) (cadr p) 0.0)))
  (setq e (entlast) o (vlax-ename->vla-object e)
        r (vl-catch-all-apply 'vla-GetBoundingBox (list o 'mn 'mx)))
  (if (not (vl-catch-all-error-p r))
    (progn
      (setq mn (vlax-safearray->list mn) mx (vlax-safearray->list mx)
            s (min (/ w (max 1e-6 (- (car mx) (car mn)))) (/ h (max 1e-6 (- (cadr mx) (cadr mn))))))
      (vl-catch-all-apply 'vla-put-XScaleFactor (list o s))
      (vl-catch-all-apply 'vla-put-YScaleFactor (list o s))
      (vl-catch-all-apply 'vla-put-ZScaleFactor (list o s))
      ;; centrarea blocului în casetă
      (setq r (vl-catch-all-apply 'vla-GetBoundingBox (list o 'mn 'mx)))
      (if (not (vl-catch-all-error-p r))
        (progn
          (setq mn (vlax-safearray->list mn) mx (vlax-safearray->list mx))
          (vl-catch-all-apply 'vla-Move (list o (vlax-3d-point (TK:Mid (TK:2d mn) (TK:2d mx))) (vlax-3d-point p)))))))
  e)

;; TKT:Legend - comanda LEGENDA: tabelul semnelor convenționale la punctul P
(defun TKT:Legend (items p / k h w1 w2 rowh x y)
  (setq k (TKT:K) h (TKT:H) w1 (* 22 k) w2 (* 62 k) rowh (* 9.0 k) x (car p) y (cadr p))
  (TKT:Txt "LEGEND\\U+0102" (list (+ x (/ (+ w1 w2) 2.0)) (+ y (* 1.5 h))) (* 1.5 h) 0.0 "C" "LEGENDA")
  (foreach it items
    (TKT:Ln (list x y) (list (+ x w1 w2) y) "LEGENDA")
    (if (= (car it) "B")
      (TKT:FitBlock (cadr it) (list (+ x (/ w1 2.0)) (- y (/ rowh 2.0))) (* 0.7 w1) (* 0.7 rowh))
      (entmake (list '(0 . "LINE") (cons 8 (cadr it)) (list 10 (+ x (* 0.15 w1)) (- y (/ rowh 2.0)) 0.0)
                     (list 11 (+ x (* 0.85 w1)) (- y (/ rowh 2.0)) 0.0))))
    (TKT:Txt (strcat (if (= (car it) "B") (TKT:BlockDesc (cadr it)) (cadr it)) " (" (itoa (caddr it)) ")")
             (list (+ x w1 (* 0.8 h)) (- y (/ rowh 2.0))) h 0.0 "ML" "LEGENDA")
    (setq y (- y rowh)))
  (TKT:Ln (list x y) (list (+ x w1 w2) y) "LEGENDA")
  (TKT:ColLines x (cadr p) y (list w1 w2))
  (length items))

;; TKT:CmdLegend - comanda LEGENDA
(defun TKT:CmdLegend (/ items p)
  (cond
    ((null (setq items (TKT:LegendItems))) (TKT:Msg "Desenul nu are blocuri sau linii pentru legenda."))
    ((setq p (getpoint "\nColtul stanga-sus al legendei: "))
     (TKT:Legend items p)
     (TKT:Msg (strcat "Legenda cu " (itoa (length items)) " semne conventionale.")))))

;;; ==========================================================================
;;;  RASTER GEOREFERENȚIAT, KML/KMZ, HARTĂ ONLINE
;;; ==========================================================================

;; TKT:WorldFile - fișierul world al imaginii F (.jgw, .jpgw, .tfw, .pgw, .wld...)
(defun TKT:WorldFile (f / base ext)
  (setq base (strcat (vl-filename-directory f) "\\" (vl-filename-base f))
        ext (strcase (substr (vl-filename-extension f) 2) T))
  (vl-some '(lambda (x) (findfile (strcat base "." x)))
           (list (strcat (substr ext 1 1) (substr ext (strlen ext) 1) "w") (strcat ext "w") "wld")))

;; TKT:ReadWorld - cei 6 parametri ai fișierului world (A D B E C F)
(defun TKT:ReadWorld (f / fh l out)
  (if (setq fh (open f "r"))
    (progn
      (while (and (setq l (read-line fh)) (< (length out) 6))
        (if (distof (vl-string-trim " \t" l) 2) (setq out (cons (distof (vl-string-trim " \t" l) 2) out))))
      (close fh)))
  (if (= (length out) 6) (reverse out)))

;; TKT:Georef - comanda GEOREF: inserează imaginea la poziția din fișierul world
(defun TKT:Georef (/ f wf w img px py res rot ll)
  (cond
    ((null (setq f (getfiled "Imaginea raster georeferentiata" (getvar "DWGPREFIX") "jpg;jpeg;png;tif;tiff;bmp" 0))) nil)
    ((or (null (setq wf (TKT:WorldFile f))) (null (setq w (TKT:ReadWorld wf))))
     (TKT:Msg "Nu am gasit fisierul world al imaginii (.jgw, .tfw, .pgw, .wld) langa imagine."))
    (T
     (setq img (vl-catch-all-apply 'vla-AddRaster
                 (list (vla-get-ModelSpace *TK:DOC*) f (vlax-3d-point 0.0 0.0 0.0) 1.0 0.0)))
     (if (vl-catch-all-error-p img)
       (TKT:Msg (strcat "Imaginea nu a putut fi inserata: " (vl-catch-all-error-message img)))
       (progn
         ;; dimensiunea în pixeli, mărimea pixelului și rotația
         (setq px (vla-get-Width img) py (vla-get-Height img)
               res (sqrt (+ (* (nth 0 w) (nth 0 w)) (* (nth 1 w) (nth 1 w))))
               rot (atan (nth 1 w) (nth 0 w))
               ;; colțul stânga-jos al imaginii: marginea pixelului (-0,5 ; py - 0,5)
               ll (list (+ (* (nth 0 w) -0.5) (* (nth 2 w) (- py 0.5)) (nth 4 w))
                        (+ (* (nth 1 w) -0.5) (* (nth 3 w) (- py 0.5)) (nth 5 w))))
         (vla-put-ImageWidth img (* px res))
         (vla-put-ImageHeight img (* py res))
         (vla-put-Rotation img rot)
         (vla-put-Origin img (vlax-3d-point (car ll) (cadr ll) 0.0))
         (vl-catch-all-apply 'vla-put-Layer (list img "RASTER"))
         (if (= *TK:SWAPXY* "1") (TKT:Msg "ATENTIE: desenul are axele inversate; imaginea foloseste X = Est."))
         (TKT:Msg (strcat "Imagine " (itoa px) " x " (itoa py) " pixeli, pixel " (TKT:Fmt res 3) " m, coltul S-V "
                          (TKT:Fmt (car ll) 2) ", " (TKT:Fmt (cadr ll) 2) "."))
         img)))))

;; TKT:WgsToS70 - coordonatele Stereo 70 (E N) ale punctului WGS84/ETRS89
;; (LON LAT, grade): inversarea numerică (Newton) a transformării TopoKit
;; Stereo 70 -> WGS84 (grila NTv2 sau Helmert), deci cu aceeași precizie
(defun TKT:WgsToS70 (lon lat / e n f fe fn j11 j12 j21 j22 det de dn i)
  (setq e (+ 500000.0 (* (- lon 25.0) 77400.0)) n (+ 500000.0 (* (- lat 46.0) 111200.0)) i 0 de 1.0 dn 1.0)
  (while (and (< i 10) (> (+ (abs de) (abs dn)) 1e-5))
    (setq f (TK:Stereo70ToWGS84 (list e n))
          fe (TK:Stereo70ToWGS84 (list (+ e 1.0) n))
          fn (TK:Stereo70ToWGS84 (list e (+ n 1.0)))
          j11 (- (car fe) (car f)) j21 (- (cadr fe) (cadr f))
          j12 (- (car fn) (car f)) j22 (- (cadr fn) (cadr f))
          det (- (* j11 j22) (* j12 j21))
          de (/ (- (* (- lon (car f)) j22) (* j12 (- lat (cadr f)))) det)
          dn (/ (- (* j11 (- lat (cadr f))) (* (- lon (car f)) j21)) det)
          e (+ e de) n (+ n dn) i (1+ i)))
  (list e n))

;; TKT:ReadAll - conținutul unui fișier text (rândurile unite cu spații)
(defun TKT:ReadAll (f / fh l out)
  (setq out "")
  (if (setq fh (open f "r"))
    (progn (while (setq l (read-line fh)) (setq out (strcat out l " "))) (close fh)))
  out)

;; TKT:Tag - conținutul primului element <TAG>...</TAG> din S (de la poziția I)
(defun TKT:Tag (s tag / a b)
  (if (and (setq a (vl-string-search (strcat "<" tag ">") s))
           (setq b (vl-string-search (strcat "</" tag ">") s a)))
    (substr s (+ a (strlen tag) 3) (- b a (strlen tag) 2))))

;; TKT:KmlCoords - punctele (lon lat) ale unui șir <coordinates>
(defun TKT:KmlCoords (s / out f)
  (foreach tok (TKT:Words s)
    (setq f (cadr (TKT:Split tok)))
    (if (and (distof (car f) 2) (distof (cadr f) 2)) (setq out (cons (list (distof (car f) 2) (distof (cadr f) 2)) out))))
  (reverse out))

;; TKT:KmlPlacemarks - elementele KML: ((nume ((lon lat) ...)) ...), câte unul pentru
;; fiecare <coordinates> (puncte, linii, poligoane, MultiGeometry)
(defun TKT:KmlPlacemarks (s / i j pm name c out k)
  (setq i 0)
  (while (setq i (vl-string-search "<Placemark" s i))
    (setq j (cond ((vl-string-search "</Placemark>" s i)) ((strlen s)))
          pm (substr s (1+ i) (- j i))
          name (cond ((TKT:Tag pm "name")) ("")) k 0)
    (if (= 0 (vl-string-search "<![CDATA[" name)) (setq name (substr name 10 (- (strlen name) 12))))
    (while (setq k (vl-string-search "<coordinates>" pm k))
      (setq c (TKT:Tag (substr pm (1+ k)) "coordinates") k (1+ k))
      (if c (setq out (cons (list (vl-string-trim " " name) (TKT:KmlCoords c)) out))))
    (setq i j))
  (reverse out))

;; TKT:KmzToKml - extrage doc.kml din arhiva KMZ (PowerShell) și îl returnează
(defun TKT:KmzToKml (f / dir lst)
  (setq dir (strcat (TK:TempDir) "TopoKit_kmz_" (TK:Stamp)))
  (TK:Run (strcat "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \"Expand-Archive -LiteralPath '"
                  f "' -DestinationPath '" dir "' -Force\"")
          T)
  (cond ((findfile (strcat dir "\\doc.kml")))
        ((setq lst (vl-directory-files dir "*.kml" 1)) (strcat dir "\\" (car lst)))))

;; TKT:ImportKml - comanda IMPKML
(defun TKT:ImportKml (/ f kml items pts n np p meth)
  (if (setq f (getfiled "Fisier Google Earth (KML/KMZ)" (getvar "DWGPREFIX") "kml;kmz" 0))
    (progn
      (setq kml (if (= (strcase (vl-filename-extension f)) ".KMZ") (TKT:KmzToKml f) f) n 0 np 0)
      (if (null kml)
        (TKT:Msg "Arhiva KMZ nu contine un fisier KML.")
        (progn
          (if (= *TK:USEGRID* "1") (TK:GridOpen))
          (setq *TK:NHELM* 0 items (TKT:KmlPlacemarks (TKT:ReadAll kml)))
          (foreach it items
            (setq pts (mapcar '(lambda (ll / en) (setq en (TKT:WgsToS70 (car ll) (cadr ll))) (TKT:ToDwg (car en) (cadr en) 0.0))
                              (cadr it)))
            (cond
              ((null pts))
              ((null (cdr pts))
               (entmake (list '(0 . "POINT") '(8 . "KML") (cons 10 (car pts)))) (setq np (1+ np)))
              (T
               (if (and (cddr pts) (equal (TK:2d (car pts)) (TK:2d (last pts)) 1e-6))
                 (setq pts (reverse (cdr (reverse pts))) p 1)
                 (setq p 0))
               (entmake (append (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") '(8 . "KML") '(100 . "AcDbPolyline")
                                      (cons 90 (length pts)) (cons 70 p))
                                (mapcar '(lambda (q) (list 10 (car q) (cadr q))) pts)))
               (setq n (1+ n))))
            (if (and pts (/= (car it) ""))
              (TKT:Txt (car it) (car pts) (TKT:H) 0.0 "L" "KML")))
          (setq meth (TK:MethodText))
          (TK:GridClose)
          (vl-catch-all-apply 'vla-ZoomExtents (list (vlax-get-acad-object)))
          (TKT:Msg (strcat "S-au importat " (itoa n) " linii/poligoane si " (itoa np) " puncte din " f
                           " (WGS84 -> Stereo 70, " meth ")."))
          (list n np))))))

;; TKT:Map - comanda HARTA: punctul indicat (sau centrul ecranului) în Google Maps
(defun TKT:Map (/ p ll url)
  (setq p (getpoint "\nPunctul de afisat pe harta online <centrul ecranului>: "))
  (if (null p) (setq p (getvar "VIEWCTR")))
  (if (= *TK:USEGRID* "1") (TK:GridOpen))
  (setq ll (TK:Stereo70ToWGS84 (TK:PtEN p)))
  (TK:GridClose)
  (setq url (strcat "https://www.google.com/maps/search/?api=1&query=" (rtos (cadr ll) 2 7) "," (rtos (car ll) 2 7)))
  (TK:Run (strcat "explorer.exe \"" url "\"") nil)
  (TKT:Msg (strcat "Harta: " url))
  url)

;;; ==========================================================================
;;;  MENIUL MODULULUI ȘI COMENZILE
;;; ==========================================================================

;; TKT:DclPath - TopoKitTeren.dcl (sau o copie generată din TKT:DclLines)
(defun TKT:DclPath (/ f lsp fh)
  (cond
    ((findfile "TopoKitTeren.dcl"))
    ((and (setq lsp (findfile "TopoKitTeren.lsp"))
          (findfile (setq f (strcat (vl-filename-directory lsp) "\\TopoKitTeren.dcl"))))
     f)
    ((and *TKT:DCLTMP* (findfile *TKT:DCLTMP*)) *TKT:DCLTMP*)
    ((setq fh (open (setq f (vl-filename-mktemp "TopoKitTeren" nil ".dcl")) "w"))
     (foreach l (TKT:DclLines) (write-line l fh))
     (close fh)
     (setq *TKT:DCLTMP* f))))

;; TKT:Fill - completează o listă derulantă
(defun TKT:Fill (key items) (start_list key) (foreach i items (add_list i)) (end_list))

;; TKT:ReadOpts - citește și validează opțiunile din dialog (T dacă sunt corecte)
(defun TKT:ReadOpts (/ v)
  (setq v (mapcar '(lambda (k) (distof (get_tile k) 2)) '("eb_lmax" "eb_echid" "eb_princ" "eb_cota" "eb_cel")))
  (cond
    ((member nil v) (set_tile "error" "Valori numerice invalide.") nil)
    ((or (<= (nth 1 v) 0.0) (< (nth 2 v) 1.0) (<= (nth 4 v) 0.0) (< (nth 0 v) 0.0))
     (set_tile "error" "Echidistanta, pasul grilei si curba principala trebuie sa fie pozitive.") nil)
    (T
     (setq *TKT:LMAX* (nth 0 v) *TKT:ECHID* (nth 1 v) *TKT:PRINC* (fix (nth 2 v)) *TKT:COTAREF* (nth 3 v)
           *TKT:CELULA* (nth 4 v)
           *TKT:COLS* (car (nth (atoi (get_tile "pl_cols")) *TKT:COLLIST*))
           *TKT:SCARA* (nth (atoi (get_tile "pl_scara")) *TKT:SCALES*)
           *TKT:3D* (get_tile "tg_3d") *TKT:CODURI* (get_tile "tg_coduri"))
     T)))

;; Butoanele meniului: (cheie cod comandă)
(setq *TKT:BTNS* '(("bt_imp" 1 TKT:ImportPoints) ("bt_tab" 2 TKT:CmdTable) ("bt_leg" 3 TKT:CmdLegend)
                   ("bt_tin" 4 TKT:MakeTin) ("bt_curbe" 5 TKT:CmdContours) ("bt_vol" 6 TKT:CmdVolPlane0)
                   ("bt_vol2" 7 TKT:CmdVolTins) ("bt_geo" 8 TKT:Georef) ("bt_kml" 9 TKT:ImportKml)
                   ("bt_harta" 10 TKT:Map)))

;; TKT:Menu - dialogul modulului; returnează codul butonului ales
(defun TKT:Menu (/ id res)
  (setq id (load_dialog (TKT:DclPath)))
  (cond
    ((< id 0) (alert "Nu s-a putut incarca TopoKitTeren.dcl.") nil)
    ((not (new_dialog "tkt_main" id)) (unload_dialog id) nil)
    (T
     (TKT:Fill "pl_cols" (mapcar 'cdr *TKT:COLLIST*))
     (set_tile "pl_cols" (itoa (max 0 (cond ((vl-position *TKT:COLS* (mapcar 'car *TKT:COLLIST*))) (0)))))
     (TKT:Fill "pl_scara" (mapcar '(lambda (s) (strcat "1:" (itoa s))) *TKT:SCALES*))
     (set_tile "pl_scara" (itoa (cond ((vl-position *TKT:SCARA* *TKT:SCALES*)) (2))))
     (set_tile "tg_3d" *TKT:3D*)
     (set_tile "tg_coduri" *TKT:CODURI*)
     (mapcar '(lambda (k v) (set_tile k (rtos v 2 2)))
             '("eb_lmax" "eb_echid" "eb_princ" "eb_cota" "eb_cel")
             (list *TKT:LMAX* *TKT:ECHID* (float *TKT:PRINC*) *TKT:COTAREF* *TKT:CELULA*))
     (foreach b *TKT:BTNS*
       (action_tile (car b) (strcat "(if (TKT:ReadOpts) (done_dialog " (itoa (cadr b)) "))")))
     (action_tile "cancel" "(done_dialog 0)")
     (setq res (start_dialog))
     (unload_dialog id)
     res)))

;; TKT:Run - execută FN cu gestionarea erorilor și a variabilelor de sistem
(defun TKT:Run (fn / *error* r)
  (defun *error* (msg) (TK:Error msg))
  (TK:Start)
  (if (/= (strcase (getvar "CTAB")) "MODEL") (setvar "CTAB" "Model"))
  (TKT:Layers)
  (setq r (eval fn))
  (TK:Stop)
  r)

;; TKT:CmdContours / TKT:CmdVolPlane0 - comenzile din meniu
(defun TKT:CmdContours (/ tris)
  (if (setq tris (TKT:SelTin "\nSelectati triunghiurile TIN (3DFACE): ")) (TKT:Contours tris)))
(defun TKT:CmdVolPlane0 () (TKT:CmdVolPlane nil))

(defun c:TOPOTEREN (/ r b)
  (if (and (setq r (TKT:Menu)) (setq b (vl-some '(lambda (x) (if (= (cadr x) r) x)) *TKT:BTNS*)))
    (TKT:Run (list (caddr b))))
  (princ))
(defun c:IMPPCT () (TKT:Run '(TKT:ImportPoints)) (princ))
(defun c:TABPCT () (TKT:Run '(TKT:CmdTable)) (princ))
(defun c:LEGENDA () (TKT:Run '(TKT:CmdLegend)) (princ))
(defun c:TIN () (TKT:Run '(TKT:MakeTin)) (princ))
(defun c:CURBE () (TKT:Run '(TKT:CmdContours)) (princ))
(defun c:VOLUM () (TKT:Run '(TKT:CmdVolPlane T)) (princ))
(defun c:VOLUM2 () (TKT:Run '(TKT:CmdVolTins)) (princ))
(defun c:GEOREF () (TKT:Run '(TKT:Georef)) (princ))
(defun c:IMPKML () (TKT:Run '(TKT:ImportKml)) (princ))
(defun c:HARTA () (TKT:Run '(TKT:Map)) (princ))

;;; ==========================================================================
;;;  DIALOGUL (COPIE PENTRU GENERAREA AUTOMATĂ)
;;; ==========================================================================
;; TKT:DclLines - conținutul fișierului TopoKitTeren.dcl
;; (Secțiune generată din TopoKitTeren.dcl cu tools/embed_dcl.py - nu editați manual.)
;;@@DCL-BEGIN@@
(defun TKT:DclLines ()
  (list
    "// ==========================================================================="
    "//  TopoKitTeren.dcl - meniul modulului de teren TopoKit (comanda TOPOTEREN)"
    "//  Fisierul este optional: daca lipseste, TopoKitTeren.lsp genereaza automat"
    "//  o copie identica intr-un fisier temporar."
    "// ==========================================================================="
    ""
    "tkt_btn : button { width = 30; fixed_width = true; }"
    "tkt_num : edit_box { edit_width = 8; }"
    ""
    "tkt_main : dialog {"
    "  label = \"TopoKit - Teren: puncte, model 3D, curbe de nivel, volume, raster\";"
    "  : row {"
    "    : column {"
    "      : boxed_column {"
    "        label = \"Puncte masurate si plan\";"
    "        : popup_list { key = \"pl_cols\"; label = \"Coloanele fisierului:\"; edit_width = 30; }"
    "        : toggle { key = \"tg_3d\"; label = \"Puncte 3D (la cota Z)\"; }"
    "        : toggle { key = \"tg_coduri\"; label = \"Uneste punctele consecutive cu acelasi cod\"; }"
    "        : popup_list { key = \"pl_scara\"; label = \"Scara planului (texte):\"; edit_width = 10; }"
    "        : tkt_btn { key = \"bt_imp\"; label = \"Import puncte (TXT/CSV)...\"; }"
    "        : tkt_btn { key = \"bt_tab\"; label = \"Tabel de coordonate\"; }"
    "        : tkt_btn { key = \"bt_leg\"; label = \"Legenda semnelor conventionale\"; }"
    "      }"
    "      : boxed_column {"
    "        label = \"Raster, Google Earth si harti online\";"
    "        : tkt_btn { key = \"bt_geo\"; label = \"Raster georeferentiat...\"; }"
    "        : tkt_btn { key = \"bt_kml\"; label = \"Import KML / KMZ...\"; }"
    "        : tkt_btn { key = \"bt_harta\"; label = \"Punct pe harta online\"; }"
    "      }"
    "    }"
    "    : column {"
    "      : boxed_column {"
    "        label = \"Model 3D (TIN) si curbe de nivel\";"
    "        : tkt_num { key = \"eb_lmax\"; label = \"Latura maxima a triunghiurilor (m, 0 = fara):\"; }"
    "        : tkt_btn { key = \"bt_tin\"; label = \"Model TIN din puncte si linii\"; }"
    "        : tkt_num { key = \"eb_echid\"; label = \"Echidistanta curbelor (m):\"; }"
    "        : tkt_num { key = \"eb_princ\"; label = \"Curba principala la fiecare (curbe):\"; }"
    "        : tkt_btn { key = \"bt_curbe\"; label = \"Curbe de nivel din TIN\"; }"
    "      }"
    "      : boxed_column {"
    "        label = \"Volume de sapatura si umplutura\";"
    "        : tkt_num { key = \"eb_cota\"; label = \"Cota planului de referinta (m):\"; }"
    "        : tkt_btn { key = \"bt_vol\"; label = \"Volume TIN - plan\"; }"
    "        : tkt_num { key = \"eb_cel\"; label = \"Pasul grilei pentru doua TIN (m):\"; }"
    "        : tkt_btn { key = \"bt_vol2\"; label = \"Volume intre doua TIN\"; }"
    "      }"
    "    }"
    "  }"
    "  : text { label = \"Comenzi directe: IMPPCT, TABPCT, LEGENDA, TIN, CURBE, VOLUM, VOLUM2, GEOREF, IMPKML, HARTA\"; }"
    "  : row {"
    "    fixed_width = true;"
    "    alignment = centered;"
    "    : button { key = \"cancel\"; label = \"Inchide\"; is_cancel = true; width = 16; }"
    "  }"
    "  errtile;"
    "}"))
;;@@DCL-END@@

(setq *TKT:LOADING* nil)
(princ "\nTopoKit Teren incarcat. Comenzi: TOPOTEREN, IMPPCT, TABPCT, LEGENDA, TIN, CURBE, VOLUM, VOLUM2, GEOREF, IMPKML, HARTA.")
(princ)
