# 当前 AI 交接

> 本文件由 `python scripts/ai_memory.py render` 根据 `project-memory.json` 生成。

## 当前断点

- 更新时间：`2026-07-31T12:51:03+08:00`
- 分支：`feature/remote-stcp-site-agent`
- HEAD：`The formally qualified runtime tip is e071982825c85b91d51ecccac8ce5531f86df876. A documentation-only HIL handoff may follow it; PR #5 headRefOid is the authoritative HIL head and must retain e071982 as an ancestor with only docs/ai and docs/verification changes after it.`
- 远端 HEAD：`Branch feature/remote-stcp-site-agent is published as GitHub PR #5 against master. Verify the live PR headRefOid, mergeability, and base immediately before HIL and merge rather than relying on this self-referential memory commit.`
- 工作树：The isolated feature branch contains the qualified six-layer runtime stack plus the real-hardware acceptance handoff at docs/verification/remote-site-agent-hil.md. No runtime change is authorized after qualification without invalidating the old evidence.
- 当前任务：Execute the signed-off real-hardware matrix in docs/verification/remote-site-agent-hil.md against the live PR #5 head; after every required row passes with no P0/P1 and the target is restored, merge PR #5 without adding another development gate.
- 状态：`remote_stcp_site_agent_hil_pending`

## 里程碑

- **Published product baseline** — `complete`。Official v0.1.4 remains the immutable public baseline; this local replay is rooted at the clean formal upstream snapshot 98baf393.
- **Remote core and in-process STCP** — `complete`。Engineer-side SDK/CLI/MCP, authenticated direct WebSocket protocol, site registry, atomic upload, high-risk confirmation, and pinned in-process STCP bridge are isolated in commit layers 1 and 2.
- **Standalone Site Agent and Windows hardening** — `complete`。The field-machine Site Agent, GUI/package inputs, platform reservation hardening, and real Windows Tauri/WebView2 surface are isolated in commit layers 3 and 4.
- **Tests, deterministic metadata, and handoff** — `complete`。Focused remote tests, exact build-tool pins, typed pending package provenance, direct deployment documentation, and generated project memory are isolated in commit layers 5 and 6.
- **Final replay and package proof** — `complete`。N4T froze runtime tip e071982825c85b91d51ecccac8ce5531f86df876. N5/N5T produced byte-identical Windows x86_64 packages twice: ZIP 18,358,681 bytes with SHA-256 b771eaf0fa308b7fecfeb2c4acae126f521eb6d62fe0e44e477a9b688fb9b709 and manifest SHA-256 6d72fb12dbc32a7659974c4699534776790c7183c88cb2244991d2e20e3d35a7.
- **Real hardware HIL and merge** — `pending`。docs/verification/remote-site-agent-hil.md is the sole remaining merge gate. Required direct-LAN, LAN-STCP, probe/target, safe-RAM, approved-flash, RTT, recovery, and cleanup rows must pass with no P0/P1; then PR #5 may be merged directly.

## 验证证据

- **Source and scope freeze**：N1 froze clean formal upstream 98baf393 and read-only candidate 6cff397 with 170 status records, 9,271 status bytes, and status SHA-256 d29a35d9ae52ab495b8ca574946fa5a7ff439b109a73ca578c6aa783cbb577a2. Replay ownership is enforced by the canonical scope and shared-hunk ledgers.
- **Remote core and STCP qualification**：N2T approved commit layers 1 and 2: full Python 1,094 passed with 1 unrelated skip, focused remote 81 passed, Go 1.25.11 with CGO and UCRT64 GCC passed, contract alignment passed 7 rows, 27 changed paths were inside the ledger, and sensitive-data hits were zero.
- **Site Agent, GUI, and Windows qualification**：N3T approved commit layers 3 and 4: Site Agent Rust 5 passed plus cargo check, Python platform tests 4 passed, GUI 38 files/422 tests plus test and production builds passed, and a genuine Tauri/WebView2 window served healthy port 8765 before deterministic owned-process cleanup and byte-for-byte schema restoration.
- **Deterministic metadata and focused tests**：N4 commit layer 5 collected 107 new remote test nodes and ran 24 package-metadata, direct-only, exact-pin, STCP, and upstream-integration checks successfully. Package provenance is explicitly pending N5 and contains no candidate artifact SHA-256 or size.
- **Final package evidence**：N5/N5T passed. Clean A/B builds are byte-identical: ZIP 18,358,681 bytes, SHA-256 b771eaf0fa308b7fecfeb2c4acae126f521eb6d62fe0e44e477a9b688fb9b709; manifest 27,199 bytes, SHA-256 6d72fb12dbc32a7659974c4699534776790c7183c88cb2244991d2e20e3d35a7; mklink-stcp.dll SHA-256 758e428fe9ed6bcbd9489d6db1990fce5a18680887137ea3ca6d348c27a77c07. Extracted loopback lifecycle passed and no local-path, credential, forbidden-suffix, signing, tag, Release, upload, or merge action occurred.
- **Final integration and publication handoff**：Formal final integration passed: Python 1,202 passed with 1 unrelated skip; GUI 422 tests plus test/production builds and HTTP smoke; Rust Site Agent 5/5 and GUI 6/6 plus checks/builds; Go test/build and canonical DLL reproduction; final audit 23/23 and requirements 34/34. Runtime tip e071982 was pushed normally and opened as GitHub PR #5 with base master; real hardware HIL remains the only merge gate.

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
- The unsigned package is acceptable only for internal HIL on an isolated LAN or managed VPN. A ZIP hash is not a publisher signature; Authenticode and official publication remain separate maintainer-only release gates.
- docs/verification/remote-site-agent-hil.md is the only remaining PR #5 merge gate. HIL must bind the live PR head and frozen package identity, redact hardware identifiers and credentials, restore scratch RAM and approved recovery firmware, and finish with no P0/P1.

## 真机环境

- **probe**：No probe or identifier was accessed by the automated replay, package proof, publication, or HIL-document preparation. The HIL operator must record only a redacted probe model/suffix.
- **target**：No target, serial port, Modbus device, or firmware image was accessed during automated qualification. The required target identity, safe-RAM, approved-flash, RTT, recovery, and cleanup matrix is documented but remains PENDING.
- **permission**：The maintainer requested a written real-machine acceptance gate and authorized completion of all non-hardware work. Actual hardware actions must be performed by the authorized HIL operators under docs/verification/remote-site-agent-hil.md; destructive steps still require the document's local confirmations.

## 下一动作

1. Push the documentation-only HIL handoff, verify PR #5 remains OPEN/MERGEABLE/CLEAN, and record its live headRefOid.
2. Authorized HIL operators execute docs/verification/remote-site-agent-hil.md against the exact PR head and frozen ZIP/manifest, fill every result row, redact evidence, restore target state, and sign the final verdict.
3. When all required rows pass, conditional rows pass or have approved N/A, open P0/P1 is zero, and target restoration is confirmed, merge PR #5 directly. If any runtime fix or master update occurs first, re-run the final automated/package/HIL gates.
4. After merge, obtain separate explicit maintainer authority and certificate access before Authenticode signing, tag, GitHub Release, latest.json, upload, or Gitee synchronization.

## 已知限制

- Real hardware HIL is not yet executed. Automated, mock, extracted-loopback, Tauri/WebView2, and package evidence do not replace the required probe/target closed loop.
- The candidate is unsigned and may be used only for internal isolated-LAN or managed-VPN HIL. Signing and official publication require separate maintainer authority.
- The plan-owned GUI has no registered mock GUI E2E directory or --run-e2e surface; unit, test-build, production-build, and real Tauri/WebView2 evidence passed. The final HIL artifact is the standalone Site Agent ZIP, not a Tauri installer.
- The repository has no _maintainer/testing/tests/e2e/hil directory. The signed-off manual CLI matrix in docs/verification/remote-site-agent-hil.md is the authoritative HIL gate.
- Any runtime change, conflict resolution, or master update after the frozen qualification invalidates the old final evidence and requires requalification before merge.

## 延续协议

- Validate docs/ai/project-memory.json, render docs/ai/CURRENT_HANDOFF.md, validate again, and compare the generated handoff before acting.
- Resolve the live Git/source root; verify e071982 is an ancestor of the live PR #5 head and that every later path is documentation-only before accepting the existing automated evidence.
- Bind HIL to ZIP SHA-256 b771eaf0fa308b7fecfeb2c4acae126f521eb6d62fe0e44e477a9b688fb9b709 and manifest SHA-256 6d72fb12dbc32a7659974c4699534776790c7183c88cb2244991d2e20e3d35a7; do not substitute an unrecorded rebuild.
- Use docs/verification/remote-site-agent-hil.md as the sole remaining merge gate. Never record full probe IDs, COM numbers, credentials, signing keys, local paths, screenshots, firmware binaries, or raw logs in Git.
- Merge only after the HIL final verdict is PASS. Stop for new authority before signing, tag, Release, latest.json, upload, Gitee synchronization, or any out-of-scope publication.
