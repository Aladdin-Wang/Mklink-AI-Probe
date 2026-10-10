"""Probe configuration must not require an attached target, on any adapter."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from mklink._types import DeviceState
from mklink.device import Device
from mklink.project_config import load_config, save_config
from mklink.remote.api import create_app
from mklink.runtime_api import install_runtime


@pytest.mark.parametrize('kind', ['gui', 'mcp', 'cli', 'sdk'])
@pytest.mark.parametrize('saved', [{'swd_clock': '20000000'}, {'debug_speed': 'high'}])
def test_connect_and_configure_without_target_through_shared_backend(tmp_path, monkeypatch, kind, saved):
    save_config(str(tmp_path), saved)
    bridge = SimpleNamespace(
        state=DeviceState.READY, idcode=0, current_mcu='', _transport_error=None,
        _ctx=SimpleNamespace(swd_clock_hz=0, idcode=0, current_mcu=''),
        connect=Mock(return_value=True), close=Mock(),
        send_command=Mock(side_effect=lambda command, **kw:
            'set clock ' + command.removeprefix('cmd.set_swd_clock(').removesuffix(')')),
    )
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge', lambda port: bridge)
    monkeypatch.setattr('mklink.device.initialize_target', lambda *a, **kw: 0)
    monkeypatch.setattr('mklink.remote.dashboards._managers', {})
    monkeypatch.setattr('mklink.probes.inventory', lambda: [
        {'probe_id': 'usb-test', 'port': 'TEST_PORT', 'serial_number': 'test', 'alias': ''}])
    def connect(**options):
        dev = Device(**options)
        dev._connect()
        return dev
    monkeypatch.setattr('mklink.connect', connect)
    app = create_app(auth_token=None, project_root=str(tmp_path))
    info = {'port': 8765, 'token': 'test-secret', 'instance_id': 'probe-only-test', 'probe_id': 'usb-test'}
    install_runtime(app, info)
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': info['token']}) as client:
        if kind == 'gui':
            response = client.post('/api/device/connect', json={'port': 'TEST_PORT'})
        else:
            response = client.post('/_runtime/attach', json={'kind': kind, 'port': 'TEST_PORT'})
        assert response.status_code == 200, response.text
        status = client.get('/api/device/status').json()
        assert status['connected'] and status['idcode'] == '0x0'
        assert status['clock_hz'] == 20_000_000 and status['clock_warning'] is None
        if kind == 'gui':
            changed = client.put('/api/config', json={'swd_clock': '30000000'})
        else:
            changed = client.post('/_runtime/call', json={
                'session_id': response.json()['session_id'], 'capability': 'set_debug_speed',
                'arguments': {'profile': 'ultra'},
            })
        assert changed.status_code == 200, changed.text
        status = client.get('/api/device/status').json()
        assert status['connected'] and status['clock_hz'] == 30_000_000
        config = load_config(str(tmp_path))
        assert config['swd_clock'] == '30000000' and config['debug_speed'] == 'ultra'
        assert all('get_idcode' not in call.args[0] for call in bridge.send_command.call_args_list)
        app.state.mklink_state['device'].close()


def test_deferred_connect_restores_profile_and_keeps_usb_when_clock_rejected(tmp_path, monkeypatch):
    from mklink.flash import FlashError
    save_config(str(tmp_path), {'swd_clock': '10000000'})
    bridge = SimpleNamespace(state=DeviceState.READY, _transport_error=None,
        connect=Mock(return_value=True), close=Mock(), _ctx=SimpleNamespace(swd_clock_hz=0))
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge', lambda port: bridge)
    monkeypatch.setattr('mklink.flash.MKLinkFlash.set_swd_clock', Mock(side_effect=FlashError('Setting rejected')))
    dev = Device(port='TEST_PORT', project_root=str(tmp_path), initialize_target_now=False)
    dev._connect()
    assert dev.connected and dev.clock_hz is None and dev.clock_warning == 'Setting rejected'
    bridge.close.assert_not_called()
    dev.close()


def test_clock_failure_does_not_hide_a_lost_usb_connection(tmp_path, monkeypatch):
    from mklink.flash import FlashError
    save_config(str(tmp_path), {'swd_clock': '10000000'})
    bridge = SimpleNamespace(state=DeviceState.READY, _transport_error=None,
        connect=Mock(return_value=True), close=Mock(), _ctx=SimpleNamespace(swd_clock_hz=0))
    def lose_usb(*args):
        bridge.state = DeviceState.ERROR
        raise FlashError('USB disconnected')
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge', lambda port: bridge)
    monkeypatch.setattr('mklink.flash.MKLinkFlash.set_swd_clock', lose_usb)
    dev = Device(port='TEST_PORT', project_root=str(tmp_path), initialize_target_now=False)
    with pytest.raises(FlashError, match='USB disconnected'):
        dev._connect()
    assert not dev.connected
    bridge.close.assert_called_once()
