import json
import queue
import threading
import time

import pytest
from websockets.sync.server import serve
from mklink.remote.rtt_subscription import RttSubscription, BUFFER_BYTES
from mklink.remote.stream_protocol import Frame, StreamType, RTT_TERMINAL_UTF8, encode_frame


def frame(sequence, payload, *, kind=StreamType.RTT_RAW, flags=RTT_TERMINAL_UTF8):
    return encode_frame(Frame(kind, flags, int(StreamType.RTT_RAW), sequence, 0, 1, payload))


@pytest.fixture
def source():
    queues = []
    lock = threading.Lock()
    def handler(ws):
        assert ws.request.headers['Authorization'] == 'Bearer test'
        outgoing = queue.Queue()
        with lock:
            queues.append(outgoing)
        ws.send(frame(0, json.dumps({'last_sequence': 0}).encode(), kind=StreamType.CONTROL, flags=0))
        try:
            while True:
                message = outgoing.get(timeout=5)
                if message is None:
                    break
                ws.send(message)
        finally:
            ws.close()
    server = serve(handler, '127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def publish(message):
        with lock:
            for outgoing in queues:
                outgoing.put(message)
    try:
        yield {'port': server.socket.getsockname()[1], 'token': 'test'}, publish
    finally:
        publish(None)
        server.shutdown()
        thread.join(timeout=3)
        assert not thread.is_alive()


def wait_sequence(reader, sequence):
    deadline = time.monotonic()+3
    while reader._sequence < sequence and not reader.error and time.monotonic() < deadline:
        time.sleep(.01)
    assert reader._sequence == sequence, reader.error


def test_real_socket_utf8_ansi_and_independent_consumers(source):
    info, publish = source
    first, second = RttSubscription(info), RttSubscription(info)
    try:
        text = '\x1b[31m中文 without newline\r'
        publish(frame(1, text.encode()))
        wait_sequence(first, 1); wait_sequence(second, 1)
        assert first.read(0)['text'] == text
        assert first.read(0)['text'] == ''
        assert second.read(0)['text'] == text
        first.close()
        publish(frame(2, b'second-only'))
        wait_sequence(second, 2)
        assert second.read(0)['text'] == 'second-only'
    finally:
        first.close(); second.close()
    assert not first._thread.is_alive() and not second._thread.is_alive()


def test_slow_consumer_reports_local_overflow_and_sequence_gaps(source):
    info, publish = source
    reader = RttSubscription(info)
    try:
        for seq in range(1, 5):
            publish(frame(seq, b'x' * (BUFFER_BYTES//2)))
        wait_sequence(reader, 4)
        page = reader.read(0)
        assert len(page['text']) == BUFFER_BYTES
        assert page['dropped_bytes'] == BUFFER_BYTES and page['missing_batches'] == 0
        publish(frame(7, b'next'))
        wait_sequence(reader, 7)
        assert reader.read(0)['missing_batches'] == 2
        publish(frame(8, b'x'*(BUFFER_BYTES+1)))
        wait_sequence(reader, 8)
        page = reader.read(0)
        assert page['text'] == '' and page['dropped_bytes'] == 2*BUFFER_BYTES+1
    finally:
        reader.close()


@pytest.mark.parametrize('payload', [b'bad frame', frame(1, b'\xff'), frame(1, b'text', flags=1)])
def test_invalid_frames_fail_explicitly_without_reconnect(source, payload):
    info, publish = source
    reader = RttSubscription(info)
    try:
        publish(payload)
        page = reader.read(2)
        assert page['error'] and page['text'] == ''
    finally:
        reader.close()
    assert not reader._thread.is_alive()
