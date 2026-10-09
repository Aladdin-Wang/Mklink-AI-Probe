#!/usr/bin/env python3
"""Native unsigned macOS/Linux bundles. Run via scripts/build_workspace.ps1."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path

import build as builder

SKILL_URL = "https://github.com/MicroKeen/Mklink-AI-Probe/releases/download/v0.3.1/Mklink-AI-Probe-v0.3.1-Skill.zip"
SKILL_SHA256 = "601721e0b8051b1c3c876fe4170fb6c507ba8e9679d5657ddea9a843d98cafe6"


def restore_published_algorithms(work: Path) -> Path:
    """Use only the already published, checksum-pinned algorithm payload."""
    archive = work / "published-skill.zip"
    urllib.request.urlretrieve(SKILL_URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SKILL_SHA256:
        raise RuntimeError("Published Skill SHA-256 mismatch")
    output = work / "builtin_flm"
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if "/mklink/builtin_flm/" not in name or name.endswith("/"):
                continue
            relative = name.split("/mklink/builtin_flm/", 1)[1]
            target = (output / relative).resolve()
            if not target.is_relative_to(output.resolve()):
                raise RuntimeError("Invalid algorithm archive path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(name))
    builder.validate_builtin_flm_bundle(output)
    return output


@contextmanager
def unix_bundle_config(config_path: Path, system: str):
    original = config_path.read_bytes()
    config = json.loads(original)
    bundle = config["bundle"]
    bundle["targets"] = ["dmg"] if system == "Darwin" else ["deb", "appimage"]
    bundle["createUpdaterArtifacts"] = False
    bundle["externalBin"] = ["binaries/mklink-sidecar"]
    bundle["icon"] = [p for p in bundle["icon"] if p.endswith(".png")]
    if system == "Darwin":
        bundle["macOS"] = {"minimumSystemVersion": "11.0", "signingIdentity": "-"}
    else:
        bundle["linux"] = {"deb": {
            "depends": ["libwebkit2gtk-4.1-0", "libusb-1.0-0", "libudev1"],
            "files": {"/lib/udev/rules.d/70-mklink.rules": "../../packaging/linux/70-mklink.rules"},
        }}
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    try:
        yield
    finally:
        config_path.write_bytes(original)


def main():
    system = platform.system()
    if system not in {"Darwin", "Linux"}:
        raise SystemExit("Run this builder natively on macOS or Linux")
    if not os.environ.get("MKLINK_BUILD_WORK_DIR"):
        raise SystemExit("Run via scripts/build_workspace.ps1 -Action run")
    root = Path(__file__).resolve().parents[3]
    version = json.loads((root / "gui" / "src-tauri" / "tauri.conf.json").read_text())["version"]
    builder.SKILL_DIR = root
    builder.GUI_DIR = root / "gui"
    builder.TAURI_DIR = root / "gui" / "src-tauri"
    work = Path(os.environ["MKLINK_BUILD_WORK_DIR"])
    work.mkdir(parents=True, exist_ok=True)
    os.environ["MKLINK_BUILTIN_FLM_ROOT"] = str(restore_published_algorithms(work))
    target = builder.native_target()
    output = Path(os.environ["MKLINK_BUILD_OUTPUT_DIR"]) / target
    output.mkdir(parents=True, exist_ok=True)
    if system == "Linux":
        shutil.copy2(root / "packaging" / "linux" / "70-mklink.rules", output / "70-mklink.rules")
    library_name = "libmklink-stcp.dylib" if system == "Darwin" else "libmklink-stcp.so"
    native = root / "native" / "stcp_bridge"
    (native / "build").mkdir(exist_ok=True)
    builder.run(["go", "build", "-buildmode=c-shared", "-trimpath", "-ldflags=-s -w", "-o", str(native / "build" / library_name), "."], cwd=native)
    builder.require_release_builtin_flm_bundle()
    try:
        if not builder.build_sidecar(force=True):
            raise RuntimeError("Sidecar build failed")
        # Retain a native executable for frozen CLI/MCP qualification.
        shutil.copy2(builder.staged_sidecar_path(), output / "mklink-sidecar")
        config = builder.TAURI_DIR / "tauri.conf.json"
        with unix_bundle_config(config, system):
            env = os.environ.copy()
            for key in list(env):
                if key.startswith(("TAURI_SIGNING_", "APPLE_", "MKLINK_TAURI_UPDATER_KEY")):
                    env.pop(key)
            env["VITE_MKLINK_API"] = "http://127.0.0.1:8765"
            env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
            builder.run(["npx", "tauri", "build"], cwd=builder.GUI_DIR, env=env)
        bundles = builder.cargo_target_dir() / "release" / "bundle"
        extensions = ["*.dmg"] if system == "Darwin" else ["*.deb", "*.AppImage"]
        packages = []
        for pattern in extensions:
            matches = list(bundles.rglob(pattern))
            if len(matches) != 1:
                raise RuntimeError(f"Expected exactly one {pattern} bundle, got {len(matches)}")
            source = matches[0]
            suffix = source.suffix
            destination = output / f"Mklink-AI-Probe-v{version}-{target}{suffix}"
            shutil.copy2(source, destination)
            packages.append({"name": destination.name, "size": destination.stat().st_size,
                             "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
        updater_platforms = {}
        if system == "Darwin":
            apps = list((bundles / "macos").glob("*.app"))
            if len(apps) != 1:
                raise RuntimeError("Expected one macOS application for updater payload")
            destination = output / f"Mklink-AI-Probe-v{version}-{target}.app.tar.gz"
            # Native tar preserves executable modes and framework symlinks.
            builder.run(["tar", "-czf", str(destination), "-C", str(apps[0].parent), apps[0].name])
            packages.append({"name": destination.name, "size": destination.stat().st_size,
                             "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
            arch = "aarch64" if target.startswith("aarch64-") else "x86_64"
            updater_platforms[f"darwin-{arch}"] = destination.name
        else:
            for suffix, installer in [(".AppImage", "appimage"), (".deb", "deb")]:
                updater_platforms[f"linux-x86_64-{installer}"] = next(p["name"] for p in packages if p["name"].endswith(suffix))
        manifest = {"version": version, "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                    "target": target, "os": platform.platform(), "python": sys.version,
                    "updater_signed": False, "apple_notarized": False, "hardware_tested": False,
                    "algorithm_source_sha256": SKILL_SHA256, "files": packages,
                    "updater_platforms": updater_platforms}
        (output / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (output / "SHA256SUMS.txt").write_text("".join(f"{p['sha256']}  {p['name']}\n" for p in packages), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
    finally:
        builder.staged_sidecar_path().unlink(missing_ok=True)


if __name__ == "__main__":
    main()
