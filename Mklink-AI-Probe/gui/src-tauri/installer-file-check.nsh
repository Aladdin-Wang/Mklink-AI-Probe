; Check the actual installation files before replacing or deleting any payload.
; Never terminate by process name: a shared backend may still own a flash job,
; an AI session, or another probe. Let its normal client/idle shutdown release it.
Var MklinkBlockedFile
Var MklinkFileError

!macro MKLINK_INSPECT_FILE FILE
  ${If} ${FileExists} "$INSTDIR\${FILE}"
    ; GENERIC_WRITE, share all, OPEN_EXISTING: no truncation or data changes.
    System::Call 'kernel32::CreateFileW(w "$INSTDIR\${FILE}", i 0x40000000, i 7, p 0, i 3, i 0x80, p 0) p .r0 ?e'
    Pop $MklinkFileError
    ${If} $0 == -1
      StrCpy $MklinkBlockedFile "$INSTDIR\${FILE}"
      Goto inspected
    ${EndIf}
    System::Call 'kernel32::CloseHandle(p r0)'
  ${EndIf}
!macroend

!macro MKLINK_DEFINE_FILE_CHECK PREFIX
Function ${PREFIX}MklinkInspectUpgradeFiles
  Push $0
  StrCpy $MklinkBlockedFile ""
  !insertmacro MKLINK_INSPECT_FILE "mklink-ai-probe.exe"
  !insertmacro MKLINK_INSPECT_FILE "mklink-sidecar.exe"
  !insertmacro MKLINK_INSPECT_FILE "mklink-stcp.dll"
  inspected:
  Pop $0
FunctionEnd

Function ${PREFIX}MklinkWaitForUpgradeFiles
  Push $0
  retry:
  StrCpy $0 0
  inspect:
  Call ${PREFIX}MklinkInspectUpgradeFiles
  ${If} $MklinkBlockedFile == ""
    Goto ready
  ${EndIf}
  ; The shared backend normally releases its probe after the last client exits.
  ; Also tolerate the onefile parent's final cleanup and short antivirus scans.
  ${If} $0 < 60
    IntOp $0 $0 + 1
    Sleep 250
    Goto inspect
  ${EndIf}
  DetailPrint "MKLink file is not writable: $MklinkBlockedFile (Windows error $MklinkFileError)"
  IfSilent blocked
  MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Please finish active capture/programming, close MKLink windows and detach AI/CLI clients, then Retry.$\r$\n$\r$\n请先结束采集或烧录，关闭 MKLink 窗口并退出 AI/CLI 连接，再点重试。$\r$\n$\r$\n$MklinkBlockedFile$\r$\nWindows error: $MklinkFileError$\r$\nIf no client is running, check folder permissions or security-software quarantine. 如果没有程序占用，请检查目录权限或安全软件拦截。" /SD IDCANCEL IDRETRY retry
  blocked:
  SetErrorLevel 2
  Abort "MKLink files are still in use or inaccessible. No new payload was written."
  ready:
  Pop $0
FunctionEnd
!macroend

!insertmacro MKLINK_DEFINE_FILE_CHECK ""
!insertmacro MKLINK_DEFINE_FILE_CHECK "un."
