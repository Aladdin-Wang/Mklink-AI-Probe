"""CLI read/write use the existing GUI worker and validate before attaching."""
import threading
from types import SimpleNamespace

import pytest

from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory, uart_attach, call


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('fc', [1, 2, 3, 4, 5, 6, 15, 16])
def test_read_write_share_one_worker_and_keep_gui_default(scan_cli, uart_app, monkeypatch, capsys, existing, fc):
    cli, args, http, control, manager, _ = scan_cli
    factory = uart_app[3]
    operations = []
    def operation(self, address, value, slave):
        operations.append((fc, address, value, slave, threading.get_ident()))
        if fc < 5:
            return [True, False] if fc < 3 else [17, 18]
    method = {1: 'read_coils', 2: 'read_discrete_inputs', 3: 'read_holding_registers',
              4: 'read_input_registers', 5: 'write_coil', 6: 'write_register',
              15: 'write_coils', 16: 'write_registers'}[fc]
    monkeypatch.setattr(factory, method, operation, raising=False)
    if existing:
        assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'slave': 7, 'registers': [],
            'timeout': .7, 'retries': 2}).status_code == 200
    values = {5: ['ON'], 6: ['0x11'], 15: ['true', 'off'], 16: ['17', '0x12']}.get(fc, [])
    vars(args).update(fc=fc, start=2, slave=8, quantity=2, format='hex', values=values, timeout=None, retries=None)
    (cli._cli_modbus_read if fc < 5 else cli._cli_modbus_write)(args)
    expected = {5: True, 6: 17, 15: [True, False], 16: [17, 18]}.get(fc, 2)
    assert [op[:4] for op in operations] == [(fc, 2, expected, 8)]
    assert operations[0][-1] != threading.get_ident()
    assert len(factory.instances) == 1 and not control.sessions
    assert manager.running == existing
    if existing:
        status = manager.get_status()
        assert status['slave'] == 7
        assert status['connection']['timeout'] == .7 and status['connection']['retries'] == 2
    else:
        assert not manager.worker_alive and factory.instances[0].closed
        assert factory.instances[0].options['timeout'] == 1.0
        assert factory.instances[0].options['retries'] == 0
    assert f'FC{fc:02d}' in capsys.readouterr().out


@pytest.mark.parametrize('fc,values', [(5, ['treu']), (15, ['on', 'typo']),
    (5, ['true', 'false']), (6, ['17', '18']), (6, ['65536']), (16, ['-1'])])
def test_invalid_write_is_rejected_before_any_connection(monkeypatch, fc, values):
    from mklink import cli, runtime
    monkeypatch.setattr(runtime, 'RuntimeClient', lambda **_: pytest.fail('invalid write attached'))
    monkeypatch.setattr(cli, '_modbus_open_client', lambda _: pytest.fail('invalid write opened direct port'))
    args = SimpleNamespace(fc=fc, slave=8, start=0, values=values)
    with pytest.raises(ValueError):
        cli._cli_modbus_write(args)


@pytest.mark.parametrize('slave,start,quantity', [(0, 0, 1), (1, 65535, 2), (1, 0, 126)])
def test_invalid_read_is_rejected_before_any_connection(monkeypatch, slave, start, quantity):
    from mklink import cli, runtime
    monkeypatch.setattr(runtime, 'RuntimeClient', lambda **_: pytest.fail('invalid read attached'))
    monkeypatch.setattr(cli, '_modbus_open_client', lambda _: pytest.fail('invalid read opened direct port'))
    with pytest.raises(ValueError):
        cli._cli_modbus_read(SimpleNamespace(fc=3, slave=slave, start=start, quantity=quantity))


@pytest.mark.parametrize('field,value', [('timeout', .2), ('retries', 1)])
def test_explicit_timing_conflict_does_not_mutate_shared_connection(scan_cli, uart_app, monkeypatch, field, value):
    from mklink.runtime import RuntimeErrorResponse
    cli, args, http, control, manager, _ = scan_cli
    assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'registers': []}).status_code == 200
    vars(args).update(fc=6, start=0, slave=8, values=['17'], timeout=None, retries=None)
    setattr(args, field, value)
    monkeypatch.setattr(uart_app[3], 'write_register', lambda *_: pytest.fail('conflicting request reached I/O'), raising=False)
    with pytest.raises(RuntimeErrorResponse, match='different port/settings'):
        cli._cli_modbus_write(args)
    assert manager.running and not control.sessions
    assert not manager.get_status()['latest']


def test_write_failure_exits_nonzero_without_false_success(scan_cli, uart_app, monkeypatch, capsys):
    cli, args, http, control, manager, _ = scan_cli
    calls = []
    def write(*_):
        calls.append('write')
        raise TimeoutError('result unknown, do not retry')
    monkeypatch.setattr(uart_app[3], 'write_register', write, raising=False)
    vars(args).update(modbus_command='write', fc=6, start=0, slave=8, values=['17'], timeout=None, retries=None)
    with pytest.raises(SystemExit, match='result unknown, do not retry'):
        cli._cli_modbus_dispatch(args)
    assert calls == ['write'] and not control.sessions and not manager.running
    assert '[OK]' not in capsys.readouterr().out


@pytest.mark.parametrize('operation_failed', [False, True])
def test_cleanup_attempts_detach_and_preserves_original_unknown_result(monkeypatch, capsys, operation_failed):
    from mklink import cli, runtime
    events = []
    class Client:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): events.append('connect')
        def call(self, name, *args):
            events.append(name)
            if name == 'modbus_status':
                return {'running': False, 'connection': {'port': 'TEST', 'baudrate': 9600,
                    'bytesize': 8, 'parity': 'N', 'stopbits': 1}}
            if name == 'modbus_stop':
                raise runtime.RuntimeErrorResponse('stop unavailable', status_code=503)
        def close(self):
            events.append('detach')
            raise runtime.RuntimeErrorResponse('detach unavailable', status_code=503)
    monkeypatch.setattr(runtime, 'RuntimeClient', Client)
    args = SimpleNamespace(port='TEST', baud=9600, parity='N', stopbits=1)
    with pytest.raises(runtime.RuntimeErrorResponse, match='result unknown' if operation_failed else 'stop unavailable'):
        with cli._modbus_shared_client(args):
            if operation_failed:
                raise runtime.RuntimeErrorResponse('result unknown, do not retry', status_code=502)
    assert events == ['connect', 'modbus_status', 'modbus_start', 'modbus_status', 'modbus_stop', 'detach']
    if operation_failed:
        assert capsys.readouterr().err.count('[WARN]') == 2


def test_explicit_new_connection_timing_is_applied(scan_cli, uart_app):
    cli, args, _, _, _, _ = scan_cli
    vars(args).update(fc=3, slave=8, start=2, quantity=1, format='dec', timeout=.4, retries=2)
    cli._cli_modbus_read(args)
    options = uart_app[3].instances[0].options
    assert options['timeout'] == .4 and options['retries'] == 2
