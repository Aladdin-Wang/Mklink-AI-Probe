import pytest
from fastapi import HTTPException

from mklink.remote.api import start_dashboard_manager, stop_dashboard_manager_transaction
from mklink.remote.dashboards import SystemViewStreamManager
from mklink.remote.protocol import AgentOperationError, RequestValidationError
from mklink.runtime import RuntimeErrorResponse
from test_remote_shared_target import target, context
from test_shared_runtime import runtime


@pytest.fixture
def capture(target):
    router, http, control, calls, managers = target
    app = control.app
    sv = SystemViewStreamManager()
    managers['systemview'] = sv

    @app.post('/api/dash/systemview/start')
    async def start(body: dict):
        def begin():
            calls.append('sv-start')
            sv._running = True
        status, _ = await start_dashboard_manager(app.state.mklink_state, 'systemview', sv, begin)
        return {'status': status}

    @app.post('/api/dash/systemview/stop')
    async def stop():
        def end():
            calls.append('sv-stop')
            sv._running = False
        sv.stop = end
        await stop_dashboard_manager_transaction(app.state.mklink_state, 'systemview', sv)
        return {'status': 'stopped'}

    @app.get('/api/dash/systemview/history/cursor')
    async def history(session: str | None = None, after: int | None = None, limit: int = 500):
        try:
            return sv.read_history(session, after, limit)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc))

    @app.get('/api/dash/systemview/status')
    async def status():
        return {'running': sv.running, 'task_names': {'5': 'worker'}}

    def dispatch(action, params=None, name='first'):
        return router.dispatch('systemview.'+action, params or {}, context(router, name))

    return router, http, control, calls, sv, dispatch


def publish(sv, count):
    with sv._history_lock:
        for _ in range(count):
            sv._history_seq += 1
            sv._history.append({'capture_seq': sv._history_seq, 'task_id': 5})


def test_independent_cursors_bounded_pages_replay_and_loss_counts(capture):
    router, _, _, calls, sv, dispatch = capture
    assert router.capabilities()['stream.systemview'].version == '2'
    assert router.capabilities()['stream.systemview'].available
    first = dispatch('start')
    second = dispatch('start', name='second')
    assert not first['reused'] and second['reused']
    publish(sv, 600)
    page = dispatch('read', {'limit': 500})
    assert len(page['points']) == 500 and page['next_seq'] == 500
    assert dispatch('read', {'session': first['session'], 'after': 0, 'limit': 500}) == page
    assert dispatch('read', name='second') == page
    assert len(dispatch('read')['points']) == 100
    sv._history = sv._history[-10:]
    lost = dispatch('read', {'session': first['session'], 'after': 0})
    assert lost['dropped'] == 590 and len(lost['points']) == 10
    assert calls == ['sv-start']


def test_borrower_stop_detaches_and_owner_cannot_stop_other_subscribers(capture):
    router, _, control, calls, sv, dispatch = capture
    dispatch('start')
    dispatch('start', name='second')
    with pytest.raises(AgentOperationError) as error:
        dispatch('stop')
    assert error.value.data['status'] == 409 and sv.running
    assert dispatch('stop', name='second') == {'subscribed': False, 'capture_stopped': False}
    assert len(control.sessions) == 1
    assert dispatch('stop')['capture_stopped'] and not sv.running
    assert not control.sessions and calls == ['sv-start', 'sv-stop']


def test_disconnect_keeps_gui_capture_and_other_remote_subscribers(capture):
    router, _, control, calls, sv, dispatch = capture
    sv._running = True  # GUI-owned capture, no remote producer ownership.
    publish(sv, 5)
    started = dispatch('start')
    assert started['after'] == 5 and started['reused']
    dispatch('start', name='second')
    router.client_closed('first')
    publish(sv, 1)
    assert len(dispatch('read', name='second')['points']) == 1
    router.close()
    assert sv.running and not control.sessions and not calls


def test_agent_close_detaches_its_borrowers_before_stopping_own_capture(capture):
    router, _, control, calls, sv, dispatch = capture
    dispatch('start')
    dispatch('start', name='second')
    router.close()
    assert not control.sessions and not sv.running
    assert calls == ['sv-start', 'sv-stop']


def test_task_names_are_cached_and_changed_capture_rejects_old_cursor(capture):
    _, _, _, _, sv, dispatch = capture
    dispatch('start')
    assert dispatch('resolve_task_names', {'task_ids': [5, 6]}) == {
        'source': 'capture_cache', 'task_names': {'5': 'worker'}, 'unresolved': [6]}
    sv._history_session = 'another-capture'
    with pytest.raises(AgentOperationError):
        dispatch('read')


@pytest.mark.parametrize('params', [{'duration': 2}, {'limit': 501}, {'limit': True}, {'after': 0}, {'session': 'bad', 'after': 0}])
def test_invalid_or_old_read_parameters_are_rejected(capture, params):
    *_, dispatch = capture
    dispatch('start')
    with pytest.raises(RequestValidationError):
        dispatch('read', params)


@pytest.mark.parametrize('status_code', [None, 500])
def test_lost_stop_response_is_not_replayed_during_disconnect(capture, monkeypatch, status_code):
    router, _, _, calls, _, dispatch = capture
    dispatch('start')
    stream = router._target._systemview['first']
    original = stream.client.call
    def lose_response(capability, *args):
        result = original(capability, *args)
        if capability == 'systemview_stop':
            raise RuntimeErrorResponse('lost response', status_code=status_code)
        return result
    monkeypatch.setattr(stream.client, 'call', lose_response)
    with pytest.raises(AgentOperationError):
        dispatch('stop')
    router.client_closed('first')
    assert calls == ['sv-start', 'sv-stop']
