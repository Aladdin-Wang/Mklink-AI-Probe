# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-16T03:12:38+08:00`
- 分支：`feature/online-flash-streaming`
- HEAD：`v0.1.0-rc.1 -> 1c7c5aa; the final documentation commit contains this memory`
- 远端 HEAD：`release tag and branch publication checkpoints pushed; final documentation push is the remaining action in this commit`
- 工作树：generated repository-local artifacts removed; external release bundle retained; final handoff commit pending
- 当前任务：v0.1.0-rc.1 published and independently verified; collect external tester feedback
- 状态：`complete`

## 里程碑

- **Online flash Tasks 1-12** — `complete`。docs/verification/online-flash-hil.md
- **High-throughput Task 1 binary protocol** — `complete`。Python 10 passed; TypeScript 8 passed
- **High-throughput Task 2 bounded StreamHub** — `complete`。Unique owner loop, immutable batch, generation/pending callback lifecycle, stale callback isolation.
- **High-throughput Task 3 authenticated binary WebSocket** — `complete`。Invalid JSON shapes and binary authentication frames close 1008 without leaks; sequence, item_count, and timestamp_ns are shared per fan-out batch.
- **High-throughput Task 4 Worker-owned stream buffers** — `complete`。Fixed-capacity typed ring, transferable Worker frames, bounded reconnect lifecycle, and generation/ticket readiness acknowledgements isolate stale sockets.
- **High-throughput Task 5 envelope, scheduler, and benchmark** — `complete`。Typed min/max envelope, one 30 FPS scheduler, strict sequence/drop accounting, responsive cancellation, and deterministic sample-rate benchmark.
- **High-throughput Task 6 SystemView binary migration** — `complete`。Recording-first fixed 48-byte events, bounded O(1) Worker rings, nested ISR contexts, exact BigInt ticks, pixel-bounded interval envelopes, binary UI at 30 FPS and event table at 5 Hz.
- **High-throughput Task 7 VOFA binary migration** — `complete`。Validated aligned source reads, atomic sample-major batches, Worker min/max envelopes, O(1) extrema and O(log N) interactions, bounded DOM work, live telemetry, pause-safe rates, and SuperWatch legacy isolation.
- **High-throughput Task 8 RTT and SuperWatch binary migration** — `complete`。RTT raw and numeric binary records, bounded virtual log, SuperWatch versioned metadata and sample generations, nonblocking hardware reads, late-subscriber metadata replay, and transactional dashboard cancellation/rollback without probe lease leaks.
- **High-throughput Task 9 performance and HIL qualification** — `complete`。All four 30-minute backend HIL gates passed at qualified stable rates. Only RTT retained a measured overload boundary; VOFA/SuperWatch used the fastest supported request and SystemView used pairs=2/tick. Real Edge visible/pause/resume gates passed with <=30 FPS and zero measured loss; hidden state was not established. Strict packaged Tauri RTT ran 300.027 seconds with exact WebSocket/Worker frame and sequence parity, zero loss, complete cleanup, and CDP browser release. Deliverable commit cc8282f is pushed.
- **Release qualification Task 10 packaged stream gates** — `complete`。Formal packaged measurements: RTT 26.090 kHz, SystemView 20.091 kEvents/s, VOFA 8.037 kHz, SuperWatch 7.887 kHz. SystemView Context parser, fixed-layout RT-Thread object validation, backend fallback behavior, GUI sanitization, and overlong-name gate are implemented. Device.flash reads multi-segment HEX/BIN regions back before reset, Device.reset sends cmd.reset_chip(), and all four regenerated cleanup artifacts contain targetVerified=true plus targetReset, zero controls, Tauri exit, and port release.
- **Release qualification Task 11 Windows installer lifecycle** — `complete`。The API binds inspected images to the selected target and recomputes reliable FLM coverage before program, requiring exact covered sectors. Windows Job creation/assignment failure cannot retain an untracked sidecar child. Final NSIS installed-GUI App HEX verify and expected VERIFY_FAIL at 0x08000000 pass without writing the target. Final unsigned MSI SHA-256 is 6612ee8427c18246d25928d9b2ed8f745f440ec30f258215c880c1af5e2a975e; NSIS is 6caef8fe36b3a29846c0ceff75a519e4b6e81bc30e03e5c3bdb0dd507e97717f.
- **Release qualification Task 12 assets and final reviews** — `complete`。Release metadata contains no local source paths. SHA256SUMS is sorted by asset name using casefold order. Task 13 must regenerate manifest.source_commit after the final release commit and upload every manifest-listed payload plus manifest/checksums.
- **Release qualification Task 13 GitHub publication** — `complete`。MSI SHA-256 6612ee8427c18246d25928d9b2ed8f745f440ec30f258215c880c1af5e2a975e; NSIS SHA-256 6caef8fe36b3a29846c0ceff75a519e4b6e81bc30e03e5c3bdb0dd507e97717f.

## 验证证据

- **Online flash automated**：Python 388 passed; GUI 69 passed; Vite 134 modules; no tracked or bundled .pack
- **Online flash HIL**：MKLink filter, Pack index, on-demand GD32 DFP, restart cache, STM32F103RC HEX/BIN program+verify, expected VERIFY_FAIL, cooperative stop, VOFA PROBE_BUSY handoff, target boot firmware restored
- **Tauri**：release EXE, MSI, and NSIS bundles were generated during Task 9; the refreshed packaged WebView2 RTT gate ran 300.027 seconds with 31010 WebSocket frames exactly matching 31010 Worker frames and final sequence 34334, 7832827 items, 5.27 FPS, zero backend/frontend/sequence loss, backend stopped, zero clients, no RTT resource owner, and successful target-dearm readback
- **Current Python baseline**：583 passed in 26.36 seconds after Task 9 browser/render fixes and evidence updates
- **Current GUI baseline**：18 files / 231 tests passed; Vite production build transformed 140 modules after SystemView pause lifecycle, offline import recovery, follow-FPS, SuperWatch pause, and deep-link fixes
- **Task 9 release harness**：13/13 Node tests passed, including exact transport/cleanup predicates and CDP browser release after both successful and failed cleanup
- **Task 5 local transport benchmark**：10 seconds at 10 kSamples/s and 8 channels produced/consumed 100000/100000 with zero drops and sequence errors; elapsed 10.001s; responsive 1800-second cancellation; real overflow accounting matched exactly
- **Task 6 SystemView soak**：Hub/codec 600 seconds at 50 kEvents/s consumed 30000000/30000000 fixed 48-byte events with zero drops/errors, 2.4036 MB/s, queue high-water 1, RSS growth 430080 bytes; realistic Worker 60 seconds processed 3000000 events at 50002.8 events/s with fixed 100000 buffer, 30 FPS visible requests, output <=1600 for 800 pixels, zero errors
- **Task 7 VOFA synthetic qualification**：Python synthetic transport 1800 seconds at 10 kSamples/s and 8 channels consumed 18000000/18000000 with zero drops/errors and working-set growth 40960 bytes. Accelerated jsdom same-thread harness processed 60 seconds of data (600000 samples), 1800 visible requests, output <=5120 for 320 pixels x 8 channels, zero ring full scans/drops/errors; this is not wall-clock browser, WebSocket, Web Worker, Python backend, or HIL evidence.
- **Task 8 RTT and SuperWatch synthetic qualification**：Python local StreamHub/codec soaks ran 600 seconds each at 10 k records/s: RTT consumed 6000000/6000000 with zero drops/sequence errors at 123599.7 B/s and queue high-water 1; SuperWatch 8-channel consumed 6000000/6000000 with zero drops/sequence errors at 403599.4 B/s and queue high-water 1. Accelerated jsdom same-thread gates processed RTT 6000 records with a 5000-line bound and DOM below 40 rows, and SuperWatch 600000 x 8 samples with a 200000-sample ring and envelope <=5120 values. These are not real wall-clock browser, WebSocket, Web Worker, packaged application, or MKLink HIL results.
- **Task 9 backend MKLink HIL**：Four authenticated binary WebSocket runs completed 1800 seconds each with zero measured sequence/backend loss: SystemView 20093.43 events/s, VOFA 8044.33 samples/s, RTT 12997.51 samples/s, SuperWatch 8023.71 samples/s. These are qualified stable rates; only RTT retained a measured overload boundary.
- **Task 9 real Edge frontend HIL**：SystemView, VOFA, RTT, and SuperWatch loaded hashed Workers and binary WebSockets; visible and resumed rendering stayed <=30 FPS; pause kept backend and Worker collection advancing with zero Canvas frames and zero measured frontend/sequence/backend loss. Peak Edge process-tree working sets were 798273536, 736600064, 709496832, and 733954048 bytes respectively. Hidden state was not established on Edge 130 and is not claimed as HIL PASS.
- **Task 10 packaged stream HIL**：Four 600-second packaged measurements pass with exact WebSocket/Worker parity, real canvas strokes, <=30.5 FPS, pause/resume evidence, zero measurement loss, and validated fixtures. Four regenerated cleanup artifacts independently prove target reflash, actual Flash readback, reset, zero controls, Tauri exit, and API/CDP port release.
- **SystemView Context corruption**：Root causes fixed at protocol, RAM fallback, backend lifecycle, and GUI display boundaries. Focused Python 50 and GUI 8 tests pass. Fresh packaged HIL ran 20.657 seconds with 414568 events, zero parser drops, one valid protocol task name, zero invalid names, and complete cleanup.
- **Current full automated baseline**：Python 618 passed in 24.91s; Node release harness 51 passed; GUI 18 files / 241 tests passed in 16.66s; Vite transformed 140 modules; Rust 5 passed and cargo check completed.
- **Task 11 online-flash safety and installer lifecycle**：Real App programming used 56 covered 2 KiB sectors and preserved independently verified bootloader and App regions. Final 56f1df6 NSIS/MSI bundles install and uninstall with exit 0, run without Python on PATH or Python descendants, and release ports. Final installed NSIS App HEX verify succeeded read-only; expected VERIFY_FAIL reported first mismatch 0x08000000. NSIS uninstall preserved both Pack/user cache fingerprints.
- **RTT View empty layout**：The large black area was the empty virtual text log joined visually to the 160 px numeric Canvas. The text log now remains mounted but hidden until text arrives, so first-batch reception is preserved; installed DOM measured zero empty-log width/height and full GUI tests pass.
- **Task 12 release assets**：21 payload assets and 18 sanitized rc1 JSON files were copied to the external release directory. All sizes and SHA-256 values match the manifest; checksum lines are sorted by asset name. The complete Pack-index, uncached GigaDevice DFP 2.2.1 install, restart reuse, and final installed-runtime cache reuse are mapped into the report and rc1-pack-catalog-cache.json.
- **Task 13 remote publication**：GitHub prerelease v0.1.0-rc.1 is non-draft and contains 23 assets. All assets were downloaded to an isolated temporary directory and matched local name, byte size, and SHA-256; the temporary verification copy was removed. Tag and manifest source both resolve to 1c7c5aac3f49f95d4195a0f07eed51bdaf6dcde6.

## 架构决策

- Only MKLink-exposed CMSIS-DAP is supported by the online flash UI.
- BIN requires an explicit base address; HEX uses embedded mappings.
- CMSIS-Pack catalog is complete but DFP files are downloaded on demand and never committed or bundled.
- High-rate data uses a versioned binary WebSocket data plane; REST/SSE remains for control and legacy low-rate paths.
- Acquisition must never wait for a browser; each client has a bounded queue that drops the oldest batch with explicit telemetry.
- Rendering is decoupled from acquisition and capped at 30 FPS with min/max pixel-envelope decimation.
- Ordinary online-flash program is enforced at both GUI and API boundaries: the inspected image is target-bound, reliable FLM coverage is recomputed, and erase sectors must exactly equal image-covered sectors; whole-chip erase remains a separate explicit confirmation.
- RTT View hides the empty text terminal but retains the numeric Canvas, which appears only when numeric channels are available.
- Subagent workflow is implementer, spec review, then quality review; review fixes receive new commits and are re-reviewed.

## 真机环境

- **probe**：MicroKeenV4/***1A91 connected
- **online_flash_project**：E:/PHDZ/PROJECT/liu/STM32F103_test/STM32F103_BOOT/MDK-ARM
- **stream_hil_project**：E:/PHDZ/PROJECT/liu/STM32F103_test/STM32F103RC/project.uvprojx
- **keil_root**：D:/Users/<redacted>/AppData/Local/Keil_v5
- **stream_target**：STM32F103RC
- **permission**：User permits adding test firmware code, compiling with Keil, flashing, and testing VOFA/SystemView/variable reads.

## 下一动作

1. Collect tester feedback from the v0.1.0-rc.1 GitHub prerelease and reproduce defects against the published hashes.
2. For the next release, add code signing before promoting beyond prerelease.
3. Keep hidden-document, Serial, Modbus, and physical fault-injection results NOT ESTABLISHED unless their required runtime or fixture is actually present.

## 已知限制

- Physical target power loss, probe unplug, SWD wire disconnect, second non-MKLink probe comparison, and physical network disconnect were not executed.
- Only RTT retained a measured overload boundary. SystemView pairs=2/tick and VOFA/SuperWatch at the fastest supported 10 us request are qualified stable zero-drop rates, not claimed drop-bounded maxima.
- Real hidden-tab HIL remains not established: Edge 130 rejected the visibility override and a background tab did not set document.hidden=true; deterministic hidden scheduling tests pass.
- GUI npm audit reports two pre-existing high vulnerabilities; dependencies were not changed during protocol work.
- Task 3 uses the first CONTROL heartbeat as a subscription-ready barrier in tests because batches published before subscribe are intentionally not cached.
- The Windows RC executables and installers are unsigned and may show an unknown-publisher warning.
- The first final-package restricted-environment teardown omitted SystemDrive in the test harness, so Windows created a literal test-cache directory after product processes and ports exited; the cache was removed and the corrected NSIS lifecycle rerun passed completely.
- Task 11 did not reflash the whole-chip stream fixture because the target currently uses a bootloader-preserving App layout; RTT performance remains supported by the existing 600-second packaged HIL artifact.
- Do not expose full probe IDs, COM ports, credentials, user names, raw logs, screenshots, Pack files, or build artifacts in Git.

## 延续协议

- Run: python scripts/ai_memory.py validate
- Read: docs/ai/CURRENT_HANDOFF.md and the active plan
- Run: git status --short and git log -12 --oneline; reconcile with repository.head
- Resume current_task before starting later tasks
- Before ending: update project-memory.json, run render, validate, tests proportional to changes, git diff --check, commit, and push
