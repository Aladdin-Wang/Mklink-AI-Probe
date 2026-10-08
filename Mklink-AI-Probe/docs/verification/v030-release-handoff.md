# 0.3.0 release handoff

The maintainer explicitly authorized official 0.3.0 publication and V3/V4 main integration on 2026-10-08. Publication must still pass the repository's CI, clean-main, signed updater and installed-package gates. This document is preparation evidence; confirm completion from the immutable release and its manifest.

## Product scope

Shared per-probe CDC runtime; GUI/AI/CLI/MCP coexistence; eight equal RTT channels; concurrent RTT/SuperWatch; unified local/remote dashboard; browser AXF upload; AI-controlled presentation when useful. No WinUSB, no SDK/submodule changes. V3 has no display or HPM support. V4 adds HPM BIN/HEX paths and qualified JTAG context borrowing. Runtime ownership is never expired merely because a debugger is idle.

## Firmware evidence

- V3: stage95 physical STM32 tests covered OpenOCD program/verify/halt/step/resume and recovery, eight RTT up/down channels and boundary conditions, installed multi-client isolation. Keil download/automatic recovery passed; native Keil pause/step remains unqualified. 30-second no-DAP one-word sampling measured 269477 samples/s, maximum adjacent 79 us, no measured millisecond gaps or transport drops. Native application suites passed again before integration.
- V4/STM32: stage94 Keil download, run/pause/step/resume/exit with RTT8/Watch passed. No-DAP one-word 30-second run measured 271577 samples/s, maximum 73 us, no measured millisecond gaps.
- V4/HPM5301: stage97 final diagnostic-free firmware measured 136525 samples/s versus 129028 before, maximum 84 us versus 188 us, with no measured millisecond gaps or transport drops. Final OpenOCD coexistence passed. Real SES download/main/step/run/pause was exercised on the preceding diagnostic build with the same coexistence logic; zero initialized RAM-pattern mismatches. This is not a full final SES qualification.

These rates are individual measurements with RTT off and one four-byte signal. They are not guaranteed performance for arbitrary signals or simultaneous debugging. DAP priority deliberately permits gaps during downloads.

## Known issues and next work

1. HPM/SES may terminate its server without DAP_Disconnect, leaving a reservation and a halted target. Framed MUX remained responsive, but a new legacy handshake could wait. After confirming SES is disconnected, a deliberate OpenOCD init/resume/shutdown recovered the test setup; USB replug is the user-facing fallback. Do not implement an arbitrary idle timeout that steals a live debugger's context.
2. SES “Failed to read priv register” was also observed before the coexistence changes. Repeat final firmware's full SES matrix, including acquisition started while already debugging, RTT downlink and flash readback under load.
3. Long-duration validation remains paused at user request. Cross-physical-host remote operation, all target/debugger combinations, destructive protection/power boundaries and true physical Modbus fixtures retain the detailed matrix's unverified status.
4. Website handoff was previously sent to the user's Labs task “来财”. This release document may be used for website content, but website deployment is not claimed complete here.

## Release verification ledger

Host full Python/GUI regression, production assets, exact merged source commit, signed NSIS and installed/frozen MCP verification are recorded in the release operation's local `release030-*` reports. The public release manifest records source commit, sizes and hashes; it is the source of truth for the distributed bytes. Never move an already published version tag to incorporate later documentation or fixes.

Release UI build identity: production assets use `VITE_APP_BUILD_COMMIT=v0.3.0` for this release, so the displayed release identity is stable across PR and merge commits. The immutable release manifest retains the exact 40-character merged source commit. Use the same value when rebuilding the signed installer from main; verify tracked production assets remain byte-identical.

The maintainer explicitly deferred upgraded firmware publication. V3/V4 source main integration is complete, but do not upload new UF2 assets or update firmware channel indexes as part of 0.3.0. Firmware-dependent features require a separately supplied matching firmware.
