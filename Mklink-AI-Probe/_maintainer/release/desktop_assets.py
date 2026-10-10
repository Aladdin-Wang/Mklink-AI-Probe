"""Strict native desktop asset names and updater platform keys."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


TARGETS = {
    "aarch64-apple-darwin": {"darwin-aarch64": ".app.tar.gz"},
    "x86_64-apple-darwin": {"darwin-x86_64": ".app.tar.gz"},
    "x86_64-unknown-linux-gnu": {
        "linux-x86_64-appimage": ".AppImage", "linux-x86_64-deb": ".deb",
    },
}


def desktop_layout(version: str) -> tuple[dict[str, str], set[str]]:
    updates = {}
    assets = set()
    for target, platforms in TARGETS.items():
        prefix = f"Mklink-AI-Probe-v{version}-{target}"
        if "apple" in target:
            assets.add(prefix + ".dmg")
        for platform, suffix in platforms.items():
            name = prefix + suffix
            updates[platform] = name
            assets.update((name, name + ".sig"))
    return updates, assets


def collect_desktop_assets(paths, version: str, commit: str):
    """Accept all three native builds, their exact payloads and signed updates."""
    expected_updates, expected_assets = desktop_layout(version)
    sources = []
    seen = set()
    for value in paths:
        path = Path(value).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        target = data.get("target")
        if target not in TARGETS or target in seen:
            raise ValueError("Unknown or duplicate desktop target")
        seen.add(target)
        if data.get("version") != version or data.get("source_commit") != commit:
            raise ValueError("Desktop build version/source does not match release")
        target_updates = {key: expected_updates[key] for key in TARGETS[target]}
        if data.get("updater_platforms") != target_updates:
            raise ValueError("Desktop updater platform map does not match target")
        names = {name for name in expected_assets if f"-{target}." in name and not name.endswith(".sig")}
        files = data.get("files", [])
        if len(files) != len(names) or {item.get("name") for item in files} != names:
            raise ValueError("Desktop manifest has an unexpected asset set")
        for item in files:
            source = path.parent / item["name"]
            if source.stat().st_size != item.get("size") or hashlib.sha256(source.read_bytes()).hexdigest() != item.get("sha256"):
                raise ValueError("Desktop asset hash or size mismatch")
            sources.append((source, source.name))
        for name in target_updates.values():
            signature = path.parent / (name + ".sig")
            if not signature.is_file() or not signature.read_text(encoding="ascii").strip():
                raise ValueError("Desktop update requires a nonempty signature")
            sources.append((signature, signature.name))
    if seen != set(TARGETS):
        raise ValueError("All three native desktop builds are required")
    return sources, expected_updates
