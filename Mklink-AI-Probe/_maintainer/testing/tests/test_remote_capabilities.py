"""Capability parity and durable Site Agent dispatcher-seam regressions."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import websockets

from mklink.remote.agent import AgentConfig, SiteAgent
from mklink.remote.capabilities import (
    CAPABILITIES,
    OPERATION_SCHEMAS,
    CapabilityUnavailableError,
    capability_catalog,
)
from mklink.remote.dispatcher import dispatch_capability
from mklink.remote.protocol import (
    AgentOperationError,
    Capability,
    MethodNotFoundError,
    PROTOCOL_VERSION,
    RequestEnvelope,
    RequestValidationError,
)


ROOT = Path(__file__).resolve().parents[3]


def _request(method: str, params=None, request_id: int = 1) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
        separators=(",", ":"),
    )


@asynccontextmanager
async def _running_agent(**kwargs):
    agent = SiteAgent(
        AgentConfig(port=0, token=kwargs.pop("token", None)),
        device_factory=lambda **_kwargs: None,
        **kwargs,
    )
    task = asyncio.create_task(agent.serve())
    try:
        for _ in range(100):
            if agent.ready:
                break
            await asyncio.sleep(0.01)
        assert agent.ready
        yield agent
    finally:
        agent.request_stop()
        await asyncio.wait_for(task, timeout=2)


def test_capability_catalog_has_all_12_groups_and_43_unique_schema_backed_operations():
    operations = [
        operation
        for capability in CAPABILITIES.values()
        for operation in capability.operations
    ]

    assert len(CAPABILITIES) == 12
    assert len(operations) == 43
    assert len(set(operations)) == 43
    assert set(operations) == set(OPERATION_SCHEMAS)
    assert {
        "probe.diagnostics",
        "flash.online",
        "flash.offline",
        "target.debug",
        "target.memory",
        "target.symbols",
        "stream.rtt",
        "stream.systemview",
        "target.hardfault",
        "transfer.upload",
        "serial",
        "modbus",
    } == set(CAPABILITIES)

    for name, capability in CAPABILITIES.items():
        for operation in capability.operations:
            schema = OPERATION_SCHEMAS[operation]
            assert schema.capability == name
            assert len(schema.parameters) == len(set(schema.parameters))
            if schema.high_risk:
                assert "confirm" in schema.parameters

    serialized = capability_catalog()
    assert set(serialized) == set(CAPABILITIES)
    assert sum(len(item["operations"]) for item in serialized.values()) == 43


def test_every_declared_operation_has_dispatch_mapping_or_explicit_group_router():
    source = (ROOT / "mklink" / "remote" / "dispatcher.py").read_text("utf-8")
    string_operations = set(
        re.findall(r"[\"']([a-z_]+(?:\.[a-z_]+)+)[\"']", source)
    )
    grouped = ("transfer.", "serial.", "modbus.")

    for operation in OPERATION_SCHEMAS:
        assert operation in string_operations or operation.startswith(grouped), operation

    with pytest.raises(MethodNotFoundError) as unsupported:
        dispatch_capability("unknown.operation", {})
    assert unsupported.value.as_error() == {
        "code": -32601,
        "message": "Method not found",
        "data": {"method": "unknown.operation", "reason": "unsupported"},
    }


def test_agent_capability_merge_is_deterministic_and_cannot_override_lifecycle():
    agent = SiteAgent(
        AgentConfig(),
        device_factory=lambda **_kwargs: None,
        capability_provider=lambda: {
            "z.custom": Capability(True, detail="z"),
            "agent.lifecycle": Capability(False, detail="must not replace"),
            "a.custom": Capability(True, detail="a"),
        },
    )

    handshake = agent.handshake()
    assert handshake.capabilities["agent.lifecycle"].available is True
    assert handshake.capabilities["agent.lifecycle"].detail != "must not replace"
    assert list(handshake.capabilities)[-2:] == ["a.custom", "z.custom"]


def test_agent_dispatch_seam_supports_sync_async_unsupported_and_redacted_failures():
    request = RequestEnvelope("custom.echo", {"value": 7}, 1)
    seen = []

    def sync_dispatch(method, params, context):
        seen.append(("sync", method, params, context.device))
        return {"value": params["value"]}

    sync_agent = SiteAgent(
        AgentConfig(),
        device_factory=lambda **_kwargs: None,
        request_dispatcher=sync_dispatch,
    )
    assert asyncio.run(sync_agent._dispatch(request)) == {"value": 7}

    async def async_dispatch(method, params, context):
        seen.append(("async", method, params, context.device))
        return {"async": True}

    async_agent = SiteAgent(
        AgentConfig(),
        device_factory=lambda **_kwargs: None,
        request_dispatcher=async_dispatch,
    )
    assert asyncio.run(async_agent._dispatch(request)) == {"async": True}
    assert [item[0] for item in seen] == ["sync", "async"]

    unsupported_agent = SiteAgent(AgentConfig(), device_factory=lambda **_kwargs: None)
    with pytest.raises(MethodNotFoundError) as unsupported:
        asyncio.run(unsupported_agent._dispatch(request))
    assert unsupported.value.data["reason"] == "unsupported"

    def failing_dispatch(*_args):
        raise RuntimeError(r"secret-token at C:\private\fixture.axf")

    failing_agent = SiteAgent(
        AgentConfig(),
        device_factory=lambda **_kwargs: None,
        request_dispatcher=failing_dispatch,
    )
    with pytest.raises(AgentOperationError) as redacted:
        asyncio.run(failing_agent._dispatch(request))
    assert redacted.value.as_error() == {
        "code": -32003,
        "message": "Agent operation failed",
    }


def test_unauthenticated_and_incompatible_sessions_never_reach_injected_dispatcher():
    async def scenario():
        calls = []

        def dispatcher(method, params, context):
            calls.append((method, params, context))
            return {"dispatched": True}

        async with _running_agent(
            token="server-secret",
            request_dispatcher=dispatcher,
            capability_provider=lambda: {"custom": Capability(True)},
        ) as agent:
            url = f"ws://127.0.0.1:{agent.port}"
            async with websockets.connect(url) as socket:
                await socket.send(_request("custom.echo"))
                denied = json.loads(await socket.recv())
                assert denied["error"]["code"] == -32001
            assert calls == []

            async with websockets.connect(url) as socket:
                await socket.send(
                    _request(
                        "system.handshake",
                        {"protocol_version": "99.0", "token": "server-secret"},
                    )
                )
                incompatible = json.loads(await socket.recv())
                assert incompatible["error"]["code"] == -32002
                await socket.send(_request("custom.echo", request_id=2))
                denied = json.loads(await socket.recv())
                assert denied["error"]["code"] == -32001
            assert calls == []

            async with websockets.connect(url) as socket:
                await socket.send(
                    _request(
                        "system.handshake",
                        {
                            "protocol_version": PROTOCOL_VERSION,
                            "token": "server-secret",
                        },
                    )
                )
                negotiated = json.loads(await socket.recv())
                assert negotiated["result"]["capabilities"]["custom"]["available"] is True
                await socket.send(_request("custom.echo", {"value": 1}, request_id=2))
                dispatched = json.loads(await socket.recv())
                assert dispatched["result"] == {"dispatched": True}
            assert len(calls) == 1

    asyncio.run(scenario())
