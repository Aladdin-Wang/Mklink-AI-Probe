# V4 / HPM6E80 live-write regression — 2026-10-02

## Result

**Verified compatibility writes; seamless live writes are not supported for this target by the current implementation.** The user's V4 reports V4.5.2 and `DUMP_WRITE=1`; it connects over JTAG with HPM's shared IDCODE `0x1000563D`. The exact HPM6E80 identity comes from the user and project, not this shared ID.

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
