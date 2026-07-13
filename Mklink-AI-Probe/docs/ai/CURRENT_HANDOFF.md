# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-13T18:00:00+08:00`
- 分支：`feature/online-flash-streaming`
- HEAD：`ecaa614`
- 远端 HEAD：`f5fdf7e`
- 工作树：clean before Task 7 completion memory refresh
- 当前任务：High-throughput Task 8: migrate RTT and SuperWatch and virtualize logs
- 状态：`in_progress`

## 里程碑

- **Online flash Tasks 1-12** — `complete`。docs/verification/online-flash-hil.md
- **High-throughput Task 1 binary protocol** — `complete`。Python 10 passed; TypeScript 8 passed
- **High-throughput Task 2 bounded StreamHub** — `complete`。Unique owner loop, immutable batch, generation/pending callback lifecycle, stale callback isolation.
- **High-throughput Task 3 authenticated binary WebSocket** — `complete`。Invalid JSON shapes and binary authentication frames close 1008 without leaks; sequence, item_count, and timestamp_ns are shared per fan-out batch.
- **High-throughput Task 4 Worker-owned stream buffers** — `complete`。Fixed-capacity typed ring, transferable Worker frames, bounded reconnect lifecycle, and generation/ticket readiness acknowledgements isolate stale sockets.
- **High-throughput Task 5 envelope, scheduler, and benchmark** — `complete`。Typed min/max envelope, one 30 FPS scheduler, strict sequence/drop accounting, responsive cancellation, and deterministic sample-rate benchmark.
- **High-throughput Task 6 SystemView binary migration** — `complete`。Recording-first fixed 48-byte events, bounded O(1) Worker rings, nested ISR contexts, exact BigInt ticks, pixel-bounded interval envelopes, binary UI at 30 FPS and event table at 5 Hz.
- **High-throughput Task 7 VOFA binary migration** — `complete`。Validated aligned source reads, atomic sample-major batches, Worker min/max envelopes, O(1) extrema and O(log N) interactions, bounded DOM work, live telemetry, pause-safe rates, and SuperWatch legacy isolation.
- **High-throughput Tasks 8-9** — `pending`。RTT and SuperWatch migration, virtual logs, final performance and HIL qualification.

## 验证证据

- **Online flash automated**：Python 388 passed; GUI 69 passed; Vite 134 modules; no tracked or bundled .pack
- **Online flash HIL**：MKLink filter, Pack index, on-demand GD32 DFP, restart cache, STM32F103RC HEX/BIN program+verify, expected VERIFY_FAIL, cooperative stop, VOFA PROBE_BUSY handoff, target boot firmware restored
- **Tauri**：release EXE 11132928 bytes and MSI 47554560 bytes generated locally; NSIS not generated because official nsis-3.11.zip download timed out
- **Current Python baseline**：544 passed after Task 7 final quality fixes
- **Current GUI baseline**：192 tests passed and Vite production build transformed 137 modules after Task 7 final quality fix
- **Task 5 local transport benchmark**：10 seconds at 10 kSamples/s and 8 channels produced/consumed 100000/100000 with zero drops and sequence errors; elapsed 10.001s; responsive 1800-second cancellation; real overflow accounting matched exactly
- **Task 6 SystemView soak**：Hub/codec 600 seconds at 50 kEvents/s consumed 30000000/30000000 fixed 48-byte events with zero drops/errors, 2.4036 MB/s, queue high-water 1, RSS growth 430080 bytes; realistic Worker 60 seconds processed 3000000 events at 50002.8 events/s with fixed 100000 buffer, 30 FPS visible requests, output <=1600 for 800 pixels, zero errors
- **Task 7 VOFA synthetic qualification**：Python synthetic transport 1800 seconds at 10 kSamples/s and 8 channels consumed 18000000/18000000 with zero drops/errors and working-set growth 40960 bytes. Accelerated jsdom same-thread harness processed 60 seconds of data (600000 samples), 1800 visible requests, output <=5120 for 320 pixels x 8 channels, zero ring full scans/drops/errors; this is not wall-clock browser, WebSocket, Web Worker, Python backend, or HIL evidence.

## 架构决策

- Only MKLink-exposed CMSIS-DAP is supported by the online flash UI.
- BIN requires an explicit base address; HEX uses embedded mappings.
- CMSIS-Pack catalog is complete but DFP files are downloaded on demand and never committed or bundled.
- High-rate data uses a versioned binary WebSocket data plane; REST/SSE remains for control and legacy low-rate paths.
- Acquisition must never wait for a browser; each client has a bounded queue that drops the oldest batch with explicit telemetry.
- Rendering is decoupled from acquisition and capped at 30 FPS with min/max pixel-envelope decimation.
- Subagent workflow is implementer, spec review, then quality review; review fixes receive new commits and are re-reviewed.

## 真机环境

- **probe**：MicroKeenV4/***1A91 connected
- **online_flash_project**：E:/PHDZ/PROJECT/liu/STM32F103_test/STM32F103_BOOT/MDK-ARM
- **stream_hil_project**：E:/PHDZ/PROJECT/liu/STM32F103_test/STM32F103RC/project.uvprojx
- **keil_root**：D:/Users/<redacted>/AppData/Local/Keil_v5
- **stream_target**：STM32F103RC
- **permission**：User permits adding test firmware code, compiling with Keil, flashing, and testing VOFA/SystemView/variable reads.

## 下一动作

1. Push the Task 7 completion and refreshed project memory to feature/online-flash-streaming.
2. Execute high-throughput Task 8 with strict TDD: RTT raw binary batches, SuperWatch sample batches, bounded VirtualLogPanel, and component migration.
3. Require Task 8 spec review and quality review before starting Task 9.
4. Execute Task 9 performance gates and MKLink/STM32F103RC HIL, preserving 30 FPS render cap and measuring actual stable acquisition rate.
5. Use STM32F103RC project and Keil for final VOFA/SystemView/read-variable HIL; record measured rates and drops, not inferred claims.

## 已知限制

- Physical target power loss, probe unplug, SWD wire disconnect, second non-MKLink probe comparison, and physical network disconnect were not executed.
- NSIS bundle remains unavailable because the official NSIS tool download timed out; EXE and MSI succeeded.
- GUI npm audit reports two pre-existing high vulnerabilities; dependencies were not changed during protocol work.
- Task 3 uses the first CONTROL heartbeat as a subscription-ready barrier in tests because batches published before subscribe are intentionally not cached.
- Do not expose full probe IDs, COM ports, credentials, user names, raw logs, screenshots, Pack files, or build artifacts in Git.

## 延续协议

- Run: python scripts/ai_memory.py validate
- Read: docs/ai/CURRENT_HANDOFF.md and the active plan
- Run: git status --short and git log -12 --oneline; reconcile with repository.head
- Resume current_task before starting later tasks
- Before ending: update project-memory.json, run render, validate, tests proportional to changes, git diff --check, commit, and push
