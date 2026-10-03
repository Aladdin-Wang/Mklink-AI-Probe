"""Probe queries share admission without creating a target Device/session."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mklink._types import DeviceState
from mklink.remote.resource_manager import ResourceGroup, ResourceManager
from mklink.runtime import RuntimeErrorResponse
from mklink.runtime_api import install_runtime
from test_power_telemetry import Bridge, wire


@pytest.fixture
def probe(monkeypatch, tmp_path):
    app = FastAPI()
    state = {'device': None, 'project_root': str(tmp_path), 'resource_manager': ResourceManager()}
    app.state.mklink_state = state
    selected = {'probe_id': 'test-probe', 'port': 'COM9'}
    monkeypatch.setattr('mklink.probes.inventory', lambda: [selected])
    monkeypatch.setattr('mklink.probes.select_probe', lambda selector: selected)
    managers = {'rtt': SimpleNamespace(running=False)}
    monkeypatch.setattr('mklink.remote.dashboards.get_managers', lambda: managers)
    bridge = Bridge()
    calls = []
    def constructor(port):
        calls.append(('open', port))
        return bridge
    def connect(**kwargs):
        calls.append(('connect', kwargs))
        return True
    bridge.connect = connect
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge', constructor)
    def forbidden(*args, **kwargs):
        raise AssertionError('Probe query created a target Device')
    monkeypatch.setattr('mklink.device.Device', forbidden)
    info = {'port': 8765, 'token': 'test-secret', 'instance_id': 'test-instance', 'probe_id': selected['probe_id']}
    control = install_runtime(app, info)
    # install_runtime must insert routes before the GUI's SPA catch-all.
    @app.get('/{path:path}')
    async def spa(path):
        return 'SPA'
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': info['token']}) as client:
        yield client, control, state, bridge, calls, managers, selected


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('capability', ['power-read', 'version'])
def test_probe_query_uses_only_selected_bridge_and_releases_own_resources(probe, existing, capability):
    client, control, state, bridge, calls, _, _ = probe
    if existing:
        state['device'] = SimpleNamespace(connected=True, port='COM9', _bridge=bridge)
    if capability == 'version':
        bridge.response = 'V4.5.2\n>>> '
    response = client.post('/api/probe/' + capability)
    assert response.status_code == 200, response.text
    assert response.json() == ({'raw': bridge.response} if capability == 'version' else dict(
        voltage_mv=3300, current_ma=12.345, power_mw=40.739, current_supported=True, sample_age_ms=10))
    assert bridge.commands == ['cmd.get_version()' if capability == 'version' else 'cmd.get_power()']
    assert calls == ([] if existing else [('open', 'COM9'), ('connect', {'recover_stream': False})])
    assert bridge.closed is (not existing)
    assert not control.sessions and not state['resource_manager'].get_status()
    assert (state['device'] is not None) is existing


@pytest.mark.parametrize('failure', ['busy', 'init', 'missing', 'stale', 'port_changed', 'job', 'unauthenticated'])
def test_conflicts_fail_before_opening_or_interrupting_probe(probe, monkeypatch, failure):
    client, control, state, bridge, calls, managers, selected = probe
    headers = {}
    if failure == 'busy':
        managers['rtt'].running = True
    elif failure == 'init':
        state['resource_manager'].acquire(ResourceGroup.TARGET_DEBUG, 'user:init')
    elif failure == 'missing':
        monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    elif failure in {'stale', 'port_changed'}:
        state['device'] = SimpleNamespace(connected=failure == 'port_changed', port='COM8', _bridge=bridge)
    elif failure == 'job':
        monkeypatch.setattr(control, 'job_busy', lambda: True)
    else:
        headers = {'X-Auth-Token': 'wrong'}
    before = state['resource_manager'].get_status()
    response = client.post('/api/probe/power-read', headers=headers)
    assert response.status_code == (401 if failure == 'unauthenticated' else 409), response.text
    assert calls == bridge.commands == [] and not bridge.closed
    assert state['resource_manager'].get_status() == before
    if failure == 'busy':
        assert managers['rtt'].running


@pytest.mark.parametrize('failure', ['old_firmware', 'timeout', 'handshake', 'not_ready'])
def test_failure_closes_temporary_bridge_without_retry_or_target_session(probe, failure):
    client, control, state, bridge, calls, _, _ = probe
    if failure == 'old_firmware':
        bridge.response = 'AttributeError: get_power\n>>> '
    elif failure == 'timeout':
        def timeout(command, timeout):
            bridge.commands.append(command)
            raise TimeoutError('query outcome unknown')
        bridge.send_command = timeout
    elif failure == 'handshake':
        bridge.connect = lambda **kwargs: False
    else:
        bridge.state = DeviceState.DUMP_STREAM
    response = client.post('/api/probe/power-read')
    assert response.status_code in (400, 409), response.text
    assert bridge.commands == (['cmd.get_power()'] if failure in {'old_firmware', 'timeout'} else [])
    assert bridge.closed and state['device'] is None
    assert not control.sessions and not state['resource_manager'].get_status()


def test_client_query_does_not_attach_or_retry(monkeypatch):
    from mklink import runtime
    calls = []
    info = {'port': 8765, 'token': 'secret'}
    def ensure(**kwargs):
        calls.append(('select', kwargs))
        return info
    def request(endpoint, method, path, body):
        calls.append((endpoint, method, path, body))
        raise RuntimeErrorResponse('failed once')
    monkeypatch.setattr(runtime, 'ensure_runtime', ensure)
    monkeypatch.setattr(runtime, 'request', request)
    with pytest.raises(ValueError):
        runtime.query_probe('halt', probe='chosen')
    assert not calls
    with pytest.raises(RuntimeErrorResponse):
        runtime.query_probe('power_read', probe='chosen')
    assert calls == [('select', {'probe': 'chosen', 'device_port': None}), (info, 'POST', '/api/probe/power-read', {})]
    calls.clear()
    with pytest.raises(RuntimeErrorResponse):
        runtime.query_probe('probe_version', info=info)
    assert calls == [(info, 'POST', '/api/probe/version', {})]


def test_cancelled_request_keeps_admission_until_worker_closes_bridge(probe):
    import threading
    client, control, state, bridge, _, _, _ = probe
    started, finish = threading.Event(), threading.Event()
    def slow(command, timeout):
        started.set()
        assert finish.wait(5)
        return wire()
    bridge.send_command = slow
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url=str(client.base_url), headers=client.headers) as http:
            task = asyncio.create_task(http.post('/api/probe/power-read'))
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(.02)
            assert not task.done() and control.operation_lock.locked()
            assert (await http.post('/api/probe/version')).status_code == 409
            assert state['resource_manager'].get_status() and not bridge.closed
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not control.operation_lock.locked() and bridge.closed
            assert not state['resource_manager'].get_status()
    try:
        asyncio.run(scenario())
    finally:
        finish.set()
