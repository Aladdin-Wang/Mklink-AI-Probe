import asyncio
import struct

import pytest

from mklink.remote.dashboards import SystemViewStreamManager
from mklink.remote.stream_hub import StreamHub
from mklink.remote.stream_protocol import (
    SYSTEMVIEW_EVENT_RECORD_SIZE,
    decode_systemview_events,
    encode_systemview_events,
)


def _events(count: int) -> list[dict]:
    return [
        {
            "kind": "task_start_exec" if index % 2 == 0 else "task_stop_exec",
            "task_id": 0x20000000 + index % 4,
            "t_ticks": index * 72,
            "t_us": float(index),
            "cpu_delta_us": 1.0,
        }
        for index in range(count)
    ]


def test_systemview_fixed_records_round_trip_and_reject_malformed_payload():
    events = _events(3)
    payload = encode_systemview_events(events)

    assert len(payload) == 3 * SYSTEMVIEW_EVENT_RECORD_SIZE
    decoded = decode_systemview_events(payload)
    assert [event["kind"] for event in decoded] == [event["kind"] for event in events]
    assert [event["task_id"] for event in decoded] == [event["task_id"] for event in events]
    assert [event["t_ticks"] for event in decoded] == [event["t_ticks"] for event in events]
    assert [event["t_us"] for event in decoded] == [event["t_us"] for event in events]

    with pytest.raises(ValueError, match="multiple"):
        decode_systemview_events(payload[:-1])

    malformed_flags = bytearray(payload[:SYSTEMVIEW_EVENT_RECORD_SIZE])
    malformed_flags[1] = 0x80
    with pytest.raises(ValueError, match="malformed"):
        decode_systemview_events(malformed_flags)


@pytest.mark.parametrize("flags", [0, 0x07], ids=["flags-off", "flags-on"])
@pytest.mark.parametrize("slot_offset", [16, 24, 32, 40], ids=["time", "delta", "aux0", "aux1"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")], ids=["nan", "pos-inf", "neg-inf"])
def test_decoder_rejects_non_finite_double_slots_regardless_of_flags(
    flags, slot_offset, value
):
    payload = bytearray(encode_systemview_events([
        {"kind": "task_info", "task_id": 1, "t_ticks": 1, "t_us": 1.0,
         "cpu_delta_us": 0.5, "prio": 3, "stack_size": 1024}
    ]))
    payload[1] = flags
    struct.pack_into("<d", payload, slot_offset, value)

    with pytest.raises(ValueError, match="finite"):
        decode_systemview_events(payload)


def test_unknown_systemview_kind_is_rejected_instead_of_silently_corrupted():
    with pytest.raises(ValueError, match="unknown SystemView event kind"):
        encode_systemview_events([{"kind": "future_event", "t_ticks": 1}])

    with pytest.raises(ValueError, match="context id must be an unsigned 32-bit integer"):
        encode_systemview_events([{"kind": "task_start_exec", "task_id": 1.5}])



@pytest.mark.parametrize("field", ["t_us", "cpu_delta_us", "prio", "stack_size"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_encoder_rejects_non_finite_double_fields(field, value):
    with pytest.raises(ValueError, match="finite"):
        encode_systemview_events([{"kind": "task_info", "task_id": 1, field: value}])


def test_length_prefixed_parser_events_use_a_generic_fixed_record():
    payload = encode_systemview_events([
        {"kind": "raw_512", "event_id": 512, "t_ticks": 9, "t_us": 1.5}
    ])

    assert decode_systemview_events(payload) == [
        {"kind": "raw_512", "t_ticks": 9, "t_us": 1.5, "event_id": 512}
    ]


def test_recording_precedes_bounded_live_publication_and_keeps_all_events():
    async def scenario():
        hub = StreamHub(max_batches_per_client=8)
        queue = hub.subscribe()
        manager = SystemViewStreamManager(stream_hub=hub)
        recorded: list[dict] = []

        class Recorder:
            def write_events(self, events):
                recorded.extend(events)

        manager._recording = Recorder()
        manager._process_events(_events(1200), now=123.0)
        await asyncio.sleep(0)

        batches = []
        while not queue.empty():
            batches.append(queue.get_nowait())
            queue.task_done()
        hub.unsubscribe(queue)

        assert len(recorded) == 1200
        assert sum(batch.item_count for batch in batches) == 1200
        assert all(batch.item_count <= manager._live_batch_limit for batch in batches)
        assert [batch.sequence for batch in batches] == sorted(
            batch.sequence for batch in batches
        )
        assert all(
            len(batch.payload) == batch.item_count * SYSTEMVIEW_EVENT_RECORD_SIZE
            for batch in batches
        )
        assert sum(len(decode_systemview_events(batch.payload)) for batch in batches) == 1200

    asyncio.run(scenario())


def test_slow_browser_drops_live_batches_without_truncating_recording():
    async def scenario():
        hub = StreamHub(max_batches_per_client=1)
        queue = hub.subscribe()
        manager = SystemViewStreamManager(stream_hub=hub)
        recorded: list[dict] = []

        class Recorder:
            def write_events(self, events):
                recorded.extend(events)

        manager._recording = Recorder()
        manager._process_events(_events(1200), now=123.0)
        await asyncio.sleep(0)

        stats = hub.stats()
        latest = queue.get_nowait()
        queue.task_done()
        hub.unsubscribe(queue)
        assert len(recorded) == 1200
        assert stats.produced_items == 1200
        assert stats.dropped_items == 1200 - latest.item_count
        assert latest.sequence == stats.last_sequence

    asyncio.run(scenario())
