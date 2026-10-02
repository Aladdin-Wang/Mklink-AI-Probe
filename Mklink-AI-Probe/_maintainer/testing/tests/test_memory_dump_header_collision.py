import pytest

from mklink.memory_access import parse_read_ram_response
from mklink.superwatch import parse_timestamped_read_ram_response


@pytest.mark.parametrize('prefix', [b'', b'\xff' * 16])
@pytest.mark.parametrize('payload', [bytes(range(47)), bytes(range(16)) * 3, bytes(47)])
def test_real_ram_rows_matching_header_are_preserved(prefix, payload):
    data = prefix + payload
    lines = ['cmd.read_ram(0x24040FA1, %d)' % len(data),
             '12345678 ' + bytes(range(16)).hex(' ').upper()]
    lines += [f'{0x24040FA1 + i:08x} ' + data[i:i+16].hex(' ') + ' '
              for i in range(0, len(data), 16)]
    raw = '\r\n'.join(lines) + '\r\n>>> '
    assert parse_read_ram_response(raw) == data
    timed = parse_timestamped_read_ram_response(raw)
    assert timed.data == data
    assert timed.timestamp_us == 0x12345678


def test_legacy_dump_without_timestamp_header():
    raw = '         00 01 02 03\r\n20000000 aa bb cc dd\r\n'
    assert parse_read_ram_response(raw) == bytes.fromhex('aa bb cc dd')
