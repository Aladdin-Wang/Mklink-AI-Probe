# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-30T22:41:14+08:00`
- 分支：`feature/remote-stcp-site-agent`
- HEAD：`The isolated branch is a six-layer local replay rooted at formal upstream 98baf393f328cac2938c3d4e49d15d9f0b48bc91. Its exact final SHA is recorded by the N4/N4T handoff gates rather than self-referenced inside this commit.`
- 远端 HEAD：`The locally recorded origin/master is 98baf393f328cac2938c3d4e49d15d9f0b48bc91. N1-N4 performed no fetch, pull, push, PR, tag, Release, upload, or other network mutation.`
- 工作树：The isolated feature branch contains six reviewable commits: remote core, in-process STCP, standalone Site Agent, Windows reservation hardening, focused tests/package metadata, and documentation/project memory. The stack is local and unpublished.
- 当前任务：Freeze and independently qualify the six-commit remote/STCP/Site Agent replay, then produce deterministic Windows x86_64 Site Agent package evidence without changing the approved product scope.
- 状态：`remote_stcp_site_agent_local_stack_package_proof_pending`

## 里程碑

- **Published product baseline** — `complete`。Official v0.1.4 remains the immutable public baseline; this local replay is rooted at the clean formal upstream snapshot 98baf393.
- **Remote core and in-process STCP** — `complete`。Engineer-side SDK/CLI/MCP, authenticated direct WebSocket protocol, site registry, atomic upload, high-risk confirmation, and pinned in-process STCP bridge are isolated in commit layers 1 and 2.
- **Standalone Site Agent and Windows hardening** — `complete`。The field-machine Site Agent, GUI/package inputs, platform reservation hardening, and real Windows Tauri/WebView2 surface are isolated in commit layers 3 and 4.
- **Tests, deterministic metadata, and handoff** — `complete`。Focused remote tests, exact build-tool pins, typed pending package provenance, direct deployment documentation, and generated project memory are isolated in commit layers 5 and 6.
- **Final replay and package proof** — `pending`。N4T must freeze the exact six-commit HEAD; N5 must independently build A/B packages and publish canonical SHA-256/size evidence at REQ-PACKAGE-10:evidence/packages.json.

## 验证证据

- **Source and scope freeze**：N1 froze clean formal upstream 98baf393 and read-only candidate 6cff397 with 170 status records, 9,271 status bytes, and status SHA-256 d29a35d9ae52ab495b8ca574946fa5a7ff439b109a73ca578c6aa783cbb577a2. Replay ownership is enforced by the canonical scope and shared-hunk ledgers.
- **Remote core and STCP qualification**：N2T approved commit layers 1 and 2: full Python 1,094 passed with 1 unrelated skip, focused remote 81 passed, Go 1.25.11 with CGO and UCRT64 GCC passed, contract alignment passed 7 rows, 27 changed paths were inside the ledger, and sensitive-data hits were zero.
- **Site Agent, GUI, and Windows qualification**：N3T approved commit layers 3 and 4: Site Agent Rust 5 passed plus cargo check, Python platform tests 4 passed, GUI 38 files/422 tests plus test and production builds passed, and a genuine Tauri/WebView2 window served healthy port 8765 before deterministic owned-process cleanup and byte-for-byte schema restoration.
- **Deterministic metadata and focused tests**：N4 commit layer 5 collected 107 new remote test nodes and ran 24 package-metadata, direct-only, exact-pin, STCP, and upstream-integration checks successfully. Package provenance is explicitly pending N5 and contains no candidate artifact SHA-256 or size.
- **Final package evidence**：Pending. N5 is the sole producer for canonical Windows x86_64 Site Agent package hashes and sizes at REQ-PACKAGE-10:evidence/packages.json; historical candidate artifact values are not final replay evidence.

## 架构决策

- AGENTS.md and the repository Skill are the workflow source of truth. Runtime changes use a dedicated branch, proportionate automated gates, and affected real-surface validation before merge.
- Official signing, tags, Releases, latest.json, Gitee synchronization, push, and PR creation require explicit maintainer authority.
- HPM targets always use the ROM API and never FLM. Bundled pyelftools is the default ELF/DWARF backend; external GNU tools run only when explicitly selected.
- Agent-driven firmware download prefers an available IDE-native verified flow, then pyOCD online flash, then MKLink offline deployment. A started backend failure is reported before any switch.
- Dashboard sessions and one-shot SWD/download operations use serialized resource arbitration; one user operation never preempts another.
- MCP stdio owns stdout exclusively for JSON-RPC; ordinary diagnostics are redirected to stderr.
- Remote field machines run only the official standalone Site Agent. Engineer machines use the Skill, SDK, remote CLI, or optional remote MCP.
- Remote transport is authenticated direct ws/wss over a managed VPN or LAN. Non-loopback listeners require explicit --allow-lan and token configuration; tokens come only from environment variables or owner-only files.
- LAN STCP is implemented as a pinned in-process library bridge. No frpc/frps executable is launched or packaged, and tunnel, Site Agent, and local operator confirmation credentials remain distinct.
- Uploads are atomic and inert until a later operation consumes the opaque reference. Flash, erase, writes, activation, and Agent stop require explicit local confirmation plus server-side validation.
- The six replay layers remain reviewable and unpublished until N4T and N5 approve exact HEAD and deterministic package evidence.

## 真机环境

- **probe**：No probe or identifier was accessed during N1-N4.
- **target**：No target, serial port, Modbus device, or firmware image was accessed during N1-N4.
- **permission**：The current replay and N5 package-proof scope does not authorize hardware actions.

## 下一动作

1. N4T: freeze the exact six-commit HEAD, verify commit subjects/order, scope ledgers, memory/render freshness, clean schemas, and canonical evidence links.
2. N5: from the N4T-approved HEAD, build the Windows x86_64 Site Agent package twice in clean isolated environments and publish matching hashes, sizes, manifests, and audit results at REQ-PACKAGE-10:evidence/packages.json.
3. After N4T and N5 pass, request explicit maintainer direction before any fetch, push, PR, tag, Release, signing, upload, or remote publication.

## 已知限制

- Final Windows x86_64 Site Agent package SHA-256 and size are pending N5; REQ-PACKAGE-10:evidence/packages.json is the only canonical pointer.
- The plan-owned GUI has no registered mock GUI E2E directory or --run-e2e surface, so that gate is not applicable; unit, test-build, production-build, and real Tauri/WebView2 evidence passed.
- The six-commit stack is local and unpublished. No network refresh was performed, so origin/master is the locally recorded 98baf393 snapshot.
- N1-N4 intentionally performed no HIL, probe, serial, Modbus, flash, signing, publication, or upload action.
- N4 static package metadata tests do not substitute for N5 clean A/B package production and hash/size comparison.

## 延续协议

- Validate docs/ai/project-memory.json, render docs/ai/CURRENT_HANDOFF.md, validate again, and compare the generated handoff before acting.
- Resolve the live Git/source root and verify the current HEAD against the N4T canonical pointer; do not infer HEAD from this self-referential docs commit.
- Treat REQ-PACKAGE-10:evidence/packages.json as pending until N5 publishes it; never reuse candidate package hash or size as final evidence.
- Follow the approved scope/shared-hunk ledgers and stop for new authority before network, hardware, publication, or out-of-scope changes.
