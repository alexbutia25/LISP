;;; ==========================================================================
;;; TopoKitLoad.lsp - incarcatorul TopoKit pentru AutoCAD
;;;
;;; Fisierul este incarcat automat de AutoCAD in fiecare desen, prin pachetul
;;; %APPDATA%\Autodesk\ApplicationPlugins\TopoKit.bundle (PackageContents.xml),
;;; sau la cerere de lansatorul TopoKit.exe (iconita din bara de sistem).
;;;
;;;   - gaseste folderul programului (registru HKCU\Software\TopoKit\ContentsDir
;;;     scris de instalator, apoi calea de cautare a AutoCAD);
;;;   - adauga folderul in calea de suport (Support File Search Path), ca
;;;     dialogurile .dcl, grila .gsb si sabloanele din "anexe" sa fie gasite;
;;;   - adauga folderul in locatiile de incredere (TRUSTEDPATHS), daca lipseste;
;;;   - incarca TopoKit.lsp (care incarca TopoKitAnexe.lsp, TopoKitTeren.lsp si
;;;     TopoKitInclinare.lsp).
;;;
;;; (TKL:Load T) reincarca toate modulele (comanda TOPOKITRELOAD).
;;; ==========================================================================

(vl-load-com)

(setq *TKL:REGKEY* "HKEY_CURRENT_USER\\Software\\TopoKit")

(defun TKL:Slash (p) (vl-string-right-trim "\\/" (vl-string-translate "/" "\\" p)))

;; Folderul care contine TopoKit.lsp
(defun TKL:Dir (/ d f)
  (cond
    ((and (setq d (vl-registry-read *TKL:REGKEY* "ContentsDir"))
          (/= d "")
          (findfile (strcat (TKL:Slash d) "\\TopoKit.lsp")))
     (TKL:Slash d))
    ((setq f (findfile "TopoKitLoad.lsp")) (TKL:Slash (vl-filename-directory f)))
    ((setq f (findfile "TopoKit.lsp")) (TKL:Slash (vl-filename-directory f)))))

;; T daca dir apare in lista de cai separate prin ";" (fara diferente de litere)
(defun TKL:InList (dir lst / u)
  (setq u (strcase (TKL:Slash dir)))
  (vl-some '(lambda (p) (= (strcase (TKL:Slash (vl-string-right-trim "." p))) u))
           (TKL:Split (if lst lst "") ";")))

(defun TKL:Split (s sep / i r)
  (while (setq i (vl-string-search sep s))
    (setq r (cons (substr s 1 i) r) s (substr s (+ i 1 (strlen sep)))))
  (reverse (cons s r)))

;; Adauga dir in calea de suport a profilului curent
(defun TKL:AddSupport (dir / files sp)
  (setq files (vla-get-Files (vla-get-Preferences (vlax-get-acad-object)))
        sp (vla-get-SupportPath files))
  (if (not (TKL:InList dir sp))
    (progn (vla-put-SupportPath files (strcat dir ";" sp)) T)))

;; Scoate dir din calea de suport (folderul "en" la trecerea inapoi pe romana)
(defun TKL:DelSupport (dir / files sp u)
  (setq files (vla-get-Files (vla-get-Preferences (vlax-get-acad-object)))
        sp (vla-get-SupportPath files)
        u (strcase (TKL:Slash dir)))
  (if (TKL:InList dir sp)
    (vla-put-SupportPath files
      (substr (apply 'strcat
                     (mapcar '(lambda (p) (strcat ";" p))
                             (vl-remove-if '(lambda (p) (= (strcase (TKL:Slash (vl-string-right-trim "." p))) u))
                                           (TKL:Split sp ";"))))
              2))))

;;; --------------------------------------------------------------------------
;;;  Limba interfetei: "RO" (implicit) sau "EN", in fisierul
;;;  %LOCALAPPDATA%\TopoKit\language.txt (scris de comanda TOPOKITLANG si de
;;;  fereastra TopoKit.exe). Fisierul, nu registrul: unele instalari AutoCAD vad
;;;  o copie virtualizata a registrului, diferita de cea a ferestrei TopoKit.
;;;  Varianta in engleza a modulelor (.lsp, .dcl) se afla in Contents\en; folderul
;;;  e pus in calea de suport INAINTEA folderului Contents, deci findfile gaseste
;;;  intai fisierele traduse. Anexele si planurile raman in romana (Ordinul ANCPI).
;;; --------------------------------------------------------------------------
(defun TKL:LangFile (/ d)
  (if (setq d (getenv "LOCALAPPDATA")) (strcat (TKL:Slash d) "\\TopoKit\\language.txt")))

(defun TKL:Lang (/ f fh l)
  (if (and (setq f (TKL:LangFile)) (findfile f) (setq fh (open f "r")))
    (progn (setq l (read-line fh)) (close fh))
    (setq l (vl-registry-read *TKL:REGKEY* "Language")))
  (if (and (= (type l) 'STR) (= (strcase (vl-string-trim " \t" l)) "EN")) "EN" "RO"))

;; Folderul din care se incarca modulele pentru limba curenta
(defun TKL:LangDir (dir)
  (if (and (= (TKL:Lang) "EN") (findfile (strcat dir "\\en\\TopoKit.lsp")))
    (strcat dir "\\en")
    dir))

;; Calea de suport pentru limba curenta: "Contents\en;Contents;..." sau "Contents;..."
(defun TKL:LangSupport (dir / ld)
  (setq ld (TKL:LangDir dir))
  (if (= ld dir)
    (TKL:DelSupport (strcat dir "\\en"))
    (if (not (TKL:InList ld (vla-get-SupportPath (vla-get-Files (vla-get-Preferences (vlax-get-acad-object))))))
      (TKL:AddSupport ld))))

;; Tabul "TopoKit" din ribbon: meniul partial TopoKit.cuix (romana) sau
;; TopoKit_EN.cuix (engleza). Ambele au grupul de meniu "TOPOKIT"; la schimbarea
;; limbii grupul se descarca si se incarca celalalt fisier.
;; Meniul ramane incarcat de la o sesiune la alta; dupa o actualizare fisierul .cuix e altul
;; (marime / data), deci se reincarca o data pe sesiune AutoCAD (amprenta e in blackboard,
;; comuna tuturor desenelor deschise).
(defun TKL:Ribbon (dir / want mgs g cur r stamp)
  (setq want (strcat dir "\\" (if (= (TKL:Lang) "EN") "TopoKit_EN.cuix" "TopoKit.cuix")))
  (cond
    ((not (findfile want)) nil)
    (T
     (setq mgs (vla-get-MenuGroups (vlax-get-acad-object))
           g (vl-catch-all-apply 'vla-item (list mgs "TOPOKIT"))
           stamp (list (strcase (vl-filename-base want)) (vl-file-size want) (vl-file-systime want)))
     (if (vl-catch-all-error-p g) (setq g nil))
     (if g (setq cur (vl-catch-all-apply 'vla-get-MenuFileName (list g))))
     (cond
       ((and g (= (type cur) 'STR)
             (= (strcase (vl-string-translate "/" "\\" (strcat (vl-filename-directory cur) "\\" (vl-filename-base cur))))
                (strcase (vl-string-translate "/" "\\" (strcat dir "\\" (vl-filename-base want)))))
             (equal (vl-bb-ref '*TKL:CUIX*) stamp))
        T)                                                   ; acelasi fisier, deja incarcat
       (T
        (vl-bb-set '*TKL:CUIX* stamp)
        (if g (vl-catch-all-apply 'vla-Unload (list g)))
        (setq r (vl-catch-all-apply 'vlax-invoke (list mgs 'Load want)))
        (not (vl-catch-all-error-p r)))))))

;; TKL:SetLang - schimba limba si reincarca TopoKit in desenul curent
(defun TKL:SetLang (l / f fh)
  (if (setq f (TKL:LangFile))
    (progn
      (vl-mkdir (vl-filename-directory f))
      (if (setq fh (open f "w")) (progn (write-line l fh) (close fh)))))
  (vl-catch-all-apply 'vl-registry-write (list *TKL:REGKEY* "Language" l))
  (TKL:Load T)
  (princ (if (= l "EN")
           "\nTopoKit: English interface. Other open drawings switch when TopoKit is used there."
           "\nTopoKit: interfata in limba romana. Celelalte desene deschise trec la folosirea TopoKit.")))

;; TOPOKITLANG - alegerea limbii (romana / engleza)
(defun c:TOPOKITLANG (/ l k)
  (setq l (TKL:Lang))
  (initget "Romana English")
  (setq k (getkword (strcat "\nTopoKit - limba / language [Romana/English] <"
                            (if (= l "EN") "Romana" "English") ">: ")))
  (if (null k) (setq k (if (= l "EN") "Romana" "English")))
  (TKL:SetLang (if (= k "English") "EN" "RO"))
  (princ))

;; Adauga dir in locatiile de incredere (AutoCAD 2014 si ulterior)
(defun TKL:AddTrusted (dir / tp)
  (setq tp (getvar "TRUSTEDPATHS"))
  (if (and tp (not (TKL:InList dir tp)))
    (not (vl-catch-all-error-p
           (vl-catch-all-apply 'setvar
             (list "TRUSTEDPATHS" (if (= tp "") (strcat dir "\\...") (strcat tp ";" dir "\\..."))))))))

;; TKL:Stale - T daca in desen e incarcata alta versiune decat cea instalata
;; (TopoKit actualizat cu AutoCAD deschis): codul vechi din memorie nu se
;; potriveste cu dialogurile noi de pe disc, deci trebuie reincarcat
;; (sau in alta limba decat cea aleasa intre timp cu TOPOKITLANG).
;; Versiunea instalata se citeste din TopoKit.lsp de pe disc, nu din registru.
(defun TKL:FileVersion (dir / fh l n v i)
  (if (and dir (setq fh (open (strcat dir "\\TopoKit.lsp") "r")))
    (progn
      (setq n 0)
      (while (and (not v) (< n 80) (setq l (read-line fh)))
        (setq n (1+ n))
        (if (and (wcmatch l "(setq `*TK:VERSION`* \"*\")*")
                 (setq i (vl-string-search "\"" l 20)))
          (setq v (substr l 21 (- i 20)))))
      (close fh)
      v)))

(defun TKL:Stale (/ v)
  (and TK:Start
       (or (and (setq v (TKL:FileVersion (if *TKL:DIR* *TKL:DIR* (TKL:Dir))))
                (/= v (if *TK:VERSION* *TK:VERSION* "1.0.0")))
           (and *TKL:LANGLOADED* (/= *TKL:LANGLOADED* (TKL:Lang))))))

;;; --------------------------------------------------------------------------
;;;  Licenta. In pachetul construit cu licentiere (tools/build_installer.py, cand
;;;  exista installer/licensing.json) *TKL:LICENTA* este T si *TKL:CMDS* contine
;;;  comenzile modulelor. Inainte de incarcarea modulelor se ruleaza
;;;  "TopoKit.exe /license" (cod de iesire 0 = licenta buna); rezultatul bun se
;;;  pastreaza in blackboard pentru toata sesiunea AutoCAD. Fara licenta modulele
;;;  nu se incarca: comenzile TopoKit afiseaza cum se activeaza si deschid
;;;  fereastra TopoKit (acolo se introduce codul de activare).
;;;  TopoKit.exe: folderul din Contents\install.txt (scris de instalator), apoi
;;;  HKCU\Software\TopoKit\InstallDir.
;;; --------------------------------------------------------------------------
(setq *TKL:LICENTA* nil)
(setq *TKL:CMDS* nil)

(defun TKL:Exe (dir / f fh l)
  (if (and dir (setq f (findfile (strcat dir "\\install.txt"))) (setq fh (open f "r")))
    (progn (setq l (read-line fh)) (close fh)))
  (vl-some '(lambda (d)
              (if (and (= (type d) 'STR) (/= (vl-string-trim " \t" d) "")
                       (findfile (strcat (TKL:Slash (vl-string-trim " \t" d)) "\\TopoKit.exe")))
                (strcat (TKL:Slash (vl-string-trim " \t" d)) "\\TopoKit.exe")))
           (list l (vl-registry-read *TKL:REGKEY* "InstallDir"))))

;; 0 = se poate lucra; altfel codul LIC_* al lansatorului (10 = neactivat)
(defun TKL:LicCheck (dir / exe sh r)
  (cond
    ((not *TKL:LICENTA*) 0)
    ((equal (vl-bb-ref '*TKL:LIC*) 0) 0)
    ((not (setq exe (TKL:Exe dir))) 10)
    (T
     (setq sh (vl-catch-all-apply 'vlax-create-object (list "WScript.Shell")))
     (if (and sh (not (vl-catch-all-error-p sh)))
       (progn
         (setq r (vl-catch-all-apply 'vlax-invoke (list sh 'Run (strcat "\"" exe "\" /license") 0 :vlax-true)))
         (vl-catch-all-apply 'vlax-release-object (list sh))))
     (setq r (if (and r (not (vl-catch-all-error-p r)) (numberp r)) (fix r) 10))
     (if (= r 0) (vl-bb-set '*TKL:LIC* 0))
     r)))

(defun TKL:NoLicense (/ exe)
  (princ (if (= (TKL:Lang) "EN")
           "\nTopoKit is not activated on this computer. In the TopoKit window enter the activation code from the administrator."
           "\nTopoKit nu este activat pe acest calculator. In fereastra TopoKit introduceti codul de activare primit de la administrator."))
  (if (setq exe (TKL:Exe *TKL:DIR*)) (startapp exe))
  (princ))

;; comenzile TopoKit cat timp licenta lipseste
(defun TKL:Stubs ()
  (foreach c *TKL:CMDS*
    (eval (list 'defun (read (strcat "C:" c)) '() '(TKL:NoLicense)))))

(defun TKL:Load (force / dir ldir r)
  (cond
    ((not (setq dir (TKL:Dir)))
     (princ "\nTopoKit: nu gasesc TopoKit.lsp. Reinstalati TopoKit (TopoKitSetup.exe).")
     nil)
    ((progn
       (vl-catch-all-apply 'TKL:AddSupport (list dir))
       (vl-catch-all-apply 'TKL:AddTrusted (list dir))
       (vl-catch-all-apply 'TKL:LangSupport (list dir))
       (setq *TKL:DIR* dir)
       (/= (TKL:LicCheck dir) 0))
     (TKL:Stubs)
     (princ (if (= (TKL:Lang) "EN")
              "\nTopoKit: not activated on this computer - open the TopoKit window to activate it."
              "\nTopoKit: neactivat pe acest calculator - deschideti fereastra TopoKit pentru activare."))
     (vl-catch-all-apply 'TKL:Ribbon (list dir))
     nil)
    (T
     (if (and (not force) (TKL:Stale))
       (progn
         (princ "\nTopoKit: versiune sau limba noua - se reincarca modulele.")
         (setq force T)))
     (if force (setq TK:Start nil TKA:Generate nil TKT:Menu nil TKI:Run nil c:TKDETASARE nil c:TKPROIECT nil))
     (setq *TKL:DIR* dir ldir (TKL:LangDir dir))
     (if (or force (not TK:Start))
       (setq r (vl-catch-all-apply 'load (list (strcat ldir "\\TopoKit.lsp")))
             *TKL:LANGLOADED* (TKL:Lang)))
     (cond
       ((vl-catch-all-error-p r)
        (princ (strcat "\nTopoKit: eroare la incarcare - " (vl-catch-all-error-message r)))
        nil)
       ;; meniul ribbon la sfarsit: incarcarea unui .cuix opreste expresia LISP in curs
       (T (TKL:Mark) (vl-catch-all-apply 'TKL:Ribbon (list dir)) T)))))

;; Marcaj pentru lansatorul TopoKit.exe (raportul de diagnostic): unde si cand
;; s-a incarcat TopoKit ultima data
(defun TKL:Mark ()
  (vl-catch-all-apply 'vl-registry-write
    (list *TKL:REGKEY* "LoadedIn"
          (strcat "TopoKit " (if *TK:VERSION* *TK:VERSION* "?") " / "
                  (vl-princ-to-string (getvar "PRODUCT")) " " (vl-princ-to-string (getvar "ACADVER"))
                  " - " (vl-princ-to-string (getvar "DWGNAME")))))
  (vl-catch-all-apply 'vl-registry-write
    (list *TKL:REGKEY* "LoadedAt" (rtos (getvar "CDATE") 2 6))))

(defun c:TOPOKITRELOAD ()
  (if (TKL:Load T) (princ "\nTopoKit reincarcat."))
  (princ))

(if (TKL:Load nil)
  (princ (strcat "\nTopoKit " *TK:VERSION* " pregatit: TOPOKIT (meniu), ANEXE (Ordin 600/2023), "
                 "TOPOTEREN (teren, TIN, volume), INCLINARE.")))
(princ)
