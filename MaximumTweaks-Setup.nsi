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
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
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

  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\${APPNAME}"
  DeleteRegKey HKCU "${UNINST_KEY}"
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  Delete "$DESKTOP\${APPNAME}.lnk"
SectionEnd





















