# SuperWatch group dragging — 2026-10-03

## Cause and change

Windows Tauri native file-drop handling intercepts HTML5 dragging. The installed
391918f build reproduced the failure with a real mouse drag.
[Tauri configuration reference](https://v2.tauri.app/reference/config/) documents
that Windows HTML5 drag and drop requires disabling native dragDropEnabled.

Group movement now uses Pointer Events and pointer capture. The handle is always
visible, valid target groups are highlighted, Escape cancels, and releasing outside
the selected-signal workspace leaves the signal unchanged. Existing native firmware
file-drop handling remains configured as before; it was not requalified this run.

## Verification

- GUI suite: 73 files, 762 tests passed. Pointer regression covers move, Escape,
  and release outside a target.
- Production frontend and Tauri no-bundle builds passed.
- Real Windows desktop test: moved a signal into another populated group, then
  into a collapsed empty group. Workspace API confirmed the saved group and
  collapsed state. V4/F103 symbols were loaded; acquisition was stopped.
- Real browser fixture using production Vue components and synthetic signals:
  pointer drag moved wave_sin into another group; group count became two and
  the corresponding waveform joined its pane.

The native test executable embeds the changed frontend and uses the existing
391918f sidecar. This is not an installer/upgrade test. The installed application
remains 0.2.3/391918f. No target memory writes or firmware changes were made.
Local build logs and UI evidence remain outside Git under .build/reports.

## Merged and installed

PR24 merged to main ae83a3774c60b4b03b754013ab4bb7604cb81bc6.
Pre-merge gates: Python 2458 passed / 2 skipped; GUI 762 passed; production
build passed. The test run retained a temporary directory containing test links,
as required by the build-storage cleanup guard.

A fresh local unsigned NSIS was built from the merged commit, including the
sidecar and Web assets. SHA-256:
`a37ecf62f8a8e3b11a917601531d7d285d403e2a5ca072439a2cd99ef52426a9`.
Overwrite installation with Windows-only PATH exited 0. Installed desktop and
Web footer both report 0.2.3 / ae83a3774c60. Health and probe endpoints passed;
frozen backend contains 41 Web files, 7059 targets and 2224 FLM blobs.
The process tree uses the bundled sidecar and WebView2, without Python processes.

Actual installed desktop mouse drag moved vofa_test_count from 波形 into 计数器;
the API and real Web SuperWatch page confirmed the group now contains two signals.
The target was connected with acquisition stopped; no memory or firmware writes.
The device was disconnected after verification. This local overwrite package is
not a published release or signed updater artifact.
Normal exit released all Mklink processes and port 8765; installer SHA-256 rechecked.
