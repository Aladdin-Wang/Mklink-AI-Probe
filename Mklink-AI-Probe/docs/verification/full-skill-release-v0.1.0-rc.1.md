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
| Python package and backend | Automated regression | `python -m pytest -q` | Complete suite passes | 590 passed | 39.79 s | PASS | Pytest terminal summary | No hardware opened by tests |
| Release Node harness | Automated regression | `node --test` on the four release harness test files | All predicates and lifecycle tests pass | 19 passed, 0 failed | 193.79 ms | PASS | Node test summary | Lifecycle tests prove browser cleanup paths |
| GUI component/runtime suite, initial full run | Automated regression | `npm test` | 232 tests pass with the strict 192 MiB VOFA heap gate | 231 passed, 1 failed; process-wide peak heap growth was 225,903,976 bytes while transport, rendering, ring, and ArrayBuffer predicates passed | 15.83 s | FAIL | Root cause: parallel test files contaminated `process.memoryUsage()` used by the VOFA memory gate | Test process exited; no hardware state |
| GUI memory-gate reproducer | Automated regression | Full `WaveformViewer.test.ts` in three fresh processes | The VOFA gate is stable without unrelated file activity | 34/34 passed in all three runs | 4.64-4.71 s each | PASS | Confirmed measurement contamination rather than retained VOFA data | Test processes exited |
| GUI component/runtime suite after `e80d5e0` | Automated regression | `npm test` | All GUI tests pass with file-level isolation and unchanged 192 MiB threshold | 18 files, 232 tests passed | 16.18 s | PASS | Vitest `fileParallelism: false`; strict memory threshold retained | Test process exited; no hardware state |
| Production frontend build | Automated regression | `npm run build` | Type check and production bundle succeed | 140 modules transformed; hashed Worker emitted | 371 ms | PASS | Vite production summary | Generated `gui/dist` remains untracked build output |
| Tauri Rust unit tests | Automated regression | `cargo test` | Sidecar selection tests pass | 3 passed, 0 failed | 59.44 s | PASS | Rust test summary | Test processes exited |
| Tauri Rust check | Automated regression | `cargo check` | Crate type-checks | Completed successfully | 0.71 s | PASS | One linker informational warning, listed below | No installed application created |
| AI project memory | Automated regression | `python scripts/ai_memory.py validate` | Durable memory schema is valid | Project memory v1 valid | <1 s | PASS | Validator timestamp `2026-07-15T01:00:45+08:00` | No state change |
| Source whitespace gate | Automated regression | `git diff --check` | No whitespace errors | No errors | <1 s | PASS | Git exit 0 | Not applicable |
| Python regression after physical-HIL fixes | Automated regression | `python -m pytest -q` | Discovery, project-init, and DWARF fixes preserve the full suite | 593 passed | 24.90 s | PASS | Corrective commit `5d41382` | No hardware opened by tests |

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
