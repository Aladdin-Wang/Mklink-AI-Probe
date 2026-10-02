# V4 / HPM6E80 live-write regression — 2026-10-02

## Resolved: V4 HPM channel and hardware verification

The V4 candidate now advertises `DUMP_WRITE_HPM=1` separately from ARM's
`DUMP_WRITE=1`. JTAG/HPM transactions use the existing RISC-V sysbus read/write
helpers at complete acquisition frame boundaries, without stopping acquisition
or halting the target CPU. ACK, CRC, duplicate suppression and unknown-outcome
handling retain the existing protocol. V2 and V3 were neither modified nor
upgraded in this follow-up; all eight previously recorded source hashes match.

The firmware bounds writes to HPM6E80 SDK internal RAM windows; the host also
intersects these with writable RAM from the target ELF/profile. Flash,
peripherals, window overflow and unsupported widths are rejected. External SDRAM
is outside this live channel. A shared JTAG ID is not exact chip identification;
this evidence qualifies the attached HPM6E80, not every HPM part. Old HPM firmware
continues through compatibility writes, and the UI now explains that firmware
or target-address eligibility may cause a sampling gap.

### Build and tests

- V4 built with SEGGER Embedded Studio 8.24; native control tests exercise ARM
  and HPM dispatch, four widths, readback and invalid address/interface cases.
- Actual candidate upgrade completed and the new HPM capability was read back.
  UF2: 1,609,728 bytes; SHA-256
  `2dfeb87b8f2c08f4a22dfbcf03f1c035d2036a2424cef5cd38db73038a1497d0`.
- Python parser/session/manager/API tests: **247 passed**. GUI variable panel,
  waveform viewer and symbol catalog tests: **128 passed**. Production build passed.
- Exact firmware task patch, pre-edit backups, source hashes, candidate and raw
  evidence are retained locally under `.build/reports/live-write-hpm-port`.
  Firmware is in its separate checkout; this host PR does not publish firmware.

### HPM6E80 measurements, 30 MHz JTAG

The complete 4,096-byte `memory_test` fixture was checked against its source
pattern, backed up and independently verified after each rate. All 16 write and
restore transactions across 1/2/4/8-byte widths passed.

| Capture | Complete samples | Mean interval | Maximum interval |
| --- | ---: | ---: | ---: |
| Requested 1 ms | 1,341 | 1,000.001 us | 1,198 us |
| Requested 1 us (fastest) | 147,960 | 8.942 us | 369 us |

Timestamps strictly increased. Parser CRC errors, dropped frames and firmware
error/drop flags were zero. ACK latency was 3.56–4.48 ms. This does not promise
zero bus jitter or atomic multiword writes. An initial evidence-analysis attempt
could not bracket a startup ACK before its first captured sample; full fixture
restoration had already succeeded. The completed rerun brackets every write.

The real SuperWatch manager returned **mode=live** for gain changes
`0.05 → 0.125 → 0.0625 → original`. Across 1,310 samples the maximum interval was
**1.218 ms**, versus **591.719 ms** before the fix. Intervals bracketing the three
writes were 1.134, 1.117 and 1.218 ms. Worker identity, time origin and metadata
epoch stayed unchanged. Paused-state writes preserved pause; resume worked;
`wave_tick` advanced and the build guard stayed intact. All original gain bytes
were independently read back after stopping.

### Real Web GUI

Chrome watched `wave_reference`, `wave_response` and `response_gain` at 1 ms.
While running, the variable editor wrote gain 0.125 and showed verified readback;
the live waveform displayed the corresponding device-timestamped write marker.
The status snapshot contained 19,495 complete samples, one WebSocket subscriber,
`mode=live`, zero read errors, zero parser CRC/dropped-frame counters, and zero
stream/binary publication drops. The local screenshot was visually inspected.
Parser preamble bytes were discarded, not counted as corrupt sample frames.
Gain was restored to the original `cdcc4c3d` bytes and independently read back.
The connection, task browser session and test backend were then closed.

No target application flash, VCC, official release assets or V2/V3 firmware were
changed in this follow-up. The earlier regression below is preserved as before-fix
evidence; its support limitation is resolved for the measured V4/HPM6E80 setup.


## Before the HPM fix

**Verified compatibility writes; seamless live writes are not supported for this target by the implementation tested in the initial regression.** The user's V4 reports V4.5.2 and `DUMP_WRITE=1`; it connects over JTAG with HPM's shared IDCODE `0x1000563D`. The exact HPM6E80 identity comes from the user and project, not this shared ID.

At the confirmed 30 MHz JTAG profile, writing `response_gain` while capturing returns `mode=legacy-gap`. The capture worker, time origin and metadata epoch remain unchanged, but acquisition stops while command-mode write/readback runs. The final run recorded 325 complete three-variable samples, strictly increasing timestamps, and a maximum gap of **591.719 ms**. This does not meet the ARM live-write timing behavior established in the other reports.

## Cause

- Host `DumpMemoryStreamSession.request_write` accepts only ARM SRAM addresses in `[0x20000000, 0x40000000)`.
- `SuperWatchStreamManager` therefore routes the HPM variable at `0x012055C4` through its compatibility transaction, despite the probe advertising a generic capability.
- The V4 firmware receiver/service also requires `DAP_PORT_SWD` and the same ARM address window, and executes SWD-specific read/write calls. Removing only the host guard would cause firmware rejection, not HPM support.
- Status `live_write_supported` currently exposes probe capability rather than target eligibility. The compatibility notification describes older firmware, which is incomplete for this case. A future fix should distinguish protocol capability, target/interface support and operation-specific fallback.

HPM support needs target-appropriate RAM validation plus JTAG/RISC-V sysbus write/readback in the acquisition owner, followed by actual HPM timing and waveform verification. ARM evidence must not be presented as HPM support.

## Actual checks

The user's SDK 1.12.1 `hello_world` project provides a FreeRTOS waveform fixture. The current ELF/BIN is 51,244 bytes, BIN SHA-256 `57169b40aa606a8c70b5761215ee8122a3000e9cb0721a434e8961c4d18ec025`. Initial whole-BIN comparison found 7,008 different bytes: every difference was zero padding in BIN versus erased `0xFF` in flash. All file-backed allocated flash ELF sections matched exactly; this was not a code mismatch. The build marker also matched `0x20260919`.

The real manager watched `response_gain`, `article_build_id` and `wave_tick`. It wrote gain `0.05 → 0.125 → 0.0625 → original` (float32 original `0.05000000074505806`), followed by an original-value write while paused. All returned verified readback; all requested gain values appeared in captured data. The marker stayed intact, pause was preserved, resume succeeded, and a command-mode independent read after stop matched the original bytes. CRC errors, parser dropped frames, firmware error/drop flags and binary publication drops were zero. The compatibility gaps are visible in timestamps despite those counters being zero. ACK write timestamps are unavailable in this mode. No browser rendering or WebSocket subscriber test was performed in this follow-up.

Initial `wave_tick` snapshots were stationary with boot stage 4 and zero assertion/trap records. Later snapshots and the final capture showed increasing waveform and telemetry counters. An attempted `cmd.reset_chip()` returned `NameError` because the running Pika binding does not export that name; it performed no reset and was not retried. The reason for the earlier stationary snapshots is not established. No target/probe firmware was flashed, no power was changed, and no target reset actually ran in this session.

Original gain was restored, test connections released, and raw observations retained locally. This is a bounded feature regression, not a claim that all HPM functionality or real-time writes passed.
