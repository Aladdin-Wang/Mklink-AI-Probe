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

from mklink.remote.agent import AgentConfig, AgentDispatchContext, SiteAgent
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
from mklink.remote.resource_manager import ResourceGroup, ResourceManager


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
        device_factory=lambda: None,
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


def test_serial_and_modbus_dispatch_use_public_domain_apis(monkeypatch):
    serial_events = []

    class SerialPort:
        def __init__(self, port, *, baudrate, timeout):
            serial_events.append(("init", port, baudrate, timeout))

        def open(self):
            serial_events.append(("open",))
            return True

        def write(self, data):
            serial_events.append(("write", data))

        def read_available(self):
            return b"\x10\x20"

        def close(self):
            serial_events.append(("close",))

    serial_module = types.ModuleType("mklink.serial")
    serial_module.SerialPort = SerialPort
    serial_module.list_uart_ports = lambda: [{"device": "test-port"}]
    monkeypatch.setitem(sys.modules, "mklink.serial", serial_module)
    monkeypatch.setattr(
        "mklink.remote.dispatcher.capability_available", lambda _name: True
    )

    assert dispatch_capability("serial.list", {}) == [{"device": "test-port"}]
    assert dispatch_capability(
        "serial.exchange",
        {
            "port": "test-port",
            "baudrate": 115200,
            "timeout": 0,
            "data_b64": "AQI=",
            "confirm": True,
        },
    ) == {"__bytes__": "ECA="}
    assert ("write", b"\x01\x02") in serial_events
    assert serial_events[-1] == ("close",)

    modbus_events = []

    class ModbusClient:
        def __init__(self, port, *, baudrate, timeout):
            modbus_events.append(("init", port, baudrate, timeout))

        def open(self):
            return True

        def read_holding_registers(self, address, count, slave):
            modbus_events.append(("read", address, count, slave))
            return [0x1234]

        read_input_registers = read_holding_registers
        read_coils = read_holding_registers
        read_discrete_inputs = read_holding_registers

        def write_register(self, address, value, slave):
            modbus_events.append(("write", address, value, slave))

        def write_registers(self, address, value, slave):
            modbus_events.append(("write-registers", address, value, slave))

        def write_coil(self, address, value, slave):
            modbus_events.append(("write-coil", address, value, slave))

        def write_coils(self, address, value, slave):
            modbus_events.append(("write-coils", address, value, slave))

        def close(self):
            modbus_events.append(("close",))

    modbus_module = types.ModuleType("mklink.modbus")
    modbus_module.ModbusClient = ModbusClient
    modbus_module.scan_slaves = lambda *_args, **_kwargs: [1]
    monkeypatch.setitem(sys.modules, "mklink.modbus", modbus_module)

    assert dispatch_capability(
        "modbus.read",
        {
            "port": "test-port",
            "kind": "holding",
            "address": 3,
            "count": 1,
            "slave": 2,
        },
    ) == [0x1234]
    assert dispatch_capability(
        "modbus.write",
        {
            "port": "test-port",
            "kind": "register",
            "address": 3,
            "value": 0x55,
            "slave": 2,
            "confirm": True,
        },
    ) == {"written": True}
    assert ("read", 3, 1, 2) in modbus_events
    assert ("write", 3, 0x55, 2) in modbus_events


class _TrackingResourceManager(ResourceManager):
    def __init__(self):
        super().__init__()
        self.acquire_calls = []
        self.release_calls = []

    def acquire(self, resource, owner, *args, **kwargs):
        self.acquire_calls.append((resource, owner))
        return super().acquire(resource, owner, *args, **kwargs)

    def release(self, owner):
        self.release_calls.append(owner)
        return super().release(owner)


@pytest.fixture
def fc03_modbus_provider(monkeypatch):
    events = []
    behavior = {
        "open_result": True,
        "read_result": [0],
        "read_error": None,
    }

    class ModbusClient:
        def __init__(
            self,
            port,
            *,
            baudrate,
            timeout,
            bytesize=8,
            parity="N",
            stopbits=1,
        ):
            events.append(
                (
                    "init",
                    port,
                    baudrate,
                    timeout,
                    bytesize,
                    parity,
                    stopbits,
                )
            )

        def open(self):
            events.append(("open",))
            return behavior["open_result"]

        def read_holding_registers(self, address, count, slave):
            events.append(("read-holding", address, count, slave))
            if behavior["read_error"] is not None:
                raise behavior["read_error"]
            return behavior["read_result"]

        def close(self):
            events.append(("close",))

        def _forbidden(self, *_args, **_kwargs):
            events.append(("forbidden",))
            raise AssertionError("FC03 read dispatched a write operation")

        write_register = _forbidden
        write_registers = _forbidden
        write_coil = _forbidden
        write_coils = _forbidden

    def forbidden_scan(*_args, **_kwargs):
        events.append(("forbidden",))
        raise AssertionError("FC03 read dispatched a scan operation")

    modbus_module = types.ModuleType("mklink.modbus")
    modbus_module.ModbusClient = ModbusClient
    modbus_module.scan_slaves = forbidden_scan
    monkeypatch.setitem(sys.modules, "mklink.modbus", modbus_module)
    return behavior, events


def _fc03_context():
    manager = _TrackingResourceManager()
    return manager, AgentDispatchContext(device=None, resource_manager=manager)


def _assert_single_modbus_lease_was_released(manager):
    assert len(manager.acquire_calls) == 1
    resource, owner = manager.acquire_calls[0]
    assert resource is ResourceGroup.MODBUS_PORT
    assert manager.release_calls == [owner]
    assert manager.get_status() == {}


def _assert_no_write_or_scan(events):
    assert ("forbidden",) not in events


def test_remote_fc03_read_propagates_9600_8n1_slave_one_holding_and_count(
    fc03_modbus_provider,
):
    behavior, events = fc03_modbus_provider
    manager, context = _fc03_context()

    result = dispatch_capability(
        "modbus.read",
        {
            "port": "test-port",
            "kind": "holding",
            "address": 12,
            "count": 4,
        },
        context=context,
    )

    assert result == behavior["read_result"]
    assert events == [
        ("init", "test-port", 9600, 1.0, 8, "N", 1),
        ("open",),
        ("read-holding", 12, 4, 1),
        ("close",),
    ]
    _assert_single_modbus_lease_was_released(manager)
    _assert_no_write_or_scan(events)


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"port": " ", "kind": "holding", "address": 0}, "port"),
        ({"port": "test-port", "kind": "input", "address": 0}, "kind"),
        ({"port": "test-port", "kind": "holding", "address": -1}, "address"),
        ({"port": "test-port", "kind": "holding", "address": 0x10000}, "address"),
        (
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0,
                "count": 0,
            },
            "count",
        ),
        (
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0,
                "count": 126,
            },
            "count",
        ),
        (
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0xFFFF,
                "count": 2,
            },
            "count",
        ),
        (
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0,
                "slave": 0,
            },
            "slave",
        ),
        (
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0,
                "slave": 248,
            },
            "slave",
        ),
        (
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0,
                "timeout": True,
            },
            "timeout",
        ),
        (
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0,
                "timeout": float("inf"),
            },
            "timeout",
        ),
    ],
)
def test_remote_fc03_invalid_arguments_release_without_opening_provider(
    fc03_modbus_provider,
    params,
    field,
):
    _behavior, events = fc03_modbus_provider
    manager, context = _fc03_context()

    with pytest.raises(RequestValidationError) as error:
        dispatch_capability("modbus.read", params, context=context)

    assert error.value.as_error()["data"] == {"field": field}
    assert events == []
    _assert_single_modbus_lease_was_released(manager)
    _assert_no_write_or_scan(events)


def test_remote_fc03_resource_busy_preserves_existing_owner_and_skips_provider(
    fc03_modbus_provider,
):
    _behavior, events = fc03_modbus_provider
    manager, context = _fc03_context()
    existing = manager.acquire(ResourceGroup.MODBUS_PORT, "test:existing-owner")
    releases_before_dispatch = list(manager.release_calls)

    with pytest.raises(CapabilityUnavailableError) as error:
        dispatch_capability(
            "modbus.read",
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0,
                "count": 1,
                "slave": 1,
            },
            context=context,
        )

    assert error.value.as_error()["data"] == {
        "capability": "modbus",
        "reason": "resource-busy",
    }
    assert events == []
    assert manager.release_calls == releases_before_dispatch
    assert manager.get_status()[ResourceGroup.MODBUS_PORT.value]["owner"] == (
        existing.owner
    )
    _assert_no_write_or_scan(events)

    assert manager.release(existing.owner) == [ResourceGroup.MODBUS_PORT]


def test_remote_fc03_port_unavailable_closes_and_releases_exactly_once(
    fc03_modbus_provider,
):
    behavior, events = fc03_modbus_provider
    behavior["open_result"] = False
    manager, context = _fc03_context()

    with pytest.raises(CapabilityUnavailableError) as error:
        dispatch_capability(
            "modbus.read",
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0,
                "count": 1,
                "slave": 1,
            },
            context=context,
        )

    assert error.value.as_error()["data"] == {
        "capability": "modbus",
        "reason": "port-unavailable",
    }
    assert events.count(("close",)) == 1
    assert not any(event[0] == "read-holding" for event in events)
    _assert_single_modbus_lease_was_released(manager)
    _assert_no_write_or_scan(events)


@pytest.mark.parametrize(
    ("requested_timeout", "provider_timeout"),
    [(0, 0.05), (99, 10.0)],
)
def test_remote_fc03_timeout_is_bounded_and_cleanup_survives_provider_timeout(
    fc03_modbus_provider,
    requested_timeout,
    provider_timeout,
):
    behavior, events = fc03_modbus_provider
    behavior["read_error"] = TimeoutError("synthetic provider timeout")
    manager, context = _fc03_context()

    with pytest.raises(TimeoutError, match="synthetic provider timeout"):
        dispatch_capability(
            "modbus.read",
            {
                "port": "test-port",
                "kind": "holding",
                "address": 0,
                "count": 1,
                "slave": 1,
                "timeout": requested_timeout,
            },
            context=context,
        )

    assert events[0] == (
        "init",
        "test-port",
        9600,
        provider_timeout,
        8,
        "N",
        1,
    )
    assert events.count(("close",)) == 1
    _assert_single_modbus_lease_was_released(manager)
    _assert_no_write_or_scan(events)


def test_agent_capability_merge_is_deterministic_and_cannot_override_lifecycle():
    agent = SiteAgent(
        AgentConfig(),
        device_factory=lambda: None,
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
        device_factory=lambda: None,
        request_dispatcher=sync_dispatch,
    )
    assert asyncio.run(sync_agent._dispatch(request)) == {"value": 7}

    async def async_dispatch(method, params, context):
        seen.append(("async", method, params, context.device))
        return {"async": True}

    async_agent = SiteAgent(
        AgentConfig(),
        device_factory=lambda: None,
        request_dispatcher=async_dispatch,
    )
    assert asyncio.run(async_agent._dispatch(request)) == {"async": True}
    assert [item[0] for item in seen] == ["sync", "async"]

    unsupported_agent = SiteAgent(AgentConfig(), device_factory=lambda: None)
    with pytest.raises(MethodNotFoundError) as unsupported:
        asyncio.run(unsupported_agent._dispatch(request))
    assert unsupported.value.data["reason"] == "unsupported"

    def failing_dispatch(*_args):
        raise RuntimeError(r"secret-token at C:\private\fixture.axf")

    failing_agent = SiteAgent(
        AgentConfig(),
        device_factory=lambda: None,
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
