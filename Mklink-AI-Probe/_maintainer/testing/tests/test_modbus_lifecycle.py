from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from mklink.modbus._session import ModbusWorker


def test_queue_timeout_never_executes_late_operation():
    worker = ModbusWorker(object(), 1)
    entered, release = threading.Event(), threading.Event()
    writes = []
    worker.start()
    with ThreadPoolExecutor() as pool:
        first = pool.submit(worker._submit, lambda: (entered.set(), release.wait(2)))
        assert entered.wait(1)
        try:
            with pytest.raises(TimeoutError, match='cancelled before execution'):
                worker._submit(lambda: writes.append('late'), timeout=.02)
        finally:
            release.set()
            first.result(1)
            worker.stop()
    assert writes == []


def test_running_timeout_reports_unknown_without_replay_and_retains_worker():
    worker = ModbusWorker(object(), 1)
    entered, release = threading.Event(), threading.Event()
    writes = []
    def operation():
        entered.set()
        release.wait(2)
        writes.append('once')
    worker.start()
    try:
        with pytest.raises(TimeoutError, match='result unknown, do not retry'):
            worker._submit(operation, timeout=.02)
        assert entered.is_set() and worker.worker_alive
        with pytest.raises(TimeoutError, match='ownership retained'):
            worker.stop(timeout=.01)
        assert worker.worker_alive
        with pytest.raises(RuntimeError, match='finish stopping'):
            worker.start()
        with pytest.raises(RuntimeError, match='not running'):
            worker._submit(lambda: writes.append('new'))
    finally:
        release.set()
        worker.stop(timeout=1)
    assert writes == ['once']
    worker.start()
    assert worker._submit(lambda: 'fresh') == 'fresh'
    worker.stop()


def test_stop_cancels_waiters_instead_of_draining_their_operations():
    worker = ModbusWorker(object(), 1)
    entered, release = threading.Event(), threading.Event()
    writes = []
    worker.start()
    with ThreadPoolExecutor() as pool:
        first = pool.submit(worker._submit, lambda: (entered.set(), release.wait(2)))
        assert entered.wait(1)
        queued = pool.submit(worker._submit, lambda: writes.append('queued'))
        deadline = time.monotonic() + 1
        while not worker._queue.qsize() and time.monotonic() < deadline:
            time.sleep(.001)
        assert worker._queue.qsize() == 1
        worker.request_stop()
        try:
            with pytest.raises(RuntimeError, match='cancelled before execution'):
                queued.result(1)
        finally:
            release.set()
            first.result(1)
            worker.stop()
    assert writes == []


def test_queue_is_bounded_and_does_not_accept_unbounded_pending_work():
    worker = ModbusWorker(object(), 1)
    entered, release = threading.Event(), threading.Event()
    worker.start()
    with ThreadPoolExecutor() as pool:
        first = pool.submit(worker._submit, lambda: (entered.set(), release.wait(2)))
        assert entered.wait(1)
        try:
            for _ in range(64):
                with pytest.raises(TimeoutError, match='cancelled before execution'):
                    worker._submit(lambda: pytest.fail('cancelled operation ran'), timeout=0)
            with pytest.raises(RuntimeError, match='queue is full'):
                worker._submit(lambda: pytest.fail('overflow operation ran'), timeout=0)
        finally:
            release.set()
            first.result(1)
            worker.stop()


def test_operation_timeout_exception_is_not_rewritten_as_wait_timeout():
    worker = ModbusWorker(object(), 1)
    worker.start()
    def failing():
        raise TimeoutError('device timeout')
    try:
        with pytest.raises(TimeoutError, match='^device timeout$'):
            worker._submit(failing)
    finally:
        worker.stop()


@pytest.fixture
def client_factory(monkeypatch):
    class Client:
        instances = []
        def __init__(self, **kwargs):
            self.options = kwargs
            self.closed = False
            self.calls = []
            self.instances.append(self)
        def open(self):
            return True
        def close(self):
            self.closed = True
        def read_holding_registers(self, address, count, slave):
            self.calls.append((address, count, slave))
            return list(range(address, address + count))
    monkeypatch.setattr('mklink.modbus._client.ModbusClient', Client)
    return Client


def test_cancelled_start_waits_for_open_then_closes_without_target_lease(client_factory, monkeypatch):
    from mklink.remote.api import start_dashboard_manager
    from mklink.remote.dashboards import ModbusStreamManager
    from mklink.remote.resource_manager import ResourceManager, ResourceGroup
    entered, release = threading.Event(), threading.Event()
    def delayed_open(self):
        entered.set()
        assert release.wait(2)
        return True
    monkeypatch.setattr(client_factory, 'open', delayed_open)
    manager = ModbusStreamManager()
    rm = ResourceManager()
    rm.acquire(ResourceGroup.TARGET_DEBUG, 'independent-target')
    async def scenario():
        task = asyncio.create_task(start_dashboard_manager(
            {'resource_manager': rm}, 'modbus', manager,
            lambda: manager.start({'port': 'TEST'}, 1, [])))
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(.01)
        assert not task.done() and not manager.running
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        manager.stop()
    assert all(client.closed for client in client_factory.instances)
    assert not manager.worker_alive
    assert set(rm.get_status()) == {'target_debug'}


def test_stop_retains_client_workers_and_lease_until_io_finishes(client_factory, monkeypatch):
    from mklink.remote.api import start_dashboard_manager, stop_dashboard_manager_transaction, DashboardStopPending
    from mklink.remote.dashboards import ModbusStreamManager
    from mklink.remote.resource_manager import ResourceManager
    entered, release = threading.Event(), threading.Event()
    def read(self, address, count, slave):
        entered.set()
        assert release.wait(2)
        assert not self.closed
        return [42]
    monkeypatch.setattr(client_factory, 'read_holding_registers', read)
    manager = ModbusStreamManager()
    manager._stop_timeout = .05
    rm = ResourceManager()
    state = {'resource_manager': rm}
    async def scenario():
        await start_dashboard_manager(state, 'modbus', manager,
            lambda: manager.start({'port': 'TEST'}, 1, [{'addr': 0}]))
        assert await asyncio.to_thread(entered.wait, 1)
        task = asyncio.create_task(stop_dashboard_manager_transaction(state, 'modbus', manager))
        await asyncio.sleep(.005)
        assert not task.done()
        with pytest.raises(DashboardStopPending):
            await task
        assert manager.worker_alive and not manager._client.closed
        assert manager.get_status()['stopping']
        assert 'modbus_port' in rm.get_status()
        with pytest.raises(RuntimeError, match='stopping'):
            manager.transaction(3, 0, quantity=1)
        with pytest.raises(DashboardStopPending):
            await start_dashboard_manager(state, 'modbus', manager,
                lambda: manager.start({'port': 'OTHER'}, 1, []))
        release.set()
        manager._stop_timeout = 1
        await stop_dashboard_manager_transaction(state, 'modbus', manager)
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        manager.stop()
    assert not rm.get_status() and not manager.worker_alive
    assert client_factory.instances[0].closed


@pytest.mark.parametrize('registers', [[{}], [{'addr': -1}], [{'addr': 65535, 'type': 'float'}],
                                      [{'addr': 0, 'type': 'unknown'}], [{'addr': 0}, {'addr': 0}]])
def test_invalid_registers_never_open_the_port(client_factory, registers):
    from mklink.remote.dashboards import ModbusStreamManager
    manager = ModbusStreamManager()
    with pytest.raises(ValueError):
        manager.start({'port': 'TEST'}, 1, registers)
    assert client_factory.instances == []
    assert not manager.worker_alive and manager._client is None


def test_failure_starting_poll_thread_cleans_io_worker_and_client(client_factory, monkeypatch):
    from mklink.remote.dashboards import ModbusStreamManager
    original = threading.Thread.start
    def start(thread):
        if thread.name == 'mklink-modbus-poll':
            raise RuntimeError('thread creation failed')
        return original(thread)
    monkeypatch.setattr(threading.Thread, 'start', start)
    manager = ModbusStreamManager()
    with pytest.raises(RuntimeError, match='thread creation failed'):
        manager.start({'port': 'TEST'}, 1, [{'addr': 0}])
    assert client_factory.instances[0].closed
    assert not manager.worker_alive and not manager.running


def test_loop_stop_timeout_keeps_thread_until_transaction_finishes(client_factory, monkeypatch):
    from mklink.remote.dashboards import ModbusStreamManager
    entered, release = threading.Event(), threading.Event()
    def read(self, address, count, slave):
        entered.set()
        assert release.wait(2)
        return [1]
    monkeypatch.setattr(client_factory, 'read_holding_registers', read)
    manager = ModbusStreamManager()
    manager._stop_timeout = .01
    manager.start({'port': 'TEST'}, 1, [])
    manager.start_loop(3, 0, quantity=1, count=1)
    assert entered.wait(1)
    try:
        with pytest.raises(TimeoutError, match='still active'):
            manager.stop_loop()
        assert manager._loop_thread.is_alive() and manager.get_status()['loop']['running']
        with pytest.raises(RuntimeError, match='already running'):
            manager.start_loop(3, 0, quantity=1)
    finally:
        release.set()
        manager._stop_timeout = 1
        manager.stop()
    assert client_factory.instances[0].closed and not manager.worker_alive


def test_poll_groups_do_not_drop_multiword_registers_at_the_protocol_limit(client_factory):
    from mklink.modbus._format import RegisterSpec
    client = client_factory()
    worker = ModbusWorker(client, 1)
    specs = [RegisterSpec(addr=i) for i in range(124)]
    specs += [RegisterSpec(addr=124, type='uint32'), RegisterSpec(addr=126)]
    worker.start()
    try:
        values = worker.submit_read(specs)
    finally:
        worker.stop()
    assert values[124] == (124 << 16) + 125 and values[126] == 126
    assert len(values) == 126
    assert client.calls == [(0, 124, 1), (124, 3, 1)]


def test_finite_loop_finishes_without_waiting_an_extra_interval(client_factory):
    from mklink.remote.dashboards import ModbusStreamManager
    manager = ModbusStreamManager()
    manager.start({'port': 'TEST'}, 1, [])
    try:
        manager.start_loop(3, 0, quantity=1, count=1, interval=3600)
        manager._loop_thread.join(timeout=1)
        assert not manager._loop_thread.is_alive()
        assert client_factory.instances[0].calls == [(0, 1, 1)]
        events = [event for event in manager._history if event['event'] == 'loop']
        assert [event['status'] for event in events] == ['started', 'stopped']
        assert events[-1]['completed'] == 1
        assert events[-1]['revision'] > events[0]['revision']
        assert manager.get_status()['loop'] == {key: value for key, value in events[-1].items()
                                               if key not in {'event', 'status'}}
    finally:
        manager.stop()


def test_loop_thread_start_failure_restores_idle_state(client_factory, monkeypatch):
    from mklink.remote.dashboards import ModbusStreamManager
    manager = ModbusStreamManager()
    manager.start({'port': 'TEST'}, 1, [])
    original_start = threading.Thread.start
    def fail_loop(thread):
        if thread.name == 'mklink-modbus-loop':
            raise RuntimeError('thread unavailable')
        return original_start(thread)
    monkeypatch.setattr(threading.Thread, 'start', fail_loop)
    try:
        with pytest.raises(RuntimeError, match='thread unavailable'):
            manager.start_loop(3, 0, quantity=1, count=1)
        assert not manager.get_status()['loop']['running']
        assert manager._loop_thread is None
        assert manager.running and manager.worker_alive
        assert client_factory.instances[0].calls == []
    finally:
        manager.stop()


def test_incomplete_poll_response_is_an_error(client_factory, monkeypatch):
    from mklink.modbus._format import RegisterSpec
    monkeypatch.setattr(client_factory, 'read_holding_registers', lambda *args: [])
    worker = ModbusWorker(client_factory(), 1)
    worker.start()
    try:
        with pytest.raises(OSError, match='incomplete'):
            worker.submit_read([RegisterSpec(0)])
    finally:
        worker.stop()


def test_modbus_explicit_open_uses_finite_write_timeout_and_real_rtu_codec(monkeypatch, tmp_path):
    from mklink.modbus._client import ModbusClient
    from mklink.modbus._session import modbus_crc16
    monkeypatch.setenv('MKLINK_LOCK_DIR', str(tmp_path))
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [])
    class Wire:
        is_open = True
        write_timeout = None
        def __init__(self):
            self.pending = b''
            self.writes = []
        @property
        def in_waiting(self):
            return len(self.pending)
        def write(self, data):
            self.writes.append(bytes(data))
            payload = bytes.fromhex('01 03 02 00 2A')
            self.pending = payload + modbus_crc16(payload).to_bytes(2, 'little')
            return len(data)
        def read(self, count):
            data, self.pending = self.pending[:count], self.pending[count:]
            return data
        def close(self):
            self.is_open = False
    wire = Wire()
    monkeypatch.setattr('serial.serial_for_url', lambda *a, **k: wire)
    client = ModbusClient('TEST', timeout=.2, retries=0)
    assert client.open()
    try:
        assert wire.write_timeout == .2
        assert client.read_holding_registers(0, 1, 1) == [42]
        assert len(wire.writes) == 1
        assert wire.writes[0][:6] == bytes.fromhex('01 03 00 00 00 01')
    finally:
        client.close()
    assert not wire.is_open


def test_serial_stop_closes_admission_even_when_read_worker_is_retained(monkeypatch):
    from mklink.serial._monitor import SerialMonitor
    monitor = SerialMonitor([{'port': 'TEST'}])
    monitor._stop_event.set()
    assert monitor.send('TEST', b'new') is False
    with pytest.raises(RuntimeError, match='stopping'):
        monitor.send_ymodem('TEST', b'data', 'test.bin')
