"""Diagnostics keep protocol semantics while sharing the existing UART worker."""
import threading

import pytest

from mklink.modbus._session import ModbusWorker, modbus_crc16, rtu_frame_length, validate_transaction
from mklink.runtime import RuntimeErrorResponse
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory, uart_attach, call


@pytest.mark.parametrize('fc,params', [
    (7, {'start': 0}), (7, {'quantity': 1}), (7, {'values': []}),
    (7, {'and_mask': 0}), (22, {'start': 0}),
    (22, {'start': 0, 'and_mask': True, 'or_mask': 0}),
    (22, {'start': 0, 'and_mask': 65536, 'or_mask': 0}),
    (22, {'start': 0, 'and_mask': 65535, 'or_mask': -.5}),
    (22, {'start': 0, 'and_mask': 65535, 'or_mask': 0, 'values': [1]}),
    (22, {'start': 0, 'and_mask': 65535, 'or_mask': 0, 'quantity': 1}),
    (23, {'start': 0, 'quantity': 1, 'values': [1]}),
    (23, {'start': 0, 'quantity': 1, 'values': [1], 'write_start': True}),
    (23, {'start': 0, 'quantity': 126, 'values': [1], 'write_start': 0}),
    (23, {'start': 0, 'quantity': 1, 'values': [1] * 122, 'write_start': 0}),
    (23, {'start': 65535, 'quantity': 2, 'values': [1], 'write_start': 0}),
    (23, {'start': 0, 'quantity': 2, 'values': [1, 2], 'write_start': 65535}),
    (23, {'start': 0, 'quantity': 1, 'values': [], 'write_start': 0}),
    (23, {'start': 0, 'quantity': 1, 'values': [True], 'write_start': 0}),
    (23, {'start': 0, 'quantity': 1, 'values': [1.5], 'write_start': 0}),
    (23, {'start': 0, 'quantity': 1, 'values': '1', 'write_start': 0}),
    (3, {'start': 0, 'quantity': 1, 'values': [1]}),
    (6, {'start': 0, 'values': [1], 'quantity': 1}),
    (3, {'start': 0, 'quantity': 1, 'and_mask': 0}),
    (6, {'start': 0, 'values': [1], 'write_start': 0}),
])
def test_function_specific_fields_rejected_before_worker_submission(fc, params):
    worker = ModbusWorker(object(), 1)
    worker._submit = lambda *_: pytest.fail('invalid request was queued')
    with pytest.raises(ValueError): worker.execute(fc, **params)


def test_fc23_validates_read_and_write_limits_independently():
    values = list(range(121))
    assert validate_transaction(23, 65411, quantity=125, values=values, write_start=65415) == (23, 65411, 125, values)
    assert validate_transaction(7) == (7, None, None, None)
    assert validate_transaction(22, 65535, and_mask=65535, or_mask=0) == (22, 65535, None, None)


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('subfunc,expected', [('exception-status', 7), ('mask-write', 22), ('read-write', 23)])
def test_cli_diag_shares_worker_and_preserves_gui(scan_cli, uart_app, monkeypatch, capsys, existing, subfunc, expected):
    cli, args, http, control, manager, _ = scan_cli
    operations = []
    factory = uart_app[3]
    def status(self, slave):
        operations.append((7, slave, threading.get_ident()))
        return 0xA5
    def mask(self, address, and_mask, or_mask, slave):
        operations.append((22, slave, threading.get_ident()))
        assert (address, and_mask, or_mask) == (4, 0xFF00, 0x55)
    def readwrite(self, read_address, read_count, write_address, write_values, slave):
        operations.append((23, slave, threading.get_ident()))
        assert (read_address, read_count, write_address, write_values) == (4, 2, 20, [17, 18])
        return [42, 43]
    monkeypatch.setattr(factory, 'read_exception_status', status, raising=False)
    monkeypatch.setattr(factory, 'mask_write_register', mask, raising=False)
    monkeypatch.setattr(factory, 'read_write_registers', readwrite, raising=False)
    if existing:
        assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'slave': 7,
            'registers': [], 'timeout': .7, 'retries': 2}).status_code == 200
    vars(args).update(subfunc=subfunc, slave=8, timeout=None, retries=None)
    if subfunc == 'mask-write': vars(args).update(addr=4, and_mask=0xFF00, or_mask=0x55)
    if subfunc == 'read-write': vars(args).update(addr=4, read_count=2, write_addr=20, write_values=[17, 18])
    cli._cli_modbus_diag(args)
    assert [(fc, slave) for fc, slave, _ in operations] == [(expected, 8)]
    assert operations[0][2] != threading.get_ident()
    assert len(factory.instances) == 1 and manager.running == existing and not control.sessions
    if existing:
        assert manager.get_status()['slave'] == 7
        assert manager.get_status()['connection']['timeout'] == .7
    else:
        assert not manager.worker_alive and factory.instances[0].closed
    assert f'FC{expected:02d}' in capsys.readouterr().out


@pytest.mark.parametrize('subfunc,fields', [
    ('exception-status', {'addr': 0}), ('exception-status', {'and_mask': 1}),
    ('mask-write', {'write_values': [1]}), ('mask-write', {'and_mask': -1}),
    ('read-write', {}), ('read-write', {'write_values': [1], 'and_mask': 1}),
    ('read-write', {'write_values': [1] * 122}),
    ('read-write', {'write_values': [1], 'read_count': 0}),
    ('read-write', {'write_values': [1, 2], 'write_addr': 65535}),
])
def test_invalid_diag_has_no_attach(scan_cli, monkeypatch, subfunc, fields):
    cli, args, *_ = scan_cli
    vars(args).update(subfunc=subfunc, slave=8, **fields)
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **_: pytest.fail('invalid diag attached'))
    with pytest.raises(ValueError): cli._cli_modbus_diag(args)


@pytest.mark.parametrize('failure', ['timeout', 'short'])
def test_read_write_failure_is_unknown_once_and_keeps_gui(scan_cli, uart_app, monkeypatch, failure, capsys):
    cli, args, http, control, manager, _ = scan_cli
    writes = []
    def readwrite(self, *operation):
        writes.append(operation)
        if failure == 'timeout': raise TimeoutError('write result unknown')
        return [42]
    monkeypatch.setattr(uart_app[3], 'read_write_registers', readwrite, raising=False)
    assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'registers': []}).status_code == 200
    vars(args).update(subfunc='read-write', slave=8, read_count=2, write_values=[17], timeout=None, retries=None)
    with pytest.raises(RuntimeErrorResponse, match='unknown'): cli._cli_modbus_diag(args)
    assert len(writes) == 1 and manager.running and not control.sessions
    assert '[OK]' not in capsys.readouterr().out


@pytest.mark.parametrize('body,status', [
    ({'fc': 7}, 200), ({'fc': 7, 'start': 0}, 400),
    ({'fc': 22, 'start': 4, 'and_mask': '65535', 'or_mask': 1}, 422),
    ({'fc': 22, 'start': 4, 'and_mask': 65535, 'or_mask': True}, 422),
    ({'fc': 23, 'start': 4, 'quantity': 1, 'write_start': .5, 'values': [1]}, 422),
    ({'fc': 23, 'start': 4, 'quantity': 1, 'write_start': 5, 'values': [1], 'retry': 0}, 422),
])
def test_runtime_diag_scope_uses_existing_capability_and_strict_schema(uart_app, monkeypatch, body, status):
    http, control, managers, factory, _ = uart_app
    operations = []
    monkeypatch.setattr(factory, 'read_exception_status', lambda _, slave: operations.append(slave) or 0xA5, raising=False)
    owner = uart_attach(http)
    assert call(http, owner, 'modbus_start', {'port': 'TEST', 'registers': []}).status_code == 200
    result = call(http, owner, 'modbus_transaction', {**body, 'slave': 8})
    assert result.status_code == status, result.text
    if status == 200:
        assert result.json()['status'] == 0xA5 and result.json()['start'] is None
        assert operations == [8]
    else: assert not operations
    assert control.app.state.mklink_state['device'] is None


@pytest.mark.parametrize('fc,params,expected', [
    (7, {}, [0xA5]),
    (22, {'start': 4, 'and_mask': 0xFF00, 'or_mask': 0x55}, []),
    (23, {'start': 4, 'quantity': 2, 'write_start': 20, 'values': [17, 18]}, [0x1234, 0x5678]),
])
@pytest.mark.parametrize('reply', ['normal', 'exception'])
def test_real_rtu_codec_diagnostic_is_one_frame_with_expected_fields(monkeypatch, tmp_path, fc, params, expected, reply):
    from mklink.modbus._client import ModbusClient, ModbusSlaveError
    from mklink.remote.dashboards import ModbusStreamManager
    monkeypatch.setenv('MKLINK_LOCK_DIR', str(tmp_path))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [])
    class Wire:
        is_open = True
        pending = b''
        writes = []
        @property
        def in_waiting(self): return len(self.pending)
        def write(self, data):
            self.writes.append(bytes(data))
            assert data[:2] == bytes([8, fc])
            if reply == 'exception': payload = bytes([8, fc | 0x80, 2])
            elif fc == 7: payload = bytes([8, 7, 0xA5])
            elif fc == 22:
                assert data[2:-2] == bytes.fromhex('00 04 FF 00 00 55')
                payload = data[:-2]
            else:
                assert data[2:-2] == bytes.fromhex('00 04 00 02 00 14 00 02 04 00 11 00 12')
                payload = bytes.fromhex('08 17 04 12 34 56 78')
            self.pending = payload + modbus_crc16(payload).to_bytes(2, 'little')
            return len(data)
        def read(self, count):
            data, self.pending = self.pending[:count], self.pending[count:]
            return data
        def close(self): self.is_open = False
    wire = Wire()
    monkeypatch.setattr('serial.serial_for_url', lambda *a, **kw: wire)
    manager = ModbusStreamManager()
    client = ModbusClient('TEST', retries=0, trace_packet=manager.trace_packet)
    assert client.open()
    worker = ModbusWorker(client, 7)
    worker.start()
    try:
        if reply == 'exception':
            with pytest.raises(ModbusSlaveError): worker.execute(fc, **params, slave=8)
        else:
            assert worker.execute(fc, **params, slave=8) == expected
        assert len(wire.writes) == 1 and worker.slave == 7
        assert rtu_frame_length(True, wire.writes[0]) == len(wire.writes[0])
        frames = [event for event in manager._history if event['event'] == 'frame']
        assert [frame['direction'] for frame in frames] == ['tx', 'rx']
        assert all(frame['complete'] and frame['crc_ok'] for frame in frames)
    finally:
        worker.stop()
        client.close()
    assert not wire.is_open and not worker.worker_alive
