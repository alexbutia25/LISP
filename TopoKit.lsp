;;; ==========================================================================
;;;  TopoKit.lsp  -  Suită de instrumente AutoLISP pentru topografie/cadastru
;;; ==========================================================================
;;;
;;;  Comenzi:
;;;    TOPOKIT / MYTOPO  - deschide meniul grafic (DCL) cu cele 3 module
;;;    ADDVTX            - corecție topologică: vertex-uri la intersecții
;;;    EXPKMZ            - export parcelă închisă în KMZ/KML (Stereo 70 -> WGS84)
;;;    INSCADRU          - inserare format A4..A0, cadru și indicator la scară
;;;
;;;  Fișiere:
;;;    TopoKit.lsp  - acest fișier (se încarcă cu APPLOAD)
;;;    TopoKit.dcl  - interfața grafică; opțional, dacă lipsește din căile
;;;                   de suport, este generat automat într-un fișier temporar
;;;
;;;  Convenții:
;;;    - Unitatea de desen este METRUL (coordonate Stereo 70).
;;;    - Implicit: X AutoCAD = Est (Y Stereo 70), Y AutoCAD = Nord (X Stereo 70).
;;;      Pentru desene cu axele inversate se bifează "Axe inversate".
;;;    - Mesajele afișate în AutoCAD sunt fără diacritice, pentru a fi
;;;      afișate corect indiferent de codificarea (ANSI/UTF-8) a sistemului.
;;; ==========================================================================

(vl-load-com)

;;; --------------------------------------------------------------------------
;;;  Setări globale implicite (păstrate pe durata sesiunii AutoCAD).
;;;  Comutatoarele sunt memorate ca "1"/"0" pentru compatibilitate cu DCL.
;;; --------------------------------------------------------------------------
(foreach p '((*TK:TOL*     . 0.001)          ; toleranța geometrică (m)
             (*TK:CONTACT* . "1")            ; include punctele de contact
             (*TK:NUME*    . "Parcela")      ; numele parcelei exportate
             (*TK:KMZ*     . "1")            ; 1 = KMZ, 0 = KML
             (*TK:PUNCTE*  . "1")            ; exportă și punctele de contur
             (*TK:SWAPXY*  . "0")            ; 1 = X desen este Nordul
             (*TK:OPENGE*  . "1")            ; deschide în Google Earth Pro
             (*TK:USEGRID* . "1")            ; folosește grila NTv2 (precizie cm)
             (*TK:FORMAT*  . 1)              ; index în *TK:FORMATE* (A3)
             (*TK:ORIENT*  . "L")            ; "P" portrait / "L" landscape
             (*TK:SCARA*   . 2)              ; index în *TK:SCARI* (1:500)
             (*TK:CAROIAJ* . "0")            ; caroiaj de coordonate
             (*TK:BENEF*   . "")
             (*TK:LUCRARE* . "")
             (*TK:TITLU*   . "PLAN DE SITUATIE")
             (*TK:EXEC*    . "")
             (*TK:PLANSA*  . "1"))
  (if (null (eval (car p))) (set (car p) (cdr p))))

;; Formatele de hârtie ISO 216 (lățime înălțime în mm, orientare portrait)
(setq *TK:FORMATE* '(("A4" 210.0 297.0) ("A3" 297.0 420.0) ("A2" 420.0 594.0)
                     ("A1" 594.0 841.0) ("A0" 841.0 1189.0)))
;; Scările disponibile (numitorul scării)
(setq *TK:SCARI* '(100 200 500 1000 2000 5000))
;; Numele stratului dedicat cadrului
(setq *TK:LAYCADRU* "L_CADRU")
;; Resetează starea de rulare la reîncărcarea fișierului
(setq *TK:ACTIVE* nil *TK:FH* nil *TK:DLGRUN* nil *TK:GRID* nil *TK:DLGMAIN* nil)

;;; ==========================================================================
;;;  FUNCȚII UTILITARE GENERALE
;;; ==========================================================================

;; TK:Start - pornește o comandă: salvează variabilele de sistem
;; (CMDECHO, OSMODE, ATTREQ, DIMZIN) și deschide un grup UNDO.
(defun TK:Start ()
  (setq *TK:DOC* (vla-get-ActiveDocument (vlax-get-acad-object)))
  (if (not *TK:ACTIVE*)
    (progn
      (setq *TK:OLDVARS*
             (mapcar '(lambda (v) (cons v (getvar v)))
                     '("CMDECHO" "OSMODE" "ATTREQ" "DIMZIN")))
      (vla-StartUndoMark *TK:DOC*)
      (setq *TK:ACTIVE* T)))
  (setvar "CMDECHO" 0)
  (setvar "DIMZIN" 0)
  (princ))

;; TK:Stop - încheie comanda: restabilește variabilele de sistem salvate
;; și închide grupul UNDO. Poate fi apelată de mai multe ori fără efecte.
(defun TK:Stop ()
  (if *TK:ACTIVE*
    (progn
      (foreach p *TK:OLDVARS*
        (vl-catch-all-apply 'setvar (list (car p) (cdr p))))
      (vl-catch-all-apply 'vla-EndUndoMark (list *TK:DOC*))
      (setq *TK:ACTIVE* nil *TK:OLDVARS* nil)))
  (princ))

;; TK:Error - rutina comună de tratare a erorilor (apelată din *error*
;; local al fiecărei comenzi). Închide fișierele deschise, restabilește
;; variabilele și afișează mesajul, cu excepția anulării de către utilizator.
(defun TK:Error (msg)
  (if *TK:FH* (progn (vl-catch-all-apply 'close (list *TK:FH*)) (setq *TK:FH* nil)))
  (setq *TK:DLGRUN* nil)
  (TK:GridClose)
  (TK:Stop)
  (if (and msg (not (wcmatch (strcase msg T) "*break*,*cancel*,*exit*")))
    (princ (strcat "\n** Eroare TopoKit: " msg " **")))
  (princ))

;; TK:Tan - tangenta unui unghi (AutoLISP nu are funcția tan)
(defun TK:Tan (x) (/ (sin x) (cos x)))

;; TK:Asin - arcsinus, calculat cu atan
(defun TK:Asin (x) (atan x (sqrt (max 0.0 (- 1.0 (* x x))))))

;; TK:Rad - transformă grade sexagesimale zecimale în radiani
(defun TK:Rad (d) (* pi (/ d 180.0)))

;; TK:Deg - transformă radiani în grade zecimale
(defun TK:Deg (r) (* 180.0 (/ r pi)))

;; TK:Sign - semnul unui număr (-1.0 sau 1.0)
(defun TK:Sign (x) (if (minusp x) -1.0 1.0))

;; TK:Mod2Pi - aduce un unghi în intervalul [0, 2*pi)
(defun TK:Mod2Pi (a)
  (while (< a 0.0) (setq a (+ a pi pi)))
  (while (>= a (+ pi pi)) (setq a (- a pi pi)))
  a)

;; TK:2d - reține doar coordonatele X,Y ale unui punct
(defun TK:2d (p) (list (car p) (cadr p)))

;; TK:Mid - mijlocul segmentului dintre două puncte
(defun TK:Mid (a b) (mapcar '(lambda (x y) (/ (+ x y) 2.0)) a b))

;; Operații vectoriale 2D: adunare, scădere, înmulțire cu scalar,
;; produs scalar și produs vectorial (componenta Z)
(defun TK:v+ (a b) (list (+ (car a) (car b)) (+ (cadr a) (cadr b))))
(defun TK:v- (a b) (list (- (car a) (car b)) (- (cadr a) (cadr b))))
(defun TK:vx (a s) (list (* (car a) s) (* (cadr a) s)))
(defun TK:Dot (a b) (+ (* (car a) (car b)) (* (cadr a) (cadr b))))
(defun TK:Cross (a b) (- (* (car a) (cadr b)) (* (cadr a) (car b))))

;; TK:SetNth - returnează lista L cu elementul de pe poziția N înlocuit cu V
(defun TK:SetNth (l n v / i)
  (setq i -1)
  (mapcar '(lambda (x) (if (= (setq i (1+ i)) n) v x)) l))

;; TK:PutDxf - înlocuiește (sau adaugă) grupul DXF cu codul C în lista ED
(defun TK:PutDxf (c v ed)
  (if (assoc c ed)
    (subst (cons c v) (assoc c ed) ed)
    (append ed (list (cons c v)))))

;; TK:CleanDxf - elimină din lista DXF grupurile care nu pot fi folosite
;; la entmake (nume entitate, handle, proprietar, reactori, dicționare)
(defun TK:CleanDxf (ed)
  (vl-remove-if '(lambda (g) (member (car g) '(-1 5 330 360 102 91))) ed))

;; TK:StrReplace - înlocuiește toate aparițiile lui OLD cu NEW în șirul S
(defun TK:StrReplace (s old new / i)
  (setq i 0)
  (while (setq i (vl-string-search old s i))
    (setq s (strcat (substr s 1 i) new (substr s (+ i 1 (strlen old))))
          i (+ i (strlen new))))
  s)

;; TK:XmlEsc - protejează caracterele speciale XML (&, <, >, ")
(defun TK:XmlEsc (s)
  (TK:StrReplace
    (TK:StrReplace (TK:StrReplace (TK:StrReplace s "&" "&amp;") "<" "&lt;") ">" "&gt;")
    "\"" "&quot;"))

;; TK:SafeName - transformă un text într-un nume de fișier valid
(defun TK:SafeName (s)
  (foreach c '("\\" "/" ":" "*" "?" "\"" "<" ">" "|" " ")
    (setq s (TK:StrReplace s c "_")))
  (if (= s "") "Parcela" s))

;; TK:Stamp - marcaj de timp AAAAMMZZ_hhmmss (din variabila CDATE)
(defun TK:Stamp (/ s)
  (setq s (rtos (getvar "CDATE") 2 6))
  (strcat (substr s 1 8) "_" (substr s 10 6)))

;; TK:Today - data curentă în format ZZ.LL.AAAA
(defun TK:Today (/ s)
  (setq s (rtos (getvar "CDATE") 2 6))
  (strcat (substr s 7 2) "." (substr s 5 2) "." (substr s 1 4)))

;; TK:EnvOr - valoarea unei variabile de mediu sau o valoare implicită
(defun TK:EnvOr (v def) (cond ((getenv v)) (def)))

;; TK:TempDir - directorul temporar al utilizatorului (cu "\" la final)
(defun TK:TempDir ()
  (strcat (vl-string-right-trim "\\" (TK:EnvOr "TEMP" (TK:EnvOr "TMP" "C:\\Temp"))) "\\"))

;; TK:Run - rulează o linie de comandă Windows prin WScript.Shell.
;; WAIT = T așteaptă terminarea; returnează codul de ieșire sau nil.
(defun TK:Run (cmd wait / sh res)
  (if (setq sh (vlax-create-object "WScript.Shell"))
    (progn
      (setq res (vl-catch-all-apply 'vlax-invoke-method
                  (list sh 'Run cmd 0 (if wait :vlax-true :vlax-false))))
      (vlax-release-object sh)
      (if (vl-catch-all-error-p res) nil res))))

;; TK:MakeLayer - creează stratul NUME cu culoarea COL dacă nu există
(defun TK:MakeLayer (name col)
  (if (not (tblsearch "LAYER" name))
    (entmake (list '(0 . "LAYER") '(100 . "AcDbSymbolTableRecord")
                   '(100 . "AcDbLayerTableRecord") (cons 2 name) '(70 . 0)
                   (cons 62 col) '(6 . "Continuous"))))
  name)

;; TK:Style - creează (dacă lipsește) stilul de text TK_ARIAL; returnează numele
(defun TK:Style ()
  (if (not (tblsearch "STYLE" "TK_ARIAL"))
    (entmake (list '(0 . "STYLE") '(100 . "AcDbSymbolTableRecord")
                   '(100 . "AcDbTextStyleTableRecord") '(2 . "TK_ARIAL")
                   '(70 . 0) '(40 . 0.0) '(41 . 1.0) '(50 . 0.0) '(71 . 0)
                   '(42 . 2.5) '(3 . "arial.ttf") '(4 . ""))))
  "TK_ARIAL")

;; TK:Line - desenează o linie între P1 și P2 pe stratul LAY (grosime LW)
(defun TK:Line (p1 p2 lay lw)
  (entmake (append (list '(0 . "LINE") (cons 8 lay))
                   (if lw (list (cons 370 lw)))
                   (list (list 10 (car p1) (cadr p1) 0.0)
                         (list 11 (car p2) (cadr p2) 0.0)))))

;; TK:Rect - desenează un dreptunghi (LWPOLYLINE închisă) pe stratul LAY
(defun TK:Rect (x1 y1 x2 y2 lay lw)
  (entmake (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") (cons 8 lay)
                 (cons 370 lw) '(100 . "AcDbPolyline") '(90 . 4) '(70 . 1)
                 (list 10 x1 y1) (list 10 x2 y1) (list 10 x2 y2) (list 10 x1 y2))))

;; TK:Text - scrie textul S în punctul P (înălțime H, rotație ROT radiani)
(defun TK:Text (s p h rot lay)
  (entmake (list '(0 . "TEXT") (cons 8 lay) (list 10 (car p) (cadr p) 0.0)
                 (cons 40 h) (cons 1 s) (cons 50 rot) (cons 7 (TK:Style)))))

;; TK:AttDef - definește un atribut (ATTDEF) în blocul aflat în construcție
(defun TK:AttDef (tag prompt def p h)
  (entmake (list '(0 . "ATTDEF") '(8 . "0") (list 10 (car p) (cadr p) 0.0)
                 (cons 40 h) (cons 1 def) (cons 3 prompt) (cons 2 tag)
                 '(70 . 0) (cons 7 (TK:Style)))))

;;; ==========================================================================
;;;  MODULUL 1 - CORECȚIE TOPOLOGICĂ (ADDVTX)
;;; ==========================================================================
;;;  Structura internă a unei polilinii (înregistrare "rec"):
;;;    (ename tip închisă normală vertexuri)
;;;      tip       = LW (LWPOLYLINE), 2D (POLYLINE 2D), 3D (POLYLINE 3D)
;;;      vertexuri = listă de (punctWCS bulge lățimeStart lățimeFinal dxfBrut)
;;;  Structura unui segment:
;;;    (index punctStart2D punctFinal2D dateArc casetă)
;;;      dateArc = nil pentru segment drept sau (centru rază unghiStart unghiLa)
;;;      casetă  = (xmin ymin xmax ymax)
;;;  Intersecțiile se calculează în plan (proiecție XY), iar noile vertex-uri
;;;  primesc cota Z interpolată pe segmentul propriu fiecărei polilinii, deci
;;;  cotele existente și forma segmentelor (inclusiv arcele) nu se modifică.
;;; ==========================================================================

;; TK:PlanNormal - T dacă vectorul normal este paralel cu axa Z (desen în plan)
(defun TK:PlanNormal (n)
  (and (equal (car n) 0.0 1e-9) (equal (cadr n) 0.0 1e-9)))

;; TK:PolyRead - citește o polilinie și returnează înregistrarea internă,
;; sau nil pentru polilinii ce nu pot fi procesate (plase 3D, polifețe,
;; polilinii netezite spline/curve-fit sau neparalele cu planul XY).
(defun TK:PolyRead (e / ed typ flag norm sgn elev verts cur is3d hw0 hw1 ve vd p)
  (setq ed   (entget e)
        typ  (cdr (assoc 0 ed))
        flag (cdr (assoc 70 ed))
        norm (cond ((cdr (assoc 210 ed))) ('(0.0 0.0 1.0))))
  (cond
    ;; ---- LWPOLYLINE: vertex-urile sunt în OCS, cota comună în grupul 38
    ((= typ "LWPOLYLINE")
     (if (TK:PlanNormal norm)
       (progn
         (setq sgn  (TK:Sign (caddr norm))
               elev (cond ((cdr (assoc 38 ed))) (0.0)))
         (foreach g ed
           (cond
             ((= (car g) 10)
              (if cur (setq verts (cons cur verts)))
              (setq cur (list (trans (list (cadr g) (caddr g) elev) norm 0) 0.0 0.0 0.0 nil)))
             ((null cur))
             ((= (car g) 40) (setq cur (TK:SetNth cur 2 (cdr g))))
             ((= (car g) 41) (setq cur (TK:SetNth cur 3 (cdr g))))
             ((= (car g) 42) (setq cur (TK:SetNth cur 1 (* sgn (cdr g)))))))
         (if cur (setq verts (cons cur verts)))
         (list e 'LW (= 1 (logand 1 flag)) norm (reverse verts)))))
    ;; ---- POLYLINE (2D sau 3D): vertex-urile sunt entități VERTEX separate
    ((= typ "POLYLINE")
     (if (and (= 0 (logand flag (+ 2 4 16 64)))
              (or (setq is3d (= 8 (logand 8 flag))) (TK:PlanNormal norm)))
       (progn
         (setq sgn  (if is3d 1.0 (TK:Sign (caddr norm)))
               elev (caddr (cdr (assoc 10 ed)))
               hw0  (cond ((cdr (assoc 40 ed))) (0.0))
               hw1  (cond ((cdr (assoc 41 ed))) (0.0))
               ve   (entnext e))
         (while (and ve (= "VERTEX" (cdr (assoc 0 (setq vd (entget ve))))))
           (setq p (cdr (assoc 10 vd))
                 p (if is3d p (trans (list (car p) (cadr p) elev) norm 0))
                 verts (cons (list p
                                   (* sgn (cond ((cdr (assoc 42 vd))) (0.0)))
                                   (cond ((cdr (assoc 40 vd))) (hw0))
                                   (cond ((cdr (assoc 41 vd))) (hw1))
                                   (TK:CleanDxf vd))
                             verts)
                 ve (entnext ve)))
         (list e (if is3d '3D '2D) (= 1 (logand 1 flag)) norm (reverse verts)))))))

;; TK:ArcData - calculează datele arcului definit de P1, P2 și bulge B:
;; (centru rază unghiStart unghiLaCentru). Unghiul este pozitiv pentru
;; arcele parcurse trigonometric (bulge > 0) și negativ în sens orar.
(defun TK:ArcData (p1 p2 b / c)
  (setq c (polar p1 (+ (angle p1 p2) (- (/ pi 2.0) (* 2.0 (atan b))))
                 (/ (* (distance p1 p2) (+ 1.0 (* b b))) 4.0 b)))
  (list (TK:2d c) (distance c p1) (angle c p1) (* 4.0 (atan b))))

;; TK:MakeSeg - construiește un segment (drept sau arc) cu caseta sa
(defun TK:MakeSeg (i pa pb b / arc box)
  (if (> (abs b) 1e-9)
    (setq arc (TK:ArcData pa pb b)
          box (list (- (caar arc) (cadr arc)) (- (cadar arc) (cadr arc))
                    (+ (caar arc) (cadr arc)) (+ (cadar arc) (cadr arc))))
    (setq box (list (min (car pa) (car pb)) (min (cadr pa) (cadr pb))
                    (max (car pa) (car pb)) (max (cadr pa) (cadr pb)))))
  (list i pa pb arc box))

;; TK:PolySegs - lista segmentelor unei polilinii (fără cele de lungime nulă)
(defun TK:PolySegs (rec / verts n i segs pa pb)
  (setq verts (nth 4 rec) n (length verts) i 0)
  (mapcar
    '(lambda (v nx)
       (if (or (nth 2 rec) (< i (1- n)))
         (progn
           (setq pa (TK:2d (car v)) pb (TK:2d (car nx)))
           (if (> (distance pa pb) *TK:TOL*)
             (setq segs (cons (TK:MakeSeg i pa pb (cadr v)) segs)))))
       (setq i (1+ i)))
    verts (append (cdr verts) (list (car verts))))
  (reverse segs))

;; TK:SegsBox - caseta de încadrare a unei liste de segmente
(defun TK:SegsBox (segs)
  (list (apply 'min (mapcar '(lambda (s) (car (nth 4 s))) segs))
        (apply 'min (mapcar '(lambda (s) (cadr (nth 4 s))) segs))
        (apply 'max (mapcar '(lambda (s) (caddr (nth 4 s))) segs))
        (apply 'max (mapcar '(lambda (s) (cadddr (nth 4 s))) segs))))

;; TK:BoxOverlap - T dacă două casete se suprapun (cu toleranța curentă)
(defun TK:BoxOverlap (b1 b2)
  (and (<= (car b1) (+ (caddr b2) *TK:TOL*)) (<= (car b2) (+ (caddr b1) *TK:TOL*))
       (<= (cadr b1) (+ (cadddr b2) *TK:TOL*)) (<= (cadr b2) (+ (cadddr b1) *TK:TOL*))))

;; TK:InBox - T dacă punctul P se află în caseta BOX (cu toleranță)
(defun TK:InBox (p box)
  (and (>= (car p) (- (car box) *TK:TOL*)) (<= (car p) (+ (caddr box) *TK:TOL*))
       (>= (cadr p) (- (cadr box) *TK:TOL*)) (<= (cadr p) (+ (cadddr box) *TK:TOL*))))

;; TK:InRange - T dacă parametrul U se află în [0,1] cu toleranța TL
(defun TK:InRange (u tl) (and (>= u (- tl)) (<= u (+ 1.0 tl))))

;; TK:ArcPos - unghiul parcurs pe arc de la punctul de start până la P
;; (în sensul arcului, valoare în [0, 2*pi))
(defun TK:ArcPos (p arc)
  (if (> (nth 3 arc) 0.0)
    (TK:Mod2Pi (- (angle (car arc) p) (nth 2 arc)))
    (TK:Mod2Pi (- (nth 2 arc) (angle (car arc) p)))))

;; TK:OnArc - T dacă punctul P (aflat pe cercul suport) este pe arcul ARC
(defun TK:OnArc (p arc / d ta)
  (setq d  (TK:ArcPos p arc)
        ta (/ *TK:TOL* (cadr arc)))
  (or (<= d (+ (abs (nth 3 arc)) ta)) (>= d (- (+ pi pi) ta))))

;; TK:IntLL - intersecția a două segmente drepte AB și CD.
;; Segmentele paralele/colineare nu au punct unic (tratate prin contacte).
(defun TK:IntLL (a b c d / r s den w tt uu lr ls)
  (setq r (TK:v- b a) s (TK:v- d c) den (float (TK:Cross r s))
        lr (distance a b) ls (distance c d))
  (if (> (abs den) (* 1e-12 lr ls))
    (progn
      (setq w  (TK:v- c a)
            tt (/ (TK:Cross w s) den)
            uu (/ (TK:Cross w r) den))
      (if (and (TK:InRange tt (/ *TK:TOL* lr)) (TK:InRange uu (/ *TK:TOL* ls)))
        (list (TK:v+ a (TK:vx r tt)))))))

;; TK:IntLC - intersecția segmentului drept AB cu cercul suport al arcului
(defun TK:IntLC (a b arc / c r v l2 l w bq cq dl tl sq res)
  (setq c (car arc) r (cadr arc) v (TK:v- b a) l2 (TK:Dot v v) l (sqrt l2)
        w (TK:v- a c) bq (TK:Dot v w) cq (- (TK:Dot w w) (* r r))
        dl (/ (abs (TK:Cross v (TK:v- c a))) l)
        tl (/ *TK:TOL* l))
  (cond
    ((> dl (+ r *TK:TOL*)) nil)
    ((> dl (- r *TK:TOL*))              ; dreaptă tangentă: un singur punct
     (setq sq (/ (- bq) l2))
     (if (TK:InRange sq tl) (list (TK:v+ a (TK:vx v sq)))))
    (T
     (setq sq (sqrt (max 0.0 (- (* bq bq) (* l2 cq)))))
     (foreach u (list (/ (- (- bq) sq) l2) (/ (+ (- bq) sq) l2))
       (if (TK:InRange u tl) (setq res (cons (TK:v+ a (TK:vx v u)) res))))
     res)))

;; TK:IntCC - intersecția cercurilor suport a două arce
(defun TK:IntCC (a1 a2 / c1 r1 c2 r2 d aa h u p n)
  (setq c1 (car a1) r1 (cadr a1) c2 (car a2) r2 (cadr a2) d (distance c1 c2))
  (cond
    ((< d *TK:TOL*) nil)                              ; cercuri concentrice
    ((> d (+ r1 r2 *TK:TOL*)) nil)                    ; cercuri exterioare
    ((< d (- (abs (- r1 r2)) *TK:TOL*)) nil)          ; un cerc în celălalt
    (T
     (setq aa (/ (+ (- (* r1 r1) (* r2 r2)) (* d d)) (* 2.0 d))
           h  (sqrt (max 0.0 (- (* r1 r1) (* aa aa))))
           u  (TK:vx (TK:v- c2 c1) (/ 1.0 d))
           p  (TK:v+ c1 (TK:vx u aa))
           n  (list (- (cadr u)) (car u)))
     (if (< h *TK:TOL*)
       (list p)
       (list (TK:v+ p (TK:vx n h)) (TK:v- p (TK:vx n h)))))))

;; TK:IntSegSeg - punctele de intersecție dintre două segmente (drepte/arce)
(defun TK:IntSegSeg (s1 s2 / a1 a2)
  (setq a1 (nth 3 s1) a2 (nth 3 s2))
  (cond
    ((not (TK:BoxOverlap (nth 4 s1) (nth 4 s2))) nil)
    ((and (not a1) (not a2)) (TK:IntLL (cadr s1) (caddr s1) (cadr s2) (caddr s2)))
    ((not a1) (vl-remove-if-not '(lambda (p) (TK:OnArc p a2)) (TK:IntLC (cadr s1) (caddr s1) a2)))
    ((not a2) (vl-remove-if-not '(lambda (p) (TK:OnArc p a1)) (TK:IntLC (cadr s2) (caddr s2) a1)))
    (T (vl-remove-if-not '(lambda (p) (and (TK:OnArc p a1) (TK:OnArc p a2))) (TK:IntCC a1 a2)))))

;; TK:OnSeg - T dacă punctul P se află pe segmentul SEG (în toleranță).
;; Folosit pentru punctele de contact (vertex al unei polilinii situat pe
;; segmentul alteia: îmbinări în "T", capete, suprapuneri colineare).
(defun TK:OnSeg (p seg / a b arc v l u)
  (if (TK:InBox p (nth 4 seg))
    (progn
      (setq a (cadr seg) b (caddr seg) arc (nth 3 seg))
      (if arc
        (and (equal (distance (car arc) p) (cadr arc) *TK:TOL*) (TK:OnArc p arc))
        (progn
          (setq v (TK:v- b a) l (distance a b) u (/ (TK:Dot (TK:v- p a) v) (* l l)))
          (and (TK:InRange u (/ *TK:TOL* l))
               (< (/ (abs (TK:Cross v (TK:v- p a))) l) *TK:TOL*)))))))

;; TK:SegKeys - pentru punctele PTS de inserat pe segmentul SEG returnează
;; lista sortată de (poziție punct), unde poziția este distanța (segment
;; drept) sau unghiul parcurs (arc) de la începutul segmentului. Punctele
;; sunt proiectate exact pe segment, iar cele care coincid cu vertex-uri
;; existente sau între ele (duplicate) sunt eliminate.
(defun TK:SegKeys (seg pts / pa pb arc tot k q lst out u)
  (setq pa (cadr seg) pb (caddr seg) arc (nth 3 seg)
        tot (if arc (abs (nth 3 arc)) (distance pa pb)))
  (foreach p pts
    (setq p (TK:2d p))
    (if (and (> (distance p pa) *TK:TOL*) (> (distance p pb) *TK:TOL*))
      (progn
        (if arc
          (setq k (TK:ArcPos p arc)
                q (polar (car arc) (+ (nth 2 arc) (* (TK:Sign (nth 3 arc)) k)) (cadr arc)))
          (setq u (TK:vx (TK:v- pb pa) (/ 1.0 tot))
                k (TK:Dot (TK:v- p pa) u)
                q (TK:v+ pa (TK:vx u k))))
        (if (and (> k 0.0) (< k tot))
          (setq lst (cons (list k (TK:2d q)) lst))))))
  (foreach x (vl-sort lst '(lambda (a b) (< (car a) (car b))))
    (if (or (null out) (> (distance (cadr x) (cadr (car out))) *TK:TOL*))
      (setq out (cons x out))))
  (reverse out))

;; TK:NewVerts - construiește noua listă de vertex-uri a poliliniei REC,
;; inserând punctele din LST = listă de (indexSegment punct).
;; Pe arce, bulge-ul se împarte exact pe sub-arce; lățimile și cotele Z
;; se interpolează liniar. Returnează (listaVertexuri . nrAdăugate).
(defun TK:NewVerts (rec segs lst / verts n i out added seg pts kp arc pa tot
                                   nx sw ew za zb cur pk pw fr w1 bs)
  (setq verts (nth 4 rec) n (length verts) i 0 added 0)
  (foreach v verts
    (setq seg (assoc i segs)
          pts (if seg (mapcar 'cadr (vl-remove-if-not '(lambda (x) (= (car x) i)) lst)))
          kp  (if pts (TK:SegKeys seg pts)))
    (if kp
      (progn
        (setq arc (nth 3 seg) pa (cadr seg)
              tot (if arc (abs (nth 3 arc)) (distance pa (caddr seg)))
              bs  (if arc (TK:Sign (nth 3 arc)) 0.0)
              nx  (nth (rem (1+ i) n) verts)
              sw  (caddr v) ew (cadddr v)
              za  (caddr (car v)) zb (caddr (car nx))
              cur (car v) pk 0.0 pw sw)
        (foreach x kp
          (setq fr (/ (car x) tot)
                w1 (+ sw (* (- ew sw) fr))
                out (cons (list cur (* bs (TK:Tan (/ (- (car x) pk) 4.0))) pw w1 (nth 4 v)) out)
                cur (list (car (cadr x)) (cadr (cadr x)) (+ za (* (- zb za) fr)))
                pk (car x) pw w1 added (1+ added)))
        (setq out (cons (list cur (* bs (TK:Tan (/ (- tot pk) 4.0))) pw ew (nth 4 v)) out)))
      (setq out (cons v out)))
    (setq i (1+ i)))
  (cons (reverse out) added))

;; TK:LayerLocked - T dacă entitatea se află pe un strat blocat
(defun TK:LayerLocked (e / l)
  (setq l (tblsearch "LAYER" (cdr (assoc 8 (entget e)))))
  (and l (= 4 (logand 4 (cdr (assoc 70 l))))))

;; TK:WriteLW - rescrie vertex-urile unei LWPOLYLINE (entmod); păstrează
;; handle-ul, proprietățile și datele extinse ale entității.
(defun TK:WriteLW (rec verts / e ed norm sgn head tail vg found p)
  (setq e (car rec) ed (entget e '("*")) norm (nth 3 rec) sgn (TK:Sign (caddr norm)))
  (foreach g ed
    (cond
      ((member (car g) '(10 40 41 42 91)) (setq found T))
      ((= (car g) 90) (setq head (cons (cons 90 (length verts)) head)))
      (found (setq tail (cons g tail)))
      (T (setq head (cons g head)))))
  (foreach v verts
    (setq p  (trans (car v) 0 norm)
          vg (cons (cons 42 (* sgn (cadr v)))
               (cons (cons 41 (cadddr v))
                 (cons (cons 40 (caddr v))
                   (cons (list 10 (car p) (cadr p)) vg))))))
  (if (entmod (append (reverse head) (reverse vg) (reverse tail)))
    (progn (entupd e) T)))

;; TK:WriteHeavy - reconstruiește o POLYLINE 2D/3D cu noile vertex-uri
;; (entmake antet + VERTEX + SEQEND), apoi șterge polilinia originală.
;; Proprietățile și datele extinse se copiază; handle-ul se schimbă.
(defun TK:WriteHeavy (rec verts / e ed norm is3d sgn ok vd p)
  (setq e (car rec) ed (entget e '("*")) norm (nth 3 rec)
        is3d (eq (nth 1 rec) '3D)
        sgn (if is3d 1.0 (TK:Sign (caddr norm))) ok T)
  (if (entmake (TK:CleanDxf ed))
    (progn
      (foreach v verts
        (if ok
          (progn
            (setq p  (if is3d (car v) (trans (car v) 0 norm))
                  vd (TK:PutDxf 10 p (nth 4 v))
                  vd (TK:PutDxf 40 (caddr v) vd)
                  vd (TK:PutDxf 41 (cadddr v) vd)
                  vd (TK:PutDxf 42 (* sgn (cadr v)) vd))
            (if (not (entmake vd)) (setq ok nil)))))
      (if (and ok (entmake (list '(0 . "SEQEND") (assoc 8 ed))))
        (progn (entdel e) T)
        (progn (entmake) nil)))))

;; TK:PolyWrite - scrie în desen noua geometrie a poliliniei
(defun TK:PolyWrite (rec verts)
  (cond
    ((TK:LayerLocked (car rec)) nil)
    ((eq (nth 1 rec) 'LW) (TK:WriteLW rec verts))
    (T (TK:WriteHeavy rec verts))))

;; TK:FindInserts - determină toate punctele de inserat pentru lista de
;; polilinii RECS = listă de (rec segmente casetă). Returnează o listă de
;; (indexPolilinie indexSegment punct).
(defun TK:FindInserts (recs / ins i j)
  (setq i 0)
  (foreach ri recs
    (setq j 0)
    (foreach rj recs
      (if (and (< i j) (TK:BoxOverlap (caddr ri) (caddr rj)))
        (progn
          ;; intersecții propriu-zise segment - segment
          (foreach s1 (cadr ri)
            (foreach s2 (cadr rj)
              (foreach p (TK:IntSegSeg s1 s2)
                (setq ins (cons (list i (car s1) p) (cons (list j (car s2) p) ins))))))
          ;; puncte de contact: vertex-urile uneia situate pe segmentele celeilalte
          (if (= *TK:CONTACT* "1")
            (progn
              (foreach v (nth 4 (car ri))
                (foreach s2 (cadr rj)
                  (if (TK:OnSeg (TK:2d (car v)) s2) (setq ins (cons (list j (car s2) (car v)) ins)))))
              (foreach v (nth 4 (car rj))
                (foreach s1 (cadr ri)
                  (if (TK:OnSeg (TK:2d (car v)) s1) (setq ins (cons (list i (car s1) (car v)) ins)))))))))
      (setq j (1+ j)))
    (setq i (1+ i)))
  ins)

;; C:ADDVTX - comanda de corecție topologică: adaugă vertex-uri pe fiecare
;; polilinie selectată în toate punctele de intersecție/contact cu celelalte.
(defun c:ADDVTX (/ *error* ss i e rec segs recs nsel nskip nlock nmod nadd ins k mine res)
  (defun *error* (msg) (TK:Error msg))
  (TK:Start)
  (princ "\nSelectati poliliniile pentru corectia topologica: ")
  (if (setq ss (ssget '((0 . "LWPOLYLINE,POLYLINE"))))
    (progn
      (setq i 0 nsel 0 nskip 0 nlock 0 nmod 0 nadd 0)
      ;; 1. citirea geometriei
      (repeat (sslength ss)
        (setq e (ssname ss i) i (1+ i))
        (if (and (setq rec (TK:PolyRead e)) (setq segs (TK:PolySegs rec)))
          (setq recs (cons (list rec segs (TK:SegsBox segs)) recs) nsel (1+ nsel))
          (setq nskip (1+ nskip))))
      (setq recs (reverse recs))
      (princ (strcat "\nAnaliza intersectiilor pentru " (itoa nsel) " polilinii..."))
      ;; 2. determinarea punctelor de intersecție (pe geometria originală)
      (setq ins (TK:FindInserts recs) k 0)
      ;; 3. inserarea vertex-urilor pe fiecare polilinie
      (foreach r recs
        (if (setq mine (vl-remove-if-not '(lambda (x) (= (car x) k)) ins))
          (progn
            (setq res (TK:NewVerts (car r) (cadr r) (mapcar 'cdr mine)))
            (if (> (cdr res) 0)
              (if (TK:PolyWrite (car r) (car res))
                (setq nmod (1+ nmod) nadd (+ nadd (cdr res)))
                (setq nlock (1+ nlock))))))
        (setq k (1+ k)))
      (if (> nskip 0)
        (princ (strcat "\n" (itoa nskip) " obiecte ignorate (plase 3D, polifete, polilinii spline/curve-fit, neparalele cu XY sau degenerate).")))
      (if (> nlock 0)
        (princ (strcat "\n" (itoa nlock) " polilinii nu au putut fi modificate (strat blocat).")))
      (princ (strcat "\nS-au procesat " (itoa nsel) " polilinii si s-au adaugat "
                     (itoa nadd) " vertex-uri noi."
                     (if (> nmod 0) (strcat " (" (itoa nmod) " polilinii modificate)") ""))))
    (princ "\nNu a fost selectata nicio polilinie."))
  (TK:Stop)
  (princ))

;;; ==========================================================================
;;;  MODULUL 2 - EXPORT KMZ (STEREO 70 -> WGS84)
;;; ==========================================================================
;;;  Etape de calcul:
;;;   1. Stereo 70 (E,N) -> latitudine/longitudine pe elipsoidul Krasovsky 1940
;;;      Proiecție stereografică oblică (dublă, pe sfera conformă Gauss),
;;;      EPSG metoda 9809: lat0 = 46 N, lon0 = 25 E, k0 = 0.99975,
;;;      FE = FN = 500 000 m.
;;;   2. Geodezice (Krasovsky) -> carteziene geocentrice X,Y,Z (h = 0).
;;;   2. Trecerea de la datumul S-42 (Krasovsky) la ETRS89/WGS84, prin una
;;;      din metodele de mai jos.
;;;
;;;   A. GRILA NTv2 (metoda implicită, precizie centimetrică):
;;;      fișierul "stereo70_etrs89A.gsb" (sub-grila "ANCPI+TN", derivată din
;;;      grila oficială de distorsiuni ANCPI/TransDatRO, pas 35" x 50").
;;;      Deplasările în latitudine/longitudine se interpolează biliniar, ca în
;;;      PROJ (+proj=hgridshift). Pe cele 11 puncte de control publicate
;;;      împreună cu grila, diferența față de coordonatele ETRS89 este 2-13 mm.
;;;      Fișierul binar este citit direct din LISP (ADODB.Stream).
;;;
;;;   B. HELMERT 7 PARAMETRI (rezervă: grila lipsește sau punctul este în
;;;      afara zonei acoperite). EPSG:15994, convenția "Coordinate Frame":
;;;        tx = 2.329 m, ty = -147.042 m, tz = -92.080 m
;;;        rx = 0.309", ry = -0.325", rz = -0.497", ds = 5.69 ppm
;;;      geodezice -> carteziene -> Helmert -> geodezice WGS84 (iterativ).
;;;      Coincide cu PROJ (EPSG:3844 -> 4326); față de grilă diferă cu
;;;      0.3 m (median) până la ~1.5 m pe teritoriul României.
;;; ==========================================================================

;; TK:S70Const - calculează (o singură dată) constantele proiecției Stereo 70
;; pe elipsoidul Krasovsky: (e2 e R n c chi0 k0 lon0)
(defun TK:S70Const (/ a f e2 e lat0 s0 k0 rho0 nu0 r n s1 s2 w1 sc c w2)
  (if (null *TK:S70*)
    (setq a    6378245.0
          f    (/ 1.0 298.3)
          e2   (- (* 2.0 f) (* f f))
          e    (sqrt e2)
          lat0 (TK:Rad 46.0)
          s0   (sin lat0)
          k0   0.99975
          rho0 (/ (* a (- 1.0 e2)) (expt (- 1.0 (* e2 s0 s0)) 1.5))  ; raza meridianului
          nu0  (/ a (sqrt (- 1.0 (* e2 s0 s0))))                       ; raza primului vertical
          r    (sqrt (* rho0 nu0))                                     ; raza sferei conforme
          n    (sqrt (+ 1.0 (/ (* e2 (expt (cos lat0) 4)) (- 1.0 e2))))
          s1   (/ (+ 1.0 s0) (- 1.0 s0))
          s2   (/ (- 1.0 (* e s0)) (+ 1.0 (* e s0)))
          w1   (expt (* s1 (expt s2 e)) n)
          sc   (/ (- w1 1.0) (+ w1 1.0))
          c    (/ (* (+ n s0) (- 1.0 sc)) (* (- n s0) (+ 1.0 sc)))
          w2   (* c w1)
          *TK:S70* (list e2 e r n c (TK:Asin (/ (- w2 1.0) (+ w2 1.0))) k0 (TK:Rad 25.0))))
  *TK:S70*)

;; TK:S70ToGeo - inversa proiecției Stereo 70: (E N) -> (lat lon) în radiani
;; pe elipsoidul Krasovsky 1940 (formulele EPSG, Guidance Note 7-2).
(defun TK:S70ToGeo (en / cs e2 e r n c chi0 k0 lon0 de dn rk g h i j chi lam psi phi
                         sp psii old it)
  (setq cs (TK:S70Const)
        e2 (nth 0 cs) e (nth 1 cs) r (nth 2 cs) n (nth 3 cs) c (nth 4 cs)
        chi0 (nth 5 cs) k0 (nth 6 cs) lon0 (nth 7 cs)
        de (- (car en) 500000.0)
        dn (- (cadr en) 500000.0)
        rk (* 2.0 r k0)
        g  (* rk (TK:Tan (- (/ pi 4.0) (/ chi0 2.0))))
        h  (+ (* 2.0 rk (TK:Tan chi0)) g)
        i  (atan (/ de (+ h dn)))
        j  (- (atan (/ de (- g dn))) i)
        chi (+ chi0 (* 2.0 (atan (/ (- dn (* de (TK:Tan (/ j 2.0)))) rk))))
        lam (+ (/ (+ j (* 2.0 i)) n) lon0)
        psi (/ (* 0.5 (log (/ (+ 1.0 (sin chi)) (* c (- 1.0 (sin chi)))))) n)
        phi (- (* 2.0 (atan (exp psi))) (/ pi 2.0))
        it 0)
  ;; iterație pentru latitudinea geodezică din latitudinea izometrică
  (while (and (< it 20) (or (null old) (> (abs (- phi old)) 1e-14)))
    (setq sp   (sin phi)
          psii (log (* (TK:Tan (+ (/ phi 2.0) (/ pi 4.0)))
                       (expt (/ (- 1.0 (* e sp)) (+ 1.0 (* e sp))) (/ e 2.0))))
          old  phi
          phi  (- phi (/ (* (- psii psi) (cos phi) (- 1.0 (* e2 sp sp))) (- 1.0 e2)))
          it   (1+ it)))
  (list phi lam))

;; TK:GeoToCart - geodezice (lat lon h, radiani/metri) -> carteziene X,Y,Z
;; pe elipsoidul cu semiaxa mare A și excentricitatea pătrată E2
(defun TK:GeoToCart (phi lam h a e2 / nu)
  (setq nu (/ a (sqrt (- 1.0 (* e2 (sin phi) (sin phi))))))
  (list (* (+ nu h) (cos phi) (cos lam))
        (* (+ nu h) (cos phi) (sin lam))
        (* (+ (* nu (- 1.0 e2)) h) (sin phi))))

;; TK:CartToGeo - carteziene X,Y,Z -> (lat lon) în radiani (iterativ)
(defun TK:CartToGeo (xyz a e2 / x y z p phi nu h it)
  (setq x (car xyz) y (cadr xyz) z (caddr xyz)
        p (sqrt (+ (* x x) (* y y)))
        phi (atan z (* p (- 1.0 e2)))
        it 0)
  (repeat 10
    (setq nu  (/ a (sqrt (- 1.0 (* e2 (sin phi) (sin phi)))))
          h   (- (/ p (cos phi)) nu)
          phi (atan z (* p (- 1.0 (/ (* e2 nu) (+ nu h)))))))
  (list phi (atan y x)))

;; TK:Helmert - transformare Helmert 7 parametri S-42 -> WGS84
;; (convenția Coordinate Frame, rotații în secunde de arc, scara în ppm)
(defun TK:Helmert (xyz / x y z sa rx ry rz m)
  (setq x (car xyz) y (cadr xyz) z (caddr xyz)
        sa (/ pi 648000.0)                ; o secundă de arc în radiani
        rx (* 0.309 sa) ry (* -0.325 sa) rz (* -0.497 sa)
        m  (+ 1.0 (* 5.69 1e-6)))
  (list (+ 2.329    (* m (+ x (* rz y) (- (* ry z)))))
        (+ -147.042 (* m (+ (- (* rz x)) y (* rx z))))
        (+ -92.080  (* m (+ (* ry x) (- (* rx y)) z)))))

;;; --------------------------------------------------------------------------
;;;  Citirea grilei NTv2 (fișier binar, little-endian)
;;;  Structura: antet general (11 înregistrări x 16 octeți), antetul sub-grilei
;;;  (11 x 16 octeți), apoi nodurile: 4 valori float32 fiecare (deplasare
;;;  latitudine ["], deplasare longitudine ["], 2 precizii). Nodurile încep
;;;  din colțul sud-est și avansează spre vest, apoi rând cu rând spre nord.
;;;  În NTv2 longitudinea este pozitivă spre VEST.
;;; --------------------------------------------------------------------------

;; Numele fișierului grilă căutat automat
(setq *TK:GRIDNAME* "stereo70_etrs89A.gsb")

;; TK:BinOpen - deschide un fișier binar pentru citire (ADODB.Stream)
(defun TK:BinOpen (f / st)
  (if (setq st (vlax-create-object "ADODB.Stream"))
    (if (vl-catch-all-error-p
          (vl-catch-all-apply
            '(lambda ()
               (vlax-put-property st 'Type 1)          ; 1 = adTypeBinary
               (vlax-invoke-method st 'Open)
               (vlax-invoke-method st 'LoadFromFile f))))
      (progn (vlax-release-object st) nil)
      st)))

;; TK:BinRead - citește N octeți de la poziția POS; returnează lista lor
(defun TK:BinRead (st pos n)
  (vlax-put-property st 'Position pos)
  (vlax-safearray->list (vlax-variant-value (vlax-invoke-method st 'Read n))))

;; TK:BinClose - închide fluxul binar
(defun TK:BinClose (st)
  (vl-catch-all-apply 'vlax-invoke-method (list st 'Close))
  (vl-catch-all-apply 'vlax-release-object (list st)))

;; TK:F32 - decodează un număr float32 IEEE-754 din 4 octeți (little-endian)
(defun TK:F32 (b / ex m v)
  (setq ex (+ (* 2 (logand (nth 3 b) 127)) (/ (nth 2 b) 128))
        m  (+ (* 65536.0 (logand (nth 2 b) 127)) (* 256.0 (nth 1 b)) (nth 0 b))
        v  (if (= ex 0)
             (* m (expt 2.0 -149))
             (* (+ 1.0 (/ m 8388608.0)) (expt 2.0 (- ex 127)))))
  (if (>= (nth 3 b) 128) (- v) v))

;; TK:F64 - decodează un număr float64 IEEE-754 din 8 octeți (little-endian)
(defun TK:F64 (b / ex m v)
  (setq ex (+ (* 16 (logand (nth 7 b) 127)) (/ (nth 6 b) 16))
        m  (logand (nth 6 b) 15))
  (foreach k '(5 4 3 2 1 0) (setq m (+ (* m 256.0) (nth k b))))
  (setq v (if (= ex 0) 0.0 (* (+ 1.0 (/ m 4503599627370496.0)) (expt 2.0 (- ex 1023)))))
  (if (>= (nth 7 b) 128) (- v) v))

;; TK:I32 - întreg pozitiv pe 4 octeți (little-endian)
(defun TK:I32 (b)
  (+ (nth 0 b) (* 256 (nth 1 b)) (* 65536 (nth 2 b)) (* 16777216 (nth 3 b))))

;; TK:Sub - sublista de N elemente a listei L începând de la poziția I
(defun TK:Sub (l i n / r)
  (repeat n (setq r (cons (nth i l) r) i (1+ i)))
  (reverse r))

;; TK:GridFind - caută fișierul grilă: căile de suport AutoCAD, folderul
;; lui TopoKit.lsp și folderul desenului curent
(defun TK:GridFind (/ lsp f)
  (cond
    ((findfile *TK:GRIDNAME*))
    ((and (setq lsp (findfile "TopoKit.lsp"))
          (findfile (setq f (strcat (vl-filename-directory lsp) "\\" *TK:GRIDNAME*))))
     f)
    ((and (= 1 (getvar "DWGTITLED"))
          (findfile (setq f (strcat (getvar "DWGPREFIX") *TK:GRIDNAME*))))
     f)))

;; TK:GridOpen - deschide grila și citește antetele. Setează *TK:GRID* =
;; (flux sLat nLat eLong wLong pasLat pasLong nrColoane nrRânduri) sau nil.
(defun TK:GridOpen (/ f st h rec keys ncol nrow)
  (setq *TK:GRID* nil)
  (if (and (setq f (TK:GridFind)) (setq st (TK:BinOpen f)))
    (progn
      (setq h (TK:BinRead st 0 352))
      ;; tabel (cheie . octeții valorii) pentru cele 22 de înregistrări
      (setq rec 0)
      (repeat 22
        (setq keys (cons (cons (vl-string-trim " " (vl-list->string (TK:Sub h (* 16 rec) 8)))
                               (TK:Sub h (+ (* 16 rec) 8) 8))
                         keys)
              rec (1+ rec)))
      (if (and (assoc "GS_COUNT" keys) (assoc "LONG_INC" keys)
               (wcmatch (strcase (vl-list->string (cdr (assoc "GS_TYPE" keys)))) "SECONDS*"))
        (progn
          (setq *TK:GRID*
                 (mapcar '(lambda (k) (TK:F64 (cdr (assoc k keys))))
                         '("S_LAT" "N_LAT" "E_LONG" "W_LONG" "LAT_INC" "LONG_INC"))
                ncol (1+ (fix (+ 0.5 (/ (- (nth 3 *TK:GRID*) (nth 2 *TK:GRID*)) (nth 5 *TK:GRID*)))))
                nrow (1+ (fix (+ 0.5 (/ (- (nth 1 *TK:GRID*) (nth 0 *TK:GRID*)) (nth 4 *TK:GRID*))))))
          (if (= (* ncol nrow) (TK:I32 (cdr (assoc "GS_COUNT" keys))))
            (setq *TK:GRID* (append (list st) *TK:GRID* (list ncol nrow) (list f)))
            (setq *TK:GRID* nil))))
      (if (not *TK:GRID*) (TK:BinClose st))))
  *TK:GRID*)

;; TK:GridClose - închide fișierul grilă (dacă este deschis)
(defun TK:GridClose ()
  (if *TK:GRID* (TK:BinClose (car *TK:GRID*)))
  (setq *TK:GRID* nil))

;; TK:GridNode - deplasările (dLat dLon) ale nodurilor (col,rând) și
;; (col+1,rând), citite dintr-o singură operație (32 octeți consecutivi)
(defun TK:GridNodes (col row / g b)
  (setq g *TK:GRID*
        b (TK:BinRead (car g) (+ 352 (* 16 (+ col (* row (nth 7 g))))) 32))
  (list (list (TK:F32 (TK:Sub b 0 4)) (TK:F32 (TK:Sub b 4 4)))
        (list (TK:F32 (TK:Sub b 16 4)) (TK:F32 (TK:Sub b 20 4)))))

;; TK:GridShift - aplică grila punctului (lat lon) în radiani (Krasovsky).
;; Returnează (lat lon) ETRS89 în radiani sau nil dacă punctul este în afara
;; zonei acoperite (inclusiv celulele de margine cu noduri fără date).
(defun TK:GridShift (geo / g lat lonw x y col row fx fy r0 r1 nd dlat dlon)
  (if (setq g *TK:GRID*)
    (progn
      (setq lat  (* 648000.0 (/ (car geo) pi))          ; secunde de arc
            lonw (- (* 648000.0 (/ (cadr geo) pi)))     ; pozitiv spre vest
            x    (/ (- lonw (nth 3 g)) (nth 6 g))
            y    (/ (- lat (nth 1 g)) (nth 5 g)))
      (if (and (>= x 0.0) (>= y 0.0) (< x (1- (nth 7 g))) (< y (1- (nth 8 g))))
        (progn
          (setq col (fix x) row (fix y) fx (- x col) fy (- y row)
                r0 (TK:GridNodes col row)
                r1 (TK:GridNodes col (1+ row))
                nd (append r0 r1))
          ;; nodurile cu deplasare zero sunt în afara teritoriului acoperit
          (if (not (vl-some '(lambda (n) (and (= 0.0 (car n)) (= 0.0 (cadr n)))) nd))
            (progn
              (setq dlat (+ (* (- 1.0 fx) (- 1.0 fy) (car (nth 0 nd))) (* fx (- 1.0 fy) (car (nth 1 nd)))
                            (* (- 1.0 fx) fy (car (nth 2 nd))) (* fx fy (car (nth 3 nd))))
                    dlon (+ (* (- 1.0 fx) (- 1.0 fy) (cadr (nth 0 nd))) (* fx (- 1.0 fy) (cadr (nth 1 nd)))
                            (* (- 1.0 fx) fy (cadr (nth 2 nd))) (* fx fy (cadr (nth 3 nd)))))
              (list (* pi (/ (+ lat dlat) 648000.0))
                    (* pi (/ (- (+ lonw dlon)) 648000.0))))))))))

;; TK:MethodText - descrierea metodei de transformare folosite la ultimul export
(defun TK:MethodText ()
  (cond
    ((null *TK:GRID*) "Helmert 7 parametri EPSG:15994 (precizie ~0.3-1.5 m)")
    ((> (cond (*TK:NHELM*) (0)) 0)
     (strcat "grila NTv2 ANCPI (precizie centimetrica); " (itoa *TK:NHELM*)
             " puncte in afara grilei transformate cu Helmert (~1 m)"))
    (T "grila NTv2 ANCPI stereo70_etrs89A.gsb (precizie centimetrica)")))

;; TK:Stereo70ToWGS84 - conversia completă: (E N) Stereo 70 -> (lon lat)
;; ETRS89/WGS84 în grade zecimale. Folosește grila NTv2 dacă este deschisă
;; și acoperă punctul; altfel transformarea Helmert (contorizată în *TK:NHELM*).
(defun TK:Stereo70ToWGS84 (en / geo fk fw ll)
  (setq geo (TK:S70ToGeo en))
  (if (not (setq ll (TK:GridShift geo)))
    (setq fk  (/ 1.0 298.3)
          fw  (/ 1.0 298.257223563)
          ll  (TK:CartToGeo
                (TK:Helmert (TK:GeoToCart (car geo) (cadr geo) 0.0 6378245.0 (- (* 2.0 fk) (* fk fk))))
                6378137.0 (- (* 2.0 fw) (* fw fw)))
          *TK:NHELM* (1+ (cond (*TK:NHELM*) (0)))))
  (list (TK:Deg (cadr ll)) (TK:Deg (car ll))))

;; TK:PtEN - coordonatele Stereo 70 (E N) ale unui punct din desen,
;; ținând cont de opțiunea de inversare a axelor
(defun TK:PtEN (p)
  (if (= *TK:SWAPXY* "1") (list (cadr p) (car p)) (list (car p) (cadr p))))

;; TK:IsClosed - T dacă polilinia este închisă (flag sau capete coincidente)
(defun TK:IsClosed (e)
  (or (vlax-curve-isClosed e)
      (equal (TK:2d (vlax-curve-getStartPoint e)) (TK:2d (vlax-curve-getEndPoint e)) 1e-6)))

;; TK:SelClosedPoly - selecția unei polilinii închise (repetă până la succes)
(defun TK:SelClosedPoly (/ es e ok)
  (while (not ok)
    (setvar "ERRNO" 0)
    (setq es (entsel "\nSelectati polilinia inchisa (conturul parcelei): "))
    (cond
      ((and (null es) (= 7 (getvar "ERRNO"))) (princ "\nNimic selectat, incercati din nou."))
      ((null es) (setq ok T))
      ((not (wcmatch (cdr (assoc 0 (entget (car es)))) "LWPOLYLINE,POLYLINE"))
       (princ "\nObiectul selectat nu este o polilinie."))
      ((not (TK:IsClosed (car es))) (princ "\nPolilinia selectata nu este inchisa."))
      (T (setq ok T e (car es)))))
  e)

;; TK:DropDup - elimină punctele consecutive duplicate dintr-o listă
(defun TK:DropDup (pts / out)
  (foreach p pts
    (if (or (null out) (> (distance (TK:2d p) (TK:2d (car out))) 1e-6))
      (setq out (cons p out))))
  (reverse out))

;; TK:CurvePts - punctele conturului: (conturDensificat vertexuri).
;; Segmentele în arc sunt densificate (16 sub-segmente) pentru a fi redate
;; corect în Google Earth; vertex-urile reale sunt returnate separat.
(defun TK:CurvePts (e / ep i p0 p1 pm d0 d1 k cont vtx)
  (setq ep (fix (+ 0.5 (vlax-curve-getEndParam e))) i 0)
  (while (< i ep)
    (setq p0 (vlax-curve-getPointAtParam e (float i))
          p1 (vlax-curve-getPointAtParam e (float (1+ i)))
          pm (vlax-curve-getPointAtParam e (+ i 0.5))
          cont (cons p0 cont)
          vtx  (cons p0 vtx))
    (if (> (distance (TK:2d pm) (TK:2d (TK:Mid p0 p1))) 0.001)   ; segment în arc
      (progn
        (setq d0 (vlax-curve-getDistAtParam e (float i))
              d1 (vlax-curve-getDistAtParam e (float (1+ i)))
              k 1)
        (repeat 15
          (setq cont (cons (vlax-curve-getPointAtDist e (+ d0 (* (- d1 d0) (/ k 16.0)))) cont)
                k (1+ k)))))
    (setq i (1+ i)))
  (setq cont (TK:DropDup (reverse cont)) vtx (TK:DropDup (reverse vtx)))
  ;; ultimul punct nu trebuie să dubleze primul (conturul se închide în KML)
  (if (and (cdr vtx) (equal (TK:2d (car vtx)) (TK:2d (last vtx)) 1e-6)) (setq vtx (reverse (cdr (reverse vtx)))))
  (if (and (cdr cont) (equal (TK:2d (car cont)) (TK:2d (last cont)) 1e-6)) (setq cont (reverse (cdr (reverse cont)))))
  (list cont vtx))

;; TK:InStereo70 - T dacă toate punctele se încadrează în domeniul
;; aproximativ al sistemului Stereo 70 pe teritoriul României
(defun TK:InStereo70 (pts)
  (vl-every '(lambda (p)
               (and (< 100000.0 (car (TK:PtEN p)) 950000.0)
                    (< 150000.0 (cadr (TK:PtEN p)) 850000.0)))
            pts))

;; TK:OpenW - deschide un fișier pentru scriere în UTF-8 (AutoCAD 2021+),
;; iar pe versiunile vechi în codificarea ANSI a sistemului.
;; Setează *TK:ENC* cu numele codificării folosite în antetul XML.
(defun TK:OpenW (f / h)
  (setq h (vl-catch-all-apply 'open (list f "w" "utf8")))
  (if (or (vl-catch-all-error-p h) (null h))
    (setq h (open f "w")
          *TK:ENC* (TK:StrReplace (strcase (getvar "SYSCODEPAGE") T) "ansi_" "windows-"))
    (setq *TK:ENC* "UTF-8"))
  h)

;; TK:Coord - formatează un punct WGS84 ca "lon,lat,0" pentru KML
(defun TK:Coord (ll) (strcat (rtos (car ll) 2 9) "," (rtos (cadr ll) 2 9) ",0"))

;; TK:WriteKml - scrie fișierul KML: stil, poligonul parcelei, vedere
;; inițială (LookAt) și, opțional, punctele de contur numerotate.
(defun TK:WriteKml (file nm cont vtx area per / gc gv fh cen ext k en)
  (setq gc (mapcar '(lambda (p) (TK:Stereo70ToWGS84 (TK:PtEN p))) cont)
        gv (mapcar '(lambda (p) (TK:Stereo70ToWGS84 (TK:PtEN p))) vtx)
        cen (list (/ (apply '+ (mapcar 'car gv)) (length gv))
                  (/ (apply '+ (mapcar 'cadr gv)) (length gv)))
        ext (max 150.0 (* 2.5 (distance (list (apply 'min (mapcar 'car vtx)) (apply 'min (mapcar 'cadr vtx)))
                                        (list (apply 'max (mapcar 'car vtx)) (apply 'max (mapcar 'cadr vtx)))))))
  (if (setq fh (TK:OpenW file))
    (progn
      (setq *TK:FH* fh nm (TK:XmlEsc nm))
      (foreach l
        (list
          (strcat "<?xml version=\"1.0\" encoding=\"" *TK:ENC* "\"?>")
          "<kml xmlns=\"http://www.opengis.net/kml/2.2\">"
          "<Document>"
          (strcat "  <name>" nm "</name>")
          "  <open>1</open>"
          (strcat "  <LookAt><longitude>" (rtos (car cen) 2 9) "</longitude><latitude>" (rtos (cadr cen) 2 9)
                  "</latitude><altitude>0</altitude><heading>0</heading><tilt>0</tilt><range>"
                  (rtos ext 2 1) "</range></LookAt>")
          "  <Style id=\"tkParcela\">"
          "    <LineStyle><color>ff0000ff</color><width>2.5</width></LineStyle>"
          "    <PolyStyle><color>4000ffff</color></PolyStyle>"
          "  </Style>"
          "  <Style id=\"tkPunct\">"
          "    <IconStyle><scale>0.6</scale><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle>"
          "    <LabelStyle><scale>0.8</scale></LabelStyle>"
          "  </Style>"
          "  <Placemark>"
          (strcat "    <name>" nm "</name>")
          (strcat "    <description>Suprafata (Stereo 70): " (rtos area 2 2) " mp&#10;Perimetru: " (rtos per 2 2)
                  " m&#10;Numar puncte: " (itoa (length vtx)) "&#10;Desen sursa: " (TK:XmlEsc (getvar "DWGNAME"))
                  "&#10;Transformare Stereo 70 -&gt; ETRS89/WGS84: " (TK:MethodText) "</description>")
          "    <styleUrl>#tkParcela</styleUrl>"
          "    <Polygon>"
          "      <tessellate>1</tessellate>"
          "      <altitudeMode>clampToGround</altitudeMode>"
          "      <outerBoundaryIs><LinearRing><coordinates>")
        (write-line l fh))
      ;; coordonatele poligonului (închis prin repetarea primului punct)
      (foreach ll (append gc (list (car gc)))
        (write-line (strcat "        " (TK:Coord ll)) fh))
      (foreach l '("      </coordinates></LinearRing></outerBoundaryIs>" "    </Polygon>" "  </Placemark>")
        (write-line l fh))
      ;; punctele de contur (opțional)
      (if (= *TK:PUNCTE* "1")
        (progn
          (write-line "  <Folder><name>Puncte contur</name><open>0</open>" fh)
          (setq k 0)
          (foreach ll gv
            (setq en (TK:PtEN (nth k vtx)) k (1+ k))
            (write-line (strcat "    <Placemark><name>" (itoa k) "</name><description>X (N) = "
                                (rtos (cadr en) 2 3) " m&#10;Y (E) = " (rtos (car en) 2 3)
                                " m</description><styleUrl>#tkPunct</styleUrl><Point><coordinates>"
                                (TK:Coord ll) "</coordinates></Point></Placemark>")
                        fh))
          (write-line "  </Folder>" fh)))
      (write-line "</Document>" fh)
      (write-line "</kml>" fh)
      (close fh)
      (setq *TK:FH* nil)
      T)))

;; TK:PsQ - dublează apostroafele pentru un șir PowerShell între '...'
(defun TK:PsQ (s) (TK:StrReplace s "'" "''"))

;; TK:MakeKmz - arhivează KML-ul ca doc.kml într-un fișier KMZ (ZIP),
;; folosind PowerShell (Compress-Archive). Returnează T la succes.
(defun TK:MakeKmz (kml kmz / zip)
  (setq zip (strcat (vl-filename-directory kml) "\\doc.zip"))
  (if (findfile zip) (vl-file-delete zip))
  (TK:Run (strcat "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \"Compress-Archive -LiteralPath '"
                  (TK:PsQ kml) "' -DestinationPath '" (TK:PsQ zip) "' -Force\"")
          T)
  (if (findfile zip)
    (progn
      (if (findfile kmz) (vl-file-delete kmz))
      (vl-file-copy zip kmz)
      (vl-file-delete zip)
      (and (findfile kmz) T))))

;; TK:FindGE - calea către googleearth.exe (registru sau locații standard)
(defun TK:FindGE ()
  (vl-some
    '(lambda (p) (if (and p (/= p "")) (findfile (vl-string-trim "\" " p))))
    (list
      (vl-registry-read "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\googleearth.exe")
      (strcat (TK:EnvOr "ProgramFiles" "C:\\Program Files") "\\Google\\Google Earth Pro\\client\\googleearth.exe")
      (strcat (TK:EnvOr "ProgramFiles(x86)" "C:\\Program Files (x86)") "\\Google\\Google Earth Pro\\client\\googleearth.exe")
      "C:\\Program Files\\Google\\Google Earth Pro\\client\\googleearth.exe"
      "C:\\Program Files (x86)\\Google\\Google Earth Pro\\client\\googleearth.exe")))

;; TK:OpenGE - deschide fișierul în Google Earth Pro (dacă este instalat);
;; altfel încearcă aplicația asociată extensiei .kmz/.kml.
(defun TK:OpenGE (file / exe sh)
  (cond
    ((setq exe (TK:FindGE))
     (TK:Run (strcat "\"" exe "\" \"" file "\"") nil)
     (princ "\nFisierul a fost deschis in Google Earth Pro."))
    ((vl-registry-read (strcat "HKEY_CLASSES_ROOT\\" (vl-filename-extension file)))
     (if (setq sh (vlax-create-object "Shell.Application"))
       (progn
         (vl-catch-all-apply 'vlax-invoke-method (list sh 'ShellExecute file))
         (vlax-release-object sh)
         (princ "\nFisierul a fost deschis cu aplicatia asociata."))))
    (T (princ "\nGoogle Earth Pro nu a fost gasit; deschideti manual fisierul generat."))))

;; TK:OutDir - directorul de ieșire: folderul desenului curent (dacă este
;; salvat) sau C:\Temp (creat la nevoie); ca ultimă variantă %TEMP%.
(defun TK:OutDir (/ d)
  (setq d (if (= 1 (getvar "DWGTITLED")) (getvar "DWGPREFIX") "C:\\Temp\\"))
  (if (not (vl-file-directory-p d)) (vl-mkdir d))
  (if (vl-file-directory-p d) d (TK:TempDir)))

;; C:EXPKMZ - exportă o parcelă (polilinie închisă) în KMZ/KML pentru
;; Google Earth, cu transformarea Stereo 70 -> WGS84 inclusă.
(defun c:EXPKMZ (/ *error* e nm cv cont vtx area per dir file tmp kml ok)
  (defun *error* (msg) (TK:Error msg))
  (TK:Start)
  (if (setq e (TK:SelClosedPoly))
    (progn
      ;; numele parcelei (din dialog sau din linia de comandă)
      (if (not *TK:DLGRUN*)
        (progn
          (setq nm (vl-string-trim " " (getstring T (strcat "\nNumele parcelei <" *TK:NUME* ">: "))))
          (if (/= nm "") (setq *TK:NUME* nm))))
      (setq cv (TK:CurvePts e) cont (car cv) vtx (cadr cv)
            area (vlax-curve-getArea e)
            per  (vlax-curve-getDistAtParam e (vlax-curve-getEndParam e)))
      (cond
        ((< (length vtx) 3) (princ "\nPolilinia are mai putin de 3 vertex-uri distincte."))
        ((and (not (TK:InStereo70 vtx))
              (progn
                (initget "Da Nu")
                (/= "Da" (getkword "\nCoordonatele par in afara domeniului Stereo 70 (verificati axele). Continuati? [Da/Nu] <Nu>: "))))
         (princ "\nExport anulat."))
        (T
         ;; grila NTv2 pentru precizie centimetrică (altfel Helmert)
         (setq *TK:NHELM* 0)
         (if (and (= *TK:USEGRID* "1") (not (TK:GridOpen)))
           (princ (strcat "\nATENTIE: grila " *TK:GRIDNAME* " nu a fost gasita (copiati-o langa TopoKit.lsp)."
                          "\nSe foloseste transformarea Helmert, precizie ~0.3-1.5 m.")))
         (setq dir  (TK:OutDir)
               file (strcat dir (TK:SafeName (vl-filename-base (getvar "DWGNAME"))) "_"
                            (TK:SafeName *TK:NUME*) "_" (TK:Stamp)
                            (if (= *TK:KMZ* "1") ".kmz" ".kml")))
         (if (= *TK:KMZ* "1")
           ;; KMZ: KML-ul se scrie ca doc.kml într-un director temporar și se arhivează
           (progn
             (setq tmp (strcat (TK:TempDir) "TopoKit_kmz"))
             (vl-mkdir tmp)
             (setq kml (strcat tmp "\\doc.kml"))
             (if (TK:WriteKml kml *TK:NUME* cont vtx area per)
               (if (TK:MakeKmz kml file)
                 (setq ok T)
                 (progn
                   ;; arhivarea a eșuat: se păstrează fișierul KML
                   (setq file (strcat (substr file 1 (- (strlen file) 4)) ".kml"))
                   (if (findfile file) (vl-file-delete file))
                   (setq ok (vl-file-copy kml file))
                   (princ "\nArhivarea KMZ nu a reusit (PowerShell indisponibil); s-a salvat fisier KML.")))))
           (setq ok (TK:WriteKml file *TK:NUME* cont vtx area per)))
         (if ok
           (progn
             (princ (strcat "\nExport finalizat: " file
                            "\n" (itoa (length vtx)) " puncte, S = " (rtos area 2 2) " mp, P = " (rtos per 2 2) " m."
                            "\nTransformare: " (TK:MethodText)))
             (if (= *TK:OPENGE* "1") (TK:OpenGE file)))
           (princ (strcat "\nNu s-a putut scrie fisierul: " file)))
         (TK:GridClose)))))
  (TK:Stop)
  (princ))

;;; ==========================================================================
;;;  MODULUL 3 - INSERARE FORMAT, CADRU ȘI INDICATOR LA SCARĂ (INSCADRU)
;;; ==========================================================================
;;;  Dimensiunile formatului (mm) se înmulțesc cu factorul  f = scara / 1000
;;;  (desen în metri): ex. A3 landscape 420 x 297 mm la 1:500 -> 210 x 148.5 m.
;;;  Margini cadru interior: 20 mm stânga (îndosariere), 5 mm (A4, A3) sau
;;;  10 mm (A2, A1, A0) pe celelalte laturi. Indicatorul (180 x 50 mm) este un
;;;  bloc cu atribute (TK_CARTUS), inserat în colțul dreapta-jos al cadrului
;;;  interior, la factorul de scară f.
;;; ==========================================================================

;; TK:FormatWH - dimensiunile (lățime înălțime) în mm pentru formatul FM
;; (element din *TK:FORMATE*) și orientarea ORI ("P" sau "L")
(defun TK:FormatWH (fm ori)
  (if (= ori "P")
    (list (cadr fm) (caddr fm))
    (list (caddr fm) (cadr fm))))

;; TK:DefCartus - definește blocul indicatorului TK_CARTUS (unități: mm,
;; punct de bază = colțul dreapta-jos) dacă nu există deja în desen.
(defun TK:DefCartus ()
  (if (not (tblsearch "BLOCK" "TK_CARTUS"))
    (progn
      (TK:Style)
      (entmake '((0 . "BLOCK") (2 . "TK_CARTUS") (70 . 2) (10 0.0 0.0 0.0)))
      ;; chenarul și liniile tabelului
      (TK:Rect -180.0 0.0 0.0 50.0 "0" 50)
      (foreach y '(10.0 20.0 30.0 40.0) (TK:Line (list -180.0 y) (list 0.0 y) "0" 18))
      (TK:Line '(-145.0 20.0) '(-145.0 50.0) "0" 18)
      (TK:Line '(-80.0 0.0) '(-80.0 20.0) "0" 18)
      (TK:Line '(-40.0 0.0) '(-40.0 20.0) "0" 18)
      ;; etichete fixe
      (foreach x '(("BENEFICIAR"     (-178.0 43.8))
                   ("LUCRAREA"       (-178.0 33.8))
                   ("TITLUL PLANSEI" (-178.0 23.8))
                   ("EXECUTANT"      (-178.0 16.8))
                   ("SCARA"          (-78.0 16.8))
                   ("FORMAT"         (-38.0 16.8))
                   ("INTOCMIT"       (-178.0 6.8))
                   ("DATA"           (-78.0 6.8))
                   ("PLANSA NR."     (-38.0 6.8)))
        (TK:Text (car x) (cadr x) 2.0 0.0 "0"))
      ;; atribute (valori editabile cu EATTEDIT)
      (foreach x '(("BENEFICIAR" "Beneficiar"      (-143.0 43.2) 3.0)
                   ("LUCRARE"    "Lucrarea"        (-143.0 33.2) 3.0)
                   ("TITLU"      "Titlul plansei"  (-143.0 22.8) 3.5)
                   ("EXECUTANT"  "Executant"       (-178.0 11.8) 2.5)
                   ("SCARA"      "Scara"           (-78.0 11.8) 2.5)
                   ("FORMAT"     "Format"          (-38.0 11.8) 2.5)
                   ("INTOCMIT"   "Intocmit"        (-178.0 1.8) 2.5)
                   ("DATA"       "Data"            (-78.0 1.8) 2.5)
                   ("PLANSA"     "Plansa nr."      (-38.0 1.8) 2.5))
        (TK:AttDef (car x) (cadr x) "" (caddr x) (cadddr x)))
      (entmake '((0 . "ENDBLK")))))
  "TK_CARTUS")

;; TK:Caroiaj - desenează caroiajul de coordonate (cruci la 10 cm pe hârtie,
;; la valori rotunde), gradațiile pe cadrul interior și etichetele X/Y.
;; Zona indicatorului [cx1..x2] x [y1..cy2] este evitată.
(defun TK:Caroiaj (x1 y1 x2 y2 cx1 cy2 f / st arm mg th tk lay gx gy lx ly)
  (setq st (* 100.0 f) arm (* 5.0 f) mg (* 5.0 f) th (* 2.0 f) tk (* 3.0 f)
        lay *TK:LAYCADRU*
        lx (if (= *TK:SWAPXY* "1") "X=" "Y=")        ; eticheta coordonatei orizontale
        ly (if (= *TK:SWAPXY* "1") "Y=" "X="))       ; eticheta coordonatei verticale
  ;; linii verticale ale rețelei: gradații sus/jos + etichete jos
  (setq gx (* st (1+ (fix (/ (+ x1 mg) st)))))
  (while (< gx (- x2 mg))
    (TK:Line (list gx y2) (list gx (- y2 tk)) lay nil)
    (if (< gx (- cx1 mg))
      (progn
        (TK:Line (list gx y1) (list gx (+ y1 tk)) lay nil)
        (TK:Text (strcat lx (rtos gx 2 0)) (list (- gx (* 0.8 f)) (+ y1 (* 4.0 f))) th (/ pi 2.0) lay)))
    ;; crucile din interior
    (setq gy (* st (1+ (fix (/ (+ y1 mg) st)))))
    (while (< gy (- y2 mg))
      (if (not (and (> gx (- cx1 mg)) (< gy (+ cy2 mg))))
        (progn
          (TK:Line (list (- gx arm) gy) (list (+ gx arm) gy) lay nil)
          (TK:Line (list gx (- gy arm)) (list gx (+ gy arm)) lay nil)))
      (setq gy (+ gy st)))
    (setq gx (+ gx st)))
  ;; linii orizontale: gradații stânga/dreapta + etichete stânga
  (setq gy (* st (1+ (fix (/ (+ y1 mg) st)))))
  (while (< gy (- y2 mg))
    (TK:Line (list x1 gy) (list (+ x1 tk) gy) lay nil)
    (if (> gy (+ cy2 mg)) (TK:Line (list x2 gy) (list (- x2 tk) gy) lay nil))
    (TK:Text (strcat ly (rtos gy 2 0)) (list (+ x1 (* 4.0 f)) (+ gy (* 0.8 f))) th 0.0 lay)
    (setq gy (+ gy st))))

;; TK:SetAtts - completează atributele blocului BLK după etichetă (TAG)
(defun TK:SetAtts (blk vals / v)
  (foreach a (vlax-invoke blk 'GetAttributes)
    (if (setq v (cdr (assoc (strcase (vla-get-TagString a)) vals)))
      (vla-put-TextString a v))))

;; TK:DrawCadru - desenează formatul în punctul P (colț stânga-jos, WCS):
;; cadrul exterior, cadrul interior, indicatorul și opțional caroiajul.
(defun TK:DrawCadru (p / fm wh sc f w h ml mo x0 y0 x1 y1 x2 y2 blk lay)
  (setq fm  (nth *TK:FORMAT* *TK:FORMATE*)
        wh  (TK:FormatWH fm *TK:ORIENT*)
        sc  (nth *TK:SCARA* *TK:SCARI*)
        f   (/ sc 1000.0)
        w   (* f (car wh))
        h   (* f (cadr wh))
        ml  (* f 20.0)
        mo  (* f (if (member (car fm) '("A4" "A3")) 5.0 10.0))
        x0  (car p) y0 (cadr p)
        x1  (+ x0 ml) y1 (+ y0 mo)
        x2  (- (+ x0 w) mo) y2 (- (+ y0 h) mo)
        lay (TK:MakeLayer *TK:LAYCADRU* 7))
  ;; cadrul exterior (marginea foii) și cadrul interior (spațiul util)
  (TK:Rect x0 y0 (+ x0 w) (+ y0 h) lay 25)
  (TK:Rect x1 y1 x2 y2 lay 50)
  ;; indicatorul (bloc cu atribute) în colțul dreapta-jos al cadrului interior
  (setq blk (vla-InsertBlock
              (vla-get-ModelSpace *TK:DOC*)
              (vlax-3d-point (list x2 y1 0.0)) (TK:DefCartus) f f f 0.0))
  (vla-put-Layer blk lay)
  (TK:SetAtts blk
    (list (cons "BENEFICIAR" *TK:BENEF*)
          (cons "LUCRARE"    *TK:LUCRARE*)
          (cons "TITLU"      *TK:TITLU*)
          (cons "EXECUTANT"  *TK:EXEC*)
          (cons "SCARA"      (strcat "1:" (itoa sc)))
          (cons "FORMAT"     (strcat (car fm) (if (= *TK:ORIENT* "P") " Portrait" " Landscape")))
          (cons "INTOCMIT"   (cond ((getvar "LOGINNAME")) ("")))
          (cons "DATA"       (TK:Today))
          (cons "PLANSA"     *TK:PLANSA*)))
  ;; caroiajul de coordonate (opțional)
  (if (= *TK:CAROIAJ* "1")
    (TK:Caroiaj x1 y1 x2 y2 (- x2 (* 180.0 f)) (+ y1 (* 50.0 f)) f))
  (princ (strcat "\nFormat " (car fm) (if (= *TK:ORIENT* "P") " Portrait" " Landscape")
                 " la scara 1:" (itoa sc) " inserat pe stratul " lay ": "
                 (rtos w 2 2) " x " (rtos h 2 2) " m.")))

;; TK:InsCadru - rulează modulul de inserare. DLG = T afișează întâi
;; sub-dialogul de configurare (format, orientare, scară, indicator).
(defun TK:InsCadru (dlg / *error* p)
  (defun *error* (msg) (TK:Error msg))
  (if (or (not dlg) (TK:CadruDialog))
    (progn
      (TK:Start)
      (setvar "ATTREQ" 0)                      ; atributele se completează automat
      ;; elementele se desenează în Model Space
      (if (and (= 0 (getvar "TILEMODE")) (= 1 (getvar "CVPORT"))) (setvar "TILEMODE" 1))
      (if (setq p (getpoint "\nPunctul de insertie (coltul stanga-jos al formatului): "))
        (progn
          (setvar "OSMODE" 0)
          (TK:DrawCadru (trans p 1 0))))
      (TK:Stop)))
  (princ))

;; C:INSCADRU - comanda directă pentru inserarea formatului și cadrului
(defun c:INSCADRU () (TK:InsCadru T))

;;; ==========================================================================
;;;  INTERFAȚA GRAFICĂ (DCL)
;;; ==========================================================================

;; TK:DclLines - conținutul fișierului TopoKit.dcl, folosit pentru generarea
;; automată a dialogului când fișierul fizic nu este găsit.
;; (Secțiune generată din TopoKit.dcl cu tools/embed_dcl.py - nu editați manual.)
;;@@DCL-BEGIN@@
(defun TK:DclLines ()
  (list
    "// ==========================================================================="
    "//  TopoKit.dcl  -  Interfata grafica (DCL) pentru suita TopoKit (AutoLISP)"
    "//  Instrumente pentru topografie si cadastru:"
    "//    1. Corectie topologica (vertex-uri la intersectii de polilinii)"
    "//    2. Export parcela inchisa in KMZ/KML (Stereo 70 -> ETRS89/WGS84)"
    "//    3. Inserare format, cadru si indicator la scara (A4 - A0)"
    "//    4. Generatorul de anexe pentru Ordinul ANCPI nr. 600/2023"
    "//       (TopoKitAnexe.lsp: PAD, dezlipire/alipire, releveu, documente Word)"
    "//"
    "//  Imaginile (sigla, pictogramele si previzualizarea plansei) sunt desenate"
    "//  din TopoKit.lsp cu vector_image / fill_image."
    "//"
    "//  Fisierul este optional: daca nu este gasit in caile de suport AutoCAD,"
    "//  TopoKit.lsp genereaza automat o copie identica intr-un fisier temporar."
    "// ==========================================================================="
    ""
    "// ---- elemente reutilizabile -------------------------------------------------"
    "tk_icon : image {"
    "  width = 34;"
    "  height = 6.5;"
    "  fixed_width = true;"
    "  fixed_height = true;"
    "  alignment = centered;"
    "  color = -15;"
    "}"
    ""
    "tk_action : button {"
    "  height = 2.2;"
    "  fixed_height = true;"
    "  width = 30;"
    "  fixed_width = true;"
    "  alignment = centered;"
    "}"
    ""
    "tk_modul : boxed_column {"
    "  width = 42;"
    "  fixed_width = true;"
    "}"
    ""
    "// ---------------------------------------------------------------------------"
    "//  Dialogul principal (comenzile TOPOKIT / MYTOPO)"
    "// ---------------------------------------------------------------------------"
    "topokit_main : dialog {"
    "  label = \"TopoKit - Topografie & Cadastru\";"
    ""
    "  // ---------------- antet: sigla + titlu ----------------"
    "  : row {"
    "    : image { key = \"img_logo\"; width = 9; height = 3.6; fixed_width = true; fixed_height = true; color = -15; }"
    "    : column {"
    "      fixed_height = true;"
    "      : text { label = \"TopoKit  -  Instrumente pentru topografie si cadastru\"; }"
    "      : text { label = \"Stereo 70  >  ETRS89 / WGS84   |   Formate A4 - A0   |   Corectie topologica\"; }"
    "    }"
    "  }"
    "  : image { key = \"img_sep\"; height = 0.35; fixed_height = true; color = -15; }"
    ""
    "  : row {"
    "    // ---------------- 1. Corectie topologica ----------------"
    "    : tk_modul {"
    "      label = \" 1   Corectie Topologica \";"
    "      : tk_icon { key = \"img_topo\"; }"
    "      : paragraph {"
    "        : text_part { label = \"Adauga vertex-uri la intersectiile si\"; }"
    "        : text_part { label = \"contactele poliliniilor selectate.\"; }"
    "        : text_part { label = \"Cotele Z si arcele raman neschimbate.\"; }"
    "      }"
    "      : boxed_column {"
    "        label = \"Optiuni\";"
    "        : toggle { key = \"tg_contact\"; label = \"Puncte de contact (T, suprapuneri)\"; mnemonic = \"P\"; }"
    "        : edit_box { key = \"eb_tol\"; label = \"Toleranta [m]:\"; edit_width = 10; mnemonic = \"T\"; }"
    "        : spacer { height = 3.2; }"
    "      }"
    "      : spacer { height = 0.3; }"
    "      : tk_action { key = \"bt_addvtx\"; label = \"Corectie Topologica\"; mnemonic = \"C\"; }"
    "      : text { label = \"Comanda directa: ADDVTX\"; alignment = centered; }"
    "    }"
    ""
    "    // ---------------- 2. Export KMZ ----------------"
    "    : tk_modul {"
    "      label = \" 2   Export Google Earth \";"
    "      : tk_icon { key = \"img_kmz\"; }"
    "      : paragraph {"
    "        : text_part { label = \"Conturul parcelei (polilinie inchisa)\"; }"
    "        : text_part { label = \"in KMZ: Stereo 70 > ETRS89 / WGS84.\"; }"
    "        : text_part { key = \"tx_grid\"; label = \"\"; width = 38; }"
    "      }"
    "      : boxed_column {"
    "        label = \"Optiuni\";"
    "        : edit_box { key = \"eb_nume\"; label = \"Nume parcela:\"; edit_width = 17; mnemonic = \"N\"; }"
    "        : radio_row {"
    "          key = \"rr_kmz\";"
    "          : radio_button { key = \"rb_kmz\"; label = \"KMZ\"; }"
    "          : radio_button { key = \"rb_kml\"; label = \"KML\"; }"
    "        }"
    "        : toggle { key = \"tg_grid\";   label = \"Grila NTv2 ANCPI (precizie cm)\"; mnemonic = \"G\"; }"
    "        : toggle { key = \"tg_puncte\"; label = \"Exporta si punctele de contur\"; }"
    "        : toggle { key = \"tg_swap\";   label = \"Axe inversate (X desen = Nord)\"; }"
    "        : toggle { key = \"tg_ge\";     label = \"Deschide in Google Earth Pro\"; }"
    "      }"
    "      : spacer { height = 0.3; }"
    "      : tk_action { key = \"bt_kmz\"; label = \"Export KMZ\"; mnemonic = \"E\"; }"
    "      : text { label = \"Comanda directa: EXPKMZ\"; alignment = centered; }"
    "    }"
    ""
    "    // ---------------- 3. Format si cadru ----------------"
    "    : tk_modul {"
    "      label = \" 3   Format si Cadru \";"
    "      : tk_icon { key = \"img_cadru\"; }"
    "      : paragraph {"
    "        : text_part { key = \"tx_dim\"; label = \"\"; width = 38; }"
    "        : text_part { label = \"Cadru, spatiu util si indicator pe\"; }"
    "        : text_part { label = \"stratul L_CADRU, in Model Space.\"; }"
    "      }"
    "      : boxed_column {"
    "        label = \"Optiuni\";"
    "        : popup_list { key = \"pl_format\"; label = \"Format:\"; edit_width = 13; mnemonic = \"F\"; }"
    "        : radio_row {"
    "          key = \"rr_orient\";"
    "          : radio_button { key = \"rb_port\"; label = \"Portrait\"; }"
    "          : radio_button { key = \"rb_land\"; label = \"Landscape\"; }"
    "        }"
    "        : popup_list { key = \"pl_scara\"; label = \"Scara:\"; edit_width = 13; mnemonic = \"S\"; }"
    "        : toggle { key = \"tg_caroiaj\"; label = \"Caroiaj de coordonate (10 cm)\"; }"
    "        : spacer { height = 1.1; }"
    "      }"
    "      : spacer { height = 0.3; }"
    "      : tk_action { key = \"bt_cadru\"; label = \"Inserare Format si Cadru\"; mnemonic = \"I\"; }"
    "      : text { label = \"Comanda directa: INSCADRU\"; alignment = centered; }"
    "    }"
    "  }"
    ""
    "  // ---------------- 4. Anexe Ordinul ANCPI 600/2023 ----------------"
    "  : spacer { height = 0.3; }"
    "  : boxed_row {"
    "    label = \" 4   Anexe - Ordinul ANCPI nr. 600/2023 \";"
    "    : paragraph {"
    "      : text_part { label = \"Planuri in layout-uri: PAD (anexa 16), dezlipire / alipire (anexa 17), releveu (anexa 18).\"; }"
    "      : text_part { label = \"Documente Word completate: cereri, declaratie, memoriu tehnic, PV de vecinatate, foaia colectiva.\"; }"
    "      : text_part { key = \"tx_anexe\"; label = \"\"; width = 90; }"
    "    }"
    "    : column {"
    "      : tk_action { key = \"bt_anexe\"; label = \"Generator anexe...\"; mnemonic = \"A\"; }"
    "      : text { label = \"Comanda directa: ANEXE\"; alignment = centered; }"
    "    }"
    "  }"
    ""
    "  : spacer { height = 0.3; }"
    "  : boxed_row {"
    "    label = \"Stare\";"
    "    : text { key = \"tx_status\"; label = \"\"; width = 100; }"
    "  }"
    "  : row {"
    "    : text { label = \"Setarile sunt memorate pe durata sesiunii AutoCAD.\"; }"
    "    : button { key = \"bt_despre\"; label = \"Despre...\"; mnemonic = \"D\"; width = 13; fixed_width = true; }"
    "    : button { key = \"cancel\"; label = \"Inchide\"; width = 13; fixed_width = true; is_cancel = true; }"
    "  }"
    "  errtile;"
    "}"
    ""
    "// ---------------------------------------------------------------------------"
    "//  Sub-dialog dedicat comenzii INSCADRU (format, scara, indicator)"
    "// ---------------------------------------------------------------------------"
    "topokit_cadru : dialog {"
    "  label = \"TopoKit - Inserare Format, Cadru & Indicator\";"
    "  : row {"
    "    : column {"
    "      : boxed_column {"
    "        label = \"Previzualizare\";"
    "        : image { key = \"img_cadru\"; width = 34; height = 10; fixed_width = true; fixed_height = true; color = -15; alignment = centered; }"
    "        : text { key = \"tx_dim\"; label = \"\"; width = 34; alignment = centered; }"
    "      }"
    "      : boxed_column {"
    "        label = \"Format si scara\";"
    "        : popup_list { key = \"pl_format\"; label = \"Format pagina:\"; edit_width = 13; mnemonic = \"F\"; }"
    "        : radio_row {"
    "          key = \"rr_orient\";"
    "          : radio_button { key = \"rb_port\"; label = \"Portrait\"; }"
    "          : radio_button { key = \"rb_land\"; label = \"Landscape\"; }"
    "        }"
    "        : popup_list { key = \"pl_scara\"; label = \"Scara desenului:\"; edit_width = 13; mnemonic = \"S\"; }"
    "        : toggle { key = \"tg_caroiaj\"; label = \"Caroiaj de coordonate (10 cm)\"; }"
    "      }"
    "    }"
    "    : column {"
    "      : boxed_column {"
    "        label = \"Indicator (cartus)\";"
    "        : edit_box { key = \"eb_benef\";   label = \"Beneficiar:\";   edit_width = 32; mnemonic = \"B\"; }"
    "        : edit_box { key = \"eb_lucrare\"; label = \"Lucrarea:\";     edit_width = 32; mnemonic = \"L\"; }"
    "        : edit_box { key = \"eb_titlu\";   label = \"Titlu plansa:\"; edit_width = 32; mnemonic = \"T\"; }"
    "        : edit_box { key = \"eb_exec\";    label = \"Executant:\";    edit_width = 32; mnemonic = \"E\"; }"
    "        : edit_box { key = \"eb_plansa\";  label = \"Plansa nr.:\";   edit_width = 32; mnemonic = \"P\"; }"
    "        : spacer { height = 0.5; }"
    "        : paragraph {"
    "          : text_part { label = \"Scara, formatul, data si autorul se completeaza\"; }"
    "          : text_part { label = \"automat. Textele se pot modifica ulterior cu EATTEDIT.\"; }"
    "        }"
    "      }"
    "      : spacer { height = 0.5; }"
    "      : paragraph {"
    "        : text_part { label = \"Dupa OK indicati coltul stanga-jos al formatului\"; }"
    "        : text_part { label = \"in Model Space.\"; }"
    "      }"
    "    }"
    "  }"
    "  ok_cancel;"
    "  errtile;"
    "}"))
;;@@DCL-END@@

;; TK:DclPath - calea fișierului DCL: TopoKit.dcl din căile de suport sau
;; din folderul lui TopoKit.lsp; altfel îl generează într-un fișier temporar.
(defun TK:DclPath (/ f lsp fh)
  (cond
    ((findfile "TopoKit.dcl"))
    ((and (setq lsp (findfile "TopoKit.lsp"))
          (findfile (setq f (strcat (vl-filename-directory lsp) "\\TopoKit.dcl"))))
     f)
    ((and *TK:DCLTMP* (findfile *TK:DCLTMP*)) *TK:DCLTMP*)
    ((setq fh (open (setq f (vl-filename-mktemp "TopoKit" nil ".dcl")) "w"))
     (foreach l (TK:DclLines) (write-line l fh))
     (close fh)
     (setq *TK:DCLTMP* f))))

;;; --------------------------------------------------------------------------
;;;  Desen în dalele de tip "image" ale dialogului (sigla, pictograme,
;;;  previzualizarea planșei). Se lucrează într-un spațiu logic W x H cu axa
;;;  Y în sus, scalat uniform și centrat în dală. Culorile sunt indici ACI:
;;;  255 alb, 254..250 nuanțe de gri, 1 roșu, 3 verde, 5 albastru,
;;;  150/152 albastru-azuriu, 50 galben, -15 fundalul dialogului.
;;; --------------------------------------------------------------------------

;; TK:ImgBegin - începe desenarea în dala KEY, pentru spațiul logic W x H
(defun TK:ImgBegin (key w h / dx dy sc)
  (setq dx (dimx_tile key) dy (dimy_tile key)
        sc (min (/ (float dx) w) (/ (float dy) h))
        *TK:IMG* (list sc (/ (- dx (* sc w)) 2.0) (/ (- dy (* sc h)) 2.0) h))
  (start_image key)
  (fill_image 0 0 dx dy -15))

;; TK:ImgEnd - încheie desenarea în dala curentă
(defun TK:ImgEnd () (end_image))

;; TK:IX / TK:IY - coordonate logice -> pixeli (Y logic în sus, pixeli în jos)
(defun TK:IX (x) (fix (+ 0.5 (nth 1 *TK:IMG*) (* x (car *TK:IMG*)))))
(defun TK:IY (y) (fix (+ 0.5 (nth 2 *TK:IMG*) (* (- (nth 3 *TK:IMG*) y) (car *TK:IMG*)))))

;; TK:IPoly - polilinie prin punctele PTS (culoarea C); CLOSED o închide;
;; TH = grosimea în pixeli (1 sau 2)
(defun TK:IPoly (pts c closed th / q a b)
  (if closed (setq pts (append pts (list (car pts)))))
  (setq q (list (TK:IX (caar pts)) (TK:IY (cadar pts))))
  (foreach p (cdr pts)
    (setq a q b (list (TK:IX (car p)) (TK:IY (cadr p))))
    (vector_image (car a) (cadr a) (car b) (cadr b) c)
    (if (> th 1)
      (progn
        (vector_image (1+ (car a)) (cadr a) (1+ (car b)) (cadr b) c)
        (vector_image (car a) (1+ (cadr a)) (car b) (1+ (cadr b)) c)))
    (setq q b)))

;; TK:ILine - segment între (x1,y1) și (x2,y2)
(defun TK:ILine (x1 y1 x2 y2 c th) (TK:IPoly (list (list x1 y1) (list x2 y2)) c nil th))

;; TK:IRect - dreptunghi plin între colțurile (x1,y1) și (x2,y2)
(defun TK:IRect (x1 y1 x2 y2 c / px py)
  (setq px (TK:IX (min x1 x2)) py (TK:IY (max y1 y2)))
  (fill_image px py (max 1 (- (TK:IX (max x1 x2)) px)) (max 1 (- (TK:IY (min y1 y2)) py)) c))

;; TK:IBox - contur dreptunghiular
(defun TK:IBox (x1 y1 x2 y2 c th)
  (TK:IPoly (list (list x1 y1) (list x2 y1) (list x2 y2) (list x1 y2)) c T th))

;; TK:IDot - punct (pătrat plin de latură 2R+1 pixeli)
(defun TK:IDot (x y r c)
  (fill_image (- (TK:IX x) r) (- (TK:IY y) r) (1+ (* 2 r)) (1+ (* 2 r)) c))

;; TK:IEllipse - elipsă (sau cerc) cu centrul (cx,cy) și semiaxele RX, RY
(defun TK:IEllipse (cx cy rx ry c th / k pts)
  (setq k 0)
  (repeat 36
    (setq pts (cons (list (+ cx (* rx (cos (* k (/ pi 18.0))))) (+ cy (* ry (sin (* k (/ pi 18.0)))))) pts)
          k (1+ k)))
  (TK:IPoly pts c T th))

;; TK:ICard - "cartonaș" alb cu chenar gri, fundalul pictogramelor
(defun TK:ICard (w h)
  (TK:IRect 1 1 (- w 1) (- h 1) 255)
  (TK:IBox 1 1 (- w 1) (- h 1) 253 1))

;; TK:DrawLogo - sigla: teodolit pe trepied și o rețea de triangulație
(defun TK:DrawLogo (key)
  (TK:ImgBegin key 100 40)
  (TK:IRect 0 0 100 40 152)
  ;; trepied și instrument
  (TK:IPoly '((22 25) (12 4)) 255 nil 2)
  (TK:IPoly '((26 25) (26 4)) 255 nil 2)
  (TK:IPoly '((30 25) (40 4)) 255 nil 2)
  (TK:IRect 20 25 32 33 255)
  (TK:IRect 17 33 35 36 255)
  (TK:IDot 26 29 1 152)
  ;; rețea de triangulație
  (TK:IPoly '((52 9) (70 32) (90 13)) 50 T 2)
  (TK:IPoly '((70 32) (72 17) (52 9)) 50 nil 1)
  (TK:ILine 72 17 90 13 50 1)
  (foreach p '((52 9) (70 32) (90 13) (72 17)) (TK:IDot (car p) (cadr p) 2 255))
  (TK:ImgEnd))

;; TK:DrawSep - linie de separare colorată sub antet
(defun TK:DrawSep (key)
  (TK:ImgBegin key 100 2)
  (fill_image 0 0 (dimx_tile key) (dimy_tile key) -15)
  (fill_image 0 (/ (dimy_tile key) 2) (dimx_tile key) 2 152)
  (TK:ImgEnd))

;; TK:DrawTopoIcon - două polilinii care se intersectează; vertex-urile noi
;; (calculate chiar cu TK:IntLL) sunt marcate cu verde
(defun TK:DrawTopoIcon (key / a b *TK:TOL* ins)
  (setq *TK:TOL* 0.001
        a '((14.0 12.0) (52.0 48.0) (92.0 18.0) (146.0 46.0))
        b '((12.0 40.0) (60.0 12.0) (108.0 46.0) (148.0 14.0)))
  (TK:ImgBegin key 160 60)
  (TK:ICard 160 60)
  (TK:IPoly a 5 nil 2)
  (TK:IPoly b 1 nil 2)
  (mapcar '(lambda (p1 p2)
             (mapcar '(lambda (q1 q2) (setq ins (append ins (TK:IntLL p1 p2 q1 q2)))) b (cdr b)))
          a (cdr a))
  (foreach p (append a b) (TK:IDot (car p) (cadr p) 2 251))
  (foreach p ins (TK:IDot (car p) (cadr p) 4 255) (TK:IDot (car p) (cadr p) 3 3))
  (TK:ImgEnd))

;; TK:DrawKmzIcon - planul Stereo 70 cu parcela, săgeată și globul pământesc
(defun TK:DrawKmzIcon (key / x)
  (TK:ImgBegin key 160 60)
  (TK:ICard 160 60)
  ;; planul cu rețea de coordonate și parcela
  (TK:IRect 8 8 56 52 255)
  (setq x 8)
  (repeat 5 (TK:ILine x 8 x 52 254 1) (TK:ILine 8 (+ 8 (- x 8)) 56 (+ 8 (- x 8)) 254 1) (setq x (+ x 11)))
  (TK:IBox 8 8 56 52 252 1)
  (TK:IPoly '((17 15) (45 19) (49 41) (30 46) (20 36)) 1 T 2)
  ;; săgeata de transformare
  (TK:ILine 64 30 90 30 152 2)
  (TK:IPoly '((84 36) (91 30) (84 24)) 152 nil 2)
  ;; globul: contur, meridiane și paralele
  (TK:IEllipse 124 30 24 24 150 2)
  (TK:IEllipse 124 30 13 24 150 1)
  (TK:ILine 124 6 124 54 150 1)
  (TK:ILine 100 30 148 30 150 1)
  (TK:ILine 104 42 144 42 150 1)
  (TK:ILine 104 18 144 18 150 1)
  ;; parcela și reperul pe glob
  (TK:IPoly '((116 34) (126 36) (127 44) (118 45)) 1 T 2)
  (TK:IEllipse 136 49 4 4 1 2)
  (TK:ILine 136 45 136 38 1 2)
  (TK:ImgEnd))

;; TK:DrawSheet - previzualizarea planșei în dala KEY: foaia la proporția
;; formatului, cadrul interior, indicatorul și (opțional) caroiajul
(defun TK:DrawSheet (key fm ori grd / wh w h m mo x1 y1 x2 y2 gx gy ar)
  (setq wh (TK:FormatWH fm ori) w (car wh) h (cadr wh)
        m  (* 0.07 (max w h))
        mo (if (member (car fm) '("A4" "A3")) 5.0 10.0)
        ar (* 0.018 (max w h)))                       ; brațul crucilor, proporțional
  (TK:ImgBegin key (+ w m m) (+ h m m))
  ;; umbră și foaie
  (TK:IRect (+ m (* 0.02 w)) (- m (* 0.02 w)) (+ m w (* 0.02 w)) (- (+ m h) (* 0.02 w)) 252)
  (TK:IRect m m (+ m w) (+ m h) 255)
  (TK:IBox m m (+ m w) (+ m h) 251 1)
  ;; cadrul interior
  (setq x1 (+ m 20.0) y1 (+ m mo) x2 (- (+ m w) mo) y2 (- (+ m h) mo))
  ;; caroiaj (cruci la 100 mm pe hârtie), în afara indicatorului
  (if (= grd "1")
    (progn
      (setq gx (+ x1 50.0))
      (while (< gx x2)
        (setq gy (+ y1 50.0))
        (while (< gy y2)
          (if (not (and (> gx (- x2 185.0)) (< gy (+ y1 55.0))))
            (progn (TK:ILine (- gx ar) gy (+ gx ar) gy 150 1) (TK:ILine gx (- gy ar) gx (+ gy ar) 150 1)))
          (setq gy (+ gy 100.0)))
        (setq gx (+ gx 100.0)))))
  (TK:IBox x1 y1 x2 y2 250 2)
  ;; indicatorul (180 x 50 mm) în colțul dreapta-jos
  (TK:IRect (- x2 180.0) y1 x2 (+ y1 50.0) 254)
  (foreach d '(10.0 20.0 30.0 40.0) (TK:ILine (- x2 180.0) (+ y1 d) x2 (+ y1 d) 252 1))
  (TK:ILine (- x2 145.0) (+ y1 20.0) (- x2 145.0) (+ y1 50.0) 252 1)
  (TK:ILine (- x2 80.0) y1 (- x2 80.0) (+ y1 20.0) 252 1)
  (TK:ILine (- x2 40.0) y1 (- x2 40.0) (+ y1 20.0) 252 1)
  (TK:IBox (- x2 180.0) y1 x2 (+ y1 50.0) 250 1)
  (TK:ImgEnd))

;; TK:UpdStatus - bara de stare a dialogului principal
(defun TK:UpdStatus (/ fm sc)
  (if *TK:DLGMAIN*
    (progn
      (setq fm (nth (atoi (get_tile "pl_format")) *TK:FORMATE*)
            sc (nth (atoi (get_tile "pl_scara")) *TK:SCARI*))
      (set_tile "tx_status"
        (strcat "Toleranta: " (get_tile "eb_tol") " m     |     Transformare: "
                (cond ((/= (get_tile "tg_grid") "1") "Helmert 7p (~0.3-1.5 m)")
                      ((TK:GridFind) "grila NTv2 ANCPI (~1 cm)")
                      (T "grila LIPSA -> Helmert 7p (~0.3-1.5 m)"))
                "     |     Plansa: " (car fm) (if (= (get_tile "rr_orient") "rb_port") " Portrait" " Landscape")
                " 1:" (itoa sc))))))

;; TK:UpdDim - actualizează dimensiunile formatului, previzualizarea
;; planșei și bara de stare după orice modificare a opțiunilor de format
(defun TK:UpdDim (/ fm sc wh f ori)
  (setq fm  (nth (atoi (get_tile "pl_format")) *TK:FORMATE*)
        sc  (nth (atoi (get_tile "pl_scara")) *TK:SCARI*)
        ori (if (= (get_tile "rr_orient") "rb_port") "P" "L")
        wh  (TK:FormatWH fm ori)
        f   (/ sc 1000.0))
  (set_tile "tx_dim" (strcat (car fm) ": " (rtos (car wh) 2 0) "x" (rtos (cadr wh) 2 0) " mm = "
                             (rtos (* f (car wh)) 2 2) " x " (rtos (* f (cadr wh)) 2 2) " m"))
  (TK:DrawSheet "img_cadru" fm ori (get_tile "tg_caroiaj"))
  (TK:UpdStatus))

;; TK:InitCadruTiles - inițializează controalele comune de format/scară
(defun TK:InitCadruTiles ()
  (start_list "pl_format")
  (foreach x *TK:FORMATE* (add_list (strcat (car x) "  (" (rtos (cadr x) 2 0) " x " (rtos (caddr x) 2 0) " mm)")))
  (end_list)
  (start_list "pl_scara")
  (foreach s *TK:SCARI* (add_list (strcat "1:" (itoa s))))
  (end_list)
  (set_tile "pl_format" (itoa *TK:FORMAT*))
  (set_tile "pl_scara" (itoa *TK:SCARA*))
  (set_tile "rr_orient" (if (= *TK:ORIENT* "P") "rb_port" "rb_land"))
  (set_tile "tg_caroiaj" *TK:CAROIAJ*)
  (foreach k '("pl_format" "pl_scara" "rb_port" "rb_land" "tg_caroiaj") (action_tile k "(TK:UpdDim)"))
  (TK:UpdDim))

;; TK:ReadCadruTiles - citește controalele comune de format/scară
(defun TK:ReadCadruTiles ()
  (setq *TK:FORMAT*  (atoi (get_tile "pl_format"))
        *TK:SCARA*   (atoi (get_tile "pl_scara"))
        *TK:ORIENT*  (if (= (get_tile "rr_orient") "rb_port") "P" "L")
        *TK:CAROIAJ* (get_tile "tg_caroiaj")))

;; TK:MainSave - validează și memorează setările dialogului principal.
;; Returnează T dacă datele sunt corecte (dialogul se poate închide).
(defun TK:MainSave (/ tol nm)
  (setq tol (distof (TK:StrReplace (vl-string-trim " " (get_tile "eb_tol")) "," ".") 2)
        nm  (vl-string-trim " " (get_tile "eb_nume")))
  (cond
    ((or (null tol) (<= tol 0.0))
     (set_tile "error" "Toleranta trebuie sa fie un numar pozitiv (ex. 0.001).")
     (mode_tile "eb_tol" 2)
     nil)
    ((= nm "")
     (set_tile "error" "Introduceti numele parcelei.")
     (mode_tile "eb_nume" 2)
     nil)
    (T
     (setq *TK:TOL*     tol
           *TK:CONTACT* (get_tile "tg_contact")
           *TK:NUME*    nm
           *TK:KMZ*     (if (= (get_tile "rr_kmz") "rb_kml") "0" "1")
           *TK:PUNCTE*  (get_tile "tg_puncte")
           *TK:SWAPXY*  (get_tile "tg_swap")
           *TK:OPENGE*  (get_tile "tg_ge")
           *TK:USEGRID* (get_tile "tg_grid"))
     (TK:ReadCadruTiles)
     T)))

;; TK:About - fereastra "Despre"
(defun TK:About ()
  (alert (strcat "TopoKit - instrumente AutoLISP pentru topografie si cadastru\n\n"
                 "TOPOKIT / MYTOPO - meniul principal\n"
                 "ADDVTX   - vertex-uri la intersectiile poliliniilor\n"
                 "EXPKMZ   - export parcela in KMZ (Stereo 70 -> WGS84)\n"
                 "INSCADRU - format A4..A0, cadru si indicator la scara\n\n"
                 "Unitati desen: metri. X desen = Est, Y desen = Nord (implicit).\n"
                 "Transformare: stereografica oblica Krasovsky + grila NTv2\n"
                 "ANCPI stereo70_etrs89A.gsb (precizie centimetrica);\n"
                 "fara grila: Helmert 7 parametri (~0.3-1.5 m).")))

;; Corespondența dintre controalele dialogului și câmpurile indicatorului
(setq *TK:CARTUSKEYS* '(("eb_benef" . *TK:BENEF*) ("eb_lucrare" . *TK:LUCRARE*)
                        ("eb_titlu" . *TK:TITLU*) ("eb_exec" . *TK:EXEC*)
                        ("eb_plansa" . *TK:PLANSA*)))

;; TK:ReadCartusTiles - memorează textele indicatorului introduse în dialog
(defun TK:ReadCartusTiles ()
  (foreach x *TK:CARTUSKEYS* (set (cdr x) (get_tile (car x)))))

;; TK:CadruDialog - afișează sub-dialogul INSCADRU; returnează T la OK
(defun TK:CadruDialog (/ id res)
  (setq id (load_dialog (TK:DclPath)))
  (cond
    ((< id 0) (alert "Nu s-a putut incarca fisierul TopoKit.dcl.") nil)
    ((not (new_dialog "topokit_cadru" id)) (unload_dialog id) (alert "Dialogul topokit_cadru lipseste.") nil)
    (T
     (TK:InitCadruTiles)
     (foreach x *TK:CARTUSKEYS* (set_tile (car x) (eval (cdr x))))
     (action_tile "accept" "(TK:ReadCadruTiles) (TK:ReadCartusTiles) (done_dialog 1)")
     (action_tile "cancel" "(done_dialog 0)")
     (setq res (start_dialog))
     (unload_dialog id)
     (= res 1))))

;; C:TOPOKIT - meniul principal (GUI) cu cele trei module
(defun c:TOPOKIT (/ id res)
  (setq id (load_dialog (TK:DclPath)))
  (cond
    ((< id 0) (alert "Nu s-a putut incarca fisierul TopoKit.dcl."))
    ((not (new_dialog "topokit_main" id)) (unload_dialog id) (alert "Dialogul topokit_main lipseste."))
    (T
     ;; modulul 1
     (set_tile "tg_contact" *TK:CONTACT*)
     (set_tile "eb_tol" (rtos *TK:TOL* 2 4))
     ;; modulul 2
     (set_tile "eb_nume" *TK:NUME*)
     (set_tile "rr_kmz" (if (= *TK:KMZ* "1") "rb_kmz" "rb_kml"))
     (set_tile "tg_puncte" *TK:PUNCTE*)
     (set_tile "tg_swap" *TK:SWAPXY*)
     (set_tile "tg_ge" *TK:OPENGE*)
     (set_tile "tg_grid" *TK:USEGRID*)
     (set_tile "tx_grid" (if (TK:GridFind) "Grila NTv2 gasita: precizie ~1 cm" "Grila NTv2 lipsa: precizie ~1 m"))
     ;; imagini
     (TK:DrawLogo "img_logo")
     (TK:DrawSep "img_sep")
     (TK:DrawTopoIcon "img_topo")
     (TK:DrawKmzIcon "img_kmz")
     ;; modulul 3 (inclusiv previzualizarea planșei) și bara de stare
     (setq *TK:DLGMAIN* T)
     (TK:InitCadruTiles)
     (foreach k '("eb_tol" "tg_grid") (action_tile k "(TK:UpdStatus)"))
     ;; butoane
     (action_tile "bt_addvtx" "(if (TK:MainSave) (done_dialog 1))")
     (action_tile "bt_kmz"    "(if (TK:MainSave) (done_dialog 2))")
     (action_tile "bt_cadru"  "(if (TK:MainSave) (done_dialog 3))")
     (action_tile "bt_anexe"  "(if (TK:MainSave) (done_dialog 4))")
     (set_tile "tx_anexe" (if TKA:Generate "Generatorul de anexe este incarcat (TopoKitAnexe.lsp)."
                            "TopoKitAnexe.lsp nu este incarcat (APPLOAD sau calea de suport)."))
     (action_tile "bt_despre" "(TK:About)")
     (action_tile "cancel"    "(done_dialog 0)")
     (setq res (start_dialog) *TK:DLGMAIN* nil)
     (unload_dialog id)
     ;; modulul ales rulează după închiderea dialogului (necesită selecții în desen)
     (setq *TK:DLGRUN* T)
     (cond
       ((= res 1) (c:ADDVTX))
       ((= res 2) (c:EXPKMZ))
       ((= res 3) (TK:InsCadru nil))
       ((= res 4) (if TKA:Generate
                    (c:ANEXE)
                    (alert (strcat "Generatorul de anexe (TopoKitAnexe.lsp) nu este incarcat.\n"
                                   "Copiati TopoKitAnexe.lsp, TopoKitAnexe.dcl si folderul \"anexe\" langa TopoKit.lsp,\n"
                                   "in calea de suport AutoCAD, sau incarcati-l cu APPLOAD.")))))
     (setq *TK:DLGRUN* nil)))
  (princ))

;; C:MYTOPO - alias pentru meniul principal
(defun c:MYTOPO () (c:TOPOKIT))

(princ "\nTopoKit incarcat. Comenzi: TOPOKIT (MYTOPO), ADDVTX, EXPKMZ, INSCADRU.")

;; Generatorul de anexe (Ordinul ANCPI 600/2023) se încarcă automat dacă
;; TopoKitAnexe.lsp se află în calea de suport (sau lângă TopoKit.lsp)
(if (and (not *TKA:LOADING*) (not TKA:Generate) (findfile "TopoKitAnexe.lsp"))
  (load (findfile "TopoKitAnexe.lsp")))
(princ)
