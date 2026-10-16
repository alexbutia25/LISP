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
;;;   - incarca TopoKit.lsp (care incarca TopoKitAnexe.lsp si TopoKitTeren.lsp).
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

;; Adauga dir in locatiile de incredere (AutoCAD 2014 si ulterior)
(defun TKL:AddTrusted (dir / tp)
  (setq tp (getvar "TRUSTEDPATHS"))
  (if (and tp (not (TKL:InList dir tp)))
    (not (vl-catch-all-error-p
           (vl-catch-all-apply 'setvar
             (list "TRUSTEDPATHS" (if (= tp "") (strcat dir "\\...") (strcat tp ";" dir "\\..."))))))))

(defun TKL:Load (force / dir r)
  (cond
    ((not (setq dir (TKL:Dir)))
     (princ "\nTopoKit: nu gasesc TopoKit.lsp. Reinstalati TopoKit (TopoKitSetup.exe).")
     nil)
    (T
     (vl-catch-all-apply 'TKL:AddSupport (list dir))
     (vl-catch-all-apply 'TKL:AddTrusted (list dir))
     (if force (setq TK:Start nil TKA:Generate nil TKT:Menu nil))
     (setq *TKL:DIR* dir)
     (if (or force (not TK:Start))
       (setq r (vl-catch-all-apply 'load (list (strcat dir "\\TopoKit.lsp")))))
     (cond
       ((vl-catch-all-error-p r)
        (princ (strcat "\nTopoKit: eroare la incarcare - " (vl-catch-all-error-message r)))
        nil)
       (T T)))))

(defun c:TOPOKITRELOAD ()
  (if (TKL:Load T) (princ "\nTopoKit reincarcat."))
  (princ))

(if (TKL:Load nil)
  (princ "\nTopoKit pregatit: TOPOKIT (meniu), ANEXE (Ordin 600/2023), TOPOTEREN (teren, TIN, volume)."))
(princ)
