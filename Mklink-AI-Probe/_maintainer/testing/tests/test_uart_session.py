"""Non-CLI callers share the same attachment and cleanup policy."""
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory


def test_two_sdk_borrowers_release_independently_without_stopping_gui(scan_cli):
    from mklink.uart_session import modbus_session
    _, _, http, control, manager, _ = scan_cli
    assert http.post('/api/dash/modbus/start', json={
        'port': 'TEST', 'registers': [], 'slave': 7}).status_code == 200
    settings = {'port': 'TEST', 'baudrate': 9600, 'bytesize': 8,
                'parity': 'N', 'stopbits': 1}
    with modbus_session(settings, kind='sdk', name='Agent first') as first:
        with modbus_session(settings, kind='sdk', name='Agent second') as second:
            assert len(control.sessions) == 2
            assert first.session_id != second.session_id
            assert second.call('modbus_status')['slave'] == 7
        assert len(control.sessions) == 1
        assert first.call('modbus_status')['running']
    assert not control.sessions and manager.running


def test_shared_context_forwards_project_and_probe_without_cli_defaults(monkeypatch, tmp_path):
    from mklink import runtime
    from mklink.uart_session import uart_session
    events = []
    class Client:
        def __init__(self, **options): events.append(('new', options))
        def connect(self, **options): events.append(('connect', options))
        def call(self, method, *args):
            events.append((method, args))
            if method.endswith('_status'): return {'running': False}
        def close(self): events.append(('close',))
    monkeypatch.setattr(runtime, 'RuntimeClient', Client)
    with uart_session('serial', {'ports': []}, project_root=tmp_path,
                      probe='chosen-probe', kind='sdk', name='Agent connection'):
        pass
    assert events[0] == ('new', {'project_root': tmp_path, 'kind': 'sdk', 'name': 'Agent connection'})
    assert events[1] == ('connect', {'scope': 'uart', 'probe': 'chosen-probe'})
    assert [event[0] for event in events] == [
        'new', 'connect', 'serial_status', 'serial_start', 'serial_stop', 'close']
