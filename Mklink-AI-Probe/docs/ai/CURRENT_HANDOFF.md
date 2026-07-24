# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-24T16:48:53+08:00`
- 分支：`master`
- HEAD：`Local master contains the verified v0.1.3 release-history correction, stale Web app cache fix, refreshed Web assets, final local-only handoff, and the maintenance source-root discovery correction prepared for GitHub.`
- 远端 HEAD：`GitHub origin/master remains at 6ce6836 with the verified v0.1.3 release-history correction. The published tag, Releases, and updates/latest.json remain unchanged.`
- 工作树：The old merged worktree and branch, generated build caches, superseded release directories, frontend node_modules, and the obsolete qualification install were removed. The maintenance source-root discovery correction is committed with its rendered handoff, leaving the main worktree clean. The final local installer, updater signature, and Skill ZIP remain outside Git under release/20260724-155059.
- 当前任务：Start future maintenance sessions by resolving the unique project source root before reading AGENTS.md, docs/ai, scripts, or repository Skills. Preserve the local v0.1.3 artifacts and wait for explicit authorization before any v0.1.4 release work.
- 状态：`maintenance_source_root_resolution_ready_for_handoff`

## 里程碑

- **Product baseline** — `complete`。Online/offline flash, debug control, symbols and types, bounded streaming, Serial, Modbus, MCP, and resource arbitration are implemented.
- **Web and desktop distribution** — `complete`。The Vue Web client, Tauri v2 desktop app, bundled Python sidecar, strict USB Web entry protocol, browser file uploads, and signed updater flow are available.
- **Compatibility hardening** — `complete`。Builtin pyelftools is the default, FastAPI 0.139.2 is supported, Windows venv process guards are stable, test extras are complete, and the frontend audit is clean.
- **Upstream integration** — `complete`。su5176/Mklink-AI-Probe PR #3 merged fork commit d344e5f into upstream master as 6cff397.
- **Shared symbol-source state** — `complete`。Symbol reparsing now binds the current Device explicitly, serializes SuperWatch stop/rebind/restart, uses one transaction for parse and connected-reload endpoints, rejects requested/active path mismatches, and exposes active versus pending AXF state consistently in the frontend.
- **Aggregate symbol recovery** — `complete`。Anonymous struct and union layers expand transparently, overlapping union interpretations remain selectable, unsupported aggregates remain visible as containers, and a bounded pycparser-backed C layout override is shared by Web, Tauri, and AI-launched services.
- **RTT encoding and SWD arbitration** — `complete`。RTT preserves device bytes until the Dashboard applies UTF-8, GB2312, GBK, GB18030, or Big5 decoding. One-shot SWD and download operations safely preempt Dashboard owners but never another user operation.
- **Proactive verified updates** — `complete`。The installed Skill checks the public update manifest once per AI session with a 24-hour cache, reports newer releases without blocking hardware work, and updates the desktop app and copied Skill only after explicit approval with size and SHA-256 verification.
- **Release-history accuracy** — `complete`。The source release history and rebuilt Web assets now include the omitted v0.1.3 summary and five user-facing changes, with regression coverage for the current-version badge and entry count.

## 验证证据

- **Latest source gate**：Python passed 989 with 1 skipped; GUI passed 36 files/412 tests; Rust passed 6 tests; cargo check, Vite 8.1.5 production build, npm audit with zero vulnerabilities, and the Tauri builder prerequisite check passed.
- **Update and release automation**：Focused updater and publisher coverage passed 20 tests. Real public-manifest checking saw public v0.1.2 from the v0.1.3 source without a false update. Release preparation now requires a verified flat installable Skill archive, and publication preserves Tauri compatibility while adding installer and Skill URL, size, SHA-256, and source commit metadata.
- **Installed v0.1.3 candidate**：The final v0.1.3 standard NSIS overwrite-installed with a restricted PATH, served health and probe discovery from its bundled sidecar with no Python child, connected the STM32F103RC fixture with the requested AXF through builtin ELF, loaded 5,157 symbols, read eight bytes at 0x20000648, and disconnected cleanly. Normal close released all MKLink processes and port 8765. The published installer SHA-256 is 9A85059E94C3A8E1A3B16268AA2306746F59A555ECFC6252E0C207730F79CEC1 and Authenticode status is NotSigned.
- **Upstream merge**：GitHub reports PR #3 MERGED at 2026-07-23T07:23:40Z. Merge commit 6cff397 has parents 51a2f8d and the qualified fork head d344e5f.
- **Shared symbol automated gate**：Regression coverage includes source ownership, anonymous struct and union expansion, overlapping union aliases, unresolved containers, C natural and packed layout, input limits, fingerprint-scoped overrides, API validation, SuperWatch rebind and restore, manual path UI, and C definition UI.
- **Symbol-source real hardware**：The repaired service switched between two real AXFs with distinct symbol counts, supported connected reload from a second client path, and preserved SuperWatch operation during an additional reload. After deployment to port 8765, parse-axf selected 4,842/129/107 symbols at generation 2 and connected reload restored 791/150/99 at generation 3. Requested and active paths matched after every operation.
- **Aggregate-symbol real hardware**：A real STM32 AXF expanded data_save at 0x20000648 into 27 selectable scalar interpretations, including odo, mileage_odo, and trip. SuperWatch completed 32,613 reads with zero read errors and zero read drops. A real unresolved one-byte aggregate accepted a pasted matching C definition, produced a selectable member at the correct RAM address, and was added through the shared SuperWatch API.
- **SWD arbitration real hardware**：SuperWatch held both probe resources while reading data_save.odo, then a real read-memory operation stopped it before returning eight target bytes and left the device READY with no leases. A second SuperWatch run was preempted by an online connect-reset-disconnect job, which succeeded without erasing or programming Flash; 46,591 reads completed with zero read errors and zero read drops.
- **RTT encoding real service**：The source service accepted GBK at RTT start and exposed the active encoding in shared status. Automated byte-boundary tests covered GBK and four-byte GB18030 text plus runtime switching. The current target image did not initialize the AXF RTT control-block symbol, so live text capture was unavailable and startup released resources cleanly.
- **Real browser UI**：After rebuilding gui/dist for v0.1.3, Playwright drove the installed Chrome executable against the source Web service at desktop and 390 px mobile viewports. UTF-8, GB2312, GBK, GB18030, and Big5 were selectable; Symbols and the SuperWatch manual-variable/C-layout controls opened; console errors and document overflow were zero. Dashboard tabs were hardened to remain single-line and scroll within the tab bar on narrow screens.
- **v0.1.3 publication and local Skill update**：GitHub and Gitee Releases contain the same five assets. Anonymous Gitee installer and Skill downloads match the local sizes and SHA-256 values; both public updates/latest.json files report version 0.1.3 and source commit f9f2f70a9da4607312542ace4a1ddd0e9202d20f. The copied local Skill was bootstrapped from 0.1.2 and updated through the public Skill updater to 0.1.3; a forced check now reports update_available=false and requires an AI restart.
- **v0.1.3 version-history correction**：The full gate passed Python 989 with 1 skipped, GUI 36 files/412 tests, Rust 6 tests, cargo check, the Vite production build, and npm audit with zero vulnerabilities. Local Chrome Playwright opened the real config page at desktop 1440x900 and mobile 390x844, clicked the footer version, and found v0.1.3 first with the current-version badge, all five release notes, four stable entries, no failed requests, no framework overlay, and no console warnings or errors.
- **Local-only v0.1.3 desktop refresh**：The final cache-corrected standard NSIS bundle from f9ecec3 was copied to release/20260724-155059 as Mklink-AI-Probe-v0.1.3-local-f9ecec3-x64-Setup.exe. Its size is 65,560,254 bytes, SHA-256 is 55BACCDD7DC0D2652DDC3FE1062E29AB277098E0B45766556CE3940423FC23E6, updater-signature SHA-256 is EA0B5E082B628026B93C2D8159A5E4AF1148C13D7290BFCC311639AE229D00FB, product version is 0.1.3, and Authenticode is NotSigned. Restricted-PATH qualification passed bundled-sidecar health, builtin ELF 0.32, and probe discovery with no Python child; normal close released both sidecars and port 8765. The installer was placed in the normal per-user location and both desktop and Start Menu shortcuts were verified.
- **Copied Skill and user-level Web entry**：The copied user-level Skill remains version 0.1.3 and now records source commit ea0a235bc9d11bcc5bc40ddae63433a7efb80753. Its validated local archive is 2,512,975 bytes with SHA-256 39BEB97D861B696BCC6735F4247EC7BE35133A6200F591C49EB486E37F3A95CC; installation retained a pre-update backup and its editable gui+mcp package reports version 0.1.3 from the copied Skill. Web-entry registration was regenerated from that Skill rather than the developer checkout; its handler inserts the copied Skill root, owns the Python GUI process on 127.0.0.1:8765, and serves builtin pyelftools 0.32 health successfully.
- **Shared Web and desktop lifecycle**：With the user-level Web entry owning port 8765, the normally installed Tauri desktop app opened using the existing service, spawned only its WebView2 child, and did not launch a second mklink sidecar. Closing the desktop window normally returned exit code 0 while the original Web-entry PID and healthy API remained unchanged. After packaged qualification, Web-entry was restarted and intentionally left owning port 8765.
- **Stale Web app cache correction**：A real Edge tab displayed cached v0.1.2 assets while the same port served the copied v0.1.3 Skill. Root cause was that index.html and SPA fallback responses had no cache policy and Web-entry reopened a stable URL. The f9ecec3 fix serves the app shell with Cache-Control no-store, revalidates unhashed static files, serves hashed assets as one-year immutable, and opens a URL containing the current index SHA-256 prefix. Focused tests passed 53; the full gate passed Python 991 with 1 skipped, GUI 36 files/412 tests, Rust 6 tests, cargo check, Vite production build, npm audit with zero vulnerabilities, and the Tauri prerequisite check. Actual isolated Microsoft Edge opened ?build=51b73617dadd#/config, displayed v0.1.3 and build f9ecec30a315, showed four release entries and five v0.1.3 notes with the current badge, and had no console errors or failed requests.
- **Workspace cleanup and source-root handoff**：The workspace was reduced from about 8.88 GB to 85 MB while preserving release/20260724-155059 and its three verified hashes. Git now lists only the main worktree, project memory validates, and the user-level Web entry remains healthy and owned on port 8765. The repository and copied user-level maintenance Skills now resolve a unique source root from the Git top-level before reading relative handoff paths; both passed quick_validate.py, and the current nested checkout resolved uniquely to the inner Mklink-AI-Probe source directory.

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
- Published release tags are immutable. The missing v0.1.3 history text is corrected in subsequent source and release artifacts; do not move or republish the existing v0.1.3 tag.
- End-user Web entry, Web GUI, and MCP installation must use the complete copied user-level Skill/runtime as their source. Run web-entry registration from that Skill after install or update so its absolute handler path never depends on a developer checkout; desktop clients may reuse the resulting service without taking ownership.
- Web app shells and SPA fallbacks must use no-store so a same-port runtime update cannot retain an old index. Content-hashed assets may be immutable, and Web-entry URLs carry the current index digest before the hash route so a newly opened client navigates to the installed build even when the browser has an older tab or cache entry.
- Maintenance instructions must resolve the unique project source root before using relative AGENTS.md, docs, scripts, or repository Skill paths. The Git/workspace root and source root may differ; release and worktree storage remain anchored at the live Git/workspace root.

## 真机环境

- **probe**：MKLink V4 available; identifier omitted.
- **target**：STM32F103RC fixture available; local project path omitted.
- **permission**：Firmware build/flash and read-only target validation are permitted when required by the active task.

## 下一动作

1. Carry the merged v0.1.3 history correction and f9ecec3 Web cache correction into the next explicitly authorized v0.1.4 installer release without moving or republishing the v0.1.3 tag, and resolve or explain the 390 px in-app Chrome horizontal overflow first.
2. Qualify USB Web entry registration and browser launch on current macOS and Linux systems.
3. Qualify the standard NSIS and older-client updater on a clean Windows machine without development tools.

## 已知限制

- Python 3.13 is not installed locally; its Windows venv launcher behavior reproduced on Python 3.14.5 and passed the real process-guard integration after the fix.
- The USB Web entry has real Windows coverage only; macOS LaunchServices and Linux xdg-mime still need physical-system qualification.
- The standard NSIS still needs qualification on a second clean Windows 10/11 machine and an older-client updater check. The installer has Tauri integrity signing but no Windows Authenticode signature.
- The available target covers the builtin STM32 algorithm. Other Pack/DAPLink/custom priority paths are automated-test evidence only; optional network and power-loss cases remain environment-specific.
- The packaged sidecar intentionally serves API only; the installed frontend is loaded from Tauri resources rather than from the sidecar HTTP root.
- The refreshed user-level Web GUI passed its desktop browser check, but an in-app Chrome viewport forced to 390x844 reported document scrollWidth 456 and visibly compressed top navigation labels. Earlier standalone Playwright evidence reported no mobile overflow, so reconcile the browser zoom/extension environment and responsive header behavior before the next installer release.

## 延续协议

- Validate memory and reconcile it with live Git/runtime state before acting.
- Follow the repository branch, automated gate, real-surface, and release-authority rules.
- Replace stale facts and consolidate evidence; do not append completed task logs that already exist in Git or verification documents.
