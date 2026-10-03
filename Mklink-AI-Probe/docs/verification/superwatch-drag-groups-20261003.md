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
