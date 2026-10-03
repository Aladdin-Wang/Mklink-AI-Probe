"""Discovery is passive; a missing/ambiguous selection cannot touch another probe."""
import json
import sys
from unittest.mock import Mock

import pytest
from mklink import cli, discovery
from mklink.device import Device, DeviceNotConnectedError
from mklink.probes import inventory, select_probe
from mklink.runtime import RuntimeErrorResponse
from test_probe_identity import port


@pytest.fixture
def devices(monkeypatch,tmp_path):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR',str(tmp_path/'runtime'))
    ports=[port('COM10','first'),port('COM20','second','1-2:x.4')]
    monkeypatch.setattr('serial.tools.list_ports.comports',lambda:ports)
    monkeypatch.setattr(discovery.serial,'Serial',lambda *a,**kw:pytest.fail('Passive discovery opened a serial port'))
    return ports


@pytest.mark.parametrize('serial',[None,'missing','logical-probe-id','FIRST'])
def test_inventory_and_serial_lookup_share_passive_candidates(devices,serial):
    result=discovery.find_mklink_cdc_port(serial)
    assert result==('COM10' if serial=='FIRST' else None)
    assert {p['port'] for p in inventory()}=={'COM10','COM20'}
    assert {p.device for p in discovery.discover_mklink_command_ports()}=={'COM10','COM20'}


def test_saved_com_does_not_choose_one_of_two_devices(devices,monkeypatch,tmp_path):
    monkeypatch.setattr('mklink.project_config.load_config',lambda *_:{'com_port':'COM10'})
    factory=Mock();monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge',factory)
    save=Mock();monkeypatch.setattr('mklink.project_config.save_config',save)
    with pytest.raises(DeviceNotConnectedError,match='No unique'):
        Device(project_root=str(tmp_path))._connect()
    factory.assert_not_called();save.assert_not_called()
    with pytest.raises(SystemExit,match='Multiple probes'):cli._resolve_port(None)


def test_unique_automatic_connection_ignores_stale_com_and_never_saves(devices,monkeypatch,tmp_path):
    devices.pop()
    config={'com_port':'COM_OLD'}
    monkeypatch.setattr('mklink.project_config.load_config',lambda *_:config)
    save=Mock();monkeypatch.setattr('mklink.project_config.save_config',save)
    bridge=Mock();bridge.connect.return_value=True
    factory=Mock(return_value=bridge);monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge',factory)
    monkeypatch.setattr('mklink.serial._port._PortLock',lambda *_:pytest.fail('Global discovery lock was used'))
    device=Device(project_root=str(tmp_path),initialize_target_now=False)
    device._connect()
    assert device.port=='COM10'
    factory.assert_called_once_with('COM10');bridge.connect.assert_called_once()
    save.assert_not_called();assert config=={'com_port':'COM_OLD'}
    device.close()


@pytest.mark.parametrize('explicit',[False,True])
@pytest.mark.parametrize('failure',[False,TimeoutError('selected probe unavailable')])
def test_failed_connection_never_retries_or_switches(devices,monkeypatch,explicit,failure):
    if not explicit:devices.pop()
    bridge=Mock()
    if isinstance(failure,Exception):bridge.connect.side_effect=failure
    else:bridge.connect.return_value=False
    factory=Mock(return_value=bridge);monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge',factory)
    with pytest.raises((DeviceNotConnectedError,TimeoutError)):
        Device(port='COM10' if explicit else None)._connect()
    factory.assert_called_once_with('COM10');bridge.connect.assert_called_once();bridge.close.assert_called_once()


def test_cli_probe_list_no_config_change_or_target_initialization(devices,monkeypatch,capsys):
    monkeypatch.setattr('mklink.project_config.save_config',lambda *a:pytest.fail('Enumeration wrote project config'))
    monkeypatch.setattr('mklink.device.initialize_target',lambda *a:pytest.fail('Enumeration initialized target'))
    monkeypatch.setattr(sys,'argv',['mklink','probes','list'])
    cli.main()
    rows=json.loads(capsys.readouterr().out)
    assert {p['port'] for p in rows}=={'COM10','COM20'}
    assert all(p['identity_stable'] for p in rows)


def test_old_discover_command_is_removed(devices,monkeypatch):
    monkeypatch.setattr(sys,'argv',['mklink','discover'])
    with pytest.raises(SystemExit) as error:cli.main()
    assert error.value.code==2


def test_unplugged_identity_does_not_select_remaining_probe(devices):
    selected=select_probe('COM10')['probe_id']
    devices.pop(0)
    with pytest.raises(RuntimeErrorResponse,match='missing or ambiguous'):select_probe(selected)
    assert discovery.find_mklink_cdc_port('first') is None
    assert select_probe('COM20')['port']=='COM20'


def test_hpm_serial_mapping_missing_never_constructs_a_device(devices):
    from mklink.cmsis_dap.backend import HpmRomBackend
    from mklink.cmsis_dap.errors import FlashError
    factory=Mock()
    backend=HpmRomBackend(device_factory=factory)
    with pytest.raises(FlashError,match='selected probe'):
        backend.connect('missing','HPM5300',1000000,board='hpm5300evk')
    factory.assert_not_called()
