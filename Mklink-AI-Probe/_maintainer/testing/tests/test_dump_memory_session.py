import binascii
import struct

from mklink._types import DeviceState
from mklink.dump_memory import (
    DumpMemoryStreamSession,
    FLAG_SAMPLE_DROPPED,
    MAGIC,
    read_dump_memory_once,
)


def _old_frame(timestamp_us, payload, *, flags=0):
    region = b"\x00" + struct.pack("<H", len(payload)) + payload
    length = 19 + len(region) + 6
    body = MAGIC + struct.pack("<QHB", timestamp_us, length, 1) + region + struct.pack("<H", flags)
    return body + struct.pack("<I", binascii.crc32(body) & 0xFFFFFFFF)


class FakeBridge:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.calls = []

    def _enter_stream(self, state):
        self.calls.append(("enter", state))

    def _write_raw(self, data):
        self.calls.append(("write", data))

    def drain_stream_bytes(self, max_bytes=None):
        self.calls.append(("drain", max_bytes))
        return self.chunks.pop(0) if self.chunks else b""

    def _exit_stream(self):
        self.calls.append(("exit",))
        return ""


def test_dump_session_reuses_parser_and_owns_exact_stream_lifecycle():
    bridge = FakeBridge([b"noise" + _old_frame(123, struct.pack("<f", 2.5))])
    session = DumpMemoryStreamSession(
        bridge, [(0x20000000, 4)], 0.0001, stop_grace_s=0,
    )

    session.start()
    frames = session.read_frames(max_bytes=8192)
    session.stop()

    assert frames[0]["timestamp_us"] == 123
    assert struct.unpack("<f", frames[0]["regions"][0][1]) == (2.5,)
    assert bridge.calls[0] == ("enter", DeviceState.DUMP_STREAM)
    assert bridge.calls[1] == (
        "write", b"cmd.dump_memory(0x20000000, 4, 0.0001)\n",
    )
    assert bridge.calls[-3] == (
        "write", b"cmd.dump_memory(0x20000000, 4, 0)\n",
    )
    assert bridge.calls[-2] == ("drain", None)
    assert bridge.calls[-1] == ("exit",)
    assert session.stats == {
        "protocol_frames": 1,
        "complete_samples": 1,
        "parser_dropped_bytes": 5,
        "parser_dropped_frames": 0,
        "parser_crc_errors": 0,
        "firmware_flagged_frames": 0,
        "firmware_sample_drop_flags": 0,
    }


def test_dump_session_reports_crc_loss_and_firmware_drop_flags_separately():
    corrupt = bytearray(_old_frame(1, b"abcd"))
    corrupt[-1] ^= 0xFF
    bridge = FakeBridge([
        bytes(corrupt) + _old_frame(2, b"efgh", flags=FLAG_SAMPLE_DROPPED),
    ])
    session = DumpMemoryStreamSession(bridge, [(0x20000000, 4)], 0.001, stop_grace_s=0)

    session.start()
    frames = session.read_frames()
    session.stop()

    assert len(frames) == 1
    assert session.stats["parser_crc_errors"] == 1
    assert session.stats["parser_dropped_frames"] == 1
    assert session.stats["firmware_flagged_frames"] == 1
    assert session.stats["firmware_sample_drop_flags"] == 1


def test_one_shot_dump_reads_payload_and_stops_stream_cleanly():
    bridge = FakeBridge([b"noise", _old_frame(123, b"\x01\x02\x03\x04")])

    payload = read_dump_memory_once(
        bridge, 0x20000020, 4, timeout=0.1, poll_interval=0,
    )

    assert payload == b"\x01\x02\x03\x04"
    assert bridge.calls[0] == ("enter", DeviceState.DUMP_STREAM)
    assert bridge.calls[1] == (
        "write", b"cmd.dump_memory(0x20000020, 4, 0)\n",
    )
    assert ("write", b"RTTView.stop()\n") in bridge.calls
    assert bridge.calls[-1] == ("exit",)
