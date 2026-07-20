# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-20T16:08:12+08:00`
- 分支：`feature/online-flash-streaming`
- HEAD：`b599f5c is the latest product source commit; the final handoff commit contains this memory`
- 远端 HEAD：`feature/online-flash-streaming is pushed through the final handoff commit`
- 工作树：clean after the final handoff commit; release files remain outside Git
- 当前任务：在第二台无开发环境和预置 Pack 缓存的 Windows 10/11 机器验证 b599f5c 标准 NSIS，并收集外部用户对器件目录与结构化符号的反馈。
- 状态：`complete`

## 里程碑

- **Online and offline flash workflows** — `complete`。Online and offline paths share the unified target/algorithm catalog, preserve ordered firmware ranges, avoid implicit whole-chip erase, support 10 MHz, and cover builtin, local Pack, custom FLM, and optional online Pack sources.
- **Desktop dashboards and high-rate streaming** — `complete`。RTT View, SystemView, VOFA, and SuperWatch use bounded binary streaming, Worker-owned buffers, explicit loss telemetry, pause/resume, and cleanup-safe resource ownership.
- **Runtime-readable structured symbols** — `complete`。Configuration, Symbols, search/typeinfo, and SuperWatch share one generation- and fingerprint-aware catalog. Reparse and reconnect rebind valid selected channels and remove invalid ones.
- **Windows standard NSIS candidate** — `complete`。The installed b599f5c candidate runs with the bundled sidecar under restricted PATH, spawns no Python child, exposes the expected build identity, and releases processes and ports on normal close.

## 验证证据

- **Latest automated baseline**：Python 860 passed and 1 skipped; GUI 32 files / 365 tests passed; Vite production build transformed 1908 modules; Rust 6 passed; cargo check completed.
- **Installed WebView2 checks**：Health ok; build identity b599f5c; no startup serial-read failure; 10 MHz visible; keep-running default; one total progress bar; target selection fills the search; SuperWatch follows RTT View; HPM5300 exposes zero algorithms.
- **Symbol and SuperWatch read-only HIL**：BOOT exposes 59 runtime-readable leaves. RGB_LCD exposes 801 leaves, shown consistently in Configuration, Symbols, and SuperWatch. Adjacent structure-array leaves merged into one four-byte block and sampled in dump-memory mode with zero read drops, read errors, or binary batch drops.
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
- Do not commit installers, firmware, Pack files, standalone FLM, logs, screenshots, full probe IDs, COM ports, usernames, credentials, or local hardware paths.

## 真机环境

- **probe**：MKLink V4 available; identifier intentionally omitted
- **latest_target**：STM32H7B0 LCD board fixture with internal and external Flash; local paths intentionally omitted
- **stream_target**：STM32F103RC fixture; local path intentionally omitted
- **permission**：User permits firmware build/flash and read-only target validation when the requested task requires it.

## 下一动作

1. Install and qualify the b599f5c standard NSIS on a second clean Windows 10/11 machine without Python, Node, Rust, Keil, or pre-existing Pack cache.
2. Collect exact model and address-range reports from external users to correct any catalog naming or Flash geometry mismatch.
3. Collect exact variable paths for any missing fixed structure/array leaves and compare the Configuration, Symbols, and SuperWatch counts.
4. Add Windows code signing before promotion beyond prerelease.

## 已知限制

- The b599f5c standard NSIS has not yet been tested on a second clean Windows machine or VM.
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
