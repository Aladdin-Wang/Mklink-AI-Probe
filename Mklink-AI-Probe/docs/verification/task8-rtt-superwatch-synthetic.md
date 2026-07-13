# Task 8 RTT and SuperWatch synthetic verification

Task 8 uses deterministic synthetic gates to verify bounded transport, decoding,
storage, and rendering behavior before Task 9 hardware qualification.

## Python transport soaks

These wall-clock runs used the local Python `StreamHub` benchmark with synthetic
payloads. They did not use an MKLink probe, target firmware, browser, WebSocket,
or Web Worker. The 600-second runs were completed before the final Task 8 review
fixes and were not repeated because those fixes do not alter the benchmark path.

| Stream | Duration | Produced/consumed | Drops | Sequence errors | Queue high-water | Throughput |
|---|---:|---:|---:|---:|---:|---:|
| RTT | 600 s | 6,000,000 / 6,000,000 | 0 | 0 | 1 | 123,599.7 B/s |
| SuperWatch, 8 channels | 600 s | 6,000,000 / 6,000,000 | 0 | 0 | 1 | 403,599.4 B/s |

Commands:

```powershell
python _maintainer/testing/performance/stream_benchmark.py --stream rtt --duration 600 --rate 10000
python _maintainer/testing/performance/stream_benchmark.py --stream superwatch --duration 600 --rate 10000 --channels 8
```

## Accelerated frontend gates

These Vitest/jsdom tests run accelerated in one JavaScript thread. They exercise
the real decoder controller and viewer logic, but they are not wall-clock browser,
real Web Worker, WebSocket, packaged application, probe, or target evidence.

- RTT decoder gate processes 600,000 encoded line records without retaining raw
  text in Worker storage.
- RTT integration gate passes 6,000 encoded records through `StreamDecoder` into
  `RttViewTab`/`VirtualLogPanel`; retention is 5,000 lines and rendered DOM rows
  remain below 40.
- SuperWatch integration gate passes metadata plus 600,000 samples across eight
  channels through `StreamDecoder` and the real waveform viewer. The typed ring
  plateaus at 200,000 samples and a 320-pixel envelope contains at most 5,120
  points.
- Separate scheduler tests remain the automated 30 FPS rendering gate.

Focused commands:

```powershell
Set-Location gui
npm test -- src/workers/streamDecoder.worker.test.ts
npm test -- src/components/dash/RttViewTab.test.ts
npm test -- src/components/dash/WaveformViewer.test.ts
```

Task 9 must record real MKLink/STM32F103RC acquisition limits, drops, memory, and
packaged-application FPS. Synthetic results must not be reported as HIL results.
