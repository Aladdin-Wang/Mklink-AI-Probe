"""Probe selection and target-debug arbitration regression tests."""
from __future__ import annotations

from types import SimpleNamespace
import asyncio
import importlib
import sys
import threading
import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import pytest


def test_filter_only_returns_mklink_identity_probe():
    from mklink.cmsis_dap.probes import filter_mklink_probes

    probes = [
        SimpleNamespace(
            vendor_name="MicroKeen",
            product_name="MKLink V4 CMSIS-DAP",
            description="",
            unique_id="mk-1",
        ),
        SimpleNamespace(
            vendor_name="ARM",
            product_name="DAPLink CMSIS-DAP",
            description="",
            unique_id="arm-1",
        ),
    ]

    assert [probe.unique_id for probe in filter_mklink_probes(probes)] == ["mk-1"]


def test_probe_filter_accepts_injected_and_environment_usb_ids(monkeypatch):
    from mklink.cmsis_dap.probes import filter_mklink_probes

    probes = [
        SimpleNamespace(unique_id="injected", vid=0x1234, pid=0x5678),
        SimpleNamespace(unique_id="environment", vendor_id=1111, product_id=2222),
        SimpleNamespace(unique_id="bare-hex", vid=0xABCD, pid=0xC001),
        SimpleNamespace(unique_id="other", vid=0x9999, pid=0x0001),
    ]
    monkeypatch.setenv(
        "MKLINK_CMSIS_DAP_USB_IDS",
        "1111:2222, 0xAAAA:0xBBBB, ABCD:C001",
    )

    assert [
        probe.unique_id
        for probe in filter_mklink_probes(probes, {(0x1234, 0x5678)})
    ] == ["injected"]
    assert [probe.unique_id for probe in filter_mklink_probes(probes)] == [
        "bare-hex",
        "environment",
    ]


def test_probe_filter_deduplicates_and_sorts_without_fallback(monkeypatch):
    from mklink.cmsis_dap.probes import filter_mklink_probes

    monkeypatch.delenv("MKLINK_CMSIS_DAP_USB_IDS", raising=False)
    probes = [
        SimpleNamespace(unique_id="z", product_name="mklink beta", vid=1, pid=2),
        SimpleNamespace(unique_id="a", description="MicroLink alpha", vid=3, pid=4),
        SimpleNamespace(unique_id="a", description="MicroLink duplicate", vid=3, pid=4),
        SimpleNamespace(unique_id="", product_name="MKLink missing id"),
        SimpleNamespace(unique_id="generic", product_name="CMSIS-DAP"),
    ]

    records = filter_mklink_probes(probes)

    assert [(record.product_name, record.unique_id) for record in records] == [
        ("", "a"),
        ("mklink beta", "z"),
    ]
    assert records[0].vid == 3
    assert records[0].pid == 4


def test_importing_probe_filter_does_not_load_hardware_backends():
    sys.modules.pop("mklink.cmsis_dap.probes", None)
    modules_before = set(sys.modules)

    importlib.import_module("mklink.cmsis_dap.probes")

    newly_loaded = set(sys.modules) - modules_before
    assert "pyocd" not in newly_loaded
    assert not any(name.startswith("usb") for name in newly_loaded)


def test_online_job_conflicts_with_dashboard_target_debug_owner():
    from mklink.remote.resource_manager import (
        ResourceError,
        ResourceGroup,
        ResourceManager,
    )

    manager = ResourceManager()
    manager.acquire(ResourceGroup.TARGET_DEBUG, "user:dashboard:rtt")

    with pytest.raises(ResourceError) as raised:
        manager.acquire(ResourceGroup.TARGET_DEBUG, "user:online-job:job-1")

    assert raised.value.conflict_owner == "user:dashboard:rtt"
    assert raised.value.resource is ResourceGroup.TARGET_DEBUG


def test_resource_manager_allows_only_one_concurrent_owner():
    from mklink.remote.resource_manager import ResourceError, ResourceGroup, ResourceManager

    manager = ResourceManager()
    barrier = threading.Barrier(3)
    outcomes = []

    def acquire(owner):
        barrier.wait()
        try:
            manager.acquire(ResourceGroup.TARGET_DEBUG, owner)
            outcomes.append((owner, "acquired"))
        except ResourceError:
            outcomes.append((owner, "conflict"))

    threads = [
        threading.Thread(target=acquire, args=(f"user:test:{index}",))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert sorted(result for _, result in outcomes) == ["acquired", "conflict"]


def test_acquire_many_rolls_back_only_transaction_changes():
    from mklink.remote.resource_manager import ResourceError, ResourceGroup, ResourceManager

    manager = ResourceManager()
    old = manager.acquire(ResourceGroup.MKLINK_BRIDGE, "user:multi", ttl=30)
    manager.acquire(ResourceGroup.TARGET_DEBUG, "user:blocker")

    with pytest.raises(ResourceError):
        manager.acquire_many(
            [ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG],
            "user:multi",
            ttl=60,
        )

    assert manager.get_active_lease(ResourceGroup.MKLINK_BRIDGE) is old
    assert manager.get_active_lease(ResourceGroup.TARGET_DEBUG).owner == "user:blocker"
    assert manager.release("user:multi") == [ResourceGroup.MKLINK_BRIDGE]


def test_preempt_callback_runs_outside_lock_and_can_query_status():
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    manager = ResourceManager()
    manager.acquire(ResourceGroup.TARGET_DEBUG, "ai:session:test")
    callback_status = []
    callback_done = threading.Event()

    def callback(_lease, _owner):
        thread = threading.Thread(target=lambda: callback_status.append(manager.get_status()))
        thread.start()
        thread.join(timeout=1)
        if not thread.is_alive():
            callback_done.set()

    manager.on_preempt(callback)
    manager.acquire(ResourceGroup.TARGET_DEBUG, "user:api:halt", preempt=True)

    assert callback_done.is_set()
    assert callback_status[0]["target_debug"]["owner"] == "user:api:halt"


def _dashboard_client(managers):
    with patch("mklink.remote.dashboards.get_managers", return_value=managers):
        from mklink.remote.api import create_app

        app = create_app(auth_token=None, project_root=".")
    app.state.mklink_state["device"] = SimpleNamespace(connected=True)
    return TestClient(app, raise_server_exceptions=False), app.state.mklink_state


@pytest.mark.parametrize(
    ("dashboard", "payload"),
    [
        ("rtt", {}),
        ("systemview", {}),
        ("superwatch", {}),
        ("vofa", {"channels": [{"name": "counter", "addr": "0x20000000"}]}),
    ],
)
def test_dashboard_start_holds_both_target_resources_and_stop_releases(
    dashboard, payload
):
    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    client, state = _dashboard_client(managers)

    response = client.post(f"/api/dash/{dashboard}/start", json=payload)

    assert response.status_code == 200
    owner = f"user:dashboard:{dashboard}"
    status = state["resource_manager"].get_status()
    assert status["mklink_bridge"]["owner"] == owner
    assert status["target_debug"]["owner"] == owner

    stop = client.post(f"/api/dash/{dashboard}/stop")
    assert stop.status_code == 200
    assert state["resource_manager"].get_status() == {}


def test_dashboard_user_conflict_returns_structured_409():
    from mklink.remote.resource_manager import ResourceGroup

    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    client, state = _dashboard_client(managers)
    state["resource_manager"].acquire(ResourceGroup.TARGET_DEBUG, "user:api:flash")

    response = client.post("/api/dash/rtt/start", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "PROBE_BUSY",
        "resource": "target_debug",
        "conflict_owner": "user:api:flash",
    }
    assert "mklink_bridge" not in state["resource_manager"].get_status()


def test_dashboard_start_failure_releases_only_its_new_leases():
    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    managers["rtt"].start.side_effect = RuntimeError("start failed")
    client, state = _dashboard_client(managers)

    response = client.post("/api/dash/rtt/start", json={})

    assert response.status_code == 500
    assert state["resource_manager"].get_status() == {}


def test_native_api_target_operation_releases_lease_on_success_and_failure():
    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    client, state = _dashboard_client(managers)
    owners_seen = []
    device = MagicMock()
    device.connected = True

    def reset():
        owners_seen.append(
            state["resource_manager"].get_status()["target_debug"]["owner"]
        )

    device.reset.side_effect = reset
    state["device"] = device

    assert client.post("/api/device/reset").status_code == 200
    assert owners_seen == ["user:api:reset"]
    assert state["resource_manager"].get_status() == {}

    device.reset.side_effect = RuntimeError("reset failed")
    assert client.post("/api/device/reset").status_code == 500
    assert state["resource_manager"].get_status() == {}


def test_native_api_conflict_with_dashboard_returns_409():
    from mklink.remote.resource_manager import ResourceGroup

    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    client, state = _dashboard_client(managers)
    device = MagicMock()
    device.connected = True
    state["device"] = device
    state["resource_manager"].acquire(
        ResourceGroup.TARGET_DEBUG, "user:dashboard:rtt"
    )

    response = client.post("/api/device/halt")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "PROBE_BUSY",
        "resource": "target_debug",
        "conflict_owner": "user:dashboard:rtt",
    }
    device.halt.assert_not_called()


def test_disconnect_cleanup_is_not_blocked_by_target_lease():
    from mklink.remote.resource_manager import ResourceGroup

    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    client, state = _dashboard_client(managers)
    device = MagicMock()
    device.connected = True
    state["device"] = device
    state["resource_manager"].acquire(
        ResourceGroup.TARGET_DEBUG, "user:dashboard:rtt"
    )

    response = client.post("/api/device/disconnect")

    assert response.status_code == 200
    device.close.assert_called_once()
    assert state["resource_manager"].get_status() == {}


def test_mcu_detect_with_idcode_uses_target_lease_and_reports_conflict():
    from mklink.remote.resource_manager import ResourceGroup

    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    client, state = _dashboard_client(managers)
    owners_seen = []

    def detect(**_kwargs):
        owners_seen.append(
            state["resource_manager"].get_status()["target_debug"]["owner"]
        )
        return {"detected": True}

    with patch("mklink.mcu_detect.detect_mcu_profile", side_effect=detect):
        response = client.post("/api/mcu-detect", json={"port": "COM5"})

    assert response.status_code == 200
    assert owners_seen == ["user:api:mcu-detect"]
    assert state["resource_manager"].get_status() == {}

    state["resource_manager"].acquire(
        ResourceGroup.TARGET_DEBUG, "user:dashboard:rtt"
    )
    with patch("mklink.mcu_detect.detect_mcu_profile") as detect_mock:
        conflict = client.post("/api/mcu-detect", json={"port": "COM5"})

    assert conflict.status_code == 409
    detect_mock.assert_not_called()


def test_run_server_auto_connect_uses_target_lease_and_does_not_bypass_conflict():
    from mklink.remote.api import create_app, run_server
    from mklink.remote.resource_manager import ResourceGroup

    app = create_app(auth_token=None, project_root=".")
    state = app.state.mklink_state
    owners_seen = []
    device = MagicMock()
    device.mcu_name = "HPM5301"
    device.idcode = 0x1234

    def connect(**_kwargs):
        owners_seen.append(
            state["resource_manager"].get_status()["target_debug"]["owner"]
        )
        return device

    with patch("mklink.connect", side_effect=connect), patch("uvicorn.run"):
        run_server(app, auto_connect=True)

    assert owners_seen == ["user:api:auto-connect"]
    assert state["device"] is device
    assert state["resource_manager"].get_status() == {}

    state["device"] = None
    state["resource_manager"].acquire(
        ResourceGroup.TARGET_DEBUG, "user:dashboard:rtt"
    )
    with patch("mklink.connect") as connect_mock, patch("uvicorn.run") as serve_mock:
        run_server(app, auto_connect=True)

    connect_mock.assert_not_called()
    serve_mock.assert_called_once()
    assert state["device"] is None


def test_session_acquire_failure_preserves_same_ai_owner_existing_lease():
    from mklink.remote.resource_manager import ResourceGroup

    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    client, state = _dashboard_client(managers)
    manager = state["resource_manager"]
    old_lease = manager.acquire(
        ResourceGroup.MKLINK_BRIDGE,
        "ai:session:existing",
        ttl=30,
    )
    manager.acquire(ResourceGroup.TARGET_DEBUG, "user:dashboard:rtt")

    response = client.post(
        "/api/session/acquire",
        json={
            "session_id": "existing",
            "resources": ["mklink_bridge", "target_debug"],
            "ttl": 60,
        },
    )

    assert response.status_code == 409
    assert manager.get_active_lease(ResourceGroup.MKLINK_BRIDGE) is old_lease
    assert manager.get_active_lease(ResourceGroup.TARGET_DEBUG).owner == "user:dashboard:rtt"


@pytest.mark.parametrize(
    ("dashboard", "manager_class", "start_method"),
    [
        ("rtt", "RttStreamManager", "rtt_start"),
        ("systemview", "SystemViewStreamManager", "systemview_start"),
    ],
)
def test_async_dashboard_initialization_failure_releases_leases(
    dashboard, manager_class, start_method
):
    from mklink.remote import dashboards

    manager = getattr(dashboards, manager_class)()
    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    managers[dashboard] = manager
    client, state = _dashboard_client(managers)
    device = MagicMock()
    device.connected = True
    device._systemview_defaults.return_value = {}
    getattr(device, start_method).side_effect = RuntimeError("async init failed")
    state["device"] = device

    released = threading.Event()
    original_release = state["resource_manager"].release

    def release(owner):
        result = original_release(owner)
        if owner == f"user:dashboard:{dashboard}":
            released.set()
        return result

    state["resource_manager"].release = release
    response = client.post(f"/api/dash/{dashboard}/start", json={})

    assert response.status_code == 200
    assert released.wait(timeout=2)
    assert state["resource_manager"].get_status() == {}


def test_old_dashboard_failure_callback_cannot_release_new_generation():
    from mklink.remote.api import start_dashboard_manager
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    class Manager:
        running = False

        def __init__(self):
            self.callbacks = []

        def set_start_failure_callback(self, callback):
            self.callbacks.append(callback)

    manager = Manager()
    state = {"resource_manager": ResourceManager()}

    asyncio.run(start_dashboard_manager(state, "rtt", manager, lambda: None))
    old_callback = manager.callbacks[-1]
    state["resource_manager"].release("user:dashboard:rtt")
    asyncio.run(start_dashboard_manager(state, "rtt", manager, lambda: None))
    new_callback = manager.callbacks[-1]

    old_callback(RuntimeError("old failure"))
    assert state["resource_manager"].get_active_lease(
        ResourceGroup.TARGET_DEBUG
    ).owner == "user:dashboard:rtt"

    new_callback(RuntimeError("current failure"))
    assert state["resource_manager"].get_status() == {}


def test_dashboard_start_resource_acquisition_does_not_block_event_loop(monkeypatch):
    from mklink.remote.api import start_dashboard_manager

    acquisition_started = threading.Event()

    def blocking_acquire(_state, dashboard):
        assert dashboard == "superwatch"
        acquisition_started.set()
        time.sleep(0.2)
        return []

    monkeypatch.setattr(
        "mklink.remote.api.acquire_dashboard_resources", blocking_acquire,
    )
    manager = SimpleNamespace(running=False)
    state = {"resource_manager": SimpleNamespace(release=lambda _owner: None)}

    async def scenario():
        loop = asyncio.get_running_loop()
        heartbeat_start = loop.time()

        async def heartbeat_probe():
            await asyncio.sleep(0.01)
            return loop.time() - heartbeat_start

        heartbeat = asyncio.create_task(heartbeat_probe())
        start = asyncio.create_task(start_dashboard_manager(
            state, "superwatch", manager, lambda: None,
        ))
        heartbeat_elapsed, _result = await asyncio.gather(heartbeat, start)
        return heartbeat_elapsed

    heartbeat_elapsed = asyncio.run(scenario())
    assert acquisition_started.is_set()
    assert heartbeat_elapsed < 0.05


def test_dashboard_start_cancel_during_acquisition_releases_late_lease(monkeypatch):
    from mklink.remote.api import start_dashboard_manager
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    resource_manager = ResourceManager()
    state = {"resource_manager": resource_manager}
    manager = SimpleNamespace(running=False)
    acquisition_started = threading.Event()
    release_acquisition = threading.Event()
    acquisition_finished = threading.Event()
    start_calls = []

    def delayed_acquire(_state, dashboard):
        acquisition_started.set()
        assert release_acquisition.wait(1.0)
        _state["resource_manager"].acquire_many(
            [ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG],
            f"user:dashboard:{dashboard}",
        )
        acquisition_finished.set()
        return []

    monkeypatch.setattr(
        "mklink.remote.api.acquire_dashboard_resources", delayed_acquire,
    )

    async def scenario():
        task = asyncio.create_task(start_dashboard_manager(
            state, "superwatch", manager, lambda: start_calls.append(True),
        ))
        assert await asyncio.to_thread(acquisition_started.wait, 1.0)
        task.cancel()
        release_acquisition.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(acquisition_finished.wait, 1.0)

    asyncio.run(scenario())
    assert start_calls == []
    assert resource_manager.get_status() == {}


def test_dashboard_start_cancel_during_start_stops_late_success_and_releases(monkeypatch):
    from mklink.remote.api import start_dashboard_manager
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    class Manager:
        running = False
        stop_calls = 0

        def stop(self):
            self.stop_calls += 1
            self.running = False

    manager = Manager()
    resource_manager = ResourceManager()
    state = {"resource_manager": resource_manager}
    start_started = threading.Event()
    release_start = threading.Event()
    start_finished = threading.Event()

    def acquire(_state, dashboard):
        _state["resource_manager"].acquire_many(
            [ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG],
            f"user:dashboard:{dashboard}",
        )
        return []

    def delayed_start():
        start_started.set()
        assert release_start.wait(1.0)
        manager.running = True
        start_finished.set()

    monkeypatch.setattr("mklink.remote.api.acquire_dashboard_resources", acquire)

    async def scenario():
        task = asyncio.create_task(start_dashboard_manager(
            state, "superwatch", manager, delayed_start,
        ))
        assert await asyncio.to_thread(start_started.wait, 1.0)
        task.cancel()
        release_start.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(start_finished.wait, 1.0)

    asyncio.run(scenario())
    assert manager.stop_calls == 1
    assert not manager.running
    assert resource_manager.get_status() == {}


def test_dashboard_start_cancel_and_shutdown_cleanup_once_without_leak(monkeypatch):
    from mklink.remote.api import start_dashboard_manager
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    class CountingResourceManager(ResourceManager):
        def __init__(self):
            super().__init__()
            self.release_calls = []

        def release(self, owner):
            self.release_calls.append(owner)
            return super().release(owner)

    class Manager:
        running = False
        stop_calls = 0

        def stop(self):
            self.stop_calls += 1
            self.running = False

    manager = Manager()
    resource_manager = CountingResourceManager()
    state = {"resource_manager": resource_manager}
    start_started = threading.Event()
    allow_shutdown = threading.Event()
    shutdown_done = threading.Event()

    def acquire(_state, dashboard):
        _state["resource_manager"].acquire_many(
            [ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG],
            f"user:dashboard:{dashboard}",
        )
        return []

    def delayed_start():
        manager.running = True
        start_started.set()
        assert shutdown_done.wait(1.0)

    def shutdown_manager():
        assert allow_shutdown.wait(1.0)
        manager.stop()
        shutdown_done.set()

    monkeypatch.setattr("mklink.remote.api.acquire_dashboard_resources", acquire)
    shutdown = threading.Thread(target=shutdown_manager, daemon=True)
    shutdown.start()

    async def scenario():
        task = asyncio.create_task(start_dashboard_manager(
            state, "superwatch", manager, delayed_start,
        ))
        assert await asyncio.to_thread(start_started.wait, 1.0)
        task.cancel()
        allow_shutdown.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    shutdown.join(timeout=1.0)
    assert not shutdown.is_alive()
    assert manager.stop_calls == 1
    assert resource_manager.release_calls == ["user:dashboard:superwatch"]
    assert resource_manager.get_status() == {}


@pytest.mark.parametrize("dashboard", ["rtt", "systemview", "superwatch", "vofa"])
def test_dashboard_stop_releases_leases_even_when_manager_stop_raises(dashboard):
    from mklink.remote.resource_manager import ResourceGroup

    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    managers[dashboard].stop.side_effect = RuntimeError("stop failed")
    client, state = _dashboard_client(managers)
    state["resource_manager"].acquire_many(
        [ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG],
        f"user:dashboard:{dashboard}",
    )

    response = client.post(f"/api/dash/{dashboard}/stop")

    assert response.status_code == 500
    assert state["resource_manager"].get_status() == {}


def test_stop_bridge_dashboards_releases_owner_when_stop_raises():
    from mklink.remote import dashboards
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    manager = SimpleNamespace(running=True)

    def stop_dead_worker():
        manager.running = False
        raise RuntimeError("boom")

    manager.stop = MagicMock(side_effect=stop_dead_worker)
    managers = {name: None for name in dashboards.BRIDGE_DASHBOARD_TYPES}
    managers["rtt"] = manager
    resource_manager = ResourceManager()
    resource_manager.acquire_many(
        [ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG],
        "user:dashboard:rtt",
    )

    with patch.object(dashboards, "get_managers", return_value=managers):
        with pytest.raises(RuntimeError, match="boom"):
            dashboards.stop_bridge_dashboards(resource_manager=resource_manager)

    assert resource_manager.get_status() == {}


def test_native_target_context_serializes_same_owner_across_threads():
    from mklink.remote.api import target_debug_lease
    from mklink.remote.resource_manager import ResourceError, ResourceGroup, ResourceManager

    state = {"resource_manager": ResourceManager()}
    first_entered = threading.Event()
    release_first = threading.Event()
    second_attempted = threading.Event()
    second_entered = threading.Event()

    def first():
        with target_debug_lease(state, "read-memory"):
            first_entered.set()
            assert release_first.wait(timeout=2)

    def second():
        second_attempted.set()
        with target_debug_lease(state, "read-memory"):
            second_entered.set()

    thread_a = threading.Thread(target=first)
    thread_b = threading.Thread(target=second)
    thread_a.start()
    assert first_entered.wait(timeout=1)
    thread_b.start()
    assert second_attempted.wait(timeout=1)
    assert not second_entered.wait(timeout=0.1)

    with pytest.raises(ResourceError):
        state["resource_manager"].acquire(
            ResourceGroup.TARGET_DEBUG,
            "ai:session:blocked",
        )

    release_first.set()
    thread_a.join(timeout=1)
    thread_b.join(timeout=1)
    assert second_entered.is_set()
    assert state["resource_manager"].get_status() == {}


def test_nested_native_target_context_does_not_release_outer_lease():
    from mklink.remote.api import target_debug_lease
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    state = {"resource_manager": ResourceManager()}
    with target_debug_lease(state, "read-memory"):
        outer = state["resource_manager"].get_active_lease(ResourceGroup.TARGET_DEBUG)
        with target_debug_lease(state, "halt"):
            assert state["resource_manager"].get_active_lease(
                ResourceGroup.TARGET_DEBUG
            ) is outer
        assert state["resource_manager"].get_active_lease(
            ResourceGroup.TARGET_DEBUG
        ) is outer

    assert state["resource_manager"].get_status() == {}


def test_async_native_target_context_serializes_independent_coroutines():
    from mklink.remote.api import async_target_debug_lease
    from mklink.remote.resource_manager import ResourceManager

    state = {"resource_manager": ResourceManager()}

    async def exercise():
        active = 0
        max_active = 0
        counter_lock = threading.Lock()
        first_entered = threading.Event()
        second_entered = threading.Event()
        release_first = threading.Event()

        def body(index):
            nonlocal active, max_active
            with counter_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                if index == 1:
                    first_entered.set()
                    assert release_first.wait(timeout=2)
                else:
                    second_entered.set()
            finally:
                with counter_lock:
                    active -= 1

        async def operation(index):
            async with async_target_debug_lease(state, "read-memory"):
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, body, index)

        first = asyncio.create_task(operation(1))
        assert await asyncio.get_running_loop().run_in_executor(
            None, first_entered.wait, 1
        )
        second = asyncio.create_task(operation(2))
        await asyncio.get_running_loop().run_in_executor(
            None, second_entered.wait, 0.1
        )
        release_first.set()
        await asyncio.gather(first, second)
        return max_active

    assert asyncio.run(exercise()) == 1
    assert state["resource_manager"].get_status() == {}


def test_async_native_target_nested_task_depth_is_task_local():
    from mklink.remote.api import async_target_debug_lease
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    state = {"resource_manager": ResourceManager()}

    async def exercise():
        independent_attempted = asyncio.Event()
        independent_entered = asyncio.Event()

        async def independent():
            independent_attempted.set()
            async with async_target_debug_lease(state, "halt"):
                independent_entered.set()

        async with async_target_debug_lease(state, "read-memory"):
            outer = state["resource_manager"].get_active_lease(
                ResourceGroup.TARGET_DEBUG
            )
            async with async_target_debug_lease(state, "halt"):
                assert state["resource_manager"].get_active_lease(
                    ResourceGroup.TARGET_DEBUG
                ) is outer
            assert state["resource_manager"].get_active_lease(
                ResourceGroup.TARGET_DEBUG
            ) is outer

            task = asyncio.create_task(independent())
            await independent_attempted.wait()
            await asyncio.sleep(0)
            assert not independent_entered.is_set()

        await task
        assert independent_entered.is_set()

    asyncio.run(exercise())
    assert state["resource_manager"].get_status() == {}


def test_rtt_stop_timeout_preserves_lease_and_prevents_overlapping_generation():
    from mklink.remote.api import stop_dashboard_manager
    from mklink.remote.dashboards import RttStreamManager
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    manager = RttStreamManager()
    state = {"resource_manager": ResourceManager()}
    state["resource_manager"].acquire_many(
        [ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG],
        "user:dashboard:rtt",
    )
    read_entered = threading.Event()
    unblock_read = threading.Event()
    active_reads = 0
    max_active_reads = 0
    read_lock = threading.Lock()
    start_calls = 0

    class Device:
        def rtt_start(self, *_args, **_kwargs):
            nonlocal start_calls
            start_calls += 1

        def rtt_read(self, **_kwargs):
            nonlocal active_reads, max_active_reads
            with read_lock:
                active_reads += 1
                max_active_reads = max(max_active_reads, active_reads)
            try:
                if not read_entered.is_set():
                    read_entered.set()
                    assert unblock_read.wait(timeout=2)
                return ""
            finally:
                with read_lock:
                    active_reads -= 1

    device = Device()
    manager.start(device)
    assert read_entered.wait(timeout=1)
    original_stop = manager.stop
    manager.stop = lambda: original_stop(timeout=0.01)

    with pytest.raises(Exception) as stopped:
        stop_dashboard_manager(state, "rtt", manager)

    assert getattr(stopped.value, "detail", {})["code"] == "stop_pending"
    assert state["resource_manager"].get_active_lease(
        ResourceGroup.TARGET_DEBUG
    ).owner == "user:dashboard:rtt"
    with pytest.raises(RuntimeError, match="still active"):
        manager.start(device)
    assert start_calls == 1

    unblock_read.set()
    manager._thread.join(timeout=1)
    stop_dashboard_manager(state, "rtt", manager)
    manager.stop = original_stop
    assert state["resource_manager"].get_status() == {}

    manager.start(device)
    assert start_calls == 2
    manager.stop(timeout=1)
    assert max_active_reads == 1


class _AlwaysAliveThread:
    def is_alive(self):
        return True


@pytest.mark.parametrize("dashboard", ["rtt", "systemview", "superwatch", "vofa"])
def test_dashboard_stop_pending_preserves_leases(dashboard):
    from mklink.remote.resource_manager import ResourceGroup

    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    managers[dashboard]._thread = _AlwaysAliveThread()
    managers[dashboard].stop.side_effect = TimeoutError("worker still active")
    client, state = _dashboard_client(managers)
    state["resource_manager"].acquire_many(
        [ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG],
        f"user:dashboard:{dashboard}",
    )

    response = client.post(f"/api/dash/{dashboard}/stop")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "stop_pending",
        "dashboard": dashboard,
    }
    assert state["resource_manager"].get_active_lease(
        ResourceGroup.TARGET_DEBUG
    ).owner == f"user:dashboard:{dashboard}"


@pytest.mark.parametrize(
    ("dashboard", "payload"),
    [
        ("rtt", {}),
        ("systemview", {}),
        ("superwatch", {}),
        ("vofa", {"channels": [{"name": "x", "addr": "0x20000000"}]}),
    ],
)
def test_dashboard_start_rejects_old_live_worker_without_refreshing_lease(
    dashboard, payload
):
    from mklink.remote.resource_manager import ResourceGroup

    managers = {
        name: SimpleNamespace(running=False, start=MagicMock(), stop=MagicMock())
        for name in ("rtt", "systemview", "superwatch", "vofa", "serial", "modbus")
    }
    managers[dashboard]._thread = _AlwaysAliveThread()
    client, state = _dashboard_client(managers)
    old_lease = state["resource_manager"].acquire(
        ResourceGroup.TARGET_DEBUG,
        f"user:dashboard:{dashboard}",
    )
    state["resource_manager"].acquire(
        ResourceGroup.MKLINK_BRIDGE,
        f"user:dashboard:{dashboard}",
    )

    response = client.post(f"/api/dash/{dashboard}/start", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "stop_pending",
        "dashboard": dashboard,
    }
    assert state["resource_manager"].get_active_lease(
        ResourceGroup.TARGET_DEBUG
    ) is old_lease
    managers[dashboard].start.assert_not_called()


def test_systemview_start_failure_releases_only_after_target_cleanup():
    from mklink.remote.dashboards import SystemViewStreamManager
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    manager = SystemViewStreamManager()
    resource_manager = ResourceManager()
    owner = "user:dashboard:systemview"
    resource_manager.acquire(ResourceGroup.TARGET_DEBUG, owner)
    cleanup_entered = threading.Event()
    allow_cleanup = threading.Event()
    callback_called = threading.Event()
    cleanup_owners = []

    device = MagicMock()
    device._systemview_defaults.return_value = {}
    device.systemview_start.side_effect = RuntimeError("init failed")

    def cleanup():
        lease = resource_manager.get_active_lease(ResourceGroup.TARGET_DEBUG)
        cleanup_owners.append(lease.owner if lease else None)
        cleanup_entered.set()
        assert allow_cleanup.wait(timeout=2)

    def failed(_error):
        callback_called.set()
        resource_manager.release(owner)

    device.systemview_stop.side_effect = cleanup
    manager.set_start_failure_callback(failed)
    manager.start(device)

    assert cleanup_entered.wait(timeout=1)
    assert cleanup_owners == [owner]
    assert not callback_called.is_set()
    assert resource_manager.get_active_lease(ResourceGroup.TARGET_DEBUG).owner == owner

    allow_cleanup.set()
    assert callback_called.wait(timeout=1)
    manager._thread.join(timeout=1)
    assert resource_manager.get_status() == {}


def test_rtt_start_failure_callback_runs_after_worker_cleanup():
    from mklink.remote.dashboards import RttStreamManager
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager

    manager = RttStreamManager()
    resource_manager = ResourceManager()
    owner = "user:dashboard:rtt"
    resource_manager.acquire(ResourceGroup.TARGET_DEBUG, owner)
    bridge_cleanup_done = threading.Event()
    callback_called = threading.Event()
    callback_observations = []
    original_bridge_stop = manager._bridge.stop

    def bridge_stop():
        original_bridge_stop()
        bridge_cleanup_done.set()

    def failed(_error):
        callback_observations.append(
            (bridge_cleanup_done.is_set(), manager.running)
        )
        callback_called.set()
        resource_manager.release(owner)

    device = MagicMock()
    device.rtt_start.side_effect = RuntimeError("init failed")
    manager._bridge.stop = bridge_stop
    manager.set_start_failure_callback(failed)
    manager.start(device)

    assert callback_called.wait(timeout=1)
    manager._thread.join(timeout=1)
    assert callback_observations == [(True, False)]
    assert resource_manager.get_status() == {}
