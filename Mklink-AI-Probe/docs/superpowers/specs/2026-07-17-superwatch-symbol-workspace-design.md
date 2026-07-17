# SuperWatch Shared Symbol Workspace Design

## Goal

Turn SuperWatch into the desktop application's single type-aware variable tuning workspace. A successfully parsed AXF symbol catalog must be immediately reusable by the Symbols tab and SuperWatch without repeated configuration. The GUI VOFA+ entry is removed because it duplicates the same waveform and `cmd.dump_memory` acquisition model.

The workflow must support:

- immediate browsing of readable AXF variables;
- checkbox-based variable selection;
- high-rate typed sampling through `cmd.dump_memory`;
- inline, type-safe RAM writes through `cmd.flush_memory`;
- explicit AXF reparse after a firmware rebuild;
- name-based selection preservation across symbol generations;
- independent waveform visibility for every selected variable;
- real hardware qualification with the local STM32F103 Bootloader and App fixtures.

## Scope

### Included

- A shared backend symbol catalog with generation and AXF fingerprint metadata.
- Immediate symbol listing in the Symbols tab.
- A left-side symbol tree and variable editor inside SuperWatch.
- Removal of the VOFA+ tab and its desktop frontend runtime.
- Typed decoding of `dump_memory` payloads.
- Typed encoding, stopped-stream write, one-shot readback verification, and stream restoration.
- AXF modification detection and user-triggered reparsing.
- Mouse interaction for waveform X/Y zoom, pan, and automatic-range reset.
- A shared numeric Y axis for all visible SuperWatch curves.
- Automated and installed-application hardware regression.

### Excluded

- Removal of the existing CLI or backend VOFA compatibility APIs. They remain available for existing non-GUI users.
- Writing structures, arrays, pointers, Flash constants, functions, locals, or variables without stable RAM addresses.
- Automatic AXF replacement while sampling without user confirmation.
- Whole-chip erase or Bootloader replacement during this qualification.

## Shared Symbol Catalog

The connected Device owns one `SymbolCatalog` snapshot. The snapshot contains:

- AXF path;
- file size and modification time;
- monotonically increasing generation;
- parse timestamp;
- filtered variable descriptors;
- structure and enum metadata required by the GUI;
- actionable parse status and errors.

A variable descriptor contains a stable name or member path, address, normalized C type, size, writability, enum values when applicable, and structure expansion metadata.

The catalog includes only variables that can be safely resolved at runtime:

- global or static variables with valid target RAM addresses;
- numeric scalar types, booleans, and enums;
- structure members that resolve to supported scalar leaves.

The catalog excludes functions, function locals, unresolved or zero-address entries, pointers, arrays as whole values, unsupported complex types, and Flash-resident constants. Structures appear as expandable directory nodes but are not sampled or written as whole objects.

The Symbols tab loads the current catalog when opened and shows a virtualized, searchable list immediately. It no longer requires the user to type a query before any symbols appear.

## Dashboard State

The dashboard uses one shared frontend symbol store backed by the catalog API. The Symbols tab and SuperWatch consume the same snapshot and generation. Component-local copies of AXF parsing state are forbidden.

SuperWatch selections are persisted by variable name or member path, not by address. A selection is resolved against the current catalog only when configuring acquisition or performing a write.

When a device disconnects, active acquisition stops but selected names remain. After reconnection and successful symbol loading, selections are rebound to the current catalog.

## SuperWatch Layout

The SuperWatch page uses the approved two-column layout:

- Left: resizable and collapsible variable directory.
- Right: full-height waveform workspace.

The variable directory contains:

- AXF state and reparse status;
- search by name, type, or member path;
- filters for all, selected, and writable variables;
- expandable structure nodes;
- checkboxes for readable scalar leaves;
- an eye control for each selected scalar leaf;
- type and current value columns;
- an edit icon for writable variables;
- an inline editor expanded only beneath the variable being edited.

The selection checkbox controls acquisition. The eye controls rendering only: hiding a curve does not remove the variable from `cmd.dump_memory`, stop current-value updates, or disable writes. Visibility is retained by variable name across device reconnect and symbol reparse while the variable remains selected. Removing a variable clears its visibility state, and selecting it again makes it visible by default.

The right workspace contains the waveform, acquisition controls, trigger controls, health telemetry, cursors, and export controls. The legacy right-side Watch table and its resizer are not shown in the desktop SuperWatch workspace because variable selection, current values, visibility, and writes are owned by the left directory. The released width belongs to the waveform. Variable write controls do not consume waveform height.

The GUI removes the VOFA+ navigation tab and does not instantiate a VOFA waveform component.

## Waveform Mouse Interaction

Coordinate interaction is direct and axis-specific:

- wheel over the X axis zooms time around the mouse position;
- drag the X axis pans time;
- double-click the X axis restores automatic time range;
- wheel over the Y axis zooms amplitude around the mouse position;
- drag the Y axis pans amplitude;
- double-click the Y axis restores automatic amplitude range.

All visible curves use one shared Y range so the numeric axis has an unambiguous meaning. The Y axis displays approximately six readable tick values aligned with the horizontal grid. Tick precision adapts to the current range and uses compact scientific notation for very large or very small values. Hiding or showing a curve recomputes the automatic shared range; manual Y zoom and pan continue from the resulting visible range. When only one curve is visible, the axis directly represents that variable.

The variable directory can be collapsed to maximize waveform area. Axis hit regions have stable dimensions so zoom and drag behavior do not shift with labels or dynamic values.

## Typed Acquisition

Selected descriptors are resolved against the current symbol generation when sampling starts. The backend groups adjacent variables into efficient `cmd.dump_memory` regions and uses multi-region requests for discontiguous variables while respecting firmware limits.

Raw payload bytes are decoded on the backend using Cortex-M little-endian representation. Supported scalar families are:

- signed and unsigned 8/16/32/64-bit integers;
- `float` and `double`;
- booleans;
- enums using their underlying integer representation.

The frontend receives structured channel metadata and numeric sample batches. It does not infer types from raw bytes.

## Typed Write Transaction

Only writable RAM scalars can be edited. The UI uses:

- numeric inputs for integers and floating-point values;
- a toggle for booleans;
- a select menu for known enum values.

NaN, infinity, out-of-range integers, invalid enum values, stale generations, and unsupported types are rejected before hardware access.

Every write is a serialized transaction:

1. Capture the current running or paused state, selected names, and sampling period.
2. Stop the active `cmd.dump_memory` session and wait for the binary parser to exit.
3. Resolve the variable again against the submitted symbol generation.
4. Encode the value in little-endian form for the resolved type.
5. Write with `cmd.flush_memory`.
6. Perform a one-shot `cmd.dump_memory` readback of the same region.
7. Decode and compare the readback value.
8. In `finally`, restore the previous continuous acquisition configuration.
9. Restore the previous paused-render state when applicable.

Write, reparse, start, stop, and reconnect transitions share one transaction lock. Command streams must not overlap.

The variable row shows the old value, requested value, verification result, and whether acquisition was restored. No blocking confirmation dialog is used.

## AXF Change And Reparse

The backend compares the loaded AXF fingerprint with the current file size and modification time. A changed file marks the catalog stale but does not replace it automatically.

The dashboard displays an `AXF updated` state and a `Reparse and refresh variables` command. Reparse behavior is:

1. Stop current acquisition and remember its state.
2. Parse a complete new catalog snapshot.
3. Recheck the file fingerprint after parsing; discard the result if the file changed again.
4. Rebind selected variables by name or member path.
5. Preserve variables that still exist.
6. Update changed addresses, types, sizes, and enum metadata.
7. Remove variables that disappeared or became unsupported.
8. Show a summary of preserved, updated, and removed selections.
9. Restore acquisition with the rebound selection and previous paused state.

If parsing fails, the previous valid catalog remains active and the previous acquisition configuration is restored.

## Errors And Recovery

All expected failures are shown as persistent Chinese inline states or toasts, not blocking browser dialogs. This includes:

- missing GNU Arm readelf support;
- AXF without usable DWARF;
- stale symbol generation;
- unsupported or removed variables;
- invalid values;
- acquisition stop failure;
- `flush_memory` write failure;
- readback mismatch;
- acquisition restore failure;
- device disconnect or resource conflict.

Write and reparse operations report their phase so the user can distinguish parse, stop, write, verify, and restore failures.

## API Shape

The exact route names may follow current repository conventions, but the contract must provide:

- catalog status and AXF fingerprint;
- paged or bounded variable listing with search and filters;
- explicit reparse;
- selection resolution against a generation;
- a typed write transaction;
- rebind summaries after reparse.

Responses must not expose credentials, complete probe identifiers, COM names, or unrelated local paths. AXF path display remains limited to the existing local desktop UI context and is not written to repository evidence.

## Automated Verification

Backend coverage includes:

- variable filtering and structure expansion;
- type normalization;
- little-endian decode and encode;
- integer, float, boolean, and enum validation;
- generation rejection;
- acquisition grouping limits;
- write stop/flush/readback/restore ordering;
- restoration on every failure phase;
- name-based rebind summaries;
- stale-file and parse-failure rollback.

Frontend coverage includes:

- Symbols tab immediate loading;
- shared catalog state across tabs;
- variable search, filters, expansion, and selection;
- inline type-specific editors;
- write transaction state and errors;
- AXF stale banner and reparse summary;
- selection preservation after reparse;
- VOFA+ navigation removal;
- absence of the redundant right-side Watch table in desktop SuperWatch;
- checkbox acquisition semantics versus eye-only rendering semantics;
- visibility preservation across reconnect and reparse, plus reset after deselection;
- shared numeric Y ticks and automatic-range updates after visibility changes;
- X/Y wheel zoom, drag pan, and double-click reset;
- layout stability with the variable directory expanded and collapsed.

## Hardware Qualification

The two local STM32F103 projects are used without committing their paths or artifacts.

- Rebuild and parse both the Bootloader and App AXF files.
- Treat the Bootloader HEX as preservation evidence only during this task.
- Use the App Keil project for SuperWatch HIL; test code may be changed as needed.
- If firmware must be updated, program only the App HEX region.
- Verify the Bootloader and App regions remain present; never use default whole-chip erase.
- Select real App variables through the new directory and run continuous typed sampling.
- Exercise pause, resume, stop, X/Y zoom, pan, and range reset with Computer Use.
- Hide and restore individual selected curves from the variable directory and confirm acquisition values continue updating while hidden.
- Confirm the shared numeric Y ticks track visible data and that the waveform uses the width released by the removed Watch table.
- Perform a reversible scalar write, verify readback, restore the original value, and confirm acquisition resumes.
- Rebuild the App, detect the changed AXF, reparse, and verify selected variables are preserved by name.
- Cover removed-variable reconciliation in automation rather than modifying the hardware fixture solely to create a deletion case.
- Rebuild the unsigned NSIS installer, overwrite-install it, and repeat the ordinary-user flow in the installed application.

No firmware, Pack, AXF, BIN, HEX, logs, screenshots, complete probe identifiers, COM names, credentials, or local hardware paths are committed.
