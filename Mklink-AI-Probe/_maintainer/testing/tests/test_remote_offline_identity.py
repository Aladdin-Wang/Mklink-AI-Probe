"""Remote offline deployment must never guess a MICROKEEN drive by label."""
from types import SimpleNamespace
from pathlib import Path
import pytest
from mklink.remote.dispatcher import dispatch_capability
from mklink.remote.capabilities import CapabilityUnavailableError, protocol_capabilities
from test_remote_upstream_integration import _offline_config


@pytest.fixture
def deployment(monkeypatch):
    calls = []
    monkeypatch.setattr('mklink.remote.dispatcher.capability_available', lambda _: True)
    monkeypatch.setattr('mklink.discovery.find_microkeen_disk', lambda: pytest.fail('label fallback'))
    monkeypatch.setenv('MKLINK_MICROKEEN_DISK', 'Z:\\')
    monkeypatch.setattr('mklink.offline_download.deploy_offline_bundle',
                        lambda config, disk, **kwargs: calls.append((disk, kwargs)) or {'deployed': True})
    uploads = SimpleNamespace(resolve=lambda reference: calls.append(reference) or Path(reference))
    params = {'confirm': True, 'config': _offline_config(),
              'firmware_files': {'boot': 'opaque-boot', 'app': 'opaque-app'},
              'algorithm_files': {'internal': 'opaque-algorithm'}}
    return params, uploads, calls


@pytest.mark.parametrize('binding,reason', [(None, 'probe-identity-required'), ('lobby', 'probe-identity-unavailable')])
def test_unbound_or_lobby_agent_cannot_resolve_uploads_or_touch_disk(monkeypatch, deployment, binding, reason):
    params, uploads, calls = deployment
    monkeypatch.setattr('mklink.probes._bound_probe', binding)
    monkeypatch.setattr('mklink.probe_volumes.volume_inventory', lambda: pytest.fail('disk enumeration'))
    with pytest.raises(CapabilityUnavailableError) as error:
        dispatch_capability('offline.deploy', params, upload_manager=uploads)
    assert error.value.data['reason'] == reason and calls == []


@pytest.mark.parametrize('failure', ['missing', 'duplicate', 'unstable', 'drive-letter'])
def test_identity_failure_never_falls_back_or_deploys(monkeypatch, deployment, failure):
    params, uploads, calls = deployment
    monkeypatch.setattr('mklink.probes._bound_probe', 'selected')
    probe = {'identity_stable': failure != 'unstable', 'vid': 1, 'pid': 2, 'serial_number': 'selected'}
    monkeypatch.setattr('mklink.probes.select_probe', lambda _: probe)
    row = {'usb_identity': (1, 2, 'selected'), 'root': '\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\', 'drive': 'H:'}
    rows = [] if failure == 'missing' else [row, row] if failure == 'duplicate' else [row]
    if failure == 'drive-letter': row['root'] = 'H:\\'
    monkeypatch.setattr('mklink.probe_volumes.volume_inventory', lambda: rows)
    with pytest.raises(CapabilityUnavailableError) as error:
        dispatch_capability('offline.deploy', params, upload_manager=uploads)
    assert error.value.data['reason'] == 'probe-identity-unavailable' and calls == []


def test_selected_identity_wins_over_first_drive_and_preserves_opaque_uploads(monkeypatch, deployment):
    params, uploads, calls = deployment
    monkeypatch.setattr('mklink.probes._bound_probe', 'selected')
    def select(probe_id):
        assert probe_id == 'selected'
        return {'identity_stable': True, 'vid': 1, 'pid': 2, 'serial_number': 'SELECTED'}
    monkeypatch.setattr('mklink.probes.select_probe', select)
    root = '\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\'
    monkeypatch.setattr('mklink.probe_volumes.volume_inventory', lambda: [
        {'usb_identity': (1, 2, 'neighbor'), 'root': 'wrong', 'drive': 'G:'},
        {'usb_identity': (1, 2, 'selected'), 'root': root, 'drive': 'H:'}])
    assert dispatch_capability('offline.deploy', params, upload_manager=uploads) == {'deployed': True}
    assert calls[:3] == ['opaque-boot', 'opaque-app', 'opaque-algorithm']
    assert calls[-1][0] == root
    assert calls[-1][1]['firmware_sources']['app'] == Path('opaque-app')
    assert 'identity-bound' in protocol_capabilities()['flash.offline'].detail


def test_authenticated_socket_receives_identity_refusal_and_preview_still_works(monkeypatch, deployment):
    import asyncio
    import json
    import websockets
    from test_remote_capabilities import _running_agent, _request
    from mklink.remote.protocol import PROTOCOL_VERSION
    params, uploads, calls = deployment
    monkeypatch.setattr('mklink.probes._bound_probe', None)
    async def scenario():
        async with _running_agent(
            capability_provider=protocol_capabilities,
            request_dispatcher=lambda op, args, context: dispatch_capability(
                op, args, context, upload_manager=uploads),
        ) as agent:
            async with websockets.connect(f'ws://127.0.0.1:{agent.port}') as socket:
                await socket.send(_request('system.handshake', {'protocol_version': PROTOCOL_VERSION}))
                handshake = json.loads(await socket.recv())['result']
                assert 'identity-bound' in handshake['capabilities']['flash.offline']['detail']
                await socket.send(_request('offline.deploy', params, request_id=2))
                error = json.loads(await socket.recv())['error']
                assert error['code'] == -32004 and error['data']['reason'] == 'probe-identity-required'
                await socket.send(_request('offline.preview', {'config': params['config']}, request_id=3))
                assert json.loads(await socket.recv())['result']['model'] == 'V4'
        assert not agent.ready
    asyncio.run(scenario())
    assert calls == []
