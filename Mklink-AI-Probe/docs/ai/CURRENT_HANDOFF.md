# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-24T00:24:03+08:00`
- 分支：`fix/symbol-source-state`
- HEAD：`The qualified v0.1.3 release branch is based on upstream merge commit 6cff397 and includes shared symbol-source repair, aggregate-symbol recovery, RTT encoding, unified SWD arbitration, and proactive verified Skill updates.`
- 远端 HEAD：`su5176/Mklink-AI-Probe PR #3 merged on 2026-07-23. Gitee was not changed by the PR work.`
- 工作树：The release implementation, regression tests, rebuilt gui/dist, v0.1.3 version bump, automatic Skill updater, release tooling, and this memory update are ready to commit on fix/symbol-source-state. The earlier local candidate predates the updater and must not be published; all owned processes are closed and port 8765 is free.
- 当前任务：Publish the qualified v0.1.3 repairs and verified proactive Skill/desktop update mechanism from final master.
- 状态：`authorized_for_v0.1.3_release`

## 里程碑

- **Product baseline** — `complete`。Online/offline flash, debug control, symbols and types, bounded streaming, Serial, Modbus, MCP, and resource arbitration are implemented.
- **Web and desktop distribution** — `complete`。The Vue Web client, Tauri v2 desktop app, bundled Python sidecar, strict USB Web entry protocol, browser file uploads, and signed updater flow are available.
- **Compatibility hardening** — `complete`。Builtin pyelftools is the default, FastAPI 0.139.2 is supported, Windows venv process guards are stable, test extras are complete, and the frontend audit is clean.
- **Upstream integration** — `complete`。su5176/Mklink-AI-Probe PR #3 merged fork commit d344e5f into upstream master as 6cff397.
- **Shared symbol-source state** — `complete`。Symbol reparsing now binds the current Device explicitly, serializes SuperWatch stop/rebind/restart, uses one transaction for parse and connected-reload endpoints, rejects requested/active path mismatches, and exposes active versus pending AXF state consistently in the frontend.
- **Aggregate symbol recovery** — `complete`。Anonymous struct and union layers expand transparently, overlapping union interpretations remain selectable, unsupported aggregates remain visible as containers, and a bounded pycparser-backed C layout override is shared by Web, Tauri, and AI-launched services.
- **RTT encoding and SWD arbitration** — `complete`。RTT preserves device bytes until the Dashboard applies UTF-8, GB2312, GBK, GB18030, or Big5 decoding. One-shot SWD and download operations safely preempt Dashboard owners but never another user operation.
- **Proactive verified updates** — `complete`。The installed Skill checks the public update manifest once per AI session with a 24-hour cache, reports newer releases without blocking hardware work, and updates the desktop app and copied Skill only after explicit approval with size and SHA-256 verification.

## 验证证据

- **Latest source gate**：Python passed 989 with 1 skipped; GUI passed 36 files/412 tests; Rust passed 6 tests; cargo check, Vite 8.1.5 production build, npm audit with zero vulnerabilities, and the Tauri builder prerequisite check passed.
- **Update and release automation**：Focused updater and publisher coverage passed 20 tests. Real public-manifest checking saw public v0.1.2 from the v0.1.3 source without a false update. Release preparation now requires a verified flat installable Skill archive, and publication preserves Tauri compatibility while adding installer and Skill URL, size, SHA-256, and source commit metadata.
- **Installed v0.1.3 candidate**：The local v0.1.3 standard NSIS overwrite-installed with a restricted PATH, served health and probe discovery from its bundled sidecar with no Python process, parsed the requested STM32F103RC AXF into 5,157 symbols, applied a pasted C layout, switched all five RTT encodings, sampled SuperWatch 28,610 times with zero read errors or drops, and passed read-memory plus online connect-reset-disconnect preemption. Normal close released all owned processes and port 8765. The candidate SHA-256 is 70DF1FA953CC8B586534CF9E602E0897E096795E0298CA1AFC55F8C4ABD25B87 and Authenticode status is NotSigned.
- **Upstream merge**：GitHub reports PR #3 MERGED at 2026-07-23T07:23:40Z. Merge commit 6cff397 has parents 51a2f8d and the qualified fork head d344e5f.
- **Shared symbol automated gate**：Regression coverage includes source ownership, anonymous struct and union expansion, overlapping union aliases, unresolved containers, C natural and packed layout, input limits, fingerprint-scoped overrides, API validation, SuperWatch rebind and restore, manual path UI, and C definition UI.
- **Symbol-source real hardware**：The repaired service switched between two real AXFs with distinct symbol counts, supported connected reload from a second client path, and preserved SuperWatch operation during an additional reload. After deployment to port 8765, parse-axf selected 4,842/129/107 symbols at generation 2 and connected reload restored 791/150/99 at generation 3. Requested and active paths matched after every operation.
- **Aggregate-symbol real hardware**：A real STM32 AXF expanded data_save at 0x20000648 into 27 selectable scalar interpretations, including odo, mileage_odo, and trip. SuperWatch completed 32,613 reads with zero read errors and zero read drops. A real unresolved one-byte aggregate accepted a pasted matching C definition, produced a selectable member at the correct RAM address, and was added through the shared SuperWatch API.
- **SWD arbitration real hardware**：SuperWatch held both probe resources while reading data_save.odo, then a real read-memory operation stopped it before returning eight target bytes and left the device READY with no leases. A second SuperWatch run was preempted by an online connect-reset-disconnect job, which succeeded without erasing or programming Flash; 46,591 reads completed with zero read errors and zero read drops.
- **RTT encoding real service**：The source service accepted GBK at RTT start and exposed the active encoding in shared status. Automated byte-boundary tests covered GBK and four-byte GB18030 text plus runtime switching. The current target image did not initialize the AXF RTT control-block symbol, so live text capture was unavailable and startup released resources cleanly.
- **Real browser UI**：After rebuilding gui/dist for v0.1.3, Playwright drove the installed Chrome executable against the source Web service at desktop and 390 px mobile viewports. UTF-8, GB2312, GBK, GB18030, and Big5 were selectable; Symbols and the SuperWatch manual-variable/C-layout controls opened; console errors and document overflow were zero. Dashboard tabs were hardened to remain single-line and scroll within the tab bar on narrow screens.

## 架构决策

- AGENTS.md and the repository skill are the workflow source of truth. Runtime changes use a dedicated feature/fix branch, the full Python and GUI suites plus production build, and an affected real-surface hardware loop before merge.
- Official signing, tags, Releases, latest.json, and Gitee synchronization require explicit maintainer authority. Build standard NSIS by default; MSI and offline WebView2 bundles require explicit authorization.
- HPM targets always use the ROM API and never FLM. Bundled pyelftools is the default ELF/DWARF backend; external GNU tools run only when explicitly selected.
- Agent-driven firmware download prefers an available IDE-native verified flow, then pyOCD online flash, then MKLink offline deployment. Automatic algorithms rank bundled Pack, bundled DAPLink, installed Pack, then custom while explicit choices remain authoritative.
- Web entry accepts only mklink-ai-probe://web start/open/stop operations, binds loopback, serializes launches, and stops only identity-verified processes it owns. Each host needs the complete runtime and one-time protocol registration.
- Browser AXF/MAP selection uploads suffix-checked, size-limited, content-addressed files into runtime project storage; Tauri retains native path selection.
- Dashboard starts share serialized resource arbitration, stop conflicting sessions, and acquire leases atomically. One-shot user SWD operations and online/offline downloads may preempt user:dashboard owners only after their synchronous stop succeeds; stop failure rolls back the new lease, and one user operation never preempts another.
- FastAPI route tests support both flattened and lazy included-router layouts. On Windows, guarded worker wrappers use the base Python interpreter so venv launcher PID proxies cannot escape parent-death protection.
- AXF reload is a shared backend transaction. The current connected Device is authoritative, SuperWatch is rebound to that exact instance, and parse/connect endpoints fail with HTTP 409 when the requested source did not become active.
- Frontend file inputs are pending configuration until the backend reports the same normalized active path. All clients read one server-side active symbol state instead of treating a successful HTTP response as proof.
- Desktop and Web-entry lifecycle follows process ownership: a client closes only a backend process it created and still owns. Browser tabs and desktop windows that reuse an existing service must not terminate that shared service.
- Anonymous struct and union members are flattened into their legal C access paths. All named union interpretations remain visible and are marked as overlapping instead of silently discarding aliases.
- Pasted C layouts are limited to 64 KiB and 512 scalar leaves, reject pointers and bit-fields, require exact AXF storage-size agreement, and are retained only in memory under the AXF path, size, and mtime fingerprint.
- RTT bridge sessions retain raw target bytes. The RTT Dashboard owns incremental UTF-8, GB2312, GBK, GB18030, or Big5 decoding and publishes the existing UTF-8 browser stream protocol; runtime encoding changes discard only unfinished decoder state and affect subsequent bytes.
- Copied Skills check Gitee then GitHub at first MKLink use in each AI session, cache successful checks for 24 hours, and never interrupt an active debug or flash operation. Installation requires explicit approval, verifies published size and SHA-256, refuses Git checkouts, backs up the Skill, and requires a new AI session after replacement.
- The updates/latest.json document remains compatible with Tauri while adding verified installer and Skill metadata. Both public Releases and both anonymous Gitee asset checks complete before either updates branch is replaced.

## 真机环境

- **probe**：MKLink V4 available; identifier omitted.
- **target**：STM32F103RC fixture available; local project path omitted.
- **permission**：Firmware build/flash and read-only target validation are permitted when required by the active task.

## 下一动作

1. Commit the qualified fix/symbol-source-state branch, merge it into clean master, and repeat the final release checks from the exact master commit.
2. Build and overwrite-install the final signed v0.1.3 standard NSIS, qualify health, probe discovery, bundled-sidecar identity, shutdown, and port release, then prepare exactly five public assets.
3. Publish v0.1.3 to GitHub and Gitee, replace updates/latest.json last, anonymously verify both public payloads and manifest metadata, then update the local copied Skill through the public updater.
4. Qualify USB Web entry registration and browser launch on current macOS and Linux systems.
5. Qualify the standard NSIS and older-client updater on a clean Windows machine without development tools.

## 已知限制

- Python 3.13 is not installed locally; its Windows venv launcher behavior reproduced on Python 3.14.5 and passed the real process-guard integration after the fix.
- The USB Web entry has real Windows coverage only; macOS LaunchServices and Linux xdg-mime still need physical-system qualification.
- The standard NSIS still needs qualification on a second clean Windows 10/11 machine and an older-client updater check. The installer has Tauri integrity signing but no Windows Authenticode signature.
- The available target covers the builtin STM32 algorithm. Other Pack/DAPLink/custom priority paths are automated-test evidence only; optional network and power-loss cases remain environment-specific.
- The in-app Browser plugin still exposed no controllable instance after reinstall, so browser qualification used repository Playwright with the installed Chrome executable. The packaged sidecar intentionally serves API only; the installed frontend is loaded from Tauri resources rather than from the sidecar HTTP root.

## 延续协议

- Validate memory and reconcile it with live Git/runtime state before acting.
- Follow the repository branch, automated gate, real-surface, and release-authority rules.
- Replace stale facts and consolidate evidence; do not append completed task logs that already exist in Git or verification documents.
