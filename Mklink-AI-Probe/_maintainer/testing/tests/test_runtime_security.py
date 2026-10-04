"""Shared security admission and observation without issuing hardware commands."""
import json
import threading
import time
from types import SimpleNamespace
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from mklink.cmsis_dap.models import JobState
from mklink.remote.api import create_app
from mklink.runtime_api import install_runtime
from mklink.runtime_jobs import RuntimeJobs
from mklink.security_operations import run_security_operation
from mklink.runtime import RuntimeErrorResponse


def arguments(**overrides):
    return dict(action='unlock', target_part='nrf54l15', voltage_mv=None,
                confirm_user=True, confirm_data_loss=True, **overrides)


def submission(**overrides):
    return dict(action='security', request_id='security-test', confirm=True,
                arguments=arguments(), **overrides)


def terminal(client, job_id):
    for _ in range(100):
        job = client.get('/api/runtime/jobs/' + job_id).json()
        if job['state'] != 'running':
            return job
        time.sleep(.01)
    pytest.fail('job did not settle')


@pytest.fixture
def security(monkeypatch, tmp_path):
    app = create_app(auth_token=None, project_root=str(tmp_path))
    services = app.state.online_flash
    selected = dict(probe_id='usb-test', serial_number='SERIAL', port='COM9')
    inventory = [selected]
    monkeypatch.setattr('mklink.probes.inventory', lambda: inventory)
    monkeypatch.setattr('mklink.probes.select_probe', lambda selector: selected)
    managers = {'rtt': SimpleNamespace(running=False)}
    monkeypatch.setattr('mklink.remote.dashboards.get_managers', lambda: managers)
    services.probe_provider = lambda: [SimpleNamespace(unique_id='SERIAL', product_name='MKLink')]
    started, release, waiting = threading.Event(), threading.Event(), threading.Event()
    calls = []
    @dataclass
    class Outcome:
        job_id: str = 'online-test'
        state: JobState = JobState.SUCCEEDED
        error_code: str | None = None
        error_message: str | None = None
    outcome = Outcome()
    def start(current, body, target):
        assert current is services
        assert json.loads((tmp_path/'jobs.json').read_text())[0]['state'] == 'running'
        calls.append(body)
        started.set()
        return 'online-test', outcome
    def wait(job_id):
        assert job_id == 'online-test'
        waiting.set()
        assert release.wait(5), 'test worker not released'
        return outcome
    # Exercise production security recipe and route; substitute only hardware job execution/catalog.
    services.job_manager = SimpleNamespace(list=lambda: [], wait=wait, events=lambda _: [])
    monkeypatch.setattr('mklink.remote.online_flash_api._resolved_target',
                        lambda catalog, part: SimpleNamespace(part_number=part))
    monkeypatch.setattr('mklink.remote.online_flash_api._start_job_with_configuration', start)
    control = install_runtime(app, dict(port=8765, token='test', instance_id='fixture',
        probe_id='usb-test', jobs_path=str(tmp_path/'jobs.json')))
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token':'test'}) as client:
        try:
            yield SimpleNamespace(client=client, control=control, services=services, calls=calls,
                managers=managers, inventory=inventory, release=release, started=started, waiting=waiting, outcome=outcome)
        finally:
            release.set()
            for job in list(control.jobs.jobs.values()):
                terminal(client, job['job_id'])


def test_unattached_security_is_journaled_deduplicated_and_held_until_terminal(security):
    s = security
    assert s.client.post('/api/device/security', json=arguments()).status_code == 409
    response = s.client.post('/api/runtime/jobs/', json=submission())
    assert response.status_code == 202, response.text
    job = response.json()
    assert s.started.wait(2)
    assert s.control.jobs.active is not None
    assert s.client.post('/api/runtime/jobs/', json=submission()).json()['job_id'] == job['job_id']
    assert s.client.post('/api/runtime/jobs/', json={**submission(), 'request_id':'second'}).status_code == 409
    assert s.client.post('/_runtime/stop', json={'confirm':True}).status_code == 409
    assert s.client.post('/api/probe/version').status_code == 409
    s.release.set()
    result = terminal(s.client, job['job_id'])
    assert result['state'] == 'succeeded'
    assert result['result']['online_job_id'] == 'online-test'
    assert s.client.post('/api/runtime/jobs/', json=submission()).json()['state'] == 'succeeded'
    assert len(s.calls) == 1
    body = s.calls[0]
    assert body.probe_id == 'SERIAL' and body.connect_mode == 'attach'
    assert body.reset_voltage_mv is None and body.actions == ['connect','unlock','reset','disconnect']


@pytest.mark.parametrize('reason', ['capture','missing','journal','confirmation','wrong-selector'])
def test_security_refuses_before_execution(security, reason):
    s = security
    body = submission()
    expected = 409
    if reason == 'capture': s.managers['rtt'].running = True
    if reason == 'missing': s.inventory.clear()
    if reason == 'journal': s.control.jobs.path = None; expected = 503
    if reason == 'confirmation': body['arguments']['confirm_data_loss'] = False; expected = 422
    if reason == 'wrong-selector': body['arguments']['probe_id'] = 'other'; expected = 422
    assert s.client.post('/api/runtime/jobs/', json=body).status_code == expected
    assert not s.calls and not s.control.jobs.jobs


def test_backend_failure_is_retained_and_not_replayed(security):
    s = security
    s.outcome.state = JobState.FAILED
    s.outcome.error_message = 'verification failed'
    s.release.set()
    job = s.client.post('/api/runtime/jobs/', json=submission()).json()
    result = terminal(s.client, job['job_id'])
    assert result['state'] == 'failed'
    assert result['result']['error_message'] == 'verification failed'
    assert s.client.post('/api/runtime/jobs/', json=submission()).json()['state'] == 'failed'
    assert len(s.calls) == 1


def test_interrupted_security_record_loads_unknown_without_replay(security):
    s = security
    job = s.client.post('/api/runtime/jobs/', json=submission()).json()
    assert s.started.wait(2)
    # A recovered backend owns a snapshot, never a second writer to a live journal.
    recovery = s.control.jobs.path.with_name('recovered.json')
    recovery.write_bytes(s.control.jobs.path.read_bytes())
    restored = RuntimeJobs(SimpleNamespace(info={'jobs_path':str(recovery)}))
    assert restored.submit(submission())['state'] == 'unknown'
    assert len(s.calls) == 1
    s.release.set()
    terminal(s.client, job['job_id'])


@pytest.mark.parametrize('mode', ['lost-submit', 'timeout', 'success'])
def test_client_submits_once_without_attaching_or_closing_services(monkeypatch, mode):
    calls = []
    monkeypatch.setattr('mklink.runtime.ensure_runtime', lambda **kw: {'probe_id':'usb-test'})
    def forbidden(*a, **kw): pytest.fail('client attempted private service creation')
    monkeypatch.setattr('mklink.remote.online_flash_api.create_default_online_flash_services', forbidden)
    monkeypatch.setattr('mklink.remote.online_flash_api.shutdown_online_flash_services', forbidden)
    def request(info, method, path, payload=None, **kwargs):
        calls.append((method,path,payload))
        if mode == 'lost-submit': raise RuntimeErrorResponse('response lost')
        return dict(job_id='job', state='succeeded' if mode == 'success' else 'running',
                    result={'status':'succeeded'})
    monkeypatch.setattr('mklink.runtime.request', request)
    kwargs = dict(voltage_mv=None, confirm_user=True, confirm_data_loss=True,
                  probe_id='usb-test', request_id='keep-this-id', timeout=.001)
    if mode == 'success':
        assert run_security_operation('unlock', 'nrf54l15', **kwargs)['request_id'] == 'keep-this-id'
    else:
        with pytest.raises(RuntimeErrorResponse, match='request_id=keep-this-id'):
            run_security_operation('unlock', 'nrf54l15', **kwargs)
    assert sum(method == 'POST' for method, _, _ in calls) == 1
    assert all('/api/runtime/jobs/' in path for _, path, _ in calls)


def test_lock_uses_image_verification_before_protection(security, monkeypatch, tmp_path):
    s = security
    firmware = tmp_path/'app.bin'; firmware.write_bytes(b'firmware')
    inspection = SimpleNamespace(image_id='image', sha256='verified')
    monkeypatch.setattr('mklink.remote.online_flash_api._target_flash_configuration', lambda *a: ([], 'fingerprint', []))
    monkeypatch.setattr(s.services.image_inspector, 'inspect', lambda path, regions, **kw: inspection)
    body = submission()
    body['arguments'] = dict(action='lock', target_part='nrf54l15', voltage_mv=None,
                            confirm_user=True, firmware=str(firmware))
    s.release.set()
    job = s.client.post('/api/runtime/jobs/', json=body).json()
    assert terminal(s.client,job['job_id'])['result']['verified_sha256'] == 'verified'
    assert s.calls[0].actions == ['connect','verify','lock','reset','disconnect']
    assert s.calls[0].image_id == 'image'


def test_client_timeout_leaves_shared_job_running(security, monkeypatch):
    s = security
    monkeypatch.setattr('mklink.runtime.ensure_runtime', lambda **kw: {'probe_id':'usb-test'})
    def request(info, method, path, payload=None, **kwargs):
        response = s.client.request(method, path, json=payload)
        if response.status_code >= 400:
            raise RuntimeErrorResponse(response.text)
        return response.json()
    monkeypatch.setattr('mklink.runtime.request', request)
    with pytest.raises(RuntimeErrorResponse, match='Observation timed out'):
        run_security_operation('unlock','nrf54l15',voltage_mv=None,
            confirm_user=True,confirm_data_loss=True,request_id='timeout-job',timeout=.01)
    assert s.started.wait(2)
    job = s.client.get('/api/runtime/jobs/').json()['jobs'][0]
    assert job['state'] == 'running' and s.control.jobs.active is not None
    s.release.set()
    assert terminal(s.client,job['job_id'])['state'] == 'succeeded'
    assert len(s.calls) == 1


def test_cancelled_task_keeps_admission_until_worker_settles(security):
    import asyncio
    s = security
    job = s.client.post('/api/runtime/jobs/', json=submission()).json()
    assert s.started.wait(2)
    async def cancel():
        next(iter(s.control.jobs.tasks)).cancel()
        await asyncio.sleep(.01)
    s.client.portal.call(cancel)
    assert s.control.jobs.active is not None
    assert s.client.post('/api/probe/version').status_code == 409
    s.release.set()
    assert terminal(s.client,job['job_id'])['state'] == 'unknown'
    assert len(s.calls) == 1


def test_non_nrf_security_preserves_explicit_voltage_and_reset_recipe(security, monkeypatch):
    # This test checks request planning, not optional packaged FLM availability.
    monkeypatch.setattr('mklink.cmsis_dap.security.require_security_capability',
                        lambda part: SimpleNamespace(family='stm32f103-rdp1'))
    s = security
    body = submission()
    body['arguments'].update(target_part='STM32F103RE', voltage_mv=3300)
    s.release.set()
    job = s.client.post('/api/runtime/jobs/', json=body).json()
    assert terminal(s.client, job['job_id'])['state'] == 'succeeded'
    assert s.calls[0].reset_mode == 'power-cycle'
    assert s.calls[0].reset_voltage_mv == 3300
    assert s.calls[0].connect_mode == 'under-reset'


def test_wrong_online_probe_never_starts_security(security):
    s = security
    s.services.probe_provider = lambda: [SimpleNamespace(unique_id='OTHER', product_name='MKLink')]
    job = s.client.post('/api/runtime/jobs/', json=submission()).json()
    assert terminal(s.client,job['job_id'])['state'] == 'failed'
    assert not s.calls


def test_cli_exposes_shared_selector_and_recovery_id(monkeypatch, capsys):
    from mklink.cli import _cli_security
    received = {}
    def run(action, target, **kwargs):
        received.update(kwargs)
        return {'status':'succeeded', 'target_part':target, 'reset_mode':'default', 'voltage_mv':None}
    monkeypatch.setattr('mklink.security_operations.run_security_operation', run)
    args = SimpleNamespace(security_command='unlock', target_part='nrf54l15', voltage_mv=None,
        confirm=True, confirm_data_loss=True, probe='test-alias', request_id='saved-id',
        project_root='.', frequency=1_000_000, timeout=1, json=True)
    assert _cli_security(args) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)['status'] == 'succeeded'
    assert 'saved-id' in output.err
    assert received['probe_id'] == 'test-alias' and received['request_id'] == 'saved-id'


def test_unwritable_security_journal_prevents_backend_start(security, monkeypatch):
    s = security
    def fail(): raise OSError('journal unavailable')
    monkeypatch.setattr(s.control.jobs, 'save', fail)
    assert s.client.post('/api/runtime/jobs/', json=submission()).status_code == 503
    assert not s.calls and not s.control.jobs.jobs


def test_reused_security_id_with_changed_operation_is_rejected(security):
    s = security
    s.release.set()
    job = s.client.post('/api/runtime/jobs/', json=submission()).json()
    terminal(s.client,job['job_id'])
    other = submission()
    other['arguments']['frequency'] = 2_000_000
    assert s.client.post('/api/runtime/jobs/', json=other).status_code == 409
    assert len(s.calls) == 1


@pytest.mark.parametrize('lose_response', [False, True])
def test_active_mcp_security_uses_real_journal_without_target_attach(security, monkeypatch, lose_response):
    import asyncio
    from fastmcp import Client
    from mklink import runtime_mcp
    s = security
    monkeypatch.setattr('mklink.runtime.ensure_runtime', lambda **kw: {'probe_id':'usb-test'})
    def forbidden(*a,**kw): pytest.fail('MCP security implicitly attached a target')
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', forbidden)
    posts = []
    def request(info, method, path, payload=None, **kwargs):
        response = s.client.request(method, path, json=payload)
        if response.status_code >= 400:
            raise RuntimeErrorResponse(response.text)
        if method == 'POST':
            posts.append(payload)
            if lose_response:
                raise RuntimeErrorResponse('response lost after acceptance')
        return response.json()
    monkeypatch.setattr('mklink.runtime.request', request)
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            args=dict(target_part='nrf54l15',request_id='security-mcp',probe='usb-test',
                      confirm_user=True,confirm_data_loss=True)
            result=await mcp.call_tool('security_unlock',args,raise_on_error=False)
            assert result.is_error == lose_response
            assert s.started.wait(2)
            assert not s.control.sessions and s.control.jobs.active is not None
            if not lose_response:
                duplicate=await mcp.call_tool('security_unlock',args)
                assert duplicate.data['job_id']==result.data['job_id']
            await mcp.call_tool('disconnect')
            listing=await mcp.call_tool('job_status')
            job=listing.data['jobs'][0]
            assert job['state']=='running' and job['request_id']=='security-mcp'
            assert len(s.calls)==1
            s.release.set()
            assert terminal(s.client,job['job_id'])['state']=='succeeded'
            status=await mcp.call_tool('job_status',{'job_id':job['job_id']})
            assert status.data['state']=='succeeded'
    asyncio.run(scenario())
    assert len(posts)==(1 if lose_response else 2)


def test_explicit_online_stop_remains_available_while_durable_job_is_running(security, monkeypatch):
    s = security
    stops = []
    def stop(job_id):
        stops.append(job_id)
        s.outcome.state = JobState.STOPPED
        s.release.set()
        return {'job_id':job_id, 'state':'stopping'}
    monkeypatch.setattr(s.services.job_manager, 'stop', stop, raising=False)
    job = s.client.post('/api/runtime/jobs/', json=submission()).json()
    assert s.waiting.wait(2)
    assert not s.control.operation_lock.locked()
    assert s.control.jobs.active is not None
    linked = s.client.get('/api/runtime/jobs/' + job['job_id']).json()
    assert linked['online_job_id'] == 'online-test'
    assert json.loads(s.control.jobs.path.read_text())[0]['online_job_id'] == 'online-test'
    assert s.client.post('/api/probe/version').status_code == 409
    response = s.client.post('/api/online-flash/jobs/online-test/stop')
    assert response.status_code == 200, response.text
    assert stops == ['online-test']
    result = terminal(s.client,job['job_id'])
    assert result['state'] == 'failed' and result['result']['online_state'] == 'stopped'


def test_link_journal_failure_retains_ownership_until_online_worker_finishes(security, monkeypatch):
    s = security
    save = s.control.jobs.save
    def fail_link_only():
        if s.control.jobs.active and s.control.jobs.active.get('online_job_id'):
            raise OSError('link write failed')
        save()
    monkeypatch.setattr(s.control.jobs, 'save', fail_link_only)
    job = s.client.post('/api/runtime/jobs/', json=submission()).json()
    assert s.waiting.wait(2)
    assert s.control.jobs.active is not None
    assert s.client.post('/api/probe/version').status_code == 409
    assert s.client.post('/_runtime/stop', json={'confirm':True}).status_code == 409
    s.release.set()
    assert terminal(s.client,job['job_id'])['state'] == 'unknown'
    assert len(s.calls) == 1


def test_gui_online_start_is_journaled_and_duplicates_return_original_result(security):
    s = security
    body = dict(actions=['connect','disconnect'], probe_id='SERIAL', target_part='nrf54l15')
    assert s.client.post('/api/online-flash/jobs',json=body).status_code == 422
    headers={'X-MKLink-Request-Id':'gui-online'}
    response=s.client.post('/api/online-flash/jobs',json=body,headers=headers)
    assert response.status_code==200, response.text
    created=response.json()
    assert created['request_id']=='gui-online' and created['job_id']=='online-test'
    assert s.waiting.wait(2)
    assert s.client.post('/api/probe/version').status_code==409
    s.release.set()
    result=terminal(s.client,created['runtime_job_id'])
    assert result['action']=='online_flash' and result['state']=='succeeded'
    duplicate=s.client.post('/api/online-flash/jobs',json=body,headers=headers)
    assert duplicate.status_code==200, duplicate.text
    assert duplicate.json()['runtime_job_id']==created['runtime_job_id']
    assert len(s.calls)==1
    assert s.client.post('/api/online-flash/jobs',json={**body,'frequency':2_000_000},headers=headers).status_code==409


def test_gui_online_journal_failure_prevents_start(security,monkeypatch):
    s=security
    def fail():raise OSError('unavailable')
    monkeypatch.setattr(s.control.jobs,'save',fail)
    response=s.client.post('/api/online-flash/jobs',json=dict(actions=['connect','disconnect'],
        probe_id='SERIAL',target_part='nrf54l15'),headers={'X-MKLink-Request-Id':'gui-refused'})
    assert response.status_code==503
    assert not s.calls and not s.control.jobs.jobs


def test_gui_start_validation_failure_is_retained_without_replay(security):
    s=security
    body=dict(actions=['connect','disconnect'],probe_id='SERIAL',target_part='')
    headers={'X-MKLink-Request-Id':'invalid-gui'}
    response=s.client.post('/api/online-flash/jobs',json=body,headers=headers)
    assert response.status_code==422
    jobs=s.client.get('/api/runtime/jobs/').json()['jobs']
    assert len(jobs)==1 and jobs[0]['state']=='failed'
    assert s.client.post('/api/online-flash/jobs',json=body,headers=headers).status_code==409
    assert not s.calls


@pytest.mark.parametrize('ending', ['cancel-observer', 'stop'])
def test_gui_job_retains_ownership_and_existing_stop_path(security, monkeypatch, ending):
    import asyncio
    s = security
    body = dict(actions=['connect', 'disconnect'], probe_id='SERIAL', target_part='nrf54l15')
    headers = {'X-MKLink-Request-Id': 'gui-lifecycle'}
    created = s.client.post('/api/online-flash/jobs', json=body, headers=headers).json()
    assert s.waiting.wait(2)
    assert not s.control.operation_lock.locked()
    assert s.client.post('/api/online-flash/jobs', json=body, headers=headers).status_code == 409
    if ending == 'cancel-observer':
        async def cancel():
            next(iter(s.control.jobs.tasks)).cancel()
            await asyncio.sleep(.01)
        s.client.portal.call(cancel)
        assert s.control.jobs.active is not None
        assert s.client.post('/api/probe/version').status_code == 409
        assert s.client.post('/_runtime/stop', json={'confirm': True}).status_code == 409
        s.release.set()
        assert terminal(s.client, created['runtime_job_id'])['state'] == 'unknown'
    else:
        def stop(job_id):
            assert job_id == created['job_id']
            s.outcome.state = JobState.STOPPED
            s.release.set()
            return {'job_id': job_id, 'state': 'stopping'}
        monkeypatch.setattr(s.services.job_manager, 'stop', stop, raising=False)
        assert s.client.post('/api/online-flash/jobs/online-test/stop').status_code == 200
        result = terminal(s.client, created['runtime_job_id'])
        assert result['state'] == 'failed' and result['result']['online_state'] == 'stopped'
    assert len(s.calls) == 1
