!define VERSION "2.5.2"
!define APPNAME "Maximum Tweaks"
!define APPNAME_SHORT "MaximumTweaks"
!define EXENAME "MaximumTweaks.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

!include "MUI2.nsh"
!include "nsProcess.nsh"

Name "${APPNAME}"
OutFile "MaximumTweaks-Setup-${VERSION}.exe"
InstallDir ""
InstallDirRegKey HKCU "Software\${APPNAME}" "InstallDir"

RequestExecutionLevel admin
ManifestSupportedOS all

!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "ui\assets\header.bmp"
!define MUI_WELCOMEFINISHPAGE_BITMAP "ui\assets\wizard.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "ui\assets\wizard.bmp"


!define MUI_ABORTWARNING

Var BrandingText

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ${nsProcess::FindProcess} "${EXENAME}" $0
  StrCmp $0 0 0 +2
  ${nsProcess::KillProcess} "${EXENAME}" $0
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
  SetOutPath "$INSTDIR\ui"
  SetOutPath "$INSTDIR"

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

  IfSilent 0 +3
    Exec '"$INSTDIR\${EXENAME}"'
    Quit

  CreateShortCut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\${EXENAME}"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXENAME}"
SectionEnd

Section "Uninstall"
  ${nsProcess::FindProcess} "${EXENAME}" $0
  StrCmp $0 0 0 +2
  ${nsProcess::KillProcess} "${EXENAME}" $0
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





















