from mklink.device import Device


class _MemoryDevice:
    def __init__(self, memory: dict[int, bytes]):
        self.memory = memory

    def _require_connected(self):
        return None

    def read_memory(self, address: int, size: int) -> bytes:
        return self.memory.get(address, b"\x00" * size)[:size]


def _thread_object(task_id: int, name: bytes, object_type: int) -> bytes:
    raw = bytearray(64)
    raw[: len(name)] = name
    raw[8] = object_type
    list_offset = 12
    list_address = task_id + list_offset
    raw[list_offset:list_offset + 4] = list_address.to_bytes(4, "little")
    raw[list_offset + 4:list_offset + 8] = list_address.to_bytes(4, "little")
    return bytes(raw)


def test_systemview_task_name_resolution_rejects_ascii_in_non_thread_memory():
    task_id = 0x2000018C
    raw = bytearray(64)
    raw[:3] = b"V1\x00"
    raw[8] = 0x09  # RT_Object_Class_Device, not a thread.
    device = _MemoryDevice({task_id: bytes(raw)})

    names = Device.systemview_resolve_task_names(device, [task_id])

    assert names == {}


def test_systemview_task_name_resolution_rejects_thread_marker_at_wrong_layout():
    task_id = 0x2000018C
    raw = bytearray(64)
    raw[:3] = b"V1\x00"
    raw[8] = 0x09  # Actual RT_NAME_MAX=8 object is a device.
    raw[16] = 0x01  # Unrelated byte must not be treated as another layout.
    device = _MemoryDevice({task_id: bytes(raw)})

    names = Device.systemview_resolve_task_names(device, [task_id])

    assert names == {}


def test_systemview_task_name_resolution_rejects_unaligned_or_non_sram_ids():
    raw = _thread_object(0x20001000, b"valid\x00", 0x01)
    device = _MemoryDevice({0x20001001: raw, 0x10001000: raw})

    names = Device.systemview_resolve_task_names(
        device, [0x20001001, 0x10001000]
    )

    assert names == {}


def test_systemview_task_name_resolution_accepts_dynamic_and_static_threads():
    dynamic_id = 0x20009F60
    static_id = 0x2000A000
    dynamic = _thread_object(dynamic_id, b"afe\x00", 0x01)
    static = _thread_object(static_id, b"svfast\x00", 0x81)
    device = _MemoryDevice({dynamic_id: dynamic, static_id: static})

    names = Device.systemview_resolve_task_names(device, [dynamic_id, static_id])

    assert names == {dynamic_id: "afe", static_id: "svfast"}
