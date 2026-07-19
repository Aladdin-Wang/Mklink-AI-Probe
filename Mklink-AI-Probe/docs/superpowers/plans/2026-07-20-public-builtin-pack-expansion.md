# Public Builtin Pack Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize offline target coverage in the public standard NSIS using only deterministic, license-audited slim CMSIS-Pack resources, with DAPLinkUtility used as a model-coverage reference.

**Architecture:** Add a read-only maintainer audit that classifies local and official Pack archives, then strengthen the existing explicit allowlist so every bundled archive pins source and license evidence. Generate deterministic PDSC+FLM+license archives and a coverage report that compares the resulting catalog with DAPLinkUtility model mappings without redistributing opaque utility binaries.

**Tech Stack:** Python 3 standard library, CMSIS-Pack XML/ZIP, pyOCD `CmsisPack`, JSON manifests, pytest, PyInstaller, Tauri v2, NSIS.

---

### Task 1: Add License-Audit Contracts

**Files:**
- Create: `skills/tauri-gui-builder/scripts/pack_license_audit.py`
- Test: `_maintainer/testing/tests/test_pack_license_audit.py`

- [ ] **Step 1: Write failing archive-classification tests**

Create fixtures for a complete license, a PDSC-declared missing license, and no license evidence. Assert the wished-for API:

```python
result = audit_pack(archive_path)
assert result.classification == "declared-present"
assert result.pack_id == "Vendor.Device_DFP"
assert result.version == "1.0.0"
assert result.license_files == ("LICENSE.txt",)
assert result.referenced_algorithms == ("Flash/Device.FLM",)
```

The missing cases must return `declared-missing` and `no-license-evidence` without treating license-like filenames as authorization.

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
python -m pytest _maintainer/testing/tests/test_pack_license_audit.py -q
```

Expected: import failure because `pack_license_audit.py` does not exist.

- [ ] **Step 3: Implement immutable audit records and structured ZIP/XML parsing**

Implement `PackAudit` and `audit_pack(path)` with safe root-PDSC discovery, local-name XML parsing, safe relative paths, SHA-256, exact Pack identity, license classification, referenced FLM inventory, target count through `CmsisPack`, and projected slim bytes. Do not download or modify archives in this module.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
python -m pytest _maintainer/testing/tests/test_pack_license_audit.py -q
git add -- skills/tauri-gui-builder/scripts/pack_license_audit.py _maintainer/testing/tests/test_pack_license_audit.py
git commit -m "feat: audit builtin Pack license evidence"
```

### Task 2: Enforce Public Redistribution Metadata

**Files:**
- Modify: `skills/tauri-gui-builder/scripts/builtin_packs.py`
- Modify: `skills/tauri-gui-builder/builtin-packs.json`
- Modify: `_maintainer/testing/tests/test_tauri_builder.py`

- [ ] **Step 1: Write failing policy tests**

Require each archive entry to contain the following values; construct the test record from fixture bytes so the hashes are exact:

```python
record = {
    "file": archive_path.name,
    "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
    "source_url": "https://vendor.example/packs/Vendor.Device_DFP.1.0.0.pack",
    "redistribution_authorized": True,
    "redistribution_basis": "Apache-2.0",
    "license_files": [{
        "path": "LICENSE.txt",
        "sha256": hashlib.sha256(b"Apache-2.0").hexdigest(),
    }],
    "provenance": "official vendor CMSIS-Pack",
}
```

Tests must reject HTTP sources, empty redistribution basis, string-only `license_files`, changed license bytes, missing PDSC-declared licenses, unsafe paths, and archive hash mismatches.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest _maintainer/testing/tests/test_tauri_builder.py -q -k "builtin"
```

Expected: new metadata tests fail because the schema and license digest checks do not exist.

- [ ] **Step 3: Implement strict metadata validation**

Validate official HTTPS URL, non-empty redistribution basis, exact source digest, exact license digests, descriptor-declared license presence, and explicit authorization before writing an archive. Include `source_sha256`, `source_url`, `redistribution_basis`, `licenses`, and `provenance` in each generated manifest record.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
python -m pytest _maintainer/testing/tests/test_tauri_builder.py -q -k "builtin"
git add -- skills/tauri-gui-builder/scripts/builtin_packs.py skills/tauri-gui-builder/builtin-packs.json _maintainer/testing/tests/test_tauri_builder.py
git commit -m "build: require audited Pack redistribution metadata"
```

### Task 3: Discover Official Replacements and Expand the Allowlist

**Files:**
- Modify: `skills/tauri-gui-builder/builtin-packs.json`
- Create outside Git: maintainer Pack cache and license audit reports

- [ ] **Step 1: Audit all 109 local RT-Thread Studio Pack archives**

```powershell
python skills/tauri-gui-builder/scripts/pack_license_audit.py `
  --root "D:\RT-ThreadStudio\repo\Extract\Debugger_Support_Packages\RealThread\PyOCD\0.2.9\packs" `
  --json-out "$env:TEMP\mklink-pack-license-audit.json"
```

Expected: 109 records with one `declared-present`, 35 `declared-missing`, and 73 `no-license-evidence` before official replacements are considered.

- [ ] **Step 2: Resolve same-version official HTTPS Pack sources**

Use the cached CMSIS Pack index or official vendor PDSC URLs to download matching complete archives into an external maintainer cache. Reject version or identity mismatches. Re-run the audit on each official archive and retain only entries whose license text explicitly permits redistribution.

- [ ] **Step 3: Add every approved archive as a digest-pinned allowlist entry**

Record exact source URL, source digest, license path and digest, redistribution basis, and provenance. Do not add an entry based solely on DAPLinkUtility presence, local installation, or PDSC license-file presence.

- [ ] **Step 4: Build twice and prove deterministic slim output**

```powershell
$env:MKLINK_BUILTIN_PACK_ROOTS="$env:LOCALAPPDATA\Mklink AI Probe Maintainer\official-packs"
python skills/tauri-gui-builder/scripts/build.py --check
python -m pytest _maintainer/testing/tests/test_tauri_builder.py -q
```

Generate two temporary bundles with `build_builtin_pack_bundle` and assert identical manifests and Pack SHA-256 values.

- [ ] **Step 5: Commit the reviewed allowlist**

```powershell
git add -- skills/tauri-gui-builder/builtin-packs.json
git commit -m "build: expand licensed builtin target Packs"
```

### Task 4: Add DAPLinkUtility Coverage Analysis

**Files:**
- Create: `skills/tauri-gui-builder/scripts/daplink_coverage.py`
- Test: `_maintainer/testing/tests/test_daplink_coverage.py`
- Create outside Git: extracted `chips.json`, FLM hash inventory, and coverage report

- [ ] **Step 1: Write failing mapping and normalization tests**

Use a fixture with manufacturer, series, model, and multiple `algoprog` regions. Assert exact matches, conservative aliases that differ only by case or separators, and unresolved models. Assert that an FLM name/hash match is evidence for identifying an official equivalent but never marks the extracted utility bytes redistributable.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest _maintainer/testing/tests/test_daplink_coverage.py -q
```

Expected: import failure because the coverage module does not exist.

- [ ] **Step 3: Implement coverage-only parsing**

Implement structured `chips.json` parsing, exact model keys, conservative alias keys, per-region address metadata, FLM basename/hash inventory, and comparison against the generated builtin manifest plus pyOCD/HPM records. Output aggregate exact, alias, and unresolved counts without local paths.

- [ ] **Step 4: Extract the unprotected DAPLinkUtility Qt resource catalog outside Git**

Recover `:/resources/algorithms/chips.json` and algorithm hashes from the local unprotected sibling executable using a deterministic maintainer-only extractor. Do not copy extracted FLM bytes into the repository or installer. Feed the extracted catalog to `daplink_coverage.py`.

- [ ] **Step 5: Verify, document coverage, and commit the tool**

```powershell
python -m pytest _maintainer/testing/tests/test_daplink_coverage.py -q
git add -- skills/tauri-gui-builder/scripts/daplink_coverage.py _maintainer/testing/tests/test_daplink_coverage.py
git commit -m "tools: audit DAPLinkUtility target coverage"
```

### Task 5: Full Regression and Standard NSIS Qualification

**Files:**
- Modify: `docs/ai/project-memory.json`
- Regenerate: `docs/ai/CURRENT_HANDOFF.md`
- Create outside Git: standard NSIS, checksum list, builtin catalog CSV, license audit, and DAP coverage report

- [ ] **Step 1: Run full automated verification**

```powershell
python -m pytest -q
cd gui
npm test
npm run build
cd src-tauri
cargo test
cargo check
```

Expected: zero failed tests and successful production builds.

- [ ] **Step 2: Build only the standard NSIS**

```powershell
python skills/tauri-gui-builder/scripts/build.py --bundle
```

Expected: `gui/src-tauri/target/release/bundle/nsis/` exists and no MSI or WebView2-offline bundle exists.

- [ ] **Step 3: Qualify the installed candidate**

Silently overwrite-install the NSIS, start the real Tauri/WebView2 app, verify `/api/health`, offline builtin target search, one internal and one custom external algorithm inspection, absence of Python processes, normal close, and release of port 8765. Do not perform HPM physical programming.

- [ ] **Step 4: Publish external artifacts and update memory**

Copy the standard NSIS to a timestamped directory produced by `Get-Date -Format 'yyyyMMdd-HHmmss'` under the main repository `release` directory, with the implementation commit in its filename. Generate SHA-256 checksums, a complete builtin model CSV, a license audit report, and a DAPLinkUtility coverage report. Keep all binaries, reports containing source paths, Pack files, and extracted resources out of Git.

- [ ] **Step 5: Clean, validate, commit, and push**

```powershell
python skills/tauri-gui-builder/scripts/build.py --clean
python scripts/ai_memory.py render
python scripts/ai_memory.py validate
git diff --check
git add -- docs/ai/project-memory.json docs/ai/CURRENT_HANDOFF.md
git commit -m "docs: hand off expanded builtin Pack coverage"
git push origin feature/online-flash-streaming
```

Expected: local and remote branch counts are `0 0` and the worktree is clean.
