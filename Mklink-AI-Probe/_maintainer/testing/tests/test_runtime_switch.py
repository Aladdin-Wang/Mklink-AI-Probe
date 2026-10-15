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


@pytest.mark.parametrize('stale_connected', [False, True])
@pytest.mark.parametrize('replacement_port', ['COM2', 'COM1'])
def test_auto_connect_after_unplug_switches_to_unique_replacement(window, monkeypatch, tmp_path,
                                                                stale_connected, replacement_port):
    client, control, device, state = window
    device.connected = stale_connected  # Enumeration can precede transport failure.
    monkeypatch.setattr(probes, 'inventory', lambda: [
        {'probe_id': B, 'port': replacement_port, 'alias': ''}])
    state['last_device_connection'] = {'port': 'COM99', 'mcu': 'old-target'}
    control.sessions['old-target'] = Session(state['project_root'], None)
    control.sessions['uart'] = Session(state['project_root'], None, scope='uart')
    replacement, _ = _connected_symbol_device(tmp_path)
    replacement.port = replacement_port
    connect = Mock(return_value=replacement)
    monkeypatch.setattr('mklink.connect', connect)

    response = client.post('/api/runtime/select', json={'connect': {'restore_last': True}})

    assert response.status_code == 200, response.text
    assert response.json()['switched'] and response.json()['connection']['port'] == replacement_port
    assert control.info['probe_id'] == B and state['device'] is replacement
    assert control.info['port'] == 8765 and control.info['instance_id'] == 'same-instance'
    assert state['device_generation'] == 1 and set(control.sessions) == {'uart'}
    assert connect.call_args.kwargs['port'] == replacement_port
    assert connect.call_args.kwargs['mcu'] is None
    device.close.assert_called_once()


@pytest.mark.parametrize('candidates', [[], [B, 'usb-' + 'd' * 24]])
def test_auto_connect_missing_probe_requires_one_candidate(window, monkeypatch, candidates):
    client, control, device, state = window
    monkeypatch.setattr(probes, 'inventory', lambda: [
        {'probe_id': probe, 'port': f'COM{i + 2}', 'alias': ''}
        for i, probe in enumerate(candidates)])
    response = client.post('/api/runtime/select', json={'connect': {'restore_last': True}})
    assert response.status_code == 409
    assert ('Multiple probes' if candidates else 'No supported probe') in response.text
    assert control.info['probe_id'] == A and state['device'] is device
    device.close.assert_not_called()


def test_auto_connect_missing_probe_does_not_take_occupied_replacement(window, monkeypatch):
    client, control, device, state = window
    monkeypatch.setattr(probes, 'inventory', lambda: [{'probe_id': B, 'port': 'COM2', 'alias': ''}])
    with runtime.runtime_lock('owner.lock', B):
        response = client.post('/api/runtime/select', json={'connect': {}})
    assert response.status_code == 409
    assert control.info['probe_id'] == A and state['device'] is device
    device.close.assert_not_called()


def test_selection_without_connect_does_not_replace_missing_binding(window, monkeypatch):
    client, control, device, state = window
    monkeypatch.setattr(probes, 'inventory', lambda: [{'probe_id': B, 'port': 'COM2', 'alias': ''}])
    assert client.post('/api/runtime/select', json={}).json() == {'same_runtime': True}
    assert client.post('/api/device/connect', json={}).status_code == 409
    assert control.info['probe_id'] == A
    device.close.assert_not_called()


def test_auto_connect_keeps_present_binding_with_multiple_probes(window):
    client, control, device, state = window
    response = client.post('/api/runtime/select', json={'connect': {'restore_last': True}})
    assert response.status_code == 200 and response.json() == {'same_runtime': True}
    assert control.info['probe_id'] == A and state['device'] is device
    device.close.assert_not_called()


@pytest.mark.parametrize('busy', ['sdk', 'uart', 'views'])
def test_explicit_switch_retires_target_clients_and_preserves_uart(window, busy):
    client, control, device, state = window
    if busy in ('sdk', 'uart'):
        control.sessions['peer'] = Session(state['project_root'], None, scope='uart' if busy == 'uart' else 'target')
    else:
        control.views = {str(i): {'expires': float('inf')} for i in range(2)}
    assert client.post('/api/runtime/select', json={'port': 'COM2'}).status_code == 200
    device.close.assert_called_once()
    assert control.info['probe_id'] == B
    assert ('peer' in control.sessions) == (busy == 'uart')


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


def test_two_pages_behind_one_proxy_follow_explicit_switch(window):
    client, control, device, state = window
    client.post('/api/runtime/control/view', json={'client_id': 'desktop-parent'})
    headers = {'X-MKLink-View-Owner': 'desktop-parent'}
    with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/one', headers=headers) as first:
        assert first.receive_json()['registered']
        with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/two', headers=headers) as second:
            assert second.receive_json()['registered']
            assert control.window_count == 2
            assert client.post('/api/runtime/select', json={'port': 'COM2'}).status_code == 200
            device.close.assert_called_once()


@pytest.mark.parametrize('endpoint,body', [
    ('/api/device/disconnect', {}),
    ('/api/runtime/control/release-device', {'confirm': True}),
    ('/api/runtime/select', {'port': 'COM2'}),
])
def test_lifecycle_stops_shared_capture_and_revokes_old_target_sessions(window, endpoint, body):
    from mklink.remote.api import acquire_dashboard_resources
    client, control, device, state = window
    control.sessions['target'] = Session(state['project_root'], None, streams={'superwatch'})
    control.sessions['uart'] = Session(state['project_root'], None, scope='uart', streams={'serial'})
    control.created_streams.update(superwatch='target', serial='uart')
    control.views = {str(i): {'expires': float('inf')} for i in range(2)}
    manager = dashboards.get_managers()['superwatch']; manager._running = True
    acquire_dashboard_resources(state, 'superwatch')
    device.close.side_effect = lambda: pytest.fail('worker not stopped') if manager.running else None
    response = client.post(endpoint, json=body)
    assert response.status_code == 200, response.text
    assert not manager.running and state['device'] is None
    assert state['device_generation'] == 1
    assert set(control.sessions) == {'uart'} and control.created_streams == {'serial': 'uart'}
    assert client.post('/_runtime/call', json={'session_id': 'target', 'capability': 'write_memory',
        'arguments': {'address':'0x20000020','data_hex':'01'}}).status_code == 409
    device.close.assert_called_once()


@pytest.mark.parametrize('waiting', ['operation', 'job'])
def test_switch_waits_for_admitted_work_and_blocks_new_target_work(window, waiting):
    import asyncio
    import httpx
    client, control, device, state = window
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def work():
            started.set(); await release.wait()
            assert state['device'] is device
        if waiting == 'operation':
            worker = asyncio.create_task(control.run_operation('/api/device/read-memory', work))
        else:
            control.jobs.jobs['job'] = dict(state='running',job_id='job',started=1,request_id='once')
            async def job():
                await work()
                control.jobs.jobs['job']['state'] = 'succeeded'
            worker = asyncio.create_task(job())
        await started.wait()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control.app),
                base_url='http://127.0.0.1:8765',headers={'X-Auth-Token':'test'}) as http:
            switch = asyncio.create_task(http.post('/api/runtime/select',json={'port':'COM2'}))
            for _ in range(100):
                if control.lifecycle_pending: break
                await asyncio.sleep(.001)
            assert control.lifecycle_pending and not switch.done()
            device.close.assert_not_called()
            from fastapi import HTTPException
            with pytest.raises(HTTPException,match='connection is changing'):
                await control.run_operation('/api/device/write-memory',work)
            release.set(); await worker
            response = await switch
            assert response.status_code == 200, response.text
            assert control.info['probe_id'] == B and not control.lifecycle_pending
    client.portal.call(scenario)


def test_cancelled_lifecycle_request_still_drains_before_releasing_device(window):
    import asyncio
    client, control, device, state = window
    async def scenario():
        await control.operation_lock.acquire()
        transitioned=[]
        async def operation(): transitioned.append(True)
        task=asyncio.create_task(control.run_lifecycle('/api/device/disconnect',operation))
        await asyncio.sleep(0)
        task.cancel(); await asyncio.sleep(0)
        assert control.lifecycle_pending and not transitioned
        control.operation_lock.release()
        with pytest.raises(asyncio.CancelledError): await task
        assert transitioned == [True] and not control.lifecycle_pending
    client.portal.call(scenario)


@pytest.fixture
def ipc(window, monkeypatch):
    client, control, device, state = window
    def request(info, method, path, payload=None, **kwargs):
        response = client.request(method,path,json=payload)
        if response.status_code >= 400:
            raise runtime.RuntimeErrorResponse(response.text,status_code=response.status_code)
        return response.json()
    monkeypatch.setattr(runtime,'request',request)
    return window


def test_sdk_explicit_selection_switches_same_backend_and_disconnects(ipc, monkeypatch, tmp_path):
    client, control, device, state = ipc
    sdk=runtime.RuntimeClient(info=dict(control.info),project_root=state['project_root'])
    sdk.connect(probe=A)
    old_session=sdk.session_id
    replacement,_ = _connected_symbol_device(tmp_path)
    replacement.port='COM2'; replacement.close=Mock()
    monkeypatch.setattr('mklink.connect',lambda **kw: replacement)
    try:
        sdk.connect(probe=B)
        assert control.info['probe_id']==B and sdk.info['port']==8765
        assert sdk.session_id != old_session and old_session not in control.sessions
        device.close.assert_called_once()
        result=sdk.disconnect()
        assert result['device_closed'] and control.info['probe_id']=='lobby'
        replacement.close.assert_called_once()
    finally: sdk.close()


def test_mcp_disconnect_is_physical_but_detach_only_leaves_session(ipc, monkeypatch):
    import asyncio
    from fastmcp import Client
    from mklink import runtime_mcp
    client, control, device, state = ipc
    monkeypatch.setattr(runtime_mcp,'RuntimeClient',lambda **kw: runtime.RuntimeClient(info=dict(control.info),**kw))
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect',{'probe':A})
            await mcp.call_tool('detach')
            device.close.assert_not_called()
            await mcp.call_tool('connect',{'probe':A})
            result=await mcp.call_tool('disconnect')
            assert result.data['device_closed']
            assert control.info['probe_id']=='lobby' and not control.target_sessions
            device.close.assert_called_once()
    asyncio.run(scenario())


def test_stale_remote_identity_cannot_write_after_switch(window):
    client, control, device, state = window
    assert client.post('/api/runtime/select',json={'port':'COM2'}).status_code==200
    response=client.post('/api/device/write-memory',headers={'X-MKLink-Probe':A},
        json={'address':'0x20000000','data_hex':'01'})
    assert response.status_code==409 and 'connection changed' in response.text



def test_lifecycle_rechecks_async_job_created_by_draining_operation(window):
    import asyncio
    client,control,device,state=window
    async def scenario():
        await control.operation_lock.acquire()
        transitioned=[]
        async def change(): transitioned.append(True)
        task=asyncio.create_task(control.run_lifecycle('/api/device/disconnect',change))
        await asyncio.sleep(.01)
        control.jobs.jobs['later']={'state':'running','job_id':'later'}
        control.operation_lock.release()
        await asyncio.sleep(.04)
        assert not transitioned and not task.done()
        control.jobs.jobs['later']['state']='succeeded'
        await task
        assert transitioned==[True] and not control.operation_lock.locked()
    client.portal.call(scenario)



def test_slow_old_request_body_cannot_cross_completed_switch(window):
    import asyncio
    import httpx
    client,control,device,state=window
    async def scenario():
        receiving,release=asyncio.Event(),asyncio.Event()
        async def body():
            receiving.set(); await release.wait()
            yield b'{"address":"0x20000020","data_hex":"01"}'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control.app),
                base_url='http://127.0.0.1:8765',headers={'X-Auth-Token':'test'}) as http:
            old=asyncio.create_task(http.post('/api/device/write-memory',content=body(),
                headers={'X-MKLink-Probe':A,'Content-Type':'application/json'}))
            await receiving.wait()
            assert (await http.post('/api/runtime/select',json={'port':'COM2'})).status_code==200
            release.set()
            response=await old
            assert response.status_code==409 and 'connection changed' in response.text
    client.portal.call(scenario)
