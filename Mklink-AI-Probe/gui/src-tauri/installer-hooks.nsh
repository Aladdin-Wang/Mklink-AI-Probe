; Installer-time USB naming is deliberately best-effort. The main application
; must remain installable when no MKLink is connected or PnP is still settling.
Var MklinkLegacyInstallDir

!macro NSIS_HOOK_PREINSTALL
  ; Tauri owns uninstall/reinstall. In /UPDATE mode it deliberately overwrites
  ; in place and preserves shortcuts. Launching another uninstaller here races
  ; file extraction and deletes shortcuts which /UPDATE will not recreate.
  ; Keep legacy files/registration until a separate, explicit cleanup.
  StrCpy $MklinkLegacyInstallDir ""
  ${If} $UpdateMode = 1
    ReadRegStr $MklinkLegacyInstallDir HKCU "${MANUPRODUCTKEY}" ""
  ${EndIf}
!macroend

!macro MKLINK_RETARGET_LEGACY_SHORTCUT SHORTCUT
  ; Only retarget an existing shortcut to this product's old executable.
  ; Do not recreate shortcuts the user intentionally deleted or touch others.
  !insertmacro IsShortcutTarget "${SHORTCUT}" "$MklinkLegacyInstallDir\${MAINBINARYNAME}.exe"
  Pop $0
  ${If} $0 = 1
    !insertmacro SetShortcutTarget "${SHORTCUT}" "$INSTDIR\${MAINBINARYNAME}.exe"
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; v0.1.7 used currentUser while v0.1.8 uses perMachine. The native updater
  ; only updates shortcuts in its own shell context. After successful file
  ; extraction, retarget matching current-user shortcuts to the new location.
  ${If} $UpdateMode = 1
  ${AndIf} $MklinkLegacyInstallDir != ""
  ${AndIf} $MklinkLegacyInstallDir != $INSTDIR
    SetShellVarContext current
    !insertmacro MKLINK_RETARGET_LEGACY_SHORTCUT "$DESKTOP\${PRODUCTNAME}.lnk"
    !insertmacro MKLINK_RETARGET_LEGACY_SHORTCUT "$SMPROGRAMS\${PRODUCTNAME}.lnk"
    !insertmacro SetContext
  ${EndIf}

  ; Apply naming immediately when a probe is already present. When no probe is
  ; connected, the helper still runs successfully and the next explicit rename
  ; action can handle the device after Windows creates its PnP registry entry.
  DetailPrint "Initializing MKLink USB serial port naming..."
  nsExec::ExecToLog '"$INSTDIR\mklink-ai-probe.exe" --manage-usb-port-names apply'
  Pop $0
  ${If} $0 == 0
    DetailPrint "MKLink USB serial port naming initialization completed."
  ${Else}
    DetailPrint "MKLink USB serial port naming initialization returned code $0."
  ${EndIf}
!macroend
