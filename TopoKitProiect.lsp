;;; ==========================================================================
;;;  TopoKitProiect.lsp  -  Pregatire proiect nou, scara planului, caroiaj
;;; ==========================================================================
;;;
;;;  Comenzi:
;;;    TKPROIECT  - pregateste un desen nou dupa standardul de plan:
;;;                 sterge straturile goale (cele implicite din Civil 3D; cele cu obiecte raman),
;;;                 creeaza straturile standard, Arial in toate stilurile de text,
;;;                 unitati in metri si unghiuri (grade centesimale / sexagesimale),
;;;                 puncte AutoCAD (PTYPE: cerculet de 1 mm la scara), scara planului;
;;;                 in Civil 3D: stilul de punct "Basic" (AutoCAD POINT, alb), eticheta
;;;                 "Point Description" (Arial, alba, fara leader cand e mutata),
;;;                 setarile de distanta / unghi / directie si stilurile de caroiaj
;;;    TKSCARA    - aduce desenul la alta scara (1:50 ... 1:5000): scara de adnotare
;;;                 (etichetele Civil 3D), tipurile de linie, punctele si textele de
;;;                 pe straturile standard
;;;    TKCAROIAJ  - caroiaj de coordonate: la colturi eticheta N= / E= cu linii in L,
;;;                 in interior cruciulite la distanta din standard (25 m la 1:500).
;;;                 In Civil 3D sunt General Note Label-uri: cand muti eticheta,
;;;                 coordonatele se actualizeaza singure; stilurile se pot modifica
;;;                 din Toolspace (Settings > General > Label Styles > Note).
;;;
;;;  Marimile sunt in mm pe hartie (ca in standard: text 1.5 mm = 0.75 m la 1:500).
;;;  Mesajele sunt fara diacritice (AutoCAD citeste .lsp ca ANSI cu LISPSYS=0).
;;;  Necesita TopoKit.lsp.
;;; ==========================================================================

(vl-load-com)
(setq *TKP:LOADING* T)
(if (and (not TK:Start) (findfile "TopoKit.lsp")) (load (findfile "TopoKit.lsp")))

;; Scarile din standard si distanta dintre cruciulitele caroiajului (m)
(setq *TKP:SCARI* '(50 100 200 500 1000 2000 5000))
(setq *TKP:PAS* '((50 . 2.0) (100 . 5.0) (200 . 10.0) (500 . 25.0) (1000 . 50.0) (2000 . 100.0) (5000 . 250.0)))

;; Marimi in mm pe hartie
(setq *TKP:TXT* 1.5       ; textele (puncte, terenuri, vecinatati, cote, constructii, caroiaj)
      *TKP:PCT* 1.0       ; cerculetul punctului
      *TKP:LIN* 13.0      ; liniile in L de la colturile caroiajului
      *TKP:CRUCE* 2.5)    ; bratul cruciulitei

;; Straturile standard: (nume culoare grosime [stins])
;; grosimea: 0 = 0.00 mm, 40 = 0.40 mm, -3 = implicita
(setq *TKP:LAYERS*
  '(("Puncte" 7 0) ("Puncte Leica" 7 0) ("Puncte South" 7 0) ("Puncte Trimble" 7 0)
    ("Puncte noi" 7 0) ("Puncte interpolate" 7 0)
    ("Ascuns - puncte Leica" 7 0 T) ("Ascuns - puncte South" 7 0 T) ("Ascuns - puncte Trimble" 7 0 T)
    ("Terenuri" 6 40) ("Vecin\\U+0103t\\U+0103\\U+021Bi" 3 -3) ("Dimensiuni" 7 -3)
    ("Construc\\U+021Bii" 5 0) ("Caroiaj" 8 0) ("PAD" 7 -3)))

;; Straturile ale caror texte se scaleaza cu TKSCARA (wcmatch)
(setq *TKP:LAYTXT* "PUNCTE*,ASCUNS*,TERENURI,VECIN*,DIMENSIUNI,CONSTRUC*,CAROIAJ,PAD")

;; Stilurile Civil 3D create de TopoKit
(setq *TKP:STPCT* "Basic" *TKP:STLBL* "Point Description" *TKP:STCRUCE* "Caroiaj - cruciulita")
(setq *TKP:STCOLT* '(("SS" . "Caroiaj - colt stanga sus") ("SD" . "Caroiaj - colt dreapta sus")
                     ("JS" . "Caroiaj - colt stanga jos") ("JD" . "Caroiaj - colt dreapta jos")))
;; Formatul coordonatelor (ca in stilurile de caroiaj existente: metri, fara zecimale)
(setq *TKP:FN* "<[Northing(Um|P0|RN|AP|GC|UN|Sn|OF)]>"
      *TKP:FE* "<[Easting(Um|P0|RN|AP|GC|UN|Sn|OF)]>")

;;; ==========================================================================
;;;  UTILITARE
;;; ==========================================================================

(defun TKP:Msg (s) (princ (strcat "\n" s)))

;; TKP:Hex - valoarea unui numar hexazecimal ("0103" -> 259)
(defun TKP:Hex (s / v c)
  (setq v 0)
  (foreach c (vl-string->list (strcase s))
    (setq v (+ (* v 16) (if (> c 64) (- c 55) (- c 48)))))
  v)

;; TKP:Uni - numele cu diacritice: \U+XXXX devine caracterul Unicode cand AutoCAD
;; lucreaza in Unicode (LISPSYS 1/2); altfel AutoCAD converteste singur secventa
(defun TKP:Uni (s / i)
  (if (and (getvar "LISPSYS") (>= (getvar "LISPSYS") 1))
    (while (setq i (vl-string-search "\\U+" s))
      (setq s (strcat (substr s 1 i) (chr (TKP:Hex (substr s (+ i 4) 4))) (substr s (+ i 8))))))
  s)

;; TKP:Num - numar fara zerouri inutile
(defun TKP:Num (v / r)
  (setq r (rtos v 2 4))
  (if (vl-string-search "." r) (setq r (vl-string-right-trim "." (vl-string-right-trim "0" r))))
  r)

;; Setarile proiectului (pastrate in desen): ((SCARA . 500) (UNGHI . "G") ...)
(setq *TKP:DEF* '(("SCARA" . 500) ("UNGHI" . "G") ("STERG" . "1") ("STRAT" . "1") ("FONT" . "1") ("C3D" . "1")))

(defun TKP:Cfg (/ r)
  (setq r (vlax-ldata-get "TOPOKIT" "PROIECT"))
  (setq r (if (= 'STR (type r)) (vl-catch-all-apply 'read (list r))))
  (mapcar '(lambda (d / p) (if (and (listp r) (setq p (assoc (car d) r)) (= (type (cdr p)) (type (cdr d)))) p d))
          *TKP:DEF*))

(defun TKP:SaveCfg (cfg) (vlax-ldata-put "TOPOKIT" "PROIECT" (vl-prin1-to-string cfg)))
(defun TKP:Get (k) (cdr (assoc k (TKP:Cfg))))
(defun TKP:Put (k v / c)
  (setq c (TKP:Cfg))
  (TKP:SaveCfg (subst (cons k v) (assoc k c) c)))

;; TKP:Scara - scara curenta a planului (din setarile proiectului)
(defun TKP:Scara () (TKP:Get "SCARA"))
;; TKP:K - metri in desen pentru 1 mm pe hartie
(defun TKP:K (sc) (/ sc 1000.0))

;;; ==========================================================================
;;;  STRATURI, FONT, UNITATI, PUNCTE, SCARA
;;; ==========================================================================

(defun TKP:LayerNames () (mapcar '(lambda (l) (strcase (TKP:Uni (car l)))) *TKP:LAYERS*))

;; TKP:Layers - creeaza straturile standard (sau le aduce la culoarea / grosimea din standard)
(defun TKP:Layers (/ n name d)
  (setq n 0)
  (foreach l *TKP:LAYERS*
    (setq name (TKP:Uni (car l)))
    (if (setq d (tblsearch "LAYER" name))
      (if (setq d (vl-catch-all-apply 'entget (list (tblobjname "LAYER" name))))
        (if (not (vl-catch-all-error-p d))
          (entmod (TKP:Subst 370 (caddr l) (TKP:Subst 62 (if (cadddr l) (- (cadr l)) (cadr l)) d)))))
      (progn
        (entmake (list '(0 . "LAYER") '(100 . "AcDbSymbolTableRecord") '(100 . "AcDbLayerTableRecord")
                       (cons 2 name) '(70 . 0) (cons 62 (if (cadddr l) (- (cadr l)) (cadr l)))
                       '(6 . "Continuous") (cons 370 (caddr l))))
        (setq n (1+ n)))))
  ;; linia intrerupta pentru parcele (DASHED din acad.lin: 0.5 m la 1:500)
  (if (and (not (tblsearch "LTYPE" "DASHED")) (findfile "acad.lin"))
    (vl-catch-all-apply 'vla-load (list (vla-get-linetypes (vla-get-activedocument (vlax-get-acad-object)))
                                        "DASHED" (findfile "acad.lin"))))
  n)

(defun TKP:Subst (code v d)
  (if (assoc code d) (subst (cons code v) (assoc code d) d) (append d (list (cons code v)))))

;; TKP:UsedLayers - straturile pe care exista obiecte: in model, in layout-uri, in
;; definitiile blocurilor si atributele blocurilor (nume cu majuscule)
(defun TKP:UsedLayers (/ used add)
  (defun add (o / l)
    (if (and (not (vl-catch-all-error-p (setq l (vl-catch-all-apply 'vla-get-layer (list o)))))
             (not (member (strcase l) used)))
      (setq used (cons (strcase l) used))))
  (vlax-for b (vla-get-blocks (vla-get-activedocument (vlax-get-acad-object)))
    (vlax-for o b
      (add o)
      (if (and (= "AcDbBlockReference" (vl-catch-all-apply 'vla-get-objectname (list o)))
               (= :vlax-true (vl-catch-all-apply 'vla-get-hasattributes (list o))))
        (foreach a (vlax-invoke o 'GetAttributes) (add a)))))
  used)

;; TKP:Merge - LAYMRG: muta referintele stratului gol NAME (stiluri Civil 3D) pe stratul 0
;; si il sterge; daca ceva ramane neterminat, comanda se anuleaza
;; (command nu se poate apela prin vl-catch-all-apply: "bad order function")
(defun TKP:Merge (name)
  (command "_.-LAYMRG" "_N" name "" "_N" "0" "_Y")
  (if (> (getvar "CMDACTIVE") 0) (command))
  (not (tblsearch "LAYER" name)))

;; TKP:KeepIds - straturile care nu se sterg niciodata, ca obiecte (ename): comparatia
;; dupa nume nu merge cu diacritice cand LISPSYS = 0
(defun TKP:KeepIds (/ r e)
  (foreach n (append '("0" "Defpoints") (mapcar 'car *TKP:LAYERS*))
    (if (setq e (tblobjname "LAYER" (TKP:Uni n))) (setq r (cons e r))))
  r)

;; TKP:Purge - sterge DOAR straturile goale (fara niciun obiect in desen sau in blocuri).
;; Cele goale dar folosite de stilurile Civil 3D (C-..., V-..., A-... din sablon) se
;; sterg cu LAYMRG spre stratul 0; straturile cu obiecte nu se ating niciodata.
;; Intoarce (sterse ramase-goale)
(defun TKP:Purge (/ keep used lays n name r left)
  (setq keep (TKP:KeepIds) n 0)
  (setvar "CLAYER" "0")
  (setq used (TKP:UsedLayers)
        lays (vla-get-layers (vla-get-activedocument (vlax-get-acad-object))))
  (vlax-for l lays
    (setq name (vla-get-name l))
    (if (and (not (member (vlax-vla-object->ename l) keep)) (not (member (strcase name) used))
             (not (vl-string-search "|" name)))
      (setq r (cons (cons name l) r))))
  (foreach p r
    (cond ((not (vl-catch-all-error-p (vl-catch-all-apply 'vla-delete (list (cdr p))))) (setq n (1+ n)))
          ((and (wcmatch (strcase (car p)) "?-*") (TKP:Merge (car p))) (setq n (1+ n)))
          (T (setq left (1+ (cond (left) (0)))))))
  (list n (cond (left) (0))))

;; TKP:Arial - fontul Arial in toate stilurile de text (inclusiv cele folosite de
;; etichetele Civil 3D); stilurile de forme (simbolurile tipurilor de linie) raman
(defun TKP:Arial (/ n doc)
  (setq n 0 doc (vla-get-activedocument (vlax-get-acad-object)))
  (vlax-for s (vla-get-textstyles doc)
    (if (and (/= 1 (logand 1 (cdr (assoc 70 (entget (vlax-vla-object->ename s))))))
             (not (vl-catch-all-error-p (vl-catch-all-apply 'vla-setfont (list s "Arial" :vlax-false :vlax-false 0 34)))))
      (setq n (1+ n))))
  (TK:Style)
  (vl-catch-all-apply 'vla-regen (list doc acAllViewports))
  n)

;; TKP:Units - metri, coordonate cu 3 zecimale, unghiuri in grade centesimale (G)
;; sau sexagesimale (D, grade/minute/secunde)
(defun TKP:Units (ang)
  (foreach v (list '("INSUNITS" . 6) '("LUNITS" . 2) '("LUPREC" . 3) '("MEASUREMENT" . 1)
                   (cons "AUNITS" (if (= ang "G") 2 1)) '("AUPREC" . 4))
    (vl-catch-all-apply 'setvar (list (car v) (cdr v)))))

;; TKP:ScaleName - intrarea "1:N" din lista de scari a desenului (o adauga daca lipseste)
(defun TKP:ScaleName (sc / name dict e d ratio n p)
  (setq name (strcat "1:" (itoa sc)) ratio nil)
  (if (setq dict (dictsearch (namedobjdict) "ACAD_SCALELIST"))
    (progn
      (setq dict (cdr (assoc -1 dict)) e (dictnext dict T))
      (while e
        (setq d e)
        (if (= (cdr (assoc 300 d)) name) (setq p T))
        ;; conventia sablonului (Civil 3D metric: 1 mm = 0.5 m la 1:500)
        (if (and (not ratio) (= 'STR (type (cdr (assoc 300 d)))) (wcmatch (cdr (assoc 300 d)) "1:#*")
                 (setq n (atoi (substr (cdr (assoc 300 d)) 3))) (> n 0)
                 (numberp (cdr (assoc 140 d))) (numberp (cdr (assoc 141 d))) (> (cdr (assoc 140 d)) 0))
          (setq ratio (/ (cdr (assoc 141 d)) (cdr (assoc 140 d)) n)))
        (setq e (dictnext dict)))))
  (if (not p)
    (progn
      (command "_.-SCALELISTEDIT" "_A" name (strcat "1:" (TKP:Num (* sc (if ratio ratio 1.0)))) "_E")
      (if (> (getvar "CMDACTIVE") 0) (command))))
  name)

;; TKP:SetScale - scara planului: adnotare (etichetele Civil 3D), tipuri de linie
;; (LTSCALE 1 la 1:500), puncte AutoCAD (cerculet de 1 mm), setarile TopoKit
(defun TKP:SetScale (sc / name i)
  (setq name (TKP:ScaleName sc))
  (vl-catch-all-apply 'setvar (list "CANNOSCALE" name))
  (foreach v (list (cons "LTSCALE" (/ sc 500.0)) '("CELTSCALE" . 1.0) '("MSLTSCALE" . 0) '("PSLTSCALE" . 1)
                   '("PDMODE" . 33) (cons "PDSIZE" (* *TKP:PCT* (TKP:K sc))))
    (vl-catch-all-apply 'setvar (list (car v) (cdr v))))
  (TKP:Put "SCARA" sc)
  ;; aceeasi scara pentru cadrul planului si pentru modulul de cadastru
  (if (and (listp *TK:SCARI*) (setq i (vl-position sc *TK:SCARI*))) (setq *TK:SCARA* i))
  (if (and TKC:CfgAll TKC:SaveCfg)
    (progn (setq *TKC:CFG* (subst (cons "SCARA" (float sc)) (assoc "SCARA" (TKC:CfgAll)) (TKC:CfgAll)))
           (TKC:SaveCfg)))
  name)

;; TKP:ScaleTexts - textele de pe straturile standard se maresc / micsoreaza cu factorul F
(defun TKP:ScaleTexts (f / ss i e d n)
  (setq n 0)
  (if (setq ss (ssget "_X" '((0 . "TEXT,MTEXT"))))
    (repeat (setq i (sslength ss))
      (setq e (ssname ss (setq i (1- i))) d (entget e))
      (if (wcmatch (strcase (cdr (assoc 8 d))) *TKP:LAYTXT*)
        (progn
          (setq d (subst (cons 40 (* f (cdr (assoc 40 d)))) (assoc 40 d) d))
          (if (and (= (cdr (assoc 0 d)) "MTEXT") (assoc 41 d))
            (setq d (subst (cons 41 (* f (cdr (assoc 41 d)))) (assoc 41 d) d)))
          (entmod d)
          (setq n (1+ n))))))
  n)

;;; ==========================================================================
;;;  CIVIL 3D (COM)
;;; ==========================================================================

;; TKP:C3d - documentul Civil 3D activ (nil in AutoCAD simplu)
(defun TKP:C3d (/ app r)
  (foreach v '("13.8" "13.9" "13.10" "13.11" "13.7" "13.6" "13.5" "13.4" "13.3")
    (if (and (not app)
             (not (vl-catch-all-error-p
                    (setq r (vl-catch-all-apply 'vla-getinterfaceobject
                              (list (vlax-get-acad-object) (strcat "AeccXUiLand.AeccApplication." v)))))))
      (setq app r)))
  (if app
    (if (not (vl-catch-all-error-p (setq r (vl-catch-all-apply 'vlax-get (list app 'ActiveDocument))))) r)))

;; TKP:G - proprietatea P a obiectului O, sau un drum de proprietati '(A B C) (nil la eroare)
(defun TKP:G (o p / r)
  (if (listp p)
    (progn (foreach x p (setq o (TKP:G o x))) o)
    (if (and o (not (vl-catch-all-error-p (setq r (vl-catch-all-apply 'vlax-get (list o p)))))) r)))

;; TKP:V - seteaza valoarea (.Value) proprietatii P a obiectului O; T daca a mers.
;; Da/Nu se trimit cu vlax-put-property: in Civil 3D, vlax-put cu :vlax-false nu schimba nimic
(defun TKP:V (o p v / x)
  (and (setq x (TKP:G o p))
       (not (vl-catch-all-error-p
              (vl-catch-all-apply (if (member v '(:vlax-true :vlax-false)) 'vlax-put-property 'vlax-put)
                                  (list x 'Value v))))))

;; TKP:P - seteaza direct proprietatea P (fara .Value); T daca a mers
(defun TKP:P (o p v)
  (and o (not (vl-catch-all-error-p (vl-catch-all-apply 'vlax-put (list o p v))))))

;; TKP:Find - elementul cu numele NAME din colectia COLL
(defun TKP:Find (coll name / r)
  (if coll
    (vlax-for x coll
      (if (and (not r) (= (strcase (vl-princ-to-string (TKP:G x 'Name))) (strcase name))) (setq r x))))
  r)

;; TKP:Item - elementul NAME din colectie; il adauga daca lipseste. Intoarce (obiect . nou)
(defun TKP:Item (coll name / r)
  (cond ((setq r (TKP:Find coll name)) (cons r nil))
        ((and coll (not (vl-catch-all-error-p (setq r (vl-catch-all-apply 'vlax-invoke (list coll 'Add name))))))
         (cons r T))))

;; TKP:Text - componenta de text NAME a stilului de eticheta ST
(defun TKP:Text (st name contents h color anchor attach x y ang / c)
  (if (setq c (car (TKP:Item (TKP:G st 'TextComponents) name)))
    (progn
      (TKP:V c 'Contents contents)
      (TKP:V c 'Height h)
      (TKP:V c 'Color color)
      (TKP:V c 'AnchorPoint anchor)
      (TKP:V c 'Attachment attach)
      (TKP:V c 'XOffset x)
      (TKP:V c 'YOffset y)
      (TKP:V c 'Angle ang)
      (TKP:V c 'Visibility :vlax-true)))
  c)

;; TKP:Line - componenta de linie NAME (porneste din punctul etichetei, unghi ANG, lungime LEN)
(defun TKP:Line (st name ang len color / c)
  (if (setq c (car (TKP:Item (TKP:G st 'LineComponents) name)))
    (progn
      (TKP:V c 'UseEndPointAnchor :vlax-false)
      (TKP:V c 'Angle ang)
      (TKP:V c 'Length len)
      (TKP:V c 'StartPointXOffset 0.0)
      (TKP:V c 'StartPointYOffset 0.0)
      (TKP:V c 'Color color)
      (TKP:V c 'Visibility :vlax-true)))
  c)

;; TKP:Label - proprietatile comune ale stilurilor de eticheta: Arial (stilul de text
;; Standard), mutata ramane "as composed" si fara leader
(defun TKP:Label (st readable)
  (TKP:V (TKP:G st 'LabelProperties) 'TextStyle "Standard")
  (TKP:V (TKP:G st 'LabelProperties) 'PlanReadable (if readable :vlax-true :vlax-false))
  (TKP:V (TKP:G st 'DraggedComponentStyle) 'StackText :vlax-false)
  (TKP:V (TKP:G st 'DraggedLeaderStyle) 'Visibility :vlax-false))

;; TKP:Hide - ascunde componentele de text pe care nu le-a facut TopoKit (ex. "Note")
(defun TKP:Hide (st keep)
  (vlax-for c (TKP:G st 'TextComponents)
    (if (not (member (TKP:G c 'Name) keep)) (TKP:V c 'Visibility :vlax-false))))

;; TKP:PointStyles - stilul de punct Basic (AutoCAD POINT, alb, 1 mm la scara) si
;; eticheta Point Description (descrierea, Arial 1.5 mm, alba, Middle left)
(defun TKP:PointStyles (cdoc / ps r st h g)
  (setq h (/ *TKP:TXT* 1000.0) g (/ *TKP:TXT* 2000.0))
  (if (setq ps (car (TKP:Item (TKP:G cdoc 'PointStyles) *TKP:STPCT*)))
    (progn
      (TKP:P ps 'MarkerType 0)                 ; aeccUsePointForMarker: PDMODE (PTYPE)
      (TKP:P ps 'MarkerSizeType 0)             ; aeccDrawingScale
      (TKP:P ps 'MarkerSize (/ *TKP:PCT* 1000.0))
      (foreach d '(MarkerDisplayStylePlan MarkerDisplayStyleModel LabelDisplayStylePlan LabelDisplayStyleModel)
        (TKP:P (TKP:G ps d) 'Color 7))))
  (if (setq r (TKP:Item (TKP:G cdoc 'PointLabelStyles) *TKP:STLBL*))
    (progn
      (setq st (car r))
      (TKP:Label st T)
      (TKP:Text st "Point Description" "<[Full Description(CP)]>" h 7 3 3 g 0.0 0.0)
      (if (cdr r) (TKP:Hide st '("Point Description")))))
  ;; stilurile implicite pentru punctele noi si pentru grupul _All Points
  (TKP:V (TKP:G cdoc '(Settings PointSettings StyleSettings)) 'Style *TKP:STPCT*)
  (TKP:V (TKP:G cdoc '(Settings PointSettings StyleSettings)) 'LabelStyle *TKP:STLBL*)
  (if (setq g (TKP:Find (TKP:G cdoc 'PointGroups) "_All Points"))
    (progn
      (or (TKP:P g 'PointStyle ps) (TKP:P g 'PointStyle *TKP:STPCT*))
      (or (TKP:P g 'PointLabelStyle st) (TKP:P g 'PointLabelStyle *TKP:STLBL*))))
  ;; punctele noi pe stratul Puncte, etichetele de caroiaj pe Caroiaj
  (TKP:P (TKP:G cdoc '(Settings DrawingSettings ObjectLayerSettings PointEntityLayer)) 'Layer "Puncte")
  (TKP:P (TKP:G cdoc '(Settings DrawingSettings ObjectLayerSettings GeneralNoteLabelLayer)) 'Layer "Caroiaj")
  (and ps st))

;; TKP:Ambient - unitatile Civil 3D: metri, distante cu 2 zecimale, coordonate si cote
;; cu 3, suprafete in mp cu 2, unghiuri si directii (azimut) in grade centesimale / sexagesimale
(defun TKP:Ambient (cdoc ang / uz am au fmt)
  (setq uz (TKP:G cdoc '(Settings DrawingSettings UnitZoneSettings))
        am (TKP:G cdoc '(Settings DrawingSettings AmbientSettings))
        au (if (= ang "G") 3 1)                 ; aeccAngleUnitGrad / aeccAngleUnitDegree
        fmt (if (= ang "G") 1 3))               ; zecimal / grade-minute-secunde
  (TKP:P uz 'DrawingUnits 2)                     ; aeccDrawingUnitMeters
  (TKP:P uz 'AngularUnits au)
  (foreach s '((DistanceSettings 2) (CoordinateSettings 3) (ElevationSettings 3) (AreaSettings 2))
    (TKP:V (TKP:G am (car s)) 'Unit 1)           ; metru / metru patrat
    (TKP:V (TKP:G am (car s)) 'Precision (cadr s)))
  (TKP:V (TKP:G am 'AngleSettings) 'Unit au)
  (TKP:V (TKP:G am 'AngleSettings) 'Format fmt)
  (TKP:V (TKP:G am 'AngleSettings) 'Precision 4)
  (TKP:V (TKP:G am 'DirectionSettings) 'Unit au)
  (TKP:V (TKP:G am 'DirectionSettings) 'Format fmt)
  (TKP:V (TKP:G am 'DirectionSettings) 'Precision 4)
  (TKP:V (TKP:G am 'DirectionSettings) 'MeasurementType 2)    ; azimut de la nord
  (and uz am))

;; TKP:GridStyles - stilurile General Note Label pentru caroiaj: un colt (N= orizontal,
;; E= vertical, linii in L) pentru fiecare colt si cruciulita din interior
(defun TKP:GridStyles (cdoc / coll h ga gp L c st r sx sy)
  ;; textele incep la 1.5 x inaltimea din colt (nu se suprapun) si stau la 0.2 x inaltimea de linie
  (setq coll (TKP:G cdoc 'GeneralNoteLabelStyles)
        h (/ *TKP:TXT* 1000.0) ga (* 1.5 h) gp (* 0.2 h) L (/ *TKP:LIN* 1000.0) c (/ *TKP:CRUCE* 1000.0))
  ;; (cod  sens-x sens-y  atasare-N  atasare-E)
  (foreach k '(("SS" 1 -1 0 2) ("SD" -1 -1 2 8) ("JS" 1 1 6 0) ("JD" -1 1 8 6))
    (if (setq r (TKP:Item coll (cdr (assoc (car k) *TKP:STCOLT*))))
      (progn
        (setq st (car r) sx (cadr k) sy (caddr k))
        (TKP:Label st nil)
        ;; N= pe linia orizontala (deasupra jos, dedesubt sus), E= rotit 90 grade langa linia verticala
        (TKP:Text st "Nord" (strcat "N=" *TKP:FN*) h 7 4 (cadddr k) (* sx ga) (* sy gp) 0.0)
        (TKP:Text st "Est" (strcat "E=" *TKP:FE*) h 7 4 (nth 4 k) (* sx gp) (* sy ga) (/ pi 2.0))
        (TKP:Line st "Linie orizontala" (if (> sx 0) 0.0 pi) L 7)
        (TKP:Line st "Linie verticala" (if (> sy 0) (/ pi 2.0) (* 1.5 pi)) L 7)
        ;; textul implicit "Note" al unui stil nou nu se vede: doar coordonatele si liniile
        (TKP:Hide st '("Nord" "Est")))))
  (if (setq r (TKP:Item coll *TKP:STCRUCE*))
    (progn
      (setq st (car r))
      (TKP:Label st nil)
      (TKP:Line st "Brat est" 0.0 c 7)
      (TKP:Line st "Brat nord" (/ pi 2.0) c 7)
      (TKP:Line st "Brat vest" pi c 7)
      (TKP:Line st "Brat sud" (* 1.5 pi) c 7)
      (TKP:Hide st nil)))
  (TKP:Find coll *TKP:STCRUCE*))

;; TKP:Civil - toata configurarea Civil 3D; intoarce lista mesajelor
(defun TKP:Civil (ang / cdoc out)
  (if (setq cdoc (TKP:C3d))
    (progn
      (setq out (list (if (TKP:Ambient cdoc ang)
                          "Civil 3D: unitati in metri, distante, unghiuri si directii setate."
                          "Civil 3D: setarile de unitati nu au putut fi schimbate.")
                      (if (TKP:PointStyles cdoc)
                          "Civil 3D: punctele pe stilul Basic (AutoCAD POINT, alb) cu eticheta Point Description."
                          "Civil 3D: stilurile de punct nu au putut fi configurate complet.")
                      (if (TKP:GridStyles cdoc)
                          "Civil 3D: stilurile de caroiaj (General Note Label) sunt gata; caroiajul: TKCAROIAJ."
                          "Civil 3D: stilurile de caroiaj nu au putut fi create.")))
      (vl-catch-all-apply 'vlax-invoke (list cdoc 'Regen acAllViewports))
      out)
    (list "Desenul nu este deschis in Civil 3D: stilurile de puncte si etichete au fost sarite.")))

;;; ==========================================================================
;;;  TKPROIECT
;;; ==========================================================================

(defun TKP:Q (s) (strcat "\"" s "\""))

(defun TKP:Dcl ()
  (list "tkp_proiect : dialog {"
        "  label = \"TopoKit - Pregatire proiect nou\";"
        "  : popup_list { key = \"scara\"; label = \"Scara planului:\"; edit_width = 12; }"
        "  : boxed_radio_column { key = \"unghi\"; label = \"Unghiuri si directii\";"
        "    : radio_button { key = \"G\"; label = \"Grade centesimale (400g)\"; }"
        "    : radio_button { key = \"D\"; label = \"Grade sexagesimale (360, grade-minute-secunde)\"; }"
        "  }"
        "  : boxed_column { label = \"Ce se configureaza\";"
        "    : toggle { key = \"STERG\"; label = \"Sterge straturile goale (cele implicite din Civil 3D); cele cu obiecte raman\"; }"
        "    : toggle { key = \"STRAT\"; label = \"Straturile standard (Puncte, Terenuri, Vecinatati, Constructii, Caroiaj...)\"; }"
        "    : toggle { key = \"FONT\"; label = \"Font Arial in toate stilurile de text\"; }"
        "    : toggle { key = \"C3D\"; label = \"Civil 3D: puncte, eticheta Point Description, unitati, caroiaj\"; }"
        "  }"
        "  : text { label = \"Mereu: unitati in metri, puncte AutoCAD (PTYPE) cu cerculet de 1 mm, scara planului.\"; }"
        "  : text { label = \"Scara se poate schimba oricand cu TKSCARA.\"; }"
        "  ok_cancel;"
        "}"))

;; TKP:Dialog - intoarce setarile alese sau nil
(defun TKP:Dialog (/ cfg fn f id r sc)
  (setq cfg (TKP:Cfg) fn (vl-filename-mktemp "tkproiect" nil ".dcl") f (open fn "w") r 0)
  (foreach ln (TKP:Dcl) (write-line ln f))
  (close f)
  (setq id (load_dialog fn))
  (if (and (>= id 0) (new_dialog "tkp_proiect" id))
    (progn
      (start_list "scara")
      (foreach s *TKP:SCARI* (add_list (strcat "1:" (itoa s))))
      (end_list)
      (set_tile "scara" (itoa (cond ((vl-position (cdr (assoc "SCARA" cfg)) *TKP:SCARI*)) (3))))
      (set_tile "unghi" (cdr (assoc "UNGHI" cfg)))
      (foreach k '("STERG" "STRAT" "FONT" "C3D") (set_tile k (cdr (assoc k cfg))))
      (action_tile "accept"
        (strcat "(setq *TKP:WK* (list (cons \"SCARA\" (nth (atoi (get_tile \"scara\")) *TKP:SCARI*))"
                " (cons \"UNGHI\" (get_tile \"unghi\")) (cons \"STERG\" (get_tile \"STERG\"))"
                " (cons \"STRAT\" (get_tile \"STRAT\")) (cons \"FONT\" (get_tile \"FONT\"))"
                " (cons \"C3D\" (get_tile \"C3D\")))) (done_dialog 1)"))
      (setq r (start_dialog))))
  (if (>= id 0) (unload_dialog id))
  (vl-file-delete fn)
  (if (= r 1) *TKP:WK*))

;; TKP:Prepare - pregateste desenul cu setarile CFG; intoarce lista mesajelor
(defun TKP:Prepare (cfg / sc ang out r)
  (setq sc (cdr (assoc "SCARA" cfg)) ang (cdr (assoc "UNGHI" cfg)))
  (TKP:SaveCfg cfg)
  (if (= (cdr (assoc "STERG" cfg)) "1")
    (progn
      (setq r (TKP:Purge))
      (setq out (cons (strcat "Straturi goale sterse: " (itoa (car r))
                              (if (> (cadr r) 0) (strcat " (" (itoa (cadr r)) " goale raman: sunt folosite de stiluri)") "")
                              "; straturile cu obiecte nu se sterg.")
                      out))))
  (if (= (cdr (assoc "STRAT" cfg)) "1")
    (setq out (cons (strcat "Straturi standard: " (itoa (length *TKP:LAYERS*)) " (" (itoa (TKP:Layers)) " noi).") out)))
  (if (= (cdr (assoc "FONT" cfg)) "1")
    (setq out (cons (strcat "Font Arial in " (itoa (TKP:Arial)) " stiluri de text.") out)))
  (TKP:Units ang)
  (setq out (cons (strcat "Unitati: metri; unghiuri in " (if (= ang "G") "grade centesimale." "grade sexagesimale.")) out))
  (TKP:SetScale sc)
  (setq out (cons (strcat "Scara 1:" (itoa sc) ": text " (TKP:Num (* *TKP:TXT* (TKP:K sc))) " m, cerculet punct "
                          (TKP:Num (* *TKP:PCT* (TKP:K sc))) " m (PTYPE), LTSCALE " (TKP:Num (/ sc 500.0))
                          ", caroiaj la " (TKP:Num (cdr (assoc sc *TKP:PAS*))) " m.")
                  out))
  (if (= (cdr (assoc "C3D" cfg)) "1")
    (setq out (append (reverse (TKP:Civil ang)) out)))
  (if (tblsearch "LAYER" "Puncte") (setvar "CLAYER" "Puncte"))
  (reverse out))

(defun TKP:CmdProiect (/ cfg)
  (if (setq cfg (TKP:Dialog))
    (progn
      (TKP:Msg "Pregatire proiect nou...")
      (foreach s (TKP:Prepare cfg) (TKP:Msg (strcat "  " s)))
      (TKP:Msg "Proiectul este pregatit. Caroiajul: TKCAROIAJ; alta scara: TKSCARA."))))

;;; ==========================================================================
;;;  TKSCARA
;;; ==========================================================================

(defun TKP:AskScale (msg def / s v)
  (setq s (getstring (strcat msg " [50/100/200/500/1000/2000/5000] <" (itoa def) ">: ")))
  (setq s (vl-string-trim " " s))
  (if (wcmatch s "1:*") (setq s (substr s 3)))
  (cond ((= s "") def)
        ((member (setq v (atoi s)) *TKP:SCARI*) v)
        (T (TKP:Msg "Scara trebuie sa fie una din standard: 50, 100, 200, 500, 1000, 2000, 5000.") nil)))

(defun TKP:CmdScara (/ old new n)
  (setq old (TKP:Scara))
  (if (and (setq new (TKP:AskScale (strcat "\nScara noua a planului (acum 1:" (itoa old) ")") old))
           (/= new old))
    (progn
      (TKP:SetScale new)
      (setq n (TKP:ScaleTexts (/ (float new) old)))
      (TKP:Msg (strcat "Desenul este la scara 1:" (itoa new) ": etichetele Civil 3D, punctele si tipurile de linie"
                       " s-au adaptat; texte redimensionate: " (itoa n) ".")))
    (if new (TKP:Msg (strcat "Desenul este deja la scara 1:" (itoa old) ".")))))

;;; ==========================================================================
;;;  TKCAROIAJ
;;; ==========================================================================

;; TKP:Nodes - nodurile caroiajului (multipli de PAS) din dreptunghiul P1-P2
(defun TKP:Range (a b pas / v r)
  (setq v (* pas (fix (/ (+ (min a b) (* pas 0.999999)) pas))))
  (if (< v (min a b)) (setq v (+ v pas)))
  (while (<= v (+ (max a b) 1e-6)) (setq r (cons v r) v (+ v pas)))
  (reverse r))

;; TKP:Txt - text cu justificarea J ("BL" "BR" "TL" "TR" ...), rotatie ROT
(defun TKP:Txt (s p h rot j lay)
  (entmake (list '(0 . "TEXT") (cons 8 lay) (list 10 (car p) (cadr p) 0.0) (list 11 (car p) (cadr p) 0.0)
                 (cons 40 h) (cons 1 s) (cons 50 rot) (cons 7 (TK:Style))
                 (cons 72 (cdr (assoc (substr j 2 1) '(("L" . 0) ("C" . 1) ("R" . 2)))))
                 (cons 73 (cdr (assoc (substr j 1 1) '(("B" . 1) ("M" . 2) ("T" . 3))))))))

;; TKP:DrawCorner - coltul caroiajului desenat cu linii si texte (fara Civil 3D)
(defun TKP:DrawCorner (p kind k / sx sy h ga gp L n e)
  (setq sx (if (wcmatch kind "?S") 1.0 -1.0) sy (if (wcmatch kind "J?") 1.0 -1.0)
        h (* *TKP:TXT* k) ga (* 1.5 h) gp (* 0.2 h) L (* *TKP:LIN* k)
        n (strcat "N=" (rtos (cadr p) 2 0)) e (strcat "E=" (rtos (car p) 2 0)))
  (TK:Line p (list (+ (car p) (* sx L)) (cadr p)) "Caroiaj" nil)
  (TK:Line p (list (car p) (+ (cadr p) (* sy L))) "Caroiaj" nil)
  (TKP:Txt n (list (+ (car p) (* sx ga)) (+ (cadr p) (* sy gp))) h 0.0
           (strcat (if (> sy 0) "B" "T") (if (> sx 0) "L" "R")) "Caroiaj")
  ;; textul vertical: atasarea in sistemul textului rotit (stanga = jos, sus = spre vest)
  (TKP:Txt e (list (+ (car p) (* sx gp)) (+ (cadr p) (* sy ga))) h (/ pi 2.0)
           (strcat (if (> sx 0) "T" "B") (if (> sy 0) "L" "R")) "Caroiaj"))

(defun TKP:DrawCross (p k / c)
  (setq c (* *TKP:CRUCE* k))
  (TK:Line (list (- (car p) c) (cadr p)) (list (+ (car p) c) (cadr p)) "Caroiaj" nil)
  (TK:Line (list (car p) (- (cadr p) c)) (list (car p) (+ (cadr p) c)) "Caroiaj" nil))

;; TKP:NoteLabels - eticheta Civil 3D (General Note Label) cu stilul STYLE in punctele PTS
(defun TKP:NoteLabels (cdoc style pts / s n)
  (setq s (TKP:G cdoc '(Settings GeneralCommandsSettings AddNoteLabelSettings StyleSettings)))
  (if (and pts (TKP:V s 'NoteLabelStyle style))
    (progn
      (setq n (length pts))
      (command "_.AeccAddNoteLabel")
      (foreach p pts (command "_non" (list (car p) (cadr p) 0.0)))
      (command "")
      (if (> (getvar "CMDACTIVE") 0) (command))
      n)
    0))

(defun TKP:CmdCaroiaj (/ sc pas k p1 p2 xs ys corners inner cdoc kw n)
  (setq sc (TKP:Scara) pas (cdr (assoc sc *TKP:PAS*)) k (TKP:K sc))
  (TK:MakeLayer "Caroiaj" 8)
  (TKP:Msg (strcat "Caroiaj la scara 1:" (itoa sc) ": cruciulite la " (TKP:Num pas) " m (alta scara: TKSCARA)."))
  (if (and (setq p1 (getpoint "\nPrimul colt al zonei caroiajului: "))
           (setq p2 (getcorner p1 "\nColtul opus: ")))
    (progn
      (setq xs (TKP:Range (car p1) (car p2) pas) ys (TKP:Range (cadr p1) (cadr p2) pas))
      (if (or (< (length xs) 2) (< (length ys) 2))
        (TKP:Msg (strcat "Zona este prea mica: trebuie sa cuprinda cel putin doua linii de caroiaj pe fiecare directie ("
                         (TKP:Num pas) " m)."))
        (progn
          (initget "Da Nu")
          (setq kw (getkword "\nCruciulite in interiorul caroiajului? [Da/Nu] <Da>: "))
          (setq corners (list (cons "JS" (list (car xs) (car ys))) (cons "JD" (list (last xs) (car ys)))
                              (cons "SS" (list (car xs) (last ys))) (cons "SD" (list (last xs) (last ys)))))
          (if (/= kw "Nu")
            (foreach x xs
              (foreach y ys
                (if (not (and (member x (list (car xs) (last xs))) (member y (list (car ys) (last ys)))))
                  (setq inner (cons (list x y) inner))))))
          (setq cdoc (TKP:C3d) n 0)
          (if (and cdoc (TKP:GridStyles cdoc))
            (progn
              (setvar "CLAYER" "Caroiaj")
              (foreach c corners
                (setq n (+ n (TKP:NoteLabels cdoc (cdr (assoc (car c) *TKP:STCOLT*)) (list (cdr c))))))
              (setq n (+ n (TKP:NoteLabels cdoc *TKP:STCRUCE* inner)))
              (TKP:Msg (strcat "Caroiaj Civil 3D: " (itoa n) " etichete (4 colturi, " (itoa (length inner))
                               " cruciulite). Cand muti o eticheta, coordonatele se actualizeaza singure.")))
            (progn
              (foreach c corners (TKP:DrawCorner (cdr c) (car c) k))
              (foreach p inner (TKP:DrawCross p k))
              (TKP:Msg (strcat "Caroiaj desenat pe stratul Caroiaj: 4 colturi, " (itoa (length inner)) " cruciulite"
                               " (fara Civil 3D coordonatele nu se actualizeaza la mutare)."))))))))
  (princ))

;;; ==========================================================================
;;;  COMENZI
;;; ==========================================================================

(defun TKP:Run (fn / *error* r)
  (defun *error* (msg) (TK:Error msg))
  (TK:Start)
  (setq r (eval fn))
  (TK:Stop)
  r)

(defun c:TKPROIECT () (TKP:Run '(TKP:CmdProiect)) (princ))
(defun c:TKSCARA () (TKP:Run '(TKP:CmdScara)) (princ))
(defun c:TKCAROIAJ () (TKP:Run '(TKP:CmdCaroiaj)) (princ))

(setq *TKP:LOADING* nil)
(princ "\nTopoKit Proiect incarcat. Comenzi: TKPROIECT (proiect nou), TKSCARA, TKCAROIAJ.")
(princ)
