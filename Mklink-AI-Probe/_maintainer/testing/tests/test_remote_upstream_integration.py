"""Permanent compatibility coverage for the v0.1.4 + direct-Remote union."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mklink.remote.agent import AgentConfig, AgentDispatchContext, SiteAgent
from mklink.remote.dispatcher import dispatch_capability
from mklink.remote.protocol import PROTOCOL_VERSION, RequestEnvelope, RequestValidationError
from mklink.remote.resource_manager import ResourceError, ResourceGroup, ResourceManager


ROOT = Path(__file__).resolve().parents[3]


def _offline_config() -> dict:
    return {
        "model": "V4",
        "script_name": "offline_download.py",
        "algorithms": [
            {
                "id": "internal",
                "file_name": "Internal.FLM",
                "flash_base": "0x08000000",
                "ram_base": "0x20000000",
                "source_kind": "upload",
                "upload_index": 0,
            }
        ],
        "firmwares": [
            {
                "id": "boot",
                "file_name": "boot.bin",
                "format": "bin",
                "base_address": "0x08000000",
                "algorithm_id": "internal",
            },
            {
                "id": "app",
                "file_name": "app.bin",
                "format": "bin",
                "base_address": "0x08004000",
                "algorithm_id": "internal",
                "upload_index": 7,
            },
        ],
    }


def test_remote_offline_preview_adapts_opaque_uploads_to_v014(monkeypatch):
    from mklink import offline_download

    parsed_payloads = []
    parse = offline_download.parse_offline_config

    def capture(payload):
        parsed_payloads.append(payload)
        return parse(payload)

    monkeypatch.setattr(offline_download, "parse_offline_config", capture)
    monkeypatch.setattr(
        "mklink.remote.dispatcher.capability_available",
        lambda _name: True,
    )

    result = dispatch_capability(
        "offline.preview",
        {"config": _offline_config()},
    )

    assert parsed_payloads[0]["firmwares"][0]["upload_index"] == 0
    assert parsed_payloads[0]["firmwares"][1]["upload_index"] == 7
    assert all(
        "source_path" not in firmware
        for firmware in parsed_payloads[0]["firmwares"]
    )
    assert result["model"] == "V4"
    assert 'load.bin("boot.bin", 0x08000000)' in result["script"]
    assert 'load.bin("app.bin", 0x08004000)' in result["script"]


def test_remote_offline_preview_rejects_field_machine_source_paths(monkeypatch):
    config = _offline_config()
    config["firmwares"][0]["source_path"] = "field-machine-input.bin"
    monkeypatch.setattr(
        "mklink.remote.dispatcher.capability_available",
        lambda _name: True,
    )

    with pytest.raises(RequestValidationError) as rejected:
        dispatch_capability("offline.preview", {"config": config})

    assert rejected.value.data == {"field": "config.firmwares.source_path"}


def test_local_fastapi_and_site_agent_keep_resource_policies_isolated(tmp_path):
    from mklink.remote.api import create_app

    app = create_app(auth_token=None, project_root=str(tmp_path))
    local_manager = app.state.mklink_state["resource_manager"]
    local_manager.acquire(
        ResourceGroup.TARGET_DEBUG,
        "user:dashboard:local",
    )

    def dispatcher(method, _params, context):
        if method == "resource.seed":
            context.resource_manager.acquire(
                ResourceGroup.TARGET_DEBUG,
                "user:dashboard:field",
            )
            return context.resource_manager.get_status()
        if method == "resource.try":
            try:
                context.resource_manager.acquire(
                    ResourceGroup.TARGET_DEBUG,
                    "user:remote:operation",
                )
            except ResourceError as error:
                return {"conflict_owner": error.conflict_owner}
        raise AssertionError(f"unexpected method: {method}")

    agent = SiteAgent(
        AgentConfig(project_root=str(tmp_path)),
        device_factory=lambda **_kwargs: None,
        request_dispatcher=dispatcher,
    )

    assert agent.handshake().protocol_version == PROTOCOL_VERSION
    seeded = asyncio.run(
        agent._dispatch(RequestEnvelope("resource.seed", {}, 1))
    )
    blocked = asyncio.run(
        agent._dispatch(RequestEnvelope("resource.try", {}, 2))
    )
    local_manager.acquire(
        ResourceGroup.TARGET_DEBUG,
        "user:local:operation",
        preempt_user_dashboard=True,
    )

    assert seeded["target_debug"]["owner"] == "user:dashboard:field"
    assert blocked == {"conflict_owner": "user:dashboard:field"}
    assert local_manager.get_active_lease(
        ResourceGroup.TARGET_DEBUG
    ).owner == "user:local:operation"
    assert {
        route.path for route in app.routes if hasattr(route, "path")
    }.issuperset({"/api/health", "/api/device/hardfault"})


def test_current_metadata_preserves_core_remote_and_separate_optional_surfaces():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10 test hosts
        import tomli as tomllib

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    project = metadata["project"]
    scripts = project["scripts"]
    extras = project["optional-dependencies"]

    assert project["version"] == "0.3.0"
    assert {
        "pyelftools==0.32",
        "pycparser>=2.22,<4",
        "websockets>=11.0",
    }.issubset(project["dependencies"])
    assert scripts == {
        "mklink": "mklink.cli:main",
        "mklink-remote": "mklink.remote.cli:main",
        "mklink-remote-agent": "mklink.remote.cli:agent_main",
        "mklink-site-agent": "mklink.remote.package_agent:main",
        "mklink-remote-mcp": "mklink.remote.mcp:main",
    }
    assert {"websockets>=11.0", "intelhex>=2.3", "httpx>=0.27,<1", "fastapi>=0.100", "python-multipart>=0.0.9"}.issubset(extras["remote"])
    assert {"fastmcp>=2.0", "pydantic<2.13", "httpx>=0.27,<1", "fastapi>=0.100"}.issubset(extras["mcp"])
    assert {
        "build==1.5.0",
        "pyinstaller==6.18.0",
        "setuptools==80.9.0",
        "wheel==0.45.1",
    } == set(extras["site-agent-build"])
    assert not any("fastmcp" in item.casefold() for item in project["dependencies"])
    assert not any("pyinstaller" in item.casefold() for item in extras["remote"])


@pytest.mark.parametrize('operation,params', [
    ('flash.program', {'firmware': 'remote-file:opaque', 'confirm': True}),
    ('symbols.memory_map', {}), ('rtt.start', {}), ('rtt.stop', {}),
    ('hardfault.decode', {'fault_regs': {'cfsr': 1}})])
def test_direct_device_is_never_used_as_shared_target_fallback(operation, params, monkeypatch):
    from mklink.remote.capabilities import CapabilityUnavailableError
    from unittest.mock import Mock
    device = Mock()
    context = AgentDispatchContext(device=device, resource_manager=ResourceManager())
    monkeypatch.setattr('mklink.remote.dispatcher.capability_available', lambda _: True)
    with pytest.raises(CapabilityUnavailableError):
        dispatch_capability(operation, params, context=context)
    assert device.mock_calls == []
