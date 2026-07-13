import asyncio
import math
import struct
import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from mklink.remote.api import create_app
from mklink.remote.dashboards import VofaStreamManager
from mklink.remote.stream_hub import StreamHub
from mklink.vofa_viewer import (
    VOFA_SAMPLE_MAJOR_FLOAT32,
    build_vofa_read_groups,
    decode_vofa_samples,
    encode_vofa_samples,
    normalize_vofa_channels,
)


def _channels(count=3):
    return [
        {"name": f"ch{index}", "addr": 0x20000000 + index * 4,
         "type": "float", "size": 4}
        for index in range(count)
    ]


def test_sample_major_payload_preserves_10000_ids_and_channel_alignment():
    samples = [
        (float(sample_id), float(sample_id + 10000), float(-sample_id))
        for sample_id in range(10000)
    ]

    payload = encode_vofa_samples(samples)
    decoded = decode_vofa_samples(payload, channel_count=3)

    assert decoded == samples
    assert struct.unpack_from("<fff", payload, 4096 * 12) == samples[4096]


def test_contiguous_channels_share_one_safe_read_and_gaps_form_groups():
    channels = [
        {"name": "a", "addr": 0x20000000, "type": "uint16_t", "size": 2},
        {"name": "b", "addr": 0x20000002, "type": "uint16_t", "size": 2},
        {"name": "c", "addr": 0x20001000, "type": "float", "size": 4},
    ]

    groups = build_vofa_read_groups(channels, max_block_size=2048)

    assert [(group.address, group.size) for group in groups] == [
        (0x20000000, 4), (0x20001000, 4),
    ]
    assert [[read.channel_index for read in group.channels] for group in groups] == [
        [0, 1], [2],
    ]


def test_unaligned_narrow_channels_use_aligned_reads_and_adjusted_offsets():
    groups = build_vofa_read_groups([
        {"name": "a", "addr": 0x20000001, "type": "uint8_t", "size": 1},
        {"name": "b", "addr": 0x20000003, "type": "uint16_t", "size": 2},
    ])

    assert [(group.address, group.size) for group in groups] == [(0x20000000, 8)]
    assert [(read.offset, read.size) for read in groups[0].channels] == [(1, 1), (3, 2)]


@pytest.mark.parametrize("channels, message", [
    ([], "between 1 and 64"),
    ([{"name": f"c{i}", "addr": 0x20000000 + i * 4} for i in range(65)], "between 1 and 64"),
    ([{"name": "dup", "addr": 0x20000000}, {"name": "dup", "addr": 0x20000004}], "unique"),
    ([{"name": "bad", "addr": -1}], "32-bit"),
    ([{"name": "bad", "addr": 0xFFFFFFFF, "type": "uint16_t", "size": 2}], "32-bit"),
    ([{"name": "bad", "addr": 0x20000000, "type": "double", "size": 8}], "unsupported"),
    ([{"name": "bad", "addr": 0x20000000, "type": "uint16", "size": 4}], "size"),
])
def test_channel_validation_rejects_noncanonical_or_unsafe_snapshots(channels, message):
    with pytest.raises(ValueError, match=message):
        normalize_vofa_channels(channels)


def test_channel_validation_normalizes_documented_aliases_atomically():
    manager = VofaStreamManager()
    manager.configure([{"name": "old", "addr": 0x20000000, "type": "float", "size": 4}])
    manager.configure([
        {"name": "flag", "addr": "0x20000001", "type": "BOOLEAN", "size": 1},
        {"name": "count", "addr": 0x20000002, "type": "ushort", "size": 2},
    ])
    assert manager.get_status()["channels"] == [
        {"name": "flag", "addr": 0x20000001, "type": "bool", "size": 1},
        {"name": "count", "addr": 0x20000002, "type": "uint16_t", "size": 2},
    ]

    with pytest.raises(ValueError):
        manager.configure([{"name": "bad", "addr": 0x20000000, "type": "float", "size": 2}])
    assert [channel["name"] for channel in manager.get_status()["channels"]] == ["flag", "count"]


def test_cycle_reads_each_group_once_and_publishes_aligned_sample_with_flag():
    async def scenario():
        hub = StreamHub(max_batches_per_client=4)
        queue = hub.subscribe()
        manager = VofaStreamManager(stream_hub=hub, batch_samples=1)
        channels = [
            {"name": "id", "addr": 0x20000000, "type": "uint32_t", "size": 4},
            {"name": "value", "addr": 0x20000004, "type": "float", "size": 4},
            {"name": "far", "addr": 0x20001000, "type": "int16_t", "size": 2},
        ]

        class Device:
            def __init__(self):
                self.reads = []

            def read_memory(self, address, size):
                self.reads.append((address, size))
                if address == 0x20000000:
                    return struct.pack("<If", 7, 3.5)
                return struct.pack("<hxx", -9)

        device = Device()
        manager.configure(channels)
        assert manager.collect_cycle(device) is True
        await asyncio.sleep(0)
        batch = queue.get_nowait()
        queue.task_done()
        hub.unsubscribe(queue)

        assert device.reads == [(0x20000000, 8), (0x20001000, 4)]
        assert batch.flags == VOFA_SAMPLE_MAJOR_FLOAT32
        assert batch.item_count == 1
        assert decode_vofa_samples(batch.payload, 3) == [(7.0, 3.5, -9.0)]

    asyncio.run(scenario())


def test_failed_group_discards_whole_cycle_without_channel_misalignment():
    hub = StreamHub(max_batches_per_client=2)
    manager = VofaStreamManager(stream_hub=hub, batch_samples=1)
    manager.configure([
        {"name": "a", "addr": 0x20000000, "type": "float", "size": 4},
        {"name": "b", "addr": 0x20001000, "type": "float", "size": 4},
    ])

    class Device:
        def read_memory(self, address, size):
            if address == 0x20001000:
                raise OSError("target read failed")
            return struct.pack("<f", 1.0)

    assert manager.collect_cycle(Device()) is False
    assert hub.stats().produced_items == 0
    assert manager.get_status()["read_errors"] == 1


@pytest.mark.parametrize("returned_size", [3, 5])
def test_cycle_rejects_any_non_exact_aligned_memory_read(returned_size):
    manager = VofaStreamManager(batch_samples=1)
    manager.configure([{"name": "a", "addr": 0x20000001, "type": "uint8_t", "size": 1}])

    class Device:
        def read_memory(self, address, size):
            assert (address, size) == (0x20000000, 4)
            return bytes(returned_size)

    assert manager.collect_cycle(Device()) is False
    assert manager.get_status()["completed_samples"] == 0
    assert manager.get_status()["read_errors"] == 1


def test_non_finite_device_values_are_sanitized_before_sse_history_and_binary():
    manager = VofaStreamManager(batch_samples=1)
    manager.configure(_channels(1))

    class Device:
        def read_memory(self, address, size):
            return struct.pack("<f", math.nan)

    assert manager.collect_cycle(Device()) is True
    assert manager._history[-1]["ch0"] == 0.0
    assert manager._pending_samples == []


def test_rate_uses_completed_reads_over_elapsed_not_requested_interval():
    now = [100.0]

    class Device:
        def read_memory(self, address, size):
            now[0] += 0.1
            return struct.pack("<f", now[0])

    manager = VofaStreamManager(clock=lambda: now[0], batch_samples=8)
    manager.configure(_channels(1), interval=0.000001)
    for _ in range(5):
        assert manager.collect_cycle(Device()) is True

    status = manager.get_status()
    assert status["completed_samples"] == 5
    assert status["completed_reads"] == 5
    assert status["actual_rate"] == 10.0
    assert status["interval"] == 0.000001


def test_rate_window_resets_across_a_long_pause_and_recovers_to_active_rate():
    now = [0.0]

    class Device:
        def read_memory(self, address, size):
            now[0] += 0.1
            return struct.pack("<f", now[0])

    manager = VofaStreamManager(clock=lambda: now[0], batch_samples=32)
    manager.configure(_channels(1))
    for _ in range(5):
        assert manager.collect_cycle(Device()) is True
    assert manager.get_status()["actual_rate"] == pytest.approx(10.0)

    manager.pause()
    now[0] += 100.0
    assert manager.get_status()["actual_rate"] == 0.0
    manager.resume()
    for _ in range(5):
        assert manager.collect_cycle(Device()) is True
    assert manager.get_status()["actual_rate"] == pytest.approx(10.0)


def test_invalid_api_configuration_is_rejected_before_leasing_or_starting():
    from mklink.remote.dashboards import get_managers

    app = create_app(auth_token=None, project_root=".")
    app.state.mklink_state["device"] = type("Device", (), {"connected": True})()
    manager = get_managers()["vofa"]
    manager.stop()
    with patch.object(manager, "start") as start, TestClient(app) as client:
        response = client.post("/api/dash/vofa/start", json={
            "channels": [{"name": "bad", "addr": 0x20000000, "type": "uint16", "size": 4}],
            "interval": 0.1,
        })

        assert response.status_code == 422
        start.assert_not_called()
        assert app.state.mklink_state["resource_manager"].get_status() == {}


@pytest.mark.parametrize("interval", [math.nan, math.inf, -math.inf, -1.0, 60.000001])
def test_manager_rejects_invalid_interval_atomically(interval):
    manager = VofaStreamManager()
    manager.configure(_channels(1), interval=0.25)
    before = manager.get_status()

    with pytest.raises(ValueError, match="interval"):
        manager.configure(_channels(2), interval=interval)
    with pytest.raises(ValueError, match="interval"):
        manager.set_interval(interval)

    after = manager.get_status()
    assert after["interval"] == before["interval"]
    assert after["channels"] == before["channels"]


def test_manager_normalizes_zero_interval_to_fastest_supported_value():
    manager = VofaStreamManager()

    manager.configure(_channels(1), interval=0)
    assert manager.get_status()["interval"] == pytest.approx(0.000001)
    assert manager.set_interval(0) == pytest.approx(0.000001)
    assert manager.get_status()["interval"] == pytest.approx(0.000001)


@pytest.mark.parametrize("raw_interval", ["NaN", "Infinity", "-Infinity", "-1", "60.000001"])
def test_interval_api_rejects_raw_invalid_numbers_before_lease_or_thread(raw_interval):
    from mklink.remote.dashboards import get_managers

    app = create_app(auth_token=None, project_root=".")
    app.state.mklink_state["device"] = type("Device", (), {"connected": True})()
    manager = get_managers()["vofa"]
    manager.stop()
    manager.configure(_channels(1), interval=0.25)
    before = manager.get_status()
    channels_json = '[{"name":"c0","addr":536870912,"type":"float","size":4}]'

    with patch.object(manager, "start") as start, TestClient(app) as client:
        start_response = client.post(
            "/api/dash/vofa/start",
            content=f'{{"channels":{channels_json},"interval":{raw_interval}}}',
            headers={"Content-Type": "application/json"},
        )
        interval_response = client.post(
            "/api/dash/vofa/interval",
            content=f'{{"interval":{raw_interval}}}',
            headers={"Content-Type": "application/json"},
        )

        assert start_response.status_code == 422
        assert interval_response.status_code == 422
        start.assert_not_called()
        assert app.state.mklink_state["resource_manager"].get_status() == {}
        after = manager.get_status()
        assert after["interval"] == before["interval"]
        assert after["channels"] == before["channels"]


def test_zero_interval_api_normalizes_before_start_and_reports_current_interval():
    from mklink.remote.dashboards import get_managers, normalize_vofa_interval

    app = create_app(auth_token=None, project_root=".")
    app.state.mklink_state["device"] = type("Device", (), {"connected": True})()
    manager = get_managers()["vofa"]
    manager.stop()
    manager.configure(_channels(1), interval=0.25)
    resource_manager = app.state.mklink_state["resource_manager"]
    acquire_many = resource_manager.acquire_many
    events = []

    def record_normalize(interval):
        events.append("normalize")
        return normalize_vofa_interval(interval)

    def record_acquire(*args, **kwargs):
        events.append("lease")
        return acquire_many(*args, **kwargs)

    with (
        patch.object(manager, "start") as start,
        patch(
            "mklink.remote.dashboards.normalize_vofa_interval",
            side_effect=record_normalize,
        ),
        patch.object(resource_manager, "acquire_many", side_effect=record_acquire),
        TestClient(app) as client,
    ):
        start_response = client.post("/api/dash/vofa/start", json={
            "channels": _channels(1), "interval": 0,
        })
        assert start_response.status_code == 200
        assert events[:2] == ["normalize", "lease"]
        start.assert_called_once()
        assert start.call_args.args[2] == pytest.approx(0.000001)

        interval_response = client.post(
            "/api/dash/vofa/interval", json={"interval": 0},
        )
        assert interval_response.status_code == 200
        assert interval_response.json()["interval"] == pytest.approx(0.000001)
        status_response = client.get("/api/dash/vofa/status")
        assert status_response.status_code == 200
        assert status_response.json()["interval"] == pytest.approx(0.000001)


def test_paused_60_second_interval_stop_is_interruptible():
    manager = VofaStreamManager(batch_samples=1)

    class Device:
        def read_memory(self, address, size):
            return bytes(size)

    real_sleep = time.sleep
    blocked_sleep = threading.Event()

    def legacy_sleep(seconds):
        if seconds >= 60:
            blocked_sleep.wait(1.0)
        else:
            real_sleep(seconds)

    error = None
    with patch("mklink.remote.dashboards.time.sleep", side_effect=legacy_sleep):
        manager.start(Device(), _channels(1), interval=0.001)
        deadline = time.perf_counter() + 1.0
        while manager.get_status()["completed_samples"] < 2 and time.perf_counter() < deadline:
            real_sleep(0.001)
        manager.pause()
        manager.set_interval(60.0)
        real_sleep(0.02)
        started = time.perf_counter()
        try:
            manager.stop(timeout=0.1)
        except Exception as exc:  # captured so the legacy sleeper can be released and joined
            error = exc
        elapsed = time.perf_counter() - started
        blocked_sleep.set()
        if manager._thread is not None and manager._thread.is_alive():
            manager.stop(timeout=1.0)

    assert error is None
    assert elapsed < 0.2
    assert manager._thread is None


def test_paused_stop_endpoint_releases_lease_without_waiting_for_long_interval():
    from mklink.remote.dashboards import get_managers

    class Device:
        connected = True

        def read_memory(self, address, size):
            return bytes(size)

    app = create_app(auth_token=None, project_root=".")
    app.state.mklink_state["device"] = Device()
    manager = get_managers()["vofa"]
    manager.stop()
    real_sleep = time.sleep
    blocked_sleep = threading.Event()

    def legacy_sleep(seconds):
        if seconds >= 60:
            blocked_sleep.wait(1.0)
        else:
            real_sleep(seconds)

    try:
        with patch("mklink.remote.dashboards.time.sleep", side_effect=legacy_sleep), TestClient(app) as client:
            start = client.post("/api/dash/vofa/start", json={
                "channels": _channels(1), "interval": 0.001,
            })
            assert start.status_code == 200
            deadline = time.perf_counter() + 1.0
            while manager.get_status()["completed_samples"] < 2 and time.perf_counter() < deadline:
                real_sleep(0.001)
            assert client.post("/api/dash/vofa/pause").status_code == 200
            assert client.post("/api/dash/vofa/interval", json={"interval": 60.0}).status_code == 200
            real_sleep(0.02)

            started = time.perf_counter()
            stopped = client.post("/api/dash/vofa/stop")
            elapsed = time.perf_counter() - started
            assert stopped.status_code == 200
            assert elapsed < 0.2
            assert app.state.mklink_state["resource_manager"].get_status() == {}
    finally:
        blocked_sleep.set()
        if manager._thread is not None and manager._thread.is_alive():
            manager.stop(timeout=1.0)


def test_slow_subscriber_reports_only_explicit_hub_drops_for_id_batches():
    async def scenario():
        hub = StreamHub(max_batches_per_client=1)
        queue = hub.subscribe()
        manager = VofaStreamManager(stream_hub=hub, batch_samples=100)
        manager.configure(_channels(2))
        for start in range(0, 10000, 100):
            manager.publish_samples([
                (float(sample_id), float(sample_id + 10000))
                for sample_id in range(start, start + 100)
            ])
        await asyncio.sleep(0)

        latest = queue.get_nowait()
        queue.task_done()
        stats = hub.stats()
        hub.unsubscribe(queue)

        assert stats.produced_items == 10000
        assert stats.dropped_items == 9900
        assert decode_vofa_samples(latest.payload, 2) == [
            (float(sample_id), float(sample_id + 10000))
            for sample_id in range(9900, 10000)
        ]

    asyncio.run(scenario())


def test_stream_hub_can_be_replaced_and_detached_for_app_lifecycle():
    first = StreamHub(max_batches_per_client=2)
    second = StreamHub(max_batches_per_client=2)
    manager = VofaStreamManager(stream_hub=first, batch_samples=1)
    manager.configure(_channels(1))

    manager.set_stream_hub(second)
    manager.publish_samples([(1.0,)])
    manager.set_stream_hub(None)
    manager.publish_samples([(2.0,)])

    assert first.stats().produced_items == 0
    assert second.stats().produced_items == 1


def test_app_registry_injects_vofa_hub_and_shutdown_detaches_it():
    from mklink.remote.dashboards import get_managers

    app = create_app(auth_token=None, project_root=".")
    manager = get_managers()["vofa"]
    assert manager._stream_hub is app.state.stream_registry["vofa"]

    with TestClient(app):
        assert manager._stream_hub is app.state.stream_registry["vofa"]

    assert manager._stream_hub is None


def test_app_shutdown_stops_its_active_vofa_producer():
    from mklink.remote.dashboards import get_managers

    app = create_app(auth_token=None, project_root=".")
    manager = get_managers()["vofa"]

    class Device:
        def read_memory(self, address, size):
            return struct.pack("<f", 1.0)

    manager.start(Device(), _channels(1), interval=0.001)
    try:
        with TestClient(app):
            assert manager.running
        assert not manager.running
        assert manager._stream_hub is None
    finally:
        if manager.running:
            manager.stop()
