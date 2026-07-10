# MKLink High-Throughput Streams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the highest stable MKLink acquisition rate, target at least 10 kSamples/s when the probe permits it, and cap visible rendering at 30 FPS for SystemView, VOFA, RTT, and SuperWatch.

**Architecture:** Add a versioned binary WebSocket data plane beside existing REST/SSE control paths. Python producers publish bounded batches with sequence and drop statistics; a browser Worker decodes transferable ArrayBuffers into typed circular buffers. Canvas renderers consume only the visible window through min/max pixel-envelope decimation on a shared 30 FPS scheduler.

**Tech Stack:** Python 3.9+, FastAPI WebSocket, `struct`, bounded queues, Vue 3, TypeScript, Web Workers, TypedArray, Canvas 2D, Vitest, pytest.

---

Run all commands from the inner project root unless a step explicitly changes directory:

```text
E:\software\HPM5300\Mklink-AI-Probe\Mklink-AI-Probe
```

## File map

### Python files to create

- `mklink/remote/stream_protocol.py` — versioned binary frame codec.
- `mklink/remote/stream_hub.py` — bounded multi-client batch broadcaster and telemetry.
- `mklink/remote/stream_api.py` — binary WebSocket route.
- `_maintainer/testing/tests/test_stream_protocol.py`
- `_maintainer/testing/tests/test_stream_hub.py`
- `_maintainer/testing/tests/test_stream_api.py`
- `_maintainer/testing/tests/test_stream_performance.py`
- `_maintainer/testing/performance/stream_benchmark.py` — repeatable local benchmark, not a hardware adapter.

### Python files to modify

- `mklink/remote/api.py` — create stream registry and include WebSocket router.
- `mklink/remote/dashboards.py` — publish SystemView/RTT/SuperWatch batches.
- `mklink/vofa_viewer.py` — publish VOFA numeric batches through the shared hub.
- `mklink/systemview.py` only if source batching must expose raw event blocks; keep parsing responsibilities out of the API layer.

### Vue/TypeScript files to create

- `gui/src/lib/stream/protocol.ts`
- `gui/src/lib/stream/typedRingBuffer.ts`
- `gui/src/lib/stream/minMaxEnvelope.ts`
- `gui/src/lib/stream/renderScheduler.ts`
- `gui/src/lib/stream/streamClient.ts`
- `gui/src/lib/stream/protocol.test.ts`
- `gui/src/lib/stream/typedRingBuffer.test.ts`
- `gui/src/lib/stream/minMaxEnvelope.test.ts`
- `gui/src/lib/stream/renderScheduler.test.ts`
- `gui/src/workers/streamDecoder.worker.ts`
- `gui/src/workers/streamDecoder.worker.test.ts`
- `gui/src/composables/useBinaryStream.ts`
- `gui/src/components/dash/VirtualLogPanel.vue`
- `gui/src/components/dash/VirtualLogPanel.test.ts`

### Vue/TypeScript files to modify

- `gui/src/components/dash/SystemViewTab.vue`
- `gui/src/components/dash/WaveformViewer.vue`
- `gui/src/components/dash/RttViewTab.vue`
- `gui/src/assets/rtt_viewer.js`
- `gui/src/lib/svTimeline.js`
- `gui/src/composables/useEventSource.ts` — keep for control/legacy streams, remove migrated high-rate data use.
- Existing SystemView and dashboard tests.

## Task 1: Define a cross-language binary frame protocol

**Files:**
- Create: `mklink/remote/stream_protocol.py`
- Create: `_maintainer/testing/tests/test_stream_protocol.py`
- Create: `gui/src/lib/stream/protocol.ts`
- Create: `gui/src/lib/stream/protocol.test.ts`

- [ ] **Step 1: Write the Python golden-vector test**

The v1 header is `struct.Struct("<4sBBBBIQQII")`:

```text
magic[4], version[u8], stream_type[u8], flags[u8], header_size[u8],
stream_id[u32], sequence[u64], timestamp_ns[u64], item_count[u32], payload_length[u32]
```

Test:

```python
from mklink.remote.stream_protocol import Frame, StreamType, encode_frame, decode_frame


GOLDEN = bytes.fromhex(
    "4d4b535401020024070000000900000000000000e803000000000000"
    "02000000080000000000803f000000c0"
)


def test_waveform_frame_matches_v1_golden_vector():
    frame = Frame(StreamType.WAVEFORM, 0, 7, 9, 1000, 2, bytes.fromhex("0000803f000000c0"))
    assert encode_frame(frame) == GOLDEN
    assert decode_frame(GOLDEN) == frame
```

- [ ] **Step 2: Run Python test and verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_stream_protocol.py -q
```

Expected: import failure for `stream_protocol`.

- [ ] **Step 3: Implement strict Python codec**

Define `StreamType` values: `SYSTEMVIEW=1`, `WAVEFORM=2`, `RTT_RAW=3`, `SUPERWATCH=4`, `CONTROL=255`. Reject incorrect magic, unknown version, header size not equal to 36, payload length mismatch, and payloads larger than 4 MiB. Return immutable `Frame` dataclasses.

- [ ] **Step 4: Run Python test**

```powershell
python -m pytest _maintainer/testing/tests/test_stream_protocol.py -q
```

Expected: golden and invalid-frame tests pass.

- [ ] **Step 5: Write TypeScript golden-vector test**

```typescript
import { describe, expect, it } from 'vitest'
import { decodeFrame } from './protocol'

const GOLDEN = Uint8Array.fromHex(
  '4d4b535401020024070000000900000000000000e80300000000000002000000080000000000803f000000c0',
)

describe('decodeFrame', () => {
  it('decodes the Python v1 golden vector', () => {
    const frame = decodeFrame(GOLDEN.buffer)
    expect(frame.streamType).toBe(2)
    expect(frame.streamId).toBe(7)
    expect(frame.sequence).toBe(9n)
    expect(frame.timestampNs).toBe(1000n)
    expect(Array.from(new Float32Array(frame.payload))).toEqual([1, -2])
  })
})
```

If the configured TypeScript lib does not expose `Uint8Array.fromHex`, add a local `hexBytes()` helper in the test; do not add a runtime dependency.

- [ ] **Step 6: Implement TypeScript decoder and run both suites**

Use `DataView` little-endian reads and validate the same invariants as Python.

```powershell
Set-Location gui
npm test -- src/lib/stream/protocol.test.ts
Set-Location ..
python -m pytest _maintainer/testing/tests/test_stream_protocol.py -q
```

Expected: both suites pass with the same vector.

- [ ] **Step 7: Commit**

```powershell
git add mklink/remote/stream_protocol.py _maintainer/testing/tests/test_stream_protocol.py gui/src/lib/stream/protocol.ts gui/src/lib/stream/protocol.test.ts
git commit -m "feat: define binary stream protocol"
```

## Task 2: Build a bounded multi-client StreamHub

**Files:**
- Create: `mklink/remote/stream_hub.py`
- Create: `_maintainer/testing/tests/test_stream_hub.py`

- [ ] **Step 1: Write queue-overflow and telemetry tests**

```python
import asyncio

from mklink.remote.stream_hub import StreamHub


def test_slow_client_drops_oldest_batch():
    async def scenario():
        hub = StreamHub(max_batches_per_client=2)
        client = hub.subscribe()
        hub.publish(b"one", item_count=1)
        hub.publish(b"two", item_count=1)
        hub.publish(b"three", item_count=1)
        assert await client.get() == b"two"
        assert await client.get() == b"three"
        assert hub.stats().dropped_batches == 1
    asyncio.run(scenario())
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_stream_hub.py -q
```

Expected: import failure for `StreamHub`.

- [ ] **Step 3: Implement hub ownership and thread-safe publication**

Each subscriber owns `asyncio.Queue(maxsize=N)`. Producers call `publish_threadsafe(loop, batch)` from acquisition threads. On full queue, drop exactly one oldest batch and count dropped batches/items/bytes. Maintain counters for produced, delivered, dropped, active clients, queue high-water mark, and last sequence.

Never block the acquisition thread waiting for a browser.

- [ ] **Step 4: Add sequence and heartbeat tests**

Assert sequence increases once per published batch, remains shared across clients, and `status_frame()` reports counters without resetting them.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest _maintainer/testing/tests/test_stream_hub.py -q
git add mklink/remote/stream_hub.py _maintainer/testing/tests/test_stream_hub.py
git commit -m "feat: add bounded stream hub"
```

## Task 3: Expose authenticated binary WebSockets

**Files:**
- Create: `mklink/remote/stream_api.py`
- Modify: `mklink/remote/api.py`
- Create: `_maintainer/testing/tests/test_stream_api.py`

- [ ] **Step 1: Write FastAPI WebSocket tests**

```python
from mklink.remote.stream_protocol import decode_frame


def test_websocket_sends_binary_batch(client, stream_registry):
    with client.websocket_connect('/ws/streams/systemview') as websocket:
        stream_registry['systemview'].publish(b'payload', item_count=1)
        frame = decode_frame(websocket.receive_bytes())
        assert frame.item_count == 1
        assert frame.payload == b'payload'
```

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_stream_api.py -q
```

Expected: WebSocket route is absent.

- [ ] **Step 3: Implement stream registry and route**

Create one hub per stream type in app state. The route validates stream name and the existing server auth token, accepts the socket, subscribes, and sends encoded binary frames. Every second with no data, send a `CONTROL` status frame containing compact UTF-8 JSON telemetry. Always unsubscribe in `finally`.

- [ ] **Step 4: Test disconnect cleanup and invalid stream names**

Assert active client count returns to zero after close and unknown streams close with policy error code 1008.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest _maintainer/testing/tests/test_stream_api.py -q
git add mklink/remote/stream_api.py mklink/remote/api.py _maintainer/testing/tests/test_stream_api.py
git commit -m "feat: expose binary stream websocket"
```

## Task 4: Decode frames in a Worker-owned typed ring buffer

**Files:**
- Create: `gui/src/lib/stream/typedRingBuffer.ts`
- Create: `gui/src/lib/stream/typedRingBuffer.test.ts`
- Create: `gui/src/workers/streamDecoder.worker.ts`
- Create: `gui/src/workers/streamDecoder.worker.test.ts`
- Create: `gui/src/lib/stream/streamClient.ts`
- Create: `gui/src/composables/useBinaryStream.ts`

- [ ] **Step 1: Write ring-buffer wrap tests**

```typescript
import { describe, expect, it } from 'vitest'
import { TypedRingBuffer } from './typedRingBuffer'

describe('TypedRingBuffer', () => {
  it('overwrites oldest samples without allocation growth', () => {
    const buffer = new TypedRingBuffer(3, 1)
    buffer.append(1, Float32Array.of(10))
    buffer.append(2, Float32Array.of(20))
    buffer.append(3, Float32Array.of(30))
    buffer.append(4, Float32Array.of(40))
    expect(buffer.snapshot()).toEqual({ times: [2, 3, 4], channels: [[20, 30, 40]] })
    expect(buffer.capacity).toBe(3)
  })
})
```

- [ ] **Step 2: Verify failure**

```powershell
Set-Location gui
npm test -- src/lib/stream/typedRingBuffer.test.ts
```

Expected: import failure.

- [ ] **Step 3: Implement ring buffer without reactive point objects**

Store timestamps in `Float64Array(capacity)` and channel values in a flat `Float32Array(capacity * channelCount)`. Expose `copyVisibleRange(start, end, destination)` and test-only `snapshot()`. Normal rendering must not call `snapshot()`.

- [ ] **Step 4: Implement Worker protocol**

Messages into Worker:

```typescript
type WorkerInput =
  | { type: 'configure'; capacity: number; channelCount: number }
  | { type: 'frame'; buffer: ArrayBuffer }
  | { type: 'visible-range'; requestId: number; start: number; end: number; pixelWidth: number }
  | { type: 'reset' }
```

Messages out include `telemetry`, `channels`, `render-envelope`, and `error`. Transfer input buffers to Worker. Detect sequence gaps and accumulate transport drops separately from backend-reported drops.

- [ ] **Step 5: Implement stream client and composable**

Set `websocket.binaryType = 'arraybuffer'`. Reconnect with capped exponential backoff, but stop reconnecting after explicit user stop. Worker and socket lifetimes end on component unmount.

- [ ] **Step 6: Run tests and commit**

```powershell
npm test -- src/lib/stream/typedRingBuffer.test.ts src/workers/streamDecoder.worker.test.ts
Set-Location ..
git add gui/src/lib/stream gui/src/workers/streamDecoder.worker.ts gui/src/workers/streamDecoder.worker.test.ts gui/src/composables/useBinaryStream.ts
git commit -m "feat: add worker-owned stream buffers"
```

## Task 5: Add min/max envelope decimation and one 30 FPS scheduler

**Files:**
- Create: `gui/src/lib/stream/minMaxEnvelope.ts`
- Create: `gui/src/lib/stream/minMaxEnvelope.test.ts`
- Create: `gui/src/lib/stream/renderScheduler.ts`
- Create: `gui/src/lib/stream/renderScheduler.test.ts`
- Create: `_maintainer/testing/performance/stream_benchmark.py`

- [ ] **Step 1: Write spike-preservation test**

```typescript
import { describe, expect, it } from 'vitest'
import { minMaxEnvelope } from './minMaxEnvelope'

describe('minMaxEnvelope', () => {
  it('keeps a one-sample spike inside a crowded pixel column', () => {
    const times = Float64Array.from([0, 1, 2, 3, 4, 5])
    const values = Float32Array.from([0, 0, 100, 0, 0, 0])
    const envelope = minMaxEnvelope(times, values, 0, 5, 2)
    expect(Math.max(...envelope.max)).toBe(100)
  })
})
```

- [ ] **Step 2: Write fake-clock scheduler test**

Assert 100 dirty notifications inside 33 ms produce one render callback and that hidden-document mode produces no render callback while collection telemetry continues.

- [ ] **Step 3: Verify tests fail**

```powershell
Set-Location gui
npm test -- src/lib/stream/minMaxEnvelope.test.ts src/lib/stream/renderScheduler.test.ts
```

Expected: imports fail.

- [ ] **Step 4: Implement envelope and scheduler**

Envelope output uses typed arrays sized at most `2 * pixelWidth`. Scheduler owns one `requestAnimationFrame` loop, checks `performance.now() - lastRender >= 1000 / 30`, and coalesces data, hover, zoom, and resize invalidations.

- [ ] **Step 5: Add the transport benchmark used by migration tasks**

Create `_maintainer/testing/performance/stream_benchmark.py`. It starts a local `StreamHub`, publishes deterministic sequence-tagged batches at `--rate`, consumes them through the binary codec, and emits JSON containing produced items, consumed items, reported drops, sequence errors, bytes/sec, peak queue depth, and elapsed seconds. Support `--stream`, `--duration`, `--rate`, and `--channels`. Exit nonzero on sequence corruption or unreported drops. This command measures acquisition and transport; browser render cadence remains covered by Vitest and hardware evidence.

- [ ] **Step 6: Run tests and commit**

```powershell
npm test -- src/lib/stream/minMaxEnvelope.test.ts src/lib/stream/renderScheduler.test.ts
Set-Location ..
python _maintainer/testing/performance/stream_benchmark.py --stream vofa --duration 10 --rate 10000 --channels 8
git add gui/src/lib/stream/minMaxEnvelope.ts gui/src/lib/stream/minMaxEnvelope.test.ts gui/src/lib/stream/renderScheduler.ts gui/src/lib/stream/renderScheduler.test.ts _maintainer/testing/performance/stream_benchmark.py
git commit -m "feat: add 30 fps envelope renderer"
```

## Task 6: Migrate SystemView first

**Files:**
- Modify: `mklink/remote/dashboards.py`
- Modify: `gui/src/components/dash/SystemViewTab.vue`
- Modify: `gui/src/lib/svTimeline.js`
- Modify: `gui/src/views/DashboardView.test.ts`
- Create/Modify: `_maintainer/testing/tests/test_systemview_streaming.py`

- [ ] **Step 1: Write a backend batching test**

Feed 1200 decoded events into a fake `SystemViewStreamManager` cycle and assert the hub receives bounded binary batches with monotonically increasing sequence and the recording path still receives all 1200 events.

- [ ] **Step 2: Verify the test fails on the SSE-only path**

```powershell
python -m pytest _maintainer/testing/tests/test_systemview_streaming.py -q
```

Expected: no binary hub publication is observed.

- [ ] **Step 3: Publish SystemView batches**

Keep recording before live-queue trimming. Encode compact event records or MessagePack-free fixed records defined in `stream_protocol.py`; do not add another serialization dependency. Publish status counters once per second as control frames.

- [ ] **Step 4: Write frontend migration assertions**

Update tests to assert `SystemViewTab.vue` uses `useBinaryStream('systemview')`, does not watch the high-rate `useEventSource` array, and schedules timeline updates through the shared scheduler.

- [ ] **Step 5: Migrate timeline rendering**

Worker produces interval envelopes for the visible time window. `svTimeline.js` accepts prefiltered intervals and never slices/sorts all 50,000 intervals during one frame. Event tables update at 5 Hz independently of the 30 FPS canvas.

- [ ] **Step 6: Run focused suites and a 10-minute synthetic soak**

```powershell
python -m pytest _maintainer/testing/tests/test_systemview_streaming.py _maintainer/testing/tests/test_systemview_cpu_clock.py -q
Set-Location gui
npm test -- src/views/DashboardView.test.ts src/lib/systemViewMetrics.test.ts src/lib/stream/renderScheduler.test.ts
Set-Location ..
python _maintainer/testing/performance/stream_benchmark.py --stream systemview --duration 600 --rate 50000
```

Expected: transport reports no sequence corruption, memory remains bounded, and the scheduler test enforces a maximum 30 FPS cadence.

- [ ] **Step 7: Remove SystemView high-rate SSE fallback and commit**

```powershell
git add mklink/remote/dashboards.py gui/src/components/dash/SystemViewTab.vue gui/src/lib/svTimeline.js gui/src/views/DashboardView.test.ts _maintainer/testing/tests/test_systemview_streaming.py
git commit -m "perf: migrate SystemView to binary streaming"
git push origin HEAD
```

## Task 7: Migrate VOFA waveform acquisition

**Files:**
- Modify: `mklink/vofa_viewer.py`
- Modify: `gui/src/components/dash/WaveformViewer.vue`
- Modify: `gui/src/assets/rtt_viewer.js`
- Create: `_maintainer/testing/tests/test_vofa_streaming.py`
- Create/Modify: `gui/src/components/dash/WaveformViewer.test.ts`

- [ ] **Step 1: Write backend sample-integrity test**

Generate 10,000 sequential sample IDs over multiple channels, publish through the VOFA producer, decode frames, and assert IDs are continuous unless the bounded queue explicitly reports drops.

- [ ] **Step 2: Verify failure**

```powershell
python -m pytest _maintainer/testing/tests/test_vofa_streaming.py -q
```

Expected: current path does not produce binary batches.

- [ ] **Step 3: Batch VOFA samples at the source**

Read the largest safe MKLink memory block per cycle, timestamp once per batch, and publish channel-major or sample-major Float32 payload according to one documented flag. Measure actual sample rate from completed reads, not requested interval.

- [ ] **Step 4: Replace per-point viewer work**

`WaveformViewer.vue` owns `useBinaryStream('vofa')`. Remove high-rate `rawLogEl.textContent +=`, `ringBuf.toArray()` inside every frame, and repeated `Object.keys(FIELDS).sort()` from the hot path. Keep project save/load, cursors, trigger, and export by adapting them to typed buffers.

Guard the new path by `CONFIG.mode === 'VOFA'` during this task so SuperWatch keeps its legacy path until Task 8.

- [ ] **Step 5: Run 10 kSamples/s tests**

```powershell
python -m pytest _maintainer/testing/tests/test_vofa_streaming.py -q
Set-Location gui
npm test -- src/components/dash/WaveformViewer.test.ts src/lib/stream
Set-Location ..
python _maintainer/testing/performance/stream_benchmark.py --stream vofa --duration 1800 --rate 10000 --channels 8
```

Expected: the 30-minute transport run completes with bounded memory; frontend tests enforce the 30 FPS scheduler limit.

- [ ] **Step 6: Commit and push**

```powershell
git add mklink/vofa_viewer.py gui/src/components/dash/WaveformViewer.vue gui/src/assets/rtt_viewer.js gui/src/components/dash/WaveformViewer.test.ts _maintainer/testing/tests/test_vofa_streaming.py
git commit -m "perf: migrate VOFA to binary streaming"
git push origin HEAD
```

## Task 8: Migrate RTT and SuperWatch and virtualize logs

**Files:**
- Modify: `mklink/remote/dashboards.py`
- Modify: `gui/src/components/dash/RttViewTab.vue`
- Modify: `gui/src/components/dash/SuperWatchTab.vue`
- Create: `gui/src/components/dash/VirtualLogPanel.vue`
- Create: `gui/src/components/dash/VirtualLogPanel.test.ts`
- Create: `_maintainer/testing/tests/test_rtt_superwatch_streaming.py`

- [ ] **Step 1: Write raw-line and sample batch tests**

Assert RTT preserves line boundaries across arbitrary byte chunks and SuperWatch preserves channel/sample alignment. Queue overflow must increment explicit drop counters.

- [ ] **Step 2: Implement backend publication**

RTT raw text uses `RTT_RAW` batches with UTF-8 payload and line-boundary metadata. Parsed numeric RTT may use `WAVEFORM`. SuperWatch uses `SUPERWATCH` with the same numeric payload layout as VOFA plus symbol metadata version.

- [ ] **Step 3: Build a bounded virtual log**

`VirtualLogPanel` stores a maximum of 5000 lines, renders only visible rows, follows bottom only when the user is within 24 px of the end, and preserves line number/time/level. Add tests for trimming and scroll-follow disablement.

- [ ] **Step 4: Migrate components**

Remove high-rate watchers over copied arrays. RTT log updates at most 10 times per second; numeric plots use the shared 30 FPS scheduler. SuperWatch metadata updates independently from sample data.

- [ ] **Step 5: Run tests and soak**

```powershell
python -m pytest _maintainer/testing/tests/test_rtt_superwatch_streaming.py -q
Set-Location gui
npm test -- src/components/dash/VirtualLogPanel.test.ts src/lib/stream
Set-Location ..
python _maintainer/testing/performance/stream_benchmark.py --stream rtt --duration 600 --rate 10000
python _maintainer/testing/performance/stream_benchmark.py --stream superwatch --duration 600 --rate 10000 --channels 8
```

Expected: no unbounded DOM/text growth; memory plateaus and telemetry exposes any drops.

- [ ] **Step 6: Commit and push**

```powershell
git add mklink/remote/dashboards.py gui/src/components/dash/RttViewTab.vue gui/src/components/dash/SuperWatchTab.vue gui/src/components/dash/VirtualLogPanel.vue gui/src/components/dash/VirtualLogPanel.test.ts _maintainer/testing/tests/test_rtt_superwatch_streaming.py
git commit -m "perf: migrate RTT and SuperWatch streaming"
git push origin HEAD
```

## Task 9: Add performance gates, hardware evidence, and release verification

**Files:**
- Create: `_maintainer/testing/tests/test_stream_performance.py`
- Create: `docs/verification/high-throughput-streams.md`
- Modify: `README.md`
- Modify: `references/commands-remote-gui.md`

- [ ] **Step 1: Add pytest performance gates**

Keep CI gates short:

```python
from _maintainer.testing.performance.stream_benchmark import run_benchmark


def test_waveform_10k_samples_per_second_for_ten_seconds():
    result = run_benchmark(stream="vofa", rate=10_000, duration=10, channels=8)
    assert result.sequence_errors == 0
    assert result.unreported_drops == 0
    assert result.consumed_items >= 100_000
```

Long 30-minute soaks remain explicit release commands. `renderScheduler.test.ts` is the automated 30 FPS gate; packaged-app FPS is recorded in hardware evidence.

- [ ] **Step 2: Run automated performance and regression tests**

```powershell
python -m pytest _maintainer/testing/tests/test_stream_performance.py -q
python -m pytest -q
Set-Location gui
npm test
npm run build
Set-Location ..
```

Expected: zero failures.

- [ ] **Step 3: Run MKLink hardware measurements**

For each SystemView, VOFA, RTT, and SuperWatch:

1. Increase acquisition rate until drops begin.
2. Repeat at the highest zero-drop rate for 30 minutes.
3. Record probe firmware, target MCU, SWD frequency, channels/event types, samples/events per second, bytes/sec, backend and frontend drops, peak memory, and render FPS.
4. Confirm acquisition continues when rendering is paused or the tab is hidden.

- [ ] **Step 4: Write evidence and limitations**

Use `docs/verification/high-throughput-streams.md` with one table per stream. State measured hardware results, not inferred limits. Include links to benchmark JSON artifacts without committing oversized raw captures.

- [ ] **Step 5: Build Tauri release and rerun a smoke stream**

```powershell
Set-Location gui
npx tauri build
```

Expected: build exits 0. Install the bundle, run a five-minute hardware stream, and confirm Worker/WebSocket assets load from the packaged application.

- [ ] **Step 6: Final commit and push**

```powershell
Set-Location ..
git add _maintainer/testing/tests/test_stream_performance.py _maintainer/testing/performance/stream_benchmark.py docs/verification/high-throughput-streams.md README.md references/commands-remote-gui.md
git commit -m "test: qualify high-throughput streams"
git status --short
git diff --check
git push origin HEAD
```

Expected: clean worktree and successful push after all release evidence is recorded.
