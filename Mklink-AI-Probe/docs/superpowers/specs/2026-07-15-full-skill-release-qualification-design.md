# MKLink Full-Skill Release Qualification Design

## Purpose

Qualify the current `feature/online-flash-streaming` branch as a Windows release
candidate, with fresh automated, physical MKLink, packaged-GUI, installer, and
performance evidence. Publish the result as GitHub prerelease
`v0.1.0-rc.1` without merging the feature branch into `master`.

The release must make the application easy to install and test while keeping
installers and other large binaries out of Git history.

## Release Identity

- Git tag and GitHub release: `v0.1.0-rc.1`.
- Tauri and Cargo version: `0.1.0-rc.1` when accepted by the Windows bundle
  toolchain.
- Python package version: `0.1.0rc1`, the PEP 440 equivalent.
- If the MSI backend rejects a prerelease version, retain numeric installer
  version `0.1.0`, record `rc.1` in the release manifest, and rename copied
  release assets to include `v0.1.0-rc.1`. This fallback must be documented in
  the report rather than silently changing the release identity.
- Source target: the final reviewed commit on
  `feature/online-flash-streaming`, after qualification fixes and reports.
- GitHub release type: prerelease, not latest stable.

## Scope

### Included

1. All Python, Vue/Vitest, Node release-harness, Vite, Rust, and Tauri build
   checks available in the repository.
2. MKLink discovery, firmware version, IDCODE, target status, RAM/Flash reads,
   safe RAM write/readback, AXF symbol/type/memory-map operations, variable
   reads, debug-control smoke, and resource cleanup.
3. The new online flash workflow through the packaged GUI and backend:
   MKLink-only probe filtering, HEX and BIN inspection, explicit BIN base
   address, program, verify, reset, verify failure, cooperative stop, Pack
   catalog/cache behavior, and probe-resource conflict handling.
4. Packaged GUI HIL for VOFA, SystemView, RTT, and SuperWatch, including binary
   WebSocket/Worker transport, pause/resume behavior, visible rendering cadence,
   loss counters, and cleanup.
5. NSIS installer EXE and MSI generation, clean install, first launch, embedded
   sidecar health, representative hardware operations, application shutdown,
   and uninstall checks.
6. A human-readable Markdown report, sanitized JSON evidence, SHA-256 manifest,
   and GitHub prerelease assets.

### Explicitly Conditional

- Serial transmit/receive requires a loopback plug or external serial peer.
- Modbus RTU requires a real slave or simulator connected to an available port.
- Physical target power removal, SWD wire removal, probe unplug, and physical
  network removal require manual hardware action.
- Hidden-document HIL is PASS only if the browser runtime proves
  `document.hidden === true` during the measured interval.

Unavailable conditional tests are reported as `NOT ESTABLISHED`, never inferred
from unit tests or marked PASS.

## Test Architecture

Qualification is divided into five evidence layers. Each result records the
layer so synthetic results cannot be confused with physical HIL.

### Layer 1: Automated Regression

- `python -m pytest -q`
- GUI `npm test`
- GUI `npm run build`
- Node browser/frontend/packaged release harnesses
- `cargo test` and `cargo check` for the Tauri crate
- project-memory validation and `git diff --check`
- tracked/bundled Pack, firmware, credential, and forbidden-binary scans

### Layer 2: Core MKLink HIL

Use the connected MKLink and the STM32F103RC test target. Test discovery and
identity without recording the full probe ID or COM port. Use the stream test
project AXF for symbols and variables. RAM writes are restricted to a fixture
address proved safe by the current MAP/AXF; every write is read back and the
target is reset or restored afterward.

Debug-control smoke may halt, read core state, single-step, set and clear one
temporary hardware breakpoint, resume, and reset. Cleanup must leave no
breakpoints, no dashboard/resource owner, and a running target.

### Layer 3: Online Flash HIL

Use the packaged application with:

- online-flash project:
  `E:/PHDZ/PROJECT/liu/STM32F103_test/STM32F103_BOOT/MDK-ARM`;
- target: STM32F103RC;
- only the MKLink-exposed CMSIS-DAP interface;
- HEX embedded mappings and BIN explicit base `0x08000000`.

Required scenarios:

1. Enumerate probes and reject non-MKLink identities by policy.
2. Inspect valid HEX and BIN images and verify ranges and hashes.
3. Program, verify, reset, and disconnect for HEX.
4. Program, verify, reset, and disconnect for BIN.
5. Verify an intentionally mismatched image and require `VERIFY_FAIL` with a
   concrete first mismatch address.
6. Stop a long-running job cooperatively and require a terminal `stopped`
   state plus disconnected probe.
7. Hold `target_debug` with VOFA, require online flash `PROBE_BUSY`, stop VOFA,
   then require the same job class to succeed without restarting the backend.
8. Search the complete Pack index, install one uncached DFP on demand when a
   safe catalog candidate is available, restart the app, and verify local cache
   reuse. Existing installed packs are not redownloaded merely to manufacture
   a network test.
9. Restore and verify the designated boot/test firmware at the end.

### Layer 4: Packaged Streaming Qualification

Use the stream project:
`E:/PHDZ/PROJECT/liu/STM32F103_test/STM32F103RC/project.uvprojx`.
Keil may rebuild and flash test-only firmware changes. The installed RC
application, not a Vite development server, is the UI under test.

Run SystemView, VOFA, RTT, and SuperWatch for ten wall-clock minutes each. A
stream passes only when all applicable predicates are true:

- physical target data is observed;
- hashed Worker and binary WebSocket assets are used;
- WebSocket data-frame and Worker-accepted-frame counts agree;
- final sequence values agree;
- frontend sequence, transport, Worker-reported backend, and backend loss
  increments are zero;
- visible rendering is greater than zero and at most 30.5 FPS;
- during a five-second pause, backend and Worker collection advance while
  target canvas frames remain zero;
- after resume, rendering advances without new loss;
- backend stop succeeds, active clients become zero, stream resource owners
  are absent, target test controls are dearmed, and the CDP browser closes;
- process-tree peak working set and achieved sample/event rate are recorded.

The fresh ten-minute results are release-candidate evidence. Existing 30-minute
Task 9 measurements remain historical comparison evidence and are not relabeled
as fresh RC results.

## Installer Qualification

Build the embedded Python sidecar and Tauri bundles with the repository builder.
The release artifacts are copied, not moved, into:

`E:/software/HPM5300/Mklink-AI-Probe/release/v0.1.0-rc.1/`

The release directory is ignored by Git. It contains:

- `Mklink-AI-Probe-v0.1.0-rc.1-x64-Setup.exe` (NSIS installer);
- `Mklink-AI-Probe-v0.1.0-rc.1-x64.msi`;
- `TEST-REPORT.md`;
- `release-manifest.json`;
- `SHA256SUMS.txt`;
- sanitized small JSON qualification artifacts when useful to external testers.

Installer validation uses a clean application install location. It verifies:

1. silent or normal installation exits successfully;
2. installed files include the Tauri executable and sidecar resources;
3. first launch starts one sidecar and `/api/health` becomes ready;
4. the installed GUI reaches Config, Online Flash, and Dashboard views;
5. one online-flash verify and one representative stream run work from the
   installed application;
6. closing the application stops its sidecar and releases port 8765;
7. uninstall succeeds and removes registered application files without
   deleting user Pack caches or project data.

The raw `target/release/mklink-ai-probe.exe` is not advertised as portable when
it depends on an adjacent sidecar. The NSIS setup EXE is the primary
"independent installable EXE" requested for testers.

## Reporting

Create `docs/verification/full-skill-release-v0.1.0-rc.1.md`. Every row contains:

- feature/scenario;
- evidence layer;
- exact sanitized command or UI path;
- expected result;
- actual result and duration;
- `PASS`, `FAIL`, `BLOCKED`, or `NOT ESTABLISHED`;
- artifact link or concise diagnostic;
- cleanup/restoration status.

The report includes separate sections for automated regression, core MKLink,
online flash, streaming performance, installer lifecycle, release assets, and
known limitations. Failures are not erased by later retries; the final report
records the original failure, root cause, corrective commit, and successful
rerun when a code defect is fixed.

Machine-readable evidence uses schema-versioned JSON with aggregate counts and
sanitized identifiers. Do not commit or upload full probe IDs, COM ports,
usernames, credentials, raw logs, screenshots containing local paths, Pack
archives, test firmware, AXF/HEX/BIN images, or unredacted process dumps.

## Failure and Cleanup Policy

- A failure first receives a focused reproducer and regression test before a
  production-code fix.
- Acquisition and flashing failures must execute cleanup in `finally`.
- Online flash cleanup disconnects pyOCD/CMSIS-DAP and releases `target_debug`.
- Streaming cleanup stops the backend, dearms the target fixture, reaches zero
  active clients, releases resource ownership, closes CDP, and resets the
  target when required.
- Installer tests terminate application and sidecar processes they started.
- The final target firmware is explicitly verified; it is not assumed restored.
- No raw release build directory is committed.

## GitHub Publication

After all mandatory gates pass and reviews approve the report:

1. commit source fixes, tests, report, sanitized evidence, release metadata,
   project memory, and version files;
2. push `feature/online-flash-streaming`;
3. create annotated tag `v0.1.0-rc.1` at the reviewed final commit and push it;
4. create a GitHub prerelease targeted at that tag;
5. upload the NSIS setup EXE, MSI, report, JSON manifest, checksums, and selected
   sanitized JSON evidence;
6. query the GitHub API and verify every asset name, byte size, and SHA-256
   against the local manifest.

Prefer GitHub CLI when available. If it is unavailable, use the GitHub REST API
with credentials obtained from the configured Git credential helper or an
environment token. Credentials remain in process memory and are never printed,
written to the repository, report, manifest, or shell transcript.

## Acceptance Criteria

The release candidate is complete only when:

- all mandatory automated tests pass;
- all mandatory online-flash scenarios pass on physical MKLink hardware;
- all four packaged stream runs satisfy the strict ten-minute predicates;
- NSIS EXE and MSI build, install, launch, perform representative hardware
  operations, close cleanly, and uninstall;
- the target is restored and no MKLink/dashboard resources remain owned;
- the final report and manifest contain no prohibited sensitive data;
- spec and quality reviews have no Critical or Important findings;
- local branch, remote branch, tag, GitHub prerelease, and uploaded assets are
  verified consistent.

Conditional hardware tests may remain `NOT ESTABLISHED` when their external
fixture is absent, but the report must state the missing fixture and must not
weaken any online-flash or high-throughput acceptance gate.
