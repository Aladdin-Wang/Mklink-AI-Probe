# MKLink Online Flash and Streaming Roadmap Implementation Plan

> **Historical completed plan.** Do not execute its task checklist or skill instructions. Use `docs/ai/CURRENT_HANDOFF.md` for current work.

**Goal:** Deliver an MKLink-only CMSIS-DAP online programmer with on-demand CMSIS-Pack support, then migrate SystemView, VOFA, RTT, and SuperWatch to a measured high-throughput streaming pipeline.

**Architecture:** Split delivery into two independently testable plans. The online-flash plan adds a modular pyOCD control plane, PackCatalog, resource arbitration, HEX/BIN inspection, and a four-zone Vue page. The streaming plan adds a binary WebSocket data plane, Worker-owned typed buffers, 30 FPS rendering, and per-stage performance telemetry.

**Tech Stack:** Python 3.9+, FastAPI, pyOCD 0.44.x, cmsis-pack-manager, IntelHex, Vue 3, TypeScript, Web Workers, WebSocket, Canvas 2D, Vitest, pytest, Tauri v2.

---

## Source documents

- Design: `docs/superpowers/specs/2026-07-10-online-flash-high-throughput-design.md`
- Online flash plan: `docs/superpowers/plans/2026-07-10-online-flash.md`
- Streaming plan: `docs/superpowers/plans/2026-07-10-high-throughput-streams.md`

All paths in the two child plans are relative to the inner project root:

```text
E:\software\HPM5300\Mklink-AI-Probe\Mklink-AI-Probe
```

Git commands run from the outer repository root:

```text
E:\software\HPM5300\Mklink-AI-Probe
```

## Roadmap checklist

- [ ] Milestone A: Online flash foundation passes focused tests and is pushed.
- [ ] Milestone B: Online flash backend passes full Python regression and is pushed.
- [ ] Milestone C: Online flash GUI, HEX/BIN hardware loop, and Tauri build are verified and pushed.
- [ ] Milestone D: Binary protocol, StreamHub, Worker buffers, and renderer primitives pass cross-language tests and are pushed.
- [ ] Milestone E: SystemView, VOFA, RTT, and SuperWatch migrations each pass their soak gate and are pushed.
- [ ] Milestone F: Full regression, packaged-app hardware smoke, documentation, and final push are complete.

## Delivery order

### Milestone A: Online flash foundation

Execute Tasks 1-4 of `2026-07-10-online-flash.md`.

Exit evidence:

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_errors.py `
  _maintainer/testing/tests/test_pack_catalog.py `
  _maintainer/testing/tests/test_pack_manager.py `
  _maintainer/testing/tests/test_online_flash_probes.py -q
```

Expected: all selected tests pass; no `.pack` file is tracked by Git.

Checkpoint commit sequence:

```text
build: add online flash dependencies
feat: add online flash domain contracts
feat: add on-demand CMSIS-Pack catalog
feat: discover MKLink CMSIS-DAP probes
```

Push checkpoint:

```powershell
git status --short
git log -4 --oneline
git push -u origin HEAD
```

Do not push if `git status --short` contains unrelated or uncommitted files.

### Milestone B: Online flash backend

Execute Tasks 5-8 of `2026-07-10-online-flash.md`.

Exit evidence:

```powershell
python -m pytest _maintainer/testing/tests/test_online_flash_images.py `
  _maintainer/testing/tests/test_online_flash_backend.py `
  _maintainer/testing/tests/test_online_flash_jobs.py `
  _maintainer/testing/tests/test_online_flash_api.py -q
```

Expected: fake-backend connect/erase/program/verify/reset flows pass; failure and cancellation paths release the `target_debug` lease.

Checkpoint commits:

```text
feat: inspect HEX and BIN images
feat: add pyOCD online flash backend
feat: add cancellable online flash jobs
feat: expose online flash API
```

Push only after the selected tests and `python -m pytest -q` pass.

### Milestone C: Online flash GUI and hardware validation

Execute Tasks 9-12 of `2026-07-10-online-flash.md`.

Exit evidence:

```powershell
Set-Location gui
npm test -- src/views/OnlineFlashView.test.ts src/lib/hexPreview.test.ts
npm run build
Set-Location ..
python -m pytest -q
```

Hardware evidence is recorded in:

```text
docs/verification/online-flash-hil.md
```

The record must include probe unique ID with the middle characters redacted, MCU part number, Pack ID/version, firmware SHA-256, HEX/BIN result, verify result, and measured duration.

Checkpoint commits:

```text
feat: add online flash workspace
feat: add virtual firmware preview
test: add online flash integration coverage
docs: record online flash hardware verification
```

Push after one HEX and one BIN closed-loop hardware test pass.

### Milestone D: Streaming protocol and browser primitives

Execute Tasks 1-5 of `2026-07-10-high-throughput-streams.md`.

Exit evidence:

```powershell
python -m pytest _maintainer/testing/tests/test_stream_protocol.py `
  _maintainer/testing/tests/test_stream_hub.py `
  _maintainer/testing/tests/test_stream_api.py -q
Set-Location gui
npm test -- src/lib/stream src/workers/streamDecoder.worker.test.ts
Set-Location ..
```

Checkpoint commits:

```text
feat: define binary stream protocol
feat: add bounded stream hub
feat: expose binary stream websocket
feat: add worker-owned stream buffers
feat: add 30 fps envelope renderer
```

Push after Python and TypeScript golden vectors agree byte-for-byte.

### Milestone E: Stream migrations

Execute Tasks 6-9 of `2026-07-10-high-throughput-streams.md`.

Migration order is fixed:

1. SystemView
2. VOFA
3. RTT
4. SuperWatch

Each migration keeps its existing SSE path behind a temporary feature flag until its binary-path tests and 30-minute soak test pass. Remove each fallback only in the migration's final commit.

Checkpoint commits:

```text
perf: migrate SystemView to binary streaming
perf: migrate VOFA to binary streaming
perf: migrate RTT and SuperWatch streaming
test: add sustained stream performance gates
```

Push after every migration, not only after all four.

### Milestone F: Release qualification

Run the full suite from the inner project root:

```powershell
python -m pytest -q
Set-Location gui
npm test
npm run build
npx tauri build
```

Expected:

- pytest reports zero failures;
- Vitest reports zero failures;
- Vue TypeScript build exits 0;
- Tauri produces release bundles under `gui/src-tauri/target/release/bundle/`.

Then execute:

```powershell
git status --short
git diff --check
git log --oneline --decorate -20
git push origin HEAD
```

The worktree must be clean before the final push.

## Rollback boundaries

- PackCatalog commits do not alter the existing native MKLink flash path.
- Online flash remains a separate route and can be disabled without changing dashboards.
- `target_debug` arbitration is introduced before online hardware operations.
- Each stream migration keeps the existing path until the new path passes soak tests.
- Pack files remain outside the repository and installer, so removing online flash code does not require repository cleanup.

## Change-control rule

If hardware evidence changes an assumption, update the relevant child plan and the design document in a documentation-only commit before changing implementation. Record the reason, observed evidence, and revised acceptance command.
