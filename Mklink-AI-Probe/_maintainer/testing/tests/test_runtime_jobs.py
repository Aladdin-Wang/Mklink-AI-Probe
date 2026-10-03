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
    for _ in range(100):
        value = client.get('/api/runtime/jobs/'+job_id).json()
        if value['state'] != 'running': return value
        time.sleep(.01)
    pytest.fail('job did not complete')


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


def test_interrupted_journal_is_unknown_without_hardware_replay(fixture):
    _, control, calls, _, _ = fixture
    control.jobs.path.write_text(json.dumps([{'job_id':'old', 'state':'running'}]), encoding='utf-8')
    restored = RuntimeJobs(control)
    assert restored.jobs['old']['state'] == 'unknown'
    assert calls == []


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
