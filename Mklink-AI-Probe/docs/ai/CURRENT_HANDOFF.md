# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-22T10:09:30+08:00`
- 分支：`master`
- HEAD：`master contains the v0.1.1 release handoff, repository-bundled maintenance workflow, and this final session handoff`
- 远端 HEAD：`GitHub and Gitee master contain this handoff; both updates branches remain ea36381`
- 工作树：clean after the final handoff; only the master worktree remains
- 当前任务：Current maintenance, branch cleanup, and GitHub/Gitee synchronization are complete; waiting for a new problem in the next conversation.
- 状态：`complete`

## 里程碑

- **Flash workflows** — `complete`。Online and offline flashing share the target/algorithm catalog, support builtin/local/custom algorithms, use image-covered erase and verification, and stream named V4 offline execution live.
- **Streaming and SuperWatch** — `complete`。RTT, SystemView, VOFA, and SuperWatch use bounded streaming. SuperWatch keeps stable chart geometry and renders structures/arrays as default-collapsed symbol trees.
- **Built-in ELF and DWARF** — `complete`。Bundled pyelftools is the default for symbols, types, memory maps, HardFault lines, and desktop features. External GNU tools run only when explicitly selected.
- **Signed desktop updates** — `complete`。The Tauri v2 application discovers signed NSIS updates from Gitee, downloads in the background, and installs after user confirmation. v0.1.1 assets are on GitHub and Gitee.
- **Shared cross-model maintenance workflow** — `complete`。AGENTS.md and the repository skill define requirement discovery, diagnosis, proportional planning/testing, worktree reuse, verification, handoff, and maintainer-only releases without relying on globally installed skills.

## 验证证据

- **v0.1.1 automated baseline**：Release source b3c7925 passed Python 915 with 1 skipped, GUI 35 files/387 tests, Rust 6 tests, Vite production build, cargo check, and production npm audit with zero vulnerabilities.
- **Installed application**：The standard NSIS ran with the bundled sidecar under a Windows-system-only PATH, exposed the builtin ELF backend, spawned no Python child, discovered a probe without recording its identifier, and released processes and port 8765 on close.
- **Real V4 offline deployment**：Deployment auto-generated a missing preview, left no staging backup on the probe disk, selected the configured script name, and delivered device output as 87 live line events before successful completion.
- **Published update**：GitHub and Gitee expose the same four v0.1.1 assets; anonymous Gitee download and SHA-256 passed, and public latest.json points to the signed Gitee NSIS payload.
- **Repository maintenance workflow**：The repository skill passed skill-creator quick validation; release preparation/publication tests passed 12/12; AI memory validation and git diff checks passed.
- **Repository synchronization**：Obsolete feature branches were removed locally and from GitHub/Gitee. Both hosts retain only master and updates, with matching branch heads and tags before this final handoff.

## 架构决策

- Repository instructions and skills are the cross-model source of truth; local/global skills may help but must not be required.
- Plans, tests, and worktrees scale with risk. Do not impose long plans, separate RED commits, or new worktrees on every task.
- Diagnose before editing, prefer existing patterns, make the smallest complete change, and verify before claiming success.
- Generate only standard NSIS by default. MSI and WebView2-offline packages require explicit authorization.
- Official signing and publication run only on the maintainer's computer or controlled CI; signing keys remain local/CI only.
- GitHub is the primary collaborative repository. Only the maintainer or controlled CI synchronizes official releases to Gitee.
- Publish GitHub/Gitee assets and verify the anonymous Gitee installer before publishing updates/latest.json last.
- HPM targets always use the dedicated ROM API and never discover or load FLM.
- Bundled pyelftools is the default; readelf/addr2line require explicit external-backend selection and never receive automatic fallback traffic.
- Do not commit installers, firmware, Packs, FLM files, logs, screenshots, full probe IDs, COM numbers, usernames, credentials, signing keys, or local hardware paths.

## 真机环境

- **probe**：MKLink V4 is available; identifier omitted
- **stream_target**：STM32F103RC fixture is available; local path omitted
- **permission**：Firmware build/flash and read-only target validation are permitted when required by the active task.

## 下一动作

1. Start the next conversation from AGENTS.md and the repository-bundled maintenance skill, then inspect live state before changing code.
2. Confirm an installed older client discovers, downloads, and installs v0.1.1 in the maintainer's normal desktop environment.
3. Qualify the standard NSIS on a second clean Windows 10/11 system without Python, Node, Rust, Keil, GNU Arm tools, or a Pack cache.

## 已知限制

- The v0.1.1 NSIS has not been qualified on a second clean Windows machine without development tools.
- The updater payload has Tauri integrity signing but no Windows Authenticode signature, so Windows may show an unknown-publisher warning.
- The latest SuperWatch tree/layout has automated coverage but no fresh interactive WebView2 geometry capture.
- Some optional online Pack operations require outbound HTTPS, and unqualified hardware/power-loss scenarios remain device-specific.

## 延续协议

- Follow AGENTS.md and skills/maintaining-mklink-ai-probe/SKILL.md.
- Reconcile AI memory with live Git and runtime state before editing.
- Before ending, run proportional checks and git diff --check, update memory, render and validate the handoff, then commit and push when authorized.
