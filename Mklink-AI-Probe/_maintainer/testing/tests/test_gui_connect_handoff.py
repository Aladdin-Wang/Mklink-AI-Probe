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
                                   {k: v for k, v in options.items() if k not in {'port', 'probe'}})


@pytest.mark.parametrize('case', ['switch', 'same', 'failure', 'invalid', 'select_only'])
def test_runtime_selection_connects_before_returning_handoff(tmp_path, monkeypatch, case):
    app = create_app(auth_token=None, project_root=str(tmp_path))
    state = app.state.mklink_state
    state.update(shared_runtime=True, shared_probe_id='current')
    selected = {'probe_id': 'current' if case == 'same' else 'other'}
    monkeypatch.setattr('mklink.probes.select_probe', lambda selector: selected)
    info = {'port': 8765, 'token': 'test', 'probe_id': selected['probe_id']}
    ensure = Mock(return_value=info)
    connect = Mock(side_effect=runtime.RuntimeErrorResponse('no target') if case == 'failure' else None)
    monkeypatch.setattr(runtime, 'ensure_runtime', ensure)
    monkeypatch.setattr(runtime, 'connect_gui_target', connect)
    body = {'port': 'COM7'}
    if case != 'select_only':
        body['connect'] = 'invalid' if case == 'invalid' else {'restore_last': True}
    with TestClient(app) as client:
        response = client.post('/api/runtime/select', json=body)
    if case == 'invalid':
        assert response.status_code == 422
        ensure.assert_not_called()
        connect.assert_not_called()
    elif case == 'same':
        assert response.json() == {'same_runtime': True}
        ensure.assert_not_called()
        connect.assert_not_called()
    else:
        ensure.assert_called_once_with(project_root=str(tmp_path), probe='other')
        if case == 'select_only':
            connect.assert_not_called()
        else:
            connect.assert_called_once_with(info, body['connect'])
        assert response.status_code == (409 if case == 'failure' else 200), response.text
        if case == 'failure':
            assert 'runtime_url' not in response.json()
