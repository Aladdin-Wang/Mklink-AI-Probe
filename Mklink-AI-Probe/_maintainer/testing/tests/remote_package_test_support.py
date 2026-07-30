"""Shared fresh-build support for standalone Site Agent package tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_NAME = "mklink-remote-site-agent-windows-x86_64.zip"
MANIFEST_NAME = "mklink-remote-site-agent-windows-x86_64.manifest.json"
PACKAGE_EVIDENCE_STATE = "pending"
PACKAGE_EVIDENCE_POINTER = "REQ-PACKAGE-10:evidence/packages.json"
PACKAGE_EVIDENCE_PRODUCER = "N5"
BUILD_SECRET_SENTINEL = "package-build-secret-4t1"
BUILD_ENDPOINT_SENTINEL = "wss://package-build-endpoint.invalid:443"
BUILD_HARDWARE_SENTINEL = "MKLINK-HARDWARE-ID-4T1"

_PACKAGE_EVIDENCE = None
_WHEEL_EVIDENCE = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ignore_source(_directory, names):
    ignored = {
        name
        for name in names
        if (
            name in {
                ".git",
                ".pytest_cache",
                "__pycache__",
                "build",
                "dist",
                "plans",
                "release",
                "skills",
            }
            or name.endswith((".egg-info", ".pyc", ".pyo"))
        )
    }
    return ignored


def copy_clean_product_source(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(ROOT / "pyproject.toml", destination / "pyproject.toml")
    shutil.copytree(
        ROOT / "mklink",
        destination / "mklink",
        ignore=_ignore_source,
    )
    packaging = destination / "packaging"
    packaging.mkdir()
    shutil.copytree(
        ROOT / "packaging" / "site_agent",
        packaging / "site_agent",
        ignore=_ignore_source,
    )
    native = destination / "native"
    native.mkdir()
    shutil.copytree(
        ROOT / "native" / "stcp_bridge",
        native / "stcp_bridge",
        ignore=_ignore_source,
    )
    forbidden_parts = {
        ".git",
        ".pytest_cache",
        "__pycache__",
        "plans",
        "release",
        "skills",
    }
    for path in destination.rglob("*"):
        assert not forbidden_parts.intersection(path.relative_to(destination).parts)
        assert not path.name.endswith((".egg-info", ".pyc", ".pyo"))
    return destination


def _hidden_creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    else:  # pragma: no cover - Windows package gate
        process.kill()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def get_clean_package(tmp_path_factory):
    global _PACKAGE_EVIDENCE
    if _PACKAGE_EVIDENCE is not None:
        return _PACKAGE_EVIDENCE

    base = tmp_path_factory.mktemp("remote-package-clean-build")
    source = copy_clean_product_source(base / "source")
    output = base / "output"
    home = base / "isolated-home"
    home.mkdir()
    log = base / "build.log"

    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH"):
        environment.pop(name, None)
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "MKLINK_REMOTE_TOKEN": BUILD_SECRET_SENTINEL,
            "MKLINK_TEST_ENDPOINT": BUILD_ENDPOINT_SENTINEL,
            "MKLINK_TEST_HARDWARE_ID": BUILD_HARDWARE_SENTINEL,
            "MKLINK_STCP_LIBRARY": str(
                ROOT / "native" / "stcp_bridge" / "build" / "mklink-stcp.dll"
            ),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
    )
    command = [
        sys.executable,
        str(source / "packaging" / "site_agent" / "build.py"),
        "--output",
        str(output),
    ]
    started = time.monotonic()
    with log.open("w", encoding="utf-8", errors="replace") as stream:
        process = subprocess.Popen(
            command,
            cwd=source,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=_hidden_creation_flags(),
        )
        deadline = started + 1_200
        next_heartbeat = started
        while process.poll() is None:
            now = time.monotonic()
            if now >= deadline:
                _terminate_process_tree(process)
                raise AssertionError(
                    "fresh Site Agent package build exceeded 1200 seconds; "
                    f"log retained at {log}"
                )
            if now >= next_heartbeat:
                print(
                    json.dumps(
                        {
                            "event": "package-build-heartbeat",
                            "pid": process.pid,
                            "elapsed_seconds": round(now - started, 1),
                            "log_size": log.stat().st_size,
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                next_heartbeat = now + 30
            time.sleep(1)
        returncode = process.wait(timeout=10)

    if returncode != 0:
        tail = log.read_text("utf-8", errors="replace")[-12_000:]
        raise AssertionError(
            f"fresh Site Agent package build failed with {returncode}\n{tail}"
        )

    artifact = output / ARTIFACT_NAME
    manifest = output / MANIFEST_NAME
    assert artifact.is_file()
    assert manifest.is_file()
    assert not (output / ".site-agent-build").exists()
    _PACKAGE_EVIDENCE = {
        "base": base,
        "source": source,
        "output": output,
        "home": home,
        "build_log": log,
        "artifact": artifact,
        "manifest": manifest,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "source_worktree": ROOT.parent,
        "source_product": ROOT,
    }
    return _PACKAGE_EVIDENCE


def _run_checked(command, *, cwd: Path, env: dict[str, str], timeout: int):
    result = subprocess.run(
        [str(item) for item in command],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_hidden_creation_flags(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def get_clean_wheel(tmp_path_factory):
    global _WHEEL_EVIDENCE
    if _WHEEL_EVIDENCE is not None:
        return _WHEEL_EVIDENCE

    base = tmp_path_factory.mktemp("remote-wheel-clean")
    source = copy_clean_product_source(base / "source")
    home = base / "isolated-home"
    home.mkdir()
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH"):
        environment.pop(name, None)
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "SOURCE_DATE_EPOCH": "315532800",
        }
    )

    environment_root = base / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment_root)
    python = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheelhouse = base / "wheelhouse"
    wheelhouse.mkdir()
    _run_checked(
        [
            python,
            "-m",
            "pip",
            "wheel",
            "--progress-bar",
            "off",
            "--no-deps",
            "--wheel-dir",
            wheelhouse,
            source,
        ],
        cwd=base,
        env=environment,
        timeout=600,
    )
    wheels = sorted(wheelhouse.glob("mklink-*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]
    _run_checked(
        [
            python,
            "-m",
            "pip",
            "install",
            "--progress-bar",
            "off",
            f"{wheel}[remote]",
        ],
        cwd=base,
        env=environment,
        timeout=600,
    )

    guard_script = r'''
import asyncio
import builtins
import importlib.metadata
import json
import sys
import threading
import time

blocked = {
    "fastapi", "fastmcp", "pyqt5", "pyqt6", "pyside2", "pyside6",
    "pyinstaller", "sitetunnel", "frp", "frpc", "frps", "stcp",
}
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split(".", 1)[0].casefold() in blocked:
        raise AssertionError("blocked optional dependency imported: " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded

from mklink.remote.agent import AgentConfig, SiteAgent
from mklink.remote.client import connect_remote
from mklink.remote.cli import build_agent_parser, build_parser
from mklink.remote.package_agent import build_parser as build_package_parser
import mklink.remote.mcp

agent = SiteAgent(AgentConfig(port=0), device_factory=lambda: None)
errors = []
def serve():
    try:
        asyncio.run(agent.serve())
    except BaseException as exc:
        errors.append(repr(exc))
thread = threading.Thread(target=serve)
thread.start()
deadline = time.monotonic() + 5
while not agent.ready and time.monotonic() < deadline:
    time.sleep(0.01)
assert agent.ready
with connect_remote(f"ws://127.0.0.1:{agent.port}", token=None) as client:
    assert client.call("agent.health")["listener"] is True
    assert client.call("agent.status")["probe_connected"] is False
agent.request_stop()
thread.join(5)
assert not thread.is_alive()
assert not errors, errors
assert build_parser().prog == "mklink-remote"
assert build_agent_parser().prog == "mklink-remote-agent"
assert build_package_parser().prog == "mklink-remote-agent"

installed = sorted({
    (distribution.metadata.get("Name") or "").casefold()
    for distribution in importlib.metadata.distributions()
})
roots = {name.split(".", 1)[0].casefold() for name in sys.modules}
assert blocked.isdisjoint(roots)
assert blocked.isdisjoint(installed)
requirements = importlib.metadata.distribution("mklink").requires or []
websockets = [item for item in requirements if item.casefold().startswith("websockets")]
normalized_websockets = [" ".join(item.split()) for item in websockets]
expected_websockets = {
    "websockets>=11.0",
    "websockets>=11.0; extra == \"remote\"",
    "websockets>=11.0; extra == \"gui\"",
}
assert len(normalized_websockets) == len(expected_websockets), websockets
assert set(normalized_websockets) == expected_websockets, websockets
print(json.dumps({
    "installed": installed,
    "websockets_requirements": normalized_websockets,
    "fastmcp_loaded": "fastmcp" in sys.modules,
    "probe_connected": False,
}, sort_keys=True))
'''
    result = _run_checked(
        [python, "-c", guard_script],
        cwd=base,
        env=environment,
        timeout=60,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])
    _WHEEL_EVIDENCE = {
        "base": base,
        "source": source,
        "home": home,
        "venv": environment_root,
        "python": python,
        "wheel": wheel,
        "report": report,
    }
    return _WHEEL_EVIDENCE
