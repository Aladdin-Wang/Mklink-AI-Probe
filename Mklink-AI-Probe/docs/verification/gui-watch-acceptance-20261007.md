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

## Windows queued reception and V3 priority follow-up

The first frozen isolation build still failed a longer loaded run with a
heartbeat response timeout. A separate run stopped receiving valid target
samples while the GUI remained running and its parser error counter increased.
Non-retryable Watch target status now stops acquisition with an explicit error
instead of silently discarding every error event indefinitely. Neither failed
run qualifies the full GUI acceptance gate.

V3 firmware b19c470 orders DAP/USB/multiplex acquisition before background work.
Modern eight-channel RTT remains inside the multiplex task. Firmware-only
testing reduced the intra-batch maximum from 130 to 63 us, but retained one
16.489 ms inter-batch stall in 30 seconds.

The isolated worker previously posted only one small read at a time. Short
descheduling leaves no large outstanding request, so CDC backpressure can stop
sampling even though the application-level receive queue is not full. Controlled
8-second runs with a 30 ms receive-thread pause approximately once per second:

| Receive path | Intervals over 1 ms | Maximum interval |
| --- | ---: | ---: |
| Existing single read, 4 KiB driver buffer request | 7 | 22,368 us |
| Single read, 1 MiB driver buffer request | 7 | 22,478 us |
| Queued reads, production implementation | 0 | 111 us |

Windows now keeps eight 16 KiB overlapped reads posted (128 KiB fixed storage).
Each owns its event/buffer until completion or cancellation; results are consumed
in submission order. A quiet reply has a short interval timeout. Reset cancels
and reaps old reads before purging and starting a new generation; shutdown reaps
before closing the port. The downstream worker queue remains bounded to 16 MiB.
The implementation follows the ownership requirements in Microsoft's
[ReadFile documentation](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-readfile).

Natural single-word sampling for 45 seconds then received 11,976,227 samples at
267,106 samples/s: maximum adjacent interval 91 us, intra-batch maximum 64 us,
zero intervals over 1 ms, zero event/queue loss. These are bounded measurements,
not a guarantee under arbitrary host stalls or deliberate DAP ownership.

130 protocol/worker/Windows request-ownership tests passed. Actual Windows
virtual-port testing passed three paced 512 KiB byte-for-byte receive cycles,
bidirectional commands, reset generation, reconnect and parent-stdin EOF cleanup;
normal close released the port in approximately 5 ms. An initial unpaced 512 KiB
virtual-port burst overflowed that test path; it is not counted as passing.
V3 eight-channel RTT with Watch also passed 256-byte/channel target hashes, and
OpenOCD halt/step/resume invalidated both streams and allowed explicit restart.
Updated frozen installation acceptance remains pending at this checkpoint.

### Downstream decode backlog

The queued-read-only frozen build ran 95 seconds without heartbeat failure but
still dropped 35,490 bytes from the bounded Watch event queue, producing three
apparent waveform gaps (maximum 5.736 ms). It therefore did not pass the end-to-end
no-gap gate, despite the raw CDC improvement.

The shared SuperWatch manager now requests compact samples referencing validated
batch bytes. Compiled scalar offsets decode directly from that payload, avoiding
per-sample region lists, tuples and byte copies. Public/default dump frames retain
their original representation. Alignment, signed subwords, cross-word values,
multiple regions, bitfields, truncated data and timestamp rollover are checked.
The related suites pass 296 tests. A local 1,016,000-sample expansion/decode
benchmark improved from 997,881 to 1,286,469 samples/s (approximately 29%).

The complete source backend plus binary WebSocket path then passed 95 seconds:
25,300,217 received samples, 267,443 samples/s, maximum adjacent interval 104 us,
zero intervals over 1 ms, zero Watch queue drops and zero WebSocket drops. Final
state was running, not a stalled graph. Updated frozen build verification remains
separate. The first NSIS attempt returned Windows "operation cancelled by user";
the installed desktop remains old until system authorization is completed.

### Final packaged backend checkpoint

The c9d2e502 NSIS payload was extracted without replacing the installation and
its frozen backend tested for 95 seconds through the binary WebSocket path:
25,303,765 received samples, 267,493 samples/s, maximum adjacent interval 94 us,
zero intervals over 1 ms, zero Watch queue drops and zero WebSocket drops. Final
state was running with no error; the test then stopped its own capture and the
backend exited. This verifies the packaged backend, not multi-GUI rendering or
an installed-desktop upgrade. Package validation matched all 39 GUI files and
the built-in 7,059-target/2,224-blob algorithm manifest. Local Skill was replaced
with c9d2e502 and its GUI files match the package build. Windows installation
authorization is still pending; the installed desktop remains f5bba9b5.

### Installed desktop and Chrome acceptance

The c9d2e502 NSIS update completed with exit code 0. All three installed native
files match the extracted candidate by SHA-256. The actual desktop and Chrome
Web GUI display v0.3.0/c9d2e502. All 2,520 files in the local Skill archive match
the installed Skill. This supersedes the installation-pending checkpoint above.

With two probes present, explicitly selecting V3 connected on the first attempt;
Chrome joined the same installed backend. Both GUIs rendered the single uint8
SuperWatch signal while a third shared client inspected the binary stream. The
collector ran for 95 seconds including pre-start waiting: 16,799,475 samples span
approximately 63 seconds of acquisition, 266,821 samples/s, maximum adjacent
interval 91 us, zero intervals over 1 ms. Watch/parser, binary and WebSocket
drop counts were zero; final acquisition state was running. The observing client
then detached without stopping the GUI acquisition.

On both real surfaces, pause -> time-axis zoom -> Start restored a full-width
waveform with the narrowed time window. Desktop Stop retained the last waveform;
further zoom -> Start again retained the narrower window and rendered across
the plot. Closing the test Chrome tab left the desktop acquisition running.
The desktop's 1,200-pixel default width still clips some toolbar badges; this
known layout issue is not a sampling failure and is not fixed in this acceptance.

These are bounded V3/STM32 installed-surface checks, not a full-product regression,
V4 priority qualification or a long soak. Earlier OpenOCD and RTT8 coexistence
evidence remains separate. No firmware or application source changed here.

### Cross-window stop/restart correction

The previous installed acceptance did not exercise a peer restart after the
other window had issued Stop. That path closed the initiating window's binary
subscription and status polling, so it could not follow the next shared start.
SuperWatch now retains its subscription and renews status polling on a successful
stop, preserving the last curve. A shared stopped status also clears the local
display-pause latch. Start while locally paused and still sampling resumes the
display without submitting another acquisition start. Ownership protection stays
unchanged. The waveform suite passes 111 tests and the production build passes.

A bounded two-Chrome test of the new production frontend against the installed
backend observed shared status following and the formerly stopped window receiving
50,000 points after a peer start. Temporary preview WebSocket proxy problems and
a subsequent DAP target-change invalidation prevented a clean full live pass;
this is not recorded as installed acceptance. A new local package and installed
desktop/Web validation are pending.

### a226562f installed cross-window acceptance

- Local unsigned NSIS overwrite installation exited 0; all three executable/DLL payload hashes matched the extracted installer. Frozen sidecar contains the exact 39 GUI files and algorithm catalog with 7,059 targets / 2,224 blobs. Local Skill updated and 2,520 package files matched.
- Actual installed desktop and local Chrome shared one V3/STM32 backend. Web Start -> desktop receives; desktop Stop -> Web stops; Web Start -> desktop receives again. The reverse Web Stop -> desktop Start -> Web receives also passed.
- Desktop display Pause left Web running; Web Stop cleared the desktop pause state. Restart restored both displays. Web Pause followed by Start resumed local display without clearing history.
- Repeated desktop Stop / Web Start with a 1 us requested interval and two float signals restored both waveforms. Transport/backend drops were zero at the final status observation. This is a short synchronization acceptance, not a new maximum-rate or long-duration benchmark.
- Capture stopped at completion; desktop and Web left available for user inspection. Firmware unchanged. Existing narrow-window toolbar clipping remains outside this fix.
