"""Optional remote MCP surface contracts without a FastMCP test dependency."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from mklink.remote.mcp import register_tools


ROOT = Path(__file__).resolve().parents[3]


class _MCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorate(function):
            self.tools[function.__name__] = function
            return function

        return decorate


class _Capability:
    def as_dict(self):
        return {"available": True, "version": "1"}


class _Handshake:
    capabilities = {"target.memory": _Capability()}


class _RemoteFile:
    reference = "upload:opaque"

    def as_dict(self):
        return {"reference": self.reference}


class _Client:
    def __init__(self):
        self.calls = []

    def supports(self, _capability):
        return True

    def call(self, operation, **params):
        self.calls.append((operation, params))
        return {"ok": True}

    def handshake(self):
        return _Handshake()

    def upload(self, _path):
        return _RemoteFile()


class _Registry:
    def __init__(self):
        self.sites = []
        self.client_instance = _Client()

    def client(self, site):
        self.sites.append(site)
        return self.client_instance

    def list(self):
        return [{"name": "field-bench"}]


def _tools():
    mcp = _MCP()
    registry = _Registry()
    register_tools(mcp, registry)
    return mcp.tools, registry


def test_importing_remote_mcp_module_does_not_load_fastmcp():
    script = (
        "import sys; import mklink.remote.mcp; "
        "assert 'fastmcp' not in sys.modules; print('isolated')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated"


def test_named_site_routing_and_capability_gate_use_public_client_api():
    tools, registry = _tools()

    assert tools["remote_status"]("field-bench") == {"ok": True}
    assert registry.sites == ["field-bench"]
    assert registry.client_instance.calls == [("agent.status", {})]


def test_generic_high_risk_operation_requires_confirmation_before_client_call():
    tools, registry = _tools()

    with pytest.raises(ValueError, match="confirmation"):
        tools["remote_call"](
            "memory.write",
            {"address": 0x20000000, "data_b64": "AA=="},
            "field-bench",
            False,
        )
    assert registry.client_instance.calls == []

    result = tools["remote_call"](
        "memory.write",
        {"address": 0x20000000, "data_b64": "AA=="},
        "field-bench",
        True,
    )
    assert result == {"ok": True}
    assert registry.client_instance.calls == [
        (
            "memory.write",
            {"address": 0x20000000, "data_b64": "AA==", "confirm": True},
        )
    ]


def test_dedicated_flash_and_memory_write_tools_gate_high_risk_calls():
    tools, registry = _tools()

    with pytest.raises(ValueError, match="confirmation"):
        tools["remote_flash"]("firmware.bin", "field-bench", confirm=False)
    with pytest.raises(ValueError, match="confirmation"):
        tools["remote_write_memory"](0x20000000, "00", "field-bench", False)
    assert registry.client_instance.calls == []

    tools["remote_write_memory"](0x20000000, "00ff", "field-bench", True)
    assert registry.client_instance.calls == [
        (
            "memory.write",
            {"address": 0x20000000, "data_b64": "AP8=", "confirm": True},
        )
    ]
