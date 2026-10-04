"""Raw exchange reserves the existing reader instead of opening another port."""
import threading
import pytest

from mklink.serial._monitor import SerialMonitor
from test_serial_autoreply import ports, wait_for


def test_exchange_blocks_same_port_and_preserves_neighbor(ports):
    trace = []
    monitor = SerialMonitor([{'port': 'A'}, {'port': 'B'}],
        chunk_callback=lambda p, d, data, t, mono: trace.append((p, d, data)))
    monitor.start()
    first, second = ports.instances
    result = []
    worker = threading.Thread(target=lambda: result.append(monitor.exchange('A', b'Q', .15)))
    worker.start()
    try:
        wait_for(lambda: bool(first.writes))
        assert first.writes[0][0] == b'Q'
        assert not monitor.send('A', b'interference')
        assert monitor.send('B', b'neighbor')
        with pytest.raises(RuntimeError, match='active transfer'):
            monitor.exchange('A', b'duplicate', .01)
        first.rx.put(b'answer')
        worker.join(1)
        assert result == [b'answer'] and not worker.is_alive()
        assert [item[0] for item in first.writes] == [b'Q']
        assert ('A', 'RX', b'answer') in trace
        assert monitor.send('A', b'normal')
        assert len(ports.instances) == 2 and not monitor._protocol_queues
    finally:
        worker.join(1)
        monitor.stop()


@pytest.mark.parametrize('data,timeout', [(b'x' * 4097, .1), (b'x', float('nan')),
    (b'x', True), (b'x', -1), (b'x', 6)])
def test_invalid_exchange_does_not_reserve_or_write(ports, data, timeout):
    monitor = SerialMonitor([{'port': 'A'}])
    monitor.start()
    try:
        with pytest.raises(ValueError): monitor.exchange('A', data, timeout)
        assert not monitor._protocol_queues and not ports.instances[0].writes
    finally:
        monitor.stop()


def test_response_overflow_fails_and_releases_without_replaying(ports):
    monitor = SerialMonitor([{'port': 'A'}])
    monitor.start()
    port = ports.instances[0]
    errors = []
    def run():
        try: monitor.exchange('A', b'Q', 1)
        except Exception as error: errors.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        wait_for(lambda: bool(port.writes))
        port.rx.put(b'x' * 65537)
        worker.join(1)
        assert not worker.is_alive() and len(errors) == 1
        assert isinstance(errors[0], BufferError)
        assert not monitor._protocol_queues and not monitor._protocol_handoffs
        assert len(port.writes) == 1 and monitor.send('A', b'normal')
    finally:
        worker.join(2)
        monitor.stop()


def test_handoff_failure_always_releases_admission(ports):
    monitor = SerialMonitor([{'port': 'A'}])
    monitor.start()
    def fail(): raise RuntimeError('handoff failed')
    try:
        with pytest.raises(RuntimeError, match='handoff failed'):
            with monitor._protocol_session('A', tail=fail): pass
        assert not monitor._protocol_queues and monitor.send('A', b'normal')
    finally:
        monitor.stop()


def test_stop_interrupts_window_and_releases_protocol(ports):
    monitor = SerialMonitor([{'port': 'A'}])
    monitor.start()
    errors = []
    def run():
        try: monitor.exchange('A', b'Q', 5)
        except Exception as error: errors.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        wait_for(lambda: bool(ports.instances[0].writes))
        monitor.stop()
        worker.join(1)
        assert not worker.is_alive() and not monitor._protocol_queues
        assert len(errors) == 1 and 'cancelled' in str(errors[0])
    finally:
        monitor.stop()
        worker.join(1)


def test_partial_write_does_not_retry_and_releases_admission(ports):
    monitor = SerialMonitor([{'port': 'A'}])
    monitor.start()
    port = ports.instances[0]
    port.fail = True
    try:
        with pytest.raises(OSError, match='partial physical write'):
            monitor.exchange('A', b'Q', .1)
        assert len(port.writes) == 1 and not monitor._protocol_queues
    finally:
        monitor.stop()
