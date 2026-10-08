# 0.3.0 release handoff

The maintainer explicitly authorized official 0.3.0 publication and V3/V4 main integration on 2026-10-08. Publication passed the repository's CI, clean-main, signed updater and installed-package gates. Official publication and installed-package qualification are complete; the immutable release manifest identifies the distributed bytes.

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

Release UI build identity: production assets use `VITE_APP_BUILD_COMMIT=v0.3.0` for this release, so the displayed release identity is stable across PR and merge commits. The immutable release manifest retains the exact 40-character merged source commit. Use the same value when rebuilding the signed installer from main; verify the installer and Skill contain the same actual compiled Web assets. Fresh clean-clone builds changed generated asset hashes; the release operation preserved that compiled output and used it in both packages, then restored tracked generated files without changing source.

The maintainer initially deferred firmware publication, then supplied final V3.6.0/V4.6.0/HPMLink V4.6.0 UF2 files and explicitly authorized joint publication. Those supplied files were published after format/hash/rollback validation, independently from application assets. Their hashes differ from the earlier HIL candidates: prior measurements describe tested candidates, not a new physical qualification of these supplied binaries. V2.8.1 is unchanged.


## Final package qualification (2026-10-08)

- Source: reviewed main `ec1d2834038b13632d4a88fa3057b5ee5fb65ff2`; host PR30/31 CI passed. V3 main `bdd18d7233aaacc9ab8a1f18778117935ab61e28`, V4 main `ed73ae90689e4454b4c011487786529c2e6a5933`; submodules preserved.
- Full host regression: 4471 Python passed, 2 skipped; 902 GUI tests in 87 files passed, including a second run after clean `npm ci`. Production build, signed NSIS and portable remote service build completed.
- NSIS overwrite installation exited 0. Installed desktop, frozen sidecar and STCP DLL hashes match the extracted installer. Installer SHA-256: `96a264a85de9a1bafee2aa629212ac9b0500094c9ce941ce7c8b49203fb641d2`.
- Local Skill updated from the release ZIP; compiled Web index matches the signed package's build. Skill SHA-256: `b4b5d566ce5240b48232e8f7841935ae0fbe13576b6a78d2b2fa4d161034ddd0`. Algorithm catalog: 7059 targets / 2224 blobs.
- Frozen MCP and installed Skill MCP both exercised `inspect_mcu` and `security_status`; both CLI runtime-status checks passed. These were non-hardware operations. Desktop launched with Windows-only PATH and bundled sidecar processes; native UI reached configuration and enumerated the probe. Browser automation was stopped by its URL-identification guard; the maintainer manually confirmed the installed Web GUI connected to STM32 and displayed v0.3.0. Do not call that an agent-run complete browser regression.
- After the maintainer closed desktop/Web clients, no MKLink process or listener on 8765/8766 remained. This checks eventual release, not a measured shutdown latency.
- Detailed local reports are `release030-*` under the ignored build reports/artifacts directories. The publication command completed all three channels, verified public downloads before index updates, and the two GitHub release asset sets and application/firmware indexes were independently read back.

## Published channels

- Application and Skill: [MicroKeen v0.3.0](https://github.com/MicroKeen/Mklink-AI-Probe/releases/tag/v0.3.0), [legacy GitHub v0.3.0](https://github.com/Aladdin-Wang/Mklink-AI-Probe/releases/tag/v0.3.0), [Gitee v0.3.0](https://gitee.com/Aladdin-Wang/Mklink-AI-Probe/releases/tag/v0.3.0). Each channel contains the same seven release files.
- Firmware: [MicroKeen assets](https://github.com/MicroKeen/Mklink-AI-Probe/releases/tag/firmware-assets), mirrored to the legacy GitHub and Gitee firmware channels. MicroLink V3.6.0, MicroLink V4.6.0 and HPMLink V4.6.0 are available through independent firmware update indexes; V2.8.1 is unchanged.
- Application indexes: MicroKeen `release/latest.json`, legacy GitHub and Gitee `updates/latest.json`; firmware indexes remain on `firmware/latest.json`. Existing client URLs are retained.
- Network TLS failures interrupted several attempts. Retries preserved immutable version assets and mandatory size/SHA-256 checks; indexes were updated only after successful public-download verification.

