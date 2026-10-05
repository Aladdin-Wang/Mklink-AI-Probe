"""Exercise the production stream router over real loopback TCP sockets."""
import socket
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI
from websockets.sync.client import connect

from mklink.remote.stream_api import create_stream_registry, create_stream_router, STREAM_TYPES
from mklink.remote.stream_protocol import decode_frame, StreamType, RTT_TERMINAL_UTF8


@pytest.fixture(scope='module')
def stream_server():
    registry = create_stream_registry()
    app = FastAPI()
    app.include_router(create_stream_router(registry, STREAM_TYPES, auth_token='test-only'))
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(32)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', ws_ping_interval=None))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        yield listener.getsockname()[1], registry
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive()


@pytest.mark.parametrize('channel', range(8))
def test_nonreading_tcp_peer_drops_without_blocking_neighbor_and_releases_queue(stream_server, channel):
    port, registry = stream_server
    hub = registry[f'rtt-terminal-{channel}']
    raw = socket.socket()
    raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
    raw.settimeout(3)
    raw.connect(('127.0.0.1', port))
    url = f'ws://127.0.0.1:{port}/ws/streams/rtt-terminal-{channel}'
    options = dict(additional_headers={'Authorization': 'Bearer test-only'},
                   compression=None, close_timeout=.2, open_timeout=3)
    slow = fast = fast_raw = None
    try:
        slow = connect(url, sock=raw, max_queue=1, **options)
        fast_raw = socket.create_connection(('127.0.0.1', port), timeout=3)
        fast = connect(url, sock=fast_raw, **options)
        assert decode_frame(slow.recv(timeout=3)).stream_type == StreamType.CONTROL
        assert decode_frame(fast.recv(timeout=3)).stream_type == StreamType.CONTROL
        deadline = time.monotonic() + 3
        while hub.stats().active_clients != 2 and time.monotonic() < deadline:
            time.sleep(.01)
        assert hub.stats().active_clients == 2
        payload = bytes([ord('0') + channel]) * 65536
        # Stop consuming slow's socket. Bound the test by both time and bytes.
        deadline = time.monotonic() + 20
        for _ in range(512):
            sequence = hub.publish(payload, item_count=1, flags=RTT_TERMINAL_UTF8)
            while True:
                frame = decode_frame(fast.recv(timeout=3))
                if frame.stream_type != StreamType.CONTROL:
                    break
            assert frame.sequence == sequence and frame.payload == payload
            if hub.stats().dropped_batches >= 8:
                break
            assert time.monotonic() < deadline, 'TCP pressure was not observed within the time limit'
        stats = hub.stats()
        assert stats.dropped_batches >= 8, 'No actual server-side queue overflow was observed'
        assert stats.queue_high_water_mark <= 64
        assert stats.dropped_bytes == stats.dropped_batches * len(payload)
        # Abort the unread TCP connection; the receiving ASGI task must cancel
        # the blocked sender and unsubscribe without waiting for the peer to read.
        raw.shutdown(socket.SHUT_RDWR)
        raw.close()
        deadline = time.monotonic() + 3
        while hub.stats().active_clients != 1 and time.monotonic() < deadline:
            time.sleep(.01)
        assert hub.stats().active_clients == 1
        expected = hub.publish(b'neighbor-alive', item_count=1, flags=RTT_TERMINAL_UTF8)
        while True:
            frame = decode_frame(fast.recv(timeout=3))
            if frame.stream_type != StreamType.CONTROL:
                break
        assert frame.sequence == expected and frame.payload == b'neighbor-alive'
    finally:
        raw.close()
        if slow is not None:
            slow.close()
        if fast is not None:
            fast.close()
        if fast_raw is not None:
            fast_raw.close()
    deadline = time.monotonic() + 3
    while hub.stats().active_clients and time.monotonic() < deadline:
        time.sleep(.01)
    assert hub.stats().active_clients == 0
