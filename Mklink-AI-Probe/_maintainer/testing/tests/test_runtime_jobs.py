import asyncio
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from mklink.runtime_api import install_runtime
from mklink.runtime_jobs import RuntimeJobs


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    app = FastAPI()
    app.state.mklink_state = {'device': SimpleNamespace(connected=True, port='COM9'), 'project_root': '.'}
    managers = {'rtt': SimpleNamespace(running=False)}
    monkeypatch.setattr('mklink.remote.dashboards.get_managers', lambda: managers)
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    calls = []
    release = asyncio.Event()
    @app.post('/api/device/flash')
    async def flash():
        calls.append('flash')
        return {'success': True}
    @app.post('/api/device/reset')
    async def reset():
        calls.append('reset')
        await release.wait()
        return {'status': 'ok'}
    @app.post('/api/device/erase')
    async def erase():
        calls.append('erase')
        raise HTTPException(500, 'timeout after command sent')
    control = install_runtime(app, {'port': 8765, 'token': 'test', 'instance_id': 'fixture', 'jobs_path': str(tmp_path/'jobs.json')})
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token':'test'}) as client:
        yield client, control, calls, managers, release
        client.portal.call(release.set)
        client.portal.call(asyncio.sleep, .03)


def body(action='reset', request_id='test-operation'):
    return {'action': action, 'request_id': request_id, 'confirm': True}


def terminal(client, job_id):
    deadline = time.monotonic() + 5.0
    value = None
    while time.monotonic() < deadline:
        response = client.get('/api/runtime/jobs/'+job_id)
        assert response.status_code == 200, response.text
        value = response.json()
        if value['state'] != 'running': return value
        time.sleep(.01)
    pytest.fail(f'job did not complete within 5 seconds: {value!r}')


def test_job_retains_exclusion_and_deduplicates_after_client_leaves(fixture):
    client, control, calls, managers, release = fixture
    result = client.post('/api/runtime/jobs/', json=body())
    assert result.status_code == 202, result.text
    job = result.json()
    assert client.post('/api/runtime/jobs/', json=body()).json()['job_id'] == job['job_id']
    assert client.post('/api/runtime/jobs/', json=body('erase')).status_code == 409
    assert client.post('/api/device/reset').status_code == 409
    assert client.post('/api/runtime/control/release-device', json={'confirm':True}).status_code == 409
    assert client.post('/_runtime/stop', json={'confirm':True}).status_code == 409
    assert client.get('/api/runtime/control/status').json()['busy']
    client.portal.call(release.set)
    assert terminal(client, job['job_id'])['state'] == 'succeeded'
    assert client.post('/api/runtime/jobs/', json=body()).json()['state'] == 'succeeded'
    assert calls == ['reset']


def test_capture_and_confirmation_prevent_submission(fixture):
    client, _, calls, managers, _ = fixture
    assert client.post('/api/runtime/jobs/', json={**body(), 'confirm':False}).status_code == 422
    managers['rtt'].running = True
    assert client.post('/api/runtime/jobs/', json=body()).status_code == 409
    assert calls == []


def test_failed_transport_is_unknown_and_never_replayed(fixture):
    client, control, calls, _, _ = fixture
    job = client.post('/api/runtime/jobs/', json=body('erase')).json()
    assert terminal(client, job['job_id'])['state'] == 'unknown'
    restored = RuntimeJobs(control)
    assert restored.jobs[job['job_id']]['state'] == 'unknown'
    assert client.post('/api/runtime/jobs/', json=body('erase')).json()['state'] == 'unknown'
    assert calls == ['erase']


def test_killed_process_journal_is_unknown_without_replay(fixture, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    _, control, calls, _, _ = fixture
    marker = tmp_path / 'worker-started'
    child = tmp_path / 'job_child.py'
    child.write_text("""
import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
from mklink.runtime_jobs import RuntimeJobs
import mklink.remote.dashboards as dashboards
dashboards.active_bridge_dashboards = lambda: []
async def main():
    async def invoke(*args):
        Path(sys.argv[2]).write_text('one simulated operation', encoding='utf-8')
        await asyncio.Event().wait()
    control = SimpleNamespace(info={'jobs_path': sys.argv[1]},
        operation_lock=asyncio.Lock(), attach_lock=asyncio.Lock(),
        require_identity=lambda: None, online_job=lambda: None, invoke=invoke,
        app=SimpleNamespace(state=SimpleNamespace(mklink_state={
            'device': SimpleNamespace(connected=True)})))
    jobs = RuntimeJobs(control)
    jobs.submit({'action':'reset','request_id':'killed-request','confirm':True})
    await asyncio.Event().wait()
asyncio.run(main())
""", encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(Path.cwd()))
    process = subprocess.Popen([sys.executable, str(child), str(control.jobs.path), str(marker)],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists(), 'Simulated worker did not start'
        accepted = json.loads(control.jobs.path.read_text(encoding='utf-8'))[0]
        assert accepted['state'] == 'running'
        process.kill()
        process.wait(timeout=10)
        restored = RuntimeJobs(control)
        job = restored.submit({'action':'reset','request_id':'killed-request','confirm':True})
        assert job['job_id'] == accepted['job_id'] and job['state'] == 'unknown'
        assert not restored.tasks and not calls
        assert marker.read_text(encoding='utf-8') == 'one simulated operation'
        assert RuntimeJobs(control).jobs[job['job_id']]['state'] == 'unknown'
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_online_background_job_blocks_cdc_and_shared_jobs(fixture):
    client, control, calls, _, _ = fixture
    control.online_job = lambda: {'job_id':'online', 'state':'programming'}
    assert client.post('/api/device/reset').status_code == 409
    assert client.post('/api/runtime/jobs/', json=body()).status_code == 409
    assert client.post('/_runtime/stop', json={'confirm':True}).status_code == 409
    assert calls == []


@pytest.mark.parametrize('action', ['flash', 'erase', 'reset'])
def test_legacy_write_routes_cannot_bypass_journal(fixture, action):
    client, control, calls, _, release = fixture
    client.portal.call(release.set)
    response = client.post('/api/device/' + action, json={})
    assert response.status_code == 409
    assert 'jobs' in response.json()['detail']
    assert not calls and not control.jobs.jobs


def test_independent_serial_capture_does_not_reserve_target_job(fixture):
    client, _, calls, managers, release = fixture
    managers['serial'] = SimpleNamespace(running=True)
    managers['modbus'] = SimpleNamespace(running=True)
    client.portal.call(release.set)
    result = client.post('/api/runtime/jobs/', json=body())
    assert result.status_code == 202, result.text
    assert terminal(client, result.json()['job_id'])['state'] == 'succeeded'
    assert calls == ['reset']
    assert managers['serial'].running and managers['modbus'].running


def test_failed_acceptance_preserves_full_deduplication_history(fixture, monkeypatch):
    import hashlib
    client, control, calls, _, _ = fixture
    fingerprint = hashlib.sha256(json.dumps(['reset', {}], sort_keys=True).encode()).hexdigest()
    control.jobs.jobs.update({str(index): {'job_id': str(index), 'request_id': f'old-{index}',
        'fingerprint': fingerprint, 'state': 'succeeded', 'result': {'status': 'ok'}}
        for index in range(64)})
    control.jobs.save()
    before = control.jobs.path.read_bytes()
    def failed_save():
        raise OSError('journal storage unavailable')
    with monkeypatch.context() as patcher:
        patcher.setattr(control.jobs, 'save', failed_save)
        response = client.post('/api/runtime/jobs/', json=body(request_id='new-request'))
    assert response.status_code == 503
    assert control.jobs.path.read_bytes() == before
    assert list(control.jobs.jobs) == [str(index) for index in range(64)]
    assert client.post('/api/runtime/jobs/', json=body(request_id='old-0')).json()['job_id'] == '0'
    assert not calls and not control.jobs.tasks


def test_loading_terminal_journal_does_not_rewrite_it(fixture):
    import os
    client, control, _, _, release = fixture
    client.portal.call(release.set)
    job = client.post('/api/runtime/jobs/', json=body()).json()
    assert terminal(client, job['job_id'])['state'] == 'succeeded'
    path = control.jobs.path
    os.utime(path, (1_000_000_000, 1_000_000_000))
    previous = (path.read_bytes(), path.stat().st_mtime_ns)
    restored = RuntimeJobs(control)
    assert restored.jobs[job['job_id']]['state'] == 'succeeded'
    assert (path.read_bytes(), path.stat().st_mtime_ns) == previous
