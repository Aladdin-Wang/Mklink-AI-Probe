"""Scanning shares the UART worker and restores actual protocol settings."""
import threading
from types import SimpleNamespace

import pytest

from mklink.modbus._client import ModbusClient, ModbusError
from mklink.modbus._scanner import scan_slaves
from mklink.modbus._session import modbus_crc16, ModbusWorker
from test_runtime_uart import uart_app, client_factory, uart_attach, call


@pytest.mark.parametrize('reply', ['data', 'exception', 'absent', 'io_error', 'restore_error'])
def test_probe_uses_real_rtu_codec_once_and_restores_all_timing(monkeypatch, tmp_path, reply):
    monkeypatch.setenv('MKLINK_LOCK_DIR', str(tmp_path))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [])
    class Wire:
        is_open = True
        timeout = 1.25
        _write_timeout = None
        pending = b''
        writes = []
        @property
        def write_timeout(self): return self._write_timeout
        @write_timeout.setter
        def write_timeout(self, value):
            if reply == 'restore_error' and self.writes and value == 1.25:
                raise OSError('restore failure')
            self._write_timeout = value
        @property
        def in_waiting(self): return len(self.pending)
        def write(self, data):
            assert self.timeout == .15 and self.write_timeout == .15
            assert raw.comm_params.timeout_connect == .15
            assert raw.retries == raw.transaction.retries == 0
            self.writes.append(bytes(data))
            if reply == 'io_error': raise OSError('port lost')
            if reply != 'absent':
                payload = bytes([data[0], 0x83, 2]) if reply == 'exception' else bytes([data[0], 3, 2, 0, 42])
                self.pending = payload + modbus_crc16(payload).to_bytes(2, 'little')
            return len(data)
        def read(self, count):
            data, self.pending = self.pending[:count], self.pending[count:]
            return data
        def close(self): self.is_open = False
    wire = Wire()
    monkeypatch.setattr('serial.serial_for_url', lambda *a, **kw: wire)
    client = ModbusClient('TEST', timeout=1.25, retries=3)
    assert client.open()
    raw = client.raw_client
    countdown = raw.transaction.count_until_disconnect
    worker = ModbusWorker(client, 1)
    worker.start()
    try:
        if reply in ('io_error', 'restore_error'):
            with pytest.raises(OSError, match='port lost|restore failure'): worker.probe_slave(7, 2)
        else:
            result = worker.probe_slave(7, 2)
            assert result['responded'] == (reply != 'absent')
            assert result['slave'] == 7
            if reply == 'exception': assert result['exception_code'] == 2
        assert len(wire.writes) == 1
        assert wire.writes[0][:6] == bytes.fromhex('07 03 00 02 00 01')
        assert raw.comm_params.timeout_connect == wire.timeout == 1.25
        assert wire.write_timeout == (.15 if reply == 'restore_error' else 1.25)
        assert raw.retries == raw.transaction.retries == 3
        assert raw.transaction.count_until_disconnect == countdown
        assert worker.slave == 1
        if reply == 'restore_error':
            from pymodbus.exceptions import ConnectionException
            from mklink.local_resources import _PortLock
            assert not wire.is_open and raw.socket is None
            contender = _PortLock('TEST')
            assert not contender.acquire()
            with pytest.raises(ConnectionException):
                worker.execute(3, 0, quantity=1)
            assert len(wire.writes) == 1
    finally:
        worker.stop()
        client.close()
    assert not worker.worker_alive and not wire.is_open


def test_scan_preserves_exception_responses_and_aborts_transport_failures():
    progress = []
    def probe(slave, register):
        assert register == 4
        return {'responded': slave != 2, 'exception_code': 2 if slave == 3 else None}
    assert scan_slaves(probe, 1, 3, 4, lambda *value: progress.append(value)) == [1, 3]
    assert [entry[:2] for entry in progress] == [(1, 3), (2, 3), (3, 3)]
    assert '异常码 2' in progress[-1][2]
    with pytest.raises(OSError, match='lost'):
        scan_slaves(lambda *_: (_ for _ in ()).throw(OSError('lost')), 1, 3)


@pytest.mark.parametrize('start,end,register', [(0, 2, 0), (2, 1, 0), (1, 248, 0), (1, 2, 65536)])
def test_invalid_scan_has_no_side_effects(start, end, register):
    with pytest.raises(ValueError):
        scan_slaves(lambda *_: pytest.fail('invalid scan reached transport'), start, end, register)


@pytest.fixture
def scan_cli(uart_app, monkeypatch):
    from mklink import runtime, cli
    http, control, managers, factory, _ = uart_app
    real_client = runtime.RuntimeClient
    calls = []
    def probe(self, slave, register):
        calls.append((slave, register, threading.get_ident()))
        return {'slave': slave, 'responded': slave == 2}
    monkeypatch.setattr(factory, 'probe_slave', probe, raising=False)
    def request(info, method, path, payload=None, **kwargs):
        response = http.request(method, path, json=payload)
        if response.status_code >= 400:
            raise runtime.RuntimeErrorResponse(response.text, status_code=response.status_code)
        return response.json()
    monkeypatch.setattr(runtime, 'request', request)
    monkeypatch.setattr(runtime, 'RuntimeClient', lambda **kwargs: real_client(info=control.info, **kwargs))
    monkeypatch.chdir(control.app.state.mklink_state['project_root'])
    monkeypatch.setattr(cli, '_modbus_save_config', lambda args: None)
    args = SimpleNamespace(port='TEST', baud=9600, parity='N', stopbits=1, start=1, end=3, probe=None)
    return cli, args, http, control, managers['modbus'], calls


@pytest.mark.parametrize('existing', [False, True])
def test_scan_cli_borrows_gui_or_stops_only_its_own_connection(scan_cli, existing, capsys):
    cli, args, http, control, manager, calls = scan_cli
    if existing:
        assert http.post('/api/dash/modbus/start', json={'port': 'TEST', 'slave': 7, 'registers': []}).status_code == 200
    cli._cli_modbus_scan(args)
    assert [c[:2] for c in calls] == [(1, 0), (2, 0), (3, 0)]
    assert len({c[2] for c in calls}) == 1
    assert '发现 1 个从站: 2' in capsys.readouterr().out
    assert manager.running == existing and not control.sessions
    if existing: assert manager.get_status()['slave'] == 7


def test_scan_cli_rejects_different_port_after_borrow_without_io(scan_cli):
    from mklink.runtime import RuntimeErrorResponse
    cli, args, http, control, manager, calls = scan_cli
    assert http.post('/api/dash/modbus/start', json={'port': 'OTHER', 'registers': []}).status_code == 200
    with pytest.raises(RuntimeErrorResponse, match='different port/settings'):
        cli._cli_modbus_scan(args)
    assert not calls and not control.sessions and manager.running


def test_scan_cli_keeps_its_connection_when_another_client_borrows(scan_cli, monkeypatch):
    cli, args, http, control, manager, calls = scan_cli
    original = manager.probe_slave
    peer = uart_attach(http)
    def probe(slave, register=0):
        assert call(http, peer, 'modbus_start').status_code == 200
        return original(slave, register)
    # The HTTP handler dispatches this through a worker thread, so it can issue
    # a second request to the TestClient portal without blocking its event loop.
    monkeypatch.setattr(manager, 'probe_slave', probe)
    cli._cli_modbus_scan(args)
    assert manager.running and list(control.sessions) == [peer]
    assert len(calls) == 3


def test_probe_rest_rejects_unknown_fields_and_scope_does_not_touch_mcu(uart_app, monkeypatch):
    http, control, managers, factory, _ = uart_app
    calls = []
    monkeypatch.setattr(factory, 'probe_slave', lambda _, slave, register: calls.append((slave, register)) or
                        {'slave': slave, 'responded': True}, raising=False)
    owner = uart_attach(http)
    assert call(http, owner, 'modbus_start', {'port': 'TEST', 'registers': []}).status_code == 200
    assert call(http, owner, 'modbus_probe', {'slave': 7}).json()['responded']
    assert call(http, owner, 'modbus_probe', {'slave': 7, 'retries': 1}).status_code == 422
    assert call(http, owner, 'modbus_probe', {'slave': 0}).status_code == 400
    assert calls == [(7, 0)]
    assert control.app.state.mklink_state['device'] is None
