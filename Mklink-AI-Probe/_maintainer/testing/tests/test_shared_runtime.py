import asyncio
import base64
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from mklink.runtime_api import install_runtime
from mklink.remote.api import start_dashboard_manager, stop_dashboard_manager_transaction
from mklink.remote.resource_manager import ResourceManager


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    app = FastAPI()
    device = SimpleNamespace(connected=True, port="COM9", axf_status={"axf_path": str(tmp_path / "test.axf")})
    app.state.mklink_state = {"device": device, "project_root": str(tmp_path), "last_device_connection": {},
                             "resource_manager": ResourceManager()}
    calls = []
    managers = {name: SimpleNamespace(running=False) for name in ("rtt", "superwatch", "systemview")}
    monkeypatch.setattr("mklink.remote.dashboards.get_managers", lambda: managers)
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])

    @app.get("/api/device/status")
    async def status():
        return {"connected": True, "port": device.port, "axf": device.axf_status}

    @app.post("/api/device/disconnect")
    async def disconnect():
        calls.append("disconnect")
        return {"ok": True}

    @app.post("/api/device/read-memory")
    async def read(body: dict):
        calls.append("read")
        return {"data_hex": "00" * body["size"], 'data_base64': base64.b64encode(bytes(body['size'])).decode()}

    @app.post('/api/device/write-memory')
    async def write(body: dict):
        calls.append('write')
        return {'bytes_written': len(bytes.fromhex(body['data_hex'])), 'verified': body.get('verify', False)}

    @app.post("/api/dash/rtt/start")
    async def start(body: dict):
        def start_manager():
            calls.append("start")
            managers['rtt'].running = True
        status, _ = await start_dashboard_manager(app.state.mklink_state, 'rtt', managers['rtt'],
                                                start_manager)
        return {"status": status}

    @app.post("/api/dash/rtt/stop")
    async def stop():
        def stop_manager():
            calls.append("stop")
            managers['rtt'].running = False
        managers['rtt'].stop = stop_manager
        await stop_dashboard_manager_transaction(app.state.mklink_state, 'rtt', managers['rtt'])
        return {"status": "stopped"}

    @app.get("/api/dash/rtt/history")
    async def history():
        return {"points": [{"text": "shared"}]}

    info = {"port": 8765, "token": "test-secret", "instance_id": "test-instance"}
    control = install_runtime(app, info)
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Auth-Token": info["token"]}) as client:
        yield client, control, calls, managers, app


def attach(client):
    response = client.post("/_runtime/attach", json={})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def call(client, session, capability, arguments=None):
    return client.post("/_runtime/call", json={"session_id": session, "capability": capability, "arguments": arguments or {}})


def test_detach_never_closes_gui_device(runtime):
    client, control, calls, _, _ = runtime
    first, second = attach(client), attach(client)
    assert client.post("/api/device/disconnect").status_code == 409
    assert client.post("/_runtime/detach", json={"session_id": first}).json()["device_closed"] is False
    assert call(client, second, "device_status").json()["connected"]
    assert "disconnect" not in calls
    assert len(control.sessions) == 1


@pytest.mark.parametrize('change', ['generation', 'fingerprint'])
def test_session_rejects_same_path_symbol_revision_until_explicit_reattach(runtime, change):
    client, control, calls, _, app = runtime
    catalog = SimpleNamespace(generation=1, fingerprint=SimpleNamespace(sha256='old'))
    app.state.mklink_state['device'].symbol_catalog = catalog
    session = attach(client)
    assert call(client, session, 'device_status').status_code == 200
    if change == 'generation':
        catalog.generation += 1
    else:
        catalog.fingerprint.sha256 = 'new'
    for capability in ['device_status', 'read_memory']:
        arguments = {'address': '0x20000000', 'size': 4} if capability == 'read_memory' else {}
        response = call(client, session, capability, arguments)
        assert response.status_code == 409 and 'Symbols changed' in response.text
    response = client.post('/api/runtime/jobs/', json={
        'action': 'reset', 'request_id': 'stale-session', 'confirm': True, 'session_id': session})
    assert response.status_code == 409 and 'Symbols changed' in response.text
    assert calls == [] and not control.jobs.jobs
    response = client.post('/_runtime/attach', json={'session_id': session})
    assert response.status_code == 200 and response.json()['session_id'] == session
    assert call(client, session, 'read_memory', {'address': '0x20000000', 'size': 4}).status_code == 200


def test_internal_operation_retains_http_and_attach_exclusion_after_cancel(runtime):
    client, control, calls, _, _ = runtime
    entered, release = asyncio.Event(), asyncio.Event()
    async def worker():
        entered.set()
        await release.wait()
    async def begin():
        task = asyncio.create_task(control.run_operation('reload-file-sources', worker, configuration=True))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        return task
    task = client.portal.call(begin)
    try:
        assert control.operation_lock.locked()
        assert client.post('/_runtime/attach', json={}).status_code == 409
        assert client.post('/api/device/read-memory', json={'address': '0x20000000', 'size': 4}).status_code == 409
        assert calls == []
    finally:
        async def finish():
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        client.portal.call(finish)
    assert not control.operation_lock.locked()
    assert control.last_operation['path'] == 'reload-file-sources'
    assert client.post('/_runtime/attach', json={}).status_code == 200


def test_shared_capture_does_not_restart_or_steal(runtime):
    client, _, calls, managers, _ = runtime
    managers["rtt"].running = True  # started in GUI
    session = attach(client)
    assert call(client, session, "rtt_start").json()["reused"]
    assert call(client, session, "rtt_history").json()["points"]
    assert call(client, session, "read_memory", {"address": "0x20000000", "size": 4}).status_code == 409
    assert call(client, session, "rtt_stop").status_code == 409
    assert client.post("/api/dash/rtt/stop").status_code == 409
    assert client.post("/api/dash/rtt/pause").status_code == 409
    assert client.post("/api/dash/superwatch/start").status_code == 409
    assert client.post("/api/dash/rtt/start", json={}).status_code == 409
    assert calls == []


def test_stream_owner_cannot_stop_other_subscriber(runtime):
    client, _, calls, _, _ = runtime
    first, second = attach(client), attach(client)
    assert call(client, first, "rtt_start").status_code == 200
    assert call(client, second, "rtt_start").status_code == 200
    assert call(client, first, "rtt_stop").status_code == 409
    client.post("/_runtime/detach", json={"session_id": second})
    assert call(client, first, "rtt_stop").status_code == 200
    assert calls == ["start", "stop"]


def test_subscribe_cannot_join_a_capture_while_it_is_stopping(runtime):
    client, control, _, managers, _ = runtime
    session = attach(client)
    managers['rtt'].running = True
    client.portal.call(control.operation_lock.acquire)
    try:
        assert call(client, session, 'rtt_start').status_code == 409
        assert not control.sessions[session].streams
    finally:
        client.portal.call(control.operation_lock.release)


def test_auth_origin_and_project_binding(runtime, tmp_path):
    client, control, calls, _, _ = runtime
    assert client.get("/_runtime/status", headers={"X-Auth-Token": "bad"}).status_code == 401
    assert client.get("/_runtime/status", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/_runtime/status", headers={"Host": "evil.example"}).status_code == 403
    mismatch = client.post("/_runtime/attach", json={"project_root": str(tmp_path / "other")})
    assert mismatch.status_code == 409
    assert "stop this probe's backend explicitly" in mismatch.text
    assert not control.sessions and calls == []
    assert client.post("/_runtime/attach", json={"axf": str(tmp_path / "other.axf")}).status_code == 409
    assert calls == []


def test_read_limits_and_expired_client(runtime):
    client, control, calls, _, _ = runtime
    session = attach(client)
    assert call(client, session, "read_memory", {"address": "0xffffffff", "size": 4}).status_code == 422
    assert call(client, session, "read_memory", {"address": "0", "size": 4097}).status_code == 422
    assert call(client, session, "read_memory", {"address": "0", "size": 4}).json()["data_hex"] == "00000000"
    control.sessions[session].expires = 0
    assert call(client, session, "device_status").status_code == 409
    assert calls == ["read"]


def test_browser_cookie_bootstrap(runtime):
    client, _, _, _, _ = runtime
    client.headers.pop("X-Auth-Token")
    assert client.get("/_runtime/open").status_code == 200
    assert client.post("/_runtime/login", json={"token": "test-secret"}).status_code == 200
    assert client.get("/_runtime/status").status_code == 200
    assert client.post("/_runtime/login", json={"token": "bad"}).status_code == 401


def test_multiple_probes_cannot_run_unbound_disk_writes(runtime, monkeypatch):
    client, _, calls, _, _ = runtime
    monkeypatch.setattr('mklink.probes.inventory', lambda: [{'probe_id': 'one'}, {'probe_id': 'two'}])
    for path in ('/api/probe/firmware-upgrade', '/api/offline-download/deploy', '/api/offline-download/trigger'):
        assert client.post(path, json={}).status_code == 409
    assert calls == []


def test_online_flash_cannot_target_another_physical_probe(runtime, monkeypatch):
    client, _, calls, _, _ = runtime
    monkeypatch.setattr('mklink.probes.select_probe', lambda *_: {'serial_number': 'test-serial'})
    for path in ('/api/online-flash/jobs', '/api/online-flash/memory/read', '/api/online-flash/memory/read-stream'):
        assert client.post(path, json={'probe_id': 'other-serial'}).status_code == 409
    assert calls == []


def test_cancelled_worker_retains_admission():
    from mklink.runtime_api import settle

    async def scenario():
        started, release = threading.Event(), threading.Event()
        lock = asyncio.Lock()

        def hardware():
            started.set()
            release.wait(5)

        async def operation():
            async with lock:
                await settle(asyncio.create_task(asyncio.to_thread(hardware)))

        task = asyncio.create_task(operation())
        await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0.01)
        assert lock.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not lock.locked()

    asyncio.run(scenario())


def test_shared_runtime_binds_remote_controller_to_own_endpoint():
    from mklink.remote.embedded_agent import EmbeddedAgentSettings
    app = FastAPI()
    app.state.mklink_state = {'project_root': '.', 'device': None}
    app.state.site_agent = SimpleNamespace(settings=EmbeddedAgentSettings(enabled=True, token='test-secret'))
    install_runtime(app, {'port': 8765, 'token': 'test-secret', 'instance_id': 'test'})
    assert app.state.site_agent.settings.enabled is True
    assert app.state.site_agent.runtime_info is app.state.shared_runtime.info


def test_write_validation_and_capture_busy_never_reach_hardware(runtime):
    client, _, calls, managers, _ = runtime
    session = attach(client)
    assert client.post('/api/device/write-memory', json={'address':'0','data_hex':'zz'}).status_code == 422
    assert client.post('/api/dash/rtt/write', json={'data_hex':('a'*257).encode().hex()}).status_code == 422
    assert client.post('/api/dash/rtt/write', json={'data_hex':b'RTTView.stop()'.hex()}).status_code == 422
    for arguments in ({'address': '0xffffffff', 'data_hex': '0000'}, {'address': '0', 'data_hex': '0g'},
                      {'address': '0', 'data_hex': '0'}, {'address': '0', 'data_hex': ''}):
        assert call(client, session, 'write_memory', arguments).status_code == 422
    managers['superwatch'].running = True
    assert client.get('/api/dash/superwatch/inspect', params={'name':'test'}).status_code == 409
    assert call(client, session, 'write_memory', {'address':'0x20000000', 'data_hex':'0102'}).status_code == 409
    assert not calls
    managers['superwatch'].running = False
    assert call(client, session, 'write_memory', {'address':'0x20000000', 'data_hex':'0102'}).json()['bytes_written'] == 2
    assert calls == ['write']


def test_management_view_detach_stop_release_are_distinct(runtime):
    client, control, calls, managers, _ = runtime
    session = attach(client)
    assert call(client, session, 'rtt_start').status_code == 200
    base = '/api/runtime/control'
    client.post(base+'/view', json={'client_id':'test-window'})
    snapshot = client.get(base+'/status').json()
    assert sorted(c['kind'] for c in snapshot['clients']) == ['gui','mcp']
    assert session not in str(snapshot)  # Public handles are not session credentials.
    assert snapshot['last_operation']['path'] == '/api/dash/rtt/start'
    assert client.post(base+'/release-device', json={'confirm':True}).status_code == 409
    assert client.post(base+'/stop-acquisition', json={'stream':'rtt','confirm':True}).status_code == 409
    public_id = next(c['id'] for c in snapshot['clients'] if c['kind']=='mcp')
    assert client.post(base+'/detach-client', json={'client_id':public_id}).status_code == 422
    assert client.post(base+'/detach-client', json={'client_id':public_id,'confirm':True}).status_code == 200
    assert managers['rtt'].running
    assert call(client, session, 'device_status').status_code == 409
    assert client.post(base+'/release-device', json={'confirm':True}).status_code == 409
    assert client.post(base+'/stop-acquisition', json={'stream':'rtt','confirm':True}).status_code == 200
    assert client.post(base+'/release-device', json={'confirm':True}).status_code == 200
    assert calls == ['start','stop','disconnect']
    client.post(base+'/view', json={'client_id':'test-window','release':True})
    assert not control.views


def test_management_backend_stop_respects_other_windows(runtime):
    client, control, _, _, _ = runtime
    base = '/api/runtime/control'
    for name in ('one','two'):
        client.post(base+'/view', json={'client_id':name})
    assert client.post(base+'/stop-backend', json={'confirm':True}).status_code == 409
    control.views['two']['expires']=0
    assert client.post(base+'/stop-backend', json={'confirm':True}).status_code == 200


def test_hotplug_never_retargets_a_window_to_another_probe(runtime, monkeypatch):
    client, control, calls, _, app = runtime
    session = attach(client)
    control.info['probe_id']='usb-'+'1'*24
    # Original probe disappeared; another now owns its old COM number.
    monkeypatch.setattr('mklink.probes.inventory', lambda:[{'probe_id':'usb-'+'2'*24,'port':'COM9'}])
    assert call(client, session, 'read_memory', {'address':'0','size':4}).status_code == 409
    assert client.get('/api/runtime/control/status').json()['status']=='missing'
    # Original device returned with a new COM number. Old handle must be released explicitly.
    monkeypatch.setattr('mklink.probes.inventory', lambda:[{'probe_id':control.info['probe_id'],'port':'COM10'}])
    assert client.get('/api/runtime/control/status').json()['status']=='port_changed'
    assert call(client, session, 'write_memory', {'address':'0','data_hex':'00'}).status_code == 409
    assert not calls


@pytest.mark.parametrize('path', ['/_runtime/stop', '/api/runtime/control/stop-backend'])
def test_all_stop_entries_preserve_capture_and_other_windows(runtime, path):
    client, control, _, managers, _ = runtime
    stopped = []
    control.shutdown = lambda: stopped.append(True)
    managers['rtt'].running = True
    assert client.post(path, json={'confirm': True}).status_code == 409
    managers['rtt'].running = False
    control.views = {key: {'expires': float('inf')} for key in ('one', 'two')}
    assert client.post(path, json={'confirm': True}).status_code == 409
    assert not stopped and not control.stopping
    control.views.pop('two')
    assert client.post(path, json={'confirm': True}).status_code == 200
    assert stopped == [True]


def test_serial_and_modbus_do_not_block_target_reads(runtime):
    client, _, calls, managers, _ = runtime
    managers['serial'] = SimpleNamespace(running=True)
    managers['modbus'] = SimpleNamespace(running=True)
    session = attach(client)
    assert call(client, session, 'read_memory', {'address': '0', 'size': 4}).status_code == 200
    assert calls == ['read']
    client.post('/_runtime/detach', json={'session_id': session})
    assert client.post('/api/runtime/control/release-device', json={'confirm': True}).status_code == 200
    assert calls == ['read', 'disconnect']
    assert managers['serial'].running and managers['modbus'].running
