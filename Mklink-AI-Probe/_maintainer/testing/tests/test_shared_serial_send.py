"""Serial CLI sends through the shared UART owner, with validation before attach."""
from types import SimpleNamespace

import pytest

from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory, uart_attach, call
from mklink.serial._monitor import SerialMonitor as RealMonitor


def arguments(**changes):
    return SimpleNamespace(**(dict(serial_command='send', port='TEST', baud=19200,
        databits=7, stop=2, parity='E', send_data='00 41 FF', hex=True,
        count=1, delay=0, probe=None) | changes))


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('hex_mode', [False, True])
def test_send_creates_or_borrows_matching_port_without_changing_other_ports(scan_cli, uart_app, existing, hex_mode, capsys):
    cli, _, http, control, _, _ = scan_cli
    manager = uart_app[2]['serial']
    ports = [{'port': 'OTHER', 'baudrate': 9600}, {'port': 'TEST', 'baudrate': 19200,
              'databits': 7, 'stopbits': 2, 'parity': 'E'}]
    if existing:
        assert http.post('/api/dash/serial/start', json={'ports': ports}).status_code == 200
        before = manager.get_status()['config']
        monitor = manager._monitor
    args = arguments(count=2, hex=hex_mode, send_data='00 41 FF' if hex_mode else '测试\r\n')
    cli._cli_serial_dispatch(args)
    expected = bytes.fromhex('00 41 FF') if hex_mode else '测试\r\n'.encode()
    assert uart_app[4].sent == [('TEST', expected)] * 2
    assert not control.sessions and manager.running == existing
    if existing:
        assert manager._monitor is monitor and manager.get_status()['config'] == before
    else:
        assert not manager.worker_alive and manager.get_status()['config'] == [ports[1]]
    assert capsys.readouterr().out.count('[TX]') == 2
    assert control.app.state.mklink_state['device'] is None


@pytest.mark.parametrize('params', [
    {'count': 0}, {'count': -1}, {'count': True}, {'count': 1.5},
    {'delay': -1}, {'delay': float('nan')}, {'delay': float('inf')}, {'delay': True}, {'delay': 3601},
    {'baud': 0}, {'baud': True}, {'baud': 4000001}, {'baud': 9600.5},
    {'databits': 4}, {'databits': True}, {'stop': 3}, {'stop': True}, {'parity': 'X'},
    {'send_data': 'invalid'}, {'send_data': ''}, {'send_data': '', 'hex': False},
])
def test_invalid_send_is_nonzero_without_attach_or_io(monkeypatch, params, capsys):
    from mklink import cli
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **_: pytest.fail('invalid send attached'))
    with pytest.raises(SystemExit) as caught: cli._cli_serial_dispatch(arguments(**params))
    assert caught.value.code and '[TX]' not in capsys.readouterr().out


@pytest.mark.parametrize('field,value', [('baud', 9600), ('databits', 8), ('stop', 1), ('parity', 'N'), ('port', 'OTHER')])
def test_settings_conflict_rejected_without_send_or_reconfigure(scan_cli, uart_app, field, value):
    cli, _, http, control, _, _ = scan_cli
    settings = {'ports': [{'port': 'TEST', 'baudrate': 19200, 'databits': 7, 'stopbits': 2, 'parity': 'E'}]}
    assert http.post('/api/dash/serial/start', json=settings).status_code == 200
    with pytest.raises(SystemExit, match='different port/settings'):
        cli._cli_serial_dispatch(arguments(**{field: value}))
    assert not uart_app[4].sent and not control.sessions
    assert uart_app[2]['serial'].running and uart_app[2]['serial'].get_status()['config'] == settings['ports']


@pytest.mark.parametrize('failure', ['open', 'send', 'unknown_ack'])
def test_failed_send_never_prints_success_or_retries(scan_cli, uart_app, monkeypatch, capsys, failure):
    cli, _, http, control, _, _ = scan_cli
    monitor_class = uart_app[4]
    if failure == 'open':
        def start(self): raise OSError('busy')
        monkeypatch.setattr(monitor_class, 'start', start)
    else:
        def send(self, port, data):
            self.sent.append((port, data))
            return False
        monkeypatch.setattr(monitor_class, 'send', send)
        if failure == 'unknown_ack':
            from mklink import runtime
            original = runtime.RuntimeClient
            def factory(**kwargs):
                client = original(**kwargs)
                original_call = client.call
                def lost_ack(capability, args=None):
                    if capability == 'serial_send': return {'ok': False}
                    return original_call(capability, args)
                client.call = lost_ack
                return client
            monkeypatch.setattr(runtime, 'RuntimeClient', factory)
    with pytest.raises(SystemExit): cli._cli_serial_dispatch(arguments(count=2))
    assert len(monitor_class.sent) == (1 if failure == 'send' else 0)
    assert not control.sessions and not uart_app[2]['serial'].running
    assert '[TX]' not in capsys.readouterr().out


def test_borrowed_send_failure_preserves_gui_and_other_port(scan_cli, uart_app, monkeypatch):
    cli, _, http, control, _, _ = scan_cli
    assert http.post('/api/dash/serial/start', json={'ports': [{'port':'TEST'}, {'port':'OTHER'}]}).status_code == 200
    monkeypatch.setattr(uart_app[4], 'send', lambda *args: False)
    with pytest.raises(SystemExit):
        cli._cli_serial_dispatch(arguments(baud=115200, databits=8, stop=1, parity='N'))
    assert not control.sessions and uart_app[2]['serial'].running
    assert set(uart_app[2]['serial'].get_status()['ports']) == {'TEST', 'OTHER'}


def test_protocol_transfer_refuses_send_without_io(scan_cli, uart_app):
    cli, _, http, control, _, _ = scan_cli
    http.post('/api/dash/serial/start', json={'ports': [{'port':'TEST'}]})
    manager = uart_app[2]['serial']
    manager._ymodem_status['active'] = True
    try:
        with pytest.raises(SystemExit, match='YMODEM'):
            cli._cli_serial_dispatch(arguments(baud=115200, databits=8, stop=1, parity='N'))
        assert not uart_app[4].sent and not control.sessions and manager.running
    finally:
        manager._ymodem_status['active'] = False


@pytest.mark.parametrize('failure', [None, 'short', 'removed'])
def test_actual_serial_stack_keeps_settings_and_never_replays_partial_write(scan_cli, uart_app, monkeypatch, tmp_path, failure):
    cli, _, _, control, _, _ = scan_cli
    monkeypatch.setattr('mklink.serial._monitor.SerialMonitor', RealMonitor)
    monkeypatch.setenv('MKLINK_LOCK_DIR', str(tmp_path))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [])
    class Wire:
        instances = []
        def __init__(self, **settings):
            self.settings = settings
            self.is_open = True
            self.writes = []
            self.instances.append(self)
        @property
        def in_waiting(self): return 0
        def write(self, data):
            self.writes.append(bytes(data))
            if failure == 'removed': raise OSError('removed after write')
            return 1 if failure == 'short' else len(data)
        def close(self): self.is_open = False
    monkeypatch.setattr('serial.Serial', Wire)
    if failure:
        with pytest.raises(SystemExit): cli._cli_serial_dispatch(arguments(count=2))
    else: cli._cli_serial_dispatch(arguments(count=2))
    assert len(Wire.instances) == 1
    wire = Wire.instances[0]
    assert {k: wire.settings[k] for k in ('baudrate', 'bytesize', 'stopbits', 'parity')} == {
        'baudrate': 19200, 'bytesize': 7, 'stopbits': 2, 'parity': 'E'}
    assert wire.writes == [bytes.fromhex('00 41 FF')] * (1 if failure else 2)
    assert not wire.is_open and not uart_app[2]['serial'].worker_alive and not control.sessions
