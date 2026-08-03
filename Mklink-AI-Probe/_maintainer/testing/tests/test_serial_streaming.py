from __future__ import annotations

import asyncio
import base64
import threading

from fastapi.testclient import TestClient

from mklink.local_resources import local_resource_status
from mklink.remote.api import create_app
from mklink.remote.dashboards import SerialStreamManager
from mklink.serial import _monitor as monitor_module
from mklink.serial._monitor import SerialEvent, SerialMonitor
from mklink.serial._port import _PortLock


def test_serial_port_lock_releases_owner_and_can_be_reacquired(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))

    for _ in range(2):
        lock = _PortLock("TEST_PORT")
        assert lock.acquire() is True
        lock.release()

        status = local_resource_status("TEST_PORT")["serial_locks"][0]
        assert status["owner_pid"] == 0
        assert status["owner_alive"] is False


def test_modbus_start_reports_busy_serial_port(monkeypatch, tmp_path):
    class BusyModbusClient:
        def __init__(self, **_kwargs):
            pass

        def open(self):
            return False

    monkeypatch.setattr("mklink.modbus._client.ModbusClient", BusyModbusClient)
    app = create_app(auth_token=None, project_root=str(tmp_path))

    with TestClient(app) as client:
        response = client.post("/api/dash/modbus/start", json={"port": "BUSY_PORT"})

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "conflict": "serial port BUSY_PORT is busy or unavailable",
            "resource": "modbus_port",
        },
    }


def test_serial_monitor_emits_partial_rx_chunk_before_line_event(monkeypatch):
    chunk_ready = threading.Event()
    chunks = []
    events = []

    class FakeSerialPort:
        def __init__(self, **_kwargs):
            self.is_open = False
            self._read = False

        def open(self):
            self.is_open = True
            return True

        def close(self):
            self.is_open = False

        def read_available(self):
            if self._read:
                return b""
            self._read = True
            return b"prompt> "

    monkeypatch.setattr(monitor_module, "SerialPort", FakeSerialPort)
    monitor = SerialMonitor(
        ports=[{"port": "TEST"}],
        event_callback=events.append,
        chunk_callback=lambda port, direction, data, timestamp: (
            chunks.append((port, direction, data, timestamp)),
            chunk_ready.set(),
        ),
    )

    monitor.start()
    assert chunk_ready.wait(1.0)
    monitor.stop()

    assert len(chunks) == 1
    assert chunks[0][:3] == ("TEST", "RX", b"prompt> ")
    assert events == []


def test_serial_stream_manager_publishes_exact_chunks_and_counts_bytes(monkeypatch):
    class FakeMonitor:
        def __init__(self, **kwargs):
            self.event_callback = kwargs["event_callback"]
            self.chunk_callback = kwargs["chunk_callback"]
            self.port_status = {"TEST": "open"}

        def start(self):
            pass

        def stop(self):
            pass

        def send(self, _port, _data):
            return True

        def send_all(self, _data):
            pass

    monkeypatch.setattr(monitor_module, "SerialMonitor", FakeMonitor)
    manager = SerialStreamManager()
    queue = manager._bridge.add_client()
    config = [{"port": "TEST", "baudrate": 115200}]
    manager.start(config)
    monitor = manager._monitor

    raw = b"\x1b[31mready> \xff"
    monitor.chunk_callback("TEST", "RX", raw, 123.5)
    monitor.event_callback(SerialEvent(123.5, "TEST", "RX", raw))

    opening = queue.get_nowait()
    terminal = queue.get_nowait()
    log_event = queue.get_nowait()
    assert opening["event"] == "status"
    assert terminal == {
        "event": "terminal",
        "timestamp": 123.5,
        "port": "TEST",
        "direction": "RX",
        "data_base64": base64.b64encode(raw).decode("ascii"),
    }
    assert log_event["event"] == "data"
    assert manager.get_status()["config"] == config
    assert manager.get_status()["stats"] == {
        "rx_count": 1,
        "tx_count": 0,
        "rx_bytes": len(raw),
        "tx_bytes": 0,
        "bytes_per_sec": float(len(raw)),
    }
    manager.stop()
    manager._bridge.remove_client(queue)


def test_serial_sse_reconnect_starts_with_current_status():
    async def first_event():
        manager = SerialStreamManager()
        generator = manager.sse_generator()
        try:
            return await anext(generator)
        finally:
            await generator.aclose()

    payload = asyncio.run(first_event())
    assert '"event": "status"' in payload
    assert '"running": false' in payload
