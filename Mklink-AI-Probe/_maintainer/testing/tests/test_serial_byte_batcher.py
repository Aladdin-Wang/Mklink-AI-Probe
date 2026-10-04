import asyncio
import threading
import pytest

from mklink.remote.serial_stream import SerialByteBatcher, SERIAL_BATCH_BYTES
from mklink.remote.stream_api import create_stream_registry
from mklink.remote.stream_protocol import encode_serial_payload, decode_serial_payload


def test_source_changes_flush_without_mixing_ports_or_directions():
    batches = []
    batcher = SerialByteBatcher(lambda data, direction, port, first, last: batches.append((port, direction, data)))
    batcher.feed(b'A', 'RX', 'ONE')
    batcher.feed(b'B', 'RX', 'TWO')
    batcher.feed(b'C', 'RX', 'ONE')
    batcher.feed(b'D', 'TX', 'ONE')
    batcher.close()
    assert batches == [('ONE', 'RX', b'A'), ('TWO', 'RX', b'B'), ('ONE', 'RX', b'C'), ('ONE', 'TX', b'D')]


@pytest.mark.parametrize('port', ['COM7', '设备串口', 'X' * 255])
def test_serial_source_codec_is_bounded_and_lossless(port):
    session = '1234567890abcdef' * 2
    raw = bytes(range(256)) * 16
    payload = encode_serial_payload(session, port, raw)
    assert decode_serial_payload(payload) == (session, port, raw)
    assert len(payload) <= 4368


@pytest.mark.parametrize('session,port,data', [('11', 'COM7', b'A'), ('11'*16, '', b'A'),
    ('11'*16, 'X'*256, b'A'), ('11'*16, 'COM7', b''), ('11'*16, 'COM7', b'A'*4097)])
def test_serial_source_codec_rejects_invalid_dimensions(session, port, data):
    with pytest.raises(ValueError): encode_serial_payload(session, port, data)


@pytest.mark.parametrize('payload', [b'', b'X'*17, b'X'*16+b'\x00A', b'X'*16+b'\x03AB',
    b'X'*16+b'\x01\xffA'])
def test_serial_source_decoder_rejects_truncation_or_invalid_utf8(payload):
    with pytest.raises(ValueError): decode_serial_payload(payload)


def test_serial_small_reads_survive_blocked_event_loop_without_byte_loss():
    async def scenario():
        hub = create_stream_registry()["serial"]
        queue = hub.subscribe()
        batcher = SerialByteBatcher(lambda data, direction, port, first, last: hub.publish(data, len(data)))
        original = b"".join(f"uart={i:08d},DATA_1234\r\n".encode() for i in range(2000))

        def producer():
            for index in range(0, len(original), 7):
                batcher.feed(original[index:index + 7], "RX", "COM7")
            batcher.close()

        # Model SVD/symbol work preventing the loop from servicing subscriptions.
        worker = threading.Thread(target=producer)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
        await asyncio.sleep(0)
        payloads = []
        while not queue.empty():
            payloads.append(bytes(queue.get_nowait()))
            queue.task_done()
        assert b"".join(payloads) == original
        assert hub.stats().dropped_batches == 0
        assert all(0 < len(payload) <= SERIAL_BATCH_BYTES for payload in payloads)
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_serial_batching_preserves_rx_tx_order_and_flushes_last_partial_on_close():
    batches = []
    batcher = SerialByteBatcher(lambda data, direction, port, first, last: batches.append((direction, data)))
    batcher.feed(b"\x00\xff", "RX", "COM7")
    batcher.feed(b"\x80", "RX", "COM7")
    batcher.feed(b"AT\r\n", "TX", "COM7")
    batcher.feed(b"OK", "RX", "COM7")
    batcher.close()
    batcher.close()
    assert batches == [("RX", b"\x00\xff\x80"), ("TX", b"AT\r\n"), ("RX", b"OK")]


def test_serial_single_byte_is_delivered_without_waiting_for_more_input():
    delivered = threading.Event()
    batches = []

    def publish(data, direction, port, first, last):
        batches.append((direction, data))
        delivered.set()

    batcher = SerialByteBatcher(publish)
    batcher.start()
    try:
        batcher.feed(b"C", "RX", "COM7")
        assert delivered.wait(timeout=1)
        assert batches == [("RX", b"C")]
    finally:
        batcher.close()
