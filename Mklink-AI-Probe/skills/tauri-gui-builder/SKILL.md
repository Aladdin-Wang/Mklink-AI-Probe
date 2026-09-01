---
name: tauri-gui-builder
description: Maintainer-only workflow to build and qualify the Mklink AI Probe Tauri v2 Windows app, bundled Python sidecar, and standard NSIS installer. Invoke explicitly in a source checkout; never use for ordinary end-user GUI startup or hardware debugging.
---

# Mklink AI Probe Tauri Builder

Use this skill for desktop GUI compilation, installer generation, bundled-sidecar checks, overwrite installation, and release-candidate packaging.

## Source Of Truth

- Read `AGENTS.md` and `docs/ai/CURRENT_HANDOFF.md` before building.
- Use the repository script at `skills/tauri-gui-builder/scripts/build.py`.
- Invoke it through `scripts/build_workspace.ps1 -Action run -Executable python
  -ArgumentList @('skills/tauri-gui-builder/scripts/build.py', ...)` so build
  scratch and caches stay under the main checkout's ignored `.build/` on E:.
  Follow `docs/ai/build-storage.md`; never build on C: or upload `.build/`.
- Do not use completed files under `docs/superpowers/` as active instructions.
- The packaged application must work without Python, Node, Rust, Keil, or a source checkout on the target computer.

## Architecture

```text
Tauri/Rust executable
  -> Vue 3 production assets
  -> bundled mklink-sidecar.exe
  -> FastAPI on 127.0.0.1:8765
  -> MKLink CMSIS-DAP hardware
```

Development builds may fall back to a Python backend. Release installers must contain `mklink-sidecar.exe`, and the Rust launcher must prefer that bundled sidecar.

The 0.2.0 release sidecar must also contain the pinned DAPLinkUtility 0.0.21
algorithm catalog. Set `MKLINK_DAPLINKUTILITY_EXE` to the authorized local
`DAPLinkUtility_v0.0.21.exe` before invoking `--bundle`. Its SHA-256 must be
`a452cf5aee6a5dd1e43d0b77ff1d8b57d7c1a0fa64aa8c7d8b98a7c9abc777b9`.
The builder extracts only the catalog and its referenced FLM payloads; it does
not package DAPLinkUtility itself.

## Commands

Run from the project root:

```powershell
./scripts/build_workspace.ps1 -Action run -Executable python -ArgumentList @('skills/tauri-gui-builder/scripts/build.py', '--check')
./scripts/build_workspace.ps1 -Action run -Executable python -ArgumentList @('skills/tauri-gui-builder/scripts/build.py')
./scripts/build_workspace.ps1 -Action run -Executable python -ArgumentList @('skills/tauri-gui-builder/scripts/build.py', '--bundle')
./scripts/build_workspace.ps1 -Action clean
```

Outputs:

- executable: `.build/cache/cargo/release/mklink-ai-probe.exe`
- setup/updater executable: `.build/cache/cargo/release/bundle/nsis/*.exe`
- updater signature: `.build/cache/cargo/release/bundle/nsis/*.exe.sig`

These paths are relative to the main checkout, shared across worktrees.

`--bundle` must force a fresh PyInstaller sidecar and collect:

- `mklink` package data;
- pyOCD plugins and package metadata;
- `cmsis_pack_manager` native/runtime data;
- HID runtime support.

Signed bundles require `MKLINK_TAURI_UPDATER_KEY` or the external key at
`~/.config/mklink-ai-probe/updater.key`. The builder passes the key only to the
Tauri child process and never prints it. Set `MKLINK_TAURI_UPDATER_KEY_PASSWORD`
when the key uses a non-empty password; the generated local key uses an empty
password by default.

## Release Candidates

Copy candidate installers to the main checkout's `.build/artifacts` directory. Include the source commit in every filename and generate a SHA-256 list. Keep installers, sidecars, checksums, logs, and extracted MSI contents out of Git. Preserve existing official `release/` assets.

Generate only the standard NSIS by default. MSI and WebView2-offline variants require explicit user authorization.

## Required Verification

1. Build exits successfully and produces the standard NSIS setup/updater executable and signature.
2. Install NSIS with a PATH containing only Windows system directories.
3. Start the installed app and verify `GET /api/health` returns `status=ok`.
4. Verify `GET /api/online-flash/probes` runs without exposing complete probe identifiers in evidence.
5. Verify the process tree contains no `python.exe` or `pythonw.exe`.
6. Close normally and verify Mklink processes and port `8765` are released.
7. Recompute every published SHA-256 value.
8. Confirm the sidecar build reports the pinned 0.0.21 catalog with 7,059
   targets and 2,224 content-deduplicated FLM blobs. The only tolerated missing
   references are the three recorded optional Option Byte algorithms; no target
   with a missing main programming algorithm may be shipped.

Do not use the removed `/api/dashboard/status` endpoint. Use the current `/api/dash/<name>/status` routes when a dashboard-specific check is needed.

## Cleanup

The workspace launcher cleans only the current `.build/runs/<run>/` temporary
directory, including PyInstaller work/dist/spec data. Preserve shared Cargo and
dependency caches. The bundler removes its staged sidecar and STCP resource.
Do not discard intentional tracked `gui/dist` updates or remove runtime assets.
If cleanup encounters links or denied access, report the exact paths instead
of forcing deletion; the maintainer will handle them manually.

The final worktree must be clean. Windows installers are currently unsigned, so qualification reports must retain the unknown-publisher limitation.
