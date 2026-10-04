import asyncio
import json
import socket
from unittest.mock import Mock
import pytest
import websockets
from fastapi.testclient import TestClient
from mklink.remote.api import create_app
from mklink.runtime_api import install_runtime
from mklink import runtime as sdk
from test_remote_api import _connected_symbol_device
from test_remote_capabilities import _request
from test_shared_runtime import attach


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('MKLINK_SITE_AGENT_ENABLED', '0')
    app = create_app(auth_token=None, project_root=str(tmp_path))
    device, _ = _connected_symbol_device(tmp_path)
    device.read_memory = Mock(return_value=bytes(4))
    app.state.mklink_state['device'] = device
    probe_id = 'usb-'+'a'*24
    info = {'port': 8765, 'token': 'local-secret', 'instance_id': 'service-test', 'probe_id': probe_id}
    control = install_runtime(app, info)
    monkeypatch.setattr('mklink.probes.select_probe', lambda *a, **k: {'probe_id': probe_id, 'identity_stable': True, 'port': device.port})
    monkeypatch.setattr('mklink.probes.inventory', lambda: [{'probe_id': probe_id, 'identity_stable': True, 'port': device.port}])
    monkeypatch.setattr(sdk, 'ensure_runtime', lambda **k: pytest.fail('Embedded service started another backend'))
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'local-secret'}) as http:
        def request(info, method, path, payload=None, **kwargs):
            response = http.request(method, path, json=payload)
            if response.status_code >= 400:
                raise sdk.RuntimeErrorResponse(response.text, status_code=response.status_code)
            return response.json()
        monkeypatch.setattr(sdk, 'request', request)
        yield http, control, device, app.state.site_agent
        app.state.mklink_state['device'] = None


def free_port():
    with socket.socket() as value:
        value.bind(('127.0.0.1',0))
        return value.getsockname()[1]


def start(http, **changes):
    return http.post('/_runtime/remote-service', json={
        'enabled': True, 'host': '127.0.0.1', 'port': free_port(), 'token': 'remote-secret', **changes})


def test_start_stop_uses_shared_admission_and_keeps_local_client(service):
    http, control, device, controller = service
    gui = attach(http)
    response = start(http)
    assert response.status_code == 200, response.text
    status = response.json()
    assert status['ready'] and 'remote-secret' not in response.text
    async def scenario():
        async with websockets.connect('ws://127.0.0.1:'+str(status['port'])) as remote:
            async def rpc(method, params=None):
                await remote.send(_request(method, params))
                return json.loads(await remote.recv())
            assert 'result' in await rpc('system.handshake', {'protocol_version': '1.0', 'token': 'remote-secret'})
            assert (await rpc('agent.reconnect'))['result']['connected']
            assert (await rpc('memory.read', {'address': 0, 'size': 4}))['result'] == {'__bytes__':'AAAAAA=='}
            assert len(control.sessions) == 2
            response = await asyncio.to_thread(http.post, '/_runtime/remote-service/stop')
            assert response.status_code == 200, response.text
            await remote.wait_closed()
    asyncio.run(scenario())
    assert list(control.sessions) == [gui] and device.connected
    assert http.get('/api/device/status').json()['connected']
    assert not controller.status()['running']
    device.read_memory.assert_called_once_with(0,4)


def test_token_rotation_requires_stopped_listener_and_stays_private(service):
    http, _, _, _ = service
    token = http.post('/_runtime/remote-service/token', json={'confirm': True}).json()['token']
    assert token not in http.get('/_runtime/remote-service').text
    assert start(http).status_code == 200
    assert http.post('/_runtime/remote-service/token', json={'confirm': True}).status_code == 409
    assert http.post('/_runtime/remote-service/stop').status_code == 200
    assert http.post('/_runtime/remote-service/token', json={'confirm': True}).json()['token'] != token


@pytest.mark.parametrize('change', [{'port': True}, {'enabled': 'true'}, {'port': 0}, {'extra': 1}, {'host': '0.0.0.0'}, {'token': ''}])
def test_bad_configuration_does_not_start_listener(service, change):
    http, control, _, controller = service
    assert start(http, **change).status_code == 422
    assert not controller.status()['running'] and not control.sessions


def test_occupied_port_failure_does_not_stop_backend(service):
    http, _, device, controller = service
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1',0));occupied.listen()
        response = start(http, port=occupied.getsockname()[1])
    assert response.status_code == 503
    assert not controller.status()['running'] and device.connected
    assert http.get('/api/device/status').status_code == 200
    assert start(http).status_code == 200


def test_control_requires_local_runtime_authentication(service):
    http, _, _, _ = service
    assert http.post('/_runtime/remote-service/token', json={'confirm': True}, headers={'X-Auth-Token':'wrong'}).status_code == 401
    assert http.post('/_runtime/remote-service/stop', headers={'Origin':'http://untrusted.invalid'}).status_code == 403


def test_stop_waits_for_active_request_without_blocking_backend_health(service):
    import threading
    http, control, device, controller = service
    entered, release = threading.Event(), threading.Event()
    def read(address, size):
        entered.set()
        assert release.wait(5)
        return bytes(size)
    device.read_memory.side_effect = read
    gui = attach(http)
    status = start(http).json()
    async def scenario():
        async with websockets.connect('ws://127.0.0.1:'+str(status['port'])) as remote:
            async def rpc(method, params=None):
                await remote.send(_request(method, params))
                return json.loads(await remote.recv())
            await rpc('system.handshake', {'protocol_version':'1.0', 'token':'remote-secret'})
            assert (await rpc('agent.reconnect'))['result']['connected']
            await remote.send(_request('memory.read', {'address':0,'size':4}))
            assert await asyncio.to_thread(entered.wait, 2)
            stopping = asyncio.create_task(asyncio.to_thread(http.post, '/_runtime/remote-service/stop'))
            try:
                await asyncio.sleep(.05)
                assert not stopping.done()
                assert (await asyncio.to_thread(http.get,'/api/device/status')).status_code == 200
                assert device.connected and gui in control.sessions
            finally:
                release.set()
            assert (await asyncio.wait_for(stopping,3)).status_code == 200
            await remote.wait_closed()
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert list(control.sessions) == [gui]
    device.read_memory.assert_called_once_with(0,4)
