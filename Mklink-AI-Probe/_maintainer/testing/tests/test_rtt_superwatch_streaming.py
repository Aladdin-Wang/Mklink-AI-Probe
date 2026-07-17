import asyncio
import binascii
import struct
import threading
import time
from types import SimpleNamespace

import pytest

from mklink.remote.dashboards import RttStreamManager, SuperWatchStreamManager
from mklink.dump_memory import MAGIC
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


def test_rtt_default_batches_keep_12khz_dual_stream_below_100_frames_per_second():
    hub = _RecordingHub()
    manager = RttStreamManager(stream_hub=hub)

    manager.feed_rtt_bytes(b"1,2,3,4\n" * 12_000)
    manager.flush_pending()

    batches = hub.snapshot()
    raw = [batch for batch in batches if batch.stream_type is StreamType.RTT_RAW]
    waveform = [batch for batch in batches if batch.stream_type is StreamType.WAVEFORM]
    assert sum(batch.item_count for batch in raw) == 12_000
    assert sum(batch.item_count for batch in waveform) == 12_000
    assert len(raw) + len(waveform) <= 100


def test_rtt_marker_lines_do_not_reset_stable_csv_waveform_layout():
    hub = _RecordingHub()
    manager = RttStreamManager(
        stream_hub=hub, raw_batch_lines=256, waveform_batch_samples=256,
    )

    for index in range(3):
        manager.feed_rtt_bytes(b"1,2,3,4\n" * 120)
        manager.feed_rtt_bytes(f"M,{index},{index},0\n".encode())
    manager.flush_pending()

    batches = hub.snapshot()
    raw = [batch for batch in batches if batch.stream_type is StreamType.RTT_RAW]
    waveform = [batch for batch in batches if batch.stream_type is StreamType.WAVEFORM]
    assert sum(batch.item_count for batch in raw) == 363
    assert sum(batch.item_count for batch in waveform) == 360
    assert manager.get_status()["numeric_channels"] == ["v0", "v1", "v2", "v3"]


def test_rtt_ignores_a_partial_initial_channel_name_before_locking_layout():
    hub = _RecordingHub()
    manager = RttStreamManager(stream_hub=hub)

    manager.feed_rtt_bytes(
        b"peed=90\ntemp=25,speed=100\ntemp=26,speed=101\n"
    )
    manager.flush_pending()

    waveform = [
        batch for batch in hub.snapshot()
        if batch.stream_type is StreamType.WAVEFORM
    ]
    assert manager.get_status()["numeric_channels"] == ["speed", "temp"]
    assert len(waveform) == 1
    assert decode_waveform_samples(waveform[0].payload, 2, 2) == (
        (100.0, 25.0), (101.0, 26.0),
    )


def test_rtt_default_marker_mix_stays_near_100fps_and_keeps_30hz_waveform():
    hub = _RecordingHub()
    manager = RttStreamManager(stream_hub=hub)

    for index in range(100):
        manager.feed_rtt_bytes(b"1,2,3,4\n" * 110)
        manager.feed_rtt_bytes(f"M,{index},{index},0\n".encode())
    manager.flush_pending()

    batches = hub.snapshot()
    raw = [batch for batch in batches if batch.stream_type is StreamType.RTT_RAW]
    waveform = [batch for batch in batches if batch.stream_type is StreamType.WAVEFORM]
    assert sum(batch.item_count for batch in raw) == 11_100
    assert sum(batch.item_count for batch in waveform) == 11_000
    assert len(waveform) >= 30
    assert len(raw) + len(waveform) <= 100


def test_rtt_manager_stop_closes_the_device_stream_session():
    read_started = threading.Event()

    class Device:
        def __init__(self):
            self.stop_calls = 0

        def rtt_start(self, *_args, **_kwargs):
            pass

        def rtt_read(self, **_kwargs):
            read_started.set()
            time.sleep(0.002)
            return b""

        def rtt_stop(self):
            self.stop_calls += 1

    device = Device()
    manager = RttStreamManager()
    manager.start(device)
    assert read_started.wait(timeout=1.0)

    manager.stop()

    assert device.stop_calls == 1


def test_rtt_manager_stops_and_reports_device_error_state():
    from mklink._types import DeviceState

    read_started = threading.Event()

    class Device:
        def __init__(self):
            self.state = DeviceState.READY

        def rtt_start(self, *_args, **_kwargs):
            pass

        def rtt_read(self, **_kwargs):
            self.state = DeviceState.ERROR
            read_started.set()
            return b""

        def rtt_stop(self):
            pass

    manager = RttStreamManager()
    manager.start(Device())
    try:
        assert read_started.wait(timeout=1.0)
        deadline = time.monotonic() + 1.0
        while manager.running and time.monotonic() < deadline:
            time.sleep(0.01)

        status = manager.get_status()
        assert status["running"] is False
        assert "ERROR" in status["error"]
    finally:
        manager.stop()


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

        assert manager.publish_metadata() == 2
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
        assert decoded_meta["version"] == 2
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


def test_superwatch_subscribe_replays_cached_metadata_without_waiting_for_read(monkeypatch):
    async def scenario():
        hub = StreamHub(max_batches_per_client=16)
        manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=1)
        manager._runtime = _MutableWatchRuntime()
        manager.publish_metadata()
        sample_started = threading.Event()

        def sample_blocks(blocks, **_kwargs):
            assert tuple(blocks) == ("a",)
            sample_started.set()
            time.sleep(0.2)
            return SimpleNamespace(origin_us=1, points=[{"a": 1.0}])

        monkeypatch.setattr("mklink.superwatch.sample_blocks", sample_blocks)
        manager.set_interval(1.0)
        manager.start(SimpleNamespace(_bridge=object()))
        try:
            assert await asyncio.to_thread(sample_started.wait, 1.0)
            loop = asyncio.get_running_loop()
            heartbeat_start = loop.time()
            heartbeat = asyncio.create_task(asyncio.sleep(0.01))
            subscribe_start = loop.time()
            queue = hub.subscribe()
            subscribe_elapsed = loop.time() - subscribe_start
            await heartbeat
            heartbeat_elapsed = loop.time() - heartbeat_start
            metadata = await asyncio.wait_for(queue.get(), timeout=0.05)
            assert metadata.flags == SUPERWATCH_METADATA_JSON
            assert decode_superwatch_metadata(metadata.payload)["channels"][0]["name"] == "a"
            hub.unsubscribe(queue)
        finally:
            await asyncio.to_thread(manager.stop)

        assert subscribe_elapsed < 0.05
        assert heartbeat_elapsed < 0.05

    asyncio.run(scenario())


def test_superwatch_layout_change_does_not_wait_for_read_and_discards_stale_cycle(monkeypatch):
    hub = _RecordingHub()
    manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=1)
    runtime = _MutableWatchRuntime()
    manager._runtime = runtime
    manager.publish_metadata()
    sample_started = threading.Event()
    release_sample = threading.Event()
    sample_finished = threading.Event()
    add_finished = threading.Event()

    def sample_blocks(blocks, **_kwargs):
        assert tuple(blocks) == ("a",)
        sample_started.set()
        assert release_sample.wait(1.0)
        sample_finished.set()
        return SimpleNamespace(origin_us=1, points=[{"a": 1.0}])

    monkeypatch.setattr("mklink.superwatch.sample_blocks", sample_blocks)
    device = SimpleNamespace(_bridge=object())
    manager.set_interval(1.0)
    manager.start(device)
    assert sample_started.wait(1.0)

    add_thread = threading.Thread(
        target=lambda: (manager.add_watch("b"), add_finished.set()), daemon=True,
    )
    add_thread.start()
    add_completed_without_read = add_finished.wait(0.05)
    release_sample.set()
    assert add_finished.wait(1.0)
    assert sample_finished.wait(1.0)
    manager.stop()
    add_thread.join(timeout=1.0)
    assert not add_thread.is_alive()
    assert add_completed_without_read
    assert not any(
        batch.flags == SUPERWATCH_SAMPLE_MAJOR_FLOAT32
        for batch in hub.snapshot()
    )
    status = manager.get_status()
    assert status["read_cycles"] == 0
    assert status["read_drops"] == 1


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
        deadline = time.monotonic() + 1.0
        while manager.get_status()["read_cycles"] < 1 and time.monotonic() < deadline:
            time.sleep(0.001)
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
    assert manager.get_status()["read_drops"] > 0
    assert manager.get_status()["binary_drops"] == {"batches": 0, "items": 0}


def test_superwatch_republishes_current_metadata_for_late_subscribers():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=1)
        manager._runtime = SimpleNamespace(items=[
            SimpleNamespace(name="a", type_name="float", size=4, address=0x20000000,
                            source="ram", enum_values=None, metadata={}),
        ])
        assert manager.publish_metadata() == 2
        queue = hub.subscribe()
        metadata = await asyncio.wait_for(queue.get(), timeout=0.1)
        assert manager.publish_sample_points([{"a": 1.0}])
        sample = await queue.get()
        assert metadata.flags == SUPERWATCH_METADATA_JSON
        assert decode_superwatch_metadata(metadata.payload)["version"] == 2
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
def _dump_frame(timestamp_us, payload):
    region = b"\x00" + struct.pack("<H", len(payload)) + payload
    length = 19 + len(region) + 6
    body = MAGIC + struct.pack("<QHB", timestamp_us, length, 1) + region + b"\x00\x00"
    return body + struct.pack("<I", binascii.crc32(body) & 0xFFFFFFFF)


def test_superwatch_uses_dump_stream_and_reports_protocol_integrity():
    item = SimpleNamespace(
        name="value", type_name="float", size=4, address=0x20000000,
        source="ram", enum_values=None, metadata={},
    )
    block = SimpleNamespace(address=0x20000000, size=4, items=[item])
    runtime = SimpleNamespace(items=[item], blocks=[block])

    class Bridge:
        def __init__(self):
            self.chunks = [b"text" + _dump_frame(10, struct.pack("<f", 4.5))]
            self.writes = []

        def _enter_stream(self, state):
            self.state = state

        def _write_raw(self, data):
            self.writes.append(data)

        def drain_stream_bytes(self, max_bytes=None):
            return self.chunks.pop(0) if self.chunks else b""

        def _exit_stream(self):
            return ""

    hub = StreamHub(max_batches_per_client=4)
    manager = SuperWatchStreamManager(stream_hub=hub, batch_samples=1)
    manager._runtime = runtime
    bridge = Bridge()
    manager.start(SimpleNamespace(_bridge=bridge))
    deadline = time.perf_counter() + 1.0
    while manager.get_status()["read_cycles"] < 1 and time.perf_counter() < deadline:
        time.sleep(0.001)
    manager.set_interval(0.001)
    restart_deadline = time.perf_counter() + 1.0
    expected_restart = b"cmd.dump_memory(0x20000000, 4, 0.001)\n"
    while expected_restart not in bridge.writes and time.perf_counter() < restart_deadline:
        time.sleep(0.001)
    manager.stop()

    status = manager.get_status()
    assert status["acquisition_mode"] == "dump-memory"
    assert status["read_cycles"] == 1
    assert status["stream_integrity"]["parser_dropped_bytes"] == 4
    assert status["stream_integrity"]["parser_crc_errors"] == 0
    assert hub.stats().produced_items == 1
    assert bridge.writes[0] == b"cmd.dump_memory(0x20000000, 4, 0.1)\n"
    assert expected_restart in bridge.writes
    assert bridge.writes[-1] == b"cmd.dump_memory(0x20000000, 4, 0)\n"


def _symbol_write_device(tmp_path, *, write_error=None):
    from mklink.dwarf_parser import DwarfInfo, DwarfVariable
    from mklink.symbol_catalog import SymbolCatalog

    axf = tmp_path / "app.axf"
    axf.write_bytes(b"axf")
    info = DwarfInfo(
        base_types={1: ("float", 4)},
        variables={
            "gain": DwarfVariable("gain", 10, 1, 0x20000020, 4, "float"),
        },
    )
    catalog = SymbolCatalog.from_dwarf(
        info, axf_path=str(axf), ram_ranges=[(0x20000000, 0x20010000)]
    )
    operations = []

    def write_memory(address, data):
        operations.append(("write", address, data))
        if write_error:
            raise write_error

    device = SimpleNamespace(
        symbol_catalog=catalog,
        write_memory=write_memory,
    )
    return device, operations


def test_superwatch_write_stops_dump_writes_reads_back_and_restores_running(tmp_path, monkeypatch):
    manager = SuperWatchStreamManager()
    manager._runtime = _MutableWatchRuntime()
    device, operations = _symbol_write_device(tmp_path)
    manager._device = device
    manager._running = True
    manager._stop_event.clear()
    manager._collecting.set()

    def stop():
        operations.append("stop")
        manager._running = False
        manager._collecting.clear()

    def start(_device):
        operations.append("start")
        manager._running = True
        manager._collecting.set()

    monkeypatch.setattr(manager, "stop", stop)
    monkeypatch.setattr(manager, "start", start)
    monkeypatch.setattr(
        manager,
        "_readback_once",
        lambda address, size: operations.append(("readback", address, size)) or struct.pack("<f", 1.5),
        raising=False,
    )

    result = manager.write_symbol("gain", generation=1, value=1.5)

    assert operations == [
        "stop",
        ("write", 0x20000020, struct.pack("<f", 1.5)),
        ("readback", 0x20000020, 4),
        "start",
    ]
    assert result["verified"] is True
    assert result["value"] == pytest.approx(1.5)
    assert manager.get_status()["state"] == "running"


def test_superwatch_write_failure_restores_paused_state(tmp_path, monkeypatch):
    manager = SuperWatchStreamManager()
    manager._runtime = _MutableWatchRuntime()
    device, operations = _symbol_write_device(tmp_path, write_error=RuntimeError("flush failed"))
    manager._device = device
    manager._running = True
    manager._stop_event.clear()
    manager._collecting.clear()

    def stop():
        operations.append("stop")
        manager._running = False

    def start(_device):
        operations.append("start")
        manager._running = True
        manager._collecting.set()

    def pause():
        operations.append("pause")
        manager._collecting.clear()

    monkeypatch.setattr(manager, "stop", stop)
    monkeypatch.setattr(manager, "start", start)
    monkeypatch.setattr(manager, "pause", pause)

    with pytest.raises(RuntimeError, match="flush failed"):
        manager.write_symbol("gain", generation=1, value=2.0)

    assert operations == [
        "stop",
        ("write", 0x20000020, struct.pack("<f", 2.0)),
        "start",
        "pause",
    ]
    assert manager.get_status()["state"] == "paused"


def test_superwatch_reparse_rebinds_selected_names_and_restores_running(tmp_path, monkeypatch):
    from mklink.dwarf_parser import DwarfInfo, DwarfVariable
    from mklink.superwatch import SuperWatchRuntime, WatchItem
    from mklink.symbol_catalog import SymbolCatalog

    first_axf = tmp_path / "first.axf"
    second_axf = tmp_path / "second.axf"
    first_axf.write_bytes(b"first")
    second_axf.write_bytes(b"second")
    old_info = DwarfInfo(
        base_types={1: ("float", 4)},
        variables={"gain": DwarfVariable("gain", 10, 1, 0x20000020, 4, "float")},
    )
    new_info = DwarfInfo(
        base_types={1: ("float", 4)},
        variables={"gain": DwarfVariable("gain", 10, 1, 0x20000040, 4, "float")},
    )
    old_catalog = SymbolCatalog.from_dwarf(
        old_info, axf_path=str(first_axf), generation=1, ram_ranges=[(0x20000000, 0x20010000)]
    )
    new_catalog = SymbolCatalog.from_dwarf(
        new_info, axf_path=str(second_axf), generation=2, ram_ranges=[(0x20000000, 0x20010000)]
    )
    operations = []
    device = SimpleNamespace(
        symbol_catalog=old_catalog,
        _dwarf_info=old_info,
        _project_root=".",
        _port=None,
    )

    def reparse_axf_atomically():
        operations.append("reparse")
        device.symbol_catalog = new_catalog
        device._dwarf_info = new_info
        return new_catalog

    device.reparse_axf_atomically = reparse_axf_atomically
    manager = SuperWatchStreamManager()
    manager._device = device
    manager._runtime = SuperWatchRuntime(
        items=[WatchItem("gain", 0x20000020, "float", 4)],
        dwarf_info=old_info,
    )
    manager._running = True
    manager._stop_event.clear()
    manager._collecting.set()

    def stop():
        operations.append("stop")
        manager._running = False
        manager._collecting.clear()

    def start(_device):
        operations.append("start")
        manager._running = True
        manager._collecting.set()

    monkeypatch.setattr(manager, "stop", stop)
    monkeypatch.setattr(manager, "start", start)

    result = manager.reparse_symbols()

    assert operations == ["stop", "reparse", "start"]
    assert result == {"preserved": [], "updated": ["gain"], "removed": []}
    assert manager._runtime.items[0].name == "gain"
    assert manager._runtime.items[0].address == 0x20000040
    assert manager.get_status()["state"] == "running"
