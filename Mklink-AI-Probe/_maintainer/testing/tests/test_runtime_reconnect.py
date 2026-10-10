"""Explicit recovery never replays work or chooses a different physical probe."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from mklink import runtime as transport
from mklink.runtime_api import Session, install_runtime
from mklink.remote.api import create_app
from test_remote_api import _connected_symbol_device
from test_shared_runtime import runtime, attach


@pytest.mark.parametrize('status', [None, 500, 502, 503, 504])
def test_transient_heartbeat_failure_keeps_existing_lease(monkeypatch, runtime, status):
    client, control, calls, _, _ = runtime
    session = attach(client)
    renewed = []
    class Stop:
        def wait(self, seconds):
            return bool(renewed)
    attempts = []
    def request(info, method, path, payload, **options):
        assert method == 'POST' and path == '/_runtime/heartbeat'
        assert payload == {'session_id': session}
        assert options['timeout'] < 4  # Leave room to retry inside the five-second lease.
        attempts.append(path)
        if len(attempts) == 1:
            raise transport.RuntimeErrorResponse('temporary failure', status_code=status)
        response = client.post(path, json=payload)
        assert response.status_code == 200
        renewed.append(session)
        return response.json()
    monkeypatch.setattr(transport, 'request', request)
    transport.RuntimeClient()._renew(Stop(), session, control.info)
    assert len(attempts) == 2 and renewed == [session]
    assert session in control.sessions and calls == []


@pytest.mark.parametrize('status,expected', [(None, 3), (503, 3), (401, 1), (403, 1), (409, 1), (422, 1)])
def test_heartbeat_failure_is_bounded_and_never_reattaches(monkeypatch, status, expected):
    attempts = []
    class Stop:
        def wait(self, seconds):
            assert len(attempts) <= 3
            return False
    def request(info, method, path, payload, **options):
        attempts.append(path)
        assert path == '/_runtime/heartbeat' and payload == {'session_id': 'old'}
        raise transport.RuntimeErrorResponse('failed', status_code=status)
    monkeypatch.setattr(transport, 'request', request)
    transport.RuntimeClient()._renew(Stop(), 'old', {'port': 8765})
    assert len(attempts) == expected


def test_expired_lease_after_transient_heartbeat_failure_is_not_resurrected(monkeypatch, runtime):
    client, control, calls, _, _ = runtime
    session = attach(client)
    attempts = []
    class Stop:
        def wait(self, seconds):
            assert len(attempts) < 3
            return False
    def request(info, method, path, payload, **options):
        attempts.append(path)
        assert path == '/_runtime/heartbeat'
        if len(attempts) == 1:
            control.sessions[session].expires = 0
            raise transport.RuntimeErrorResponse('response timed out')
        response = client.post(path, json=payload)
        assert response.status_code == 409
        raise transport.RuntimeErrorResponse(response.text, status_code=409)
    monkeypatch.setattr(transport, 'request', request)
    transport.RuntimeClient()._renew(Stop(), session, control.info)
    assert len(attempts) == 2 and session not in control.sessions and not calls


@pytest.mark.parametrize('failure', ['offline', 'replaced'])
def test_explicit_connect_rediscovers_bound_runtime_without_replaying_work(monkeypatch, failure):
    old = dict(port=8765, token='old', instance_id='old', probe_id='usb-' + '1' * 24)
    new = {**old, 'port': 8767, 'token': 'new', 'instance_id': 'new'}
    calls, discoveries = [], []
    def request(info, method, path, body=None, **options):
        calls.append((dict(info), path, body))
        if path == '/_runtime/status':
            if failure == 'offline':
                raise transport.RuntimeErrorResponse('Shared runtime unavailable')
            return {'instance_id': 'another-instance'}
        if path == '/_runtime/attach':
            assert info == new and body['session_id'] is None
            return {'session_id': 'new-session'}
        if path == '/_runtime/call':
            raise transport.RuntimeErrorResponse('unknown write outcome')
        return {}
    monkeypatch.setattr(transport, 'request', request)
    monkeypatch.setattr(transport, 'ensure_runtime', lambda **kwargs: discoveries.append(kwargs) or new)
    client = transport.RuntimeClient(info=old, project_root='chosen-project')
    client.session_id = 'old-session'
    with pytest.raises(transport.RuntimeErrorResponse, match='unknown write'):
        client.call('write_memory', {'address': '0x20000000', 'data_hex': '01'})
    assert not discoveries and len(calls) == 1
    try:
        assert client.connect()['session_id'] == 'new-session'
        assert discoveries == [dict(project_root='chosen-project', probe=old['probe_id'], allow_lobby=False)]
        assert [path for _, path, _ in calls].count('/_runtime/call') == 1
    finally:
        client.close()


def test_missing_bound_probe_cannot_attach_to_only_remaining_probe(monkeypatch):
    client = transport.RuntimeClient(info={'port': 8765, 'probe_id': 'usb-' + '1' * 24})
    client.session_id = 'old-session'
    monkeypatch.setattr(transport, 'request', Mock(side_effect=transport.RuntimeErrorResponse('offline')))
    ensure = Mock(side_effect=transport.RuntimeErrorResponse('Selected probe is missing'))
    monkeypatch.setattr(transport, 'ensure_runtime', ensure)
    with pytest.raises(transport.RuntimeErrorResponse, match='missing'):
        client.connect()
    assert ensure.call_args.kwargs['probe'] == client.info['probe_id']
    assert client.session_id is None


@pytest.mark.parametrize('scope', ['target', 'uart'])
@pytest.mark.parametrize('removed', [False, True])
def test_disconnected_target_stops_renewing_only_target_sessions(runtime, scope, removed):
    client, control, _, _, app = runtime
    session = client.post('/_runtime/attach', json={'scope': scope}).json()['session_id']
    app.state.mklink_state['device'].connected = False
    if removed:
        app.state.mklink_state['device'] = None
    result = client.post('/_runtime/heartbeat', json={'session_id': session})
    assert result.status_code == (409 if scope == 'target' else 200)
    assert (session in control.sessions) == (scope == 'uart')


def test_live_shared_disconnect_exposes_owners_without_releasing_device(runtime):
    client, control, calls, _, _ = runtime
    session = attach(client)
    result = client.post('/api/device/disconnect')
    assert result.status_code == 409
    detail = result.json()['detail']
    assert detail['reason'] == 'shared_clients_attached'
    assert detail['clients'][0]['id'] == control.sessions[session].public_id
    assert session not in str(detail) and not calls


def test_temporary_cdc_release_during_admitted_operation_does_not_evict_client(runtime):
    client, control, _, _, app = runtime
    session = attach(client)
    client.portal.call(control.operation_lock.acquire)
    try:
        app.state.mklink_state['device'].connected = False
        assert client.post('/_runtime/heartbeat', json={'session_id': session}).status_code == 200
        assert session in control.sessions
    finally:
        client.portal.call(control.operation_lock.release)
    assert client.post('/_runtime/heartbeat', json={'session_id': session}).status_code == 409


@pytest.mark.parametrize('entry', ['gui', 'mcp'])
@pytest.mark.parametrize('port_changed', [False, True, 'already_closed'])
def test_hotplug_closes_old_handle_revokes_old_target_sessions_then_connects_same_probe(
        monkeypatch, tmp_path, entry, port_changed):
    replacement, _ = _connected_symbol_device(tmp_path)
    replacement.port = 'COM229' if port_changed else 'COM228'
    events = []
    stale = SimpleNamespace(connected=port_changed, port='COM228',
                            close=lambda: events.append('close-old'))
    app = create_app(auth_token=None, project_root=str(tmp_path))
    info = dict(port=8765, token='test-token', instance_id='test-instance', probe_id='usb-' + '1' * 24)
    control = install_runtime(app, info)
    state = app.state.mklink_state
    state['device'] = None if port_changed == 'already_closed' else stale
    state['dispatcher'] = object()
    selected = dict(probe_id=info['probe_id'], port=replacement.port)
    monkeypatch.setattr('mklink.probes.inventory', lambda: [selected])
    monkeypatch.setattr('mklink.probes.select_probe', lambda *a, **k: selected)
    def connect(**kwargs):
        assert events == ([] if port_changed == 'already_closed' else ['close-old'])
        assert kwargs['port'] == replacement.port
        assert 'old-target' not in control.sessions
        events.append('open-new')
        return replacement
    monkeypatch.setattr('mklink.connect', connect)
    monkeypatch.setattr('mklink.device.initialize_target', lambda *a, **k: None)
    control.sessions['old-target'] = Session(str(tmp_path), None)
    control.sessions['independent-uart'] = Session(str(tmp_path), None, scope='uart')
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': info['token']}) as client:
        path = '/api/device/connect' if entry == 'gui' else '/_runtime/attach'
        result = client.post(path, json={'port': replacement.port, **({'session_id': 'old-target'} if entry == 'mcp' else {})})
        assert result.status_code == 200, result.text
        assert events == (['open-new'] if port_changed == 'already_closed' else ['close-old', 'open-new'])
        assert state['device'] is replacement
        assert 'old-target' not in control.sessions and 'independent-uart' in control.sessions
        assert client.post('/_runtime/call', json={'session_id': 'old-target', 'capability': 'read_memory',
                                                  'arguments': {'address': '0x20000000', 'size': 4}}).status_code == 409
        if entry == 'mcp':
            assert result.json()['session_id'] != 'old-target'


@pytest.mark.parametrize('failure', ['lock', 'open'])
def test_command_port_failure_reports_actionable_reason_without_fallback(monkeypatch, tmp_path, failure):
    from mklink.bridge import MKLinkSerialBridge
    from mklink.device import Device, DeviceNotConnectedError
    import serial
    bridge = MKLinkSerialBridge('COM228')
    monkeypatch.setattr(bridge._port_lock, 'acquire', lambda: failure != 'lock')
    monkeypatch.setattr('mklink.probes.require_runtime_port', lambda _: None)
    serial_factory = Mock(side_effect=serial.SerialException('Access is denied'))
    monkeypatch.setattr('mklink.bridge.serial.Serial', serial_factory)
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge', lambda port: bridge)
    with pytest.raises(DeviceNotConnectedError, match='owned by another process' if failure == 'lock' else 'Access is denied'):
        Device(port='COM228', project_root=str(tmp_path))._connect()
    assert serial_factory.call_count == (0 if failure == 'lock' else 1)
