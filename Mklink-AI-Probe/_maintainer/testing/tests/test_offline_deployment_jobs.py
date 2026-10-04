"""Deploy journals share the production request admission and temporary inputs."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from test_shared_runtime import runtime
from test_offline_download import _config
from mklink.remote.offline_download_api import create_offline_download_router
from mklink.runtime_jobs import RuntimeJobs


@pytest.fixture
def deployment(runtime, tmp_path, monkeypatch):
    client, control, calls, managers, app = runtime
    disk = tmp_path / 'disk'
    disk.mkdir()
    control.info['jobs_path'] = str(tmp_path / 'jobs.json')
    control.jobs.path = Path(control.info['jobs_path'])
    monkeypatch.setattr('mklink.probe_volumes.resolve_volume', lambda _: {'root': str(disk)})
    monkeypatch.setattr('mklink.discovery.find_microkeen_disk', lambda: str(disk))
    app.include_router(create_offline_download_router(SimpleNamespace(), app.state.mklink_state['resource_manager']))
    config = _config()
    config['firmwares'] = [config['firmwares'][1]]
    config['firmwares'][0]['upload_index'] = 0
    config['algorithms'] = [config['algorithms'][0]]
    def submit(request_id='deployment-one', content=b':00000001FF\n'):
        return client.post('/api/offline-download/deploy',
            data={'request_id': request_id, 'config_json': json.dumps(config)},
            files=[('firmware_files', ('app.hex', content)), ('flm_files', ('algo.flm', b'algorithm'))])
    return client, control, disk, config, submit


def test_same_request_uses_content_not_temporary_path_and_never_writes_twice(deployment, monkeypatch):
    client, control, disk, config, submit = deployment
    first = submit()
    assert first.status_code == 200, first.text
    job_id = first.json()['job_id']
    def forbidden(*args, **kwargs):
        pytest.fail('duplicate deployment wrote again')
    monkeypatch.setattr('mklink.remote.offline_download_api.deploy_offline_bundle', forbidden)
    assert submit().json()['job_id'] == job_id
    assert submit(content=b'changed').status_code == 409
    job = client.get('/api/runtime/jobs/' + job_id).json()
    assert job['state'] == 'succeeded' and job['request_id'] == 'deployment-one'
    assert 'recovery_directory' not in job
    assert RuntimeJobs(control).jobs[job_id]['state'] == 'succeeded'
    assert (disk / 'rt-thread.hex').read_bytes() == b':00000001FF\n'


def test_accept_save_failure_never_modifies_disk(deployment, monkeypatch):
    _, control, disk, _, submit = deployment
    def fail(): raise OSError('journal unavailable')
    monkeypatch.setattr(control.jobs, 'save', fail)
    assert submit().status_code == 503
    assert not list(disk.rglob('*')) and not control.jobs.jobs


def test_recovery_registration_failure_never_modifies_disk(deployment, monkeypatch):
    import threading
    _, control, disk, _, submit = deployment
    destination = disk / 'rt-thread.hex'
    destination.write_bytes(b'original')
    original = control.jobs.save
    directories, threads = [], set()
    def save():
        threads.add(threading.get_ident())
        job = next(iter(control.jobs.jobs.values()))
        if job.get('recovery_directory'):
            directories.append(Path(job['recovery_directory']))
            raise OSError('recovery journal unavailable')
        original()
    monkeypatch.setattr(control.jobs, 'save', save)
    response = submit()
    assert response.status_code == 409, response.text
    assert response.json()['detail']['state'] == 'failed'
    assert destination.read_bytes() == b'original'
    assert list(disk.iterdir()) == [destination]
    assert len(directories) == 1 and not directories[0].exists()
    assert len(threads) == 1  # Worker callbacks never mutate the journal concurrently.
    job = RuntimeJobs(control).jobs[response.json()['detail']['job_id']]
    assert 'recovery_directory' not in job


def test_terminal_save_failure_retains_unknown_without_replay(deployment, monkeypatch):
    _, control, disk, _, submit = deployment
    original = control.jobs.save
    count = 0
    def fail_terminal():
        nonlocal count
        count += 1
        if control.jobs.active is None: raise OSError('terminal journal unavailable')
        original()
    monkeypatch.setattr(control.jobs, 'save', fail_terminal)
    response = submit()
    assert response.status_code == 500, response.text
    detail = response.json()['detail']
    assert detail['state'] == 'unknown'
    assert RuntimeJobs(control).jobs[detail['job_id']]['state'] == 'unknown'
    assert submit().json()['detail']['job_id'] == detail['job_id']
    assert count == 4


@pytest.mark.parametrize('terminal_save_fails', [False, True])
def test_cleared_recovery_journal_failure_never_replays_completed_copy(deployment, monkeypatch, terminal_save_fails):
    _, control, disk, _, submit = deployment
    original = control.jobs.save
    saved_recovery = None
    clear_failed = False
    def save():
        nonlocal saved_recovery, clear_failed
        job = next(iter(control.jobs.jobs.values()))
        if saved_recovery is not None and 'recovery_directory' not in job:
            clear_failed = True
            raise OSError('cleared recovery journal unavailable')
        if clear_failed and terminal_save_fails:
            raise OSError('terminal journal unavailable')
        original()
        if job.get('recovery_directory'):
            saved_recovery = Path(job['recovery_directory'])
    monkeypatch.setattr(control.jobs, 'save', save)
    response = submit()
    assert response.status_code == 500, response.text
    detail = response.json()['detail']
    assert detail['state'] == 'unknown'
    assert clear_failed and saved_recovery is not None
    assert detail['recovery_directory'] == str(saved_recovery)
    assert not saved_recovery.exists()  # A recorded location is not proof of retained files.
    snapshot = {str(path.relative_to(disk)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in disk.rglob('*') if path.is_file()}
    assert snapshot['rt-thread.hex'][0] == b':00000001FF\n'
    assert len(snapshot) == 3
    restored = RuntimeJobs(control)
    assert restored.jobs[detail['job_id']]['state'] == 'unknown'
    assert restored.jobs[detail['job_id']]['recovery_directory'] == str(saved_recovery)
    control.jobs.jobs.update(restored.jobs)
    def forbidden(*args, **kwargs):
        pytest.fail('uncertain deployment replayed after journal reload')
    monkeypatch.setattr('mklink.remote.offline_download_api.deploy_offline_bundle', forbidden)
    duplicate = submit()
    assert duplicate.status_code == 500, duplicate.text
    assert duplicate.json()['detail']['job_id'] == detail['job_id']
    assert snapshot == {str(path.relative_to(disk)): (path.read_bytes(), path.stat().st_mtime_ns)
                        for path in disk.rglob('*') if path.is_file()}


def test_recovery_directory_survives_reload(deployment, tmp_path, monkeypatch):
    from mklink.offline_download import OfflineRecoveryError
    _, control, _, _, submit = deployment
    recovery = tmp_path / 'retained'
    recovery.mkdir()
    def fail(*args, **kwargs): raise OfflineRecoveryError(recovery)
    monkeypatch.setattr('mklink.remote.offline_download_api.deploy_offline_bundle', fail)
    response = submit()
    assert response.status_code == 500, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'OFFLINE_RECOVERY_REQUIRED'
    job = RuntimeJobs(control).jobs[detail['job_id']]
    assert job['recovery_directory'] == str(recovery)
    assert job['state'] == 'unknown'


def test_deployment_recorder_rejects_admission_bypass(deployment):
    _, control, disk, _, _ = deployment
    async def operation(): pytest.fail('must not run')
    with pytest.raises(HTTPException) as error:
        asyncio.run(control.jobs.record_deployment('outside', 'fingerprint', operation))
    assert error.value.status_code == 409
    assert not control.jobs.jobs


def test_request_cancellation_keeps_inputs_and_admission_until_deployment_finishes(deployment, monkeypatch):
    import threading
    import httpx
    import mklink.remote.offline_download_api as api
    client, control, disk, config, _ = deployment
    started, release = threading.Event(), threading.Event()
    original = api.deploy_offline_bundle
    snapshots = []
    def blocked(*args, **kwargs):
        snapshots.extend(kwargs['firmware_sources'].values())
        started.set()
        assert release.wait(5), 'test release timeout'
        assert all(path.is_file() for path in snapshots)
        return original(*args, **kwargs)
    monkeypatch.setattr(api, 'deploy_offline_bundle', blocked)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=control.app),
                base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as http:
            task = asyncio.create_task(http.post('/api/offline-download/deploy',
                data={'request_id': 'cancelled-http', 'config_json': json.dumps(config)},
                files=[('firmware_files', ('app.hex', b':00000001FF\n')),
                       ('flm_files', ('algo.flm', b'algorithm'))]))
            try:
                assert await asyncio.to_thread(started.wait, 3)
                task.cancel()
                await asyncio.sleep(.05)
                assert control.operation_lock.locked() and not task.done()
                jobs = (await http.get('/api/runtime/jobs/')).json()['jobs']
                assert jobs[0]['state'] == 'running'
                assert all(path.is_file() for path in snapshots)
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError): await task
            jobs = (await http.get('/api/runtime/jobs/')).json()['jobs']
            assert jobs[0]['state'] == 'succeeded'
            assert not control.operation_lock.locked()
            assert not any(path.exists() for path in snapshots)
    client.portal.call(scenario)
    assert (disk / 'rt-thread.hex').exists()


def test_disk_identity_is_rechecked_after_input_preparation(deployment, tmp_path, monkeypatch):
    import mklink.remote.offline_download_api as api
    _, control, disk, _, submit = deployment
    prepare = api._deployment_inputs
    def change_after_preparing(*args):
        fingerprint = prepare(*args)
        monkeypatch.setattr('mklink.probe_volumes.resolve_volume', lambda _: {'root': str(tmp_path / 'other')})
        return fingerprint
    monkeypatch.setattr(api, '_deployment_inputs', change_after_preparing)
    response = submit()
    assert response.status_code == 409, response.text
    assert response.json()['detail']['state'] == 'failed'
    assert not list(disk.rglob('*'))


def test_large_deployment_result_preserves_queryable_summary(deployment, monkeypatch):
    _, control, _, _, submit = deployment
    result = {'status': 'deployed', 'model': 'V4', 'script_name': 'main.py', 'files': ['x' * 200] * 100}
    monkeypatch.setattr('mklink.remote.offline_download_api.deploy_offline_bundle', lambda *a, **k: result)
    response = submit()
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['status'] == 'deployed' and value['file_count'] == 100
    assert value['files'] == [] and value['truncated']
    assert len(control.jobs.path.read_bytes()) < 16384


def test_killed_deployment_is_unknown_and_duplicate_does_not_rewrite(deployment, tmp_path):
    import os
    import subprocess
    import sys
    import time
    client, control, disk, config, submit = deployment
    destination = disk / 'rt-thread.hex'
    destination.write_bytes(b'original')
    payload = tmp_path / 'config.json'
    payload.write_text(json.dumps(config), encoding='utf-8')
    marker = tmp_path / 'disk-write-completed'
    staging = tmp_path / 'child-temp'
    staging.mkdir()
    child = tmp_path / 'deploy_child.py'
    child.write_text("""
import json, sys, threading, shutil
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mklink.runtime_api import install_runtime
from mklink.remote.resource_manager import ResourceManager
from mklink.remote.offline_download_api import create_offline_download_router
import mklink.probes, mklink.probe_volumes, mklink.discovery, mklink.remote.dashboards
journal, disk, payload, marker = map(Path, sys.argv[1:])
mklink.probes.inventory = lambda: []
mklink.probe_volumes.resolve_volume = lambda _: {'root': str(disk)}
mklink.discovery.find_microkeen_disk = lambda: str(disk)
mklink.remote.dashboards.get_managers = lambda: {}
app = FastAPI()
app.state.mklink_state = {'device': SimpleNamespace(connected=True, port='COM9'),
                         'project_root': str(disk), 'resource_manager': ResourceManager()}
control = install_runtime(app, {'port':8765, 'token':'fixture', 'instance_id':'child', 'jobs_path':str(journal)})
app.include_router(create_offline_download_router(SimpleNamespace(), app.state.mklink_state['resource_manager']))
import mklink.offline_download as offline
original_copy = offline.copy_verified
def copy_and_block(source, target, *args, **kwargs):
    result = original_copy(source, target, *args, **kwargs)
    if Path(target) == disk/'rt-thread.hex':
        marker.write_text('one completed destination write', encoding='utf-8')
        threading.Event().wait()
    return result
offline.copy_verified = copy_and_block
with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token':'fixture'}) as client:
    client.post('/api/offline-download/deploy',
        data={'request_id':'deployment-one', 'config_json':payload.read_text()},
        files=[('firmware_files', ('app.hex', b':00000001FF\\n')),
               ('flm_files', ('algo.flm', b'algorithm'))])
""", encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(Path.cwd()), TEMP=str(staging), TMP=str(staging), TMPDIR=str(staging))
    process = subprocess.Popen([sys.executable, str(child), str(control.jobs.path), str(disk), str(payload), str(marker)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        deadline = time.monotonic() + 20
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists(), 'deployment did not reach destination write'
        accepted = json.loads(control.jobs.path.read_text())[0]
        assert accepted['state'] == 'running'
        assert Path(accepted['recovery_directory']).is_dir()
        process.kill()
        process.wait(timeout=10)
        assert destination.read_bytes() == b':00000001FF\n'
        backups = list(staging.glob('mklink-offline-staging-*/backup/rt-thread.hex'))
        assert len(backups) == 1 and backups[0].read_bytes() == b'original'
        assert backups[0] == Path(accepted['recovery_directory']) / 'backup' / 'rt-thread.hex'
        restored = RuntimeJobs(control)
        control.jobs.jobs.update(restored.jobs)
        job = client.get('/api/runtime/jobs/' + accepted['job_id']).json()
        assert job['state'] == 'unknown'
        assert job['recovery_directory'] == accepted['recovery_directory']
        timestamp = destination.stat().st_mtime_ns
        result = submit()
        assert result.status_code == 500, result.text
        assert result.json()['detail']['job_id'] == accepted['job_id']
        assert result.json()['detail']['state'] == 'unknown'
        assert destination.stat().st_mtime_ns == timestamp
        assert not (disk / 'Python').exists()
        assert not control.jobs.tasks
        assert RuntimeJobs(control).jobs[accepted['job_id']]['state'] == 'unknown'
    finally:
        if process.poll() is None: process.kill()
        process.communicate(timeout=10)
