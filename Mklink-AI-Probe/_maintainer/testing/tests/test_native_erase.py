"""Erasure must prepare the selected target algorithm and never infer success from an address."""
from dataclasses import replace
from types import SimpleNamespace
import sys

import pytest
from fastapi.testclient import TestClient

from mklink._types import DeviceState
from mklink.cmsis_dap.algorithm_catalog import FlashAlgorithm
from mklink.device import Device, DeviceError
from mklink.flash import MKLinkFlash
from test_runtime_jobs import terminal, fixture


@pytest.fixture
def native(monkeypatch, tmp_path):
    algorithm = FlashAlgorithm('selected', 'STM32F103RET6', 'test.FLM', 0x08000000,
        0x80000, 0x20000000, 0x10000, True, 'builtin-pack', 'fixture', 'fixture',
        sector_sizes=((0, 2048),))
    algorithms = [algorithm];calls = []
    device = Device(port='TEST', mcu='STM32F103RET6', project_root=str(tmp_path))
    device._connected = True
    device._bridge = SimpleNamespace(idcode=0x1ba01477, current_mcu='STM32F103RET6', state=DeviceState.READY)
    device._flash = SimpleNamespace(
        load_flm=lambda *args: calls.append(('load', args)) or True,
        erase_chip=lambda *args: calls.append(('chip', args)) or True,
        erase_sector=lambda *args: calls.append(('sector', args)) or True)
    monkeypatch.setattr('mklink.cmsis_dap.algorithm_catalog.discover_flash_algorithms', lambda target: algorithms)
    monkeypatch.setattr('mklink.cmsis_dap.algorithm_catalog.deploy_algorithm_to_probe',
        lambda selected, **kwargs: calls.append(('deploy', selected.algorithm_id, kwargs['disk_root'])) or '/FLM/test.FLM')
    monkeypatch.setattr('mklink.probes.select_probe', lambda port: {'probe_id': 'chosen', 'identity_stable': True})
    monkeypatch.setattr('mklink.probes.bound_probe', lambda: 'chosen')
    monkeypatch.setattr('mklink.probe_volumes.resolve_volume', lambda probe: {'root': str(tmp_path/'probe')})
    return device, algorithms, calls


@pytest.mark.parametrize('sector', [False, True])
def test_fresh_erase_loads_exact_algorithm_before_command(native, sector, tmp_path):
    device, _, calls = native
    assert (device.erase_sector(0x08005000) if sector else device.erase_chip())
    assert calls == [('deploy', 'selected', tmp_path/'probe'),
                     ('load', ('/FLM/test.FLM', '0x08000000', '0x20000000')),
                     ('sector', ('0x08005000',)) if sector else ('chip', ('0x08000000',))]


@pytest.mark.parametrize('address', [None, True, -1, 0x100000000, 0x08000001, 0x08080000])
def test_invalid_sector_never_deploys_or_erases(native, address):
    device, _, calls = native
    with pytest.raises((DeviceError, ValueError)): device.erase_sector(address)
    assert not calls


@pytest.mark.parametrize('changes,address', [({'sector_sizes': ()}, 0x08000000),
    ({'flash_size': 3000}, 0x08000800), ({'ram_start': 0}, 0x08000000)])
def test_incomplete_geometry_or_ram_is_rejected(native, changes, address):
    device, algorithms, calls = native
    algorithms[0] = replace(algorithms[0], **changes)
    with pytest.raises(DeviceError): device.erase_sector(address)
    assert not calls


def test_ambiguous_geometry_requires_explicit_algorithm(native):
    device, algorithms, calls = native
    algorithms.append(replace(algorithms[0], algorithm_id='other', sector_sizes=((0, 1024),)))
    with pytest.raises(DeviceError, match='Ambiguous'): device.erase_sector(0x08005000)
    assert not calls
    assert device.erase_sector(0x08005000, algorithm_id='selected')
    assert calls[0][1] == 'selected'


def test_hpm_unknown_target_and_no_idcode_do_not_prepare(native):
    device, _, calls = native
    with pytest.raises(DeviceError, match='HPM'): device.erase_chip(target_part='HPM6E80')
    device._mcu_hint = 'stm32f1'
    with pytest.raises(DeviceError, match='exact'): device.erase_chip()
    device._bridge.idcode = 0
    with pytest.raises(DeviceError, match='IDCODE'): device.erase_chip(target_part='STM32F103RET6')
    assert not calls


def test_failed_flm_load_never_sends_erase(native):
    device, _, calls = native
    device._flash.load_flm = lambda *args: False
    with pytest.raises(DeviceError, match='initialization'): device.erase_chip()
    assert [c[0] for c in calls] == ['deploy']


def test_usb_identity_mismatch_prevents_deployment(native, monkeypatch):
    device, _, calls = native
    monkeypatch.setattr('mklink.probes.bound_probe', lambda: 'neighbor')
    with pytest.raises(DeviceError, match='identity'): device.erase_chip()
    assert not calls


@pytest.mark.parametrize('reply,expected', [('cmd.erase_sector_flash(0x08005000)\r\n-1\r\n>>>', False),
    ('error 10', False), ('-10', False), ('0x0', False), ('', False), ('\r\n0\r\n>>>', True)])
def test_sector_success_requires_exact_zero_line(reply, expected):
    commands = []
    flash = MKLinkFlash(SimpleNamespace(send_command=lambda command, **_: commands.append(command) or reply))
    assert flash.erase_sector('0x08005000') is expected
    assert len(commands) == 1


def test_real_shared_sector_job_uses_preparation_and_retains_one_result(native, monkeypatch, tmp_path):
    from mklink.remote.api import create_app
    from mklink.runtime_api import install_runtime
    device, _, calls = native
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    app = create_app(project_root=str(tmp_path));app.state.mklink_state['device'] = device
    control = install_runtime(app, {'port': 8765, 'token': 'test', 'instance_id': 'erase-test'})
    payload = {'action': 'erase_sector', 'request_id': 'one-sector', 'confirm': True,
               'arguments': {'address': '0x08005000', 'target_part': 'STM32F103RET6'}}
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test'}) as client:
        assert client.post('/api/device/erase-sector', json=payload['arguments']).status_code == 409
        accepted = client.post('/api/runtime/jobs/', json=payload)
        assert accepted.status_code == 202, accepted.text
        result = terminal(client, accepted.json()['job_id'])
        assert result['state'] == 'succeeded', result
        assert client.post('/api/runtime/jobs/', json=payload).json()['job_id'] == result['job_id']
        assert [c[0] for c in calls] == ['deploy', 'load', 'sector']
        assert len(control.jobs.jobs) == 1


def test_cli_sector_erase_uses_existing_job_client(monkeypatch):
    from mklink import cli, runtime_cli
    calls=[]
    class Client:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): calls.append(('connect', kwargs))
        def start_job(self, action, **kwargs):
            calls.append((action, kwargs));return {'job_id': 'j', 'state': 'succeeded'}
        def close(self): calls.append(('close', {}))
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', Client)
    monkeypatch.setattr(sys, 'argv', ['mklink', 'erase', '--probe', 'selected', '--address', '0x08005000',
        '--target-part', 'STM32F103RET6', '--algorithm-id', 'selected', '--request-id', 'once'])
    cli.main()
    assert calls[1] == ('erase_sector', {'arguments': {'target_part': 'STM32F103RET6',
        'algorithm_id': 'selected', 'address': 0x08005000}, 'request_id': 'once', 'confirm': True})
    assert calls[-1][0] == 'close'


@pytest.mark.parametrize('arguments', [{}, {'address': True}, {'address': -1}, {'address': 1.5},
    {'address': 0, 'unknown': 1}, {'address': 0, 'target_part': None}, {'address': 0, 'algorithm_id': ''}])
def test_invalid_sector_job_is_not_journaled(fixture, arguments):
    client, control, calls, _, _ = fixture
    response = client.post('/api/runtime/jobs/', json={'action': 'erase_sector',
        'arguments': arguments, 'request_id': 'invalid', 'confirm': True})
    assert response.status_code == 422 and not control.jobs.jobs and not calls
