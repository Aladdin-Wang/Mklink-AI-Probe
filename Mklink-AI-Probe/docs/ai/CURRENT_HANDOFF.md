# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-22T15:56:25+08:00`
- 分支：`master`
- HEAD：`8a8a227 plus the uncommitted v0.1.2 RTT/SuperWatch/version-history, USB Web entry, and browser file-source upload release source`
- 远端 HEAD：`GitHub origin master remains 8a8a227 and updates remains ea36381; no Gitee remote is configured in this worktree, so Gitee was not rechecked in this session`
- 工作树：dirty with intended v0.1.2 source, tests, version metadata, workflow documentation, and AI memory; final generated build/cache cleanup and release-source commit are pending, test services are stopped, and the target is reset and disconnected
- 当前任务：Prepare and publish v0.1.2. Release publication is gated on generating the signed standard NSIS, overwriting the local installation, and completing a real-hardware closed loop in the installed Tauri/WebView2 application.
- 状态：`in_progress`

## 里程碑

- **Flash workflows** — `complete`。Online and offline flashing share the target/algorithm catalog, support builtin/local/custom algorithms, use image-covered erase and verification, and stream named V4 offline execution live.
- **Streaming and SuperWatch** — `complete`。RTT, SystemView, VOFA, and SuperWatch use bounded streaming. RTT View now has optional labeled axes with wheel zoom, drag pan, retained pause/stop curves, and inline input-format guidance. SuperWatch retains paused/stopped curves, exports timestamped selected-variable raw data, and suppresses viewer shortcuts while users type in editable controls.
- **Built-in ELF and DWARF** — `complete`。Bundled pyelftools is the default for symbols, types, memory maps, HardFault lines, and desktop features. External GNU tools run only when explicitly selected.
- **Signed desktop updates** — `complete`。The Tauri v2 application discovers signed NSIS updates from Gitee, downloads in the background, and installs after user confirmation. v0.1.1 assets are on GitHub and Gitee.
- **Shared cross-model maintenance workflow** — `complete`。AGENTS.md and the repository skill define requirement discovery, diagnosis, proportional planning/testing, worktree reuse, verification, handoff, and maintainer-only releases without relying on globally installed skills.
- **Cross-platform USB Web entry** — `complete`。One offline HTML uses the strict mklink-ai-probe://web start/open/stop protocol. User-scoped Windows, macOS, and Linux handlers start the existing loopback GUI, reuse existing Web services without ownership, and stop only identity-verified processes started by the entry.
- **Browser file-source loading** — `complete`。The Web configuration page uses a native browser file input and multipart upload for AXF/ELF/OUT and MAP sources, while Tauri keeps its native path dialog. Uploaded files are suffix-checked, size-limited, content-addressed, and stored under the runtime project .mklink directory.

## 验证证据

- **v0.1.2 final source gate and real hardware**：The final source gate passed Python 948 with 1 skipped, GUI 36 files/400 tests, Rust 6 tests, cargo check, the production Vite build, builder prerequisite checks, and npm production audit with zero vulnerabilities. Against the STM32F103 fixture, the Web runtime uploaded the real AXF and MAP into its user-data workspace, connected with the uploaded AXF through the builtin ELF backend, loaded a 4,851-item symbol catalog, and sampled a selected RAM variable through SuperWatch for about 19,000 read cycles with zero read errors or drops before stop/reset/disconnect. The installed v0.1.2 NSIS candidate still requires the same hardware closed loop before publication.
- **Cross-platform USB Web entry**：Focused Web-entry and CLI coverage passed 34/34, the full Python suite passed 945 with 1 skipped, the GUI suite passed 36 files/397 tests, and the production Vite build passed. On Windows, the real user-level protocol and physical MICROKEEN USB HTML reused an existing Web service without changing its PID or stopping it, then independently started one owned loopback GUI, reused the same PID on a second click, and stopped only that owned process. Uninstall removed the owned registry tree and reinstall restored it. macOS and Linux registration/quoting are covered by unit tests but were not run on those operating systems.
- **RTT View and SuperWatch interaction change**：The full GUI suite passed 36 files/397 tests, the production Vue/Vite build passed, and focused dashboard resource plus RTT/SuperWatch Python tests passed 111/111. A system Edge Web-client run against the STM32F103 fixture verified named RTT channels, chart interaction and retention, both mutual-switch directions, timestamped selected-variable raw logs, and literal L entry in the SuperWatch search. The same browser verified the 390x348 version-history popover stayed within a 1280x800 viewport and supported hover, click pinning, and outside close without layout overlap.
- **v0.1.1 automated baseline**：Release source b3c7925 passed Python 915 with 1 skipped, GUI 35 files/387 tests, Rust 6 tests, Vite production build, cargo check, and production npm audit with zero vulnerabilities.
- **Installed application**：The standard NSIS ran with the bundled sidecar under a Windows-system-only PATH, exposed the builtin ELF backend, spawned no Python child, discovered a probe without recording its identifier, and released processes and port 8765 on close.
- **Real V4 offline deployment**：Deployment auto-generated a missing preview, left no staging backup on the probe disk, selected the configured script name, and delivered device output as 87 live line events before successful completion.
- **Published update**：GitHub and Gitee expose the same four v0.1.1 assets; anonymous Gitee download and SHA-256 passed, and public latest.json points to the signed Gitee NSIS payload.
- **Repository maintenance workflow**：The repository skill passed skill-creator quick validation; release preparation/publication tests passed 12/12; AI memory validation and git diff checks passed.
- **Repository synchronization**：Obsolete feature branches were removed locally and from GitHub/Gitee. Both hosts retain only master and updates, with matching branch heads and tags before this final handoff.

## 架构决策

- Every runtime or user-facing feature and bug fix now requires the full Python and GUI suites plus a production build, followed by a real-hardware closed loop on the affected Web, Tauri, or device surface before release. Component or mocked tests alone are not release evidence.
- Browser file pickers cannot expose an absolute local path. Web AXF/MAP selection therefore uploads the selected File to a suffix-checked, 256 MiB-limited, content-addressed runtime directory and uses the returned backend path; Tauri continues to use its native dialog without upload.
- The v0.1.2 public release must not start until its signed NSIS has overwritten the local installation and the installed bundled-sidecar application has passed the real-hardware closed loop.
- The USB contains only one identical offline HTML file. Each computer performs one user-level protocol registration when the complete Mklink runtime is deployed; a standalone SKILL.md cannot start a local process under browser security rules.
- The Web entry accepts only mklink-ai-probe://web/start, /open, and /stop with no queries, fragments, commands, or arbitrary paths. It binds loopback, serializes repeated clicks, scans the local port range before spawning, and refuses to compete with an API-only Mklink backend.
- Web-entry process ownership includes PID plus process-creation identity so stale state cannot kill a recycled PID. Uninstall removes the Windows protocol only when its owner and handler markers match the current installation.
- The new web-entry CLI branch and protocol handler are additive. Existing AI/MCP calls, mklink gui, mklink serve, and the Tauri sidecar retain their original code paths and ownership.
- All bridge Dashboard starts share one serialized backend transaction that stops conflicting sessions and releases their leases before atomically acquiring resources for the new session; the RTT-only confirmation prompt was removed.
- RTT auto-detection evaluates the accumulated startup sample window so occasional marker lines cannot replace a majority key-value stream format.
- After a successful RTT status poll, backend running state is authoritative over stale local toolbar state so peer-triggered stops return the hidden RTT view to idle without clearing retained data.
- Waveform global shortcuts yield to input, textarea, select, contenteditable, and textbox-role targets so search and value editing receive literal keystrokes.
- Version history is bundled as structured frontend data so the footer popover works offline; stable release entries must be updated as part of future version preparation.
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

1. Clean generated verification output, commit and push the intended v0.1.2 source on master, then build the signed standard NSIS and four sanitized public assets.
2. Overwrite the local application with the v0.1.2 NSIS and qualify health, bundled sidecar, no Python child, Web file upload, symbol parsing, RTT/SuperWatch real-hardware behavior, normal shutdown, and port release.
3. Only after installed-candidate qualification passes, run the one-command publisher to push the v0.1.2 tag and four assets to GitHub/Gitee, verify anonymous Gitee download, and publish latest.json last.
4. Qualify the same USB HTML and user-level protocol on one current macOS system and one mainstream Linux desktop, including browser confirmation and USB HID/serial permissions.
5. Ensure the deployed skill/runtime package carries matching built gui/dist assets and runs web-entry install whenever its absolute installation path changes.
6. Optionally repeat the qualified real-hardware workflow in the installed Tauri WebView2 shell before the next desktop release.
7. Confirm an installed older client discovers, downloads, and installs v0.1.1 in the maintainer's normal desktop environment.
8. Qualify the standard NSIS on a second clean Windows 10/11 system without Python, Node, Rust, Keil, GNU Arm tools, or a Pack cache.

## 已知限制

- The protocol handler was exercised on Windows only. macOS LaunchServices and Linux xdg-mime behavior still need real-system qualification even though their generated files and quoting have automated coverage.
- Every target computer needs a complete Mklink runtime with GUI dependencies and built gui/dist assets plus one-time web-entry registration; the USB HTML intentionally contains no executable runtime.
- The v0.1.1 NSIS has not been qualified on a second clean Windows machine without development tools.
- The updater payload has Tauri integrity signing but no Windows Authenticode signature, so Windows may show an unknown-publisher warning.
- The new RTT View and SuperWatch workflow passed real-hardware validation in the system Edge Web client, but has no fresh capture from the installed Tauri WebView2 shell.
- Some optional online Pack operations require outbound HTTPS, and unqualified hardware/power-loss scenarios remain device-specific.

## 延续协议

- Follow AGENTS.md and skills/maintaining-mklink-ai-probe/SKILL.md.
- Reconcile AI memory with live Git and runtime state before editing.
- Before ending, run proportional checks and git diff --check, update memory, render and validate the handoff, then commit and push when authorized.
