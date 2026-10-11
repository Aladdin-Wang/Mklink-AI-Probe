"""A probe switch must retain the backend and never move another client's work."""
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from mklink import probes, runtime
from mklink.remote import dashboards
from mklink.remote.api import create_app
from mklink.runtime_api import install_runtime, Session
from mklink.runtime_binding import RuntimeBinding
from test_remote_api import _connected_symbol_device

A, B = 'usb-' + 'a' * 24, 'usb-' + 'b' * 24


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(probes, '_bound_probe', A)
    monkeypatch.setattr(dashboards, '_managers', {})
    rows = [{'probe_id': A, 'port': 'COM1', 'alias': ''}, {'probe_id': B, 'port': 'COM2', 'alias': ''}]
    monkeypatch.setattr(probes, 'inventory', lambda: rows)
    monkeypatch.setattr(runtime, 'ensure_runtime', Mock(side_effect=AssertionError('Switch spawned a backend')))
    app = create_app(project_root=str(tmp_path), auth_token=None)
    info = {'port': 8765, 'token': 'test', 'pid': 123, 'instance_id': 'same-instance',
            'probe_id': A, 'runtime_id': 'local-' + 'c' * 24}
    control = install_runtime(app, info)
    binding = control.binding = RuntimeBinding(info)
    with binding.reserve(A) as commit:
        commit()
    device, _ = _connected_symbol_device(tmp_path)
    device.port = 'COM1'
    device.close = Mock()
    app.state.mklink_state['device'] = device
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test'}) as client:
        try:
            yield client, control, device, app.state.mklink_state
        finally:
            control.sessions.clear()
            app.state.mklink_state['device'] = None
            binding.close()


def test_switch_releases_old_handle_clears_target_data_and_keeps_endpoint(window, monkeypatch):
    client, control, device, state = window
    original = dict(control.info)
    old = dict(dashboards.get_managers())
    old['rtt']._history.append({'text': 'old target'})
    closed = []
    device.close.side_effect = lambda: closed.append(probes.bound_probe())
    response = client.post('/api/runtime/select', json={'port': 'COM2'})
    assert response.status_code == 200, response.text
    assert response.json()['same_runtime'] and response.json()['switched']
    assert closed == [A] and probes.bound_probe() == B
    assert {k: control.info[k] for k in ('port', 'pid', 'instance_id', 'token')} == {
        k: original[k] for k in ('port', 'pid', 'instance_id', 'token')}
    assert state['device'] is None and state['device_generation'] == 1
    for name in dashboards.BRIDGE_DASHBOARD_TYPES:
        assert dashboards.get_managers()[name] is not old[name]
    assert dashboards.get_managers()['serial'] is old['serial']
    assert dashboards.get_managers()['rtt'].get_history() == []
    assert not (runtime.runtime_dir(A) / 'endpoint.json').exists()
    assert json.loads((runtime.runtime_dir(B) / 'endpoint.json').read_text())['port'] == 8765
    with runtime.runtime_lock('owner.lock', A):
        pass
    with pytest.raises(runtime.RuntimeErrorResponse):
        with runtime.runtime_lock('owner.lock', B):
            pass
    assert client.post('/api/runtime/select', json={'port': 'COM1'}).status_code == 200
    assert state['device_generation'] == 2


def test_occupied_destination_keeps_current_device_and_data(window):
    client, control, device, state = window
    old = dashboards.get_managers()['rtt']
    with runtime.runtime_lock('owner.lock', B):
        response = client.post('/api/runtime/select', json={'port': 'COM2'})
    assert response.status_code == 409
    assert control.info['probe_id'] == A and state['device'] is device
    assert dashboards.get_managers()['rtt'] is old
    device.close.assert_not_called()


@pytest.mark.parametrize('busy', ['sdk', 'uart', 'job', 'views', 'operation'])
def test_shared_work_cannot_be_retargeted(window, busy):
    client, control, device, state = window
    if busy in ('sdk', 'uart'):
        control.sessions['peer'] = Session(state['project_root'], None, scope='uart' if busy == 'uart' else 'target')
    elif busy == 'job':
        control.jobs.jobs['job'] = {'state': 'running', 'job_id': 'job'}
    elif busy == 'views':
        control.views = {str(i): {'expires': float('inf')} for i in range(2)}
    else:
        client.portal.call(control.operation_lock.acquire)
    try:
        assert client.post('/api/runtime/select', json={'port': 'COM2'}).status_code == 409
        device.close.assert_not_called()
        assert control.info['probe_id'] == A
    finally:
        control.jobs.jobs.clear()
        control.views.clear()
        if busy == 'operation':
            control.operation_lock.release()


def test_connect_failure_leaves_new_selection_disconnected_not_old_target(window, monkeypatch):
    client, control, device, state = window
    monkeypatch.setattr('mklink.connect', Mock(side_effect=RuntimeError('USB open failed')))
    response = client.post('/api/runtime/select', json={'port': 'COM2', 'connect': {}})
    assert response.status_code == 500 and 'USB open failed' in response.text
    assert control.info['probe_id'] == B and state['device'] is None
    assert client.get('/api/device/status').json()['device_generation'] == 1
    device.close.assert_called_once()


def test_expired_client_cannot_attach_after_backend_moves(window):
    client, control, device, state = window
    assert client.post('/api/runtime/select', json={'port': 'COM2'}).status_code == 200
    result = client.post('/_runtime/attach', json={'scope': 'uart', 'probe_id': A})
    assert result.status_code == 409 and not control.sessions


def test_live_capture_is_stopped_before_old_device_is_closed(window):
    from mklink.remote.api import acquire_dashboard_resources
    client, control, device, state = window
    rtt = dashboards.get_managers()['rtt']
    rtt._running = True
    acquire_dashboard_resources(state, 'rtt')
    device.close.side_effect = lambda: (
        pytest.fail('Capture still running during close') if rtt.running else None)
    assert client.post('/api/runtime/select', json={'port': 'COM2'}).status_code == 200
    assert not rtt.running and state['resource_manager'].get_status() == {}


def test_unknown_job_request_is_retained_without_replay_on_new_probe(window):
    client, control, device, state = window
    job = {'job_id': 'old', 'request_id': 'uncertain-request', 'fingerprint': 'same',
           'state': 'unknown', 'started': 1, 'probe_id': A, 'action': 'erase'}
    control.jobs.jobs['old'] = job
    assert client.post('/api/runtime/select', json={'port': 'COM2'}).status_code == 200
    assert control.jobs._previous('uncertain-request', 'same') == job
    stored = json.loads(control.jobs.path.read_text(encoding='utf-8'))
    assert stored[0]['state'] == 'unknown' and stored[0]['probe_id'] == A


def test_disconnect_releases_physical_ownership_but_not_backend(window):
    client, control, device, state = window
    assert client.post('/api/device/disconnect').status_code == 200
    assert control.info['probe_id'] == 'lobby'
    assert control.info['pid'] == 123 and control.info['port'] == 8765
    assert not (runtime.runtime_dir(A) / 'endpoint.json').exists()
    with runtime.runtime_lock('owner.lock', A):
        pass
    assert state['last_device_connection']['port'] == 'COM1'


def test_desktop_lease_and_presentation_socket_are_one_window(window):
    client, control, device, state = window
    client.post('/api/runtime/control/view', json={'client_id': 'desktop-parent'})
    with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/page?presentation=1',
                                  headers={'X-MKLink-View-Owner': 'desktop-parent'}) as socket:
        assert socket.receive_json()['registered']
        assert control.window_count == 1
        status = client.get('/api/runtime/control/status').json()
        assert len(status['clients']) == 1
        assert client.post('/api/runtime/select', json={'port': 'COM2'}).status_code == 200


def test_old_binary_subscription_ends_on_switch(window):
    client, control, device, state = window
    with client.websocket_connect('ws://127.0.0.1:8765/ws/streams/superwatch') as socket:
        socket.receive_bytes()  # subscription readiness / metadata
        assert client.post('/api/runtime/select', json={'port': 'COM2'}).status_code == 200
        for _ in range(4):
            message = socket.receive()
            if message['type'] == 'websocket.close':
                assert message['code'] == 1012
                break
        else:
            pytest.fail('Old target subscription survived the switch')


def test_two_pages_behind_one_proxy_still_block_switching(window):
    client, control, device, state = window
    client.post('/api/runtime/control/view', json={'client_id': 'desktop-parent'})
    headers = {'X-MKLink-View-Owner': 'desktop-parent'}
    with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/one', headers=headers) as first:
        assert first.receive_json()['registered']
        with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/two', headers=headers) as second:
            assert second.receive_json()['registered']
            assert control.window_count == 2
            assert client.post('/api/runtime/select', json={'port': 'COM2'}).status_code == 409
            device.close.assert_not_called()
