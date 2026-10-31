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
;; (si straturile modulului de cadastru: numerele punctelor, cotele, suprafetele)
(setq *TKP:LAYTXT* "PUNCTE*,ASCUNS*,TERENURI,VECIN*,DIMENSIUNI,CONSTRUC*,CAROIAJ,PAD,0_PNT_NUMBER,DIMENSIONS,SUPRAFETE")

;; Stilurile Civil 3D create de TopoKit
(setq *TKP:STPCT* "Basic" *TKP:STLBL* "Point Description" *TKP:STCRUCE* "Caroiaj - cruciulita")
;; cruciulitele cu coordonate, in acelasi design ca liniile in L de la colturi: bratul cu text e lung
;; (ca linia L), celelalte raman scurte; textul sta pe brat, spre interiorul caroiajului.
;; Cheia (sens-N sens-E): N= pe bratul est (1) sau vest (-1); E= pe bratul nord (1) sau sud (-1); nil = fara
(setq *TKP:STCRUCEX*
       (list (cons (list 1 nil) "Caroiaj - cruciulita N") (cons (list -1 nil) "Caroiaj - cruciulita N stanga")
             (cons (list nil 1) "Caroiaj - cruciulita E") (cons (list nil -1) "Caroiaj - cruciulita E jos")
             (cons (list 1 1) "Caroiaj - cruciulita N E") (cons (list -1 1) "Caroiaj - cruciulita N E stanga")
             (cons (list 1 -1) "Caroiaj - cruciulita N E jos")
             (cons (list -1 -1) "Caroiaj - cruciulita N E stanga jos")))
(setq *TKP:STCOLT* '(("SS" . "Caroiaj - colt stanga sus") ("SD" . "Caroiaj - colt dreapta sus")
                     ("JS" . "Caroiaj - colt stanga jos") ("JD" . "Caroiaj - colt dreapta jos")))
;; Eticheta de segment (cote): stilul si continutul (metri, 2 zecimale, " m")
(setq *TKP:STSEG* "Distance Only"
      *TKP:FSEG* "<[General Segment Length(Um|P2|RN|AP|GC|UN|Sn|OF)]> m")
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

;; TKP:ShowLayer - stratul NAME dezghetat si pornit (intoarce T daca a trebuit schimbat)
(defun TKP:ShowLayer (name / e d fl col ch)
  (if (and (setq e (tblobjname "LAYER" name)) (setq d (entget e)))
    (progn
      (setq fl (cond ((cdr (assoc 70 d))) (0)) col (cond ((cdr (assoc 62 d))) (7)))
      (if (= 1 (logand 1 fl)) (setq d (subst (cons 70 (- fl 1)) (assoc 70 d) d) ch T))
      (if (minusp col) (setq d (subst (cons 62 (abs col)) (assoc 62 d) d) ch T))
      (if ch (entmod d))
      ch)))

;; TKP:SetClayer - stratul curent NAME, fara eroare daca AutoCAD il refuza (de ex. inghetat)
(defun TKP:SetClayer (name)
  (and (tblsearch "LAYER" name)
       (not (vl-catch-all-error-p (vl-catch-all-apply 'setvar (list "CLAYER" name))))))

;; TKP:ToLayer - obiectele create dupa E0 (entlast de dinainte) trec pe stratul LAY
(defun TKP:ToLayer (e0 lay / e n)
  (setq e (if e0 (entnext e0) (entnext)) n 0)
  (while e
    (if (not (vl-catch-all-error-p
               (vl-catch-all-apply 'vla-put-layer (list (vlax-ename->vla-object e) lay))))
      (setq n (1+ n)))
    (setq e (entnext e)))
  n)

;; TKP:Num - numar fara zerouri inutile
(defun TKP:Num (v / r)
  (setq r (rtos v 2 4))
  (if (vl-string-search "." r) (setq r (vl-string-right-trim "." (vl-string-right-trim "0" r))))
  r)

;; Setarile proiectului (pastrate in desen): ((SCARA . 500) (UNGHI . "G") ...)
(setq *TKP:DEF* '(("SCARA" . 500) ("UNGHI" . "G") ("STERG" . "1") ("STRAT" . "1") ("FONT" . "1") ("C3D" . "1")
                  ("CRUCECOORD" . "Directie")))

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
;; TKP:K - metri in desen pentru 1 mm pe hartie la scara planului
(defun TKP:K (sc) (/ sc 1000.0))

;; Scara de adnotare ramane mereu 1:1000 (ca stilurile de caroiaj existente); la alta scara a
;; planului se schimba doar marimile. TKP:Pm - valoarea din stilurile Civil 3D (metri pe
;; hartie la 1:1000) pentru MM milimetri pe hartie la scara SC: 1.5 mm la 1:500 -> 0.00075
(setq *TKP:ANNO* 1000)
(defun TKP:Pm (mm sc) (* (/ mm 1000.0) (/ sc (float *TKP:ANNO*))))

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
(defun TKP:Purge (/ keep used lays n name r left batch)
  (setq keep (TKP:KeepIds) n 0)
  (TKP:SetClayer "0")
  (setq used (TKP:UsedLayers)
        lays (vla-get-layers (vla-get-activedocument (vlax-get-acad-object))))
  (vlax-for l lays
    (setq name (vla-get-name l))
    (if (and (not (member (vlax-vla-object->ename l) keep)) (not (member (strcase name) used))
             (not (vl-string-search "|" name)))
      (setq r (cons (cons name l) r))))
  ;; intai stergerea directa (rapida); cele folosite de stilurile Civil 3D (C-..., V-..., A-...) se
  ;; aduna si se muta toate pe stratul 0 cu UN singur LAYMRG (inainte: o comanda pe strat, ~30 s)
  (foreach p r
    (cond ((not (vl-catch-all-error-p (vl-catch-all-apply 'vla-delete (list (cdr p))))) (setq n (1+ n)))
          ((wcmatch (strcase (car p)) "?-*") (setq batch (cons (car p) batch)))
          (T (setq left (1+ (cond (left) (0)))))))
  (if batch (TKP:MergeAll batch))
  ;; ce n-a mers in grup se incearca unul cate unul
  (foreach name batch
    (cond ((not (tblsearch "LAYER" name)) (setq n (1+ n)))
          ((TKP:Merge name) (setq n (1+ n)))
          (T (setq left (1+ (cond (left) (0)))))))
  (list n (cond (left) (0))))

;; TKP:MergeAll - LAYMRG cu mai multe straturi deodata (nume fara spatii si separatori), in grupuri
(defun TKP:MergeAll (names / grp i)
  (setq names (vl-remove-if '(lambda (x) (wcmatch x "*[ ,;]*")) names))
  (while names
    (setq grp nil i 0)
    (while (and names (< i 60)) (setq grp (cons (car names) grp) names (cdr names) i (1+ i)))
    (command "_.-LAYMRG")
    (foreach name grp (command "_N" name))
    (command "" "_N" "0" "_Y")
    (if (> (getvar "CMDACTIVE") 0) (command))))

;; TKP:Arial - fontul Arial in toate stilurile de text (inclusiv cele folosite de
;; etichetele Civil 3D); stilurile de forme (simbolurile tipurilor de linie) raman
(defun TKP:Arial (/ n doc)
  (setq n 0 doc (vla-get-activedocument (vlax-get-acad-object)))
  (vlax-for s (vla-get-textstyles doc)
    (if (and (/= 1 (logand 1 (cdr (assoc 70 (entget (vlax-vla-object->ename s))))))
             (not (vl-catch-all-error-p (vl-catch-all-apply 'vla-setfont (list s "Arial" :vlax-false :vlax-false 0 34)))))
      (setq n (1+ n))))
  (TK:Style)
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

;; TKP:SetScale - scara planului. Scara de adnotare ramane 1:1000; se schimba marimile:
;; tipurile de linie (LTSCALE 1 la 1:500), punctele AutoCAD (cerculet de 1 mm pe hartie),
;; cotele noi (text 1.5 mm pe hartie) si setarile TopoKit
(defun TKP:SetScale (sc / name i dt)
  (setq name (TKP:ScaleName *TKP:ANNO*))
  (vl-catch-all-apply 'setvar (list "CANNOSCALE" name))
  (setq dt (getvar "DIMTXT"))
  (foreach v (list (cons "LTSCALE" (/ sc 500.0)) '("CELTSCALE" . 1.0) '("MSLTSCALE" . 0) '("PSLTSCALE" . 1)
                   '("PDMODE" . 33) (cons "PDSIZE" (* *TKP:PCT* (TKP:K sc)))
                   (cons "DIMSCALE" (* (TKP:K sc) (/ *TKP:TXT* (if (and dt (> dt 0)) dt 2.5)))))
    (vl-catch-all-apply 'setvar (list (car v) (cdr v))))
  (TKP:Put "SCARA" sc)
  ;; aceeasi scara pentru cadrul planului si pentru modulul de cadastru
  (if (and (listp *TK:SCARI*) (setq i (vl-position sc *TK:SCARI*))) (setq *TK:SCARA* i))
  (if (and TKC:CfgAll TKC:SaveCfg)
    (progn (setq *TKC:CFG* (subst (cons "SCARA" (float sc)) (assoc "SCARA" (TKC:CfgAll)) (TKC:CfgAll)))
           (TKC:SaveCfg)))
  name)

;; TKP:ScaleTexts - textele si cotele de pe straturile standard se maresc / micsoreaza cu
;; factorul F (pozitia ramane); cotele AutoCAD prin factorul lor de scara
(defun TKP:ScaleTexts (f / ss i e d n o sf)
  (setq n 0)
  (if (setq ss (ssget "_X" '((0 . "TEXT,MTEXT,DIMENSION"))))
    (repeat (setq i (sslength ss))
      (setq e (ssname ss (setq i (1- i))) d (entget e))
      (cond
        ((not (wcmatch (strcase (cdr (assoc 8 d))) *TKP:LAYTXT*)))
        ((= (cdr (assoc 0 d)) "DIMENSION")
         (setq o (vlax-ename->vla-object e) sf (vl-catch-all-apply 'vla-get-scalefactor (list o)))
         (if (and (numberp sf) (not (vl-catch-all-error-p (vl-catch-all-apply 'vla-put-scalefactor (list o (* f sf))))))
           (setq n (1+ n))))
        (T
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
  ;; aplicatia Civil 3D se cauta o singura data pe sesiune ("NONE" = AutoCAD fara Civil 3D)
  (if (null *TKP:C3DAPP*)
    (progn
      (foreach v '("13.8" "13.9" "13.10" "13.11" "13.7" "13.6" "13.5" "13.4" "13.3")
        (if (and (not app)
                 (not (vl-catch-all-error-p
                        (setq r (vl-catch-all-apply 'vla-getinterfaceobject
                                  (list (vlax-get-acad-object) (strcat "AeccXUiLand.AeccApplication." v)))))))
          (setq app r)))
      (setq *TKP:C3DAPP* (if app app "NONE"))))
  (if (/= *TKP:C3DAPP* "NONE")
    (if (not (vl-catch-all-error-p (setq r (vl-catch-all-apply 'vlax-get (list *TKP:C3DAPP* 'ActiveDocument))))) r)))

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

;; TKP:DragDefaults - "drag mode" oprit pentru stilurile de eticheta noi din desen: o eticheta mutata
;; ramane "as composed", fara leader (stilurile TopoKit primesc acelasi lucru prin TKP:Label)
(defun TKP:DragDefaults (cdoc / d)
  (setq d (TKP:G cdoc '(Settings DrawingSettings LabelStyleDefaults)))
  (and (TKP:V (TKP:G d 'DraggedComponentStyle) 'StackText :vlax-false)
       (TKP:V (TKP:G d 'DraggedLeaderStyle) 'Visibility :vlax-false)))

;; TKP:Hide - ascunde componentele de text pe care nu le-a facut TopoKit (ex. "Note")
(defun TKP:Hide (st keep)
  (vlax-for c (TKP:G st 'TextComponents)
    (if (not (member (TKP:G c 'Name) keep)) (TKP:V c 'Visibility :vlax-false))))

;; TKP:PointStyles - stilul de punct Basic (AutoCAD POINT, alb, 1 mm la scara) si
;; eticheta Point Description (descrierea, Arial 1.5 mm, alba, Middle left)
(defun TKP:PointStyles (cdoc sc / ps r st h g)
  (setq h (TKP:Pm *TKP:TXT* sc) g (* 0.5 h))
  (if (setq ps (car (TKP:Item (TKP:G cdoc 'PointStyles) *TKP:STPCT*)))
    (progn
      (TKP:P ps 'MarkerType 0)                 ; aeccUsePointForMarker: PDMODE (PTYPE)
      (TKP:P ps 'MarkerSizeType 2)             ; aeccAbsoluteUnits: 0.5 m la 1:500
      (TKP:P ps 'MarkerSize (* *TKP:PCT* (TKP:K sc)))
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

;; TKP:LineStyles - eticheta de segment (General Segment Label) "Distance Only": lungimea in metri cu
;; 2 zecimale si sufixul " m", Arial alb, marimea textelor din standard (Dimensiuni: 0.75 m la 1:500),
;; Bottom center, gap jumatate din text; etichetele noi folosesc acest stil si stau pe stratul Dimensiuni
(defun TKP:LineStyles (cdoc sc / r st h n)
  (setq h (TKP:Pm *TKP:TXT* sc) n 0)
  (if (setq r (TKP:Item (TKP:G cdoc 'GeneralLineLabelStyles) *TKP:STSEG*))
    (progn
      (setq st (car r))
      (TKP:Label st T)
      ;; componentele existente cu lungimea segmentului (stilul din sablon) sau una noua
      (vlax-for c (TKP:G st 'TextComponents)
        (if (wcmatch (strcase (vl-princ-to-string (TKP:G (TKP:G c 'Contents) 'Value))) "*SEGMENT LENGTH*")
          (progn (TKP:SegText c h) (setq n (1+ n)))))
      (if (= n 0)
        (TKP:SegText (car (TKP:Item (TKP:G st 'TextComponents) "Distanta")) h))))
  (foreach s '(AddSegmentLabelSettings AddSegmentLabelsSettings)
    (TKP:V (TKP:G cdoc (list 'Settings 'GeneralCommandsSettings s 'StyleSettings)) 'LineLabelStyle *TKP:STSEG*))
  (TKP:P (TKP:G cdoc '(Settings DrawingSettings ObjectLayerSettings GeneralSegmentLabelLayer)) 'Layer "Dimensiuni")
  st)

(defun TKP:SegText (c h)
  (if c
    (progn
      (TKP:V c 'Contents *TKP:FSEG*)
      (TKP:V c 'Height h)
      (TKP:V c 'Color 7)
      (TKP:V c 'Attachment 7)            ; Bottom center
      (TKP:V c 'YOffset (* 0.5 h))       ; gap = jumatate din inaltimea textului
      (TKP:V c 'Visibility :vlax-true))))

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
(defun TKP:GridStyles (cdoc sc / coll h ga gp L c st r sx sy)
  ;; textele incep la 1.5 x inaltimea din colt (nu se suprapun) si stau la 0.2 x inaltimea de linie
  (setq coll (TKP:G cdoc 'GeneralNoteLabelStyles)
        h (TKP:Pm *TKP:TXT* sc) ga (* 1.5 h) gp (* 0.2 h) L (TKP:Pm *TKP:LIN* sc) c (TKP:Pm *TKP:CRUCE* sc))
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
  ;; cruciulitele: simpla si cele cu coordonate (TKP:CrossStyle)
  (foreach cs (cons (cons (list nil nil) *TKP:STCRUCE*) *TKP:STCRUCEX*)
    (if (setq r (TKP:Item coll (cdr cs)))
      (TKP:CrossStyle (car r) (car (car cs)) (cadr (car cs)) h ga gp L c)))
  (TKP:Find coll *TKP:STCRUCE*))

;; TKP:AttN / TKP:AttE - atasarea textelor N= / E= pentru sensurile SX, SY (ca la colturi)
(defun TKP:AttN (sx sy) (if (> sy 0) (if (> sx 0) 6 8) (if (> sx 0) 0 2)))
(defun TKP:AttE (sx sy) (if (> sx 0) (if (> sy 0) 0 2) (if (> sy 0) 6 8)))

;; TKP:CrossStyle - cruciulita: patru brate; bratul cu N= (spre NSX) si cel cu E= (spre ESY) au lungimea
;; liniilor L de la colturi, cu textul pe ele; celelalte brate sunt scurte. Cu N= si E= e exact un colt L
;; plus cele doua brate scurte.
(defun TKP:CrossStyle (st nsx esy h ga gp L c / sx sy)
  (setq sx (if nsx nsx 1) sy (if esy esy 1))
  (TKP:Label st nil)
  (TKP:Line st "Brat est" 0.0 (if (and nsx (> nsx 0)) L c) 7)
  (TKP:Line st "Brat vest" pi (if (and nsx (< nsx 0)) L c) 7)
  (TKP:Line st "Brat nord" (/ pi 2.0) (if (and esy (> esy 0)) L c) 7)
  (TKP:Line st "Brat sud" (* 1.5 pi) (if (and esy (< esy 0)) L c) 7)
  (if nsx (TKP:Text st "Nord" (strcat "N=" *TKP:FN*) h 7 4 (TKP:AttN sx sy) (* sx ga) (* sy gp) 0.0))
  (if esy (TKP:Text st "Est" (strcat "E=" *TKP:FE*) h 7 4 (TKP:AttE sx sy) (* sx gp) (* sy ga) (/ pi 2.0)))
  (TKP:Hide st (append (if nsx '("Nord")) (if esy '("Est")))))

;; TKP:Civil - toata configurarea Civil 3D; intoarce lista mesajelor
(defun TKP:Civil (ang sc / cdoc out)
  (if (setq cdoc (TKP:C3d))
    (progn
      (setq out (list (if (TKP:Ambient cdoc ang)
                          "Civil 3D: unitati in metri, distante, unghiuri si directii setate."
                          "Civil 3D: setarile de unitati nu au putut fi schimbate.")
                      (if (TKP:DragDefaults cdoc)
                          "Civil 3D: etichetele mutate raman ca la origine (fara leader, fara text stivuit)."
                          "Civil 3D: modul de mutare a etichetelor nu a putut fi schimbat.")
                      (if (TKP:PointStyles cdoc sc)
                          "Civil 3D: punctele pe stilul Basic (AutoCAD POINT, alb) cu eticheta Point Description."
                          "Civil 3D: stilurile de punct nu au putut fi configurate complet.")
                      (if (TKP:LineStyles cdoc sc)
                          "Civil 3D: eticheta Distance Only: metri, 2 zecimale, pe stratul Dimensiuni."
                          "Civil 3D: eticheta Distance Only nu a putut fi configurata.")
                      (if (TKP:GridStyles cdoc sc)
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
                          ", caroiaj la " (TKP:Num (cdr (assoc sc *TKP:PAS*))) " m; scara de adnotare 1:1000.")
                  out))
  (if (= (cdr (assoc "C3D" cfg)) "1")
    (setq out (append (reverse (TKP:Civil ang sc)) out)))
  (TKP:SetClayer "Puncte")
  (if (/= (cdr (assoc "C3D" cfg)) "1")                ; in Civil 3D regenerarea o face TKP:Civil
    (vl-catch-all-apply 'vla-regen (list (vla-get-activedocument (vlax-get-acad-object)) acAllViewports)))
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

;; TKP:CivilSizes - marimile stilurilor Civil 3D ale TopoKit (punct, eticheta, caroiaj) la scara SC
(defun TKP:CivilSizes (sc / cdoc)
  (if (setq cdoc (TKP:C3d))
    (progn
      (TKP:PointStyles cdoc sc)
      (TKP:LineStyles cdoc sc)
      (if (TKP:Find (TKP:G cdoc 'GeneralNoteLabelStyles) *TKP:STCRUCE*) (TKP:GridStyles cdoc sc))
      (vl-catch-all-apply 'vlax-invoke (list cdoc 'Regen acAllViewports)))))

(defun TKP:CmdScara (/ old new n)
  (setq old (TKP:Scara))
  (if (and (setq new (TKP:AskScale (strcat "\nScara noua a planului (acum 1:" (itoa old) ")") old))
           (/= new old))
    (progn
      (TKP:SetScale new)
      (setq n (TKP:ScaleTexts (/ (float new) old)))
      (TKP:CivilSizes new)
      (TKP:Msg (strcat "Desenul este la scara 1:" (itoa new) " (scara de adnotare ramane 1:1000): punctele,"
                       " etichetele, tipurile de linie si cotele s-au adaptat; texte redimensionate: " (itoa n) ".")))
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

;; TKP:DrawCross - cruciulita desenata cu linii si texte (fara Civil 3D), ca TKP:CrossStyle
(defun TKP:DrawCross (p k key / c h ga gp L nsx esy sx sy x y)
  (setq c (* *TKP:CRUCE* k) h (* *TKP:TXT* k) ga (* 1.5 h) gp (* 0.2 h) L (* *TKP:LIN* k)
        nsx (car key) esy (cadr key) sx (if nsx nsx 1) sy (if esy esy 1) x (car p) y (cadr p))
  (TK:Line (list (- x (if (and nsx (< nsx 0)) L c)) y) (list (+ x (if (and nsx (> nsx 0)) L c)) y) "Caroiaj" nil)
  (TK:Line (list x (- y (if (and esy (< esy 0)) L c))) (list x (+ y (if (and esy (> esy 0)) L c))) "Caroiaj" nil)
  (if nsx
    (TKP:Txt (strcat "N=" (rtos y 2 0)) (list (+ x (* sx ga)) (+ y (* sy gp))) h 0.0
             (strcat (if (> sy 0) "B" "T") (if (> sx 0) "L" "R")) "Caroiaj"))
  (if esy
    (TKP:Txt (strcat "E=" (rtos x 2 0)) (list (+ x (* sx gp)) (+ y (* sy ga))) h (/ pi 2.0)
             (strcat (if (> sx 0) "T" "B") (if (> sy 0) "L" "R")) "Caroiaj")))

;; TKP:CrossKey - cheia stilului cruciulitei P (vezi *TKP:STCRUCEX*) sau nil (simpla). Textele merg spre
;; interiorul caroiajului: pe randul de sus E= pe bratul de jos, pe coloana din dreapta N= pe bratul din
;; stanga. Cu MODE "Directie" se scrie coordonata care se schimba pe directia marginii: E= sus si jos,
;; N= stanga si dreapta; cruciulitele din interior raman simple.
(defun TKP:CrossKey (p mode xs ys / top bot lft rgt sx sy)
  (setq bot (equal (cadr p) (car ys) 1e-6) top (equal (cadr p) (last ys) 1e-6)
        lft (equal (car p) (car xs) 1e-6) rgt (equal (car p) (last xs) 1e-6)
        sx (if rgt -1 1) sy (if top -1 1))
  (cond ((= mode "Est") (list nil sy))
        ((= mode "Nord") (list sx nil))
        ((= mode "Ambele") (list sx sy))
        ((/= mode "Directie") nil)
        ((or bot top) (list nil sy))
        ((or lft rgt) (list sx nil))))

;; TKP:KwName - numele afisat al unei optiuni (in engleza se traduce)
(defun TKP:KwName (s) s)

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

(defun TKP:CmdCaroiaj (/ sc pas k p1 p2 xs ys corners inner cdoc kw n d mode def groups key e0)
  (setq sc (TKP:Scara) pas (cdr (assoc sc *TKP:PAS*)) k (TKP:K sc))
  (TK:MakeLayer "Caroiaj" 8)
  ;; caroiajul trebuie sa se vada: stratul Caroiaj inghetat sau oprit se dezgheata / porneste
  (if (TKP:ShowLayer "Caroiaj") (TKP:Msg "Stratul Caroiaj era inghetat sau oprit: l-am facut vizibil."))
  (TKP:Msg (strcat "Caroiaj la scara 1:" (itoa sc) " (alta scara: TKSCARA)."))
  ;; distanta dintre cruciulite: implicit cea din standard, se poate scrie alta
  (initget 6)
  (if (setq d (getreal (strcat "\nDistanta intre cruciulite, in metri <" (TKP:Num pas) ">: ")))
    (setq pas (float d)))
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
            (progn
              (foreach x xs
                (foreach y ys
                  (if (not (and (member x (list (car xs) (last xs))) (member y (list (car ys) (last ys)))))
                    (setq inner (cons (list x y) inner)))))
              ;; coordonatele pe cruciulite (setare pastrata in desen)
              (setq def (TKP:Get "CRUCECOORD"))
              (if (not (member def '("Fara" "Directie" "Est" "Nord" "Ambele"))) (setq def "Directie"))
              (TKP:Msg "Fara = doar cruciulite; Directie = pe margini coordonata care se schimba (E= sus si jos, N= stanga si dreapta);")
              (TKP:Msg "Est / Nord = E= / N= pe toate cruciulitele; Ambele = N= si E= pe toate cruciulitele.")
              (initget "Fara Directie Est Nord Ambele")
              (setq mode (cond ((getkword (strcat "\nCoordonate pe cruciulite [Fara/Directie/Est/Nord/Ambele] <"
                                                  (cdr (assoc def (list (cons "Fara" (TKP:KwName "Fara"))
                                                                        (cons "Directie" (TKP:KwName "Directie"))
                                                                        (cons "Est" (TKP:KwName "Est"))
                                                                        (cons "Nord" (TKP:KwName "Nord"))
                                                                        (cons "Ambele" (TKP:KwName "Ambele")))))
                                                  ">: ")))
                               (def)))
              (TKP:Put "CRUCECOORD" mode)
              ;; cruciulitele grupate dupa stil: nil (simpla) sau cheia din *TKP:STCRUCEX*
              (foreach p inner
                (setq key (TKP:CrossKey p mode xs ys))
                (if (assoc key groups)
                  (setq groups (subst (cons key (cons p (cdr (assoc key groups)))) (assoc key groups) groups))
                  (setq groups (cons (list key p) groups))))))
          (setq cdoc (TKP:C3d) n 0)
          (if (and cdoc (TKP:GridStyles cdoc sc))
            (progn
              ;; stratul curent ramane cel al utilizatorului; etichetele noi trec apoi pe Caroiaj
              (setq e0 (entlast))
              (foreach c corners
                (setq n (+ n (TKP:NoteLabels cdoc (cdr (assoc (car c) *TKP:STCOLT*)) (list (cdr c))))))
              (foreach g groups
                (setq n (+ n (TKP:NoteLabels cdoc (if (car g) (cdr (assoc (car g) *TKP:STCRUCEX*)) *TKP:STCRUCE*)
                                             (reverse (cdr g))))))
              (TKP:ToLayer e0 "Caroiaj")
              (TKP:Msg (strcat "Caroiaj Civil 3D: " (itoa n) " etichete (4 colturi, " (itoa (length inner))
                               " cruciulite). Cand muti o eticheta, coordonatele se actualizeaza singure.")))
            (progn
              (foreach c corners (TKP:DrawCorner (cdr c) (car c) k))
              (foreach p inner (TKP:DrawCross p k (TKP:CrossKey p mode xs ys)))
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
