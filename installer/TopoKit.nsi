; ==========================================================================
; TopoKit.nsi - instalatorul TopoKit (TopoKitSetup.exe), NSIS 3
;
; Se compileaza cu tools/build_installer.py, care pregateste folderul STAGE:
;   STAGE\bundle\TopoKit.bundle\...   pachetul AutoCAD (PackageContents.xml + Contents)
;   STAGE\app\...                     TopoKit.exe (lansatorul), README.html, docs
;
; Instalare pentru utilizatorul curent (fara drepturi de administrator):
;   %APPDATA%\Autodesk\ApplicationPlugins\TopoKit.bundle   incarcat automat de AutoCAD
;   %LOCALAPPDATA%\Programs\TopoKit                        lansatorul din bara de sistem
; Instalare silentioasa: TopoKitSetup.exe /S   (dezinstalare: Uninstall.exe /S)
;   /S cu AutoCAD deschis: meniul .cuix blocat ramane in versiunea veche (jurnal: %LOCALAPPDATA%\TopoKit\install.log)
; ==========================================================================
Unicode true
ManifestDPIAware true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "WinMessages.nsh"
!include "FileFunc.nsh"

!ifndef VERSION
  !define VERSION "1.11.0"
!endif
!ifndef STAGE
  !error "Compilati cu tools/build_installer.py (definește STAGE)"
!endif
!ifndef OUTFILE
  !define OUTFILE "TopoKitSetup-${VERSION}.exe"
!endif

!define APP       "TopoKit"
!define BUNDLE    "$APPDATA\Autodesk\ApplicationPlugins\TopoKit.bundle"
!define REGAPP    "Software\TopoKit"
!define REGUNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\TopoKit"
!define REGRUN    "Software\Microsoft\Windows\CurrentVersion\Run"
!define WNDCLASS  "TopoKitLauncherWnd"
; lista fisierelor instalate in $INSTDIR (dezinstalarea sterge doar aceste fisiere)
!define MANIFEST  "TopoKit.installed"
; foldere temporare cu fisierele noi (langa destinatie: mutarea e o redenumire)
!define STGNAME   "~TopoKit-update.tmp"
!define BUNDLESTG "$APPDATA\Autodesk\ApplicationPlugins\~TopoKit-update.tmp"
!ifndef TKLOG
  !define TKLOG   "$LOCALAPPDATA\TopoKit\install.log"
!endif
; folderul implicit (facut de instalator): la o instalare veche fara lista, doar aici fisierele existente
; sunt considerate ale TopoKit (LegacyOwned)
!ifndef DEFDIR
  !define DEFDIR  "$LOCALAPPDATA\Programs\TopoKit"
!endif

Name "${APP} ${VERSION}"
OutFile "${OUTFILE}"
RequestExecutionLevel user
InstallDir "${DEFDIR}"
InstallDirRegKey HKCU "${REGAPP}" "InstallDir"
SetCompressor /SOLID lzma
BrandingText "${APP} ${VERSION}"
ShowInstDetails show

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1048 "ProductName" "${APP}"
VIAddVersionKey /LANG=1048 "FileDescription" "Instalare ${APP} pentru AutoCAD"
VIAddVersionKey /LANG=1048 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1048 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1048 "CompanyName" "${APP}"
VIAddVersionKey /LANG=1048 "LegalCopyright" "${APP}"

!define MUI_ICON   "${STAGE}\app\topokit.ico"
!define MUI_UNICON "${STAGE}\app\topokit.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEFINISHPAGE_BITMAP   "${STAGE}\art\welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${STAGE}\art\welcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP         "${STAGE}\art\header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP       "${STAGE}\art\header.bmp"
!define MUI_COMPONENTSPAGE_SMALLDESC

!define MUI_WELCOMEPAGE_TITLE "Instalare ${APP} ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "${APP} adaugă în AutoCAD instrumente de topografie și cadastru:$\r$\n$\r$\n\
  • conversie Stereo 70 / WGS84 (grila ANCPI) și export KMZ$\r$\n\
  • anexele Ordinului ANCPI nr. 600/2023 (planuri, Word, PDF)$\r$\n\
  • puncte, TIN, curbe de nivel, volume, georeferențiere$\r$\n$\r$\n\
După instalare, ${APP} se încarcă automat în AutoCAD 2013 sau mai nou. \
Fereastra ${APP} arată conexiunea cu AutoCAD și deschide modulele cu un clic; lansatorul rămâne în fundal (iconița de lângă ceas).$\r$\n$\r$\n\
Nu sunt necesare drepturi de administrator."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
; doar un folder gol / nou sau unul TopoKit (vezi DirKind); un folder cu sursele proiectului (.git)
; doar daca TopoKit e deja instalat acolo. Dezinstalarea sterge doar fisierele din lista ${MANIFEST}.
!define MUI_DIRECTORYPAGE_TEXT_TOP "Alegeți un folder nou (gol) sau folderul în care TopoKit este deja instalat. Un folder cu sursele TopoKit (.git) se poate alege doar dacă TopoKit este deja instalat acolo."
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "${APP} este instalat"
!define MUI_FINISHPAGE_TEXT "${APP} se încarcă automat în fiecare desen AutoCAD (comenzile TOPOKIT, ANEXE, TOPOTEREN).$\r$\n$\r$\n\
Dacă AutoCAD este deja deschis, alegeți o comandă din iconița ${APP} de lângă ceas sau reporniți AutoCAD."
!define MUI_FINISHPAGE_RUN "$INSTDIR\TopoKit.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Deschide ${APP} acum"
; la final se deschide pagina cu toate functiile programului (bifat implicit)
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\Functii.html"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Arată toate funcțiile ${APP}"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Romanian"

; Inchide lansatorul care ruleaza (actualizare / dezinstalare) si asteapta sa dispara (max. ~5 s)
!macro CloseLauncher
  FindWindow $0 "${WNDCLASS}"
  ${If} $0 <> 0
    SendMessage $0 ${WM_CLOSE} 0 0 /TIMEOUT=3000
    StrCpy $1 0
    ${Do}
      Sleep 250
      IntOp $1 $1 + 1
      FindWindow $0 "${WNDCLASS}"
      ${IfThen} $1 >= 20 ${|} ${ExitDo} ${|}
    ${LoopUntil} $0 = 0
    Sleep 300
  ${EndIf}
!macroend

; >>> TKFILES ---------------------------------------------------------------
; Fisierele instalate. Instalarea scrie in $INSTDIR\${MANIFEST} lista fisierelor puse de ea (cai
; relative, UTF-16LE, cate una pe rand); dezinstalarea sterge exact aceste fisiere si apoi doar
; folderele ramase goale. Un folder nu se sterge niciodata cu tot ce contine (RMDir /r): $INSTDIR
; poate fi si o copie a proiectului (D:\TopoKit cu .git, docs, tools...).
; Actualizarea: fisierele noi se despacheteaza intai intr-un folder temporar langa destinatie
; (${STGNAME}); abia dupa ce toate au fost scrise se inlocuiesc cele vechi, fisier cu fisier.
; Un fisier existent care nu e in lista versiunii vechi (al utilizatorului / al proiectului) nu se
; suprascrie si nu intra in lista.
Var Stg       ; folderul temporar cu fisierele noi
Var Dst       ; destinatia ($INSTDIR sau pachetul AutoCAD)
Var Mf        ; lista noua (handle) sau ""
Var Own       ; fisier existent la destinatie: all = al nostru (pachetul), none = strain (exista lista),
              ; legacy = fara lista (versiuni <= 1.10.0), vezi LegacyOwned
Var Repo      ; 1 = $INSTDIR contine sursele proiectului (.git / installer\TopoKit.nsi)
Var Legacy    ; 1 = fara lista de fisiere (instalare veche)
Var DefDir    ; 1 = $INSTDIR e folderul implicit ${DEFDIR}
Var Kept      ; fisiere straine lasate neatinse
Var Locked    ; fisiere blocate care au ramas in versiunea veche (doar /S sau "Ignorare")

; jurnal (DetailPrint nu se vede la /S): stiva = textul
!macro TK_LOG_FUNC UN
Function ${UN}LogLine
  Exch $R0
  Push $R1
  DetailPrint "$R0"
  ${GetParent} "${TKLOG}" $R1
  CreateDirectory "$R1"
  ClearErrors
  FileOpen $R1 "${TKLOG}" a
  ${IfNot} ${Errors}
    FileSeek $R1 0 END
    FileWrite $R1 "${APP} ${VERSION}: $R0$\r$\n"
    FileClose $R1
  ${EndIf}
  Pop $R1
  Pop $R0
  ClearErrors
FunctionEnd
!macroend
!insertmacro TK_LOG_FUNC ""
!insertmacro TK_LOG_FUNC "un."

!macro TK_COMMON UN
; $R0 = cale relativa din lista; eroare daca nu e o cale simpla sub destinatie
; (fara "..", ":", "*", "?" - Delete accepta mascari -, fara "\" / "/" la inceput)
Function ${UN}RelOk
  Push $R1
  Push $R2
  Push $R3
  ClearErrors
  StrCpy $R1 $R0 1
  ${If} $R0 == ""
  ${OrIf} $R1 == "\"
  ${OrIf} $R1 == "/"
    Goto relok_bad
  ${EndIf}
  StrCpy $R2 0
  ${Do}
    StrCpy $R1 $R0 2 $R2
    ${IfThen} $R1 == "" ${|} ${ExitDo} ${|}
    StrCpy $R3 $R1 1
    ${If} $R1 == ".."
    ${OrIf} $R3 == ":"
    ${OrIf} $R3 == "*"
    ${OrIf} $R3 == "?"
      Goto relok_bad
    ${EndIf}
    IntOp $R2 $R2 + 1
  ${Loop}
  Goto relok_end
  relok_bad:
  Pop $R3
  Pop $R2
  Pop $R1
  SetErrors
  Return
  relok_end:
  Pop $R3
  Pop $R2
  Pop $R1
  ClearErrors
FunctionEnd

; $R0 fara CR/LF la sfarsit
Function ${UN}TrimEol
  Push $R1
  ${Do}
    StrCpy $R1 $R0 1 -1
    ${If} $R1 == "$\r"
    ${OrIf} $R1 == "$\n"
      StrCpy $R0 $R0 -1
    ${Else}
      ${ExitDo}
    ${EndIf}
  ${Loop}
  Pop $R1
FunctionEnd

; dupa stergerea fisierului $Dst\$R0: folderele lui, doar daca au ramas goale (RMDir fara /r)
Function ${UN}RmParents
  Push $R1
  StrCpy $R1 $R0
  ${Do}
    ${GetParent} "$R1" $R1
    ${IfThen} $R1 == "" ${|} ${ExitDo} ${|}
    ClearErrors
    RMDir "$Dst\$R1"
    ${IfThen} ${Errors} ${|} ${ExitDo} ${|}
  ${Loop}
  Pop $R1
  ClearErrors
FunctionEnd

; Fisierul $R0 e folosit de un program care ruleaza ($R1 = numele lui)? Un .exe pornit nu se poate
; deschide pentru scriere. Se verifica INAINTE de orice stergere. Blocaje scurte (antivirus,
; indexare): se reincearca singur ~2 s (la /S ~10 s). Apoi: interactiv Reincercare / Anulare;
; /S: $R2 = 1 (meniul .cuix tinut deschis de AutoCAD) -> fisierul ramane in versiunea veche, se
; noteaza in jurnal si instalarea continua; altfel se renunta (codul de iesire 2).
Function ${UN}WaitUnlocked
  ${IfNot} ${FileExists} "$R0"
    Return
  ${EndIf}
  StrCpy $R3 0
  ${Do}
    ClearErrors
    FileOpen $0 "$R0" a
    ${IfNot} ${Errors}
      FileClose $0
      ${ExitDo}
    ${EndIf}
    IntOp $R3 $R3 + 1
    StrCpy $R4 8
    ${IfThen} ${Silent} ${|} StrCpy $R4 40 ${|}
    ${If} $R3 < $R4
      Sleep 250
      ${Continue}
    ${EndIf}
    ${If} ${Silent}
      ${If} $R2 == 1
        IntOp $Locked $Locked + 1
        Push "$R1 este deschis: fișierul rămâne în versiunea veche ($R0)."
        Call ${UN}LogLine
        ${ExitDo}
      ${EndIf}
      Push "$R1 este deschis: operația a fost anulată ($R0)."
      Call ${UN}LogLine
    ${EndIf}
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$R1 este deschis.$\r$\n$\r$\nÎnchideți-l (salvați lucrul) și apăsați Reîncercare.$\r$\n$\r$\n$R0" \
      /SD IDCANCEL IDRETRY wu_retry
    Abort "$R1 este deschis: operația a fost anulată."
    wu_retry:
    StrCpy $R3 0
  ${Loop}
  ClearErrors
FunctionEnd
!macroend
!insertmacro TK_COMMON ""
!insertmacro TK_COMMON "un."

; $R0 = folder existent: $R1 = "ok" daca are doar ce ramane dupa dezinstalare (fisiere care nu sunt in
; lista): setarile Plan Inclinare (PlanInclinare\*.json), listele ${MANIFEST}*, jurnale *.log, folderul
; temporar ${STGNAME}; altfel "bad"
Function DirLeftovers
  Push $R4
  Push $R5
  Push $R6
  Push $R7
  Push $R8
  StrCpy $R1 "ok"
  ClearErrors
  FindFirst $R4 $R5 "$R0\*.*"
  ${DoWhile} $R5 != ""
    StrCpy $R6 $R5 17
    StrCpy $R7 $R5 "" -4
    ${If} $R5 == "."
    ${OrIf} $R5 == ".."
      ; nimic
    ${ElseIf} $R5 == "PlanInclinare"
    ${AndIf} ${FileExists} "$R0\$R5\*.*"
      FindFirst $R6 $R7 "$R0\$R5\*.*"
      ${DoWhile} $R7 != ""
        StrCpy $R8 $R7 "" -5
        ${If} $R7 == "."
        ${OrIf} $R7 == ".."
          ; nimic
        ${ElseIf} $R8 != ".json"
        ${OrIf} ${FileExists} "$R0\$R5\$R7\*.*"
          StrCpy $R1 "bad"
          ${ExitDo}
        ${EndIf}
        FindNext $R6 $R7
      ${Loop}
      FindClose $R6
    ${ElseIf} $R6 == "${MANIFEST}"
    ${OrIf} $R5 == "${STGNAME}"
    ${OrIf} $R7 == ".log"
      ; rest al TopoKit
    ${Else}
      StrCpy $R1 "bad"
    ${EndIf}
    ${IfThen} $R1 == "bad" ${|} ${ExitDo} ${|}
    FindNext $R4 $R5
  ${Loop}
  FindClose $R4
  Pop $R8
  Pop $R7
  Pop $R6
  Pop $R5
  Pop $R4
  ClearErrors
FunctionEnd

; Folderul de instalare (stiva: folderul -> "ok" | "repo" | "bad"):
;   ok   = inexistent / gol / cu TopoKit.exe (fara surse) / folderul implicit ${DEFDIR} / folderul
;          inregistrat (HKCU\Software\TopoKit InstallDir) / unul cu doar resturile unei dezinstalari
;          (DirLeftovers: de ex. setarile Plan Inclinare - reinstalarea in acelasi folder);
;   repo = contine sursele proiectului (.git sau installer\TopoKit.nsi) SI TopoKit e deja instalat
;          exact acolo (HKCU\Software\TopoKit InstallDir): se accepta, ca actualizare;
;   bad  = orice altceva (Documente, C:\, un folder cu surse in care TopoKit nu e instalat).
; Un folder acceptat nu pierde nimic: se scriu / sterg doar fisierele din lista ${MANIFEST}, iar fara
; lista, in afara folderului implicit, doar caile instalatorului (LegacyOwned).
Function DirKind
  Exch $R0
  Push $R1
  Push $R2
  Push $R3
  ${Do}
    StrCpy $R1 $R0 1 -1
    ${IfThen} $R1 != "\" ${|} ${ExitDo} ${|}
    StrCpy $R0 $R0 -1
  ${Loop}
  ReadRegStr $R2 HKCU "${REGAPP}" "InstallDir"
  ${Do}
    StrCpy $R3 $R2 1 -1
    ${IfThen} $R3 != "\" ${|} ${ExitDo} ${|}
    StrCpy $R2 $R2 -1
  ${Loop}
  StrCpy $R1 "bad"
  ${If} $R0 == ""
    ; nimic
  ${ElseIf} ${FileExists} "$R0\.git"
  ${OrIf} ${FileExists} "$R0\installer\TopoKit.nsi"
    ${If} $R2 != ""
    ${AndIf} $R2 == $R0
      StrCpy $R1 "repo"
    ${EndIf}
  ${ElseIf} ${FileExists} "$R0\TopoKit.exe"
    StrCpy $R1 "ok"
  ${ElseIf} $R0 == "${DEFDIR}"
    StrCpy $R1 "ok"
  ${ElseIf} $R2 != ""
  ${AndIf} $R2 == $R0
    StrCpy $R1 "ok"
  ${Else}
    Call DirLeftovers
  ${EndIf}
  StrCpy $R0 $R1
  Pop $R3
  Pop $R2
  Pop $R1
  Exch $R0
  ClearErrors
FunctionEnd

; $R0 = cale relativa: o adauga in lista noua
Function Record
  ${If} $Mf != ""
    FileWriteUTF16LE $Mf "$R0$\r$\n"
  ${EndIf}
FunctionEnd

; Fara lista (versiuni <= 1.10.0): un fisier existent e al TopoKit doar in folderul implicit ${DEFDIR}
; fara surse (folder facut de instalator). In orice alt folder (ales de utilizator, poate cu fisierele
; lui) sau intr-unul cu surse: doar caile pe care le pune instalatorul si pe care proiectul nu le are -
; lansatorul, paginile generate, modules\ si PlanInclinare\ (docs\ poate fi al proiectului / al lui).
; $R0 = cale relativa -> $R1 = 1 / 0
Function LegacyOwned
  Push $R2
  StrCpy $R1 1
  ${If} $Repo == 1
  ${OrIf} $DefDir != 1
    StrCpy $R1 0
    StrCpy $R2 $R0 8
    ${If} $R2 == "modules\"
      StrCpy $R1 1
    ${EndIf}
    StrCpy $R2 $R0 14
    ${If} $R2 == "PlanInclinare\"
      StrCpy $R1 1
    ${EndIf}
    ${If} $R0 == "TopoKit.exe"
    ${OrIf} $R0 == "topokit.ico"
    ${OrIf} $R0 == "README.html"
    ${OrIf} $R0 == "Functii.html"
    ${OrIf} $R0 == "Functii_EN.html"
      StrCpy $R1 1
    ${EndIf}
  ${EndIf}
  Pop $R2
FunctionEnd

; $Stg\$R0 -> $Dst\$R0 (inlocuieste fisierul vechi). Fisier vechi blocat: reincercare automata
; ~2 s (/S ~10 s), apoi interactiv Abandon / Reincercare / Ignorare; /S sau Ignorare = ramane
; versiunea veche (in jurnal), fisierul ramane in lista.
Function MoveOne
  Push $R1
  Push $R2
  ${GetParent} "$Dst\$R0" $R1
  CreateDirectory "$R1"
  ${If} ${FileExists} "$Dst\$R0"
    StrCpy $R2 0
    ${Do}
      ClearErrors
      Delete "$Dst\$R0"
      ${IfNot} ${Errors}
        ${ExitDo}
      ${EndIf}
      SetFileAttributes "$Dst\$R0" NORMAL
      IntOp $R2 $R2 + 1
      ${If} $R2 < 8
        Sleep 250
        ${Continue}
      ${EndIf}
      ${If} ${Silent}
      ${AndIf} $R2 < 40
        Sleep 250
        ${Continue}
      ${EndIf}
      MessageBox MB_ABORTRETRYIGNORE|MB_ICONEXCLAMATION "Fișierul este folosit de alt program:$\r$\n$\r$\n$Dst\$R0$\r$\n$\r$\n\
        Închideți programul și apăsați Reîncercare (Ignorare = rămâne versiunea veche a acestui fișier)." \
        /SD IDIGNORE IDRETRY mo_retry IDIGNORE mo_keep
      Abort "Fișier folosit de alt program: $Dst\$R0"
      mo_retry:
      StrCpy $R2 0
      ${Continue}
      mo_keep:
      IntOp $Locked $Locked + 1
      Push "Fișier blocat, rămâne versiunea veche: $Dst\$R0"
      Call LogLine
      Delete "$Stg\$R0"
      Pop $R2
      Pop $R1
      ClearErrors
      Return
    ${Loop}
  ${EndIf}
  ClearErrors
  Rename "$Stg\$R0" "$Dst\$R0"
  ${If} ${Errors}
    ClearErrors
    CopyFiles /SILENT "$Stg\$R0" "$Dst\$R0"
    ${If} ${Errors}
      Push "Nu s-a putut scrie $Dst\$R0"
      Call LogLine
      Abort "Nu s-a putut scrie $Dst\$R0"
    ${EndIf}
    Delete "$Stg\$R0"
  ${EndIf}
  Pop $R2
  Pop $R1
  ClearErrors
FunctionEnd

; ${Locate} in $Stg: fisierele noi ramase dupa ApplyList (nu erau in lista versiunii vechi)
Function MoveNew
  StrLen $R1 "$Stg\"
  StrCpy $R0 $R9 "" $R1
  StrCpy $R1 1
  ${If} ${FileExists} "$Dst\$R0"
    ${If} $Own == "none"
      StrCpy $R1 0
    ${ElseIf} $Own == "legacy"
      Call LegacyOwned
    ${EndIf}
  ${EndIf}
  ${If} $R1 == 1
    Call MoveOne
    Call Record
  ${Else}
    DetailPrint "Păstrat (nu a fost instalat de ${APP}): $Dst\$R0"
    Delete "$R9"
    IntOp $Kept $Kept + 1
  ${EndIf}
  ClearErrors
  Push "go"
FunctionEnd

; ${Locate} in $Dst\modules (instalare veche, fara lista): fisierele build-ului Nuitka vechi pe care
; versiunea noua nu le mai are (DLL-uri / .pyd ramase)
Function DropStale
  StrLen $R1 "$Dst\"
  StrCpy $R0 $R9 "" $R1
  ${IfNot} ${FileExists} "$Stg\$R0"
    Delete "$R9"
  ${EndIf}
  ClearErrors
  Push "go"
FunctionEnd

; Lista versiunii vechi $R8. $R7 = 1: fisierele ei pe care versiunea noua nu le mai are se sterg;
; $R7 = 2: cele pe care le are se inlocuiesc. (Doua treceri: o linie repetata nu poate sterge un
; fisier abia instalat.)
Function ApplyList
  Push $R6
  ClearErrors
  FileOpen $R6 "$R8" r
  ${If} ${Errors}
    Pop $R6
    ClearErrors
    Return
  ${EndIf}
  ${Do}
    ClearErrors
    FileReadUTF16LE $R6 $R0
    ${IfThen} ${Errors} ${|} ${ExitDo} ${|}
    Call TrimEol
    Call RelOk
    ${IfThen} ${Errors} ${|} ${Continue} ${|}
    ${If} $R7 == 1
      ${IfNot} ${FileExists} "$Stg\$R0"
      ${AndIf} ${FileExists} "$Dst\$R0"
        ClearErrors
        Delete "$Dst\$R0"
        ${If} ${Errors}
          Push "Nu s-a putut șterge (rămâne în listă): $Dst\$R0"
          Call LogLine
          Call Record
        ${Else}
          Call RmParents
        ${EndIf}
      ${EndIf}
    ${ElseIf} ${FileExists} "$Stg\$R0"
      Call MoveOne
      Call Record
    ${EndIf}
  ${Loop}
  FileClose $R6
  Pop $R6
  ClearErrors
FunctionEnd

; $DefDir = 1 daca $INSTDIR e folderul implicit ${DEFDIR}
Function CheckDefDir
  Push $R0
  StrCpy $DefDir 0
  StrCpy $R0 "$INSTDIR"
  ${Do}
    StrCpy $DefDir $R0 1 -1
    ${IfThen} $DefDir != "\" ${|} ${ExitDo} ${|}
    StrCpy $R0 $R0 -1
  ${Loop}
  StrCpy $DefDir 0
  ${IfThen} $R0 == "${DEFDIR}" ${|} StrCpy $DefDir 1 ${|}
  Pop $R0
FunctionEnd

; Programul: $Stg (despachetat complet) -> $INSTDIR, cu lista $INSTDIR\${MANIFEST}
Function AppApply
  StrCpy $Dst "$INSTDIR"
  StrCpy $Kept 0
  Call CheckDefDir
  ; lista unei instalari intrerupte (.new) se pastreaza ca .prev: si fisierele ei sunt ale noastre
  ${If} ${FileExists} "$Dst\${MANIFEST}.new"
    Delete "$Dst\${MANIFEST}.prev"
    Rename "$Dst\${MANIFEST}.new" "$Dst\${MANIFEST}.prev"
  ${EndIf}
  StrCpy $Legacy 1
  ${If} ${FileExists} "$Dst\${MANIFEST}"
  ${OrIf} ${FileExists} "$Dst\${MANIFEST}.prev"
    StrCpy $Legacy 0
  ${EndIf}
  ClearErrors
  FileOpen $Mf "$Dst\${MANIFEST}.new" w
  ${If} ${Errors}
    StrCpy $Mf ""
    Push "Nu se poate scrie $Dst\${MANIFEST}.new"
    Call LogLine
    Abort "Nu se poate scrie $Dst\${MANIFEST}.new"
  ${EndIf}
  StrCpy $R7 1
  StrCpy $R8 "$Dst\${MANIFEST}"
  Call ApplyList
  StrCpy $R8 "$Dst\${MANIFEST}.prev"
  Call ApplyList
  StrCpy $R7 2
  StrCpy $R8 "$Dst\${MANIFEST}"
  Call ApplyList
  StrCpy $R8 "$Dst\${MANIFEST}.prev"
  Call ApplyList
  ${If} $Legacy == 1
    StrCpy $Own "legacy"
    ${If} ${FileExists} "$Dst\modules\DWGtoKMZ.exe"
      ${Locate} "$Dst\modules" "/L=F /G=1" "DropStale"
    ${EndIf}
  ${Else}
    StrCpy $Own "none"
  ${EndIf}
  ${Locate} "$Stg" "/L=F /G=1" "MoveNew"
  FileClose $Mf
  StrCpy $Mf ""
  RMDir /r "$Stg"                     ; doar folderul temporar al instalatorului (acum fara fisiere)
  Delete "$Dst\${MANIFEST}"
  Rename "$Dst\${MANIFEST}.new" "$Dst\${MANIFEST}"
  Delete "$Dst\${MANIFEST}.prev"
  ${If} $Kept > 0
    Push "$Kept fișiere existente în $Dst nu au fost instalate de ${APP}: au rămas neschimbate."
    Call LogLine
  ${EndIf}
  ClearErrors
FunctionEnd

; Pachetul AutoCAD (doar al TopoKit, cale fixa): $Stg (despachetat complet) -> $Dst. Vechiul pachet
; se sterge abia acum; un fisier blocat (meniul .cuix cu AutoCAD deschis, /S) ramane cel vechi.
Function BundleApply
  RMDir /r "$Dst"
  ClearErrors
  ${IfNot} ${FileExists} "$Dst\*.*"
    Rename "$Stg" "$Dst"
    ${IfNot} ${Errors}
      Return
    ${EndIf}
  ${EndIf}
  StrCpy $Mf ""
  StrCpy $Own "all"
  ${Locate} "$Stg" "/L=F /G=1" "MoveNew"
  RMDir /r "$Stg"
  ClearErrors
FunctionEnd

; Dezinstalare: fisierele din lista $R8, apoi folderele lor ramase goale
Function un.RemoveList
  Push $R6
  ClearErrors
  FileOpen $R6 "$R8" r
  ${If} ${Errors}
    Pop $R6
    ClearErrors
    Return
  ${EndIf}
  ${Do}
    ClearErrors
    FileReadUTF16LE $R6 $R0
    ${IfThen} ${Errors} ${|} ${ExitDo} ${|}
    Call un.TrimEol
    Call un.RelOk
    ${IfThen} ${Errors} ${|} ${Continue} ${|}
    Delete "$Dst\$R0"
    Call un.RmParents
  ${Loop}
  FileClose $R6
  Pop $R6
  ClearErrors
FunctionEnd
; <<< TKFILES ---------------------------------------------------------------

!macro CheckClosed UN FILE NAME SKIP
  StrCpy $R0 "${FILE}"
  StrCpy $R1 "${NAME}"
  StrCpy $R2 "${SKIP}"
  Call ${UN}WaitUnlocked
!macroend

!macro CheckAllClosed UN
  !insertmacro CheckClosed "${UN}" "$INSTDIR\TopoKit.exe" "Lansatorul ${APP}" 0
  !insertmacro CheckClosed "${UN}" "$INSTDIR\PlanInclinare\PlanInclinare.exe" "Plan Înclinare" 0
  !insertmacro CheckClosed "${UN}" "$INSTDIR\modules\DWGtoKMZ.exe" "DWG to KMZ" 0
  !insertmacro CheckClosed "${UN}" "${BUNDLE}\Contents\TopoKit.cuix" "AutoCAD (cu meniul ${APP})" 1
  !insertmacro CheckClosed "${UN}" "${BUNDLE}\Contents\TopoKit_EN.cuix" "AutoCAD (cu meniul ${APP})" 1
!macroend

; Folderul ales (pagina "Folder"): vezi DirKind. Abort = butonul "Înainte" dezactivat.
Function .onVerifyInstDir
  Push $0
  Push "$INSTDIR"
  Call DirKind
  Pop $0
  ${If} $0 == "bad"
    Pop $0
    Abort
  ${EndIf}
  Pop $0
FunctionEnd

Section "${APP} pentru AutoCAD (obligatoriu)" SecMain
  SectionIn RO
  ; aceeasi verificare si la /S (acolo pagina "Folder" lipseste: /D=... sau InstallDir din registru)
  Push "$INSTDIR"
  Call DirKind
  Pop $0
  StrCpy $Repo 0
  ${If} $0 == "bad"
    MessageBox MB_OK|MB_ICONSTOP "Folderul $INSTDIR nu poate fi folosit pentru ${APP}.$\r$\n$\r$\n\
      Alegeți un folder nou (gol) sau folderul în care ${APP} este deja instalat." /SD IDOK
    Push "Folder refuzat: $INSTDIR"
    Call LogLine
    Abort "Folder refuzat: $INSTDIR"
  ${ElseIf} $0 == "repo"
    StrCpy $Repo 1
    DetailPrint "$INSTDIR conține și sursele ${APP}: se actualizează doar fișierele instalate de ${APP}."
    MessageBox MB_OKCANCEL|MB_ICONINFORMATION "Folderul $INSTDIR conține și sursele ${APP} (.git / installer).$\r$\n$\r$\n\
      Se actualizează doar fișierele instalate de ${APP} (TopoKit.exe, modules, PlanInclinare, paginile de ajutor). \
      Fișierele proiectului nu se suprascriu și nu se șterg, nici la dezinstalare." /SD IDOK IDOK +2
    Abort "Instalare anulată."
  ${EndIf}

  !insertmacro CloseLauncher
  StrCpy $Locked 0
  !insertmacro CheckAllClosed ""

  ; 1) fisierele noi se despacheteaza complet in foldere temporare; instalarea veche ramane intreaga
  ;    pana aici (spatiu lipsa / eroare = nimic schimbat). Folderele temporare sunt ale instalatorului
  ;    (nume fix); unul ramas de la o instalare intrerupta se sterge.
  RMDir /r "${BUNDLESTG}"
  RMDir /r "$INSTDIR\${STGNAME}"
  SetOutPath "${BUNDLESTG}"
  File /r "${STAGE}\bundle\TopoKit.bundle\*.*"
  SetOutPath "$INSTDIR\${STGNAME}"
  File "${STAGE}\app\TopoKit.exe"
  File "${STAGE}\app\topokit.ico"
  File "${STAGE}\app\README.html"
  File "${STAGE}\app\Functii.html"
  File "${STAGE}\app\Functii_EN.html"
  SetOutPath "$INSTDIR\${STGNAME}\docs"
  File /r "${STAGE}\app\docs\*.*"
  ; programul Plan Inclinare (calcul inclinatie); setarile utilizatorului (nu sunt in lista) raman
  SetOutPath "$INSTDIR\${STGNAME}\PlanInclinare"
  File /r "${STAGE}\app\PlanInclinare\*.*"
  ; modulul DWG to KMZ (se deschide din TopoKit, nu are scurtatura proprie)
  SetOutPath "$INSTDIR\${STGNAME}\modules"
  File /r "${STAGE}\app\modules\*.*"
  SetOutPath "$INSTDIR"                 ; folderul curent nu poate fi mutat / sters
  ${GetSize} "$INSTDIR\${STGNAME}" "/S=0K" $5 $1 $2
  ${GetSize} "${BUNDLESTG}" "/S=0K" $3 $1 $2
  IntOp $5 $5 + $3

  ; 2) pachetul AutoCAD (Autoloader)
  StrCpy $Stg "${BUNDLESTG}"
  StrCpy $Dst "${BUNDLE}"
  Call BundleApply

  ; 3) lansatorul, documentatia, modulele: doar fisierele instalatorului (lista ${MANIFEST})
  Call CheckDefDir
  ${If} $Repo == 0
  ${AndIf} $DefDir == 1
  ${AndIfNot} ${FileExists} "$INSTDIR\${MANIFEST}"
    ; versiunea veche a convertorului (1.1.0), doar in folderul implicit (facut de instalator)
    RMDir /r "$INSTDIR\Bogdanel"
    RMDir /r "$INSTDIR\DWGtoKMZ"
  ${EndIf}
  Delete "$SMPROGRAMS\${APP}\Convertor DXF-DWG - KMZ.lnk"
  Delete "$SMPROGRAMS\${APP}\DWG to KMZ.lnk"
  StrCpy $Stg "$INSTDIR\${STGNAME}"
  Call AppApply
  SetOutPath "$INSTDIR"
  ${If} $Locked > 0
    Push "$Locked fișiere erau folosite (de ex. meniul ${APP} în AutoCAD deschis) și au rămas în versiunea veche: reporniți AutoCAD și rulați din nou instalarea."
    Call LogLine
  ${EndIf}

  ; folderul lansatorului, citit de TopoKitLoad.lsp (verificarea licentei: TopoKit.exe /license)
  FileOpen $0 "${BUNDLE}\Contents\install.txt" w
  FileWrite $0 "$INSTDIR$\r$\n"
  FileClose $0
  WriteRegStr HKCU "${REGAPP}" "ContentsDir" "${BUNDLE}\Contents"
  WriteRegStr HKCU "${REGAPP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGAPP}" "Version" "${VERSION}"
  ; pornirea cu Windows: o scrie din nou sectiunea SecAutorun doar daca e bifata (la actualizare
  ; debifarea trebuie sa o si opreasca)
  DeleteRegValue HKCU "${REGRUN}" "${APP}"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${REGUNINST}" "DisplayName" "${APP} ${VERSION} (AutoCAD)"
  WriteRegStr HKCU "${REGUNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${REGUNINST}" "Publisher" "${APP}"
  WriteRegStr HKCU "${REGUNINST}" "DisplayIcon" "$INSTDIR\TopoKit.exe"
  WriteRegStr HKCU "${REGUNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${REGUNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${REGUNINST}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${REGUNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${REGUNINST}" "NoRepair" 1
  ; marimea fisierelor instalate (nu a intregului folder: poate contine si proiectul)
  WriteRegDWORD HKCU "${REGUNINST}" "EstimatedSize" $5

  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortCut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\TopoKit.exe" "" "$INSTDIR\topokit.ico" 0 \
    SW_SHOWNORMAL "" "Deschide TopoKit în AutoCAD"
  CreateShortCut "$SMPROGRAMS\${APP}\Plan Inclinare.lnk" "$INSTDIR\PlanInclinare\PlanInclinare.exe" "" \
    "$INSTDIR\PlanInclinare\PlanInclinare.exe" 0 SW_SHOWNORMAL "" "Calcul inclinatie (verticalitate)"
  CreateShortCut "$SMPROGRAMS\${APP}\Ghid ${APP}.lnk" "$INSTDIR\README.html"
  CreateShortCut "$SMPROGRAMS\${APP}\Funcții ${APP}.lnk" "$INSTDIR\Functii.html"
  CreateShortCut "$SMPROGRAMS\${APP}\Dezinstalare ${APP}.lnk" "$INSTDIR\Uninstall.exe"

  ; AutoCAD prezent? (instalarea continua oricum: pachetul se activeaza la instalarea AutoCAD)
  SetRegView 64
  ReadRegStr $0 HKCR "AutoCAD.Application\CLSID" ""
  ${If} $0 == ""
    EnumRegKey $0 HKLM "SOFTWARE\Autodesk\AutoCAD" 0
  ${EndIf}
  SetRegView lastused
  ${If} $0 == ""
    DetailPrint "AutoCAD nu a fost detectat."
    MessageBox MB_OK|MB_ICONINFORMATION "AutoCAD nu a fost detectat pe acest calculator.$\r$\n$\r$\n\
      ${APP} se instalează oricum și se va încărca automat după instalarea AutoCAD 2013 sau mai nou." /SD IDOK
  ${Else}
    DetailPrint "AutoCAD detectat: ${APP} se încarcă automat la pornirea AutoCAD."
  ${EndIf}
SectionEnd

Section "Scurtătură pe desktop" SecDesktop
  CreateShortCut "$DESKTOP\${APP}.lnk" "$INSTDIR\TopoKit.exe" "" "$INSTDIR\topokit.ico" 0 \
    SW_SHOWNORMAL "" "Deschide TopoKit în AutoCAD"
SectionEnd

Section "Pornește în fundal odată cu Windows" SecAutorun
  WriteRegStr HKCU "${REGRUN}" "${APP}" '"$INSTDIR\TopoKit.exe" /background'
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "Comenzile TopoKit în AutoCAD (încărcare automată) și lansatorul din bara de sistem."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Pictogramă TopoKit pe desktop: deschide TopoKit în AutoCAD (pornește AutoCAD dacă e nevoie)."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAutorun} "Lansatorul pornește cu Windows și așteaptă AutoCAD în fundal (iconița de lângă ceas)."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  !insertmacro CloseLauncher
  StrCpy $Locked 0
  !insertmacro CheckAllClosed "un."
  ; pachetul AutoCAD: cale fixa, doar al TopoKit
  RMDir /r "${BUNDLE}"
  RMDir /r "${BUNDLESTG}"
  ; programul: exact fisierele din lista scrisa la instalare, apoi doar folderele ramase goale
  StrCpy $Dst "$INSTDIR"
  ${If} ${FileExists} "$INSTDIR\${MANIFEST}"
  ${OrIf} ${FileExists} "$INSTDIR\${MANIFEST}.prev"
    StrCpy $R8 "$INSTDIR\${MANIFEST}"
    Call un.RemoveList
    StrCpy $R8 "$INSTDIR\${MANIFEST}.prev"
    Call un.RemoveList
    StrCpy $R8 "$INSTDIR\${MANIFEST}.new"
    Call un.RemoveList
  ${Else}
    ; lista lipseste: doar fisierele principale (nimic sters cu tot cu folder)
    Push "Lista fișierelor instalate lipsește ($INSTDIR\${MANIFEST}): se șterg doar fișierele principale."
    Call un.LogLine
    Delete "$INSTDIR\TopoKit.exe"
    Delete "$INSTDIR\topokit.ico"
    Delete "$INSTDIR\README.html"
    Delete "$INSTDIR\Functii.html"
    Delete "$INSTDIR\Functii_EN.html"
  ${EndIf}
  RMDir /r "$INSTDIR\${STGNAME}"         ; folderul temporar al instalatorului (instalare intrerupta)
  Delete "$INSTDIR\${MANIFEST}"
  Delete "$INSTDIR\${MANIFEST}.prev"
  Delete "$INSTDIR\${MANIFEST}.new"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  ; datele lansatorului; licenta (license.lic + state.dat) ramane: stergerea lui state.dat nu elibera
  ; locul pe server (dezactivarea are nevoie de el) si o reinstalare pe acelasi calculator ar consuma
  ; o activare noua. Locul se elibereaza din fereastra TopoKit (Dezactivează) inainte de dezinstalare.
  Delete "$LOCALAPPDATA\TopoKit\TopoKit.log"
  Delete "$LOCALAPPDATA\TopoKit\install.log"
  Delete "$LOCALAPPDATA\TopoKit\diagnostic.txt"
  Delete "$LOCALAPPDATA\TopoKit\language.txt"
  Delete "$LOCALAPPDATA\TopoKit\*.tmp"
  RMDir "$LOCALAPPDATA\TopoKit"
  Delete "$DESKTOP\${APP}.lnk"
  RMDir /r "$SMPROGRAMS\${APP}"
  DeleteRegValue HKCU "${REGRUN}" "${APP}"
  DeleteRegKey HKCU "${REGAPP}"
  DeleteRegKey HKCU "${REGUNINST}"
SectionEnd
