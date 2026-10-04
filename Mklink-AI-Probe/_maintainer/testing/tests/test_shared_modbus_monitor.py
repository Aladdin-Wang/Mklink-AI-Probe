"""Shared monitor uses real trace bytes, bounded cursors and incremental logs."""
import io
import threading

import pytest

from mklink.modbus._monitor import monitor_traffic
from mklink.modbus._session import modbus_crc16
from mklink.remote.dashboards import ModbusStreamManager
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory, uart_attach, call


def frame(payload):
    raw = bytes.fromhex(payload)
    return raw + modbus_crc16(raw).to_bytes(2, 'little')


def test_history_tail_gap_pagination_copy_and_independent_sources():
    manager = ModbusStreamManager()
    initial = manager.get_history()
    for index in range(600):
        manager._record_event({'event': 'test', 'index': index})
    assert len(manager._history) == 500
    assert manager.get_history()['entries'] == []  # no unexpected old replay
    page = manager.get_history(initial['session'], 0, 256)
    assert (page['dropped'], page['next_seq'], page['latest_seq']) == (100, 356, 600)
    assert len(page['entries']) == 256
    page['entries'][0]['event'] = 'tampered'
    assert manager._history[0]['event'] == 'test'
    end = manager.get_history(initial['session'], page['next_seq'])
    assert len(end['entries']) == 244 and end['next_seq'] == 600 and end['dropped'] == 0
    assert manager.get_history(initial['session'], 600)['entries'] == []
    with pytest.raises(RuntimeError, match='session changed'):
        ModbusStreamManager().get_history(initial['session'], 0)


@pytest.mark.parametrize('args', [
    {'after': 0}, {'session': 'x'}, {'limit': True}, {'limit': 0}, {'limit': 257},
    {'limit': 1.5}, {'limit': '1'}, {'after': True}, {'after': -1},
])
def test_bad_history_cursor_rejected(args):
    with pytest.raises(ValueError): ModbusStreamManager().get_history(**args)


def test_history_restart_and_stop_are_explicit(client_factory):
    manager = ModbusStreamManager()
    manager.start({'port': 'TEST'}, 1, [])
    first = manager.get_history()
    try:
        with pytest.raises(ValueError, match='ahead'):
            manager.get_history(first['session'], 1)
        manager.trace_packet(True, frame('01 03 00 00 00 01'))
        manager.stop()
        stopped = manager.get_history(first['session'], 0)
        assert not stopped['running'] and len(stopped['entries']) == 1
        manager.start({'port': 'OTHER'}, 1, [])
        with pytest.raises(RuntimeError, match='session changed'):
            manager.get_history(first['session'], 0)
        assert manager.get_history()['connection']['port'] == 'OTHER'
        assert manager.get_history()['next_seq'] == 0
    finally:
        manager.stop()


@pytest.mark.parametrize('args,status', [({}, 200), ({'limit': 0}, 400), ({'limit': 257}, 400),
    ({'limit': True}, 422), ({'limit': '1'}, 422), ({'after': 0}, 400),
    ({'session': 'other', 'after': 0}, 409), ({'after': 1.5}, 422), ({'unknown': 1}, 422)])
def test_history_rpc_is_uart_only_strict_and_never_opens_device(uart_app, args, status):
    http, control, managers, factory, _ = uart_app
    result = call(http, uart_attach(http), 'modbus_history', args)
    assert result.status_code == status, result.text
    assert not factory.instances and control.app.state.mklink_state['device'] is None


@pytest.mark.parametrize('mode', ['decoded', 'hex', 'both'])
@pytest.mark.parametrize('existing', [False, True])
def test_cli_monitor_shares_worker_and_flushes_before_next_request(scan_cli, uart_app, monkeypatch, tmp_path, mode, existing):
    cli, args, http, control, manager, _ = scan_cli
    logfile = tmp_path / 'monitor.log'
    operations = []
    def read(self, address, count, slave):
        if operations:
            # Must already be visible on disk while the monitor is still running.
            saved = logfile.read_text(encoding='utf-8')
            assert 'RX' in saved
            assert ('12 34' in saved) == (mode != 'decoded')
        operations.append((address, count, slave, threading.get_ident()))
        manager.trace_packet(True, frame('08 03 00 00 00 0A'))
        raw = frame('08 03 14 ' + '12 34 ' * 10)
        manager.trace_packet(False, raw[:5])  # partial accumulation is not a new frame
        manager.trace_packet(False, raw)
        return [0x1234] * count
    monkeypatch.setattr(uart_app[3], 'read_holding_registers', read)
    if existing:
        assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'slave': 7, 'registers': []}).status_code == 200
    vars(args).update(slave=8, interval=.02, output_format=mode, count=2, save=str(logfile), passive=False)
    cli._cli_modbus_monitor(args)
    saved = logfile.read_text(encoding='utf-8')
    assert saved.count(' TX ') == saved.count(' RX ') == 2
    assert 'session=' in saved and 'TEST' in saved
    assert len(operations) == 2 and len({item[3] for item in operations}) == 1
    assert operations[0][3] != threading.get_ident()
    assert len(uart_app[3].instances) == 1 and not control.sessions
    assert manager.running == existing
    if existing: assert manager.get_status()['slave'] == 7
    else: assert not manager.worker_alive and uart_app[3].instances[0].closed


@pytest.mark.parametrize('params', [{'interval': float('nan')}, {'interval': 0}, {'count': 0},
    {'count': True}, {'output_format': 'other'}, {'slave': 0}])
def test_invalid_monitor_has_no_attach(scan_cli, monkeypatch, params):
    cli, args, *_ = scan_cli
    vars(args).update(slave=1, interval=.02, output_format='hex', count=1, save=None, passive=False)
    vars(args).update(params)
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **_: pytest.fail('invalid monitor attached'))
    with pytest.raises(ValueError): cli._cli_modbus_monitor(args)


def test_invalid_log_destination_has_no_attach(scan_cli, monkeypatch, tmp_path):
    cli, args, *_ = scan_cli
    vars(args).update(slave=1, interval=.02, output_format='hex', count=1, save=str(tmp_path/'absent'/'log'), passive=False)
    monkeypatch.setattr('mklink.runtime.RuntimeClient', lambda **_: pytest.fail('invalid destination attached'))
    with pytest.raises(OSError): cli._cli_modbus_monitor(args)


def test_passive_is_read_only_and_reports_loss_with_bounded_drain(monkeypatch):
    manager = ModbusStreamManager()
    manager._running = True
    count = 0
    def rpc(capability, args):
        nonlocal count
        assert capability == 'modbus_history'
        if args:
            count += 1
            # Unbounded producer pressure; consumer must still terminate its round.
            for _ in range(600): manager.trace_packet(False, frame('07 83 02'))
        return manager.get_history(**args)
    output = io.StringIO()
    monitor_traffic(rpc, 1, count=1, passive=True, output=output)
    assert count == 2 and 'Lost 100' in output.getvalue()
    assert 'Slave=7 FC=83 CRC=OK Exception=2' in output.getvalue()


def test_transaction_failure_logs_trace_once_and_preserves_gui(scan_cli, uart_app, monkeypatch, tmp_path):
    cli, args, http, control, manager, _ = scan_cli
    operations = []
    def read(self, *args):
        operations.append(args)
        manager.trace_packet(True, frame('08 03 00 00 00 0A'))
        manager.trace_packet(False, frame('08 83 02'))
        raise OSError('connection lost')
    monkeypatch.setattr(uart_app[3], 'read_holding_registers', read)
    http.post('/api/dash/modbus/start', json={'port': 'TEST', 'registers': []})
    logfile = tmp_path/'failed.log'
    vars(args).update(slave=8, interval=.02, output_format='both', count=2, save=str(logfile), passive=False)
    with pytest.raises(RuntimeError, match='connection lost'): cli._cli_modbus_monitor(args)
    assert len(operations) == 1 and manager.running and not control.sessions
    saved = logfile.read_text(encoding='utf-8')
    assert 'Exception=2' in saved and '08 83 02' in saved and '[ERROR]' in saved


@pytest.mark.parametrize('changed', ['session', 'stopped', 'keyboard'])
def test_passive_stops_without_automatic_reopen(changed):
    manager = ModbusStreamManager()
    manager._running = True
    count = 0
    def rpc(capability, args):
        nonlocal count
        count += 1
        if args:
            if changed == 'keyboard': raise KeyboardInterrupt()
            if changed == 'session': manager._history_session = 'replacement'
            else: manager._running = False
        return manager.get_history(**args)
    if changed == 'keyboard': monitor_traffic(rpc, 1, passive=True)
    else:
        with pytest.raises((RuntimeError, OSError), match='changed|stopped'): monitor_traffic(rpc, 1, passive=True)
    assert count == 2


def test_log_write_failure_propagates_before_any_send():
    class FullDisk(io.StringIO):
        def write(self, _): raise OSError('disk full')
    def rpc(capability, args):
        assert capability == 'modbus_history' and args == {}
        return {'running': True, 'stopping': False, 'session': 'test', 'next_seq': 0, 'connection': {}}
    with pytest.raises(OSError, match='disk full'):
        monitor_traffic(rpc, 1, output=FullDisk())


def test_failed_final_trace_does_not_mask_transaction_failure(capsys):
    class FullAfterHeader(io.StringIO):
        def write(self, line):
            if '[ERROR]' in line: raise OSError('disk full')
            return super().write(line)
    def rpc(capability, args):
        if capability == 'modbus_transaction': raise OSError('original I/O failure')
        return {'running': True, 'stopping': False, 'session': 'test', 'next_seq': 0,
                'latest_seq': 0, 'entries': [], 'dropped': 0, 'connection': {}}
    with pytest.raises(OSError, match='original I/O failure'):
        monitor_traffic(rpc, 1, output=FullAfterHeader())
    assert 'disk full' in capsys.readouterr().err


@pytest.mark.parametrize('mode', ['decoded', 'hex', 'both'])
@pytest.mark.parametrize('reply', ['normal', 'exception'])
def test_monitor_real_pymodbus_trace_and_incremental_file(monkeypatch, tmp_path, mode, reply):
    from mklink.modbus._client import ModbusSlaveError
    monkeypatch.setenv('MKLINK_LOCK_DIR', str(tmp_path))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [])
    logfile = tmp_path / 'rtu.log'
    class Wire:
        is_open = True
        pending = b''
        writes = []
        @property
        def in_waiting(self): return len(self.pending)
        def write(self, data):
            if self.writes:
                assert ' RX ' in logfile.read_text(encoding='utf-8')
            self.writes.append(bytes(data))
            assert data == frame('08 03 00 00 00 0A')
            self.pending = frame('08 83 02') if reply == 'exception' else frame('08 03 14 ' + '12 34 '*10)
            return len(data)
        def read(self, count):
            data, self.pending = self.pending[:count], self.pending[count:]
            return data
        def close(self): self.is_open = False
    wire = Wire()
    monkeypatch.setattr('serial.serial_for_url', lambda *a, **kw: wire)
    manager = ModbusStreamManager()
    manager.start({'port': 'TEST'}, 1, [])
    def rpc(capability, args):
        return (manager.get_history if capability == 'modbus_history' else manager.transaction)(**args)
    try:
        with logfile.open('w', encoding='utf-8') as output:
            if reply == 'exception':
                with pytest.raises(ModbusSlaveError):
                    monitor_traffic(rpc, 8, interval=.02, count=2, output_format=mode, output=output)
            else:
                monitor_traffic(rpc, 8, interval=.02, count=2, output_format=mode, output=output)
        saved = logfile.read_text(encoding='utf-8')
        assert saved.count(' TX ') == saved.count(' RX ') == len(wire.writes)
        assert len(wire.writes) == (1 if reply == 'exception' else 2)
        if mode != 'decoded': assert '08 03 00 00 00 0A' in saved
        if mode != 'hex': assert 'CRC=OK' in saved
    finally:
        manager.stop()
    assert not wire.is_open and not manager.worker_alive
