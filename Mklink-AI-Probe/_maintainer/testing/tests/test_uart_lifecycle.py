from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mklink.local_resources import _PortLock, serial_lock_path
from mklink.serial import _monitor as monitors
from mklink.serial._monitor import SerialMonitor
from mklink.serial._port import SerialPort, list_uart_ports
from mklink.usb_interfaces import canonical_serial_port, require_uart_port


@pytest.fixture(autouse=True)
def isolated_ports(monkeypatch, tmp_path):
    monkeypatch.setenv('MKLINK_LOCK_DIR', str(tmp_path))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [])


def metadata(interface, *, device='COM6', mklink=True):
    return SimpleNamespace(device=device, vid=0x0D28 if mklink else 0x1234,
                           pid=0x0202, hwid=interface, location='', interface='', description='test')


@pytest.mark.parametrize('port', ['COM6', 'com006', r'\\.\COM006'])
def test_com_aliases_share_the_existing_os_lock(port):
    assert canonical_serial_port(port) == 'COM6'
    assert serial_lock_path(port) == serial_lock_path('COM6')
    first, second = _PortLock('COM6'), _PortLock(port)
    assert first.acquire()
    try:
        assert not second.acquire()
    finally:
        first.release()
    assert second.acquire()
    second.release()


def test_other_paths_preserved():
    assert canonical_serial_port('/dev/ttyACM0') == '/dev/ttyACM0'
    assert canonical_serial_port(r'\\.\custom') == r'\\.\custom'


@pytest.mark.parametrize('interface', ['MI_04', ''])
@pytest.mark.parametrize('kind', ['serial', 'modbus'])
def test_command_and_unidentified_interfaces_rejected_before_open(monkeypatch, interface, kind):
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [metadata(interface)])
    def forbidden(*args, **kwargs):
        pytest.fail('unsafe port was opened')
    if kind == 'serial':
        monkeypatch.setattr('serial.Serial', forbidden)
        port = SerialPort(r'\\.\com006')
    else:
        from mklink.modbus._client import ModbusClient, _ExplicitSerialClient
        monkeypatch.setattr(_ExplicitSerialClient, 'open_port', forbidden)
        port = ModbusClient('com006')
    with pytest.raises(ValueError, match='command or unidentified'):
        port.open()
    assert list_uart_ports() == []
    lock = _PortLock('COM6')
    assert lock.acquire()
    lock.release()


@pytest.mark.parametrize('interface,mklink', [('MI_00', True), ('MI_02', True), ('', False)])
def test_uart_metadata_allowed_without_io(monkeypatch, interface, mklink):
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [metadata(interface, mklink=mklink)])
    assert require_uart_port('com6') == 'COM6'
    assert list_uart_ports()[0]['device'] == 'COM6'


def test_reclassification_during_serial_open_closes_and_unlocks(monkeypatch):
    current = [metadata('MI_00')]
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: current)
    handle = SimpleNamespace(is_open=True)
    def close():
        handle.is_open = False
    handle.close = close
    def opening(**kwargs):
        current[:] = [metadata('MI_04')]
        return handle
    monkeypatch.setattr('serial.Serial', opening)
    with pytest.raises(ValueError):
        SerialPort('COM6').open()
    assert not handle.is_open
    lock = _PortLock('COM6')
    assert lock.acquire()
    lock.release()


def test_closed_and_partial_writes_fail_without_replay():
    port = SerialPort('COM6')
    with pytest.raises(OSError, match='closed'):
        port.write(b'abc')
    calls = []
    port._serial = SimpleNamespace(is_open=True, write=lambda b: calls.append(b) or 1)
    with pytest.raises(OSError, match='incomplete'):
        port.write(b'abc')
    assert calls == [b'abc']


class FakePort:
    instances = []
    def __init__(self, port, **kwargs):
        self.port, self.is_open, self.opens = port, False, 0
        self.instances.append(self)
    def open(self):
        self.opens += 1
        self.is_open = self.port != 'BUSY'
        return self.is_open
    def close(self):
        self.is_open = False
    def read_available(self):
        return b''


@pytest.fixture
def fake_port(monkeypatch):
    FakePort.instances = []
    monkeypatch.setattr(monitors, 'SerialPort', FakePort)
    return FakePort


def test_validate_all_ports_before_opening_any(monkeypatch, fake_port):
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [metadata('MI_04')])
    with pytest.raises(ValueError):
        SerialMonitor([{'port': 'TEST'}, {'port': 'COM6'}]).start()
    assert not fake_port.instances
    with pytest.raises(ValueError, match='distinct'):
        SerialMonitor([{'port': 'com006'}, {'port': r'\\.\COM6'}])


def test_partial_start_rolls_back_and_reports_failure(fake_port):
    monitor = SerialMonitor([{'port': 'TEST'}, {'port': 'BUSY'}])
    with pytest.raises(OSError, match='BUSY'):
        monitor.start()
    assert not monitor.is_running() and not monitor.worker_alive
    assert not monitor._serial_ports
    assert all(not port.is_open for port in fake_port.instances)
    assert monitor.port_status['BUSY'].startswith('error:')


def test_read_failure_is_terminal_and_explicit_start_can_reopen(monkeypatch, fake_port):
    monkeypatch.setattr(fake_port, 'read_available', lambda self: (_ for _ in ()).throw(OSError('removed')))
    monitor = SerialMonitor([{'port': 'TEST'}])
    monitor.start()
    for thread in monitor._threads:
        thread.join(1)
    assert not monitor.is_running()
    assert monitor.port_status['TEST'] == 'error: removed'
    assert len(fake_port.instances) == 1
    assert not fake_port.instances[0].is_open
    monkeypatch.setattr(fake_port, 'read_available', lambda self: b'')
    monitor.start()
    try:
        assert monitor.is_running() and len(fake_port.instances) == 2
    finally:
        monitor.stop()


def test_stop_timeout_keeps_reader_and_open_handle(monkeypatch, fake_port):
    entered, release = threading.Event(), threading.Event()
    def blocked(self):
        entered.set()
        release.wait(2)
        return b''
    monkeypatch.setattr(fake_port, 'read_available', blocked)
    monitor = SerialMonitor([{'port': 'TEST'}])
    monitor._stop_timeout = .01
    monitor.start()
    assert entered.wait(1)
    try:
        with pytest.raises(TimeoutError, match='ownership retained'):
            monitor.stop()
        assert monitor.worker_alive and monitor.is_running()
        assert monitor._serial_ports['TEST'].is_open
        assert len(monitor._threads) == 1
    finally:
        release.set()
        monitor._stop_timeout = 1
        monitor.stop()
    assert not monitor.worker_alive and not monitor._serial_ports


def test_modbus_requests_cannot_implicitly_open_or_reopen(monkeypatch):
    from mklink.modbus._client import ModbusClient
    from pymodbus.exceptions import ConnectionException
    monkeypatch.setattr('serial.serial_for_url', lambda *a, **k: pytest.fail('implicit reopen'))
    client = ModbusClient('COM6')
    with pytest.raises(ConnectionException):
        client.read_holding_registers(0, 1, 1)
    client._client.socket = SimpleNamespace(is_open=False)
    with pytest.raises(ConnectionException):
        client.write_register(0, 1, 1)
    client._client.socket = None
    client.close()


def test_serial_api_open_failure_is_409_and_has_no_lease(monkeypatch, fake_port, tmp_path):
    from mklink.remote.api import create_app
    app = create_app(auth_token=None, project_root=str(tmp_path))
    with TestClient(app) as client:
        response = client.post('/api/dash/serial/start', json={'ports': [{'port': 'BUSY'}]})
        assert response.status_code == 409
        assert not client.get('/api/dash/serial/status').json()['running']
        response = client.post('/api/dash/serial/start', json={'ports': [{'port': 'TEST'}]})
        assert response.status_code == 200
        assert client.post('/api/dash/serial/stop').status_code == 200


def test_cancel_start_settles_port_open_then_releases_only_uart_lease(monkeypatch, fake_port):
    from mklink.remote.api import start_dashboard_manager
    from mklink.remote.dashboards import SerialStreamManager
    from mklink.remote.resource_manager import ResourceGroup, ResourceManager
    entered, release = threading.Event(), threading.Event()
    original = fake_port.open
    def delayed(self):
        entered.set()
        assert release.wait(2)
        return original(self)
    monkeypatch.setattr(fake_port, 'open', delayed)
    manager = SerialStreamManager()
    rm = ResourceManager()
    rm.acquire(ResourceGroup.TARGET_DEBUG, 'independent-target')
    async def scenario():
        task = asyncio.create_task(start_dashboard_manager(
            {'resource_manager': rm}, 'serial', manager, lambda: manager.start([{'port': 'TEST'}])))
        assert await asyncio.to_thread(entered.wait, 1)
        assert not manager.running
        task.cancel()
        await asyncio.sleep(.01)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        manager.stop()
    assert not manager.worker_alive
    assert all(not port.is_open for port in fake_port.instances)
    assert set(rm.get_status()) == {'target_debug'}


def test_stop_transaction_retains_lease_and_does_not_block_event_loop(monkeypatch, fake_port):
    from mklink.remote.api import start_dashboard_manager, stop_dashboard_manager_transaction, DashboardStopPending
    from mklink.remote.dashboards import SerialStreamManager
    from mklink.remote.resource_manager import ResourceManager
    entered, release = threading.Event(), threading.Event()
    def blocked(self):
        entered.set()
        release.wait(2)
        return b''
    monkeypatch.setattr(fake_port, 'read_available', blocked)
    manager = SerialStreamManager()
    rm = ResourceManager()
    state = {'resource_manager': rm}
    async def scenario():
        await start_dashboard_manager(state, 'serial', manager, lambda: manager.start([{'port': 'TEST'}]))
        assert await asyncio.to_thread(entered.wait, 1)
        manager._monitor._stop_timeout = .1
        stop = asyncio.create_task(stop_dashboard_manager_transaction(state, 'serial', manager))
        await asyncio.sleep(.01)
        assert not stop.done()
        with pytest.raises(DashboardStopPending):
            await stop
        assert 'serial_port' in rm.get_status() and manager.worker_alive
        release.set()
        manager._monitor._stop_timeout = 1
        await stop_dashboard_manager_transaction(state, 'serial', manager)
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        manager.stop()
    assert not rm.get_status() and not manager.worker_alive


def test_uart_inventory_uses_same_guard_as_open_in_shared_runtime(monkeypatch, tmp_path):
    from mklink.remote.api import create_app
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [
        metadata('MI_04'), metadata('MI_02', device='COM7'), metadata('', device='COM8'),
        metadata('', device='COM9', mklink=False),
    ])
    app = create_app(auth_token=None, project_root=str(tmp_path))
    app.state.mklink_state['shared_runtime'] = True
    with TestClient(app) as client:
        response = client.get('/api/ports/uart')
    assert response.status_code == 200
    assert [p['device'] for p in response.json()] == ['COM7', 'COM9']


def test_monitor_send_accepts_same_alias_as_open(monkeypatch, fake_port):
    from mklink.remote.dashboards import SerialStreamManager
    writes = []
    monkeypatch.setattr(fake_port, 'write', lambda self, data: writes.append(data), raising=False)
    manager = SerialStreamManager()
    manager.start([{'port': r'\\.\com006'}])
    try:
        assert manager.get_status()['config'][0]['port'] == 'COM6'
        assert manager.get_status()['ports']['COM6'] == 'open'
        assert manager.send('com006', b'abc')
        assert writes == [b'abc']
    finally:
        manager.stop()
