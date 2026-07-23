from mklink.systemview_parser import EVTID_STACK_INFO, EVTID_TASK_INFO, SystemViewParser


def _encode_u32(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def test_task_info_uses_segger_task_id_priority_name_order():
    task_id_raw = 0x123
    priority = 6
    name = b"svuser"
    timestamp_delta = 7
    packet = b"".join(
        (
            bytes((EVTID_TASK_INFO,)),
            _encode_u32(task_id_raw),
            _encode_u32(priority),
            bytes((len(name),)),
            name,
            _encode_u32(timestamp_delta),
        )
    )

    parser = SystemViewParser()
    events = parser.feed(packet)

    assert events == [
        {
            "kind": "task_info",
            "task_id_raw": task_id_raw,
            "task_id": task_id_raw << 2,
            "prio": priority,
            "name": "svuser",
            "delta_ticks": timestamp_delta,
            "t_ticks": timestamp_delta,
            "task_name": "svuser",
        }
    ]
    assert parser.task_name(task_id_raw << 2) == "svuser"


def test_stack_info_consumes_stack_end_before_timestamp_delta():
    task_id_raw = 0x123
    stack_base = 0x20001000
    stack_size = 1024
    stack_end = 0
    timestamp_delta = 7
    packet = b"".join(
        (
            bytes((EVTID_STACK_INFO,)),
            _encode_u32(task_id_raw),
            _encode_u32(stack_base),
            _encode_u32(stack_size),
            _encode_u32(stack_end),
            _encode_u32(timestamp_delta),
        )
    )

    parser = SystemViewParser()
    events = parser.feed(packet)

    assert events == [
        {
            "kind": "stack_info",
            "task_id_raw": task_id_raw,
            "task_id": task_id_raw << 2,
            "stack_base": stack_base,
            "stack_size": stack_size,
            "stack_end": stack_end,
            "delta_ticks": timestamp_delta,
            "t_ticks": timestamp_delta,
            "task_name": None,
        }
    ]


def test_task_info_rejects_non_printable_names_from_false_packet_alignment():
    task_id_raw = 6
    priority = 5
    name = b"n_rx\x00corrupt"
    invalid_packet = b"".join(
        (
            bytes((EVTID_TASK_INFO,)),
            _encode_u32(task_id_raw),
            _encode_u32(priority),
            bytes((len(name),)),
            name,
            _encode_u32(7),
        )
    )
    valid_packet = b"".join(
        (
            bytes((4,)),
            _encode_u32(0x123),
            _encode_u32(11),
        )
    )

    parser = SystemViewParser()
    events = parser.feed(invalid_packet + valid_packet)

    assert events == [
        {
            "kind": "task_start_exec",
            "task_id_raw": 0x123,
            "task_id": 0x123 << 2,
            "delta_ticks": 11,
            "t_ticks": 11,
            "task_name": None,
        }
    ]
    assert parser.task_name(task_id_raw << 2) is None
    assert parser.dropped_packets == 1
