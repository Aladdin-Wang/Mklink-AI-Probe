# Maintainer Release Procedure

Application 0.2.1 prepares the migration to MicroKeen. Only Aladdin-Wang may
publish. Use reviewed, clean `main` equal to the remote MicroKeen `main` tip.
For an explicitly authorized version release, the maintainer's 2026-09-15
exception permits qualified release-PR integration without another person's
approval. Follow the temporary approval-only change and mandatory restoration
in `docs/ai/repository-governance.md`; ordinary PR review and required CI remain.
The application publisher sends identical signed assets and immutable tags to
MicroKeen, legacy Aladdin-Wang GitHub, and the existing Gitee repository. It
does not push source branches. See `docs/ai/repository-governance.md` before publication.

GitHub is the primary source and collaboration repository. Gitee mirrors the
official release for users who cannot access GitHub, but Gitee synchronization
is performed only by the maintainer or maintainer-controlled CI.

## Authority And Secrets

Contributors and coding agents may change code, run tests, prepare unsigned
candidates, and report release readiness. They must not infer permission to
create official tags, signed updater artifacts, GitHub/Gitee Releases, or the
`updates` branch.

Only the maintainer's computer or controlled CI may access:

- updater key: `~/.config/mklink-ai-probe/updater.key` or
  `MKLINK_TAURI_UPDATER_KEY`;
- optional key password: `MKLINK_TAURI_UPDATER_KEY_PASSWORD`;
- Gitee personal access token: `GITEE_TOKEN` or the maintainer's Git credential;
- authenticated GitHub release access used by `gh`.

Never commit, print, log, transmit, or copy these secrets into project files.

## Preconditions

1. Work from clean reviewed `main` equal to the current MicroKeen remote tip.
   Do not publish from a feature branch. Candidate build/install testing can
   run on the development branch; rebuild from the reviewed final commit before publication.
2. Set the same version in `pyproject.toml`, `gui/src-tauri/Cargo.toml`, and
   `gui/src-tauri/tauri.conf.json`.
3. Run tests appropriate to the release, then:

```powershell
./scripts/build_workspace.ps1 -Action run -Executable python -ArgumentList @('skills/tauri-gui-builder/scripts/build.py', '--check')
./scripts/build_workspace.ps1 -Action run -Executable python -ArgumentList @('skills/tauri-gui-builder/scripts/build.py', '--bundle')
```

Build standard NSIS only unless the user explicitly requests MSI or a
WebView2-offline package. A signed bundle must produce one NSIS `.exe` and its
adjacent `.exe.sig`.

## Prepare Five Payloads And Two Integrity Files

Create an empty directory under the main checkout's ignored `.build/artifacts/`.
Do not use C: or create another ad hoc build tree. Preserve existing official
`release/` assets. From the source root:

```powershell
$Version = "X.Y.Z"
$SourceCommit = git rev-parse HEAD
$BuildRoot = (./scripts/build_workspace.ps1 -Action paths | ConvertFrom-Json).root
$ReleaseDir = Join-Path $BuildRoot "artifacts\<YYYYMMDD-HHMMSS>"
$PortableWork = Join-Path $BuildRoot "artifacts\<YYYYMMDD-HHMMSS>-portable"
$NsisFiles = @(Get-ChildItem (Join-Path $BuildRoot "cache\cargo\release\bundle\nsis\*.exe"))
if ($NsisFiles.Count -ne 1) { throw "Expected exactly one NSIS executable" }
$Nsis = $NsisFiles[0]
./scripts/build_workspace.ps1 -Action run -Executable python -ArgumentList @('packaging/site_agent/build.py', '--output', "$PortableWork\core")
./scripts/build_workspace.ps1 -Action run -WorkingDirectory site-agent-gui\src-tauri -Executable cargo -ArgumentList @('build', '--release')
./scripts/build_workspace.ps1 -Action run -Executable python -ArgumentList @(
  'packaging/site_agent/build_gui.py', '--output', "$PortableWork\gui",
  '--core-zip', "$PortableWork\core\mklink-remote-site-agent-windows-x86_64.zip",
  '--core-manifest', "$PortableWork\core\mklink-remote-site-agent-windows-x86_64.manifest.json",
  '--gui-exe', (Join-Path $BuildRoot 'cache\cargo\release\MKLink-Site-Agent.exe'),
  '--source-root', 'site-agent-gui'
)

python _maintainer/release/prepare_release.py `
  --version $Version `
  --source-commit $SourceCommit `
  --output $ReleaseDir `
  --nsis $Nsis.FullName `
  --updater-signature "$($Nsis.FullName).sig" `
  --site-agent-archive "$PortableWork\gui\MKLink-Site-Agent-v$Version-windows-x86_64-portable.zip" `
  --site-agent-manifest "$PortableWork\gui\MKLink-Site-Agent-v$Version-windows-x86_64-portable.manifest.json"
```

The directory must contain exactly:

- `Mklink-AI-Probe-vX.Y.Z-x64-Setup.exe`
- `Mklink-AI-Probe-vX.Y.Z-x64-Setup.exe.sig`
- `Mklink-AI-Probe-vX.Y.Z-Skill.zip`
- `MKLink-Site-Agent-vX.Y.Z-windows-x86_64-portable.zip`
- `MKLink-Site-Agent-vX.Y.Z-windows-x86_64-portable.manifest.json`
- `SHA256SUMS.txt`
- `release-manifest.json`

`prepare_release.py` builds the public Skill archive directly from the release
commit using an explicit runtime-content allowlist. It excludes repository
maintenance instructions, project memory, tests, desktop source, and maintainer
build skills. The published update document includes the installer and Skill
package size, SHA-256, and source commit so AI clients can verify automatic
updates before installation.

Install and qualify the NSIS candidate under a restricted PATH. Confirm health,
bundled-sidecar use, no Python child process, probe discovery without exposing
its full ID, normal shutdown, released port `8765`, and recomputed hashes.

## Publish

Publication is intentionally one maintainer command because ordering matters:

```powershell
python _maintainer/release/publish_update_release.py `
  --version $Version `
  --notes-file "<release-notes.md>" `
  --release-dir $ReleaseDir `
  --updater-installer "$ReleaseDir\Mklink-AI-Probe-v$Version-x64-Setup.exe" `
  --updater-signature "$ReleaseDir\Mklink-AI-Probe-v$Version-x64-Setup.exe.sig"
```

The publisher verifies clean reviewed `main`, version agreement, source commit, exact
asset set, sizes, and hashes. It then:

1. pushes only the immutable annotated version tag to both GitHub repositories and Gitee;
2. creates or verifies all three Releases and uploads the same seven public files;
3. anonymously downloads GitHub assets and the Gitee installer/Skill, verifying size and SHA-256;
4. publishes indexes last: MicroKeen `release/latest.json`, legacy GitHub
   `updates/latest.json`, and unchanged Gitee `updates/latest.json`. GitHub
   manifests point to MicroKeen release assets; Gitee uses its own mirror URLs.

0.2.0 clients retain their old endpoints and discover the compatibility index.
The installed 0.2.1 application and Skill contain MicroKeen as their primary
endpoint and Gitee as fallback. Keep the same updater key and application ID.
Never remove the old index during migration or change the Gitee URL.

Publishing `latest.json` last prevents clients from discovering an incomplete
release. Never move a published tag. Documentation or tooling corrections after
publication belong in later `main` commits or a new version.

## Publish Probe Firmware Independently

Probe UF2 updates are independent from application and Skill releases. Put the
newly compiled file in `MK-Firmware/` using the exact
`MicroLink_V<major>.<minor>.<patch>.uf2` or
`HPMLink_V4.<minor>.<patch>.uf2` name, then run:

```powershell
python _maintainer/firmware/publish_firmware.py
```

The command validates UF2 framing, selects the newest file for each exact
family/model, rejects version rollback and same-version content changes, and
verifies the public GitHub/Gitee assets by size and SHA-256. It adds immutable
files to the `firmware-assets` Release on both providers and force-publishes
`firmware/latest.json` last. Re-running it with unchanged files is safe.

Use `--dry-run` for local validation. Do not add UF2 files to the NSIS bundle or
the public Skill archive; installed clients resolve the independent manifest
with GitHub-to-Gitee fallback.
