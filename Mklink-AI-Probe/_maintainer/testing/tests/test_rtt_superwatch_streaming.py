import asyncio
import threading
import time
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


def _watch_item(name, address):
    return SimpleNamespace(
        name=name, type_name="float", size=4, address=address,
        source="ram", enum_values=None, metadata={},
    )


class _MutableWatchRuntime:
    def __init__(self):
        self.items = [_watch_item("a", 0x20000000)]
        self.blocks = ["a"]

    def add(self, name):
        if name == "b" and all(item.name != name for item in self.items):
            self.items.append(_watch_item("b", 0x20000004))
        self.blocks = [item.name for item in self.items]
        return {"name": name}

    def remove(self, name):
        self.items = [item for item in self.items if item.name != name]
        self.blocks = [item.name for item in self.items]
        return {"removed": True, "name": name}


class _RecordingHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._sequence = 0
        self.batches = []
        self.callback = None

    def set_subscribe_callback(self, callback):
        self.callback = callback

    def publish(self, payload, *, item_count, flags=0, stream_type=None):
        with self._lock:
            self._sequence += 1
            self.batches.append(SimpleNamespace(
                payload=bytes(payload), item_count=item_count, flags=flags,
                stream_type=stream_type, sequence=self._sequence,
            ))
            return self._sequence

    def snapshot(self):
        with self._lock:
            return list(self.batches)

    def stats(self):
        return SimpleNamespace()


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


def test_rtt_raw_records_preserve_whitespace_and_empty_line_boundaries():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        queue = hub.subscribe()
        manager = RttStreamManager(stream_hub=hub, raw_batch_lines=8)
        manager.feed_rtt_bytes(b"  padded  \r\n\n")
        manager.flush_pending(final=True)
        batch = await queue.get()
        assert [line.text for line in decode_rtt_lines(batch.payload, 2)] == [
            "  padded  ", "",
        ]
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_rtt_poll_preserves_whitespace_only_device_chunks():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        queue = hub.subscribe()
        manager = RttStreamManager(stream_hub=hub, raw_batch_lines=8)
        read_once = threading.Event()

        class Device:
            def rtt_start(self, *_args, **_kwargs):
                pass

            def rtt_read(self, **_kwargs):
                if not read_once.is_set():
                    read_once.set()
                    return b"  \n\n"
                time.sleep(0.001)
                return b""

        manager.start(Device())
        assert await asyncio.to_thread(read_once.wait, 1.0)
        await asyncio.to_thread(manager.stop)
        batch = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert [line.text for line in decode_rtt_lines(batch.payload, 2)] == ["  ", ""]
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


def test_superwatch_layout_changes_flush_old_samples_before_metadata_atomically():
    async def scenario():
        hub = StreamHub(max_batches_per_client=16)
        manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=8)
        manager._runtime = _MutableWatchRuntime()
        manager.publish_metadata()
        queue = hub.subscribe()
        initial = await queue.get()
        assert [channel["name"] for channel in decode_superwatch_metadata(initial.payload)["channels"]] == ["a"]

        assert manager.publish_sample_points([{"a": 1.0}])
        manager.add_watch("b")
        old_sample = await asyncio.wait_for(queue.get(), timeout=0.1)
        added_metadata = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert old_sample.flags == SUPERWATCH_SAMPLE_MAJOR_FLOAT32
        assert decode_waveform_samples(old_sample.payload, 1, 1) == ((1.0,),)
        assert [channel["name"] for channel in decode_superwatch_metadata(added_metadata.payload)["channels"]] == ["a", "b"]

        assert manager.publish_sample_points([{"a": 2.0, "b": 3.0}])
        manager.remove_watch("b")
        two_channel_sample = await asyncio.wait_for(queue.get(), timeout=0.1)
        removed_metadata = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert decode_waveform_samples(two_channel_sample.payload, 1, 2) == ((2.0, 3.0),)
        assert [channel["name"] for channel in decode_superwatch_metadata(removed_metadata.payload)["channels"]] == ["a"]
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_superwatch_layout_change_reports_pending_samples_dropped_without_hub():
    manager = SuperWatchStreamManager(batch_samples=8)
    manager._runtime = _MutableWatchRuntime()
    assert manager.publish_sample_points([{"a": 1.0}])
    manager.add_watch("b")
    assert manager.get_status()["binary_drops"] == {"batches": 1, "items": 1}
    assert manager._pending_samples == []


def test_superwatch_stop_flushes_a_partial_batch():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=8)
        manager._runtime = _MutableWatchRuntime()
        manager.publish_metadata()
        queue = hub.subscribe()
        await queue.get()
        assert manager.publish_sample_points([{"a": 7.0}])
        manager.stop()
        sample = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert decode_waveform_samples(sample.payload, 1, 1) == ((7.0,),)
        hub.unsubscribe(queue)

    asyncio.run(scenario())


def test_superwatch_poll_and_add_share_one_layout_lock(monkeypatch):
    hub = StreamHub(max_batches_per_client=16)
    manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=1)
    runtime = _MutableWatchRuntime()
    manager._runtime = runtime
    sample_started = threading.Event()
    release_sample = threading.Event()
    add_finished = threading.Event()

    def sample_blocks(blocks, **_kwargs):
        assert blocks == ["a"]
        sample_started.set()
        assert release_sample.wait(1.0)
        return SimpleNamespace(origin_us=1, points=[{"a": 1.0}])

    monkeypatch.setattr("mklink.superwatch.sample_blocks", sample_blocks)
    device = SimpleNamespace(_bridge=object())
    manager.start(device)
    assert sample_started.wait(1.0)

    add_thread = threading.Thread(
        target=lambda: (manager.add_watch("b"), add_finished.set()), daemon=True,
    )
    add_thread.start()
    add_was_blocked = not add_finished.wait(0.05)
    release_sample.set()
    assert add_finished.wait(1.0)
    add_thread.join(timeout=1.0)
    manager.stop()
    assert not add_thread.is_alive()
    assert add_was_blocked


def test_superwatch_concurrent_poll_add_remove_pressure_keeps_batches_aligned(monkeypatch):
    hub = _RecordingHub()
    manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=8)
    manager._runtime = _MutableWatchRuntime()
    manager.publish_metadata()
    sampled = 0

    def sample_blocks(blocks, **_kwargs):
        nonlocal sampled
        sampled += 1
        time.sleep(0.0002)
        point = {name: float(sampled + index) for index, name in enumerate(blocks)}
        return SimpleNamespace(origin_us=sampled, points=[point])

    monkeypatch.setattr("mklink.superwatch.sample_blocks", sample_blocks)
    manager.set_interval(0.0)
    manager.start(SimpleNamespace(_bridge=object()))
    try:
        for _ in range(100):
            manager.add_watch("b")
            manager.remove_watch("b")
    finally:
        manager.stop()

    active_channel_count = None
    sample_channel_counts = set()
    for batch in hub.snapshot():
        if batch.flags == SUPERWATCH_METADATA_JSON:
            active_channel_count = len(decode_superwatch_metadata(batch.payload)["channels"])
        elif batch.flags == SUPERWATCH_SAMPLE_MAJOR_FLOAT32:
            assert active_channel_count in (1, 2)
            decode_waveform_samples(batch.payload, batch.item_count, active_channel_count)
            sample_channel_counts.add(active_channel_count)
    assert sampled > 0
    assert sample_channel_counts
    assert manager.get_status()["binary_drops"] == {"batches": 0, "items": 0}


def test_superwatch_republishes_current_metadata_for_late_subscribers():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=1)
        manager._runtime = SimpleNamespace(items=[
            SimpleNamespace(name="a", type_name="float", size=4, address=0x20000000,
                            source="ram", enum_values=None, metadata={}),
        ])
        assert manager.publish_metadata() == 1
        queue = hub.subscribe()
        metadata = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert manager.publish_sample_points([{"a": 1.0}])
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
