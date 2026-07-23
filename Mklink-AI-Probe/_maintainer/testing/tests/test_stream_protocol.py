from dataclasses import FrozenInstanceError

import pytest

from mklink.remote.stream_protocol import Frame, StreamType, decode_frame, encode_frame


GOLDEN = bytes.fromhex(
    "4d4b535401020024070000000900000000000000e803000000000000"
    "02000000080000000000803f000000c0"
)
MAX_PAYLOAD_SIZE = 4 * 1024 * 1024


def test_waveform_frame_matches_v1_golden_vector():
    frame = Frame(
        StreamType.WAVEFORM,
        0,
        7,
        9,
        1000,
        2,
        bytes.fromhex("0000803f000000c0"),
    )

    assert encode_frame(frame) == GOLDEN
    assert decode_frame(GOLDEN) == frame


def test_frame_is_immutable():
    frame = decode_frame(GOLDEN)

    with pytest.raises(FrozenInstanceError):
        frame.sequence = 10


@pytest.mark.parametrize(
    ("offset", "replacement", "match"),
    [
        (0, ord("X"), "magic"),
        (4, 2, "version"),
        (5, 99, "stream type"),
        (7, 35, "header size"),
    ],
)
def test_decode_rejects_invalid_header_fields(offset, replacement, match):
    encoded = bytearray(GOLDEN)
    encoded[offset] = replacement

    with pytest.raises(ValueError, match=match):
        decode_frame(bytes(encoded))


@pytest.mark.parametrize("declared_length", [7, 9])
def test_decode_rejects_payload_length_mismatch(declared_length):
    encoded = bytearray(GOLDEN)
    encoded[32:36] = declared_length.to_bytes(4, "little")

    with pytest.raises(ValueError, match="payload length"):
        decode_frame(bytes(encoded))


def test_decode_rejects_payload_larger_than_four_mib_before_reading_it():
    encoded = bytearray(GOLDEN[:36])
    encoded[32:36] = (MAX_PAYLOAD_SIZE + 1).to_bytes(4, "little")

    with pytest.raises(ValueError, match="payload.*4 MiB"):
        decode_frame(bytes(encoded))


def test_encode_rejects_payload_larger_than_four_mib():
    frame = Frame(
        StreamType.RTT_RAW,
        0,
        1,
        1,
        1,
        1,
        b"x" * (MAX_PAYLOAD_SIZE + 1),
    )

    with pytest.raises(ValueError, match="payload.*4 MiB"):
        encode_frame(frame)
