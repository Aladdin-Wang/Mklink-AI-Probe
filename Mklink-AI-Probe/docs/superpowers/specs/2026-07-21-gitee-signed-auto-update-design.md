# Gitee Signed Auto Update Design

## Goal

Ship Mklink AI Probe `v0.1.0` with automatic update download from Gitee, while publishing the same release assets to GitHub and Gitee without committing installers to Git.

## Client Update Flow

- Use the official Tauri v2 updater and process plugins.
- Check `https://gitee.com/Aladdin-Wang/Mklink-AI-Probe/raw/updates/latest.json` after the desktop shell starts.
- If a newer version exists, download the signed Windows updater artifact automatically.
- Keep the application usable while checking or downloading.
- After download, show a compact update banner with `Install now` and `Later`; installation restarts the app.
- Network or manifest failures remain non-blocking and expose a retry action.

The updater accepts only Tauri-signed artifacts. The public key is compiled into the app. The private key stays outside Git under the current user's configuration directory and may also be supplied through CI secrets.

## Release Layout

Each release publishes these assets to both GitHub Release and Gitee Release:

- standard NSIS setup executable;
- Tauri NSIS updater archive;
- updater signature;
- `SHA256SUMS.txt`;
- release manifest.

The dedicated `updates` branch contains only `latest.json`. Its platform entry points to the Gitee Release updater archive and carries the Tauri signature.

## Publication Order

1. Validate version and clean source state.
2. Build the standard NSIS and signed updater artifact.
3. Create and push the version tag to GitHub and Gitee.
4. Create both Releases and upload all assets.
5. Verify the Gitee download URL and SHA-256.
6. Update and push the `updates` branch to both repositories last.

This order prevents clients from discovering an unavailable update.

## Release Automation

Add a maintainer script that:

- obtains GitHub authentication from `gh`;
- obtains Gitee API authentication from `GITEE_TOKEN`, falling back to the configured Git credential without printing it;
- creates or updates matching Releases;
- uploads assets;
- writes the signed Tauri `latest.json` in a temporary checkout of the `updates` branch;
- pushes `master`, the version tag, and `updates` to both remotes.

The script is idempotent for an existing draft/incomplete release but refuses conflicting tags, versions, hashes, or assets.

## Versioning

The first stable release is `v0.1.0`. Tauri, Cargo, Python package metadata, UI version tests, filenames, tag names, and updater metadata must agree on `0.1.0`.

## Verification

- Unit tests cover update state transitions, automatic download, retry, install/relaunch, release manifest generation, Gitee request construction, and updates-branch JSON.
- Build checks confirm updater artifacts and signatures exist beside the standard NSIS.
- Installed-app qualification confirms the Gitee manifest is reachable, a newer synthetic manifest is detected, invalid signatures are rejected, and normal close still releases the sidecar and port.
- Only standard NSIS is built; no MSI or WebView2 offline package is produced.
