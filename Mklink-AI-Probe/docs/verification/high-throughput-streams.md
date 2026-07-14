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
| SystemView | V4.3.4 | 1 MHz | host-armed user-event pairs=2/tick | 20,093.43 events/s | 36,171,279 | 966,024.77 | 0 | pending browser gate | pending | pending browser gate | pending browser gate | backend HIL PASS |
| VOFA | V4.3.4 | 1 MHz | 2 | 8,044.33 samples/s | 14,479,808 | 73,404.55 | 0 | pending browser gate | pending | pending browser gate | pending browser gate | backend HIL PASS |
| RTT | V4.3.4 | 1 MHz | 4 numeric + raw log | 12,997.51 samples/s | 23,395,840 | 474,932.82 | 0 | pending browser gate | 70,324,224 B | pending browser gate | pending browser gate | backend HIL PASS |
| SuperWatch | V4.3.4 | 1 MHz | 2 | 8,023.71 samples/s | 14,442,688 | 73,477.36 | 0 | pending browser gate | pending | pending browser gate | pending browser gate | backend HIL PASS |

The committed report must contain only the masked probe identity, firmware
version, STM32F103RC, configured SWD frequency, aggregate samples/events per
second, encoded bytes per second, both loss domains, process peak memory, and
measured visible FPS. Full probe IDs, serial ports, usernames, screenshots,
and raw captures must not be committed.

The backend HIL artifacts are
[SystemView](artifacts/systemview-ws-30min-2026-07-14.json),
[VOFA](artifacts/vofa-ws-30min-2026-07-14.json),
[RTT](artifacts/rtt-ws-30min-2026-07-14.json), and
[SuperWatch](artifacts/superwatch-ws-30min-2026-07-14.json). All four used
one authenticated binary WebSocket for the complete timed window and report
zero sequence gaps and zero stream-specific backend loss increments.

RTT qualification used a test-firmware-only 16 KiB channel-0 up buffer. The
original 1 KiB buffer exposed target scheduling jitter: burst 11 sustained
10,999.61 samples/s and had no WebSocket or Hub loss, but accumulated 32
target-side write drops over 30 minutes. That diagnostic is retained as
[the burst-11 failed-limit artifact](artifacts/rtt-ws-burst11-fail-30min-2026-07-14.json).
After changing `PKG_SEGGER_RTT_BUFFER_SIZE_UP` from 1,024 to 16,384 in the
external STM32F103RC test project's `.config` and `rtconfig.h`, Keil rebuilt
the firmware with zero errors (four pre-existing warnings; ZI 45,816 bytes).
Five-minute host-armed screens were lossless at bursts 10, 12, and 13; burst
14 was the overload boundary. The selected burst 13 then completed 1,800.025
seconds with 23,395,840 numeric samples, target markers
`130/130/0 -> 23395710/23395710/0`, zero Hub loss, and queue high-water 33/64.
The target fixture remains outside this repository and must keep the 16 KiB
test setting for this exact RTT result to be reproducible.

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
