;;; ==========================================================================
;;;  TopoKitInclinare.lsp  -  Planul de înclinare (verticalitate) TopoKit
;;; ==========================================================================
;;;
;;;  Comenzi:
;;;    INCLINARE - planul de înclinare / verticalitate al unei
;;;                construcții înalte (siloz, stâlp, coș, turn) din puncte
;;;                măsurate pe rânduri (ex. codurile "stanga" și "dreapta").
;;;
;;;  Modelul de calcul (identic cu programul Plan Inclinare):
;;;    - punctele unui rând se aleg după cod și se ordonează după cota Z;
;;;    - verticala de referință (linia verde) trece prin punctul cel mai de
;;;      jos al rândului; H = Z - Z(bază);
;;;    - abaterea totală = distanța orizontală de la punct la verticală;
;;;      abaterea proiectată = proiecția pe axa rândul din stânga -> rândul
;;;      din dreapta (prin punctele de bază);
;;;    - direcția de aplecare se deduce pe aceeași axă (auto) sau se alege;
;;;    - linia roșie unește pozițiile reale, linia gri arată abaterea la
;;;      lungimea reală (desen 1:1, în metri), cu valoarea scrisă;
;;;    - planșa A4...A0 la scara 1:100...1:2000 (aleasă sau automat), cu
;;;      chenar și cartuș; textele au mărimea în mm pe hârtie.
;;;
;;;  Punctele: puncte COGO Civil 3D (codul = descrierea), puncte AutoCAD
;;;  (codul = stratul), blocuri cu atribute sau fișier CSV/TXT (Nr,X,Y,Z,Cod).
;;;  Necesită TopoKit.lsp.
;;; ==========================================================================

(vl-load-com)
(setq *TKI:LOADING* T)
(if (and (not TK:Start) (findfile "TopoKit.lsp")) (load (findfile "TopoKit.lsp")))
(if (not TK:Start)
  (alert "TopoKitInclinare.lsp necesita TopoKit.lsp (in acelasi folder, in calea de suport AutoCAD)."))

(setq *TKI:REGKEY* "HKEY_CURRENT_USER\\Software\\TopoKit\\Inclinare")
(setq *TKI:FORMATE* '(("A4" 210.0 297.0) ("A3" 297.0 420.0) ("A2" 420.0 594.0) ("A1" 594.0 841.0) ("A0" 841.0 1189.0)))
(setq *TKI:SCARI* '(100 200 500 1000 2000))
(setq *TKI:MST* 20.0 *TKI:MRG* 10.0 *TKI:CL* 120.0 *TKI:CH* 30.0 *TKI:TW* 1.0)

;; Setările (nume valoare-implicită); se păstrează în registru între sesiuni
(setq *TKI:DEF*
       '(("rand1" . "stanga|PARTEA STANGA|auto") ("rand2" . "dreapta|PARTEA DREAPTA|auto")
         ("rand3" . "||auto") ("rand4" . "||auto")
         ("potrivire" . "incepe cu") ("abatere" . "totala") ("unitate" . "cm") ("zecimale" . "1")
         ("format" . "auto") ("orientare" . "auto") ("scara" . "auto") ("prioritate" . "scara mare")
         ("cartus" . "1") ("beneficiar" . "") ("obiectiv" . "") ("intocmit" . "") ("plansa" . "1")
         ("titlu" . "PLAN INCLINARE SILOZ") ("text_mm" . "1.8") ("titlu_mm" . "4.0") ("raza_mm" . "0.35")
         ("etichete_mm" . "18.0") ("randuri_mm" . "15.0") ("arata_h" . "1") ("arata_z" . "0")
         ("evita" . "1") ("legenda" . "1") ("rama" . "1") ("strat" . "PLAN_INCLINARE")
         ("coloane" . "NXYZC")))

;; TKI:Get / TKI:Set - setarea NUME (șir); TKI:Num - valoarea numerică
(defun TKI:Get (k / v)
  (cond ((cdr (assoc k *TKI:CFG*)))
        ((and (setq v (vl-registry-read *TKI:REGKEY* k)) (= (type v) 'STR)) v)
        ((cdr (assoc k *TKI:DEF*)))
        ("")))
(defun TKI:Set (k v)
  (setq *TKI:CFG* (cons (cons k v) (vl-remove-if '(lambda (x) (= (car x) k)) *TKI:CFG*))))
(defun TKI:Num (k) (cond ((distof (TKI:Get k) 2)) ((distof (cdr (assoc k *TKI:DEF*)) 2)) (0.0)))
(defun TKI:On (k) (= (TKI:Get k) "1"))
(defun TKI:Save ()
  (foreach p *TKI:CFG* (vl-catch-all-apply 'vl-registry-write (list *TKI:REGKEY* (car p) (cdr p)))))

;; TKI:SplitS - împarte șirul S după separatorul SEP (un caracter)
(defun TKI:SplitS (s sep / out cur c)
  (setq cur "")
  (foreach c (vl-string->list s)
    (if (= (chr c) sep) (setq out (cons cur out) cur "") (setq cur (strcat cur (chr c)))))
  (reverse (cons cur out)))

;; TKI:Rows - rândurile configurate: ((cod titlu directie) ...), doar cele cu cod
(defun TKI:Rows (/ r out)
  (foreach k '("rand1" "rand2" "rand3" "rand4")
    (setq r (TKI:SplitS (TKI:Get k) "|"))
    (while (< (length r) 3) (setq r (append r (list ""))))
    (if (/= (vl-string-trim " " (car r)) "")
      (setq out (cons (list (vl-string-trim " " (car r)) (vl-string-trim " " (cadr r))
                            (if (member (caddr r) '("stanga" "dreapta")) (caddr r) "auto"))
                      out))))
  (reverse out))

;; TKI:Ascii - textul fără diacritice și alte caractere non-ASCII (fonturile
;; AutoCAD, codificarea DWG). Coduri Unicode (LISPSYS=1) și Windows-1250 (LISPSYS=0).
(setq *TKI:DIA* '((537 . 115) (351 . 115) (186 . 115) (536 . 83) (350 . 83) (170 . 83)
                  (539 . 116) (355 . 116) (254 . 116) (538 . 84) (354 . 84) (222 . 84)
                  (259 . 97) (227 . 97) (226 . 97) (238 . 105) (258 . 65) (195 . 65) (194 . 65) (206 . 73)))
(defun TKI:Ascii (s / c)
  (vl-list->string
    (vl-remove nil (mapcar '(lambda (c) (cond ((< c 128) c) ((cdr (assoc c *TKI:DIA*)))))
                           (vl-string->list s)))))

;; TKI:Fmt - număr cu D zecimale (independent de DIMZIN)
(defun TKI:Fmt (x d / dz s)
  (setq dz (getvar "DIMZIN"))
  (if dz (setvar "DIMZIN" 0))
  (setq s (rtos x 2 d))
  (if dz (setvar "DIMZIN" dz))
  s)

;;; ==========================================================================
;;;  CALCULUL
;;; ==========================================================================

;; TKI:Match - T dacă codul COD se potrivește cu WANTED (mai multe coduri
;; separate prin virgulă), după modul "exact" / "incepe cu" / "contine"
(defun TKI:Match (cod wanted mode / a)
  (setq a (strcase (vl-string-trim " " (vl-princ-to-string cod)) T))
  (vl-some '(lambda (b)
              (setq b (strcase (vl-string-trim " " b) T))
              (and (/= b "")
                   (cond ((= mode "exact") (= a b))
                         ((= mode "contine") (vl-string-search b a))
                         (T (= 0 (vl-string-search b a))))))
           (TKI:SplitS wanted ",")))

;; TKI:SortZ - punctele ordonate crescător după cotă (sortare stabilă)
(defun TKI:SortZ (pts / n a b)
  (if (cdr pts)
    (progn
      (setq n (/ (length pts) 2))
      (repeat n (setq a (cons (car pts) a) pts (cdr pts)))
      (setq a (TKI:SortZ (reverse a)) b (TKI:SortZ pts) pts nil)
      (while (and a b)
        (if (<= (nth 3 (car a)) (nth 3 (car b)))
          (setq pts (cons (car a) pts) a (cdr a))
          (setq pts (cons (car b) pts) b (cdr b))))
      (append (reverse pts) a b))
    pts))

;; TKI:Compute - rândurile calculate pentru punctele PTS ((nr x y z cod) ...):
;; ((cfgRând date semn vârf) ...) cu date = ((punct H totală proiectată valoare desen) ...)
;; și lista mesajelor în *TKI:MSGS*
(defun TKI:Compute (pts / sel rows b0 b1 dx dy l ax data b proj aus d sign flip proj? out x)
  (setq *TKI:MSGS* nil proj? (= (TKI:Get "abatere") "proiectata"))
  (foreach rc (TKI:Rows)
    (setq sel (vl-remove-if-not '(lambda (p) (TKI:Match (nth 4 p) (car rc) (TKI:Get "potrivire"))) pts))
    (if (< (length sel) 2)
      (setq *TKI:MSGS* (cons (strcat "Randul '" (car rc) "': " (itoa (length sel)) " puncte (minim 2) - ignorat.")
                             *TKI:MSGS*))
      (setq rows (cons (list rc (TKI:SortZ sel)) rows))))
  (setq rows (reverse rows))
  ;; axa rândul din stânga -> rândul din dreapta (prin punctele de bază)
  (if (cdr rows)
    (setq b0 (car (cadr (car rows))) b1 (car (cadr (last rows)))
          dx (- (cadr b1) (cadr b0)) dy (- (caddr b1) (caddr b0))
          l  (sqrt (+ (* dx dx) (* dy dy)))
          ax (if (> l 1e-6) (list (/ dx l) (/ dy l)))))
  (foreach row rows
    (setq b (car (cadr row)) data nil)
    (foreach p (cadr row)
      (setq dx (- (cadr p) (cadr b)) dy (- (caddr p) (caddr b))
            proj (if ax (+ (* dx (car ax)) (* dy (cadr ax))) 0.0)
            data (cons (list p (- (nth 3 p) (nth 3 b)) (sqrt (+ (* dx dx) (* dy dy))) proj) data)))
    (setq data (reverse data)
          aus (if (or (null ax) (>= (apply '+ (mapcar 'cadddr data)) 0.0)) 1 -1)
          d (caddr (car row))
          sign (cond ((= d "dreapta") 1) ((= d "stanga") -1) (T aus))
          flip (* sign aus))
    (if (and (= d "auto") (null ax))
      (setq *TKI:MSGS* (cons (strcat "Randul '" (car (car row)) "': directia nu se poate deduce dintr-un singur rand - "
                                     "am pus 'dreapta'. Alegeti directia in dialog.")
                             *TKI:MSGS*)))
    (setq data (mapcar '(lambda (x)
                          (if (and proj? ax)
                            (append x (list (abs (nth 3 x)) (* (nth 3 x) flip)))
                            (append x (list (nth 2 x) (* sign (nth 2 x))))))
                       data)
          out (cons (list (car row) data sign (last data)) out)))
  (if (and proj? (null ax) rows)
    (setq *TKI:MSGS* (cons "Abaterea proiectata cere doua randuri; s-a folosit abaterea totala." *TKI:MSGS*)))
  (setq *TKI:MSGS* (reverse *TKI:MSGS*))
  (reverse out))

;; TKI:FmtVal - abaterea V (m) în unitatea aleasă, cu unitatea scrisă
(defun TKI:FmtVal (v / u)
  (setq u (TKI:Get "unitate"))
  (strcat (TKI:Fmt (* v (cdr (assoc u '(("cm" . 100.0) ("mm" . 1000.0) ("m" . 1.0))))) (fix (TKI:Num "zecimale")))
          " " u))

;;; ==========================================================================
;;;  GEOMETRIA (listă de elemente, desenate apoi în spațiul model)
;;;    ("line" a b culoare) ("pline" puncte culoare grosime)
;;;    ("circle" centru rază culoare) ("text" punct șir înălțime culoare "L"/"C"/"R")
;;; ==========================================================================

(defun TKI:BBox (items / xs ys w x0)
  (foreach it items
    (cond
      ((= (car it) "line") (setq xs (cons (car (cadr it)) (cons (car (caddr it)) xs))
                                 ys (cons (cadr (cadr it)) (cons (cadr (caddr it)) ys))))
      ((= (car it) "pline") (foreach p (cadr it) (setq xs (cons (car p) xs) ys (cons (cadr p) ys))))
      ((= (car it) "circle")
       (setq xs (cons (- (car (cadr it)) (caddr it)) (cons (+ (car (cadr it)) (caddr it)) xs))
             ys (cons (- (cadr (cadr it)) (caddr it)) (cons (+ (cadr (cadr it)) (caddr it)) ys))))
      ((= (car it) "text")
       (setq w (* *TKI:TW* (nth 3 it) (strlen (nth 2 it)))
             x0 (cond ((= (nth 5 it) "R") (- (car (cadr it)) w)) ((= (nth 5 it) "C") (- (car (cadr it)) (/ w 2.0)))
                      (T (car (cadr it))))
             xs (cons x0 (cons (+ x0 w) xs))
             ys (cons (- (cadr (cadr it)) (* 0.6 (nth 3 it))) (cons (+ (cadr (cadr it)) (* 0.6 (nth 3 it))) ys))))))
  (if xs (list (apply 'min xs) (apply 'min ys) (apply 'max xs) (apply 'max ys)) (list 0.0 0.0 1.0 1.0)))

(defun TKI:Mv (p dx dy) (list (+ (car p) dx) (+ (cadr p) dy)))
(defun TKI:Move (items dx dy)
  (mapcar '(lambda (it)
             (cond
               ((= (car it) "line") (list "line" (TKI:Mv (cadr it) dx dy) (TKI:Mv (caddr it) dx dy) (cadddr it)))
               ((= (car it) "pline") (list "pline" (mapcar '(lambda (p) (TKI:Mv p dx dy)) (cadr it)) (caddr it) (cadddr it)))
               ((= (car it) "circle") (list "circle" (TKI:Mv (cadr it) dx dy) (caddr it) (cadddr it)))
               (T (cons "text" (cons (TKI:Mv (cadr it) dx dy) (cddr it))))))
          items))

(defun TKI:Rect (x0 y0 x1 y1 col w)
  (list "pline" (list (list x0 y0) (list x1 y0) (list x1 y1) (list x0 y1) (list x0 y0)) col w))

;; TKI:Content - desenul rândurilor; K = metri în model pentru 1 mm pe hârtie
(defun TKI:Content (rows k / g th lab gap rpt wred cg cr cy ct hmax top x0 pos neg tt pct titlu rez1 rez2
                       textw width gx red n lasth htop slab extout extin colout colin i x r info cx totalw y yy
                       legrows)
  (setq th (* (TKI:Num "text_mm") k) lab (* (TKI:Num "etichete_mm") k) gap (* (TKI:Num "randuri_mm") k)
        rpt (* (TKI:Num "raza_mm") k) wred 0.0 cg 3 cr 1 cy 8 ct 7
        hmax (apply 'max (mapcar '(lambda (x) (cadr x)) (apply 'append (mapcar 'cadr rows))))
        top (+ hmax (* 5 th)) x0 0.0)
  (foreach row rows
    (setq pos (max 0.0 (apply 'max (mapcar '(lambda (x) (nth 5 x)) (cadr row))))
          neg (max 0.0 (- (apply 'min (mapcar '(lambda (x) (nth 5 x)) (cadr row)))))
          tt (cadddr row)
          pct (if (> (cadr tt) 0.0) (* 100.0 (/ (nth 4 tt) (cadr tt))) 0.0)
          titlu (TKI:Ascii (if (/= (cadr (car row)) "") (cadr (car row)) (car (car row))))
          rez1 (strcat "Abatere la varf: " (TKI:FmtVal (nth 4 tt)))
          rez2 (strcat "la H=" (TKI:Fmt (cadr tt) 2) " m - " (TKI:Fmt pct 2) "% (" (TKI:Fmt (* pct 10.0) 1) " mm/m)")
          textw (+ (max (* *TKI:TW* th 1.7 (strlen titlu)) (* *TKI:TW* th 1.1 (max (strlen rez1) (strlen rez2)))) (* 2 th))
          width (max (+ (* 2 lab) pos neg) textw)
          gx (+ x0 (/ (- width (+ pos neg)) 2.0) neg)
          g (cons (list "line" (list (- gx (* 4 th)) 0.0) (list (+ gx (* 4 th)) 0.0) cy) g)        ; baza
          g (cons (list "line" (list gx (* -1.5 th)) (list gx top) cg) g)                           ; verticala
          red (mapcar '(lambda (x) (list (+ gx (nth 5 x)) (cadr x))) (cadr row))
          g (cons (list "pline" red cr wred) g)                                                     ; poziția reală
          n (length red) lasth nil htop (cadr (last red))
          slab (caddr row)
          extout (if (> slab 0) pos neg) extin (if (> slab 0) neg pos)
          colout (+ gx (* slab (+ extout (* 1.5 th))))
          colin (- gx (* slab (+ extin (* 1.5 th))))
          i 0)
    (foreach x (cadr row)
      (setq r (nth i red))
      (setq g (cons (list "circle" r rpt cr) g))
      (if (> (abs (- (car r) gx)) 1e-9) (setq g (cons (list "line" (list gx (cadr r)) r cy) g)))
      (if (not (and (TKI:On "evita") (< 0 i (1- n))
                    (or (and lasth (< (- (cadr r) lasth) (* 1.25 th))) (< (- htop (cadr r)) (* 1.25 th)))))
        (progn
          (setq lasth (cadr r)
                g (cons (list "text" (list colout (cadr r)) (TKI:FmtVal (nth 4 x)) th ct (if (> slab 0) "L" "R")) g)
                info nil)
          (if (TKI:On "arata_h") (setq info (cons (strcat "H=" (TKI:Fmt (cadr x) 2)) info)))
          (if (TKI:On "arata_z") (setq info (cons (strcat "Z=" (TKI:Fmt (nth 3 (car x)) 3)) info)))
          (if info
            (setq g (cons (list "text" (list colin (cadr r))
                                (apply 'strcat (cdr (apply 'append (mapcar '(lambda (s) (list "  " s)) (reverse info)))))
                                (* th 0.85) cy (if (> slab 0) "R" "L"))
                          g)))))
      (setq i (1+ i)))
    (setq cx (+ x0 (/ width 2.0))
          g (cons (list "text" (list cx (+ top (* 9 th))) titlu (* th 1.7) ct "C") g)
          g (cons (list "text" (list cx (+ top (* 5.8 th))) rez1 (* th 1.1) 2 "C") g)
          g (cons (list "text" (list cx (+ top (* 4.0 th))) rez2 (* th 1.1) 2 "C") g)
          x0 (+ x0 width gap)))
  (setq totalw (- x0 gap)
        g (cons (list "text" (list (/ totalw 2.0) (+ top (* 14 th))) (TKI:Ascii (TKI:Get "titlu")) (* (TKI:Num "titlu_mm") k) ct "C") g))
  (if (TKI:On "legenda")
    (progn
      (setq y (* -5 th) i 0
            legrows (list (list cg 0 "Linia verde - verticala de referinta,")
                          (list nil 0 "dusa prin punctul cel mai de jos al randului")
                          (list cr wred "Linia rosie - pozitia reala masurata")
                          (list cy 0 (strcat "Linia gri - abaterea pe orizontala (" (TKI:Get "unitate") ")"))))
      (foreach lr legrows
        (setq yy (- y (* i 2.2 th)))
        (if (car lr) (setq g (cons (list "pline" (list (list 0.0 yy) (list (* 5 th) yy)) (car lr) (cadr lr)) g)))
        (setq g (cons (list "text" (list (* 6.2 th) yy) (caddr lr) th ct "L") g) i (1+ i)))
      (setq yy (- y (* (length legrows) 2.2 th) (* 0.5 th))
            g (cons (list "text" (list 0.0 yy) "Cote in metri, desen la scara 1:1; abaterile sunt desenate la lungimea reala."
                          (* th 0.9) cy "L") g)
            g (cons (list "text" (list 0.0 (- yy (* 1.9 th))) "H = inaltimea fata de punctul de baza al randului."
                          (* th 0.9) cy "L") g))))
  (reverse g))

;; TKI:FormatWH - dimensiunile (mm) formatului FMT în orientarea ORI
(defun TKI:FormatWH (fmt ori / f)
  (setq f (cdr (assoc fmt *TKI:FORMATE*)))
  (if (= ori "peisaj") (list (cadr f) (car f)) f))

;; TKI:Fit - T dacă desenul cu dreptunghiul BB încape pe planșă
(defun TKI:Fit (bb fmt ori sc / k wh aw ah)
  (setq k (/ sc 1000.0) wh (TKI:FormatWH fmt ori)
        aw (- (car wh) *TKI:MST* *TKI:MRG* 10.0)
        ah (- (cadr wh) (* 2 *TKI:MRG*) 10.0 (if (TKI:On "cartus") (+ *TKI:CH* 5.0) 0.0)))
  (and (<= (/ (- (caddr bb) (car bb)) k) aw) (<= (/ (- (cadddr bb) (cadr bb)) k) ah)))

;; TKI:Sheet - chenarul și cartușul; returnează (elemente zonaUtilă)
(defun TKI:Sheet (fmt ori sc / k wh w h g fx0 fy0 fx1 fy1 cx0 cy0 rh rows i y ym v1 w1)
  (setq k (/ sc 1000.0) wh (TKI:FormatWH fmt ori) w (* k (car wh)) h (* k (cadr wh))
        g (list (TKI:Rect 0.0 0.0 w h 8 0.0))
        fx0 (* *TKI:MST* k) fy0 (* *TKI:MRG* k) fx1 (- w (* *TKI:MRG* k)) fy1 (- h (* *TKI:MRG* k))
        g (cons (TKI:Rect fx0 fy0 fx1 fy1 7 (* 0.5 k)) g))
  (if (TKI:On "cartus")
    (progn
      (setq cx0 (- fx1 (* *TKI:CL* k)) cy0 fy0
            g (cons (TKI:Rect cx0 cy0 fx1 (+ cy0 (* *TKI:CH* k)) 7 0.0) g)
            rows (list (list "Intocmit" (TKI:Get "intocmit") "Data" (TKI:Today))
                       (list "Scara" (strcat "1:" (itoa sc)) "Format" (strcat fmt " " ori))
                       (list "Plansa" (TKI:Get "titlu") "Nr." (TKI:Get "plansa"))
                       (list "Obiectiv" (TKI:Get "obiectiv") "" "")
                       (list "Beneficiar" (TKI:Get "beneficiar") "" ""))
            rh (/ *TKI:CH* (length rows)) i 0)
      (foreach r rows
        (setq y (+ cy0 (* i rh k)) ym (+ y (/ (* rh k) 2.0)) v1 (TKI:Ascii (cadr r)) w1 (if (/= (caddr r) "") 59.0 96.0))
        (if (> i 0) (setq g (cons (list "line" (list cx0 y) (list fx1 y) 7) g)))
        (setq g (cons (list "text" (list (+ cx0 (* 2 k)) ym) (car r) (* (TKI:FitH (car r) 1.8 17.0) k) 8 "L") g)
              g (cons (list "text" (list (+ cx0 (* 22 k)) ym) v1 (* (TKI:FitH v1 2.2 w1) k) 7 "L") g))
        (if (/= (caddr r) "")
          (setq g (cons (list "text" (list (+ cx0 (* 84 k)) ym) (caddr r) (* (TKI:FitH (caddr r) 1.8 10.0) k) 8 "L") g)
                g (cons (list "text" (list (+ cx0 (* 95 k)) ym) (TKI:Ascii (cadddr r))
                              (* (TKI:FitH (TKI:Ascii (cadddr r)) 2.2 23.0) k) 7 "L") g)))
        (setq i (1+ i)))
      (setq g (cons (list "line" (list (+ cx0 (* 20 k)) cy0) (list (+ cx0 (* 20 k)) (+ cy0 (* *TKI:CH* k))) 7) g)
            g (cons (list "line" (list (+ cx0 (* 82 k)) cy0) (list (+ cx0 (* 82 k)) (+ cy0 (* 3 rh k))) 7) g))))
  (list (reverse g)
        (list (+ fx0 (* 5 k)) (+ fy0 (* (if (TKI:On "cartus") (+ *TKI:CH* 5.0) 5.0) k)) (- fx1 (* 5 k)) (- fy1 (* 5 k)))))

;; TKI:FitH - înălțimea textului (mm) ca S să încapă în W mm (maxim H)
(defun TKI:FitH (s h w) (min h (/ w (* *TKI:TW* (max (strlen s) 1)))))

;; TKI:Today - data curentă zz.ll.aaaa
(defun TKI:Today (/ d)
  (setq d (rtos (getvar "CDATE") 2 0))
  (strcat (substr d 7 2) "." (substr d 5 2) "." (substr d 1 4)))

;; TKI:Layout - alege formatul și scara; returnează (elemente info) cu
;; info = (format orientare scara încape)
(defun TKI:Layout (rows / scs fmts oris combos cache bb chosen ok c content sh av cb dx dy sc fm m)
  (setq sc (TKI:Get "scara") fm (TKI:Get "format")
        scs (if (= sc "auto") *TKI:SCARI* (list (atoi (substr sc 3)))))
  (cond
    ((null rows) nil)
    ((= fm "fara")
     (setq content (TKI:Content rows (/ (car scs) 1000.0)))
     (if (TKI:On "rama")
       (setq bb (TKI:BBox content) m (* 5 (/ (car scs) 1000.0))
             content (append content (list (TKI:Rect (- (car bb) m) (- (cadr bb) m) (+ (caddr bb) m) (+ (cadddr bb) m) 7 0.0)))))
     (list content (list "fara" "" (car scs) T)))
    (T
     (setq fmts (if (= fm "auto") (mapcar 'car *TKI:FORMATE*) (list fm))
           oris (if (= (TKI:Get "orientare") "auto") '("portret" "peisaj") (list (TKI:Get "orientare"))))
     (if (= (TKI:Get "prioritate") "format mic")
       (foreach f fmts (foreach s scs (setq combos (cons (list f s) combos))))
       (foreach s scs (foreach f fmts (setq combos (cons (list f s) combos)))))
     (setq combos (reverse combos))
     (while (and combos (not chosen))
       (setq c (car combos) combos (cdr combos))
       (if (not (assoc (cadr c) cache))
         (setq cache (cons (cons (cadr c) (TKI:Content rows (/ (cadr c) 1000.0))) cache)))
       (setq bb (TKI:BBox (cdr (assoc (cadr c) cache))))
       (foreach o oris (if (and (not chosen) (TKI:Fit bb (car c) o (cadr c))) (setq chosen (list (car c) o (cadr c))))))
     (setq ok (and chosen T))
     (if (not chosen) (setq chosen (list (last fmts) (car oris) (last scs))))
     (setq content (cond ((cdr (assoc (caddr chosen) cache))) ((TKI:Content rows (/ (caddr chosen) 1000.0))))
           sh (TKI:Sheet (car chosen) (cadr chosen) (caddr chosen))
           av (cadr sh) cb (TKI:BBox content)
           dx (- (/ (+ (car av) (caddr av)) 2.0) (/ (+ (car cb) (caddr cb)) 2.0))
           dy (- (/ (+ (cadr av) (cadddr av)) 2.0) (/ (+ (cadr cb) (cadddr cb)) 2.0)))
     (list (append (car sh) (TKI:Move content dx dy)) (append chosen (list ok))))))

;;; ==========================================================================
;;;  PUNCTELE: DIN DESEN SAU DIN FIȘIER
;;; ==========================================================================

;; TKI:FromSel - punctele ((nr x y z cod) ...) din setul de selecție SS:
;; COGO (cod = descrierea), POINT (cod = stratul), INSERT (cod = stratul,
;; numărul din primul atribut)
(defun TKI:FromSel (ss / i e ed o v out k)
  (setq i 0 k 0)
  (repeat (sslength ss)
    (setq e (ssname ss i) ed (entget e) i (1+ i))
    (cond
      ((= (cdr (assoc 0 ed)) "AECC_COGO_POINT")
       (setq o (vlax-ename->vla-object e)
             v (mapcar '(lambda (p / r) (setq r (vl-catch-all-apply 'vlax-get-property (list o p)))
                          (if (vl-catch-all-error-p r) nil r))
                       '(Number Easting Northing Elevation RawDescription)))
       (if (and (numberp (cadr v)) (numberp (caddr v)) (numberp (cadddr v)))
         (setq out (cons (list (vl-princ-to-string (car v)) (cadr v) (caddr v) (cadddr v)
                               (if (nth 4 v) (vl-princ-to-string (nth 4 v)) ""))
                         out))))
      ((= (cdr (assoc 0 ed)) "POINT")
       (setq v (cdr (assoc 10 ed)) k (1+ k)
             out (cons (list (strcat "P" (itoa k)) (car v) (cadr v) (caddr v) (cdr (assoc 8 ed))) out)))
      ((= (cdr (assoc 0 ed)) "INSERT")
       (setq v (cdr (assoc 10 ed)) k (1+ k) o nil)
       (if (= 1 (cdr (assoc 66 ed)))
         (setq o (entget (entnext e))))
       (setq out (cons (list (if (and o (= "ATTRIB" (cdr (assoc 0 o)))) (cdr (assoc 1 o)) (strcat "B" (itoa k)))
                             (car v) (cadr v) (caddr v) (cdr (assoc 8 ed)))
                       out)))))
  (reverse out))

;; TKI:Fields - câmpurile unui rând: (separator câmpuri); separatorul se
;; detectează: ";", tab, "," sau spații
(defun TKI:Fields (s / sep out)
  (setq sep (cond ((vl-string-search ";" s) ";") ((vl-string-search "\t" s) "\t")
                  ((vl-string-search "," s) ",") (T " ")))
  (setq out (mapcar '(lambda (x) (vl-string-trim " \t\r" x)) (TKI:SplitS s sep)))
  (list sep (if (= sep " ") (vl-remove "" out) out)))

;; TKI:Val - valoarea numerică a unui câmp (virgula zecimală acceptată dacă
;; separatorul nu este virgula)
(defun TKI:Val (s sep)
  (if (and s (/= s "")) (distof (if (/= sep ",") (vl-string-translate "," "." s) s) 2)))

;; TKI:FromFile - punctele din fișierul text F (coloanele după setarea "coloane":
;; NXYZC = Nr X Y Z Cod, NYXZC = Nr Y X Z Cod). X și Y se iau așa cum sunt în
;; fișier: abaterile nu depind de ordinea axelor.
(defun TKI:FromFile (f / fh l sp sep fl v out cols)
  (setq cols (TKI:Get "coloane"))
  (if (setq fh (open f "r"))
    (progn
      (while (setq l (read-line fh))
        (setq l (vl-string-trim " \t\r" l))
        (if (and (/= l "") (/= (substr l 1 1) "#"))
          (progn
            (setq sp (TKI:Fields l) sep (car sp) fl (cadr sp)
                  v (mapcar '(lambda (s) (TKI:Val s sep)) (list (nth 1 fl) (nth 2 fl) (nth 3 fl))))
            (if (not (member nil v))
              (setq out (cons (list (car fl)
                                    (if (= cols "NYXZC") (cadr v) (car v))
                                    (if (= cols "NYXZC") (car v) (cadr v))
                                    (caddr v)
                                    (cond ((nth 4 fl)) ("")))
                              out))))))
      (close fh)))
  (reverse out))

;; TKI:Codes - codurile distincte ale punctelor, sortate
(defun TKI:Codes (pts / out)
  (foreach p pts (if (and (/= (nth 4 p) "") (not (member (nth 4 p) out))) (setq out (cons (nth 4 p) out))))
  (acad_strlsort out))

;; TKI:Guess - propune codurile (stânga dreapta spate) din codurile găsite
(defun TKI:Guess (codes / l r s c lc)
  (foreach c codes
    (setq lc (strcase c T))
    (cond
      ((or (vl-string-search "spate" lc) (vl-string-search "back" lc)) (if (not s) (setq s c)))
      ((vl-some '(lambda (p) (= 0 (vl-string-search p lc))) '("stanga" "stg" "st_" "s_" "s-" "left" "l_"))
       (if (not l) (setq l c)))
      ((vl-some '(lambda (p) (= 0 (vl-string-search p lc))) '("dreapta" "dr" "d_" "d-" "right" "r_"))
       (if (not r) (setq r c)))))
  (list l r s))

;;; ==========================================================================
;;;  DESENAREA
;;; ==========================================================================

;; TKI:Draw - desenează elementele ITEMS cu originea foii în BASE, pe stratul LAY
(defun TKI:Draw (items base lay / bx by p st)
  (setq bx (car base) by (cadr base) st (TK:Style))
  (TK:MakeLayer lay 7)
  (foreach it items
    (cond
      ((= (car it) "line")
       (entmake (list '(0 . "LINE") (cons 8 lay) (cons 62 (cadddr it))
                      (list 10 (+ bx (car (cadr it))) (+ by (cadr (cadr it))) 0.0)
                      (list 11 (+ bx (car (caddr it))) (+ by (cadr (caddr it))) 0.0))))
      ((= (car it) "pline")
       (entmake (append (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") (cons 8 lay) (cons 62 (caddr it))
                              '(100 . "AcDbPolyline") (cons 90 (length (cadr it))) '(70 . 0) (cons 43 (cadddr it)))
                        (mapcar '(lambda (p) (list 10 (+ bx (car p)) (+ by (cadr p)))) (cadr it)))))
      ((= (car it) "circle")
       (entmake (list '(0 . "CIRCLE") (cons 8 lay) (cons 62 (cadddr it))
                      (list 10 (+ bx (car (cadr it))) (+ by (cadr (cadr it))) 0.0) (cons 40 (caddr it)))))
      (T
       (setq p (list (+ bx (car (cadr it))) (+ by (cadr (cadr it))) 0.0))
       (entmake (list '(0 . "TEXT") (cons 8 lay) (cons 62 (nth 4 it)) (cons 7 st) (cons 10 p) (cons 11 p)
                      (cons 40 (nth 3 it)) (cons 1 (nth 2 it)) '(50 . 0.0)
                      (cons 72 (cdr (assoc (nth 5 it) '(("L" . 0) ("C" . 1) ("R" . 2))))) '(73 . 2)))))))

;; TKI:Report - rezumatul în linia de comandă (câte un rând pentru fiecare rând de puncte)
(defun TKI:Report (rows info / tt)
  (foreach row rows
    (setq tt (cadddr row))
    (princ (strcat "\n  " (car (car row)) ": " (itoa (length (cadr row))) " puncte, varf "
                   (TKI:FmtVal (nth 4 tt)) " la H=" (TKI:Fmt (cadr tt) 2) " m ("
                   (TKI:Fmt (if (> (cadr tt) 0.0) (* 100.0 (/ (nth 4 tt) (cadr tt))) 0.0) 2)
                   "%), spre " (if (> (caddr row) 0) "dreapta" "stanga"))))
  (foreach m *TKI:MSGS* (princ (strcat "\n  ! " m)))
  (if info
    (princ (strcat "\n  Plansa: "
                   (if (= (car info) "fara") (strcat "fara format, texte pentru scara 1:" (itoa (caddr info)))
                     (strcat (car info) " " (cadr info) ", scara 1:" (itoa (caddr info))))
                   (if (cadddr info) "" "  - ATENTIE: desenul nu incape; alegeti un format sau o scara mai mare.")))))

;;; ==========================================================================
;;;  DIALOGUL
;;; ==========================================================================

(setq *TKI:CHOICES*
       '(("pl_potr" "potrivire" ("exact" "incepe cu" "contine"))
         ("pl_abat" "abatere" ("totala" "proiectata"))
         ("pl_unit" "unitate" ("cm" "mm" "m"))
         ("pl_fmt" "format" ("auto" "fara" "A4" "A3" "A2" "A1" "A0"))
         ("pl_ori" "orientare" ("auto" "portret" "peisaj"))
         ("pl_scara" "scara" ("auto" "1:100" "1:200" "1:500" "1:1000" "1:2000"))
         ("pl_prio" "prioritate" ("scara mare" "format mic"))))
(setq *TKI:EDITS* '(("eb_zec" . "zecimale") ("eb_text" . "text_mm") ("eb_titlu" . "titlu") ("eb_ben" . "beneficiar")
                    ("eb_obi" . "obiectiv") ("eb_int" . "intocmit") ("eb_nr" . "plansa") ("eb_strat" . "strat")))
(setq *TKI:TOGGLES* '(("tg_cartus" . "cartus") ("tg_h" . "arata_h") ("tg_z" . "arata_z") ("tg_evita" . "evita")
                      ("tg_leg" . "legenda")))
(setq *TKI:DIRS* '("auto" "stanga" "dreapta"))

;; TKI:DclPath - TopoKitInclinare.dcl (sau o copie generată din TKI:DclLines)
(defun TKI:DclPath (/ f lsp fh)
  (cond
    ((findfile "TopoKitInclinare.dcl"))
    ((and (setq lsp (findfile "TopoKitInclinare.lsp"))
          (findfile (setq f (strcat (vl-filename-directory lsp) "\\TopoKitInclinare.dcl"))))
     f)
    ((and *TKI:DCLTMP* (findfile *TKI:DCLTMP*)) *TKI:DCLTMP*)
    ((setq fh (open (setq f (vl-filename-mktemp "TopoKitInclinare" nil ".dcl")) "w"))
     (foreach l (TKI:DclLines) (write-line l fh))
     (close fh)
     (setq *TKI:DCLTMP* f))))

;; TKI:Preview - recalculează și afișează rezultatul în dialog (bara de stare)
(defun TKI:Preview (/ rows lay s)
  (TKI:ReadTiles)
  (setq rows (TKI:Compute *TKI:PTS*))
  (cond
    ((null *TKI:PTS*) (set_tile "tx_rez" "Niciun punct."))
    ((null rows)
     (set_tile "tx_rez" (strcat "Niciun rand potrivit. Coduri gasite: " (TKI:Join (TKI:Codes *TKI:PTS*) ", "))))
    (T
     (setq lay (TKI:Layout rows) s "")
     (foreach row rows
       (setq s (strcat s (car (car row)) ": " (TKI:FmtVal (nth 4 (cadddr row))) " spre "
                       (if (> (caddr row) 0) "dreapta" "stanga") "   ")))
     (set_tile "tx_rez" s)
     (set_tile "tx_plansa"
               (if (= (car (cadr lay)) "fara") (strcat "Fara format, texte pentru 1:" (itoa (caddr (cadr lay))))
                 (strcat "Plansa " (car (cadr lay)) " " (cadr (cadr lay)) ", scara 1:" (itoa (caddr (cadr lay)))
                         (if (cadddr (cadr lay)) "" "  - NU INCAPE")))))))

(defun TKI:Join (l sep / s)
  (setq s "")
  (foreach x l (setq s (if (= s "") x (strcat s sep x))))
  s)

;; TKI:Fill - completează o listă derulantă
(defun TKI:Fill (key items) (start_list key) (foreach i items (add_list i)) (end_list))

;; TKI:ReadTiles - citește valorile din dialog în setări
(defun TKI:ReadTiles (/ i)
  (foreach c *TKI:CHOICES* (TKI:Set (cadr c) (nth (atoi (get_tile (car c))) (caddr c))))
  (foreach e *TKI:EDITS* (TKI:Set (cdr e) (vl-string-trim " " (get_tile (car e)))))
  (foreach tg *TKI:TOGGLES* (TKI:Set (cdr tg) (get_tile (car tg))))
  (setq i 1)
  (repeat 4
    (TKI:Set (strcat "rand" (itoa i))
             (strcat (vl-string-trim " |" (get_tile (strcat "eb_cod" (itoa i)))) "|"
                     (vl-string-trim "|" (get_tile (strcat "eb_tit" (itoa i)))) "|"
                     (nth (atoi (get_tile (strcat "pl_dir" (itoa i)))) *TKI:DIRS*)))
    (setq i (1+ i))))

;; TKI:Validate - verifică valorile numerice (T dacă sunt corecte)
(defun TKI:Validate (/ z th)
  (setq z (distof (get_tile "eb_zec") 2) th (distof (get_tile "eb_text") 2))
  (cond
    ((or (null z) (< z 0) (> z 4)) (set_tile "error" "Zecimale: 0...4.") nil)
    ((or (null th) (< th 0.5) (> th 10)) (set_tile "error" "Inaltimea textului: 0.5...10 mm.") nil)
    ((null (TKI:Compute (progn (TKI:ReadTiles) *TKI:PTS*)))
     (set_tile "error" "Niciun rand nu are minim 2 puncte: alegeti codurile randurilor.") nil)
    (T (set_tile "error" "") T)))

;; TKI:PickCode - pune codul ales din lista CODURI în rândul I
(defun TKI:PickCode (i v / codes c)
  (setq codes (TKI:Codes *TKI:PTS*))
  (if (and (> (atoi v) 0) (setq c (nth (1- (atoi v)) codes)))
    (progn
      (set_tile (strcat "eb_cod" (itoa i)) c)
      (if (= (get_tile (strcat "eb_tit" (itoa i))) "")
        (set_tile (strcat "eb_tit" (itoa i)) (strcat "PARTEA " (strcase (TKI:Ascii c)))))
      (set_tile (strcat "pl_cod" (itoa i)) "0")))
  (TKI:Preview))

;; TKI:Dialog - dialogul planului; T dacă s-a ales OK
(defun TKI:Dialog (/ id res i r codes g)
  (setq id (load_dialog (TKI:DclPath)) codes (TKI:Codes *TKI:PTS*))
  ;; codurile din setări nu se potrivesc: propunerea automată
  (if (and codes (null (TKI:Compute *TKI:PTS*)))
    (progn
      (setq g (TKI:Guess codes))
      (TKI:Set "rand1" (strcat (cond ((car g)) ((car codes))) "|PARTEA STANGA|auto"))
      (TKI:Set "rand2" (strcat (cond ((cadr g)) ((cadr codes)) ("")) "|PARTEA DREAPTA|auto"))
      (TKI:Set "rand3" (if (caddr g) (strcat (caddr g) "|SPATE|dreapta") "||auto"))
      (TKI:Set "rand4" "||auto")))
  (cond
    ((< id 0) (alert "Nu s-a putut incarca TopoKitInclinare.dcl.") nil)
    ((not (new_dialog "tki_main" id)) (unload_dialog id) nil)
    (T
     (set_tile "tx_pct" (strcat (itoa (length *TKI:PTS*)) " puncte; coduri: " (TKI:Join codes ", ")))
     (setq i 1)
     (repeat 4
       (setq r (TKI:SplitS (TKI:Get (strcat "rand" (itoa i))) "|"))
       (while (< (length r) 3) (setq r (append r (list ""))))
       (set_tile (strcat "eb_cod" (itoa i)) (car r))
       (set_tile (strcat "eb_tit" (itoa i)) (cadr r))
       (TKI:Fill (strcat "pl_dir" (itoa i)) *TKI:DIRS*)
       (set_tile (strcat "pl_dir" (itoa i)) (itoa (cond ((vl-position (caddr r) *TKI:DIRS*)) (0))))
       (TKI:Fill (strcat "pl_cod" (itoa i)) (cons "<coduri>" codes))
       (set_tile (strcat "pl_cod" (itoa i)) "0")
       (action_tile (strcat "pl_cod" (itoa i)) (strcat "(TKI:PickCode " (itoa i) " $value)"))
       (foreach k (list "eb_cod" "eb_tit" "pl_dir") (action_tile (strcat k (itoa i)) "(TKI:Preview)"))
       (setq i (1+ i)))
     (foreach c *TKI:CHOICES*
       (TKI:Fill (car c) (caddr c))
       (set_tile (car c) (itoa (cond ((vl-position (TKI:Get (cadr c)) (caddr c))) (0))))
       (action_tile (car c) "(TKI:Preview)"))
     (foreach e *TKI:EDITS* (set_tile (car e) (TKI:Get (cdr e))) (action_tile (car e) "(TKI:Preview)"))
     (foreach tg *TKI:TOGGLES* (set_tile (car tg) (TKI:Get (cdr tg))) (action_tile (car tg) "(TKI:Preview)"))
     (TKI:Preview)
     (action_tile "accept" "(if (TKI:Validate) (done_dialog 1))")
     (action_tile "cancel" "(done_dialog 0)")
     (setq res (start_dialog))
     (unload_dialog id)
     (= res 1))))

;;; ==========================================================================
;;;  COMANDA
;;; ==========================================================================

;; TKI:GetPoints - punctele: selecție în desen sau fișier (Enter = fișier)
(defun TKI:GetPoints (/ ss f)
  (princ "\nSelectati punctele masurate (puncte COGO, puncte AutoCAD, blocuri) sau Enter pentru fisier CSV/TXT: ")
  (if (setq ss (ssget '((0 . "AECC_COGO_POINT,POINT,INSERT"))))
    (TKI:FromSel ss)
    (if (setq f (getfiled "Fisier cu puncte (Nr, X, Y, Z, Cod)" (getvar "DWGPREFIX") "csv;txt;pnt;dat;xyz" 0))
      (TKI:FromFile f))))

;; TKI:Run - comanda INCLINARE
(defun TKI:Run (/ *error* rows lay base)
  (defun *error* (msg) (TK:Error msg))
  (TK:Start)
  (setq *TKI:CFG* nil)
  (cond
    ((null (setq *TKI:PTS* (TKI:GetPoints))) (princ "\nNiciun punct (sunt necesare puncte 3D cu cod)."))
    ((not (TKI:Dialog)) (princ "\nAnulat."))
    ((null (setq rows (TKI:Compute *TKI:PTS*))) (princ "\nNiciun rand nu are minim 2 puncte."))
    (T
     (TKI:Save)
     (setq lay (TKI:Layout rows))
     (if (/= (strcase (getvar "CTAB")) "MODEL") (setvar "CTAB" "Model"))
     (if (setq base (getpoint "\nColtul stanga-jos al planului <0,0>: ")) nil (setq base '(0.0 0.0 0.0)))
     (TKI:Draw (car lay) base (TKI:Get "strat"))
     (princ (strcat "\nPlanul de inclinare a fost desenat pe stratul " (TKI:Get "strat") ":"))
     (TKI:Report rows (cadr lay))
     (vl-catch-all-apply 'vla-ZoomExtents (list (vlax-get-acad-object)))))
  (TK:Stop)
  (princ))

(defun c:INCLINARE () (TKI:Run))

;;; ==========================================================================
;;;  PROGRAMUL PLAN INCLINARE (PlanInclinare.exe, instalat cu TopoKit)
;;; ==========================================================================

;; TKI:AppExe - calea programului Plan Inclinare (folderul de instalare TopoKit)
(defun TKI:AppExe (/ d f)
  (if (and (setq d (vl-registry-read "HKEY_CURRENT_USER\\Software\\TopoKit" "InstallDir"))
           (findfile (setq f (strcat (vl-string-right-trim "\\" d) "\\PlanInclinare\\PlanInclinare.exe"))))
    f))

;; TKI:PointsFile - fișierul prin care punctele selectate ajung în program
(defun TKI:PointsFile () (strcat (TK:TempDir) "TopoKit_PlanInclinare_puncte.csv"))

;; C:PLANINCL - pornește programul Plan Inclinare (drag & drop CSV/TXT/DWG/DXF,
;; previzualizare, export DXF/DWG); fără program, planul se desenează în AutoCAD
(defun c:PLANINCL (/ exe)
  (if (setq exe (TKI:AppExe))
    (progn (startapp exe) (princ "\nPlan Inclinare a fost pornit."))
    (progn (princ "\nPlanInclinare.exe nu a fost gasit (reinstalati TopoKit); se foloseste INCLINARE.")
           (TKI:Run)))
  (princ))

;; C:PLANINCLSEL - selecția punctelor din desenul deschis pentru programul
;; Plan Inclinare (butonul "Puncte din AutoCAD"): Nr;X;Y;Z;Cod în fișierul comun.
;; Fără selecție se scrie un fișier gol (programul nu mai așteaptă).
(defun c:PLANINCLSEL (/ *error* ss pts f tmp fh)
  (defun *error* (msg) (TK:Error msg))
  (TK:Start)
  (setq f (TKI:PointsFile) tmp (strcat f ".tmp"))
  (princ "\nPlan Inclinare - selectati punctele masurate (puncte COGO, puncte AutoCAD, blocuri): ")
  (setq ss (ssget '((0 . "AECC_COGO_POINT,POINT,INSERT")))
        pts (if ss (TKI:FromSel ss)))
  (if (findfile tmp) (vl-file-delete tmp))
  (if (setq fh (open tmp "w"))
    (progn
      (foreach p pts
        (write-line (strcat (car p) ";" (TKI:Fmt (cadr p) 4) ";" (TKI:Fmt (caddr p) 4) ";" (TKI:Fmt (nth 3 p) 4)
                            ";" (vl-string-translate ";" "," (TKI:Ascii (nth 4 p))))
                    fh))
      (close fh)
      (if (findfile f) (vl-file-delete f))
      (vl-file-rename tmp f)))
  (princ (if pts (strcat "\n" (itoa (length pts)) " puncte trimise programului Plan Inclinare.")
           "\nNiciun punct selectat."))
  (TK:Stop)
  (princ))

;;; ==========================================================================
;;;  DIALOGUL (COPIE PENTRU GENERAREA AUTOMATĂ)
;;; ==========================================================================
;; TKI:DclLines - conținutul fișierului TopoKitInclinare.dcl
;; (Secțiune generată din TopoKitInclinare.dcl cu tools/embed_dcl.py - nu editați manual.)
;;@@DCL-BEGIN@@
(defun TKI:DclLines ()
  (list
    "// ==========================================================================="
    "//  TopoKitInclinare.dcl - dialogul planului de inclinare TopoKit (comanda INCLINARE)"
    "//  Fisierul este optional: daca lipseste, TopoKitInclinare.lsp genereaza automat"
    "//  o copie identica intr-un fisier temporar."
    "// ==========================================================================="
    ""
    "tki_cod : edit_box { edit_width = 14; width = 16; fixed_width = true; }"
    "tki_lst : popup_list { width = 14; fixed_width = true; }"
    "tki_tit : edit_box { edit_width = 22; width = 24; fixed_width = true; }"
    "tki_dir : popup_list { width = 10; fixed_width = true; }"
    "tki_pl : popup_list { edit_width = 12; }"
    "tki_eb : edit_box { edit_width = 26; }"
    ""
    "tki_main : dialog {"
    "  label = \"TopoKit - Plan de inclinare (verticalitate)\";"
    "  : text { key = \"tx_pct\"; label = \"\"; width = 96; }"
    "  : boxed_column {"
    "    label = \"Randuri, de la stanga la dreapta (codul punctelor; mai multe coduri separate prin virgula)\";"
    "    : row {"
    "      fixed_width = true;"
    "      : text { label = \"Cod\"; width = 16; fixed_width = true; }"
    "      : text { label = \"Alege din coduri\"; width = 16; fixed_width = true; }"
    "      : text { label = \"Titlu in plan\"; width = 24; fixed_width = true; }"
    "      : text { label = \"Aplecare\"; width = 10; fixed_width = true; }"
    "    }"
    "    : row { fixed_width = true; : tki_cod { key = \"eb_cod1\"; } : tki_lst { key = \"pl_cod1\"; } : tki_tit { key = \"eb_tit1\"; } : tki_dir { key = \"pl_dir1\"; } }"
    "    : row { fixed_width = true; : tki_cod { key = \"eb_cod2\"; } : tki_lst { key = \"pl_cod2\"; } : tki_tit { key = \"eb_tit2\"; } : tki_dir { key = \"pl_dir2\"; } }"
    "    : row { fixed_width = true; : tki_cod { key = \"eb_cod3\"; } : tki_lst { key = \"pl_cod3\"; } : tki_tit { key = \"eb_tit3\"; } : tki_dir { key = \"pl_dir3\"; } }"
    "    : row { fixed_width = true; : tki_cod { key = \"eb_cod4\"; } : tki_lst { key = \"pl_cod4\"; } : tki_tit { key = \"eb_tit4\"; } : tki_dir { key = \"pl_dir4\"; } }"
    "  }"
    "  : row {"
    "    : boxed_column {"
    "      label = \"Calcul\";"
    "      : tki_pl { key = \"pl_potr\"; label = \"Potrivire cod:\"; }"
    "      : tki_pl { key = \"pl_abat\"; label = \"Abatere:\"; }"
    "      : tki_pl { key = \"pl_unit\"; label = \"Unitate:\"; }"
    "      : edit_box { key = \"eb_zec\"; label = \"Zecimale:\"; edit_width = 4; }"
    "      : toggle { key = \"tg_h\"; label = \"Inaltimea H la puncte\"; }"
    "      : toggle { key = \"tg_z\"; label = \"Cota Z la puncte\"; }"
    "      : toggle { key = \"tg_evita\"; label = \"Ascunde etichetele suprapuse\"; }"
    "      : toggle { key = \"tg_leg\"; label = \"Legenda\"; }"
    "    }"
    "    : boxed_column {"
    "      label = \"Plansa\";"
    "      : tki_pl { key = \"pl_fmt\"; label = \"Format:\"; }"
    "      : tki_pl { key = \"pl_ori\"; label = \"Orientare:\"; }"
    "      : tki_pl { key = \"pl_scara\"; label = \"Scara:\"; }"
    "      : tki_pl { key = \"pl_prio\"; label = \"Automat prefera:\"; }"
    "      : edit_box { key = \"eb_text\"; label = \"Inaltime text (mm):\"; edit_width = 5; }"
    "      : edit_box { key = \"eb_strat\"; label = \"Strat:\"; edit_width = 16; }"
    "      : toggle { key = \"tg_cartus\"; label = \"Chenar cu cartus\"; }"
    "    }"
    "    : boxed_column {"
    "      label = \"Cartus\";"
    "      : tki_eb { key = \"eb_titlu\"; label = \"Titlu:\"; }"
    "      : tki_eb { key = \"eb_ben\"; label = \"Beneficiar:\"; }"
    "      : tki_eb { key = \"eb_obi\"; label = \"Obiectiv:\"; }"
    "      : tki_eb { key = \"eb_int\"; label = \"Intocmit:\"; }"
    "      : edit_box { key = \"eb_nr\"; label = \"Plansa nr.:\"; edit_width = 6; }"
    "    }"
    "  }"
    "  : boxed_column {"
    "    label = \"Rezultat\";"
    "    : text { key = \"tx_rez\"; label = \"\"; width = 96; }"
    "    : text { key = \"tx_plansa\"; label = \"\"; width = 96; }"
    "  }"
    "  : text { label = \"Verticala fiecarui rand trece prin punctul lui cel mai de jos. Desenul este 1:1 (metri); scara mareste chenarul si textele.\"; }"
    "  ok_cancel;"
    "  errtile;"
    "}"))
;;@@DCL-END@@

(setq *TKI:LOADING* nil)
(princ "\nTopoKit Inclinare incarcat. Comenzi: PLANINCL (programul Plan Inclinare), INCLINARE (planul direct in desen), PLANINCLSEL.")
(princ)
