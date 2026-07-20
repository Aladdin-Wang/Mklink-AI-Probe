# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-20T18:16:15+08:00`
- 分支：`feature/online-flash-streaming`
- HEAD：`a8f82c2 is the latest product source commit; d005864 refreshes tracked frontend assets; the final handoff commit contains this memory`
- 远端 HEAD：`feature/online-flash-streaming is pushed through the final handoff commit`
- 工作树：clean after the final handoff commit; release files remain outside Git
- 当前任务：在可用的 Edge/Playwright/WebView2 或 computer-use 会话中，用 STM32F103 真机确认 a8f82c2 SuperWatch 曲线几何稳定、完整目录流畅度和结构体/数组折叠交互。
- 状态：`complete`

## 里程碑

- **Online and offline flash workflows** — `complete`。Online and offline paths share the unified target/algorithm catalog, preserve ordered firmware ranges, avoid implicit whole-chip erase, support 10 MHz, and cover builtin, local Pack, custom FLM, and optional online Pack sources.
- **Desktop dashboards and high-rate streaming** — `complete`。RTT View, SystemView, VOFA, and SuperWatch use bounded binary streaming, Worker-owned buffers, explicit loss telemetry, pause/resume, and cleanup-safe resource ownership.
- **Runtime-readable structured symbols** — `complete`。Configuration, Symbols, search/typeinfo, and SuperWatch share one generation- and fingerprint-aware catalog. Reparse and reconnect rebind valid selected channels and remove invalid ones.
- **Windows standard NSIS candidate** — `complete`。The installed a8f82c2 candidate runs with the bundled sidecar under restricted PATH, spawns no Python child, embeds the expected build identity, discovers the available probe without exposing its identifier, and releases processes and port 8765 on normal close.
- **SuperWatch symbol tree and layout stability** — `complete`。Structured symbols render as a default-collapsed tree with search-state restoration and selected-only pruning. Desktop live status and toolbars use stable single-row geometry, and a 4660-leaf component test proves collapsed catalogs do not mount leaf rows.

## 验证证据

- **Latest automated baseline**：Python 860 passed and 1 skipped; GUI 33 files / 375 tests passed; Vite production build transformed 1909 modules and embedded a8f82c2d9cc2; Rust 6 passed; cargo check completed.
- **Installed WebView2 checks**：The standard a8f82c2 NSIS installed silently to an isolated location and launched under restricted PATH. Health was ok, one probe was discoverable, no Python process was present, and normal window close left zero product processes and released port 8765.
- **SuperWatch tree and layout qualification**：Pure and component tests cover nested structures/arrays, default collapse, search expansion restoration, selected-only pruning, reparse cleanup, and a 4660-leaf catalog mounting zero leaf rows while collapsed. Source-level guards cover stable desktop header/toolbars. Interactive live geometry sampling was unavailable because browser and computer-use control surfaces were not available.
- **Flash and package qualification**：STM32H7B0 internal and external Flash program/verify/reset paths passed in earlier qualification. The final symbol pass performed no erase or program. Normal close left zero product/Python processes and released ports 8765 and 9223.

## 架构决策

- Generate only the standard NSIS installer by default. MSI and WebView2-offline packages require explicit user request.
- Only MKLink-exposed CMSIS-DAP probes are supported by the online flash UI.
- BIN requires an explicit base address; HEX uses embedded addresses.
- Ordinary programming erases only image-covered sectors and verifies readback before reset. Whole-chip erase remains a separate confirmed operation.
- Algorithm selection is offline-first: builtin catalog, then user Pack, then target-scoped custom FLM; optional online Pack installation remains available.
- HPM targets always use the HPM ROM API path and never discover or load FLM.
- The public symbol catalog contains only fixed readable scalar leaves. Pointers, bit-fields, variable-length arrays, overlapping union aliases, incomplete layouts, and non-RAM addresses are excluded.
- SuperWatch merges nearby addresses through build_read_blocks(max_gap=256) and preserves selected symbol names across valid reparse/reconnect transitions.
- High-rate acquisition never waits for the browser; queues are bounded and report drops explicitly.
- SuperWatch structure and array branches are collapsed by default; search and selected-only filters expose only matching leaves and ancestors without changing acquisition selection.
- Do not commit installers, firmware, Pack files, standalone FLM, logs, screenshots, full probe IDs, COM ports, usernames, credentials, or local hardware paths.

## 真机环境

- **probe**：MKLink V4 available; identifier intentionally omitted
- **latest_target**：STM32H7B0 LCD board fixture with internal and external Flash; local paths intentionally omitted
- **stream_target**：STM32F103RC fixture; local path intentionally omitted
- **permission**：User permits firmware build/flash and read-only target validation when the requested task requires it.

## 下一动作

1. Use real Edge/Playwright/WebView2 or computer use with the supplied STM32F103 project to record invariant SuperWatch chart geometry and confirm smooth full-catalog interaction.
2. Install and qualify the a8f82c2 standard NSIS on a second clean Windows 10/11 machine without Python, Node, Rust, Keil, or pre-existing Pack cache.
3. Collect exact model and address-range reports from external users to correct any catalog naming or Flash geometry mismatch.
4. Collect exact variable paths for any missing fixed structure/array leaves and compare the Configuration, Symbols, and SuperWatch counts.
5. Add Windows code signing before promotion beyond prerelease.

## 已知限制

- The a8f82c2 standard NSIS has not yet been tested on a second clean Windows machine or VM.
- The new SuperWatch layout has automated geometry guards but no fresh interactive Edge/WebView2 rectangle sampling because browser and computer-use control surfaces were unavailable.
- The supplied STM32F103 project could not complete a new source-backend connection while another process owned the probe resources; the installed candidate probe-discovery and lifecycle checks passed after cleanup.
- The installer is unsigned and may show an unknown-publisher warning.
- Optional online Pack installation requires outbound HTTPS and may require a configured proxy.
- Physical HPM programming, V2/V3 offline deployment, target power loss, probe unplug, SWD disconnect, Serial, Modbus, and hidden-tab HIL are not established in the latest pass.
- DISP0_ADAPTER and s_tLCDTextControl are intentionally truncated to their first 256 readable leaves.
- One HK32 catalog region lacks reliable sector geometry and is correctly rejected for ordinary covered-sector programming.

## 延续协议

- Run python scripts/ai_memory.py validate.
- Read docs/ai/CURRENT_HANDOFF.md and reconcile it with git status --short --branch and git log -12 --oneline.
- Resume current_session.current_task before starting later work.
- Before ending, update project-memory.json, render and validate the handoff, run proportional tests and git diff --check, then commit and push.
