"""Shared polling preserves typed values and never fabricates data on failure."""
import threading
from types import SimpleNamespace

import pytest

from mklink.modbus._format import RegisterSpec
from mklink.modbus._poller import poll_registers
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('register_type', ['holding', 'input'])
def test_poll_cli_uses_shared_worker_and_decodes_grouped_values(scan_cli, uart_app, monkeypatch, capsys, existing, register_type):
    cli, args, http, control, manager, _ = scan_cli
    factory = uart_app[3]
    calls = []
    def read(self, address, count, slave):
        calls.append((address, count, slave, threading.get_ident()))
        return [0xffff, 0x3f80, 0] if address == 0 else [17]
    method = 'read_holding_registers' if register_type == 'holding' else 'read_input_registers'
    monkeypatch.setattr(factory, method, read, raising=False)
    if existing:
        assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'slave': 7, 'registers': []}).status_code == 200
    vars(args).update(slave=8, registers='0:int16:Signed 1:float:Voltage 5:uint16:Count',
                      register_type=register_type, interval=.02, count=2, format='dec', timeout=None, retries=None)
    cli._cli_modbus_poll(args)
    assert [c[:3] for c in calls] == [(0, 3, 8), (5, 1, 8)] * 2
    assert len({c[3] for c in calls}) == 1 and calls[0][3] != threading.get_ident()
    output = capsys.readouterr().out
    assert 'Signed' in output and '-1' in output and 'Voltage' in output and '1.0' in output
    assert '轮询: 2' in output and manager.running == existing and not control.sessions
    assert len(factory.instances) == 1
    if existing: assert manager.get_status()['slave'] == 7


@pytest.mark.parametrize('registers,interval,count', [('', 1, 1), ('0:garbage', 1, 1),
    ('65535:float', 1, 1), ('-1:uint16', 1, 1), ('0 0', 1, 1),
    ('0', 0, 1), ('0', float('nan'), 1), ('0', float('inf'), 1), ('0', 1, 0),
    ('0:uint16:Name:ignored', 1, 1)])
def test_invalid_poll_rejected_before_open(scan_cli, monkeypatch, registers, interval, count):
    from mklink import runtime
    cli, args, *_ = scan_cli
    vars(args).update(slave=8, registers=registers, register_type='holding', interval=interval,
                      count=count, format='dec', timeout=None, retries=None)
    monkeypatch.setattr(runtime, 'RuntimeClient', lambda **_: pytest.fail('invalid poll attached'))
    with pytest.raises(ValueError):
        cli._cli_modbus_poll(args)


def test_poll_failure_never_prints_a_fabricated_zero(capsys):
    from mklink.modbus._client import ModbusError
    class Reader:
        def __call__(self, *args): raise ModbusError('lost response')
        # Reproduce the old client-shaped path before replacing it with a callback.
        read_holding_registers = __call__
    with pytest.raises(ModbusError, match='lost response'):
        poll_registers(Reader(), 8, [RegisterSpec(0, name='Lost')], count=1)
    assert '轮询: 1' not in capsys.readouterr().out


def test_partial_poll_is_not_rendered_as_a_complete_snapshot(capsys):
    class Reader:
        calls = []
        def __call__(self, fc, address, count):
            self.calls.append((fc, address, count))
            return [17] if address == 0 else []
    reader = Reader()
    with pytest.raises(OSError, match='incomplete register group'):
        poll_registers(reader, 8, [RegisterSpec(0), RegisterSpec(4, 'float')], count=1)
    assert reader.calls == [(3, 0, 1), (3, 4, 2)]
    assert '轮询: 1' not in capsys.readouterr().out


def test_shared_grouping_keeps_wide_values_whole_and_splits_function_codes():
    from mklink.modbus._registers import read_register_values
    specs = [RegisterSpec(i) for i in range(124)]
    specs += [RegisterSpec(124, 'uint32'), RegisterSpec(126, 'int32'),
              RegisterSpec(128, 'float', register_type='input')]
    calls = []
    def read(fc, address, count):
        calls.append((fc, address, count))
        return list(range(124)) if address == 0 else [0x1234, 0x5678, 0xffff, 0xfffe] if address == 124 else [0x3f80, 0]
    result = read_register_values(read, specs)
    assert calls == [(3, 0, 124), (3, 124, 4), (4, 128, 2)]
    assert (result[123], result[124], result[126], result[128]) == (123, 0x12345678, -2, 1.0)


@pytest.mark.parametrize('legacy', [False, True])
def test_worker_batch_paths_use_the_same_input_register_and_partial_response_rules(legacy):
    from mklink.modbus._session import ModbusWorker
    from mklink.modbus._dashboard import _ModbusWorker
    calls = []
    class Client:
        def read_input_registers(self, address, count, slave):
            calls.append((address, count, slave))
            return [0x3f80, 0] if address == 0 else [17]
        def read_holding_registers(self, *_): pytest.fail('input spec sent FC03')
    worker = (_ModbusWorker if legacy else ModbusWorker)(Client(), 8)
    assert worker._batch_read([RegisterSpec(0, 'float', register_type='input')]) == {0: 1.0}
    with pytest.raises(OSError, match='incomplete register group'):
        worker._batch_read([RegisterSpec(4, 'float', register_type='input')])
    assert calls == [(0, 2, 8), (4, 2, 8)]


def test_manager_preserves_input_register_type_and_rejects_unknown_before_open(client_factory, monkeypatch):
    from mklink.remote.dashboards import ModbusStreamManager
    entered = threading.Event()
    calls = []
    def read(self, address, count, slave):
        calls.append((address, count, slave))
        entered.set()
        return [0x3f80, 0]
    monkeypatch.setattr(client_factory, 'read_input_registers', read, raising=False)
    manager = ModbusStreamManager()
    with pytest.raises(ValueError, match='holding or input'):
        manager.start({'port': 'TEST'}, 8, [{'addr': 0, 'register_type': 'typo'}])
    assert not client_factory.instances
    try:
        manager.start({'port': 'TEST'}, 8, [{'addr': 0, 'type': 'float', 'register_type': 'input'}])
        assert entered.wait(2)
    finally:
        manager.stop()
    assert calls and all(call == (0, 2, 8) for call in calls)
    assert not manager.worker_alive


def test_interrupted_poll_detaches_without_stopping_gui(scan_cli, monkeypatch):
    cli, args, http, control, manager, _ = scan_cli
    assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'registers': []}).status_code == 200
    vars(args).update(slave=8, registers='0:uint16', register_type='holding', interval=.02,
                      count=None, format='dec', timeout=None, retries=None)
    def interrupted(_): raise KeyboardInterrupt
    monkeypatch.setattr('mklink.modbus._poller.time', SimpleNamespace(sleep=interrupted))
    cli._cli_modbus_poll(args)
    assert manager.running and not control.sessions
