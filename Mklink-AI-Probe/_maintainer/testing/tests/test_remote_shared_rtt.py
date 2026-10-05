import pytest
from mklink.remote.protocol import AgentOperationError, RequestValidationError
from test_remote_shared_target import target, context
from test_shared_runtime import runtime


@pytest.fixture
def rtt(target, monkeypatch):
    router, http, control, calls, managers = target
    manager = managers['rtt']
    manager.session = 'capture-one'
    readers = []
    class Reader:
        def __init__(self, info):
            self.closed = False
            readers.append(self)
        def read(self, timeout):
            assert not self.closed
            return {'text': 'hello\r', 'error': None, 'dropped_bytes': 0, 'missing_batches': 0}
        def close(self):
            self.closed = True
    monkeypatch.setattr('mklink.remote.shared_rtt.RttSubscription', Reader)

    @control.app.get('/api/dash/rtt/status')
    async def status():
        return {'running': manager.running, 'session': manager.session, 'encoding': 'utf-8',
                'line_parser': {'dropped_lines': 1, 'dropped_chars': 70000}}

    @control.app.post('/api/dash/rtt/write')
    async def write(body: dict):
        calls.append(body['data_hex'])
        return {'sent_bytes': len(bytes.fromhex(body['data_hex']))}

    def dispatch(action, params=None, name='first'):
        return router.dispatch('rtt.'+action, params or {}, context(router, name))
    return router, control, calls, manager, readers, dispatch


def test_rtt_shared_owner_borrower_read_write_and_stop(rtt):
    router, control, calls, manager, readers, dispatch = rtt
    assert router.capabilities()['stream.rtt'].version == '2'
    assert not dispatch('start')['reused']
    assert dispatch('start', name='second')['reused']
    reading = dispatch('read', {'timeout': 0})
    assert reading['text'] == 'hello\r'
    assert reading['capture']['line_parser'] == {'dropped_lines': 1, 'dropped_chars': 70000}
    assert dispatch('write', {'data': '中\n'}) == {'sent_bytes': 4}
    with pytest.raises(AgentOperationError) as error:
        dispatch('stop')
    assert error.value.data['status'] == 409 and manager.running
    assert not dispatch('stop', name='second')['capture_stopped']
    assert readers[1].closed and not readers[0].closed
    assert dispatch('stop')['capture_stopped']
    assert all(r.closed for r in readers) and not control.sessions
    assert calls == ['start', '中\n'.encode().hex(), 'stop']


def test_generation_change_and_reconfigure_do_not_silently_replace_subscription(rtt):
    router, _, calls, manager, readers, dispatch = rtt
    dispatch('start')
    with pytest.raises(RequestValidationError):
        dispatch('start', {'channel': 1})
    assert not readers[0].closed
    assert dispatch('read')['session'] == 'capture-one'
    manager.session = 'another'
    with pytest.raises(AgentOperationError):
        dispatch('read')
    assert calls == ['start']
    router.client_closed('first')
    assert readers[0].closed


@pytest.mark.parametrize('params', [{'timeout': -1}, {'timeout': 6}, {'timeout': True}, {'timeout': float('nan')}, {'duration': 1}])
def test_read_bounds_and_removed_duration(rtt, params):
    *_, dispatch = rtt
    dispatch('start')
    with pytest.raises(RequestValidationError):
        dispatch('read', params)


@pytest.mark.parametrize('data', ['', '中'*86, '\ud800'])
def test_write_rejects_oversized_or_invalid_text_before_device(rtt, data):
    _, _, calls, _, _, dispatch = rtt
    dispatch('start')
    with pytest.raises((RequestValidationError, AgentOperationError)):
        dispatch('write', {'data': data})
    assert calls == ['start']


def test_remote_disconnect_does_not_stop_gui_capture(rtt):
    router, control, calls, manager, readers, dispatch = rtt
    manager.running = True
    dispatch('start')
    dispatch('start', name='second')
    router.client_closed('first')
    assert readers[0].closed and not readers[1].closed
    assert dispatch('read', name='second')['capture']['running']
    router.close()
    assert manager.running and not calls and not control.sessions


def test_sdk_helpers_preserve_diagnostics_and_use_confirmed_write_count():
    from unittest.mock import Mock
    from mklink.remote.client import RemoteClient, RemoteClientError
    client = object.__new__(RemoteClient)
    client.call = Mock(return_value={'text': 'hello', 'missing_batches': 1})
    assert client.rtt_read(0)['missing_batches'] == 1
    client.call.assert_called_once_with('rtt_read', timeout=0)
    with pytest.raises(RemoteClientError, match='lost'):
        client.wait_for_rtt('hello')
    client.call = Mock(return_value={'sent_bytes': 3})
    assert client.rtt_write('中')
    client.call.return_value = {'sent_bytes': 1}
    assert not client.rtt_write('中')

@pytest.mark.parametrize('channel', range(8))
def test_channel_read_reuses_shared_cursor_and_binary_write(rtt, channel):
    from unittest.mock import Mock
    router, _, _, _, _, dispatch = rtt
    dispatch('start')
    capture = router._target._captures[('first', 'rtt')]
    original_call = capture.client.call
    page = {'channel': channel, 'cursor': 123, 'data_hex': '00ff80', 'lost_bytes': 7}
    routed = Mock(return_value=page)
    def call(name, arguments=None):
        if name == 'rtt_status':
            return original_call(name, arguments)
        return routed(name, arguments)
    capture.client.call = call
    assert dispatch('read_channel', {'channel': channel, 'cursor': 120}) == page
    routed.assert_called_once_with('rtt_read_channel', {'channel': channel, 'cursor': 120, 'session': 'capture-one'})
    routed.reset_mock()
    dispatch('write', {'channel': channel, 'data_hex': '00ff80'})
    routed.assert_called_once_with('rtt_write', {'channel': channel, 'data_hex': '00ff80'})


@pytest.mark.parametrize('action,params', [
    ('read_channel', {'channel': True}), ('read_channel', {'channel': 8}),
    ('read_channel', {'cursor': -1}), ('read_channel', {'cursor': True}),
    ('write', {'data_hex': '00', 'channel': True}),
    ('write', {'data_hex': '00', 'channel': 8}),
    ('write', {'data_hex': '00', 'data': 'x'}),
    ('write', {'data_hex': 'ff'*257}), ('write', {'data_hex': '0g'}),
    ('write', {'data_hex': '0'}), ('write', {'data_hex': '00 ff'}),
])
def test_channel_parameters_rejected_before_data_operation(rtt, action, params):
    _, _, calls, _, _, dispatch = rtt
    dispatch('start')
    with pytest.raises(RequestValidationError):
        dispatch(action, params)
    assert calls == ['start']


def test_binary_client_helper_and_channel_cursor():
    from unittest.mock import Mock
    from mklink.remote.client import RemoteClient
    client = object.__new__(RemoteClient)
    client.call = Mock(return_value={'sent_bytes': 3})
    assert client.rtt_write(b'\x00\xff\x80', channel=7)
    client.call.assert_called_once_with('rtt_write', data_hex='00ff80', channel=7)
    client.call.reset_mock()
    client.rtt_read_channel(7, 123)
    client.call.assert_called_once_with('rtt.read_channel', channel=7, cursor=123)
