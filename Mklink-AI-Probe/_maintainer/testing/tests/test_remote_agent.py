"""Public lifecycle tests for the probe-independent Site Agent.

Traces: TEST-001, API-005, REQ-004, INV-03 and INV-06.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

import pytest

from mklink.remote.agent import AgentConfig, SiteAgent


def _run(coro):
    return asyncio.run(coro)


@asynccontextmanager
async def _running(agent):
    task = asyncio.create_task(agent.serve())
    try:
        for _ in range(100):
            if agent.ready:
                break
            await asyncio.sleep(0.01)
        assert agent.ready
        yield task
    finally:
        agent.request_stop()
        await asyncio.wait_for(task, timeout=2)


class _Device:
    connected = True

    def __init__(self):
        self.closed = threading.Event()

    def close(self):
        self.closed.set()


def test_readiness_handshake_health_and_status_work_without_a_probe():
    async def scenario():
        agent = SiteAgent(AgentConfig(port=0), device_factory=lambda: _Device())
        async with _running(agent):
            assert agent.ready is True
            assert agent.port not in (None, 0)
            handshake = agent.handshake().as_dict()
            assert handshake["capabilities"]["agent.lifecycle"]["available"] is True
            assert handshake["limits"]["max_message_bytes"] > 0
            assert agent.health() == {
                "ready": True, "listener": True, "probe_connected": False,
            }
            status = agent.status()
            assert status["device_state"] == "disconnected"
            assert status["resources"] == {}

    _run(scenario())


def test_factory_failure_is_redacted_and_a_later_reconnect_recovers_without_listener_restart():
    calls = []
    device = _Device()

    def factory(**_kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("sensitive local path and token")
        return device

    async def scenario():
        agent = SiteAgent(AgentConfig(port=0), device_factory=factory)
        async with _running(agent):
            initial_port = agent.port
            failed = agent.reconnect()
            assert failed == {"connected": False, "error": "Device connection failed"}
            assert "sensitive" not in agent.status()["last_error"]
            recovered = agent.reconnect()
            assert recovered == {"connected": True}
            assert agent.port == initial_port
            assert agent.status()["device_state"] == "connected"

    _run(scenario())


@pytest.mark.parametrize("factory_form", ["keyword", "no-argument"])
def test_system_exit_from_factory_is_contained_and_recovery_reuses_listener(
    factory_form,
):
    """Both supported factory forms must contain process-style connect exits."""

    first_device = _Device()
    recovered_device = _Device()
    devices = [first_device, SystemExit("sensitive local details"), recovered_device]

    def next_result():
        result = devices.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    if factory_form == "keyword":
        def factory(**_kwargs):
            return next_result()
    else:
        def factory():
            return next_result()

    async def scenario():
        agent = SiteAgent(AgentConfig(port=0), device_factory=factory)
        async with _running(agent):
            initial_port = agent.port
            assert agent.reconnect() == {"connected": True}

            failed = agent.reconnect()

            assert failed == {
                "connected": False,
                "error": "Device connection failed",
            }
            assert first_device.closed.is_set()
            assert agent.port == initial_port
            assert agent.health() == {
                "ready": True,
                "listener": True,
                "probe_connected": False,
            }
            status = agent.status()
            assert status["device_state"] == "disconnected"
            assert status["last_error"] == "Device connection failed"
            assert "sensitive" not in status["last_error"]
            assert status["resources"] == {}

            assert agent.reconnect() == {"connected": True}
            assert agent.port == initial_port
            assert agent.status()["resources"] == {}

        assert recovered_device.closed.is_set()

    _run(scenario())


@pytest.mark.parametrize("factory_form", ["keyword", "no-argument"])
def test_keyboard_interrupt_from_factory_is_not_mapped_to_connection_failure(
    factory_form,
):
    recovered_device = _Device()
    results = [KeyboardInterrupt(), recovered_device]

    def next_result():
        result = results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    if factory_form == "keyword":
        def factory(**_kwargs):
            return next_result()
    else:
        def factory():
            return next_result()

    async def scenario():
        agent = SiteAgent(AgentConfig(port=0), device_factory=factory)
        async with _running(agent):
            initial_port = agent.port
            with pytest.raises(KeyboardInterrupt):
                agent.reconnect()

            assert agent.port == initial_port
            assert agent.health() == {
                "ready": True,
                "listener": True,
                "probe_connected": False,
            }
            assert agent.status()["last_error"] is None
            assert agent.status()["resources"] == {}
            assert agent.reconnect() == {"connected": True}
            assert agent.port == initial_port

        assert recovered_device.closed.is_set()

    _run(scenario())


def test_same_device_reconnect_commands_are_serialized():
    entered = threading.Event()
    release = threading.Event()
    active = 0
    maximum_active = 0
    active_lock = threading.Lock()

    def factory(**_kwargs):
        nonlocal active, maximum_active
        with active_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        entered.set()
        assert release.wait(timeout=2)
        with active_lock:
            active -= 1
        return _Device()

    agent = SiteAgent(AgentConfig(), device_factory=factory)
    first = threading.Thread(target=agent.reconnect)
    second = threading.Thread(target=agent.reconnect)
    first.start()
    assert entered.wait(timeout=1)
    second.start()
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert maximum_active == 1
    agent.close()


def test_status_remains_responsive_while_reconnect_has_long_running_device_work():
    """A status request must not wait for a lower-level reconnect operation."""

    factory_started = threading.Event()
    release_factory = threading.Event()
    status_finished = threading.Event()
    status_result = {}

    def factory(**_kwargs):
        factory_started.set()
        assert release_factory.wait(timeout=2)
        return _Device()

    agent = SiteAgent(AgentConfig(), device_factory=factory)
    reconnect_thread = threading.Thread(target=agent.reconnect)
    reconnect_thread.start()
    assert factory_started.wait(timeout=1)

    def read_status():
        status_result.update(agent.status())
        status_finished.set()

    status_thread = threading.Thread(target=read_status)
    status_thread.start()
    try:
        assert status_finished.wait(timeout=1), (
            "status was blocked by long-running device work"
        )
        assert status_result["device_state"] == "disconnected"
    finally:
        release_factory.set()
        reconnect_thread.join(timeout=2)
        status_thread.join(timeout=2)
        agent.close()


def test_cooperative_stop_releases_device_and_listener_resources():
    device = _Device()

    async def scenario():
        agent = SiteAgent(AgentConfig(port=0), device_factory=lambda **_kwargs: device)
        async with _running(agent):
            assert agent.reconnect() == {"connected": True}
            assert agent.status()["resources"] == {}
            agent.request_stop()
        assert agent.ready is False
        assert agent.port is None
        assert device.closed.is_set()

    _run(scenario())
