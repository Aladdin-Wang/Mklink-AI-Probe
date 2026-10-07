# GUI acceptance and installed SuperWatch reception

## GUI acceptance

Local unsigned NSIS 64f27ca6 overwrite returned 0. The three installed binaries
match the installer payload, all 39 Web assets match the build, and the local
Skill and sidecar contain the 7059-target/2224-blob catalog. GUI suite: 894 passed;
related backend suite: 47 passed. The attempted full Python run was interrupted
at 40% after two fixture errors; it is not a passing full regression.

Actual desktop and local Chrome checks:

- Connecting the V3 from Chrome succeeds on the first attempt after normal
  desktop launch. The other desktop window reloads and attaches to the same
  backend without manual refresh. Both register for GUI presentation.
- The earlier installed desktop passed directed SuperWatch navigation, 1 ms
  acquisition, pause/zoom/start with the 2 s/div scale retained, RAM reads and
  HardFault checking. New installed Chrome passed full-speed uint8 acquisition
  at approximately 260 kHz, pause/zoom/start retaining the approximately 60 ms
  visible span, and stopping with the waveform retained. Transmission/backend
  drop counters stayed zero. These counters do not measure unsampled time.
- RTT channels 0–7 receive simultaneously. While Chrome owns acquisition, the
  local Skill MCP subscribes, writes 13 bytes to each channel, observes the
  target's corresponding RX count and detaches. All eight cursors report no
  loss; GUI acquisition continues. Log/HEX display switches operate.
- Serial assistant sends 13 bytes through a virtual serial pair and receives
  an 18-byte echo. Modbus FC03 reads ten simulated registers (100–109), renders
  both frames with valid CRC, and rejects quantity 126 before another request.
  This verifies application transport, not physical UART/RS485 wiring.
- Symbol filtering resolves the test uint8's type, width and address. Online
  and offline flash pages expose their catalogs and refuse a missing image.
  Remote service refuses startup without an access token. RTOS Trace renders
  its empty state; this target fixture is not a SystemView stream.

These checks supplement, rather than replace, the historical full-function
matrix. Physical flash lifecycle, voltage/security writes, actual Modbus slaves,
cross-host remote access, unplug/sleep and long soak are not newly certified.

## Throughput versus gaps

Installed backend, V3/STM32, 30 MHz, Watch only, two-second measurements:

| Requested period | One 32-bit word | Four separated words |
| --- | ---: | ---: |
| 1 us/full speed | 240.7 kHz; repeats 252.9–256.9 kHz | 19.84 kHz |
| 20 us | 49.05 kHz | 19.67 kHz |
| 50 us | 19.87 kHz | 19.62 kHz |
| 100 us | 10.00 kHz | 10.00 kHz |

All integrity counters were zero, but full-speed maximum intervals included
0.778–45.579 ms. Average throughput alone therefore does not pass gap acceptance.
These measurements report all adjacent sample intervals, not only inter-batch
intervals; they cannot be directly compared with the historical inter-batch P99.

Historical firmware comparisons in `v3-watch-raw-frames.md` remain valid for
their bounded runs: single-word throughput 239.6 to approximately 260 kHz and
inter-batch median 48 to 22 us. They are not a maximum-gap guarantee.

## Reception isolation regression

The Windows source bridge uses an independent CDC receive process, but frozen
executables explicitly disabled it. The frozen path therefore permits parent
Python pauses to stop serial draining and eventually apply USB backpressure.

A bounded, same-device A/B experiment reads raw timestamped batches with no RTT.
Without injected pauses, both paths reach approximately 258–259 kHz, with no
interval over 1 ms. Thirty-millisecond parent GIL pauses also fit existing
buffering. Five injected 200 ms pauses expose the difference:

| Reception | Intervals over 1 ms | Maximum interval | Event/queue loss |
| --- | ---: | ---: | ---: |
| Direct, matching old frozen behavior | 5 | 14,958 us | 0 |
| Existing isolated receiver | 0 | 161 us | 0 |

All five direct-reception long intervals occur between batches (10.731–14.958
ms). This demonstrates a backpressure mechanism; it does not establish that
every naturally occurring gap has the same cause, or that 200 ms is a universal
buffer limit.

The fix reuses the existing worker for frozen Windows executables through the
shared internal-process dispatcher. It adds no firmware protocol or sampling
state. Source and frozen CLI/remote entries use the same worker control contract;
port identity is still checked before and after open. Finite queues and explicit
failure behavior remain. Thirty-nine worker/entry/identity tests pass; packaged
execution and natural-load sampling acceptance are pending.
