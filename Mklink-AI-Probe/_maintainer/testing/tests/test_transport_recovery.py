"""USB loss recovery retains identity and intent, never submitted commands."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from mklink.runtime_api import RuntimeControl
from mklink.runtime_recovery import TransportRecovery
from test_download_acquisition import capture
from test_shared_runtime import runtime, attach


@pytest.fixture
def recovery(capture, monkeypatch):
    state, managers, calls = capture
    app = FastAPI()
    app.state.mklink_state = state
    device = state['device']
    device.idcode, device.clock_hz = 123, 4_000_000
    device._mcu_hint, device._project_root = None, '.'
    device._bridge = SimpleNamespace(_transport_error=None)
    device._flash = SimpleNamespace(set_swd_clock=Mock())
    device.symbol_catalog = SimpleNamespace(is_stale=lambda: False)
    def close():
        calls.append(('close', device))
        device.connected = False
        device._bridge = None
    def connect(*, load_symbols):
        assert load_symbols is False  # Never reparse new on-disk firmware.
        calls.append(('connect', device._port))
        device.connected = True
        device._bridge = SimpleNamespace(_transport_error=None)
    device.close, device._connect = close, connect
    c = RuntimeControl(app, {'probe_id': 'same', 'instance_id': 'fixture'})
    monkeypatch.setattr(c, 'gui_active', lambda: True)
    monkeypatch.setattr('mklink.probes.select_probe', lambda key: {'probe_id': key, 'port': 'COM12'})
    monkeypatch.setattr('mklink.device.initialize_target', lambda *a, **k: 123)
    r = TransportRecovery(c)
    c.recovery = r
    return r, state, managers, calls


async def lose(r, state):
    await r.tick()
    state['device'].connected = False
    state['device']._bridge._transport_error = OSError('CDC failed')


def test_restores_same_identity_new_port_catalog_and_paused_stream(recovery):
    r, state, managers, calls = recovery
    managers['superwatch'].paused = True
    catalog = state['device'].symbol_catalog
    async def run():
        await lose(r, state)
        assert r.retains_session()
        await r.tick()
    asyncio.run(run())
    assert ('connect', 'COM12') in calls
    assert calls[-3:] == [('start', 'rtt'), ('start', 'superwatch'), ('pause', 'superwatch')]
    assert state['device'].symbol_catalog is catalog
    assert r.status['state'] == 'restored' and r.status['data_gap']
    assert managers['serial'].running


@pytest.mark.parametrize('reason', ['missing', 'different', 'manual-disconnect', 'expired', 'job', 'operation', 'shutdown'])
def test_never_opens_wrong_probe_or_overrides_admission(recovery, monkeypatch, reason):
    r, state, _, calls = recovery
    async def run():
        await lose(r, state)
        if reason == 'missing':
            monkeypatch.setattr('mklink.probes.select_probe', Mock(side_effect=RuntimeError('missing')))
        elif reason == 'different':
            monkeypatch.setattr('mklink.probes.select_probe', lambda key: {'probe_id': 'other', 'port': 'COM12'})
        elif reason == 'manual-disconnect':
            state['device'] = None
        elif reason == 'expired':
            monkeypatch.setattr(r.control, 'gui_active', lambda: False)
        elif reason == 'job':
            monkeypatch.setattr(r.control, 'job_busy', lambda: True)
        elif reason == 'operation':
            await r.control.operation_lock.acquire()
        else:
            r.control.stopping = True
        await r.tick()
    asyncio.run(run())
    assert calls == []


@pytest.mark.parametrize('reason', ['stopped', 'changed-symbols', 'changed-target', 'stale-catalog'])
def test_reconnect_does_not_resume_invalid_capture(recovery, monkeypatch, reason):
    r, state, managers, calls = recovery
    async def run():
        await lose(r, state)
        if reason == 'stopped':
            for m in managers.values():
                m._explicit_stop_version = 1
        elif reason == 'changed-symbols':
            state['file_source_change'] = {'pending': True}
        elif reason == 'changed-target':
            monkeypatch.setattr('mklink.device.initialize_target', lambda *a, **k: 456)
        else:
            state['device'].symbol_catalog.is_stale = lambda: True
        await r.tick()
    asyncio.run(run())
    assert state['device'].connected
    assert not any(action == 'start' for action, _ in calls)


def test_drain_error_after_worker_exit_allows_recovery(recovery):
    r, state, managers, calls = recovery
    def stop():
        managers['rtt'].running = False
        raise OSError('dead CDC cannot acknowledge stop')
    managers['rtt'].stop = stop
    async def run():
        await lose(r, state)
        await r.tick()
    asyncio.run(run())
    assert r.status['state'] == 'restored'
    assert ('start', 'rtt') in calls


def test_stuck_worker_blocks_close_and_retry_is_bounded(recovery):
    r, state, managers, calls = recovery
    managers['rtt'].stop = Mock(side_effect=TimeoutError('still reading'))
    async def run():
        await lose(r, state)
        for _ in range(6):
            r.next_attempt = 0
            await r.tick()
    asyncio.run(run())
    assert r.status['state'] == 'failed' and r.attempts == 5
    assert not r.retains_session()
    assert calls == []


def test_heartbeat_retains_ai_lease_before_first_monitor_tick(runtime):
    client, control, _, _, app = runtime
    session = attach(client)
    control.info['probe_id'] = 'same'
    device = app.state.mklink_state['device']
    device.connected = False
    device._bridge = SimpleNamespace(_transport_error=OSError('USB gone'))
    assert client.post('/_runtime/heartbeat', json={'session_id': session}).status_code == 200
    assert session in control.sessions
    app.state.mklink_state['device'] = None
    assert client.post('/_runtime/heartbeat', json={'session_id': session}).status_code == 409


def test_target_error_without_transport_failure_does_not_reconnect(recovery):
    r, state, _, calls = recovery
    state['device'].connected = False
    asyncio.run(r.tick())
    assert calls == [] and not r.retains_session()


def test_recovery_keeps_client_ownership_and_subscriptions(recovery):
    from mklink.runtime_api import Session
    r, state, _, calls = recovery
    session = Session('AI', 'mcp', '.', None)
    session.streams.add('rtt')
    r.control.sessions['existing'] = session
    r.control.created_streams['rtt'] = 'existing'
    async def run():
        await lose(r, state)
        await r.tick()
    asyncio.run(run())
    assert r.control.sessions['existing'] is session
    assert session.streams == {'rtt'}
    assert r.control.created_streams['rtt'] == 'existing'
    assert ('start', 'rtt') in calls


def test_absence_over_five_seconds_never_reconnects_on_later_arrival(recovery, monkeypatch):
    r, state, _, calls = recovery
    clock = [100.0]
    monkeypatch.setattr('mklink.runtime_recovery.time.monotonic', lambda: clock[0])
    select = Mock(side_effect=RuntimeError('missing'))
    monkeypatch.setattr('mklink.probes.select_probe', select)
    async def run():
        await lose(r, state)
        await r.tick()
        assert r.status['state'] == 'waiting' and r.retains_session()
        clock[0] += 5
        await r.tick()
        assert r.status['state'] == 'expired' and not r.retains_session()
        select.side_effect = None
        select.return_value = {'probe_id':'same', 'port':'COM12'}
        for _ in range(3):
            clock[0] += 10
            await r.tick()
        assert r.status['state'] == 'expired'
    asyncio.run(run())
    assert calls == []
    assert select.call_count == 1


def test_open_finishing_after_deadline_is_closed_without_resuming(recovery, monkeypatch):
    r, state, _, calls = recovery
    clock = [100.0]
    monkeypatch.setattr('mklink.runtime_recovery.time.monotonic', lambda: clock[0])
    connect = state['device']._connect
    def slow_connect(**kwargs):
        connect(**kwargs)
        clock[0] += 5.1
    state['device']._connect = slow_connect
    async def run():
        await lose(r, state)
        await r.tick()
    asyncio.run(run())
    assert r.status['state'] == 'expired'
    assert not state['device'].connected
    assert not any(action == 'start' for action, _ in calls)


def test_expiry_during_worker_join_does_not_close_its_handle(recovery, monkeypatch):
    r, state, managers, calls = recovery
    clock = [100.0]
    monkeypatch.setattr('mklink.runtime_recovery.time.monotonic', lambda: clock[0])
    def stuck():
        clock[0] += 6
        raise TimeoutError('worker remains active')
    managers['rtt'].stop = stuck
    async def run():
        await lose(r, state)
        await r.tick()
    asyncio.run(run())
    assert r.status['state'] == 'expired' and calls == []
