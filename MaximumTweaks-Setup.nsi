; VERSION can be overridden by the release workflow (/DVERSION=x.y.z);
; the fallback below is only used for local compiles.
!ifndef VERSION
  !define VERSION "2.5.5"
!endif
!define APPNAME "Maximum Tweaks"
!define APPNAME_SHORT "MaximumTweaks"
!define EXENAME "MaximumTweaks.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

Name "${APPNAME}"
OutFile "MaximumTweaks-Setup-${VERSION}.exe"
InstallDir ""
InstallDirRegKey HKCU "Software\${APPNAME}" "InstallDir"

RequestExecutionLevel admin
ManifestSupportedOS all

# Set to 1 when launched with /UPDATE by the in-app updater: the welcome and
# directory pages are skipped so the wizard opens straight on the file-copy
# progress, and the app is relaunched automatically once the copy finishes.
Var UpdateMode

!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "ui\assets\header.bmp"
!define MUI_WELCOMEFINISHPAGE_BITMAP "ui\assets\wizard.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "ui\assets\wizard.bmp"


!define MUI_ABORTWARNING

!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfUpdateMode
!insertmacro MUI_PAGE_WELCOME
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfUpdateMode
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
# Manual installs finish with a checked Launch box so double-clicking the
# setup reopens the app afterwards (it used to close without launching).
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXENAME}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${APPNAME}"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Function SkipIfUpdateMode
  StrCmp $UpdateMode "1" 0 +2
  Abort
FunctionEnd

Function .onInit
  StrCpy $UpdateMode "0"
  ${GetParameters} $R0
  ${GetOptions} $R0 "/UPDATE" $R1
  ${IfNot} ${Errors}
    StrCpy $UpdateMode "1"
  ${EndIf}

  # Kill any running copy with stock taskkill - nsProcess is a third-party
  # plugin that a stock/choco NSIS install does not provide, and its absence
  # broke the installer compile. taskkill exits 128 when nothing is running,
  # which we ignore.
  ExecWait '"$SYSDIR\taskkill.exe" /F /IM "${EXENAME}"'
  Sleep 1000

  ReadRegStr $INSTDIR HKCU "Software\${APPNAME}" "InstallDir"
  StrCmp $INSTDIR "" 0 done
  ReadRegStr $INSTDIR HKLM "Software\${APPNAME}" "InstallDir"
  StrCmp $INSTDIR "" 0 done
  StrCpy $INSTDIR "$PROGRAMFILES\${APPNAME}"
done:
FunctionEnd

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "dist\MaximumTweaks.exe"

  WriteRegStr HKCU "Software\${APPNAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\${APPNAME}" "Version" "${VERSION}"
  # Same InstallDir in HKLM (default view, matching the .onInit read below).
  WriteRegStr HKLM "Software\${APPNAME}" "InstallDir" "$INSTDIR"
  # Per-machine install: register the uninstall entry in the 64-bit HKLM view
  # so Settings > Apps lists it for every user (an HKCU entry only ever shows
  # up for the account that ran the installer).
  SetRegView 64
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "Maximum Tweaks"
  WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1
  SetRegView 32
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  # Shortcuts are created for every mode. The silent branch used to Quit
  # before this point, so the first silent (updater-triggered) install left
  # the machine with no Start Menu or desktop shortcut at all.
  CreateShortCut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\${EXENAME}"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXENAME}"

  # Launch the freshly installed app afterwards:
  #   /S      - silent install (2.5.4 and older updaters run this): relaunch
  #   /UPDATE - current updater: progress page was visible, relaunch + close
  #   manual  - Finish page shows a checked Launch box (MUI_FINISHPAGE_RUN)
  # Explicit labels - no fragile +N offsets.
  IfSilent silent_run 0
  StrCmp $UpdateMode "1" silent_run interactive_done
silent_run:
  Exec '"$INSTDIR\${EXENAME}"'
  Quit
interactive_done:
SectionEnd

Section "Uninstall"
  ExecWait '"$SYSDIR\taskkill.exe" /F /IM "${EXENAME}"'
  Sleep 500

  # Remove only the files this installer created. User data that the app
  # keeps next to the exe (data\, Logs\, qos_state.json, staged update
  # downloads) must survive an uninstall - the previous "RMDir /r $INSTDIR"
  # wiped it. Plain RMDir removes $INSTDIR only when nothing is left in it.
  Delete "$INSTDIR\${EXENAME}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR\ui"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "Software\${APPNAME}"
  DeleteRegKey HKCU "${UNINST_KEY}"
  SetRegView 64
  DeleteRegKey HKLM "${UNINST_KEY}"
  SetRegView 32
  DeleteRegKey HKLM "Software\${APPNAME}"
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  Delete "$DESKTOP\${APPNAME}.lnk"
SectionEnd
