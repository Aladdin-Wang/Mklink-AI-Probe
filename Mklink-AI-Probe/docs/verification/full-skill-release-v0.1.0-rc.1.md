# MKLink AI Probe v0.1.0-rc.1 Qualification Report

Release identity: `v0.1.0-rc.1` prerelease from
`feature/online-flash-streaming`. Python package version is `0.1.0rc1`; Tauri
and Cargo versions are `0.1.0-rc.1`.

This report records only evidence produced by an executed command or physical
scenario. Later qualification stages append their rows after the corresponding
hardware, installer, or publication command completes.

## Automated Regression

| Feature / scenario | Layer | Command | Expected | Actual | Duration | Status | Artifact / diagnostic | Cleanup / restoration |
|---|---|---|---|---|---:|---|---|---|
| Python package and backend, final Task 10 run | Automated regression | `python -m pytest -q` | Complete suite passes | 611 passed | 26.41 s | PASS | Pytest terminal summary | No hardware opened by tests |
| Release Node harness, final Task 10 run | Automated regression | `node --test` on the five release harness test files | All predicates and lifecycle tests pass | 49 passed, 0 failed | 222.33 ms | PASS | Node test summary | Lifecycle tests prove browser and final cleanup paths |
| GUI component/runtime suite, initial full run | Automated regression | `npm test` | 232 tests pass with the strict 192 MiB VOFA heap gate | 231 passed, 1 failed; process-wide peak heap growth was 225,903,976 bytes while transport, rendering, ring, and ArrayBuffer predicates passed | 15.83 s | FAIL | Root cause: parallel test files contaminated `process.memoryUsage()` used by the VOFA memory gate | Test process exited; no hardware state |
| GUI memory-gate reproducer | Automated regression | Full `WaveformViewer.test.ts` in three fresh processes | The VOFA gate is stable without unrelated file activity | 34/34 passed in all three runs | 4.64-4.71 s each | PASS | Confirmed measurement contamination rather than retained VOFA data | Test processes exited |
| GUI component/runtime suite, final Task 10 run | Automated regression | `npm test` | All GUI tests pass with file-level isolation and unchanged 192 MiB threshold | 18 files, 238 tests passed | 18.14 s | PASS | Vitest `fileParallelism: false`; strict memory threshold retained | Test process exited; no hardware state |
| Production frontend build | Automated regression | `npm run build` | Type check and production bundle succeed | 140 modules transformed; hashed Worker emitted | 431 ms | PASS | Vite production summary | Tracked generated `gui/dist` refreshed for the packaged application |
| Tauri Rust unit tests | Automated regression | explicit local Cargo `test` | Sidecar selection tests pass | 3 passed, 0 failed | 6.68 s compile/test | PASS | Rust test summary | Test processes exited |
| Tauri Rust check | Automated regression | explicit local Cargo `check` | Crate type-checks | Completed successfully | 0.87 s | PASS | One linker informational warning, listed below | No installed application created |
| AI project memory | Automated regression | `python scripts/ai_memory.py validate` | Durable memory schema is valid | Project memory v1 valid before Task 10 update | <1 s | PASS | Validator timestamp updated with this checkpoint | No hardware state |
| Source whitespace gate | Automated regression | `git diff --check` | No whitespace errors | No errors | <1 s | PASS | Git exit 0 | Not applicable |
| Python regression after physical-HIL fixes | Automated regression | `python -m pytest -q` | Discovery, project-init, and DWARF fixes preserve the full suite | 593 passed | 24.90 s | PASS | Corrective commit `5d41382` | No hardware opened by tests |
| SystemView protocol regressions | Automated regression | Focused parser/backend and GUI task-name tests | SEGGER `TASK_INFO`/`STACK_INFO` layouts decode exactly and false-alignment names are rejected | 50 Python tests and 8 GUI tests passed; task-name gate rejects control, replacement, surrogate, format, empty, overlong, and non-string values | <3 s aggregate | PASS | Raw-packet, RAM-object, backend lifecycle, and display fallback regressions | No hardware opened by tests |
| Final firmware readback and reset regression | Automated regression | Focused `Device.flash`, `Device.reset`, and cleanup tests | `verify=true` reads back HEX/BIN regions before a real MCU reset and cleanup requires `targetVerified` | 6 Python tests plus 3 Node cleanup tests passed; covers multi-segment HEX, BIN, 1024-byte chunk tail, mismatch, skip-readback, and `cmd.reset_chip()` | <1 s aggregate | PASS | Unit tests and four regenerated physical cleanup artifacts | No hardware opened by unit tests |

## Core MKLink

| Feature / scenario | Layer | Command | Expected | Actual | Duration | Status | Artifact / diagnostic | Cleanup / restoration |
|---|---|---|---|---|---:|---|---|---|
| Probe discovery, initial run | Physical HIL | `python -m mklink discover` | Find the connected MKLink without indefinite unrelated-port delay | Timed out while probing Bluetooth/virtual ports first | 120 s limit | FAIL | Root cause and rerun retained in [core artifact](artifacts/rc1-core-mklink.json) | Timed-out child processes were identified by command line and stopped |
| Probe discovery after `5d41382` | Physical HIL | `python -m mklink discover` | Find MKLink through prioritized physical USB probing | Connected MKLink found; identity withheld | 7.0 s | PASS | [core artifact](artifacts/rc1-core-mklink.json) | Command closed the port |
| Probe firmware and target link | Physical HIL | `python -m mklink version --port <configured>` and connection test | Read firmware version and valid target IDCODE | Firmware V4.3.4; valid STM32/Cortex-M3 IDCODE | 1.1 s | PASS | [core artifact](artifacts/rc1-core-mklink.json) | Both commands disconnected |
| Fixture parse, symbols, type, and memory map | Physical HIL | `keil-parse`, `symbols`, `typeinfo`, and `memmap` on the stream fixture | Identify target, controls, and aggregate memory use | STM32F103RE; test controls resolved; Flash 113,200 bytes and RAM 46,344 bytes used | <1 s each | PASS | [core artifact](artifacts/rc1-core-mklink.json) | Read-only host operations |
| Keil fixture build | Physical HIL | Keil batch build of the stream fixture | Zero errors; warning count recorded | 0 errors, 0 warnings | 2 s | PASS | [core artifact](artifacts/rc1-core-mklink.json) | Build outputs remain outside Git |
| Project initialization, initial run | Physical HIL | `python -m mklink project-init --project-root <stream-fixture>` | Refresh configuration using the saved MKLink port | Timed out after discarding the valid saved port and rescanning | >70 s before bounded termination | FAIL | Root cause and rerun retained in [core artifact](artifacts/rc1-core-mklink.json) | Only the two verified project-init child processes were stopped |
| Project initialization after `5d41382` | Physical HIL | `python -m mklink project-init --project-root <stream-fixture>` | Refresh configuration without unnecessary scanning | Configuration refreshed and saved | 0.9 s | PASS | [core artifact](artifacts/rc1-core-mklink.json) | Port remained available |
| Stream fixture program | Physical HIL | `python -m mklink flash --project-root <stream-fixture> --port <configured>` | Load FLM and program the image | Program succeeded | 13.257 s | PASS | [core artifact](artifacts/rc1-core-mklink.json) | Target resumed from programmed image |
| Safe RAM and fault/Flash reads | Physical HIL | `read-ram`, zero `write-ram`, `read-reg SCB.CFSR`, and 64-byte `read-flash` | Read succeeds; zero write verifies; no active fault | All commands passed; CFSR was zero | 2.5 s aggregate | PASS | [core artifact](artifacts/rc1-core-mklink.json) | Dedicated test control remained zero |
| Typed variable watch, initial run | Physical HIL | `watch` for one control and two VOFA variables | Return typed values | Address resolved but type/size were `unknown/0`, so values were not valid | <1 s | FAIL | DWARF qualifier root cause retained in [core artifact](artifacts/rc1-core-mklink.json) | Read-only failure |
| Typed variable watch after `5d41382` | Physical HIL | `watch` for one control and two VOFA variables | Return typed values | One 4-byte integer and two 4-byte floats read successfully | 0.7 s | PASS | [core artifact](artifacts/rc1-core-mklink.json) | Read-only command disconnected |
| CPU debug control | Physical HIL | `halt`, `step`, breakpoint list/clear, `resume` | CPU halts, steps, has no stale breakpoints, and resumes | All predicates passed; 6 hardware slots reported, 0 active | 4.5 s | PASS | [core artifact](artifacts/rc1-core-mklink.json) | CPU resumed; breakpoints cleared |
| Final target and resource restoration | Physical HIL | Zero both arm controls, clear breakpoints, resume, reflash fixture, inspect resources, and typed watch | Controls zero, no owner, target running from fixture | Both controls zero; no owner; restoration program succeeded | 17.7 s | PASS | [core artifact](artifacts/rc1-core-mklink.json) | Target restored and running |

## Packaged Online Flash

| Feature / scenario | Layer | Command | Expected | Actual | Duration | Status | Artifact / diagnostic | Cleanup / restoration |
|---|---|---|---|---|---:|---|---|---|
| Packaged probe enumeration, initial bundle | Packaged physical HIL | Release sidecar `/api/online-flash/probes` | HTTP 200 and one MKLink CMSIS-DAP probe | HTTP 500; pyOCD could not load the bundled `cmsis_pack_manager` native library | 5.2 s | FAIL | Local diagnostic reduced to exception class and Windows loader code; no raw log retained | Sidecar and port were stopped |
| Packaged probe enumeration after builder fix | Packaged physical HIL | Rebuilt release sidecar `/api/online-flash/probes` | HTTP 200 and one MKLink CMSIS-DAP probe | HTTP 200; one MKLink probe returned | 8.0 s | PASS | Builder regression: 5 passed in 0.15 s | Sidecar and port were stopped |
| Complete release bundle | Packaged build | `python skills/tauri-gui-builder/scripts/build.py --bundle` | Self-contained EXE, MSI, and NSIS with source config restored | 140 frontend modules; Tauri EXE, 62.1 MiB MSI, and 60.9 MiB NSIS produced; source version remained `0.1.0-rc.1` | 107.7 s | PASS | Builder output; PyInstaller warnings retained under Known Limitations | Pre-install application used only for HIL |
| HEX HIL, initial harness run | Packaged physical HIL | `packaged_online_flash_probe.cjs` scenario `hex` | Select `STM32F103RC` and complete program/verify/reset | Target catalog normalized the part number to lowercase, while the harness used a case-sensitive test id | 62.2 s | FAIL | Sanitized failure stage `target-selection`; overwritten artifact excluded from final evidence | No flash job started; no target change |
| Verify-mismatch HIL, initial harness run | Packaged physical HIL | `packaged_online_flash_probe.cjs` scenario `verify-fail` | Verify-only job ends with `VERIFY_FAIL` | Batched checkbox clicks observed stale Vue props and left erase/program selected; the altered image was programmed and verified | <6 s | FAIL | Harness root cause covered by sequential-selection regression test | Resource released; known-good BIN was immediately reprogrammed before rerun |
| Online-flash harness regressions | Automated regression | `node --test packaged_online_flash_probe.test.cjs` | Case-normalized target lookup and sequential action selection pass | 6 passed, 0 failed | 75.8 ms | PASS | Node test summary | No hardware opened by unit tests |
| HEX program/verify/reset | Packaged physical HIL | Scenario `hex` | Full ordered state progression succeeds | All required states observed; image hash matched; zero console errors | 6.1 s | PASS | [HEX artifact](artifacts/rc1-online-flash-hex.json) | No active job or target-debug owner |
| BIN program/verify/reset | Packaged physical HIL | Scenario `bin`, base `0x08000000` | Full ordered state progression succeeds | All required states observed; image hash matched; zero console errors | <6 s | PASS | [BIN artifact](artifacts/rc1-online-flash-bin.json) | No active job or target-debug owner |
| Verify mismatch | Packaged physical HIL | Scenario `verify-fail` | Verify-only job fails with `VERIFY_FAIL` | Ordered verify-only states observed; terminal `failed`; error `VERIFY_FAIL` | <6 s | PASS | [verify-fail artifact](artifacts/rc1-online-flash-verify-fail.json) | No active job or target-debug owner |
| Cooperative stop | Packaged physical HIL | Scenario `stop` | Active job reaches `stopped` and disconnects | `stopping`, `disconnecting`, and terminal `stopped` observed | 23.9 s aggregate for final three scenarios | PASS | [stop artifact](artifacts/rc1-online-flash-stop.json) | No active job or target-debug owner |
| Probe busy and handoff | Packaged physical HIL | Scenario `probe-busy` | VOFA ownership yields `PROBE_BUSY`; retry succeeds after release | First job failed with `PROBE_BUSY`; handoff job completed program/verify/reset | Included above | PASS | [probe-busy artifact](artifacts/rc1-online-flash-probe-busy.json) | VOFA stopped; owner released |
| Final boot restore | Packaged physical HIL | Scenario `restore` | Restore HEX, verify matching hash, and reset | Program and verify succeeded; restored SHA-256 matched expected SHA-256 | Included above | PASS | [restore artifact](artifacts/rc1-online-flash-restore.json) | Target restored; no owner or active job |
| Desktop lifecycle cleanup | Packaged runtime | Close main window and poll process/listening-port state | Tauri and sidecar exit; ports 8765 and 9223 release | All processes exited and both listening ports released | 11.3 s | PASS | Lifecycle command summary | No remaining MKLink sidecar process |

## Packaged Stream Performance

Each mode used a fresh target program and a fresh packaged Tauri process. The
ten-minute rates below are sustained release-candidate observations, not new
maximum claims. The existing 30-minute backend rates remain the longer-duration
reference: RTT 12.997 kHz, SystemView 20.093 kEvents/s, VOFA 8.044 kHz, and
SuperWatch 8.024 kHz.

| Feature / scenario | Layer | Command | Expected | Actual | Duration | Status | Artifact / diagnostic | Cleanup / restoration |
|---|---|---|---|---|---:|---|---|---|
| RTT packaged stream | Packaged physical HIL | `packaged_stream_probe.cjs`, mode `rtt` | Strict frame/sequence parity, real curve strokes, capped FPS, pause/resume, zero loss | 15,669,402 items at 26.090 kHz; 62,022 WebSocket/Worker frames matched; 12,568 strokes at 5.23 FPS; all loss counters zero | 600.583 s | PASS | [measurement](artifacts/rc1-packaged-rtt.json), [cleanup](artifacts/rc1-packaged-rtt-cleanup.json) | Browser closed; target dearmed, reprogrammed, read back, and reset; controls zero; Tauri and ports released |
| SystemView packaged stream and Context names | Packaged physical HIL | Mode `systemview`, two user-event pairs/tick | Same transport/render predicates plus printable Context task names | 12,067,495 events at 20.091 kEvents/s; 25,953 frames matched; 61,026 strokes at 25.40 FPS; 1 protocol task name, 0 invalid; parser and stable-window loss zero | 600.632 s | PASS | [measurement](artifacts/rc1-packaged-systemview.json), [cleanup](artifacts/rc1-packaged-systemview-cleanup.json) | Browser closed; target dearmed, reprogrammed, read back, and reset; controls zero; Tauri and ports released |
| SystemView Context fix short revalidation | Packaged physical HIL | Current packaged EXE, 20-second SystemView gate from the configured stream project | No corrupt Context names and complete transport/render cleanup | 414,568 events at 20.069 kEvents/s; 885 WebSocket/Worker frames matched; 0 parser drops; 1 task name and 0 invalid names | 20.657 s | PASS | Sanitized temporary gate output, intentionally not committed | Backend stopped, zero clients/owner, target dearmed, browser closed, process and ports released |
| VOFA packaged stream | Packaged physical HIL | Mode `vofa`, two symbols, fastest supported 10 us request | Visible curves at <=30.5 FPS with collection continuing during render pause | 4,826,656 items at 8.037 kHz; 150,833 frames matched; 216,272 strokes at 25.72 FPS; all loss counters zero | 600.567 s | PASS | [measurement](artifacts/rc1-packaged-vofa.json), [cleanup](artifacts/rc1-packaged-vofa-cleanup.json) | Browser closed; target reprogrammed, read back, and reset; controls zero; Tauri and ports released |
| SuperWatch packaged stream | Packaged physical HIL | Mode `superwatch`, two-symbol dump-memory sampling | Visible curves at <=30.5 FPS with strict transport and cleanup evidence | 4,736,448 items at 7.887 kHz; 148,611 frames matched; 216,412 strokes at 25.74 FPS; all loss counters zero | 600.569 s | PASS | [measurement](artifacts/rc1-packaged-superwatch.json), [cleanup](artifacts/rc1-packaged-superwatch-cleanup.json) | Browser closed; target reprogrammed, read back, and reset; controls zero; Tauri and ports released |

SystemView produced an initial target-overflow baseline while attaching to the
already active high-rate trace. The gate waited for those counters to stabilize
before starting its 600-second measurement and then observed zero additional
target overflow or dropped packets. The baseline is retained in the artifact
and is not represented as stable-window loss.

The Context corruption had three independent sources and defenses. The parser
previously decoded `TASK_INFO` in the wrong field order and omitted the fourth
`STACK_INFO` value, so later bytes could be interpreted as names. The RAM
fallback also scanned arbitrary offsets and could accept unrelated ASCII such
as `V1`. The corrected path follows the bundled SEGGER encoder exactly,
requires an RT-Thread Thread object before accepting an inline RAM name, avoids
disruptive RAM resolution once protocol names exist, and rejects invalid names
again at the GUI boundary with a hexadecimal task-id fallback.

## Security And Artifact Scans

| Feature / scenario | Layer | Command | Expected | Actual | Duration | Status | Artifact / diagnostic | Cleanup / restoration |
|---|---|---|---|---|---:|---|---|---|
| Tracked firmware and installer scan | Automated regression | `git ls-files` for Pack, firmware, executable, installer, and log extensions | No prohibited release binaries or raw logs tracked | No matches | <1 s | PASS | Empty result | Not applicable |
| Bundled Pack scan | Automated regression | Search `gui/src-tauri/target/release` for `*.pack` | No Pack archive bundled | No matches | <1 s | PASS | Empty result | Not applicable |
| Sanitized docs and harness scan | Automated regression | Git grep for full probe IDs, COM ports, and local user paths in `docs` and `_maintainer` | No unmasked hardware or username data | No matches | <1 s | PASS | Git grep exit 1 means no match | Not applicable |

## Known Limitations

- `npm audit` reports 2 high-severity vulnerabilities and 0 critical
  vulnerabilities in the current locked development dependency graph. No
  lockfile-changing automatic remediation was applied during qualification.
- `npm ci` reports the existing deprecated `glob@10.5.0` warning.
- Vue/Vite reports existing HTML structure warnings where `<tr>` is a direct
  child of `<table>` in `SymbolsTab.vue` and `ConfigView.vue`. The tests and
  production build pass, but the markup should receive a later `<tbody>`
  cleanup.
- Rust emits one Windows linker informational message while producing the test
  import library; `cargo test` and `cargo check` both exit successfully.
- `discover` still performs active confirmation across multiple physical USB
  CDC interfaces when descriptor identity is generic. The corrected order is
  bounded in practice on the qualified MKLink, but descriptor-specific
  matching would be faster if a stable vendor/product identity is assigned.
- The CLI has no standalone target reset command. Core HIL used a final reflash
  of the same fixture image to provide reset and restoration evidence.
- Serial transmit/receive and Modbus RTU require external fixtures. They may be
  reported as `NOT ESTABLISHED` if those fixtures are unavailable, but this
  does not weaken online-flash or high-throughput stream gates.
