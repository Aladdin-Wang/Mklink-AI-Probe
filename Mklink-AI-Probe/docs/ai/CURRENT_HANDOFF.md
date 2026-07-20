# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-21T00:01:10+08:00`
- 分支：`feature/online-flash-streaming`
- HEAD：`063068d is the latest product source commit; 9890008 refreshes tracked frontend assets; the final handoff commit contains this memory`
- 远端 HEAD：`feature/online-flash-streaming is pushed through the final handoff commit`
- 工作树：clean after the final handoff commit; release files remain outside Git
- 当前任务：内置 pyelftools ELF/DWARF 后端已完成并通过真实 STM32F103 AXF/ELF、完整自动化测试和标准 NSIS 安装态验证；等待后续任务。
- 状态：`complete`

## 里程碑

- **Online and offline flash workflows** — `complete`。Online and offline paths share the unified target/algorithm catalog, preserve ordered firmware ranges, avoid implicit whole-chip erase, support 10 MHz, and cover builtin, local Pack, custom FLM, and optional online Pack sources.
- **Desktop dashboards and high-rate streaming** — `complete`。RTT View, SystemView, VOFA, and SuperWatch use bounded binary streaming, Worker-owned buffers, explicit loss telemetry, pause/resume, and cleanup-safe resource ownership.
- **Runtime-readable structured symbols** — `complete`。Configuration, Symbols, search/typeinfo, and SuperWatch share one generation- and fingerprint-aware catalog. Reparse and reconnect rebind valid selected channels and remove invalid ones.
- **Built-in ELF and DWARF backend** — `complete`。pyelftools 0.32 is the default across SDK, CLI, MCP, REST, desktop, SuperWatch, VOFA, breakpoints, memory maps, and HardFault source lookup. GNU readelf/addr2line are isolated behind explicit elf_backend=external selection with no automatic fallback.
- **Windows standard NSIS candidate** — `complete`。The installed a8f82c2 candidate runs with the bundled sidecar under restricted PATH, spawns no Python child, embeds the expected build identity, discovers the available probe without exposing its identifier, and releases processes and port 8765 on normal close.
- **SuperWatch symbol tree and layout stability** — `complete`。Structured symbols render as a default-collapsed tree with search-state restoration and selected-only pruning. Desktop live status and toolbars use stable single-row geometry, and a 4660-leaf component test proves collapsed catalogs do not mount leaf rows.

## 验证证据

- **Latest automated baseline**：Python 899 passed and 1 skipped after review fixes; GUI 33 files / 376 tests passed; Vite production build transformed 1909 modules; Rust release packaging completed with 6 prior tests passing and cargo check completed.
- **Installed WebView2 checks**：The standard 063068d/9890008 NSIS installed silently to an isolated location and launched under a Windows-system-only PATH. Health reported elf_backend=builtin, pyelftools 0.32 available, readelf/addr2line unavailable, no Python/GNU child, and normal close left zero product processes and released port 8765.
- **SuperWatch tree and layout qualification**：Pure and component tests cover nested structures/arrays, default collapse, search expansion restoration, selected-only pruning, reparse cleanup, and a 4660-leaf catalog mounting zero leaf rows while collapsed. Source-level guards cover stable desktop header/toolbars. Interactive live geometry sampling was unavailable because browser and computer-use control surfaces were not available.
- **Built-in ELF real-file qualification**：On the supplied STM32F103 fixtures, builtin/external symbol sets matched exactly: Keil AXF 1626 and GCC ELF 1418. Safe builtin readable catalogs contain Keil 4851 and GCC 4385 leaves. GCC remains a strict superset of external results; the 17 Keil external-only leaves were confirmed to come from dereference/stack-value or piece expressions that external text parsing misclassifies as direct writable addresses. Builtin line lookup resolved 50/50 sampled Keil addresses and 48/50 GCC addresses. Installed sidecar symbols, typeinfo, and memmap all passed under restricted PATH.

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
- ELF/AXF parsing defaults to bundled pyelftools. External readelf/addr2line are used only for explicit elf_backend=external requests; path configuration does not activate them, and builtin failures do not auto-fallback.
- Do not commit installers, firmware, Pack files, standalone FLM, logs, screenshots, full probe IDs, COM ports, usernames, credentials, or local hardware paths.

## 真机环境

- **probe**：MKLink V4 available; identifier intentionally omitted
- **latest_target**：STM32H7B0 LCD board fixture with internal and external Flash; local paths intentionally omitted
- **stream_target**：STM32F103RC fixture; local path intentionally omitted
- **permission**：User permits firmware build/flash and read-only target validation when the requested task requires it.

## 下一动作

1. Use real Edge/Playwright/WebView2 or computer use with the supplied STM32F103 project to record invariant SuperWatch chart geometry and confirm smooth full-catalog interaction.
2. Install and qualify the 063068d/9890008 standard NSIS on a second clean Windows 10/11 machine without Python, Node, Rust, Keil, GNU Arm tools, or pre-existing Pack cache.
3. Collect exact model and address-range reports from external users to correct any catalog naming or Flash geometry mismatch.
4. Collect exact variable paths for any missing fixed structure/array leaves and compare the Configuration, Symbols, and SuperWatch counts.
5. Add Windows code signing before promotion beyond prerelease.

## 已知限制

- The a8f82c2 standard NSIS has not yet been tested on a second clean Windows machine or VM.
- The new SuperWatch layout has automated geometry guards but no fresh interactive Edge/WebView2 rectangle sampling because browser and computer-use control surfaces were unavailable.
- The supplied STM32F103 project could not complete a new source-backend connection while another process owned the probe resources; the installed candidate probe-discovery and lifecycle checks passed after cleanup.
- Builtin source-line lookup resolved 48 of 50 sampled GCC addresses; unresolved locations remain unresolved instead of silently invoking addr2line.
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
