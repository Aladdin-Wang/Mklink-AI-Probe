# Issue #7: variable catalog width and name alignment

Based on main `9758c677`. The catalog divider was clamped to 280–520 px regardless
of available space. Long names already allowed individual horizontal dragging,
but there was no control to show all name beginnings or endings together.

The divider now uses workspace width (reserving 160 px for the waveform and 5 px
for the divider), with arrow/Home/End keyboard controls and resize observation.
The existing mobile stacked layout is retained. Left/right buttons scroll both
leaf and branch names; repeated clicks work after an individual manual scroll.
Fresh search results and resized names follow the chosen alignment.

Validation on Windows, 2026-10-02:

- 27 existing component tests passed across SuperWatchTab, SymbolVariablePanel
  and VariablePath; production TypeScript/Vite build passed. Both ran through
  `scripts/build_workspace.ps1`. Build emitted the existing large-chunk warning.
- Real Chrome loaded the newly built production resources through the local
  backend. V4.5.2 + STM32F103RET6 connected and its existing AXF loaded 5,325
  variables; no flash or firmware modification was required.
- Dragging the divider expanded the catalog from 340 to 940 px in an 1,816 px
  workspace, exceeding the old cap. Home returned it to 280 px.
- Real `_object_container` search results included a long `spinlock.critical_level`
  path: right alignment scrolled to 133/133 px; left alignment returned all
  inspected names to zero. Other paths reached 38/38 and 67/67 px respectively.
- Probe disconnected after inspection. Screenshot evidence remains local in
  ignored build storage; no hardware identifiers or customer files committed.
