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
