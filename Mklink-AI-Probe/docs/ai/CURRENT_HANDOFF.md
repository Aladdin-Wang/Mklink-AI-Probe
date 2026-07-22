# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-22T23:00:14+08:00`
- 分支：`master`
- HEAD：`local master and the Aladdin-Wang GitHub fork include the AI-first README, firmware-download priority repair, and maintenance workflow updates; upstream PR su5176/Mklink-AI-Probe#3 is open; v0.1.2 remains tagged at 9cd9177`
- 远端 HEAD：`GitHub origin master is published with the current maintenance work and feeds upstream PR #3; Gitee master intentionally remains at e911e62, updates remains 926f046, and v0.1.2 peels to 9cd9177`
- 工作树：clean after GitHub publication, upstream PR #3 creation, and handoff recording; v0.1.2 remains installed, test services are stopped, and the target is running with the probe released
- 当前任务：The GitHub fork is current, upstream PR su5176/Mklink-AI-Probe#3 is open with a concise full-project summary, and repository memory is prepared for the next maintainer.
- 状态：`complete`

## 里程碑

- **Flash workflows** — `complete`。Online and offline flashing share the target/algorithm catalog, support builtin/local/custom algorithms, use image-covered erase and verification, and stream named V4 offline execution live. Agent-driven downloads prefer IDE-native build/download, then pyOCD, then offline deployment. Automatic FLM selection uses bundled Pack, bundled DAPLink, installed Pack, then registered custom algorithms while explicit user choices remain selectable and authoritative.
- **Streaming and SuperWatch** — `complete`。RTT, SystemView, VOFA, and SuperWatch use bounded streaming. RTT View now has optional labeled axes with wheel zoom, drag pan, retained pause/stop curves, and inline input-format guidance. SuperWatch retains paused/stopped curves, exports timestamped selected-variable raw data, and suppresses viewer shortcuts while users type in editable controls.
- **Built-in ELF and DWARF** — `complete`。Bundled pyelftools is the default for symbols, types, memory maps, HardFault lines, and desktop features. External GNU tools run only when explicitly selected.
- **Signed desktop updates** — `complete`。The Tauri v2 application discovers signed NSIS updates from Gitee, downloads in the background, and installs after user confirmation. v0.1.2 assets and latest.json are published on GitHub and Gitee.
- **Shared cross-model maintenance workflow** — `complete`。AGENTS.md and the repository skill require dedicated feature/fix branches, branch-local automated and real-hardware qualification before merge, requirement discovery, diagnosis, proportional planning, handoff, and maintainer-only releases without relying on globally installed skills.
- **Cross-platform USB Web entry** — `complete`。One offline HTML uses the strict mklink-ai-probe://web start/open/stop protocol. User-scoped Windows, macOS, and Linux handlers start the existing loopback GUI, reuse existing Web services without ownership, and stop only identity-verified processes started by the entry.
- **Browser file-source loading** — `complete`。The Web configuration page uses a native browser file input and multipart upload for AXF/ELF/OUT and MAP sources, while Tauri keeps its native path dialog. Uploaded files are suffix-checked, size-limited, content-addressed, and stored under the runtime project .mklink directory.
- **AI-first README and Web GUI onboarding** — `complete`。The repository landing page gives users GitHub and Gitee links for AI-assisted Skill installation, documents complete Web GUI setup and use, distinguishes the Windows desktop and USB HTML entry, and removes obsolete V3.3.3/V4.3.3 firmware release content and stale toolchain prerequisites.
- **Upstream PR and maintainer handoff** — `complete`。The Aladdin-Wang GitHub fork master is published and proposes the complete 237-commit delta to su5176/Mklink-AI-Probe master in PR #3. Gitee was not synchronized because this request authorized GitHub and the upstream PR only.

## 验证证据

- **GitHub publication and upstream PR**：GitHub accepted the origin master push, the origin branch resolved to the published source tip, and su5176/Mklink-AI-Probe PR #3 was read back as OPEN from Aladdin-Wang:master to su5176:master with 331 changed files and no upstream-only commits or reported CI checks. Gitee master was read-only checked and intentionally left at e911e62.
- **README and Web GUI onboarding**：The documentation-only change was checked against current CLI help, pyproject requirements, Web entry behavior, browser file-source limits, built-in ELF policy, and release constraints. Every local Markdown target exists, stale V3.3.3/V4.3.3 and MK-Firmware release-history references are absent from both READMEs, Gitee returned HTTP 200, the GitHub repository address matches the configured and queried origin, and git diff validation passed. Runtime code did not change, so automated product suites and real-hardware qualification were not required.
- **Firmware download priority and debug-control repair**：RED tests reproduced all four stale debug CLI resolver calls, installed/custom algorithms outranking bundled sources, missing address-coverage fallback, unstable multi-version selection, and lost explicit custom choices in online/offline flows. Final review found no Critical or Important issues. The final gate passed Python 957 with 1 skipped, GUI 36 files/401 tests, Rust 6 tests, cargo check, and the production Vite build. On the STM32F103 fixture, Keil build completed with zero errors/warnings and native download reported erase/program/verify/application-running success; pyOCD then verified the same HEX, programmed exactly its 56 covered sectors, verified, reset, and disconnected. The repaired resume command succeeded on real hardware and the runtime counter changed after both Keil and pyOCD downloads. A clean archive of the tested commit replaced the Codex global Skill; the installed copy repeated Keil build/download with verify, served the bundled Web client, completed pyOCD online verify, and resumed the target. Old Skill backups were removed and ports 8765 and 5173 were closed afterward.
- **Dedicated feature-branch workflow**：Three baseline pressure scenarios exposed that the previous rules allowed direct master development, treated feature branches as optional, and left stale verification after master advanced ambiguous. Repeating the same scenarios against the revised AGENTS.md and repository skill made every agent select a feature/fix branch, reject direct master development, invalidate evidence after master advanced, and require the automated plus affected real-hardware gates before merge.
- **v0.1.2 final source gate and real hardware**：The final source gate passed Python 948 with 1 skipped, GUI 36 files/400 tests, Rust 6 tests, cargo check, the production Vite build, builder prerequisite checks, and npm production audit with zero vulnerabilities. Against the STM32F103 fixture, the Web runtime uploaded the real AXF and MAP into its user-data workspace, connected with the uploaded AXF through the builtin ELF backend, loaded a 4,851-item symbol catalog, and sampled a selected RAM variable through SuperWatch for about 19,000 read cycles with zero read errors or drops before stop/reset/disconnect.
- **v0.1.2 installed candidate and publication**：The signed standard NSIS overwrote the local v0.1.1 installation under a Windows-system-only PATH. The installed v0.1.2 used one bundled sidecar and no Python child, exposed builtin ELF, discovered one probe without recording its identifier, uploaded the real AXF/MAP into an isolated runtime directory, connected the STM32F103 target, and sampled a selected RAM variable for 3,215 cycles with zero errors or drops. RTT-to-SuperWatch and SuperWatch-to-RTT switching each stopped the previous dashboard automatically. Normal window close removed all product processes and released port 8765. GitHub and Gitee expose the four release attachments, anonymous Gitee installer download passed size/SHA-256 verification, and both latest.json files point to the signed v0.1.2 Gitee payload.
- **Cross-platform USB Web entry**：Focused Web-entry and CLI coverage passed 34/34, the full Python suite passed 945 with 1 skipped, the GUI suite passed 36 files/397 tests, and the production Vite build passed. On Windows, the real user-level protocol and physical MICROKEEN USB HTML reused an existing Web service without changing its PID or stopping it, then independently started one owned loopback GUI, reused the same PID on a second click, and stopped only that owned process. Uninstall removed the owned registry tree and reinstall restored it. macOS and Linux registration/quoting are covered by unit tests but were not run on those operating systems.
- **RTT View and SuperWatch interaction change**：The full GUI suite passed 36 files/397 tests, the production Vue/Vite build passed, and focused dashboard resource plus RTT/SuperWatch Python tests passed 111/111. A system Edge Web-client run against the STM32F103 fixture verified named RTT channels, chart interaction and retention, both mutual-switch directions, timestamped selected-variable raw logs, and literal L entry in the SuperWatch search. The same browser verified the 390x348 version-history popover stayed within a 1280x800 viewport and supported hover, click pinning, and outside close without layout overlap.
- **v0.1.1 automated baseline**：Release source b3c7925 passed Python 915 with 1 skipped, GUI 35 files/387 tests, Rust 6 tests, Vite production build, cargo check, and production npm audit with zero vulnerabilities.
- **Installed application**：The standard NSIS ran with the bundled sidecar under a Windows-system-only PATH, exposed the builtin ELF backend, spawned no Python child, discovered a probe without recording its identifier, and released processes and port 8765 on close.
- **Real V4 offline deployment**：Deployment auto-generated a missing preview, left no staging backup on the probe disk, selected the configured script name, and delivered device output as 87 live line events before successful completion.
- **Published update**：GitHub and Gitee expose the same four v0.1.2 release attachments; anonymous Gitee download and SHA-256 passed, and both public latest.json files point to the signed v0.1.2 Gitee NSIS payload.
- **Repository maintenance workflow**：The repository skill passed skill-creator quick validation; release preparation/publication tests passed 12/12; AI memory validation and git diff checks passed.
- **Repository synchronization**：Obsolete feature branches were removed locally and from GitHub/Gitee. Both hosts retain only master and updates, with matching branch heads and tags before this final handoff.

## 架构决策

- Agent-driven firmware download uses an available project IDE's verified native build/download commands first, pyOCD online flash when the IDE path is unavailable or not applicable, and the MKLink offline API last. A backend that has started and failed stops with evidence instead of silently falling through; python -m mklink flash is an explicit compatibility/diagnostic path.
- Automatic FLM resolution ranks bundled Pack, bundled DAPLink, installed Pack, then registered custom algorithms, considers all tiers for address coverage, preserves Pack-version discovery order, and lets explicit user selections override the automatic order. HPM remains ROM API/BIN only.
- Every runtime or user-facing feature and bug fix must start on a dedicated feature/<topic> or fix/<topic> branch created from a clean, current master. Required automated tests, production build, project-memory update, and affected real-hardware closed loop must pass on the branch before merge; later code or integration changes invalidate that evidence.
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
- Repository instructions and the bundled skills/maintaining-mklink-ai-probe/SKILL.md are the cross-model source of truth. Computer-global workflow skills must not override or add required process to this repository because their contents differ across developer machines.
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

1. Monitor su5176/Mklink-AI-Probe PR #3, answer review feedback on a dedicated feature or fix branch, and merge into Aladdin-Wang master only after the required automated and affected real-hardware gates pass.
2. Qualify the same USB HTML and user-level protocol on one current macOS system and one mainstream Linux desktop, including browser confirmation and USB HID/serial permissions.
3. Ensure the deployed skill/runtime package carries matching built gui/dist assets and runs web-entry install whenever its absolute installation path changes.
4. Confirm an installed older client discovers, downloads, and installs v0.1.2 in the maintainer's normal desktop environment.
5. Qualify the standard NSIS on a second clean Windows 10/11 system without Python, Node, Rust, Keil, GNU Arm tools, or a Pack cache.

## 已知限制

- The available STM32F103 fixture uses pyOCD's bundled builtin target algorithm. Bundled Pack/DAPLink versus installed/custom priority, address fallback, and explicit override behavior are covered by automated catalog/API/UI tests; this fixture did not provide a second physical target that requires a repository-bundled Pack or DAPLink FLM.
- The protocol handler was exercised on Windows only. macOS LaunchServices and Linux xdg-mime behavior still need real-system qualification even though their generated files and quoting have automated coverage.
- Every target computer needs a complete Mklink runtime with GUI dependencies and built gui/dist assets plus one-time web-entry registration; the USB HTML intentionally contains no executable runtime.
- The v0.1.2 NSIS has not been qualified on a second clean Windows machine without development tools.
- The updater payload has Tauri integrity signing but no Windows Authenticode signature, so Windows may show an unknown-publisher warning.
- The installed v0.1.2 Tauri application passed backend and hardware lifecycle qualification, but no automated screenshot capture was available from its WebView2 surface.
- Some optional online Pack operations require outbound HTTPS, and unqualified hardware/power-loss scenarios remain device-specific.

## 延续协议

- Follow AGENTS.md and skills/maintaining-mklink-ai-probe/SKILL.md.
- Reconcile AI memory with live Git and runtime state before editing.
- Create a dedicated feature or fix branch before runtime or user-facing implementation, complete the required automated and real-hardware gates there, and merge only after the branch passes.
- Before ending, run proportional checks and git diff --check, update memory, render and validate the handoff, then commit and push when authorized.
