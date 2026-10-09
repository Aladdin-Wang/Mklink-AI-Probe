"""Shared jobs deliver complete target options once, without direct fallback."""
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mklink.remote.api import create_app
from mklink.runtime_api import install_runtime
from test_remote_api import _connected_symbol_device
from test_runtime_jobs import terminal, fixture, body


CFG = ['0xfcf90001U', '0x00000007U', '0x00000000U', '0xf3000000U']


@pytest.mark.parametrize('fail', [False, True])
def test_real_flash_route_pauses_and_restores_capture_without_nested_lock(monkeypatch, tmp_path, fail):
    device, _ = _connected_symbol_device(tmp_path)
    calls = []
    manager = SimpleNamespace(running=True, paused=False)
    def stop():
        calls.append('stop')
        manager.running = False
    def restart():
        calls.append('restart')
        manager.running = True
    manager.stop, manager._restart_after_operation = stop, restart
    monkeypatch.setattr('mklink.remote.api.acquire_dashboard_resources', lambda *args: [])
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    def flash(**kwargs):
        assert not manager.running
        calls.append('flash')
        if fail:
            raise RuntimeError('simulated flash failure')
        return {'success': True}
    device.flash = flash
    app = create_app(project_root=str(tmp_path))
    monkeypatch.setattr('mklink.remote.dashboards.get_managers', lambda: {'rtt': manager})
    app.state.mklink_state['device'] = device
    install_runtime(app, {'port': 8765, 'token': 'test', 'instance_id': 'flash-capture',
                          'jobs_path': str(tmp_path / 'jobs.json')})
    firmware = tmp_path / 'demo.bin'
    firmware.write_bytes(b'fixture')
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test'}) as client:
        response = client.post('/api/runtime/jobs/', json={**body('flash'), 'arguments': {'firmware': str(firmware)}})
        assert response.status_code == 202, response.text
        job = terminal(client, response.json()['job_id'])
        assert job['state'] == ('unknown' if fail else 'succeeded'), job
        assert calls == ['stop', 'flash', 'restart']
        assert manager.running
        assert app.state.mklink_state['acquisition_transition']['state'] == 'restored'


def test_shared_job_preserves_hpm_options_and_deduplicates_after_file_removed(monkeypatch, tmp_path):
    device, _ = _connected_symbol_device(tmp_path)
    calls = []
    device.flash = lambda **kwargs: calls.append(kwargs) or {'success': True, 'algorithm_source': 'hpm-rom-api'}
    app = create_app(project_root=str(tmp_path))
    app.state.mklink_state['device'] = device
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    control = install_runtime(app, {'port': 8765, 'token': 'test', 'instance_id': 'flash-test',
                                    'jobs_path': str(tmp_path/'jobs.json')})
    firmware = tmp_path/'demo.bin'; firmware.write_bytes(b'fixture')
    arguments = {'firmware': str(firmware), 'target_part': 'HPM6E80', 'base_address': '0x80000400',
                 'board': 'hpm6e00evk', 'hpm_flash_cfg': CFG, 'swd_clock': 1000000,
                 'verify': True, 'reset_after': False}
    payload = {**body('flash'), 'arguments': arguments}
    with patch('mklink.remote.dashboards.stop_bridge_dashboards', return_value=[]), \
         TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test'}) as client:
        accepted = client.post('/api/runtime/jobs/', json=payload)
        assert accepted.status_code == 202, accepted.text
        job = terminal(client, accepted.json()['job_id'])
        assert job['state'] == 'succeeded', job
        assert calls == [{**arguments, 'base_address': 0x80000400}]
        assert job['result']['algorithm_source'] == 'hpm-rom-api'
        firmware.unlink()
        assert client.post('/api/runtime/jobs/', json=payload).json()['job_id'] == job['job_id']
        changed = {**payload, 'arguments': {**arguments, 'base_address': 0x80001000}}
        assert client.post('/api/runtime/jobs/', json=changed).status_code == 409
        assert len(calls) == 1 and len(control.jobs.jobs) == 1
        assert client.post('/api/device/flash', json=arguments).status_code == 409
        assert app.state.mklink_state['resource_manager'].get_status() == {}


@pytest.mark.parametrize('invalid', [
    {'verify': 1}, {'reset_after': 'false'}, {'base_address': True}, {'base_address': 1.5},
    {'base_address': -1}, {'base_address': 0x100000000}, {'base_address': '0xzz'},
    {'hpm_flash_cfg': CFG[:3]}, {'hpm_flash_cfg': [1, 2, 3, 4]},
    {'hpm_flash_cfg': ['0x100000000', *CFG[1:]]}, {'hpm_flash_cfg': None},
    {'board': 'bad();'}, {'board': ''}, {'target_part': None}, {'target_part': 'x'*129},
    {'swd_clock': True}, {'swd_clock': 0}, {'swd_clock': 100.5}, {'swd_clock': 31000000},
    {'typo_option': 1},
])
def test_invalid_options_never_accept_a_job_or_touch_device(fixture, tmp_path, invalid):
    client, control, calls, _, _ = fixture
    firmware = tmp_path/'test.bin'; firmware.write_bytes(b'fixture')
    response = client.post('/api/runtime/jobs/', json={**body('flash'),
                           'arguments': {'firmware': str(firmware), **invalid}})
    assert response.status_code == 422, response.text
    assert not calls and not control.jobs.jobs


def test_plain_api_rejects_unknown_flash_options_before_lease(tmp_path):
    app = create_app(project_root=str(tmp_path))
    with TestClient(app) as client:
        response = client.post('/api/device/flash', json={'firmware': 'unused.bin', 'base_adress': 42})
        assert response.status_code == 422
        assert app.state.mklink_state['resource_manager'].get_status() == {}


def test_cli_hpm_options_use_one_shared_job(monkeypatch, tmp_path):
    from mklink import cli, runtime_cli
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): calls.append(('connect', kwargs))
        def start_job(self, action, **kwargs):
            calls.append((action, kwargs));return {'job_id': 'test', 'state': 'succeeded'}
        def close(self): calls.append(('close', {}))
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', Client)
    monkeypatch.setattr('mklink.device.connect', lambda **_: pytest.fail('CLI opened CDC'))
    path = tmp_path/'demo.bin'
    monkeypatch.setattr(sys, 'argv', ['mklink', 'flash', '--firmware', str(path),
        '--probe', 'selected', '--target-part', 'HPM6E80', '--base-address', '0x80000400',
        '--board', 'hpm6e00evk', '--hpm-flash-cfg', *CFG, '--swd-clock', '1000000',
        '--no-reset', '--request-id', 'stable-request'])
    cli.main()
    assert calls[0][1]['probe'] == 'selected'
    assert calls[1] == ('flash', {'arguments': {'firmware': str(path.resolve()),
        'verify': True, 'reset_after': False, 'target_part': 'HPM6E80', 'base_address': 0x80000400,
        'board': 'hpm6e00evk', 'hpm_flash_cfg': CFG, 'swd_clock': 1000000},
        'request_id': 'stable-request', 'confirm': True})
    assert len(calls) == 3 and calls[-1][0] == 'close'


def test_invalid_cli_flash_does_not_attach(monkeypatch):
    from mklink import cli, runtime_cli
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', lambda **_: pytest.fail('Invalid flash attached'))
    monkeypatch.setattr(sys, 'argv', ['mklink', 'flash', '--firmware', 'demo.bin', '--base-address', '-1'])
    with pytest.raises(SystemExit, match='address'):
        cli.main()
