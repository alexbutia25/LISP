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
; ==========================================================================
Unicode true
ManifestDPIAware true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "WinMessages.nsh"
!include "FileFunc.nsh"

!ifndef VERSION
  !define VERSION "1.0.0"
!endif
!ifndef STAGE
  !error "Compilati cu tools/build_installer.py (definește STAGE)"
!endif
!ifndef OUTFILE
  !define OUTFILE "TopoKitSetup.exe"
!endif

!define APP       "TopoKit"
!define BUNDLE    "$APPDATA\Autodesk\ApplicationPlugins\TopoKit.bundle"
!define REGAPP    "Software\TopoKit"
!define REGUNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\TopoKit"
!define REGRUN    "Software\Microsoft\Windows\CurrentVersion\Run"
!define WNDCLASS  "TopoKitLauncherWnd"

Name "${APP} ${VERSION}"
OutFile "${OUTFILE}"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\TopoKit"
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
!define MUI_COMPONENTSPAGE_SMALLDESC

!define MUI_WELCOMEPAGE_TITLE "Instalare ${APP} ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "${APP} adaugă în AutoCAD instrumente de topografie și cadastru:$\r$\n$\r$\n\
  • conversie Stereo 70 / WGS84 (grila ANCPI) și export KMZ$\r$\n\
  • anexele Ordinului ANCPI nr. 600/2023 (planuri, Word, PDF)$\r$\n\
  • puncte, TIN, curbe de nivel, volume, georeferențiere$\r$\n$\r$\n\
După instalare, ${APP} se încarcă automat în AutoCAD 2013 sau mai nou. \
Lansatorul ${APP} rulează în fundal (iconița de lângă ceas) și deschide comenzile în AutoCAD.$\r$\n$\r$\n\
Nu sunt necesare drepturi de administrator."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "${APP} este instalat"
!define MUI_FINISHPAGE_TEXT "${APP} se încarcă automat în fiecare desen AutoCAD (comenzile TOPOKIT, ANEXE, TOPOTEREN).$\r$\n$\r$\n\
Dacă AutoCAD este deja deschis, alegeți o comandă din iconița ${APP} de lângă ceas sau reporniți AutoCAD."
!define MUI_FINISHPAGE_RUN "$INSTDIR\TopoKit.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Pornește ${APP} acum"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.html"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Deschide ghidul de utilizare"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Romanian"

; Inchide lansatorul care ruleaza (actualizare / dezinstalare)
!macro CloseLauncher
  FindWindow $0 "${WNDCLASS}"
  ${If} $0 <> 0
    SendMessage $0 ${WM_CLOSE} 0 0 /TIMEOUT=3000
    Sleep 700
  ${EndIf}
!macroend

Section "${APP} pentru AutoCAD (obligatoriu)" SecMain
  SectionIn RO
  !insertmacro CloseLauncher

  ; pachetul AutoCAD (Autoloader): o versiune veche se inlocuieste complet
  RMDir /r "${BUNDLE}"
  SetOutPath "${BUNDLE}"
  File /r "${STAGE}\bundle\TopoKit.bundle\*.*"

  ; lansatorul si documentatia
  SetOutPath "$INSTDIR"
  File "${STAGE}\app\TopoKit.exe"
  File "${STAGE}\app\topokit.ico"
  File "${STAGE}\app\README.html"
  SetOutPath "$INSTDIR\docs"
  File /r "${STAGE}\app\docs\*.*"
  SetOutPath "$INSTDIR"

  WriteRegStr HKCU "${REGAPP}" "ContentsDir" "${BUNDLE}\Contents"
  WriteRegStr HKCU "${REGAPP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGAPP}" "Version" "${VERSION}"

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
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  ${GetSize} "${BUNDLE}" "/S=0K" $3 $1 $2
  IntOp $0 $0 + $3
  WriteRegDWORD HKCU "${REGUNINST}" "EstimatedSize" $0

  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortCut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\TopoKit.exe" "" "$INSTDIR\topokit.ico" 0 \
    SW_SHOWNORMAL "" "Deschide TopoKit în AutoCAD"
  CreateShortCut "$SMPROGRAMS\${APP}\Ghid ${APP}.lnk" "$INSTDIR\README.html"
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
  RMDir /r "${BUNDLE}"
  Delete "$INSTDIR\TopoKit.exe"
  Delete "$INSTDIR\topokit.ico"
  Delete "$INSTDIR\README.html"
  RMDir /r "$INSTDIR\docs"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  RMDir /r "$LOCALAPPDATA\TopoKit"
  Delete "$DESKTOP\${APP}.lnk"
  RMDir /r "$SMPROGRAMS\${APP}"
  DeleteRegValue HKCU "${REGRUN}" "${APP}"
  DeleteRegKey HKCU "${REGAPP}"
  DeleteRegKey HKCU "${REGUNINST}"
SectionEnd
