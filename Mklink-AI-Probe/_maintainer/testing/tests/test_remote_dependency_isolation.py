"""Clean-environment dependency and lazy FastMCP loading contracts."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = ROOT / "pyproject.toml"


def _venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _create_and_install(directory: Path, extra: str) -> Path:
    venv.EnvBuilder(with_pip=True, clear=True).create(directory)
    python = _venv_python(directory)
    result = subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "-e",
            f"{ROOT}[{extra}]",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return python


def _run(python: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_pyproject_declares_separate_ordinary_remote_and_mcp_extras():
    metadata = tomllib.loads(PYPROJECT.read_text("utf-8"))["project"]
    extras = metadata["optional-dependencies"]

    assert "remote" in extras
    assert any(item.lower().startswith("websockets") for item in extras["remote"])
    assert "mcp" in extras
    assert any(item.lower().startswith("fastmcp") for item in extras["mcp"])
    assert all("fastmcp" not in item.lower() for item in extras["remote"])


def test_clean_remote_extra_runs_client_and_agent_without_optional_stacks(tmp_path):
    extras = tomllib.loads(PYPROJECT.read_text("utf-8"))["project"][
        "optional-dependencies"
    ]
    assert "remote" in extras
    python = _create_and_install(tmp_path / "ordinary-remote", "remote")
    script = r'''
import asyncio
import builtins
import sys
import threading
import time

blocked = {
    "fastmcp", "PyQt5", "PyQt6", "PySide2", "PySide6", "PyInstaller",
    "SiteTunnel", "sitetunnel", "frp", "frpc", "frps", "stcp",
}
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split(".", 1)[0] in blocked:
        raise AssertionError("blocked optional dependency imported: " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded

from mklink.remote.agent import AgentConfig, SiteAgent
from mklink.remote.client import connect_remote
from mklink.remote.cli import build_agent_parser, build_parser
import mklink.remote.mcp

agent = SiteAgent(AgentConfig(port=0), device_factory=lambda: None)
errors = []
def serve():
    try:
        asyncio.run(agent.serve())
    except BaseException as exc:
        errors.append(exc)
thread = threading.Thread(target=serve)
thread.start()
deadline = time.monotonic() + 5
while not agent.ready and time.monotonic() < deadline:
    time.sleep(0.01)
assert agent.ready
with connect_remote(f"ws://127.0.0.1:{agent.port}", token=None) as client:
    assert client.call("agent.health")["listener"] is True
agent.request_stop()
thread.join(5)
assert not thread.is_alive()
assert not errors, errors
assert build_parser().prog == "mklink-remote"
assert build_agent_parser().prog == "mklink-remote-agent"
assert blocked.isdisjoint(sys.modules)
print("ordinary-remote-isolated")
'''
    result = _run(python, script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "ordinary-remote-isolated"


def test_clean_mcp_extra_loads_fastmcp_only_at_mcp_server_boundary(tmp_path):
    python = _create_and_install(tmp_path / "remote-mcp", "mcp")
    script = r'''
import sys
from mklink.remote.agent import AgentConfig
from mklink.remote.client import RemoteClient
from mklink.remote.cli import build_agent_parser, build_parser
import mklink.remote.mcp as remote_mcp

assert "fastmcp" not in sys.modules
AgentConfig()
build_parser()
build_agent_parser()
assert "fastmcp" not in sys.modules
server = remote_mcp.build_server(registry=object())
assert server is not None
assert "fastmcp" in sys.modules
print("mcp-boundary-isolated")
'''
    result = _run(python, script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "mcp-boundary-isolated"
