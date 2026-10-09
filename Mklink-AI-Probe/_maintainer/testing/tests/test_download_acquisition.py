import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mklink.remote.acquisition import suspend_acquisition
from mklink.remote.resource_manager import ResourceManager


@pytest.fixture
def capture(monkeypatch):
    calls = []
    state = {'device': SimpleNamespace(connected=True), 'resource_manager': ResourceManager()}
    managers = {}
    for name in ('rtt', 'superwatch', 'serial'):
        manager = SimpleNamespace(running=True, paused=False)
        def stop(m=manager, n=name):
            calls.append(('stop', n))
            m.running = False
        def start(m=manager, n=name):
            calls.append(('start', n))
            m.running = True
        def pause(m=manager, n=name):
            calls.append(('pause', n))
            m.paused = True
        manager.stop, manager.pause, manager._restart_after_operation = stop, pause, start
        managers[name] = manager
    monkeypatch.setattr('mklink.remote.dashboards.get_managers', lambda: managers)
    monkeypatch.setattr('mklink.remote.api.acquire_dashboard_resources', lambda *args: [])
    return state, managers, calls


@pytest.mark.parametrize('fail', [False, True])
def test_restore_all_captures_even_when_download_fails(capture, fail):
    state, managers, calls = capture
    managers['superwatch']._collecting = threading.Event()  # Was paused.
    async def run():
        try:
            async with suspend_acquisition(state) as report:
                assert not managers['rtt'].running and not managers['superwatch'].running
                assert managers['serial'].running
                calls.append(('download', 'started'))
                if fail:
                    raise ValueError('flash failed')
        except ValueError:
            assert fail
        assert report['state'] == 'restored'
        assert report['restored'] == ['rtt', 'superwatch']
    asyncio.run(run())
    assert calls == [('stop', 'rtt'), ('stop', 'superwatch'), ('download', 'started'),
                     ('start', 'rtt'), ('start', 'superwatch'), ('pause', 'superwatch')]


def test_partial_stop_failure_rolls_back_without_download(capture):
    state, managers, calls = capture
    def stuck():
        raise TimeoutError('worker still active')
    managers['superwatch'].stop = stuck
    async def run():
        with pytest.raises(HTTPException, match='Could not pause'):
            async with suspend_acquisition(state):
                pytest.fail('must not start download while a reader is still active')
    asyncio.run(run())
    assert calls == [('stop', 'rtt'), ('start', 'rtt')]
    assert managers['superwatch'].running
    assert state['acquisition_transition']['errors']


def test_restore_failure_is_reported_without_replaying_download(capture):
    state, managers, calls = capture
    def failed():
        raise RuntimeError('new target has no RTT control block')
    managers['rtt']._restart_after_operation = failed
    async def run():
        async with suspend_acquisition(state) as report:
            calls.append(('download', 'once'))
        assert report['state'] == 'failed'
        assert 'new target' in report['errors'][0]
        assert report['restored'] == ['superwatch']
    asyncio.run(run())
    assert calls.count(('download', 'once')) == 1


def test_same_usb_identity_reconnect_after_hpm_closes_device(capture, monkeypatch):
    state, managers, calls = capture
    device = state['device']
    device._connect = lambda: setattr(device, 'connected', True)
    control = SimpleNamespace(info={'probe_id': 'bound-probe'})
    selected = []
    def select(identity):
        selected.append(identity)
        return {'port': 'COM11'}
    monkeypatch.setattr('mklink.probes.select_probe', select)
    async def run():
        async with suspend_acquisition(state, control):
            device.connected = False
            state['device'] = None
        assert state['device'] is device and device.connected
    asyncio.run(run())
    assert selected == ['bound-probe'] and device._port == 'COM11'


def test_online_job_holds_suspension_until_worker_and_restoration_finish(capture, tmp_path):
    from fastapi import FastAPI
    from mklink.runtime_api import RuntimeControl, active_operation, Session
    from mklink.runtime_jobs import RuntimeJobs
    state, managers, calls = capture
    app = FastAPI()
    app.state.mklink_state = state
    control = RuntimeControl(app, {'jobs_path': str(tmp_path / 'jobs.json')})
    jobs = control.jobs = RuntimeJobs(control)
    control.sessions['owner'] = Session('.', None, streams={'rtt'})
    control.created_streams['rtt'] = 'owner'
    async def run():
        done = asyncio.Event()
        async def observe(job, result):
            await done.wait()
            return {'status': 'succeeded'}
        jobs._observe_online = observe
        async def start():
            assert not managers['rtt'].running
            return {'job_id': 'online-1', 'job': {'state': 'running'}}
        async with control.operation_lock:
            token = active_operation.set((control, None))
            control.current_operation = {'path': '/api/online-flash/jobs'}
            try:
                result = await jobs.record_online_start('one', {}, start)
            finally:
                active_operation.reset(token)
        assert result['job_id'] == 'online-1'
        assert jobs.active and not managers['rtt'].running
        done.set()
        await asyncio.gather(*jobs.tasks)
        assert jobs.active is None and managers['rtt'].running
        assert control.sessions['owner'].streams == {'rtt'}
        assert control.created_streams == {'rtt': 'owner'}
        assert next(iter(jobs.jobs.values()))['result']['acquisition']['restored'] == ['rtt', 'superwatch']
    asyncio.run(run())


@pytest.mark.parametrize('path', ['/api/offline-download/deploy', '/api/offline-download/trigger',
                                 '/api/offline-download/algorithm', '/api/online-flash/memory/read'])
def test_http_download_gate_pauses_before_handler_and_restores(capture, monkeypatch, tmp_path, path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mklink.runtime_api import install_runtime
    state, managers, calls = capture
    state['project_root'] = '.'
    app = FastAPI()
    app.state.mklink_state = state
    @app.post(path)
    async def download():
        assert not managers['rtt'].running and not managers['superwatch'].running
        calls.append(('download', 'once'))
        return {'status': 'completed'}
    monkeypatch.setattr('mklink.probe_volumes.resolve_volume', lambda *args: tmp_path)
    monkeypatch.setattr('mklink.probes.select_probe', lambda *args: {'serial_number': 'fixture'})
    install_runtime(app, {'port': 8765, 'token': 'test', 'instance_id': 'fixture'})
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test'}) as client:
        assert client.post(path, json={'probe_id': 'fixture'}).status_code == 200
    assert managers['rtt'].running and managers['superwatch'].running
    assert calls.count(('download', 'once')) == 1


def test_submission_marker_distinguishes_rejection_from_existing_job(capture):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mklink.runtime_api import install_runtime
    state, _, _ = capture
    state['project_root'] = '.'
    app = FastAPI()
    app.state.mklink_state = state
    control = install_runtime(app, {'port': 8765, 'token': 'test', 'instance_id': 'fixture'})
    control.jobs.jobs['original'] = {'job_id': 'original', 'request_id': 'original', 'state': 'running'}
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test'}) as client:
        for request_id, marker in [('new', 'not-started'), ('original', 'accepted')]:
            response = client.post('/api/online-flash/jobs', json={}, headers={'X-MKLink-Request-Id': request_id})
            assert response.status_code == 409
            assert response.headers['X-MKLink-Submission'] == marker


@pytest.mark.parametrize('streaming', [False, True])
def test_final_response_waits_for_restore_and_includes_restore_errors(capture, streaming):
    import json
    from mklink.remote.acquisition import download_response
    state, managers, calls = capture
    def failed():
        raise RuntimeError('restore failed')
    managers['rtt']._restart_after_operation = failed
    messages = []
    async def app(scope, receive, send):
        content_type = b'application/x-ndjson' if streaming else b'application/json'
        await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'content-type', content_type)]})
        if streaming:
            await send({'type': 'http.response.body', 'body': b'{"type":"line","line":"programming"}\n', 'more_body': True})
        payload = {'type': 'result', 'result': {'status': 'completed'}} if streaming else {'status': 'completed'}
        await send({'type': 'http.response.body', 'body': json.dumps(payload).encode(), 'more_body': streaming})
        if streaming:
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
    async def send(message):
        if message['type'] == 'http.response.body' and not message.get('more_body'):
            assert managers['superwatch'].running
        messages.append(message)
    asyncio.run(download_response(app, {}, None, send, state, None))
    payload = json.loads(messages[-1]['body'])
    result = payload['result'] if streaming else payload
    assert result['status'] == 'completed'
    assert 'restore failed' in result['acquisition']['errors'][0]
    if not streaming:
        assert int(dict(messages[0]['headers'])[b'content-length']) == len(messages[-1]['body'])


def test_cancellation_waits_for_worker_before_restoring(capture):
    from mklink.runtime_api import settle
    state, managers, _ = capture
    async def run():
        entered, done = asyncio.Event(), asyncio.Event()
        async def operation():
            async with suspend_acquisition(state):
                entered.set()
                await done.wait()
        worker = asyncio.create_task(operation())
        request = asyncio.create_task(settle(worker))
        await entered.wait()
        request.cancel()
        await asyncio.sleep(0)
        assert not request.done() and not managers['rtt'].running
        done.set()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert managers['rtt'].running
    asyncio.run(run())


def test_desktop_proxy_exposes_definite_rejection_to_webview():
    import httpx
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from mklink.runtime_proxy import create_proxy
    upstream = FastAPI()
    @upstream.post('/api/online-flash/jobs')
    async def reject(request: Request):
        assert request.headers['X-MKLink-Request-Id'] == 'new'
        return JSONResponse({'detail': 'invalid'}, status_code=422,
                            headers={'X-MKLink-Submission': 'not-started'})
    app = create_proxy({'port': 9001, 'token': 'test'}, port=8766, instance_id='desktop',
                       transport=httpx.ASGITransport(app=upstream))
    with TestClient(app, base_url='http://127.0.0.1:8766') as client:
        response = client.post('/api/online-flash/jobs', json={}, headers={
            'Origin': 'http://tauri.localhost', 'X-MKLink-Request-Id': 'new'})
        assert response.status_code == 422
        assert response.headers['X-MKLink-Submission'] == 'not-started'
        assert 'x-mklink-submission' in response.headers['Access-Control-Expose-Headers'].lower()


@pytest.mark.parametrize('kind', ['rtt', 'vofa', 'systemview'])
def test_restore_retains_live_channel_settings(capture, kind):
    state, managers, calls = capture
    manager = managers['rtt']
    managers.clear()
    managers[kind] = manager
    if kind == 'rtt':
        manager._line_assembler = SimpleNamespace(encoding='gbk')
        manager._channel_decoders = {0: SimpleNamespace(_line_assembler=SimpleNamespace(encoding='utf-8')),
                                     2: SimpleNamespace(_line_assembler=SimpleNamespace(encoding='gbk'))}
        manager.set_encoding = lambda value, channel=None: calls.append(('encoding', channel, value))
    elif kind == 'vofa':
        manager._channel_specs = [{'path': 'counter'}]
        manager._interval = 0.25  # Changed since the original start.
        def start(device, channels, interval):
            calls.append(('vofa', channels, interval))
            manager.running = True
        manager.start = start
    else:
        manager._recording = object()
        manager.start_recording = lambda: calls.append(('recording', 'start'))
    async def run():
        async with suspend_acquisition(state):
            pass
    asyncio.run(run())
    if kind == 'rtt':
        assert calls[-3:] == [('encoding', None, 'gbk'), ('encoding', 0, 'utf-8'), ('encoding', 2, 'gbk')]
    elif kind == 'vofa':
        assert calls[-1] == ('vofa', [{'path': 'counter'}], 0.25)
    else:
        assert calls[-1] == ('recording', 'start')
