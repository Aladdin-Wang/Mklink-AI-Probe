"""A shared backend must reject a changed USB selection before CDC commands."""
import os
from unittest.mock import Mock

import pytest

from mklink import bridge as bridge_module, probes as binding
from mklink.bridge import MKLinkSerialBridge
from mklink.probes import inventory
from test_probe_identity import port


@pytest.fixture
def bound_probe(monkeypatch, tmp_path):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setenv('MKLINK_LOCK_DIR', str(tmp_path / 'locks'))
    monkeypatch.setattr(binding, '_bound_probe', None)
    ports = [port('COM10', 'first'), port('COM20', 'second', '1-2:x.4')]
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: ports)
    selected = next(p for p in inventory() if p['port'] == 'COM10')
    binding.bind_runtime(selected['probe_id'])
    return ports


def change_selection(ports, change):
    if change == 'missing':
        ports.pop(0)
    elif change == 'replaced':
        ports[0] = port('COM10', 'replacement')
    elif change == 'renumbered':
        ports[0] = port('COM99', 'first')
    elif change == 'duplicate':
        ports.append(port('COM30', 'first', '1-3:x.4'))


def assert_port_released():
    other = MKLinkSerialBridge('COM10')
    try:
        assert other._port_lock.acquire(), 'Rejected open retained the port lock'
    finally:
        other.close()


@pytest.mark.parametrize('change', ['missing', 'replaced', 'renumbered', 'duplicate'])
def test_identity_change_before_open_never_constructs_serial(bound_probe, monkeypatch, change):
    change_selection(bound_probe, change)
    constructor = Mock(side_effect=AssertionError('Opened a different or missing probe'))
    monkeypatch.setattr(bridge_module.serial, 'Serial', constructor)
    bridge = MKLinkSerialBridge('COM10')
    try:
        assert bridge.connect() is False
        constructor.assert_not_called()
        assert_port_released()
    finally:
        bridge.close()


@pytest.mark.parametrize('frozen', [False, True])
@pytest.mark.parametrize('isolated', [False, pytest.param(True, marks=pytest.mark.skipif(os.name != 'nt', reason='Windows transport'))])
@pytest.mark.parametrize('change', ['missing', 'replaced', 'renumbered', 'duplicate'])
def test_identity_change_during_open_closes_without_commands(bound_probe, monkeypatch, change, isolated, frozen):
    monkeypatch.setattr(bridge_module.sys, 'frozen', frozen, raising=False)
    serial_port = Mock(is_open=True)
    serial_port.close.side_effect = lambda: setattr(serial_port, 'is_open', False)
    opened = []
    def constructor(*args, **kwargs):
        opened.append(args[0])
        change_selection(bound_probe, change)
        return serial_port
    if isolated:
        # Select the real Windows bridge branch, replacing only its transport.
        constructor.__module__ = 'serial.serialwin32'
        monkeypatch.setattr(bridge_module, 'IsolatedSerial', constructor)
    monkeypatch.setattr(bridge_module.serial, 'Serial', constructor)
    bridge = MKLinkSerialBridge('COM10')
    try:
        assert bridge.connect() is False
        assert opened == ['COM10']
        serial_port.reset_input_buffer.assert_not_called()
        serial_port.reset_output_buffer.assert_not_called()
        serial_port.write.assert_not_called()
        serial_port.close.assert_called_once()
        assert not bridge._running and bridge._reader_thread is None
        assert_port_released()
    finally:
        bridge.close()


def test_bound_identity_allows_only_its_own_port(bound_probe, monkeypatch):
    constructor = Mock(side_effect=AssertionError('Opened another backend probe'))
    monkeypatch.setattr(bridge_module.serial, 'Serial', constructor)
    bridge = MKLinkSerialBridge('COM20')
    try:
        assert bridge.connect() is False
        constructor.assert_not_called()
    finally:
        bridge.close()


def test_unchanged_identity_keeps_existing_handshake(bound_probe, monkeypatch):
    serial_port = Mock(is_open=True)
    monkeypatch.setattr(bridge_module.serial, 'Serial', Mock(return_value=serial_port))
    monkeypatch.setattr(bridge_module.threading, 'Thread', Mock())
    bridge = MKLinkSerialBridge('COM10')
    bridge._prompt_event = Mock()
    bridge._prompt_event.wait.return_value = True
    try:
        assert bridge.connect() is True
        serial_port.write.assert_called_once_with(b'\n')
        serial_port.reset_input_buffer.assert_called_once()
    finally:
        bridge.close()


def test_runtime_binding_cannot_be_changed_or_cleared(bound_probe):
    selected = next(p for p in inventory() if p['port'] == 'COM10')['probe_id']
    binding.bind_runtime(selected)
    for other in ('lobby', 'other', None):
        with pytest.raises(RuntimeError, match='cannot change'):
            binding.bind_runtime(other)


def test_lobby_cannot_open_a_command_port(bound_probe, monkeypatch):
    monkeypatch.setattr(binding, '_bound_probe', 'lobby')
    selected = inventory()[0]['probe_id']
    monkeypatch.setattr(binding, 'load_aliases', lambda: {selected: 'lobby'})
    constructor = Mock(side_effect=AssertionError('Lobby opened CDC'))
    monkeypatch.setattr(bridge_module.serial, 'Serial', constructor)
    bridge = MKLinkSerialBridge('COM10')
    try:
        assert bridge.connect() is False
        constructor.assert_not_called()
    finally:
        bridge.close()


@pytest.mark.parametrize('fail_after_open', [False, True])
def test_enumeration_error_releases_open_and_lock(bound_probe, monkeypatch, fail_after_open):
    serial_port = Mock(is_open=True)
    serial_port.close.side_effect = lambda: setattr(serial_port, 'is_open', False)
    def fail():
        raise OSError('USB enumeration unavailable')
    def constructor(*args, **kwargs):
        monkeypatch.setattr('serial.tools.list_ports.comports', fail)
        return serial_port
    if not fail_after_open:
        monkeypatch.setattr('serial.tools.list_ports.comports', fail)
    opened = Mock(side_effect=constructor)
    monkeypatch.setattr(bridge_module.serial, 'Serial', opened)
    bridge = MKLinkSerialBridge('COM10')
    try:
        with pytest.raises(OSError, match='USB enumeration unavailable'):
            bridge.connect()
        assert opened.call_count == int(fail_after_open)
        assert serial_port.close.call_count == int(fail_after_open)
        serial_port.write.assert_not_called()
        assert_port_released()
    finally:
        bridge.close()
