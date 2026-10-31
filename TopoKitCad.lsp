;;; ==========================================================================
;;;  TopoKitCad.lsp  -  Cadastru TopoKit: puncte TopoLT, suprafete, detasari,
;;;  cotari, suma textelor, import / export coordonate
;;; ==========================================================================
;;;
;;;  Preluat din CadTopo.lsp (functiile care lipseau din TopoKit), cu erorile
;;;  corectate. Comenzi:
;;;    TKPCT       - introducere puncte (bloc "Punct" ca in TopoLT)
;;;    TKPCTCONTUR - puncte in varfurile poliliniilor, fara dubluri
;;;    TKIMPPCT    - raporteaza puncte din fisier (Nr X Y [Z] [Cod]) ca blocuri TopoLT
;;;    TKEXPPCT    - reface fisierul de coordonate din punctele desenului
;;;    TKSTERGPCT  - sterge puncte (bloc + textele legate)
;;;    TKRENUM     - renumeroteaza punctele, pe rand (verifica dublurile)
;;;    TKSELCOD    - selecteaza punctele dupa cod (* si ?)
;;;    TKSCHCOD    - schimba codul punctelor
;;;    TKSUPRAF    - suprafete: S= in centrul poligonului, optional hasura
;;;    TKDETASARE  - detaseaza o suprafata (paralela, directie, perpendiculara,
;;;                  punct obligat)
;;;    TKDETMULT   - detasari multiple dintr-un tabel (manual sau Excel / CSV)
;;;    TKCOTE      - coteaza laturile poliliniilor, spre exterior
;;;    TKSUMA      - suma numerelor din texte
;;;    TKCADSET    - setarile modulului (scara, inaltimi in mm, zecimale)
;;;    TKCAD       - lista comenzilor
;;;
;;;  Punctele sunt compatibile cu desenele TopoLT / CadTopo: bloc "Punct" pe
;;;  stratul 0_pnt_symbols cu atributele DENPCT, COTA, COD, textul numarului
;;;  pe 0_pnt_number, legate prin XDATA (TOPOLT, CTOPO).
;;;  Setarile se pastreaza in desen (ca la CadTopo, in mm pe hartie).
;;;  Mesajele sunt fara diacritice (AutoCAD citeste .lsp ca ANSI cu LISPSYS=0).
;;;  Necesita TopoKit.lsp.
;;; ==========================================================================

(vl-load-com)
(setq *TKC:LOADING* T)
(if (and (not TK:Start) (findfile "TopoKit.lsp")) (load (findfile "TopoKit.lsp")))

(setq *TKC:BLK* "Punct" *TKC:LAYSYM* "0_pnt_symbols" *TKC:LAYNR* "0_pnt_number"
      *TKC:LAYDIM* "Dimensions" *TKC:LAYSUP* "Suprafete" *TKC:LAYHAT* "Hasuri")

;; Setarile implicite (marimi in mm pe hartie, ca la TopoLT / CadTopo)
(setq *TKC:DEF*
       '(("SCARA" . 1000.0) ("FONT" . "TK_ARIAL")
         ("PCT_H" . 1.2) ("PCT_COD" . "Grf") ("PCT_DMIN" . 0.03)
         ("SUP_H" . 1.2) ("SUP_HASH" . 0) ("SUP_PAT" . "ANSI31") ("DET_RUPE" . 1)
         ("COT_H" . 1.2) ("COT_PRE" . "") ("COT_SUF" . "m") ("COT_DEC" . 2)
         ("UN_COORD" . 3) ("UN_DIST" . 2) ("UN_SUP" . 2)))

;;; ==========================================================================
;;;  UTILITARE
;;; ==========================================================================

;; TKC:F - numar cu D zecimale fixe (independent de DIMZIN)
(defun TKC:F (v d / z r)
  (setq z (getvar "DIMZIN"))
  (if z (setvar "DIMZIN" 0))
  (setq r (rtos v 2 d))
  (if z (setvar "DIMZIN" z))
  r)

;; TKC:Num0 - numar fara zerouri inutile (1000, 1.2, 0.03)
(defun TKC:Num0 (v / z r)
  (setq z (getvar "DIMZIN"))
  (if z (setvar "DIMZIN" 8))
  (setq r (rtos v 2 6))
  (if z (setvar "DIMZIN" z))
  r)

(defun TKC:Msg (s) (princ (strcat "\n" s)))

;; vectori 2D
(defun TKC:v- (a b) (list (- (car a) (car b)) (- (cadr a) (cadr b))))
(defun TKC:v+ (a b) (list (+ (car a) (car b)) (+ (cadr a) (cadr b))))
(defun TKC:v* (a k) (list (* (car a) k) (* (cadr a) k)))
(defun TKC:Dot (a b) (+ (* (car a) (car b)) (* (cadr a) (cadr b))))
(defun TKC:Perp (a) (list (- (cadr a)) (car a)))
(defun TKC:Unit (a) (TKC:v* a (/ 1.0 (distance '(0.0 0.0) (TK:2d a)))))

;; TKC:Slice - elementele A .. B-1 ale listei L
;; (in CadTopo functia se numea ct:sub si era suprascrisa de functia de meniu
;;  cu acelasi nume: detasarea prin punct obligat dadea eroare)
(defun TKC:Slice (l a b / r i)
  (setq i a)
  (while (< i b) (setq r (cons (nth i l) r) i (1+ i)))
  (reverse r))

;; TKC:SArea - dublul ariei cu semn (> 0 = sens trigonometric)
(defun TKC:SArea (pts / s n p q i)
  (setq s 0.0 n (length pts) i 0)
  (repeat n
    (setq p (nth i pts) q (nth (rem (1+ i) n) pts)
          s (+ s (- (* (car p) (cadr q)) (* (car q) (cadr p))))
          i (1+ i)))
  s)

(defun TKC:Area (pts) (if (> (length pts) 2) (abs (/ (TKC:SArea pts) 2.0)) 0.0))

;; TKC:Centroid - centrul de greutate al poligonului (coordonate locale, precizie)
(defun TKC:Centroid (pts / p0 a cx cy n p q c i)
  (setq p0 (car pts) a 0.0 cx 0.0 cy 0.0 n (length pts) i 0
        pts (mapcar '(lambda (p) (TKC:v- p p0)) pts))
  (repeat n
    (setq p (nth i pts) q (nth (rem (1+ i) n) pts)
          c (- (* (car p) (cadr q)) (* (car q) (cadr p)))
          a (+ a c)
          cx (+ cx (* (+ (car p) (car q)) c))
          cy (+ cy (* (+ (cadr p) (cadr q)) c))
          i (1+ i)))
  (if (equal a 0.0 1e-9)
    p0
    (list (+ (car p0) (/ cx (* 3.0 a))) (+ (cadr p0) (/ cy (* 3.0 a))))))

;; TKC:PlPts - varfurile (x y) ale unei LWPOLYLINE
(defun TKC:PlPts (en)
  (mapcar '(lambda (x) (list (cadr x) (caddr x)))
          (vl-remove-if-not '(lambda (x) (= 10 (car x))) (entget en))))

;; TKC:HasArcs - T daca polilinia are laturi in arc (bulge)
(defun TKC:HasArcs (en)
  (vl-some '(lambda (x) (and (= 42 (car x)) (not (equal (cdr x) 0.0 1e-12)))) (entget en)))

(defun TKC:Closed (d) (= 1 (logand 1 (cond ((cdr (assoc 70 d))) (0)))))

;; TKC:Clean - elimina varfurile duble consecutive (si inchiderea repetata)
(defun TKC:Clean (pts / out)
  (foreach p pts
    (if (or (null out) (> (distance (TK:2d p) (TK:2d (car out))) 1e-7)) (setq out (cons p out))))
  (setq out (reverse out))
  (if (and (> (length out) 2) (< (distance (TK:2d (car out)) (TK:2d (last out))) 1e-7))
    (setq out (reverse (cdr (reverse out)))))
  out)

;; TKC:Fields - campurile unui rand: separatorul se detecteaza (";", tab, ",",
;; spatii); virgula zecimala se accepta cand separatorul nu este virgula
(defun TKC:Fields (s / sep out cur)
  (setq sep (cond ((vl-string-search ";" s) ";") ((vl-string-search "\t" s) "\t")
                  ((and (vl-string-search "," s) (not (vl-string-search " " (vl-string-trim " " s)))) ",")
                  (T " "))
        cur "")
  (foreach c (vl-string->list s)
    (if (= (chr c) sep) (setq out (cons cur out) cur "") (setq cur (strcat cur (chr c)))))
  (setq out (mapcar '(lambda (x) (vl-string-trim " \t\r\"" x)) (reverse (cons cur out))))
  (list sep (if (= sep " ") (vl-remove "" out) out)))

(defun TKC:Val (s sep)
  (if (and s (/= s "")) (distof (if (/= sep ",") (vl-string-translate "," "." s) s) 2)))

;;; ==========================================================================
;;;  SETARI (pastrate in desen, ldata "TOPOKIT" "CAD"; citite si din CadTopo)
;;; ==========================================================================

(defun TKC:Merge (l / p)
  (mapcar '(lambda (d) (if (and (setq p (assoc (car d) l)) (= (type (cdr p)) (type (cdr d)))) p d))
          *TKC:DEF*))

(defun TKC:ReadCfg (s / r)
  (if (and (= 'STR (type s))
           (not (vl-catch-all-error-p (setq r (vl-catch-all-apply 'read (list s)))))
           (listp r) r)
    (TKC:Merge r)))

;; TKC:DefCfg - setarile implicite, cu scara planului din setarile TopoKit (implicit 1:500),
;; ca textele sa aiba aceeasi marime ca formatul / cadrul planului
(defun TKC:DefCfg (/ sc)
  (setq sc (if (and (numberp *TK:SCARA*) (listp *TK:SCARI*)) (nth *TK:SCARA* *TK:SCARI*)))
  (if (numberp sc) (subst (cons "SCARA" (float sc)) (assoc "SCARA" *TKC:DEF*) *TKC:DEF*) *TKC:DEF*))

(defun TKC:CfgAll ()
  (if (null *TKC:CFG*)
    (progn
      (setq *TKC:CFG* (cond ((TKC:ReadCfg (vlax-ldata-get "TOPOKIT" "CAD")))
                            ((TKC:ReadCfg (vlax-ldata-get "CTOPO" "CFG")))
                            ((TKC:DefCfg))))
      (TKC:Apply)))
  *TKC:CFG*)

(defun TKC:Cfg (k) (cdr (assoc k (TKC:CfgAll))))

;; TKC:Apply - marimile in unitati de desen (setarile sunt in mm pe hartie)
(defun TKC:Apply (/ k)
  (setq k (/ (TKC:Cfg "SCARA") 1000.0)
        *TKC:TXTH* (* k (TKC:Cfg "PCT_H"))
        *TKC:SUPH* (* k (TKC:Cfg "SUP_H"))
        *TKC:COTH* (* k (TKC:Cfg "COT_H"))
        *TKC:DX*   (* 0.3 *TKC:TXTH*)
        *TKC:COTOFF* (* 0.65 *TKC:COTH*)))

(defun TKC:SaveCfg ()
  (vlax-ldata-put "TOPOKIT" "CAD" (vl-prin1-to-string *TKC:CFG*))
  (TKC:Apply))

;; TKC:Style - stilul de text (TIMES_NEW_ROMAN se creeaza, ca in TopoLT)
(defun TKC:Style (/ s)
  (setq s (TKC:Cfg "FONT"))
  (cond ((= (strcase s) "TK_ARIAL") (TK:Style))      ; stilul TopoKit (Arial), ca in restul planului
        ((tblsearch "STYLE" s) s)
        ((= (strcase s) "TIMES_NEW_ROMAN")
         (entmake '((0 . "STYLE") (100 . "AcDbSymbolTableRecord") (100 . "AcDbTextStyleTableRecord")
                    (2 . "TIMES_NEW_ROMAN") (70 . 0) (40 . 0.0) (41 . 1.0) (50 . 0.0) (71 . 0) (42 . 1.2)
                    (3 . "times.ttf") (4 . "")))
         s)
        (T (getvar "TEXTSTYLE"))))

;; TKC:Txt - text; HA 0 stanga, 1 centru, 2 dreapta; VA 0 baza, 2 mijloc
(defun TKC:Txt (p s lay h rot ha va / l)
  (setq l (list '(0 . "TEXT") (cons 8 lay) (cons 7 (TKC:Style)) (list 10 (car p) (cadr p) 0.0)
                (cons 40 h) (cons 1 s) (cons 50 rot)))
  (if (or (/= ha 0) (/= va 0))
    (setq l (append l (list (list 11 (car p) (cadr p) 0.0) (cons 72 ha) (cons 73 va)))))
  (entmake l)
  (entlast))

(defun TKC:Line (p q lay)
  (entmake (list '(0 . "LINE") (cons 8 lay) (list 10 (car p) (cadr p) 0.0) (list 11 (car q) (cadr q) 0.0))))

;;; ==========================================================================
;;;  PUNCTE (bloc "Punct", compatibil TopoLT / CadTopo)
;;; ==========================================================================

(defun TKC:IsP (en / d)
  (and en (setq d (entget en)) (= "INSERT" (cdr (assoc 0 d)))
       (= (strcase *TKC:BLK*) (strcase (cdr (assoc 2 d))))))

(defun TKC:Att (en tag / e d v)
  (setq e (entnext en))
  (while (and e (= "ATTRIB" (cdr (assoc 0 (setq d (entget e))))))
    (if (= (strcase tag) (strcase (cdr (assoc 2 d)))) (setq v (cdr (assoc 1 d))))
    (setq e (entnext e)))
  v)

(defun TKC:SetAtt (en tag val / e d)
  (setq e (entnext en))
  (while (and e (= "ATTRIB" (cdr (assoc 0 (setq d (entget e))))))
    (if (= (strcase tag) (strcase (cdr (assoc 2 d)))) (entmod (subst (cons 1 val) (assoc 1 d) d)))
    (setq e (entnext e)))
  (entupd en))

;; TKC:Linked - entitatile legate de punct prin XDATA (TOPOLT, CTOPO)
(defun TKC:Linked (en / x l e)
  (setq x (assoc -3 (entget en '("TOPOLT" "CTOPO"))))
  (foreach app (cdr x)
    (foreach it (cdr app)
      (if (and (= 1005 (car it)) (/= "0" (cdr it)) (setq e (handent (cdr it))) (entget e))
        (setq l (cons e l)))))
  l)

(defun TKC:NrTxt (en / r d)
  (foreach e (TKC:Linked en)
    (setq d (entget e))
    (if (and (= "TEXT" (cdr (assoc 0 d))) (= (strcase *TKC:LAYNR*) (strcase (cdr (assoc 8 d)))))
      (setq r e)))
  r)

(defun TKC:Link (en tx)
  (regapp "CTOPO")
  (entmod (append (entget en) (list (list -3 (list "CTOPO" (cons 1005 (cdr (assoc 5 (entget tx))))))))))

(defun TKC:AttDef (tag prm def y)
  (entmake (list '(0 . "ATTDEF") '(8 . "0") (list 10 1.4 y 0.0) '(40 . 1.5)
                 (cons 1 def) (cons 3 prm) (cons 2 tag) '(70 . 1))))

;; TKC:DefBlk - blocul Punct (aceeasi structura ca in TopoLT), daca lipseste
(defun TKC:DefBlk ()
  (if (not (tblsearch "BLOCK" *TKC:BLK*))
    (progn
      (entmake (list '(0 . "BLOCK") (cons 2 *TKC:BLK*) '(70 . 2) '(10 0.0 0.0 0.0)))
      (entmake '((0 . "POINT") (8 . "0") (10 0.0 0.0 0.0)))
      (TKC:AttDef "DENPCT" "DenPct=" "" 0.0)
      (TKC:AttDef "COTA" "Z=" "0.000" -2.5)
      (TKC:AttDef "COD" "Cod=" "" -5.0)
      (entmake '((0 . "ENDBLK")))))
  *TKC:BLK*)

;; TKC:MkPct - punct complet: bloc + atribute + textul numarului + legatura
(defun TKC:MkPct (p nr z cod / en tx)
  (TKC:DefBlk)
  (TK:MakeLayer *TKC:LAYSYM* 7)
  (TK:MakeLayer *TKC:LAYNR* 7)
  (entmake (list '(0 . "INSERT") (cons 8 *TKC:LAYSYM*) (cons 2 *TKC:BLK*) '(66 . 1)
                 (list 10 (car p) (cadr p) z) '(41 . 1.0) '(42 . 1.0) '(43 . 1.0) '(50 . 0.0)))
  (foreach a (list (list "DENPCT" nr 0.0) (list "COTA" (TKC:F z 3) -2.5) (list "COD" cod -5.0))
    (entmake (list '(0 . "ATTRIB") '(8 . "0") (list 10 (+ (car p) 1.4) (+ (cadr p) (caddr a)) 0.0)
                   '(40 . 1.5) (cons 1 (cadr a)) (cons 2 (car a)) '(70 . 1))))
  (entmake '((0 . "SEQEND") (8 . "0")))
  (setq en (entlast)
        en (cond ((TKC:InsertOf en)) (en))
        tx (TKC:Txt (list (+ (car p) *TKC:DX*) (cadr p)) nr *TKC:LAYNR* *TKC:TXTH* 0.0 0 0))
  (TKC:Link en tx)
  en)

;; TKC:InsertOf - blocul caruia ii apartine SEQEND-ul E (entlast dupa entmake)
(defun TKC:InsertOf (e / d)
  (setq d (entget e))
  (if (= "SEQEND" (cdr (assoc 0 d))) (cdr (assoc -2 d))))

;; TKC:SetNr - schimba numarul punctului (atribut + text)
(defun TKC:SetNr (en s / tx d p)
  (TKC:SetAtt en "DENPCT" s)
  (if (setq tx (TKC:NrTxt en))
    (progn (setq d (entget tx)) (entmod (subst (cons 1 s) (assoc 1 d) d)))
    (progn
      (setq p (cdr (assoc 10 (entget en))))
      (TK:MakeLayer *TKC:LAYNR* 7)
      (TKC:Link en (TKC:Txt (list (+ (car p) *TKC:DX*) (cadr p)) s *TKC:LAYNR* *TKC:TXTH* 0.0 0 0)))))

;; TKC:Pcts - punctele: ((ename nr x y z cod) ...); SS nil = toate din desen
(defun TKC:Pcts (ss / i en p l)
  (if (null ss) (setq ss (ssget "_X" (list '(0 . "INSERT") (cons 2 *TKC:BLK*)))))
  (if ss
    (repeat (setq i (sslength ss))
      (setq en (ssname ss (setq i (1- i))) p (cdr (assoc 10 (entget en))))
      (if (TKC:IsP en)
        (setq l (cons (list en (cond ((TKC:Att en "DENPCT")) (""))
                            (car p) (cadr p)
                            (cond ((distof (cond ((TKC:Att en "COTA")) ("")) 2)) ((caddr p)) (0.0))
                            (cond ((TKC:Att en "COD")) ("")))
                      l)))))
  l)

;; TKC:NrKey - cheia de sortare naturala: "pt145" -> ("PT" 145)
(defun TKC:NrKey (s / i)
  (setq i (strlen s))
  (while (and (> i 0) (wcmatch (substr s i 1) "#")) (setq i (1- i)))
  (if (< i (strlen s))
    (list (strcase (substr s 1 i)) (atoi (substr s (1+ i))))
    (list (strcase s) -1)))

(defun TKC:NrLess (a b / ka kb)
  (setq ka (TKC:NrKey a) kb (TKC:NrKey b))
  (if (= (car ka) (car kb)) (< (cadr ka) (cadr kb)) (< (car ka) (car kb))))

;; TKC:SortPcts - punctele in ordinea naturala a numerelor (pt2 inaintea pt10)
(defun TKC:SortPcts (lst / out)
  (foreach a lst
    (setq out (TKC:Insert a out)))
  out)
(defun TKC:Insert (a l)
  (cond ((null l) (list a))
        ((TKC:NrLess (cadr a) (cadr (car l))) (cons a l))
        (T (cons (car l) (TKC:Insert a (cdr l))))))

;; TKC:NextNr - urmatorul numar liber pentru prefixul PREF (pt146, 501 ...)
(defun TKC:NextNr (pref lst / mx k)
  (setq mx 0)
  (foreach a lst
    (setq k (TKC:NrKey (cadr a)))
    (if (and (>= (cadr k) 0) (= (car k) (strcase pref))) (setq mx (max mx (cadr k)))))
  (strcat pref (itoa (1+ mx))))

;; TKC:NrLa - numarul punctului din pozitia P (toleranta PCT_DMIN) sau nil
(defun TKC:NrLa (p lst / r tol)
  (setq tol (TKC:Cfg "PCT_DMIN"))
  (foreach a lst
    (if (and (not r) (< (distance (TK:2d p) (list (caddr a) (cadddr a))) tol)) (setq r (cadr a))))
  r)

;; TKC:Prefix - prefixul numerelor folosite in desen (cel al primului punct)
(defun TKC:Prefix (lst) (if lst (car (TKC:NrKey (cadr (car lst)))) ""))

;;; ==========================================================================
;;;  COMENZI - PUNCTE
;;; ==========================================================================

(defun TKC:Run (fn / *error* r)
  (defun *error* (msg) (TK:Error msg))
  (TK:Start)
  (TKC:CfgAll)
  (setq r (eval fn))
  (TK:Stop)
  r)

;; TKPCT - introducere puncte (cota din punctul indicat)
(defun TKC:CmdPct (/ lst pref n s p)
  (setq lst (TKC:Pcts nil) pref (if lst (car (TKC:NrKey (cadr (car (TKC:SortPcts lst))))) "")
        n (TKC:NextNr pref lst)
        s (getstring T (strcat "\nNumar punct <" n ">: ")))
  (if (/= s "") (setq n s))
  (while (setq p (getpoint (strcat "\nPozitia punctului " n " <Enter = gata>: ")))
    (TKC:MkPct p n (if (caddr p) (caddr p) 0.0) (TKC:Cfg "PCT_COD"))
    (setq lst (cons (list nil n (car p) (cadr p) 0.0 "") lst)
          n (TKC:NextNr (car (TKC:NrKey n)) lst))))

;; TKPCTCONTUR - cate un punct in fiecare varf, fara dubluri
(defun TKC:CmdContur (/ ss lst n s cod i en nou sar)
  (princ "\nSelectati poliliniile (conturul): ")
  (if (setq ss (ssget '((0 . "LWPOLYLINE"))))
    (progn
      (setq lst (TKC:Pcts nil) n (TKC:NextNr (TKC:Prefix (TKC:SortPcts lst)) lst)
            s (getstring (strcat "\nPrimul numar <" n ">: ")))
      (if (/= s "") (setq n s))
      (setq cod (getstring (strcat "\nCod <" (TKC:Cfg "PCT_COD") ">: ")))
      (if (= cod "") (setq cod (TKC:Cfg "PCT_COD")))
      (setq nou 0 sar 0 i 0)
      (repeat (sslength ss)
        (setq en (ssname ss i) i (1+ i))
        (foreach p (TKC:PlPts en)
          (if (TKC:NrLa p lst)
            (setq sar (1+ sar))
            (progn
              (TKC:MkPct p n (cond ((cdr (assoc 38 (entget en)))) (0.0)) cod)
              (setq lst (cons (list nil n (car p) (cadr p) 0.0 cod) lst)
                    n (TKC:NextNr (car (TKC:NrKey n)) lst) nou (1+ nou))))))
      (TKC:Msg (strcat (itoa nou) " puncte noi, " (itoa sar) " varfuri aveau deja punct.")))))

;; TKIMPPCT - puncte din fisier: Nr X(Nord) Y(Est) [Z] [Cod]
(defun TKC:CmdImport (/ fn f ln fl sep nr x y z cod cnt skip)
  (if (setq fn (getfiled "Fisier coordonate (Nr X Y Z Cod)" (getvar "DWGPREFIX") "txt;csv;coo;xyz;pnt" 0))
    (progn
      (setq f (open fn "r") cnt 0 skip 0 *TK:FH* f)   ; *TK:FH*: fisierul se inchide si la eroare
      (while (setq ln (read-line f))
        (setq fl (TKC:Fields ln) sep (car fl) fl (cadr fl))
        (if (and (>= (length fl) 3) (setq x (TKC:Val (nth 1 fl) sep)) (setq y (TKC:Val (nth 2 fl) sep)))
          (progn
            (setq nr (car fl)
                  z  (cond ((TKC:Val (nth 3 fl) sep)) (0.0))
                  cod (cond ((nth 4 fl))
                            ((and (nth 3 fl) (not (TKC:Val (nth 3 fl) sep))) (nth 3 fl))
                            ((TKC:Cfg "PCT_COD"))))
            (TKC:MkPct (if (= *TK:SWAPXY* "1") (list x y) (list y x)) nr z cod)
            (setq cnt (1+ cnt)))
          (setq skip (1+ skip))))
      (close f)
      (setq *TK:FH* nil)
      (TKC:Msg (strcat (itoa cnt) " puncte raportate, " (itoa skip) " linii ignorate (antet sau gresite).")))))

;; TKEXPPCT - fisierul de coordonate: Nr, X(Nord), Y(Est), Z, Cod (ordine naturala)
(defun TKC:CmdExport (/ ss lst fn f dc)
  (princ "\nSelectati punctele <Enter = toate>: ")
  (setq ss (ssget (list '(0 . "INSERT") (cons 2 *TKC:BLK*)))
        lst (TKC:SortPcts (TKC:Pcts ss)) dc (TKC:Cfg "UN_COORD"))
  (cond
    ((null lst) (TKC:Msg "Niciun punct gasit."))
    ((setq fn (getfiled "Salveaza coordonatele" (getvar "DWGPREFIX") "txt;csv" 1))
     (setq f (open fn "w") *TK:FH* f)
     (foreach a lst
       (write-line (strcat (cadr a) ","
                           (TKC:F (if (= *TK:SWAPXY* "1") (caddr a) (cadddr a)) dc) ","
                           (TKC:F (if (= *TK:SWAPXY* "1") (cadddr a) (caddr a)) dc) ","
                           (TKC:F (nth 4 a) dc) "," (nth 5 a))
                   f))
     (close f)
     (setq *TK:FH* nil)
     (TKC:Msg (strcat (itoa (length lst)) " puncte scrise in " fn)))))

;; TKSTERGPCT - sterge punctele cu textele legate
(defun TKC:CmdSterg (/ ss i en cnt)
  (princ "\nSelectati punctele de sters: ")
  (if (setq ss (ssget (list '(0 . "INSERT") (cons 2 *TKC:BLK*))))
    (progn
      (setq cnt 0)
      (repeat (setq i (sslength ss))
        (setq en (ssname ss (setq i (1- i))))
        (foreach e (TKC:Linked en) (entdel e))
        (entdel en)
        (setq cnt (1+ cnt)))
      (TKC:Msg (if (= cnt 1) "1 punct sters." (strcat (itoa cnt) " puncte sterse."))))))

;; TKRENUM - renumerotare pe rand; avertizeaza daca numarul exista deja
(defun TKC:CmdRenum (/ n pre s go lst nr own)
  (setq n (getint "\nNumar de start <1>: "))
  (if (null n) (setq n 1))
  (setq pre (getstring "\nPrefix <fara>: ") go T)
  (while go
    (setvar "ERRNO" 0)
    (setq nr (strcat pre (itoa n))
          s (entsel (strcat "\nPunctul care devine " nr " <Enter = gata>: ")))
    (cond
      ((and s (TKC:IsP (car s)))
       (setq lst (TKC:Pcts nil)
             own (vl-remove-if-not '(lambda (a) (and (= (strcase (cadr a)) (strcase nr)) (not (eq (car a) (car s))))) lst))
       (if (or (null own)
               (progn
                 (initget "Da Nu")
                 (= "Da" (getkword (strcat "\nNumarul " nr " exista deja la alt punct. Il folosesc oricum? [Da/Nu] <Nu>: ")))))
         (progn (TKC:SetNr (car s) nr) (setq n (1+ n)))))
      (s (TKC:Msg "Obiectul ales nu este un punct TopoLT / TopoKit."))
      ((= 7 (getvar "ERRNO")) (TKC:Msg "Nimic selectat, incercati din nou."))
      (T (setq go nil)))))

;; TKSELCOD - selecteaza punctele dupa cod (accepta * si ?)
(defun TKC:CmdSelCod (/ cod ss)
  (setq cod (strcase (getstring "\nCod (ex. Grf, G*, *): ")) ss (ssadd))
  (if (= cod "") (setq cod "*"))
  (foreach a (TKC:Pcts nil)
    (if (wcmatch (strcase (nth 5 a)) cod) (ssadd (car a) ss)))
  (TKC:Msg (strcat (itoa (sslength ss)) " puncte cu codul " cod "."))
  (if (> (sslength ss) 0) (sssetfirst nil ss)))

;; TKSCHCOD - schimba codul punctelor selectate
(defun TKC:CmdSchCod (/ ss cod i)
  (princ "\nSelectati punctele: ")
  (if (and (setq ss (ssget (list '(0 . "INSERT") (cons 2 *TKC:BLK*))))
           (/= "" (setq cod (getstring "\nCodul nou: "))))
    (progn
      (repeat (setq i (sslength ss)) (TKC:SetAtt (ssname ss (setq i (1- i))) "COD" cod))
      (TKC:Msg (strcat "Cod schimbat la " (itoa (sslength ss)) " puncte.")))))

;;; ==========================================================================
;;;  SUPRAFETE, COTARI, SUMA
;;; ==========================================================================

;; TKC:Hatch - hasura polilinii inchise EN (modelul din setari)
(defun TKC:Hatch (en / ms h arr r)
  (setq r (vl-catch-all-apply
            '(lambda ()
               (setq ms  (vla-get-modelspace (vla-get-activedocument (vlax-get-acad-object)))
                     h   (vla-addhatch ms acHatchPatternTypePreDefined (TKC:Cfg "SUP_PAT") :vlax-true)
                     arr (vlax-make-safearray vlax-vbObject '(0 . 0)))
               (vlax-safearray-put-element arr 0 (vlax-ename->vla-object en))
               (vla-appendouterloop h arr)
               (vla-put-patternscale h (/ (TKC:Cfg "SCARA") 1000.0))
               (vla-put-layer h (TK:MakeLayer *TKC:LAYHAT* 8))
               (vla-evaluate h))))
  (if (vl-catch-all-error-p r)
    (progn
      (if (= 'VLA-OBJECT (type h)) (vl-catch-all-apply 'vla-delete (list h)))
      (TKC:Msg (strcat "Hasura nu a putut fi creata: " (vl-catch-all-error-message r))))))

;; TKC:PlArea - suprafata poliliniei: din varfuri (ca in inventarul de coordonate);
;; daca are arce, suprafata reala a curbei (si avertisment)
(defun TKC:PlArea (en)
  (if (TKC:HasArcs en)
    (progn (TKC:Msg "Atentie: polilinia are arce; suprafata include segmentele de cerc.")
           (vlax-curve-getArea en))
    (TKC:Area (TKC:PlPts en))))

;; TKC:Inside - T daca punctul P e in interiorul poligonului PTS (regula par-impar)
(defun TKC:Inside (p pts / in i m a b)
  (setq m (length pts) i 0)
  (repeat m
    (setq a (nth i pts) b (nth (rem (1+ i) m) pts) i (1+ i))
    (if (and (/= (> (cadr a) (cadr p)) (> (cadr b) (cadr p)))
             (< (car p) (+ (car a) (/ (* (- (car b) (car a)) (- (cadr p) (cadr a))) (- (cadr b) (cadr a))))))
      (setq in (not in))))
  in)

;; TKC:ClearSup - sterge etichetele "S=..." (TKSUPRAF) din interiorul poligonului PTS:
;; la recalculare nu se dubleaza, iar dupa detasare nu ramane suprafata veche.
;; Returneaza numarul de etichete sterse.
(defun TKC:ClearSup (pts / ss i d p n)
  (setq n 0)
  (if (setq ss (ssget "_X" (list '(0 . "TEXT") (cons 8 *TKC:LAYSUP*) '(1 . "S=*"))))
    (repeat (setq i (sslength ss))
      (setq d (entget (ssname ss (setq i (1- i))))
            p (cdr (assoc (if (or (/= 0 (cdr (assoc 72 d))) (/= 0 (cdr (assoc 73 d)))) 11 10) d)))
      (if (and (/= 1 (cdr (assoc 67 d))) (wcmatch (cdr (assoc 1 d)) "S=*") (TKC:Inside p pts))  ; doar in model
        (progn (entdel (cdr (assoc -1 d))) (setq n (1+ n))))))
  n)

;; TKC:SupLabel - eticheta "S=... mp" in centrul poligonului PTS
(defun TKC:SupLabel (pts)
  (TKC:Txt (TKC:Centroid pts) (strcat "S=" (TKC:F (TKC:Area pts) (TKC:Cfg "UN_SUP")) " mp")
           (TK:MakeLayer *TKC:LAYSUP* 3) *TKC:SUPH* 0.0 1 2))

;; TKSUPRAF - S= in centrul fiecarui poligon inchis, optional hasura
;; (eticheta S= existenta in poligon se inlocuieste, nu se dubleaza)
(defun TKC:CmdSupraf (/ ss i en ar lay tot)
  (princ "\nSelectati poliliniile inchise: ")
  (if (setq ss (ssget '((0 . "LWPOLYLINE") (-4 . "&=") (70 . 1))))
    (progn
      (setq lay (TK:MakeLayer *TKC:LAYSUP* 3) tot 0.0)
      (repeat (setq i (sslength ss))
        (setq en (ssname ss (setq i (1- i))) ar (TKC:PlArea en) tot (+ tot ar))
        (if (= 1 (TKC:Cfg "SUP_HASH")) (TKC:Hatch en))
        (TKC:ClearSup (TKC:PlPts en))
        (TKC:Txt (TKC:Centroid (TKC:PlPts en)) (strcat "S=" (TKC:F ar (TKC:Cfg "UN_SUP")) " mp")
                 lay *TKC:SUPH* 0.0 1 2))
      (TKC:Msg (strcat (itoa (sslength ss)) " suprafete, total " (TKC:F tot (TKC:Cfg "UN_SUP")) " mp.")))))

;; TKCOTE - lungimea fiecarei laturi, spre exteriorul poligonului
(defun TKC:CmdCote (/ ss i en d pts n cl sg k p q a m lay pre suf dec)
  (princ "\nSelectati poliliniile de cotat: ")
  (if (setq ss (ssget '((0 . "LWPOLYLINE"))))
    (progn
      (setq lay (TK:MakeLayer *TKC:LAYDIM* 4)
            pre (TKC:Cfg "COT_PRE") suf (TKC:Cfg "COT_SUF") dec (TKC:Cfg "COT_DEC"))
      (repeat (setq i (sslength ss))
        (setq en (ssname ss (setq i (1- i))) d (entget en) pts (TKC:PlPts en) n (length pts)
              cl (TKC:Closed d) sg (if (and cl (< (TKC:SArea pts) 0)) -1.0 1.0) k 0)
        (repeat (if cl n (1- n))
          (setq p (nth k pts) q (nth (rem (1+ k) n) pts) k (1+ k))
          (if (> (distance p q) 1e-6)
            (progn
              (setq a (angle p q)
                    m (polar (polar p a (/ (distance p q) 2.0)) (- a (* sg (/ pi 2))) *TKC:COTOFF*))
              (if (and (> a (/ pi 2)) (<= a (* 1.5 pi))) (setq a (+ a pi)))
              (TKC:Txt m (strcat pre (TKC:F (distance p q) dec) suf) lay *TKC:COTH* a 1 2))))))))

;; TKC:Num - numarul dintr-un text: dupa ultimul "=" (S=500mp -> 500), altfel
;; primul numar; codurile de formatare MTEXT se elimina; virgula zecimala acceptata,
;; si cu separator de mii (1.234,5 sau 1,234.5 -> 1234.5)
(defun TKC:DelCh (s ch / r i c)
  (setq r "" i 1)
  (while (<= i (strlen s)) (if (/= (setq c (substr s i 1)) ch) (setq r (strcat r c))) (setq i (1+ i)))
  r)

(defun TKC:Num (s / p r i c on pd pc)
  (if (or (vl-string-search "\\" s) (vl-string-search "{" s)) (setq s (TK:MText s)))
  (if (setq p (vl-string-position (ascii "=") s nil T)) (setq s (substr s (+ p 2))))
  (setq pd (vl-string-position (ascii ".") s nil T) pc (vl-string-position (ascii ",") s nil T))
  (cond ((and pd pc (> pc pd)) (setq s (vl-string-translate "," "." (TKC:DelCh s "."))))
        ((and pd pc) (setq s (TKC:DelCh s ",")))
        (pc (setq s (vl-string-translate "," "." s))))
  (setq r "" i 1)
  (while (<= i (strlen s))
    (setq c (substr s i 1))
    (cond ((wcmatch c "#") (setq r (strcat r c) on T))
          ((and (= c ".") on (not (vl-string-search "." r))) (setq r (strcat r c)))
          ((and (= c "-") (not on)) (setq r "-"))
          (on (setq i (strlen s)))
          (T (setq r "")))
    (setq i (1+ i)))
  (if on (atof r)))

;; TKSUMA - suma numerelor din textele selectate
(defun TKC:CmdSuma (/ ss i d v s cnt p)
  (princ "\nSelectati textele: ")
  (if (setq ss (ssget '((0 . "TEXT,MTEXT"))))
    (progn
      (setq s 0.0 cnt 0)
      (repeat (setq i (sslength ss))
        (setq d (entget (ssname ss (setq i (1- i)))))
        (if (setq v (TKC:Num (cdr (assoc 1 d)))) (setq s (+ s v) cnt (1+ cnt))))
      (TKC:Msg (strcat "Suma = " (TKC:F s 2) "  (" (itoa cnt) " texte numerice din " (itoa (sslength ss)) ")"))
      (if (setq p (getpoint "\nUnde scriu suma <Enter = nu scriu>: "))
        (TKC:Txt p (TKC:F s 2) (TK:MakeLayer *TKC:LAYSUP* 3) *TKC:SUPH* 0.0 0 0))
      s)))

;;; ==========================================================================
;;;  DETASARE
;;; ==========================================================================

;; TKC:SegDist - distanta punct-segment: (distanta proiectie parametru)
(defun TKC:SegDist (p a b / ab u pr)
  (setq ab (TKC:v- b a)
        u  (if (> (TKC:Dot ab ab) 0.0) (/ (TKC:Dot (TKC:v- p a) ab) (TKC:Dot ab ab)) 0.0)
        u  (max 0.0 (min 1.0 u))
        pr (TKC:v+ a (TKC:v* ab u)))
  (list (distance (TK:2d p) pr) pr u))

;; TKC:NearSeg - latura cea mai apropiata de P: (index proiectie parametru)
(defun TKC:NearSeg (p pts / m i best r x)
  (setq m (length pts) i 0 best 1e99)
  (repeat m
    (setq x (TKC:SegDist p (nth i pts) (nth (rem (1+ i) m) pts)))
    (if (< (car x) best) (setq best (car x) r (list i (cadr x) (caddr x))))
    (setq i (1+ i)))
  r)

;; TKC:Clip - partea poligonului cu dot(n,X) <= tv (suprafata corecta si pentru
;; poligoane neconvexe; bucatile separate raman legate prin "punti" de latime 0)
(defun TKC:Clip (pts n tv / out i m p q dp dq)
  (setq m (length pts) i 0)
  (repeat m
    (setq p (nth i pts) q (nth (rem (1+ i) m) pts)
          dp (- (TKC:Dot n p) tv) dq (- (TKC:Dot n q) tv))
    (if (<= dp 0.0) (setq out (cons p out)))
    (if (< (* dp dq) 0.0) (setq out (cons (TKC:v+ p (TKC:v* (TKC:v- q p) (/ dp (- dp dq)))) out)))
    (setq i (1+ i)))
  (reverse out))

;; TKC:CutSegs - bucatile liniei dot(n,X) = tv aflate in interiorul poligonului:
;; intersectiile cu laturile, ordonate pe linie si luate doua cate doua.
;; La un poligon neconvex linia poate avea mai multe bucati.
(defun TKC:CutSegs (pts n tv / m i p q dp dq x d ts out)
  (setq m (length pts) i 0 d (TKC:Perp n))
  (repeat m
    (setq p (nth i pts) q (nth (rem (1+ i) m) pts)
          dp (- (TKC:Dot n p) tv) dq (- (TKC:Dot n q) tv))
    (if (< (* dp dq) 0.0)
      (setq x (TKC:v+ p (TKC:v* (TKC:v- q p) (/ dp (- dp dq))))
            ts (cons (cons (TKC:Dot d x) x) ts)))
    (setq i (1+ i)))
  (setq ts (mapcar 'cdr (vl-sort ts '(lambda (a b) (< (car a) (car b))))))
  (while (cdr ts)
    (setq out (cons (list (car ts) (cadr ts)) out) ts (cddr ts)))
  (reverse out))

;; TKC:DetHP - detasarea cu linie de directie data (normala N), din partea cu
;; dot(n,X) mic: (partea-detasata rest segmente-taietura)
(defun TKC:DetHP (pts n target / vals lo hi mid tv)
  (setq vals (mapcar '(lambda (p) (TKC:Dot n p)) pts) lo (apply 'min vals) hi (apply 'max vals))
  (repeat 80
    (setq mid (/ (+ lo hi) 2.0))
    (if (< (TKC:Area (TKC:Clip pts n mid)) target) (setq lo mid) (setq hi mid)))
  (setq tv (/ (+ lo hi) 2.0))
  (list (TKC:Clean (TKC:Clip pts n tv)) (TKC:Clean (TKC:Clip pts (TKC:v* n -1.0) (- tv)))
        (TKC:CutSegs pts n tv)))

;; TKC:PLen / TKC:Walk - lungimea unui drum si parcurgerea lui pe distanta S
(defun TKC:PLen (pp / s i)
  (setq s 0.0 i 1)
  (repeat (1- (length pp)) (setq s (+ s (distance (nth (1- i) pp) (nth i pp))) i (1+ i)))
  s)

(defun TKC:Walk (pp s / acc out i a b l q done)
  (setq acc 0.0 out (list (car pp)) i 1)
  (while (and (not done) (< i (length pp)))
    (setq a (nth (1- i) pp) b (nth i pp) l (distance a b))
    (if (and (> l 0.0) (>= (+ acc l) s))
      (setq q (TKC:v+ a (TKC:v* (TKC:v- b a) (/ (- s acc) l))) done T)
      (setq acc (+ acc l) out (cons b out) i (1+ i))))
  (if done
    (list (reverse (cons q out)) (cons q (TKC:Slice pp i (length pp))))
    (list (reverse out) nil)))

;; TKC:DrumPO - drumul pe contur pornind din punctul obligat F (latura J), in sensul FWD
(defun TKC:DrumPO (pts f j fwd / m lst)
  (setq m (length pts) lst (append (TKC:Slice pts (1+ j) m) (TKC:Slice pts 0 (1+ j))))
  (append (cons f (if fwd lst (reverse lst))) (list f)))

;; TKC:DetPO - detasare prin punctul obligat F
(defun TKC:DetPO (pts f j fwd target / pp lo hi mid w)
  (setq pp (TKC:DrumPO pts f j fwd) lo 0.0 hi (TKC:PLen pp))
  (repeat 80
    (setq mid (/ (+ lo hi) 2.0))
    (if (< (TKC:Area (car (TKC:Walk pp mid))) target) (setq lo mid) (setq hi mid)))
  (setq w (TKC:Walk pp (/ (+ lo hi) 2.0)))
  (list (TKC:Clean (car w)) (TKC:Clean (cadr w)) (list (list f (last (car w))))))

;; TKC:MDetHP / TKC:MDetPO - mai multe detasari succesive; ((parte taieturi) ...) si restul
(defun TKC:MDetHP (pts n areas / vals lo0 hi0 lo hi mid cum tprev tv p res)
  (setq vals (mapcar '(lambda (q) (TKC:Dot n q)) pts) lo0 (apply 'min vals) hi0 (apply 'max vals) cum 0.0)
  (foreach a areas
    (setq cum (+ cum a) lo lo0 hi hi0)
    (repeat 80
      (setq mid (/ (+ lo hi) 2.0))
      (if (< (TKC:Area (TKC:Clip pts n mid)) cum) (setq lo mid) (setq hi mid)))
    (setq tv (/ (+ lo hi) 2.0) p (TKC:Clip pts n tv))
    (if tprev (setq p (TKC:Clip p (TKC:v* n -1.0) (- tprev))))
    (setq res (cons (list (TKC:Clean p) (TKC:CutSegs pts n tv)) res) tprev tv))
  (list (reverse res) (TKC:Clean (TKC:Clip pts (TKC:v* n -1.0) (- tprev)))))

(defun TKC:MDetPO (pts f j fwd areas / pp len cum lo hi mid s sprev sub res)
  (setq pp (TKC:DrumPO pts f j fwd) len (TKC:PLen pp) cum 0.0 sprev 0.0)
  (foreach a areas
    (setq cum (+ cum a) lo 0.0 hi len)
    (repeat 80
      (setq mid (/ (+ lo hi) 2.0))
      (if (< (TKC:Area (car (TKC:Walk pp mid))) cum) (setq lo mid) (setq hi mid)))
    (setq s (/ (+ lo hi) 2.0)
          sub (car (TKC:Walk (cadr (TKC:Walk pp sprev)) (- s sprev)))
          res (cons (list (TKC:Clean (cons f sub)) (list (list f (last sub)))) res)
          sprev s))
  (list (reverse res) (TKC:Clean (cons f (cadr (TKC:Walk pp sprev))))))

;; TKC:PlNew - polilinie inchisa cu proprietatile poliliniei EN si varfurile PTS
(defun TKC:PlNew (en pts / d keep l)
  (setq d (entget en)
        keep (vl-remove-if-not '(lambda (x) (member (car x) '(6 8 38 39 43 48 62 210 370 420))) d)
        l (append (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity")) (vl-remove-if '(lambda (x) (member (car x) '(38 43 210))) keep)
                  (list '(100 . "AcDbPolyline") (cons 90 (length pts)) '(70 . 1))
                  (vl-remove-if-not '(lambda (x) (member (car x) '(38 43 210))) keep)
                  (mapcar '(lambda (p) (list 10 (car p) (cadr p))) pts)))
  (entmake l)
  (entlast))

(defun TKC:Rect (a b lay)
  (entmake (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") (cons 8 lay) '(100 . "AcDbPolyline")
                 '(90 . 4) '(70 . 1) (list 10 (car a) (cadr a)) (list 10 (car b) (cadr a))
                 (list 10 (car b) (cadr b)) (list 10 (car a) (cadr b)))))

;; TKC:Eticheta - eticheta parcelei: numarul in chenar, proprietarul, suprafata
(defun TKC:Eticheta (c nr ar prop / h w lay)
  (setq h *TKC:SUPH* lay (TK:MakeLayer *TKC:LAYSUP* 3) w (+ (* 0.45 h (max 1 (strlen nr))) (* 0.4 h)))
  (TKC:Txt (list (car c) (+ (cadr c) (* 0.9 h))) nr lay h 0.0 1 2)
  (TKC:Rect (list (- (car c) w) (+ (cadr c) (* 0.2 h))) (list (+ (car c) w) (+ (cadr c) (* 1.6 h))) lay)
  (if (/= prop "") (TKC:Txt (list (car c) (- (cadr c) (* 0.6 h))) prop lay h 0.0 1 2))
  (TKC:Txt (list (car c) (- (cadr c) (if (/= prop "") (* 2.0 h) (* 0.6 h))))
           (strcat (TKC:F ar (TKC:Cfg "UN_SUP")) "mp") lay h 0.0 1 2))

;; TKC:DetSetup - selectia parcelei si modul: (mod en d o pts pk ns n pf j tf) sau nil
(defun TKC:DetSetup (/ mode sel en d pts0 o pts m pk ns k a b sg n d1 d2 pf nf j tf vals lo hi)
  (if (null *TKC:DETMODE*) (setq *TKC:DETMODE* "PAralela"))
  (initget "PAralela DirectieParalela PErpendiculara PUnctObligat")
  (setq mode (getkword (strcat "\nDetasare [PAralela/DirectieParalela/PErpendiculara/PUnctObligat] <"
                               *TKC:DETMODE* ">: ")))
  (if mode (setq *TKC:DETMODE* mode) (setq mode *TKC:DETMODE*))
  (setq sel (entsel "\nSelectati conturul parcelei, pe latura dinspre care se face detasarea: "))
  (cond
    ((not (and sel (= "LWPOLYLINE" (cdr (assoc 0 (setq d (entget (setq en (car sel)))))))))
     (TKC:Msg "Nu ati selectat o polilinie.") nil)
    ((< (length (TKC:PlPts en)) 3) (TKC:Msg "Polilinia are mai putin de 3 varfuri.") nil)
    (T
     (if (TKC:HasArcs en) (TKC:Msg "Atentie: arcele poliliniei sunt tratate ca segmente (corzi)."))
     ;; coordonate locale fata de primul varf, pentru precizie
     (setq pts0 (TKC:Clean (TKC:PlPts en)) o (car pts0)
           pts (mapcar '(lambda (p) (TKC:v- p o)) pts0) m (length pts)
           pk (TKC:v- (TK:2d (cadr sel)) o) ns (TKC:NearSeg pk pts) k (car ns)
           a (nth k pts) b (nth (rem (1+ k) m) pts)
           sg (if (> (TKC:SArea pts) 0.0) 1.0 -1.0))
     (grdraw (TKC:v+ a o) (TKC:v+ b o) 1 1)
     (TKC:Msg (strcat "Suprafata parcelei: " (TKC:F (TKC:Area pts) 2) " mp"))
     (cond
       ((= mode "PAralela") (setq n (TKC:v* (TKC:Unit (TKC:Perp (TKC:v- b a))) sg)))
       ((= mode "PErpendiculara")
        (setq n (TKC:Unit (if (< (distance pk a) (distance pk b)) (TKC:v- b a) (TKC:v- a b)))))
       ((= mode "DirectieParalela")
        (if (and (setq d1 (getpoint "\nDirectia liniei de detasare - primul punct: "))
                 (setq d2 (getpoint d1 "\nDirectia liniei de detasare - al doilea punct: ")))
          (progn
            (setq n (TKC:Unit (TKC:Perp (TKC:v- (TK:2d d2) (TK:2d d1))))
                  vals (mapcar '(lambda (p) (TKC:Dot n p)) pts) lo (apply 'min vals) hi (apply 'max vals))
            (if (> (- (TKC:Dot n pk) lo) (- hi (TKC:Dot n pk))) (setq n (TKC:v* n -1.0))))))
       ((= mode "PUnctObligat")
        (if (setq pf (getpoint "\nPunctul obligat (pe contur): "))
          (setq nf (TKC:NearSeg (TKC:v- (TK:2d pf) o) pts) j (car nf) tf (caddr nf) pf (cadr nf)))))
     (cond
       ((and (= mode "DirectieParalela") (null n)) (TKC:Msg "Directie neprecizata.") nil)
       ((and (= mode "PUnctObligat") (null pf)) (TKC:Msg "Punct obligat neprecizat.") nil)
       (T (list mode en d o pts pk ns n pf j tf))))))

;; TKC:Fwd - sensul de parcurgere a conturului pentru punctul obligat
(defun TKC:Fwd (s / m k j sf sb)
  (setq m (length (nth 4 s)) k (car (nth 6 s)) j (nth 9 s)
        sf (rem (+ (- k j) m) m) sb (rem (+ (- j k) m) m))
  (if (= k j) (> (caddr (nth 6 s)) (nth 10 s)) (<= sf sb)))

;; TKC:Draw - desenul unei parti: polilinie noua (rupere) sau linia taieturii
(defun TKC:DrawPart (en lay pw cuts rupe hash / e tmp)
  (if rupe
    (progn (setq e (TKC:PlNew en pw)) (if hash (TKC:Hatch e)))
    (progn
      (foreach c cuts (TKC:Line (car c) (cadr c) lay))
      (if hash (progn (setq tmp (TKC:PlNew en pw)) (TKC:Hatch tmp) (entdel tmp))))))

;; TKDETASARE - detaseaza o suprafata
(defun TKC:CmdDet (/ s tot target nr prop res o p1 p2 cuts rupe lay nx)
  (if (setq s (TKC:DetSetup))
    (progn
      (setq o (nth 3 s) tot (TKC:Area (nth 4 s)))
      (if (null *TKC:DETLAST*) (setq *TKC:DETLAST* (min 1000.0 (/ tot 2.0))))
      (initget 6)
      (setq target (getreal (strcat "\nSuprafata de detasat <" (TKC:F *TKC:DETLAST* 2) "> mp: ")))
      (if (null target) (setq target *TKC:DETLAST*))
      (if (>= target tot)
        (TKC:Msg (strcat "Suprafata ceruta depaseste suprafata parcelei (" (TKC:F tot 2) " mp)."))
        (progn
          (setq *TKC:DETLAST* target
                nx (itoa (1+ (cond ((vlax-ldata-get "TOPOKIT" "NRPAR")) ((vlax-ldata-get "CTOPO" "NRPAR")) (0))))
                nr (getstring (strcat "\nNumar parcela <" nx ">: ")))
          (if (= nr "") (setq nr nx))
          (setq prop (getstring T "\nNume proprietar <nimic>: ")
                res (if (= (car s) "PUnctObligat")
                      (TKC:DetPO (nth 4 s) (nth 8 s) (nth 9 s) (TKC:Fwd s) target)
                      (TKC:DetHP (nth 4 s) (nth 7 s) target))
                p1 (mapcar '(lambda (p) (TKC:v+ p o)) (car res))
                p2 (mapcar '(lambda (p) (TKC:v+ p o)) (cadr res))
                cuts (mapcar '(lambda (c) (mapcar '(lambda (p) (TKC:v+ p o)) c)) (caddr res))
                lay (cdr (assoc 8 (nth 2 s)))
                ;; rupere doar cand linia taie conturul o singura data (doua parti curate)
                rupe (and (= 1 (TKC:Cfg "DET_RUPE")) (= 1 (length cuts))))
          (if (and (= 1 (TKC:Cfg "DET_RUPE")) (> (length cuts) 1))
            (TKC:Msg (strcat "Linia de detasare taie conturul in " (itoa (* 2 (length cuts)))
                             " puncte: s-au desenat taieturile, polilinia nu a fost rupta.")))
          (TKC:DrawPart (nth 1 s) lay p1 cuts rupe (= 1 (TKC:Cfg "SUP_HASH")))
          (if rupe (progn (TKC:PlNew (nth 1 s) p2) (entdel (nth 1 s))))
          (TKC:Eticheta (TKC:Centroid p1) nr (TKC:Area p1) prop)
          ;; eticheta S= a parcelei initiale nu mai e valabila: se inlocuieste cu S= pe rest
          (if (> (TKC:ClearSup (mapcar '(lambda (p) (TKC:v+ p o)) (nth 4 s))) 0) (TKC:SupLabel p2))
          (if (distof nr 2) (vlax-ldata-put "TOPOKIT" "NRPAR" (atoi nr)))
          (TKC:Msg (strcat "Detasat: " (TKC:F (TKC:Area p1) 2) " mp (cerut " (TKC:F target 2)
                           "), rest: " (TKC:F (TKC:Area p2) 2) " mp."))
          res)))))

;;; ---- detasare multipla: tabelul (Nr, Proprietar, Suprafata) -------------

(defun TKC:Pad (s n) (if (> (strlen s) n) (setq s (substr s 1 n))) (while (< (strlen s) n) (setq s (strcat s " "))) s)
(defun TKC:PadL (s n) (while (< (strlen s) n) (setq s (strcat " " s))) s)
(defun TKC:LRep (l i v / k) (setq k -1) (mapcar '(lambda (x) (setq k (1+ k)) (if (= k i) v x)) l))
(defun TKC:LDel (l i / k) (setq k -1) (vl-remove-if '(lambda (x) (= (setq k (1+ k)) i)) l))
(defun TKC:NumS (s) (if s (distof (vl-string-translate "," "." (vl-string-trim " \"" s)) 2)))
;; numarul urmator: dupa randurile din tabel si dupa ultima parcela detasata in desen
(defun TKC:MNextNr ()
  (itoa (1+ (apply 'max (append (list 0 (cond ((vlax-ldata-get "TOPOKIT" "NRPAR")) ((vlax-ldata-get "CTOPO" "NRPAR")) (0)))
                                (mapcar '(lambda (x) (atoi (car x))) *TKC:MTAB*))))))

;; TKC:ReadCsv - Nr ; Proprietar ; Suprafata (separator ; tab sau ,)
(defun TKC:ReadCsv (fn / f ln fl v rows)
  (if (setq f (open fn "r"))
    (progn
      (while (setq ln (read-line f))
        (setq fl (cadr (TKC:Fields ln)))
        (if (and (>= (length fl) 3) (setq v (TKC:NumS (caddr fl))) (> v 0))
          (setq rows (cons (list (car fl) (cadr fl) v) rows))))
      (close f)))
  (reverse rows))

;; TKC:XlCell - o celula Excel ca text
(defun TKC:XlCell (sh r c / rg v)
  (setq rg (vlax-get-property (vlax-get-property sh 'Cells) 'Item r c))
  (if (= (type rg) 'VARIANT) (setq rg (vlax-variant-value rg)))
  (setq v (vlax-get-property rg 'Value2))
  (if (= (type v) 'VARIANT) (setq v (vlax-variant-value v)))
  (cond ((null v) "")
        ((= (type v) 'STR) v)
        ((numberp v) (if (equal v (fix v) 1e-9) (itoa (fix v)) (rtos v 2 6)))
        (T "")))

;; TKC:ReadXl - prima foaie Excel: A = Nr, B = Proprietar, C = Suprafata.
;; Metodele cu parametri optionali (Open, Close, Quit) se apeleaza cu vlax-invoke:
;; vlax-invoke-method fara ei esueaza in AutoCAD 2025/2026 (eroarea din CadTopo)
(defun TKC:ReadXl (fn / xl new wb sh r go miss a b c v rows)
  (setq xl (vl-catch-all-apply 'vlax-get-object (list "Excel.Application")))
  (if (or (null xl) (vl-catch-all-error-p xl)) (setq xl (vlax-create-object "Excel.Application") new T))
  (if xl
    (progn
      (setq wb (vl-catch-all-apply 'vlax-invoke (list (vlax-get-property xl 'Workbooks) 'Open fn)))
      (if (not (vl-catch-all-error-p wb))
        (progn
          (setq sh (vlax-get-property (vlax-get-property wb 'Worksheets) 'Item 1) r 1 go T miss 0)
          (while (and go (< r 5000))
            (setq a (TKC:XlCell sh r 1) b (TKC:XlCell sh r 2) c (TKC:XlCell sh r 3))
            (if (and (= a "") (= b "") (= c "")) (setq miss (1+ miss)) (setq miss 0))
            (if (> miss 3) (setq go nil))
            (if (and (setq v (TKC:NumS c)) (> v 0)) (setq rows (cons (list a b v) rows)))
            (setq r (1+ r)))
          (vl-catch-all-apply 'vlax-invoke (list wb 'Close :vlax-false))))
      (if new (vl-catch-all-apply 'vlax-invoke (list xl 'Quit)))
      (vl-catch-all-apply 'vlax-release-object (list xl))
      (if (vl-catch-all-error-p wb) (exit))))
  (reverse rows))

(defun TKC:DclMDet ()
  '("tkc_mdet : dialog {"
    "  label = \"TopoKit - Detasari multiple: tabelul suprafetelor\";"
    "  : list_box { key = \"hdr\"; height = 2; width = 64; tabs = \"8 46\"; tab_truncate = true; is_enabled = false; }"
    "  : list_box { key = \"lst\"; height = 16; width = 64; tabs = \"8 46\"; tab_truncate = true; }"
    "  : row {"
    "    : edit_box { key = \"nr\"; label = \"Nr.\"; edit_width = 6; }"
    "    : edit_box { key = \"prop\"; label = \"Proprietar\"; edit_width = 28; }"
    "    : edit_box { key = \"sup\"; label = \"Suprafata\"; edit_width = 10; }"
    "  }"
    "  : row {"
    "    : button { key = \"add\"; label = \"Adauga\"; }"
    "    : button { key = \"mod\"; label = \"Modifica\"; }"
    "    : button { key = \"del\"; label = \"Sterge\"; }"
    "    : button { key = \"up\"; label = \"Sus\"; }"
    "    : button { key = \"dn\"; label = \"Jos\"; }"
    "    : button { key = \"clr\"; label = \"Goleste\"; }"
    "  }"
    "  : row {"
    "    : button { key = \"imp\"; label = \"Incarca Excel/CSV...\"; }"
    "    : button { key = \"exp\"; label = \"Salveaza CSV...\"; }"
    "    : column {"
    "      : text { key = \"max\"; width = 34; }"
    "      : text { key = \"rest\"; width = 34; }"
    "    }"
    "  }"
    "  ok_cancel;"
    "  errtile;"
    "}"))

(defun TKC:MFmt (rw) (strcat (car rw) (chr 9) (cadr rw) (chr 9) (TKC:F (caddr rw) 2)))
(defun TKC:MSum () (apply '+ (cons 0.0 (mapcar 'caddr *TKC:MTAB*))))

(defun TKC:MRef ()
  (start_list "lst")
  (foreach rw *TKC:MTAB* (add_list (TKC:MFmt rw)))
  (end_list)
  (set_tile "max" (strcat "Suprafata parcelei:  " (TKC:F *TKC:MTOT* 2) " mp"))
  (set_tile "rest" (strcat "Ramane:  " (TKC:F (- *TKC:MTOT* (TKC:MSum)) 2) " mp"))
  (if (and *TKC:MSEL* (< *TKC:MSEL* (length *TKC:MTAB*))) (set_tile "lst" (itoa *TKC:MSEL*))))

(defun TKC:MPick (v / rw)
  (setq *TKC:MSEL* (atoi v) rw (nth *TKC:MSEL* *TKC:MTAB*))
  (if rw (progn (set_tile "nr" (car rw)) (set_tile "prop" (cadr rw)) (set_tile "sup" (TKC:F (caddr rw) 2)))))

(defun TKC:MFields (/ nr v)
  (setq nr (get_tile "nr") v (TKC:NumS (get_tile "sup")))
  (if (or (null v) (<= v 0))
    (progn (set_tile "error" "Suprafata trebuie sa fie un numar pozitiv.") nil)
    (progn (set_tile "error" "") (if (= nr "") (setq nr (TKC:MNextNr))) (list nr (get_tile "prop") v))))

(defun TKC:MAdd (/ rw)
  (if (setq rw (TKC:MFields))
    (progn
      (setq *TKC:MTAB* (append *TKC:MTAB* (list rw)) *TKC:MSEL* (1- (length *TKC:MTAB*)))
      (TKC:MRef) (set_tile "nr" (TKC:MNextNr)) (set_tile "prop" "") (mode_tile "prop" 2))))

(defun TKC:MMod (/ rw)
  (cond ((null *TKC:MSEL*) (set_tile "error" "Alegeti intai un rand din tabel."))
        ((setq rw (TKC:MFields)) (setq *TKC:MTAB* (TKC:LRep *TKC:MTAB* *TKC:MSEL* rw)) (TKC:MRef))))

(defun TKC:MDel ()
  (if *TKC:MSEL*
    (progn
      (setq *TKC:MTAB* (TKC:LDel *TKC:MTAB* *TKC:MSEL*))
      (if (>= *TKC:MSEL* (length *TKC:MTAB*)) (setq *TKC:MSEL* (if *TKC:MTAB* (1- (length *TKC:MTAB*)))))
      (TKC:MRef))))

(defun TKC:MMove (dir / j a b)
  (if *TKC:MSEL*
    (progn
      (setq j (+ *TKC:MSEL* dir))
      (if (and (>= j 0) (< j (length *TKC:MTAB*)))
        (setq a (nth *TKC:MSEL* *TKC:MTAB*) b (nth j *TKC:MTAB*)
              *TKC:MTAB* (TKC:LRep (TKC:LRep *TKC:MTAB* *TKC:MSEL* b) j a) *TKC:MSEL* j))
      (TKC:MRef))))

(defun TKC:MImport (/ fn rows)
  (if (setq fn (getfiled "Tabel suprafete (Excel sau CSV): Nr, Proprietar, Suprafata" "" "xlsx;xls;csv;txt" 0))
    (progn
      (setq rows (if (wcmatch (strcase fn) "*.XLS,*.XLSX") (vl-catch-all-apply 'TKC:ReadXl (list fn)) (TKC:ReadCsv fn)))
      (cond
        ((vl-catch-all-error-p rows) (set_tile "error" "Excel nu a putut fi citit. Salvati fisierul ca CSV."))
        ((null rows) (set_tile "error" "Nu am gasit randuri valide (coloane: Nr, Proprietar, Suprafata)."))
        (T (setq *TKC:MTAB* rows *TKC:MSEL* nil)
           (set_tile "error" (strcat (itoa (length rows)) " randuri incarcate.")) (TKC:MRef))))))

(defun TKC:MExport (/ fn f)
  (if (setq fn (getfiled "Salveaza tabelul de suprafete" "" "csv" 1))
    (progn
      (setq f (open fn "w"))
      (write-line "Nr;Proprietar;Suprafata" f)
      (foreach rw *TKC:MTAB*
        (write-line (strcat (car rw) ";" (cadr rw) ";" (vl-string-translate "." "," (TKC:F (caddr rw) 2))) f))
      (close f)
      (set_tile "error" "Tabel salvat."))))

(defun TKC:MOk ()
  (cond ((null *TKC:MTAB*) (set_tile "error" "Tabelul e gol."))
        ((>= (TKC:MSum) (- *TKC:MTOT* 0.005)) (set_tile "error" "Suma suprafetelor trebuie sa fie mai mica decat suprafata parcelei."))
        (T (done_dialog 1))))

;; TKC:MDialog - fereastra cu tabelul; T la OK
(defun TKC:MDialog (/ fn f id r)
  (setq fn (vl-filename-mktemp "tkcmdet" nil ".dcl") f (open fn "w") r 0)
  (foreach ln (TKC:DclMDet) (write-line ln f))
  (close f)
  (setq id (load_dialog fn))
  (if (and (>= id 0) (new_dialog "tkc_mdet" id))
    (progn
      (start_list "hdr") (add_list (strcat "Nr." (chr 9) "Proprietar" (chr 9) "Suprafata (mp)")) (end_list)
      (TKC:MRef)
      (set_tile "nr" (TKC:MNextNr))
      (action_tile "lst" "(TKC:MPick $value)")
      (action_tile "add" "(TKC:MAdd)")
      (action_tile "mod" "(TKC:MMod)")
      (action_tile "del" "(TKC:MDel)")
      (action_tile "up" "(TKC:MMove -1)")
      (action_tile "dn" "(TKC:MMove 1)")
      (action_tile "clr" "(setq *TKC:MTAB* nil *TKC:MSEL* nil) (TKC:MRef) (set_tile \"nr\" \"1\")")
      (action_tile "imp" "(TKC:MImport)")
      (action_tile "exp" "(TKC:MExport)")
      (action_tile "accept" "(TKC:MOk)")
      (setq r (start_dialog)))
    (TKC:Msg "Fereastra nu a putut fi deschisa."))
  (if (>= id 0) (unload_dialog id))
  (vl-file-delete fn)
  (= r 1))

;; TKDETMULT - detasari multiple dintr-un tabel
(defun TKC:CmdDetMult (/ s o areas res lay rupe hash i rw pw mx rest)
  (if (setq s (TKC:DetSetup))
    (progn
      (setq o (nth 3 s) *TKC:MTOT* (TKC:Area (nth 4 s)) *TKC:MSEL* nil)
      (if (TKC:MDialog)
        (progn
          (setq areas (mapcar 'caddr *TKC:MTAB*)
                res (if (= (car s) "PUnctObligat")
                      (TKC:MDetPO (nth 4 s) (nth 8 s) (nth 9 s) (TKC:Fwd s) areas)
                      (TKC:MDetHP (nth 4 s) (nth 7 s) areas))
                lay (cdr (assoc 8 (nth 2 s)))
                rupe (= 1 (TKC:Cfg "DET_RUPE")) hash (= 1 (TKC:Cfg "SUP_HASH"))
                i 0 mx (cond ((vlax-ldata-get "TOPOKIT" "NRPAR")) (0)))
          ;; ruperea in polilinii doar daca fiecare taietura e o singura linie
          (if (and rupe (vl-some '(lambda (pc) (> (length (cadr pc)) 1)) (car res)))
            (progn (setq rupe nil)
                   (TKC:Msg "O linie de detasare taie conturul de mai multe ori: s-au desenat taieturile, polilinia nu a fost rupta.")))
          (foreach pc (car res)
            (setq rw (nth i *TKC:MTAB*) pw (mapcar '(lambda (p) (TKC:v+ p o)) (car pc)))
            (TKC:DrawPart (nth 1 s) lay pw (mapcar '(lambda (c) (mapcar '(lambda (p) (TKC:v+ p o)) c)) (cadr pc))
                          rupe hash)
            (TKC:Eticheta (TKC:Centroid pw) (car rw) (TKC:Area pw) (cadr rw))
            (if (distof (car rw) 2) (setq mx (max mx (atoi (car rw)))))
            (TKC:Msg (strcat "Parcela " (car rw) ": " (TKC:F (TKC:Area pw) 2) " mp (cerut " (TKC:F (caddr rw) 2) ")"))
            (setq i (1+ i)))
          (setq rest (mapcar '(lambda (p) (TKC:v+ p o)) (cadr res)))
          (if (> (TKC:ClearSup (mapcar '(lambda (p) (TKC:v+ p o)) (nth 4 s))) 0) (TKC:SupLabel rest))
          (if rupe (progn (TKC:PlNew (nth 1 s) rest) (entdel (nth 1 s))))
          (vlax-ldata-put "TOPOKIT" "NRPAR" mx)
          (TKC:Msg (strcat "Rest: " (TKC:F (TKC:Area rest) 2) " mp."))
          ;; parcelele au fost detasate: tabelul se goleste, ca sa nu fie detasate inca o data
          ;; din greseala la parcela urmatoare (tabelul se poate salva in CSV din dialog)
          (setq *TKC:MTAB* nil)
          res)))))

;;; ==========================================================================
;;;  SETARI (dialog)
;;; ==========================================================================

(setq *TKC:FIELDS*
       '(("SCARA" "Scara planului  1:" "real") ("FONT" "Stil text" "str")
         ("PCT_H" "Puncte: inaltime text (mm)" "real") ("PCT_COD" "Puncte: cod implicit" "str")
         ("PCT_DMIN" "Puncte: distanta minima (m)" "real")
         ("SUP_H" "Suprafete: inaltime text (mm)" "real") ("SUP_HASH" "Suprafete: hasura" "toggle")
         ("SUP_PAT" "Suprafete: model hasura" "str") ("DET_RUPE" "Detasare: rupe polilinia" "toggle")
         ("COT_H" "Cotari: inaltime text (mm)" "real") ("COT_PRE" "Cotari: prefix" "str")
         ("COT_SUF" "Cotari: sufix" "str") ("COT_DEC" "Cotari: zecimale" "int")
         ("UN_COORD" "Zecimale coordonate" "int") ("UN_DIST" "Zecimale distante" "int")
         ("UN_SUP" "Zecimale suprafete" "int")))

(defun TKC:Q (s) (strcat "\"" s "\""))

(defun TKC:DclSet (/ l)
  (setq l (list "tkc_set : dialog {" "  label = \"TopoKit - Setari cadastru\";"
                "  : text { label = \"Inaltimile textelor sunt in mm pe hartie (x scara).\"; }"))
  (foreach f *TKC:FIELDS*
    (setq l (append l (list (if (= (caddr f) "toggle")
                              (strcat "  : toggle { key = " (TKC:Q (car f)) "; label = " (TKC:Q (cadr f)) "; }")
                              (strcat "  : edit_box { key = " (TKC:Q (car f)) "; label = " (TKC:Q (cadr f))
                                      "; edit_width = 18; }"))))))
  (append l (list "  : text { label = \"Setarile se pastreaza in desen.\"; }" "  ok_cancel;" "  errtile;" "}")))

(defun TKC:SetInit (f / v)
  (setq v (cdr (assoc (car f) *TKC:WK*)))
  (set_tile (car f) (cond ((= (caddr f) "real") (TKC:Num0 v)) ((member (caddr f) '("int" "toggle")) (itoa v)) (T v))))

(defun TKC:SetRead (f / s v)
  (setq s (get_tile (car f))
        v (cond ((= (caddr f) "real") (if (and (setq v (distof s 2)) (> v 0)) v))
                ((= (caddr f) "int") (if (and (setq v (distof s 2)) (>= v 0) (= v (fix v))) (fix v)))
                ((= (caddr f) "toggle") (atoi s))
                (T s)))
  (if (null v)
    (progn (set_tile "error" (strcat "Valoare gresita: " (cadr f))) (mode_tile (car f) 2) nil)
    (progn (setq *TKC:WK* (subst (cons (car f) v) (assoc (car f) *TKC:WK*) *TKC:WK*)) T)))

;; TKCADSET - setarile modulului
(defun TKC:CmdSet (/ fn f id r)
  (setq *TKC:WK* (TKC:CfgAll) fn (vl-filename-mktemp "tkcset" nil ".dcl") f (open fn "w") r 0)
  (foreach ln (TKC:DclSet) (write-line ln f))
  (close f)
  (setq id (load_dialog fn))
  (if (and (>= id 0) (new_dialog "tkc_set" id))
    (progn
      (foreach fl *TKC:FIELDS* (TKC:SetInit fl))
      (action_tile "accept" "(if (vl-every 'TKC:SetRead *TKC:FIELDS*) (done_dialog 1))")
      (setq r (start_dialog))))
  (if (>= id 0) (unload_dialog id))
  (vl-file-delete fn)
  (if (= r 1) (progn (setq *TKC:CFG* *TKC:WK*) (TKC:SaveCfg) (TKC:Msg "Setarile au fost salvate in desen."))))

;;; ==========================================================================
;;;  COMENZI, AJUTOR, MENIU
;;; ==========================================================================

(defun c:TKPCT () (TKC:Run '(TKC:CmdPct)) (princ))
(defun c:TKPCTCONTUR () (TKC:Run '(TKC:CmdContur)) (princ))
(defun c:TKIMPPCT () (TKC:Run '(TKC:CmdImport)) (princ))
(defun c:TKEXPPCT () (TKC:Run '(TKC:CmdExport)) (princ))
(defun c:TKSTERGPCT () (TKC:Run '(TKC:CmdSterg)) (princ))
(defun c:TKRENUM () (TKC:Run '(TKC:CmdRenum)) (princ))
(defun c:TKSELCOD () (TKC:Run '(TKC:CmdSelCod)) (princ))
(defun c:TKSCHCOD () (TKC:Run '(TKC:CmdSchCod)) (princ))
(defun c:TKSUPRAF () (TKC:Run '(TKC:CmdSupraf)) (princ))
(defun c:TKCOTE () (TKC:Run '(TKC:CmdCote)) (princ))
(defun c:TKSUMA () (TKC:Run '(TKC:CmdSuma)) (princ))
(defun c:TKDETASARE () (TKC:Run '(TKC:CmdDet)) (redraw) (princ))
(defun c:TKDETMULT () (TKC:Run '(TKC:CmdDetMult)) (redraw) (princ))
(defun c:TKCADSET () (TKC:Run '(TKC:CmdSet)) (princ))

(setq *TKC:CMDS*
       '(("TKDETASARE" "Detaseaza o suprafata (paralela, directie, perpendiculara, punct obligat)")
         ("TKDETMULT" "Detasari multiple dintr-un tabel (manual sau Excel / CSV)")
         ("TKSUPRAF" "Calculeaza suprafete (S= in centrul poligonului, hasura optionala)")
         ("TKCOTE" "Coteaza laturile poliliniilor")
         ("TKSUMA" "Suma numerelor din texte")
         ("TKPCT" "Introducere puncte (bloc TopoLT)")
         ("TKPCTCONTUR" "Puncte in varfurile poliliniilor")
         ("TKIMPPCT" "Raporteaza puncte din fisier (bloc TopoLT)")
         ("TKEXPPCT" "Reface fisierul de coordonate")
         ("TKSTERGPCT" "Sterge puncte (cu textele legate)")
         ("TKRENUM" "Renumeroteaza puncte")
         ("TKSELCOD" "Selecteaza puncte dupa cod")
         ("TKSCHCOD" "Schimba codul punctelor")
         ("TKCADSET" "Setari: scara, inaltimi text, zecimale")))

(defun c:TKCAD ()
  (textscr)
  (princ "\n=== TopoKit - cadastru ===")
  (foreach c *TKC:CMDS* (princ (strcat "\n" (TKC:Pad (car c) 12) " - " (cadr c))))
  (princ))

;; TKC:Menu - meniul "TopoKit" in bara de meniuri AutoCAD (vizibila daca MENUBAR = 1;
;; setarea utilizatorului nu se schimba)
(defun TKC:Item (pm lbl cmd) (vla-addmenuitem pm (vla-get-count pm) lbl (strcat (chr 3) (chr 3) "_" cmd " ")))
(defun TKC:Sep (pm) (vla-addseparator pm (vla-get-count pm)))
(defun TKC:SubMenu (pm lbl) (vla-addsubmenu pm (vla-get-count pm) lbl))

(defun TKC:Menu (/ acad pms pm r s)
  (setq acad (vlax-get-acad-object)
        pms (vla-get-menus (vla-item (vla-get-menugroups acad) 0))
        r (vl-catch-all-apply 'vla-item (list pms "TopoKit")))
  (setq pm (if (vl-catch-all-error-p r) (vla-add pms "TopoKit") r))
  (while (> (vla-get-count pm) 0) (vla-delete (vla-item pm (1- (vla-get-count pm)))))
  (TKC:Item pm "Fereastra TopoKit..." "TOPOKIT")
  (TKC:Item pm "Setari module..." "TOPOKITSET")
  (TKC:Sep pm)
  (setq s (TKC:SubMenu pm "Proiect"))
  (TKC:Item s "Pregatire proiect nou..." "TKPROIECT")
  (TKC:Item s "Schimba scara planului" "TKSCARA")
  (TKC:Item s "Caroiaj de coordonate" "TKCAROIAJ")
  (TKC:Item s "Legenda automata" "TKLEGENDA")
  (setq s (TKC:SubMenu pm "Suprafete"))
  (TKC:Item s "Calculeaza suprafete" "TKSUPRAF")
  (TKC:Item s "Detaseaza o suprafata" "TKDETASARE")
  (TKC:Item s "Detasari multiple" "TKDETMULT")
  (setq s (TKC:SubMenu pm "Puncte"))
  (TKC:Item s "Introducere puncte" "TKPCT")
  (TKC:Item s "Puncte pe contur" "TKPCTCONTUR")
  (TKC:Item s "Renumeroteaza puncte" "TKRENUM")
  (TKC:Item s "Sterge puncte" "TKSTERGPCT")
  (TKC:Sep s)
  (TKC:Item s "Selecteaza dupa cod" "TKSELCOD")
  (TKC:Item s "Schimba codul" "TKSCHCOD")
  (setq s (TKC:SubMenu pm "Coordonate"))
  (TKC:Item s "Raporteaza puncte (TopoLT)" "TKIMPPCT")
  (TKC:Item s "Import puncte si linii pe coduri" "IMPPCT")
  (TKC:Item s "Reface fisier coordonate" "TKEXPPCT")
  (TKC:Item s "Tabel coordonate" "TABPCT")
  (setq s (TKC:SubMenu pm "Utile"))
  (TKC:Item s "Coteaza polilinii" "TKCOTE")
  (TKC:Item s "Suma texte" "TKSUMA")
  (TKC:Item s "Corectie topologica (vertexi)" "ADDVTX")
  (TKC:Sep pm)
  (TKC:Item pm "Anexe Ordin 600/2023..." "ANEXE")
  (TKC:Item pm "Teren si volume..." "TOPOTEREN")
  (TKC:Item pm "Export KMZ" "EXPKMZ")
  (TKC:Item pm "DWG to KMZ" "DWGKMZ")
  (TKC:Item pm "Calcul inclinatie" "PLANINCL")
  (TKC:Sep pm)
  (TKC:Item pm "Setari cadastru..." "TKCADSET")
  (TKC:Item pm "Lista comenzilor cadastru" "TKCAD")
  (if (= :vlax-false (vla-get-onmenubar pm))
    (vla-insertinmenubar pm (vla-get-count (vla-get-menubar acad)))))

(setq *TKC:CFG* nil)
(vl-catch-all-apply 'TKC:CfgAll nil)
(if (vl-catch-all-error-p (vl-catch-all-apply 'TKC:Menu nil))
  (princ "\nMeniul TopoKit nu a putut fi adaugat in bara de meniuri; comenzile merg din linia de comanda."))

(setq *TKC:LOADING* nil)
(princ "\nTopoKit Cadastru incarcat. Comenzi: TKDETASARE, TKDETMULT, TKSUPRAF, TKCOTE, TKSUMA, TKPCT ... (lista: TKCAD).")
(princ)
