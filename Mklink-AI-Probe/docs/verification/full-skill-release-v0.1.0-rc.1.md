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
- Serial transmit/receive and Modbus RTU require external fixtures. They may be
  reported as `NOT ESTABLISHED` if those fixtures are unavailable, but this
  does not weaken online-flash or high-throughput stream gates.
