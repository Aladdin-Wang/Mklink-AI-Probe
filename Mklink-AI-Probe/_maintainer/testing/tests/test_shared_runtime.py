import asyncio
import base64
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from mklink.runtime_api import install_runtime


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    app = FastAPI()
    device = SimpleNamespace(connected=True, port="COM9", axf_status={"axf_path": str(tmp_path / "test.axf")})
    app.state.mklink_state = {"device": device, "project_root": str(tmp_path), "last_device_connection": {}}
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
        calls.append("start")
        managers["rtt"].running = True
        return {"status": "started"}

    @app.post("/api/dash/rtt/stop")
    async def stop():
        calls.append("stop")
        managers["rtt"].running = False
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
    client, _, calls, _, _ = runtime
    assert client.get("/_runtime/status", headers={"X-Auth-Token": "bad"}).status_code == 401
    assert client.get("/_runtime/status", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/_runtime/status", headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/_runtime/attach", json={"project_root": str(tmp_path / "other")}).status_code == 409
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


def test_shared_runtime_disables_legacy_agent_that_bypasses_admission():
    from mklink.remote.embedded_agent import EmbeddedAgentSettings
    app = FastAPI()
    app.state.mklink_state = {'project_root': '.', 'device': None}
    app.state.site_agent = SimpleNamespace(settings=EmbeddedAgentSettings(enabled=True, token='test-secret'))
    install_runtime(app, {'port': 8765, 'token': 'test-secret', 'instance_id': 'test'})
    assert app.state.site_agent.settings.enabled is False
    assert 'not yet supported' in app.state.site_agent.settings.configuration_error


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
