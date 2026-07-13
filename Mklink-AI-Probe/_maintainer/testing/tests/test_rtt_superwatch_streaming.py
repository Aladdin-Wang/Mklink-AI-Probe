import asyncio
from types import SimpleNamespace

import pytest

from mklink.remote.dashboards import RttStreamManager, SuperWatchStreamManager
from mklink.remote.stream_hub import StreamHub
from mklink.remote.stream_protocol import (
    RTT_RAW_UTF8_LINES,
    SUPERWATCH_METADATA_JSON,
    SUPERWATCH_SAMPLE_MAJOR_FLOAT32,
    StreamType,
    decode_rtt_lines,
    decode_superwatch_metadata,
    decode_waveform_samples,
)


def _drain(loop, turns=4):
    for _ in range(turns):
        loop.run_until_complete(asyncio.sleep(0))


def test_rtt_arbitrary_chunks_preserve_utf8_crlf_and_partial_tail():
    async def scenario():
        hub = StreamHub(max_batches_per_client=8)
        queue = hub.subscribe()
        manager = RttStreamManager(stream_hub=hub, raw_batch_lines=2)

        encoded = "alpha\r\n温度=25\nlast".encode("utf-8")
        split_inside_multibyte = encoded.index("温".encode("utf-8")) + 1
        manager.feed_rtt_bytes(encoded[:split_inside_multibyte])
        manager.feed_rtt_bytes(encoded[split_inside_multibyte:-2])
        manager.feed_rtt_bytes(encoded[-2:])
        manager.flush_pending(final=True)

        first = await queue.get()
        second = await queue.get()
        assert first.stream_type is StreamType.RTT_RAW
        assert first.flags == RTT_RAW_UTF8_LINES
        assert [line.text for line in decode_rtt_lines(first.payload, first.item_count)] == [
            "alpha", "温度=25",
        ]
        assert [line.text for line in decode_rtt_lines(second.payload, second.item_count)] == [
            "last",
        ]
        assert all(line.timestamp_ns > 0 for line in decode_rtt_lines(first.payload, 2))
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_rtt_invalid_utf8_is_replaced_and_empty_final_tail_is_not_emitted():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        queue = hub.subscribe()
        manager = RttStreamManager(stream_hub=hub, raw_batch_lines=8)
        manager.feed_rtt_bytes(b"bad:\xff\n")
        manager.flush_pending(final=True)
        batch = await queue.get()
        assert [line.text for line in decode_rtt_lines(batch.payload, 1)] == ["bad:\ufffd"]
        assert hub.stats().produced_items == 1
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_rtt_parsed_numeric_rows_can_publish_waveform_batches():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        queue = hub.subscribe()
        manager = RttStreamManager(
            stream_hub=hub, raw_batch_lines=8, waveform_batch_samples=2,
        )
        manager.feed_rtt_bytes(b"a=1 b=2\na=3 b=4\n")
        raw = await queue.get()
        waveform = await queue.get()
        assert raw.stream_type is StreamType.RTT_RAW
        assert waveform.stream_type is StreamType.WAVEFORM
        assert decode_waveform_samples(waveform.payload, 2, 2) == ((1.0, 2.0), (3.0, 4.0))
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_rtt_auto_detects_csv_rows_before_publishing_waveform_batches():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        queue = hub.subscribe()
        manager = RttStreamManager(
            stream_hub=hub, raw_batch_lines=8, waveform_batch_samples=2,
        )
        manager.feed_rtt_bytes(b"1,2\n3,4\n")
        raw = await asyncio.wait_for(queue.get(), timeout=0.1)
        waveform = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert raw.stream_type is StreamType.RTT_RAW
        assert waveform.stream_type is StreamType.WAVEFORM
        assert decode_waveform_samples(waveform.payload, 2, 2) == (
            (1.0, 2.0), (3.0, 4.0),
        )
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_superwatch_sample_rows_are_aligned_and_metadata_is_versioned():
    async def scenario():
        hub = StreamHub(max_batches_per_client=8)
        queue = hub.subscribe()
        manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=2)
        manager._runtime = SimpleNamespace(items=[
            SimpleNamespace(name="a", type_name="float", size=4, address=0x20000000,
                            source="ram", enum_values=None, metadata={}),
            SimpleNamespace(name="b", type_name="uint32_t", size=4, address=0x20000004,
                            source="ram", enum_values=None, metadata={}),
        ])

        assert manager.publish_metadata() == 1
        assert manager.publish_sample_points([
            {"_t": 0.0, "a": 1.0}, {"_t": 0.0, "b": 2},
        ])
        assert manager.publish_sample_points([
            {"_t": 0.1, "a": 3.0}, {"_t": 0.1, "b": 4},
        ])

        metadata = await queue.get()
        samples = await queue.get()
        assert metadata.stream_type is StreamType.SUPERWATCH
        assert metadata.flags == SUPERWATCH_METADATA_JSON
        decoded_meta = decode_superwatch_metadata(metadata.payload)
        assert decoded_meta["version"] == 1
        assert [channel["name"] for channel in decoded_meta["channels"]] == ["a", "b"]
        assert samples.flags == SUPERWATCH_SAMPLE_MAJOR_FLOAT32
        assert decode_waveform_samples(samples.payload, 2, 2) == ((1.0, 2.0), (3.0, 4.0))
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_superwatch_rejects_partial_and_nonfinite_samples_atomically():
    hub = StreamHub(max_batches_per_client=2)
    manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=1)
    manager._runtime = SimpleNamespace(items=[
        SimpleNamespace(name="a"), SimpleNamespace(name="b"),
    ])
    assert not manager.publish_sample_points([{"_t": 0.0, "a": 1.0}])
    assert not manager.publish_sample_points([{"_t": 0.0, "a": 1.0, "b": float("inf")}])
    assert hub.stats().produced_batches == 0


def test_superwatch_republishes_current_metadata_for_late_subscribers():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=1)
        manager._runtime = SimpleNamespace(items=[
            SimpleNamespace(name="a", type_name="float", size=4, address=0x20000000,
                            source="ram", enum_values=None, metadata={}),
        ])
        assert manager.publish_metadata() == 1
        manager._last_metadata_publish_monotonic -= 2.0
        queue = hub.subscribe()
        assert manager.publish_sample_points([{"a": 1.0}])
        metadata = await queue.get()
        sample = await queue.get()
        assert metadata.flags == SUPERWATCH_METADATA_JSON
        assert decode_superwatch_metadata(metadata.payload)["version"] == 1
        assert sample.flags == SUPERWATCH_SAMPLE_MAJOR_FLOAT32
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_binary_queue_overflow_reports_explicit_rtt_drops_without_blocking_producer():
    async def scenario():
        hub = StreamHub(max_batches_per_client=1)
        queue = hub.subscribe()
        manager = RttStreamManager(stream_hub=hub, raw_batch_lines=1)
        for index in range(100):
            manager.feed_rtt_bytes(f"line-{index}\n".encode())
        await asyncio.sleep(0)
        stats = hub.stats()
        assert stats.produced_items == 100
        assert stats.dropped_batches == 99
        assert stats.dropped_items == 99
        assert queue.qsize() == 1
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_app_injects_and_shuts_down_rtt_and_superwatch_hubs(monkeypatch):
    from mklink.remote.api import create_app
    from mklink.remote.dashboards import get_managers

    app = create_app()
    managers = get_managers()
    assert managers["rtt"]._stream_hub is app.state.stream_registry["rtt"]
    assert managers["superwatch"]._stream_hub is app.state.stream_registry["superwatch"]

    stopped = []
    hubs = {}
    for name in ("rtt", "superwatch"):
        manager = managers[name]
        hub = app.state.stream_registry[name]
        hubs[name] = hub
        manager._running = True
        manager._stop_event.clear()
        def stop(name=name, manager=manager):
            stopped.append(name)
            manager._running = False
        monkeypatch.setattr(manager, "stop", stop)
    asyncio.run(app.router.shutdown())
    for name in ("rtt", "superwatch"):
        manager = managers[name]
        assert name in stopped
        assert manager._stream_hub is not hubs[name]
