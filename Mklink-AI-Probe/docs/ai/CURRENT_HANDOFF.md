# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-12T17:50:00+08:00`
- 分支：`feature/online-flash-streaming`
- HEAD：`d8029d8`
- 远端 HEAD：`05eda14`
- 工作树：clean before final AI memory refresh; Task 3 quality review in progress
- 当前任务：Task 3 authenticated binary WebSocket final quality review
- 状态：`in_progress`

## 里程碑

- **Online flash Tasks 1-12** — `complete`。docs/verification/online-flash-hil.md
- **High-throughput Task 1 binary protocol** — `complete`。Python 10 passed; TypeScript 8 passed
- **High-throughput Task 2 bounded StreamHub** — `complete`。Unique owner loop, immutable batch, generation/pending callback lifecycle, stale callback isolation.
- **High-throughput Task 3 authenticated binary WebSocket** — `quality_review_pending`。Invalid authentication JSON shapes close with 1008; sequence, item_count, and timestamp_ns are shared per fan-out batch.
- **High-throughput Tasks 4-9** — `pending`。Worker typed ring buffer; min/max envelope and 30 FPS scheduler; SystemView, VOFA, RTT, SuperWatch migrations; performance and HIL qualification.

## 验证证据

- **Online flash automated**：Python 388 passed; GUI 69 passed; Vite 134 modules; no tracked or bundled .pack
- **Online flash HIL**：MKLink filter, Pack index, on-demand GD32 DFP, restart cache, STM32F103RC HEX/BIN program+verify, expected VERIFY_FAIL, cooperative stop, VOFA PROBE_BUSY handoff, target boot firmware restored
- **Tauri**：release EXE 11132928 bytes and MSI 47554560 bytes generated locally; NSIS not generated because official nsis-3.11.zip download timed out
- **Current Python baseline**：448 passed after Task 3 spec fixes

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

1. Collect the independent Task 3 quality review result for c1346f3+d8029d8; fix and re-review any finding.
2. If Task 3 quality is APPROVED, mark Task 3 complete and update both memory files before push.
3. Push feature/online-flash-streaming after Task 3 approval and memory commit.
4. Execute high-throughput Task 4 with strict TDD: typed ring buffer, decoder Worker, stream client, useBinaryStream.
5. Continue Tasks 5-9 in order, preserving 30 FPS render cap and measuring actual MKLink stable acquisition rate.
6. Use STM32F103RC project and Keil for final VOFA/SystemView/read-variable HIL; record measured rates and drops, not inferred claims.

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
