# Maintainer Release Procedure

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

1. Work from a clean `master` whose intended release commit is pushed to
   GitHub. Do not publish from a feature branch.
2. Set the same version in `pyproject.toml`, `gui/src-tauri/Cargo.toml`, and
   `gui/src-tauri/tauri.conf.json`.
3. Run tests appropriate to the release, then:

```powershell
python skills/tauri-gui-builder/scripts/build.py --check
python skills/tauri-gui-builder/scripts/build.py --bundle
```

Build standard NSIS only unless the user explicitly requests MSI or a
WebView2-offline package. A signed bundle must produce one NSIS `.exe` and its
adjacent `.exe.sig`.

## Prepare Four Public Assets

Create an empty workspace-level `release/<YYYYMMDD-HHMMSS>/` directory outside
the source repository. From the repository root:

```powershell
$Version = "X.Y.Z"
$SourceCommit = git rev-parse HEAD
$ReleaseDir = "..\release\<YYYYMMDD-HHMMSS>"
$NsisFiles = @(Get-ChildItem "gui\src-tauri\target\release\bundle\nsis\*.exe")
if ($NsisFiles.Count -ne 1) { throw "Expected exactly one NSIS executable" }
$Nsis = $NsisFiles[0]

python _maintainer/release/prepare_release.py `
  --version $Version `
  --source-commit $SourceCommit `
  --output $ReleaseDir `
  --nsis $Nsis.FullName `
  --updater-signature "$($Nsis.FullName).sig"
```

The directory must contain exactly:

- `Mklink-AI-Probe-vX.Y.Z-x64-Setup.exe`
- `Mklink-AI-Probe-vX.Y.Z-x64-Setup.exe.sig`
- `SHA256SUMS.txt`
- `release-manifest.json`

Install and qualify the NSIS candidate under a restricted PATH. Confirm health,
bundled-sidecar use, no Python child process, probe discovery without exposing
its full ID, normal shutdown, released port `8765`, and recomputed hashes.

## Publish

Publication is intentionally one maintainer command because ordering matters:

```powershell
python _maintainer/release/publish_update_release.py `
  --version $Version `
  --notes "<release notes>" `
  --release-dir $ReleaseDir `
  --updater-installer "$ReleaseDir\Mklink-AI-Probe-v$Version-x64-Setup.exe" `
  --updater-signature "$ReleaseDir\Mklink-AI-Probe-v$Version-x64-Setup.exe.sig"
```

The publisher verifies clean `master`, version agreement, source commit, exact
asset set, sizes, and hashes. It then:

1. pushes `master` and the annotated version tag to GitHub and Gitee;
2. creates or verifies both Releases and uploads the same four assets;
3. anonymously downloads the Gitee installer and verifies size and SHA-256;
4. publishes the single-file `updates/latest.json` branch to both hosts last.

Publishing `latest.json` last prevents clients from discovering an incomplete
release. Never move a published tag. Documentation or tooling corrections after
publication belong in later `master` commits or a new version.
