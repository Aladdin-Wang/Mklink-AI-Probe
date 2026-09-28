import asyncio
import json
from types import SimpleNamespace

import pytest

from mklink._types import DeviceState
from mklink.power import parse_power_response, read_power


def wire(**changes):
    data = dict(schema=1, voltage_mv=3300, current_ua=12345, power_uw=40739,
                current_supported=True, sample_age_ms=10)
    data.update(changes)
    return 'cmd.get_power()\r\nMKLINK_POWER ' + json.dumps(data) + '\r\n>>> '


class Bridge:
    state = DeviceState.READY

    def __init__(self, response=None):
        self.response = wire() if response is None else response
        self.commands = []
        self.closed = False

    def connect(self):
        return True

    def send_command(self, command, timeout):
        self.commands.append(command)
        return self.response

    def close(self):
        self.closed = True


def test_v4_units_and_probe_only_command():
    bridge = Bridge()
    assert read_power(bridge) == dict(voltage_mv=3300, current_ma=12.345,
                                      power_mw=40.739, current_supported=True,
                                      sample_age_ms=10)
    assert bridge.commands == ['cmd.get_power()']


def test_v3_does_not_fabricate_current_or_power():
    result = parse_power_response(wire(current_supported=False, current_ua=None, power_uw=None))
    assert result['voltage_mv'] == 3300
    assert result['current_ma'] is result['power_mw'] is None
    assert result['current_supported'] is False


def test_zero_is_a_valid_measurement_but_adc_not_ready_is_null():
    result = parse_power_response(wire(voltage_mv=0, current_ua=0, power_uw=0))
    assert result['voltage_mv'] == result['current_ma'] == result['power_mw'] == 0
    result = parse_power_response(wire(voltage_mv=None, current_ua=None, power_uw=None))
    assert result['voltage_mv'] is result['current_ma'] is result['power_mw'] is None


@pytest.mark.parametrize('changes', [
    {'voltage_mv': -1}, {'voltage_mv': True}, {'current_ua': float('nan')},
    {'power_uw': float('inf')}, {'power_uw': 1}, {'sample_age_ms': 1001},
    {'sample_age_ms': None}, {'schema': 2}, {'schema': True},
    {'current_supported': 1}, {'current_supported': False},
    {'voltage_mv': None}, {'current_ua': None}, {'voltage_mv': '3300'},
])
def test_rejects_invalid_or_stale_measurements(changes):
    with pytest.raises(ValueError):
        parse_power_response(wire(**changes))


@pytest.mark.parametrize('response', [
    'AttributeError: cmd has no get_power\n>>>', '', 'MKLINK_POWER {}',
    'MKLINK_POWER []', 'MKLINK_POWER broken', wire() + '\n' + wire(),
])
def test_old_firmware_or_bad_frames_never_become_zero(response):
    with pytest.raises(ValueError):
        parse_power_response(response)


@pytest.mark.parametrize('state', [s for s in DeviceState if s != DeviceState.READY])
def test_busy_or_streaming_session_is_not_interrupted(state):
    bridge = Bridge()
    bridge.state = state
    with pytest.raises(RuntimeError, match='idle'):
        read_power(bridge)
    assert bridge.commands == []


def test_device_entry_uses_same_parser():
    from mklink.device import Device
    dev = object.__new__(Device)
    dev._connected = True
    dev._bridge = Bridge()
    assert dev.get_power()['current_ma'] == 12.345
    assert dev._bridge.commands == ['cmd.get_power()']


def test_cli_json_has_no_diagnostics_and_closes_port(monkeypatch, capsys):
    from mklink import bridge as bridge_module, cli
    bridge = Bridge()
    def connect():
        print('connection diagnostic')
        return True
    bridge.connect = connect
    monkeypatch.setattr(bridge_module, 'MKLinkSerialBridge', lambda port: bridge)
    assert cli._cli_power_read('COM_TEST', as_json=True) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)['power_mw'] == 40.739
    assert 'connection diagnostic' in output.err
    assert bridge.closed and bridge.commands == ['cmd.get_power()']


def test_cli_old_firmware_fails_and_closes_port(monkeypatch, capsys):
    from mklink import bridge as bridge_module, cli
    bridge = Bridge('AttributeError: get_power\n>>>')
    monkeypatch.setattr(bridge_module, 'MKLinkSerialBridge', lambda port: bridge)
    assert cli._cli_power_read('COM_TEST', as_json=True) == 1
    output = capsys.readouterr()
    assert not output.out and 'upgrade' in output.err
    assert bridge.closed


def test_cli_dispatch(monkeypatch, capsys):
    import sys
    from mklink import cli
    calls = []
    monkeypatch.setattr(sys, 'argv', ['mklink', 'power-read', '--port', 'COM_TEST', '--json'])
    monkeypatch.setattr(cli, '_cli_power_read', lambda port, as_json: calls.append((port, as_json)) or 0)
    assert cli.main() == 0
    assert calls == [('COM_TEST', True)]


def test_mcp_registration_schema_and_read_only_result(monkeypatch):
    import fastmcp
    from mklink import mcp_server
    bridge = Bridge()
    dev = SimpleNamespace(get_power=lambda: read_power(bridge))
    monkeypatch.setattr(mcp_server, '_connected_device', lambda: dev)
    monkeypatch.setitem(mcp_server._holder, 'quarantine', None)
    server = fastmcp.FastMCP('power-contract')
    mcp_server._register_flash_tools(server)

    async def exchange():
        async with fastmcp.Client(server) as client:
            tool = next(t for t in await client.list_tools() if t.name == 'get_power')
            assert not tool.inputSchema.get('required')
            assert not tool.inputSchema.get('properties')
            result = await client.call_tool('get_power', {})
            assert result.data['voltage_mv'] == 3300
            assert result.data['current_ma'] == 12.345
    asyncio.run(exchange())
    assert bridge.commands == ['cmd.get_power()']
