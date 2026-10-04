"""Protocol RX has bounded retention and fails without blocking the reader."""
import threading
import pytest

from mklink.serial._monitor import SerialMonitor, _ProtocolQueue
from test_serial_autoreply import ports, wait_for


def test_protocol_queue_preserves_chunks_and_aborts_on_overflow():
    inbox = _ProtocolQueue()
    payload = b'a' * 4096 + b'b' * 17
    inbox.feed(payload)
    assert inbox.get_nowait() + inbox.get_nowait() == payload
    inbox.feed(b'x' * (inbox.MAX_CHUNKS * inbox.CHUNK_BYTES))
    with pytest.raises(BufferError, match='overflow'):
        inbox.feed(b'y')
    assert inbox.qsize() == inbox.MAX_CHUNKS
    with pytest.raises(BufferError):
        inbox.check()


@pytest.mark.parametrize('failure', ['overflow', 'reader'])
@pytest.mark.parametrize('consumer', ['read', 'write', 'return'])
def test_reader_failure_aborts_protocol_and_preserves_other_port(ports, monkeypatch, failure, consumer):
    admitted, release, trigger = threading.Event(), threading.Event(), threading.Event()
    errors = []
    original_read = ports.read_available
    def read(port):
        if port.name == 'A' and trigger.is_set():
            raise OSError('synthetic reader loss')
        return original_read(port)
    monkeypatch.setattr(ports, 'read_available', read)
    class Sender:
        def __init__(self, read, write, **kwargs):
            self.read, self.write = read, write
        def send(self, *args):
            admitted.set()
            assert release.wait(2)
            if consumer == 'read': self.read(20)
            if consumer == 'write': self.write(b'forbidden-after-loss')
    monkeypatch.setattr('mklink.serial._ymodem.YModemSender', Sender)
    monitor = SerialMonitor([{'port': 'A'}, {'port': 'B'}])
    monitor.start()
    first, second = ports.instances
    def transfer():
        try:
            monitor.send_ymodem('A', b'file', 'data.bin')
        except Exception as error:
            errors.append(error)
    worker = threading.Thread(target=transfer)
    worker.start()
    try:
        assert admitted.wait(1)
        inbox = monitor._protocol_queues['A']
        if failure == 'overflow':
            first.rx.put(b'x' * ((_ProtocolQueue.MAX_CHUNKS + 1) * _ProtocolQueue.CHUNK_BYTES))
        else:
            trigger.set()
        wait_for(lambda: not first.is_open)
        assert inbox.qsize() <= _ProtocolQueue.MAX_CHUNKS
        assert monitor.send('B', b'neighbor')
        release.set()
        worker.join(1)
        assert not worker.is_alive() and len(errors) == 1
        assert ('overflow' if failure == 'overflow' else 'reader loss') in str(errors[0])
        assert not first.writes and second.writes[0][0] == b'neighbor'
        assert 'A' not in monitor._protocol_queues and not monitor._protocol_handoffs
    finally:
        release.set()
        worker.join(2)
        monitor.stop()


def test_sender_constructor_failure_releases_protocol_ownership(ports, monkeypatch):
    def fail(*args, **kwargs): raise RuntimeError('constructor failed')
    monkeypatch.setattr('mklink.serial._ymodem.YModemSender', fail)
    monitor = SerialMonitor([{'port': 'A'}])
    monitor.start()
    try:
        with pytest.raises(RuntimeError, match='constructor failed'):
            monitor.send_ymodem('A', b'file', 'data.bin')
        assert not monitor._protocol_queues
        assert monitor.send('A', b'normal')
    finally:
        monitor.stop()
