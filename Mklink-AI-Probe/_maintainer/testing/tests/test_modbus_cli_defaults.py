"""Explicit serial settings must survive loading a saved Modbus port."""
import sys

import pytest

from mklink import cli, project_config


COMMANDS = [
    ['scan'],
    ['read', '--slave', '1', '--fc', '3', '--start', '0'],
    ['write', '--slave', '1', '--fc', '6', '--start', '0', '42'],
    ['poll', '--slave', '1', '--registers', '0:uint16'],
    ['monitor'],
    ['diag', '--slave', '1'],
    ['dashboard'],
]


def resolve(monkeypatch, command, options, config):
    captured = []
    monkeypatch.setattr(project_config, 'load_config', lambda _: config)
    monkeypatch.setattr(sys, 'argv', ['mklink', 'modbus', *command, *options])
    def dispatch(args):
        captured.append((cli._modbus_resolve_defaults(args), args))
    # Exercise the real parser and default resolver, stopping before any I/O.
    monkeypatch.setattr(cli, '_cli_modbus_dispatch', dispatch)
    cli.main()
    assert len(captured) == 1
    return captured[0]


@pytest.mark.parametrize('command', COMMANDS, ids=lambda command: command[0])
def test_explicit_values_including_builtin_defaults_override_saved_profile(monkeypatch, command):
    ok, args = resolve(monkeypatch, command, ['--baud', '9600', '--parity', 'N', '--stopbits', '1'],
                       {'modbus_port': 'SAVED', 'modbus_baud': 115200,
                        'modbus_parity': 'E', 'modbus_stopbits': 2})
    assert ok and args.port == 'SAVED'
    assert (args.baud, args.parity, args.stopbits) == (9600, 'N', 1)


@pytest.mark.parametrize('options,config,expected', [
    ([], {'modbus_port': 'SAVED', 'modbus_baud': 115200, 'modbus_parity': 'E', 'modbus_stopbits': 2},
     (True, 'SAVED', 115200, 'E', 2)),
    (['--baud', '19200'], {'modbus_port': 'SAVED', 'modbus_parity': 'O', 'modbus_stopbits': 2},
     (True, 'SAVED', 19200, 'O', 2)),
    (['--port', 'OTHER'], {'modbus_port': 'SAVED', 'modbus_baud': 115200, 'modbus_parity': 'E', 'modbus_stopbits': 2},
     (True, 'OTHER', 9600, 'N', 1)),
    ([], {'modbus_port': 'SAVED'}, (True, 'SAVED', 9600, 'N', 1)),
    ([], None, (False, None, 9600, 'N', 1)),
])
def test_saved_port_defaults_fill_only_unspecified_values(monkeypatch, options, config, expected):
    ok, args = resolve(monkeypatch, ['scan'], options, config)
    assert (ok, args.port, args.baud, args.parity, args.stopbits) == expected
