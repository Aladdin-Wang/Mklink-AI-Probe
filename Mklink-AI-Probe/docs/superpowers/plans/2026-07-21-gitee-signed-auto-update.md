# Gitee Signed Auto Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release Mklink AI Probe `v0.1.0` with signed automatic update downloads from Gitee and repeatable GitHub/Gitee publishing.

**Architecture:** The desktop app uses Tauri's updater plugin against a static `latest.json` on a dedicated `updates` branch. A maintainer publisher uploads the standard NSIS and signed updater artifacts to both hosting providers, verifies Gitee availability, then updates the manifest branch last.

**Tech Stack:** Tauri v2, Vue 3, TypeScript, Rust, Python 3, GitHub CLI, Gitee API v5.

---

### Task 1: Stable Version And Tauri Updater Foundation

**Files:**
- Modify: `pyproject.toml`
- Modify: `gui/src-tauri/Cargo.toml`
- Modify: `gui/src-tauri/Cargo.lock`
- Modify: `gui/src-tauri/tauri.conf.json`
- Modify: `gui/src-tauri/src/lib.rs`
- Modify: `gui/src-tauri/capabilities/default.json`
- Modify: `gui/package.json`
- Modify: `gui/package-lock.json`
- Test: `gui/src/App.test.ts`
- Test: `_maintainer/testing/tests/test_tauri_builder.py`

- [ ] Add failing assertions that all product metadata reports `0.1.0`, updater artifacts are enabled, the endpoint is the Gitee `updates` branch, and the updater/process plugins are registered.
- [ ] Run `python -m pytest _maintainer/testing/tests/test_tauri_builder.py -q` and `npm test -- App.test.ts`; confirm the new assertions fail.
- [ ] Add `tauri-plugin-updater`, `tauri-plugin-process`, `@tauri-apps/plugin-updater`, and `@tauri-apps/plugin-process`; register both Rust plugins and permissions.
- [ ] Set `bundle.createUpdaterArtifacts` to `true` and configure the endpoint plus generated public key in `tauri.conf.json`.
- [ ] Generate the private key non-interactively at `%USERPROFILE%\.config\mklink-ai-probe\updater.key`; keep it outside Git and restrict access to the current Windows user.
- [ ] Run the focused Python, Vue, and Rust tests; commit as `feat: enable signed desktop updates`.

### Task 2: Automatic Download And Install UI

**Files:**
- Create: `gui/src/composables/useAppUpdater.ts`
- Create: `gui/src/composables/useAppUpdater.test.ts`
- Create: `gui/src/components/AppUpdateBanner.vue`
- Create: `gui/src/components/AppUpdateBanner.test.ts`
- Modify: `gui/src/App.vue`
- Modify: `gui/src/App.test.ts`

- [ ] Write failing tests for: non-Tauri no-op; startup check; automatic download progress; ready-to-install state; retry after network failure; install followed by relaunch.
- [ ] Implement one shared state machine with states `idle`, `checking`, `downloading`, `ready`, `installing`, and `error`.
- [ ] Use `check()` to discover an update, `update.download()` for automatic background download, `update.install()` on explicit user action, and `relaunch()` after installation.
- [ ] Render a compact unframed banner only for download, ready, installing, or error states; keep normal application workflows available.
- [ ] Run `npm test -- useAppUpdater.test.ts AppUpdateBanner.test.ts App.test.ts`; commit as `feat: download signed updates from Gitee`.

### Task 3: Signed Release Metadata And Dual Publisher

**Files:**
- Create: `_maintainer/release/publish_update_release.py`
- Create: `_maintainer/testing/tests/test_publish_update_release.py`
- Modify: `_maintainer/release/prepare_release.py`
- Modify: `_maintainer/testing/tests/test_release_manifest.py`

- [ ] Write failing tests for stable asset names, SHA-256 manifest data, Tauri `latest.json`, Gitee release requests, credential redaction, idempotent existing releases, and updates-branch publication order.
- [ ] Implement a pure helper with this interface and output shape:

```python
def build_latest_document(
    *, version: str, notes: str, published_at: str, signature: str, url: str
) -> dict[str, object]:
    return {
        "version": version,
        "notes": notes,
        "pub_date": published_at,
        "platforms": {
            "windows-x86_64": {"signature": signature, "url": url}
        },
    }
```

- [ ] Implement GitHub publication through `gh release create/upload` and Gitee publication through API v5. Resolve the Gitee token from `GITEE_TOKEN`, otherwise use `git credential fill` without logging the secret.
- [ ] Publish `latest.json` from a temporary `updates` checkout only after both releases and Gitee asset verification succeed.
- [ ] Run `python -m pytest _maintainer/testing/tests/test_publish_update_release.py _maintainer/testing/tests/test_release_manifest.py -q`; commit as `feat: publish updates to GitHub and Gitee`.

### Task 4: Signed NSIS Build Integration

**Files:**
- Modify: `skills/tauri-gui-builder/scripts/build.py`
- Modify: `_maintainer/testing/tests/test_tauri_builder.py`
- Modify: `skills/tauri-gui-builder/SKILL.md`

- [ ] Write failing tests that `--bundle` requires the external private key, still selects only NSIS, and reports the setup/updater executable and signature.
- [ ] Load the key from `MKLINK_TAURI_UPDATER_KEY` or `%USERPROFILE%\.config\mklink-ai-probe\updater.key`; never print key contents.
- [ ] Set `TAURI_SIGNING_PRIVATE_KEY` only in the child build environment and keep MSI/WebView2-offline disabled.
- [ ] Verify all three updater outputs exist before reporting build success.
- [ ] Run the builder tests and `python skills/tauri-gui-builder/scripts/build.py --check`; commit as `build: produce signed NSIS updates`.

### Task 5: Build, Publish, And Qualify v0.1.0

**Files:**
- Modify: `docs/ai/project-memory.json`
- Generate: `docs/ai/CURRENT_HANDOFF.md`
- External only: `release/YYYYMMDD-HHMMSS/`
- External branches/tags: `v0.1.0`, `updates`

- [ ] Run full Python, GUI, Vite, Rust, and cargo checks.
- [ ] Build only the signed standard NSIS and updater artifacts.
- [ ] Install under restricted PATH; verify health, sidecar lifecycle, no Python/GNU child, and port cleanup.
- [ ] Publish `v0.1.0` and all update assets to GitHub and Gitee, then publish `updates/latest.json`.
- [ ] Fetch the Gitee manifest and updater installer anonymously; verify version, signature field, filename, size, and SHA-256.
- [ ] Update AI memory, render and validate handoff, run `git diff --check`, commit, push the feature branch, merge to `master`, and synchronize GitHub/Gitee.
