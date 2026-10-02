# SuperWatch offline replay verification

Branch: `codex/superwatch-replay`, based on main `9758c677`. Independent of
Issue #8 / PR #10 and Issue #7 / PR #11; those fixes are not merged into this
branch. Integration must reconcile generated GUI resources and handoff files.

## Implemented

Shared desktop/standalone replay dialog, local CSV/TXT/JSONL import, background
streaming parser, bounded typed-array storage, pixel min/max views, per-channel
Y scales, play/pause/restart, 0.25–16x speed, bidirectional seek, zoom and overview.
No device or live-acquisition commands are sent by replay controls.

## Automated checks

Run through `scripts/build_workspace.ps1` on Windows:

- 124 tests passed: `superwatchReplay.test.ts`,
  `superwatchReplayControls.test.ts`, `WaveformViewer.test.ts`.
- Covers export-compatible timestamps, sparse channels, duplicates, quoted CSV,
  alternate delimiters, UTF-8 split across chunks, raw TXT across midnight,
  invalid records with line numbers, file/channel bounds, peak preservation,
  reverse seek, cancellation, stale Worker replies, zero-duration logs, shortcut
  isolation and unmount cleanup.
- TypeScript/Vite production build passed and emits a dedicated replay Worker.
  Existing large-chunk and Node localStorage warnings remain non-fatal.
- 84 Python RTT/SuperWatch streaming tests passed after adding the standalone
  template assets. The build wrapper retained test scratch containing links for
  safe manual inspection; no linked paths were force-cleaned.
- The first feedback-contract run caught a README link to an unshipped `docs`
  file. User instructions were moved to public `references/superwatch-replay.md`;
  all 60 feedback queue/public-package boundary tests then passed.

## Real Chrome (2026-10-02)

- Desktop production resources served by a real local backend, no probe connected:
  imported generated 100,000-row / eight-channel CSV (800,000 values, 999.990 s).
  Overview retained 16,864 plotted extrema across the channels at this viewport.
- Sought backwards from end to 100.000 s. At 4x, approximately 1.1 seconds of
  wall time advanced playback to 104.402 s. Pause held the clock stationary.
- Invalid CSV with backwards timestamp reported line 3 and disabled playback.
- Export-format TXT loaded two rows/two channels and reached ended state;
  final numeric values were 2 and 0. Sparse JSONL returned final values 3 and 4.
- Reloaded final production resources, verified JSONL import, overview,
  keyboard isolation from the live viewer and dialog close.
- Standalone visualization server loaded the same shared modules and Worker.
  Imported 1,000,000 rows / eight channels / 8,000,000 values (the declared value
  limit), displayed overview and correct final values 1–8. Cancelled a second
  import during loading: empty state, disabled playback and cancellation message.
- Reloaded the final standalone modules and replayed sparse JSONL to completion;
  the final values again matched 3 and 4.

Inputs are synthetic export-format fixtures, not customer logs or a claim of a
million-row hardware capture. Earlier V4/F103 hardware verification belongs to
the separate issue reports. Screenshots and generated logs remain in ignored
local build storage. This is browser verification, not a new NSIS installation
or native WebView2 qualification. No merge or release was performed.
