"""Removed raw-socket entrypoints must fail before connecting to hardware."""
import json
from unittest.mock import Mock

import pytest

import mklink
from mklink import cli
from mklink.remote import device_rpc


@pytest.mark.parametrize('arguments', [[], ['--backend', 'legacy'], ['--backend', 'fastapi']])
def test_removed_serve_is_rejected_before_device_access(monkeypatch, arguments):
    connect = Mock(side_effect=AssertionError('must not connect'))
    monkeypatch.setattr(mklink, 'connect', connect)
    monkeypatch.setattr('sys.argv', ['mklink', 'serve', *arguments])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    connect.assert_not_called()


def test_raw_server_public_export_is_removed():
    import mklink.remote as remote
    assert not hasattr(mklink, 'serve')
    assert not hasattr(remote, 'serve')
    assert not hasattr(remote, 'serve_fastapi')


@pytest.mark.parametrize('missing', ['--desktop-instance-id', '--desktop-port-end', '--desktop-runtime-info'])
def test_desktop_proxy_requires_complete_handshake_before_start(monkeypatch, missing):
    from mklink import runtime
    start = Mock(side_effect=AssertionError('must not start'))
    monkeypatch.setattr(runtime, 'ensure_runtime', start)
    options = {'--desktop-instance-id': 'test', '--desktop-port-end': '8799',
               '--desktop-runtime-info': 'endpoint.json'}
    argv = ['mklink', 'desktop-proxy']
    for key, value in options.items():
        if key != missing:
            argv.extend([key, value])
    monkeypatch.setattr('sys.argv', argv)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    start.assert_not_called()


def test_backend_rpc_adapter_still_encodes_binary_and_errors():
    device = Mock()
    device.read_memory.return_value = b'\x00\xff'
    dispatcher = device_rpc.DeviceDispatcher(device)
    response = json.loads(dispatcher.dispatch('read_memory', {'address': 0x20000000, 'size': 2}, 7))
    assert response['result'] == {'__bytes__': 'AP8='}
    assert response['id'] == 7
    assert json.loads(dispatcher.dispatch('missing', {}, 8))['error']['code'] == -32601
