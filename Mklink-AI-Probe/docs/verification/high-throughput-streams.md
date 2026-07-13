# High-throughput stream qualification

This page separates the automated transport gate from browser, packaged-app,
and physical MKLink evidence. A synthetic result is never reported as HIL.

## Automated release gate

The CI gate runs for a real ten seconds and requires 100,000 aggregate samples,
zero sequence errors, and zero unreported loss:

```powershell
python -m pytest _maintainer/testing/tests/test_stream_performance.py -q
python _maintainer/testing/performance/stream_benchmark.py --stream vofa --duration 10 --rate 10000 --channels 8
```

On 2026-07-14 it produced and consumed 100,000 samples in 10.001 seconds at
403,556.9 encoded bytes/s, with queue high-water 1 and no reported or
unreported loss. The small machine-readable result is
[stream-ci-gate-2026-07-14.json](artifacts/stream-ci-gate-2026-07-14.json).
This is a local Python `StreamHub`/codec benchmark: it does not exercise a
WebSocket, browser Worker, GUI renderer, packaged app, USB, SWD, or target MCU.

`gui/src/lib/stream/renderScheduler.test.ts` is the automated 30 FPS rendering
cadence gate. It verifies coalescing and hidden-document behavior with a fake
clock; it is not a measured packaged-app frame rate.

## MKLink HIL matrix

Target qualification uses the connected MKLink and STM32F103RC test project.
For each stream, increase the requested acquisition rate until a loss counter
changes, then repeat the highest zero-drop rate for 30 wall-clock minutes.

| Stream | Probe firmware | SWD | Channels/events | Highest zero-drop rate | 30 min items | Bytes/s | Backend drops | Frontend drops | Peak memory | Render FPS | Paused/hidden acquisition | Evidence scope |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| SystemView | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | HIL pending |
| VOFA | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | HIL pending |
| RTT | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | HIL pending |
| SuperWatch | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | HIL pending |

The committed report must contain only the masked probe identity, firmware
version, STM32F103RC, configured SWD frequency, aggregate samples/events per
second, encoded bytes per second, both loss domains, process peak memory, and
measured visible FPS. Full probe IDs, serial ports, usernames, screenshots,
and raw captures must not be committed.

## Browser and packaged-app gates

The browser/Worker gate must connect to `/ws/streams/{name}`, observe binary
frames and Worker telemetry, pause rendering, hide the tab, and prove that
backend and Worker collection counters continue while visible rendering stays
at or below 30 FPS. These measurements are recorded separately from backend-
only HIL.

The packaged Tauri gate is:

```powershell
python scripts/build.py --check
Set-Location gui
npx tauri build
```

Install or launch the produced bundle, then run one physical stream for five
wall-clock minutes. Confirm that the hashed Worker asset and binary WebSocket
load from the packaged application. Build products and raw captures remain
untracked.

## Regression commands

```powershell
python -m pytest -q
Set-Location gui
npm test
npm run build
Set-Location ..
git diff --check
```

Baseline before HIL: Python 571 passed; GUI 18 files / 217 tests passed; Vite
production build transformed 140 modules. Vitest reports pre-existing invalid
`<tr>` nesting warnings, and `npm audit` reports two pre-existing high-severity
dependency findings; neither was introduced by this qualification task.

## Existing bounded synthetic evidence

The earlier RTT/SuperWatch soaks and their explicit limitations are retained in
[task8-rtt-superwatch-synthetic.md](task8-rtt-superwatch-synthetic.md). They
must not be used to fill the HIL matrix above.
