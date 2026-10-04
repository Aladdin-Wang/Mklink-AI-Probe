"""SystemView report readers share one history and detect incomplete captures."""
import pytest
from mklink.remote.dashboards import SystemViewStreamManager


def test_independent_readers_open_at_tail_and_page_without_consuming_events():
    manager = SystemViewStreamManager()
    manager._process_events([{'kind': 'init'}], now=0)
    first = manager.read_history()
    second = manager.read_history()
    assert first['next_seq'] == 1 and first['points'] == []
    events = [{'kind': 'task_start_exec', 'task_id': n} for n in range(3)]
    manager._process_events(events, now=0)
    page = manager.read_history(first['session'], first['next_seq'], 2)
    assert [p['task_id'] for p in page['points']] == [0, 1]
    assert page['dropped'] == 0 and page['next_seq'] == 3
    tail = manager.read_history(page['session'], page['next_seq'])
    assert [p['task_id'] for p in tail['points']] == [2]
    assert len(manager.read_history(second['session'], second['next_seq'])['points']) == 3
    page['points'][0]['task_id'] = 99
    assert manager.get_history()[1]['task_id'] == 0
    assert all('capture_seq' not in e for e in events)


def test_eviction_reports_gaps_including_nonprefix_time_trimming():
    manager = SystemViewStreamManager()
    manager._history_buffer_us = 10
    cursor = manager.read_history()
    manager._process_events([{'kind': 'init'}, {'t_us': 0}, {'t_us': 20}], now=0)
    page = manager.read_history(cursor['session'], 0)
    assert [e['capture_seq'] for e in page['points']] == [1, 3]
    assert page['dropped'] == 1
    manager._max_history = 1
    manager._process_events([{'t_us': 21}, {'t_us': 22}], now=0)
    page = manager.read_history(cursor['session'], 3)
    assert page['next_seq'] == 5 and page['dropped'] == 1


def test_reset_invalidates_old_cursor_even_when_new_sequence_matches():
    manager = SystemViewStreamManager()
    before = manager.read_history()
    manager._reset_history()
    with pytest.raises(RuntimeError, match='capture changed'):
        manager.read_history(before['session'], 0)
    assert manager.read_history()['session'] != before['session']


@pytest.mark.parametrize('arguments', [{'after': 0}, {'session': 'x'}, {'limit': 0},
                                      {'limit': 501}, {'limit': True}])
def test_invalid_cursor_arguments_are_rejected(arguments):
    with pytest.raises(ValueError):
        SystemViewStreamManager().read_history(**arguments)


def test_history_cursor_api_and_runtime_dispatch_use_same_manager(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from mklink.remote.api import create_app
    from mklink.remote import dashboards
    from mklink.runtime_api import install_runtime
    from test_shared_runtime import attach, call
    monkeypatch.setattr(dashboards, '_managers', {})
    monkeypatch.setattr('mklink.probes.inventory', lambda: [])
    app = create_app(project_root=str(tmp_path))
    app.state.mklink_state['device'] = SimpleNamespace(
        connected=True, port='TEST', axf_status={'loaded': False}, state=None,
        mcu_name='test', idcode=0, close=lambda: None)
    control = install_runtime(app, {'port': 8765, 'token': 'test-secret', 'instance_id': 'sv-history'})
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token': 'test-secret'}) as client:
        session = attach(client)
        cursor = call(client, session, 'systemview_capture_history').json()
        manager = dashboards.get_managers()['systemview']
        manager._process_events([{'kind': 'task_start_exec', 'task_id': 7}], now=0)
        args = {'session': cursor['session'], 'after': cursor['next_seq']}
        result = call(client, session, 'systemview_capture_history', args)
        assert result.status_code == 200, result.text
        assert result.json()['points'][0]['task_id'] == 7
        assert client.get('/api/dash/systemview/history').json()['points'][0]['task_id'] == 7
        assert call(client, session, 'systemview_capture_history', {'after': 0}).status_code == 422
        manager._reset_history()
        assert call(client, session, 'systemview_capture_history', args).status_code == 409
        client.post('/_runtime/detach', json={'session_id': session})
        assert not control.sessions
