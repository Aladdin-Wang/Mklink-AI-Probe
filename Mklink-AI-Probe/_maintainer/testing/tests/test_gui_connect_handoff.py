"""A GUI's first Connect initializes the selected probe before retargeting."""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from mklink import runtime
from mklink.remote.api import create_app


@pytest.mark.parametrize('fails', [False, True])
def test_connect_target_uses_one_scoped_request_and_always_releases_presence(monkeypatch, fails):
    info = {'port': 8765, 'token': 'test'}
    lease = Mock()
    factory = Mock(return_value=lease)
    request = Mock(side_effect=runtime.RuntimeErrorResponse('failed') if fails else None,
                   return_value={'connected': True})
    monkeypatch.setattr(runtime, 'RuntimeClient', factory)
    monkeypatch.setattr(runtime, 'request', request)
    options = {'port': 'COM-old', 'probe': 'old-id', 'axf': 'symbols.axf',
               'mcu': 'auto', 'restore_last': True, 'elf_backend': 'pyelftools'}
    if fails:
        with pytest.raises(runtime.RuntimeErrorResponse):
            runtime.connect_gui_target(info, options)
    else:
        assert runtime.connect_gui_target(info, options) == {'connected': True}
    lease.connect.assert_called_once_with(scope='uart')
    factory.assert_called_once_with(info=info, kind='cli', name='GUI connection handoff')
    lease.close.assert_called_once_with()
    request.assert_called_once_with(info, 'POST', '/api/device/connect',
                                   {**{k: v for k, v in options.items() if k not in {'port', 'probe'}},
                                    'reuse_connected': True})
