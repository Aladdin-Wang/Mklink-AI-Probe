"""Read-only RTT discovery uses the shared admission/capability path."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from mklink.remote.api import create_app
from mklink.runtime_api import install_runtime
from mklink.runtime_capabilities import CAPABILITIES, validate_arguments


@pytest.mark.parametrize('address', ['0x20000001', '-4', '0x100000000', 'bad'])
def test_inspect_rejects_invalid_addresses(address):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        validate_arguments('rtt_inspect', {'address': address})


@pytest.mark.parametrize('idcode', [0, 0x1ba01477])
def test_http_inspect_requires_identity_without_starting_capture(tmp_path, monkeypatch, idcode):
    app = create_app(auth_token=None, project_root=str(tmp_path))
    result = {'channels': [0, 1], 'control_block_addr': '0x20000000'}
    inspect = Mock(return_value=result)
    device = SimpleNamespace(connected=True, port='COM9', idcode=idcode, rtt_inspect=inspect)
    monkeypatch.setattr('mklink.probes.inventory', lambda: [dict(probe_id='usb-test', port='COM9', serial_number='test')])
    install_runtime(app, dict(port=8765, token='test', instance_id='fixture', probe_id='usb-test'))
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test'}) as client:
        app.state.mklink_state['device'] = device
        try:
            method, path = CAPABILITIES['rtt_inspect']
            response = client.request(method, path, json={'address': '0x20000000'})
            assert response.status_code == (200 if idcode else 400), response.text
            if idcode:
                assert response.json() == result
                inspect.assert_called_once_with(0x20000000)
            else:
                inspect.assert_not_called()
        finally:
            app.state.mklink_state['device'] = None
