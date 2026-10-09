from types import SimpleNamespace

import pytest

from mklink import usb_interfaces, usb_platform
from mklink.discovery import discover_mklink_command_ports


def port(path='/dev/cu.usbmodem-example', **values):
    return SimpleNamespace(**dict(device=path, vid=0x0D28, pid=0x0202, serial_number='fixture',
                                  hwid='USB VID:PID=0D28:0202 LOCATION=0-1.3.4.2.1',
                                  location='0-1.3.4.2.1', interface=None, description='fixture', **values))


def registry(data_parent=False):
    interfaces = []
    for number, name in [(2, 'MKLink USB to UART'), (4, 'MKLink Python Console'), (6, 'MKLink USB to RS485')]:
        serial = {'IOCalloutDevice': f'/dev/cu.usbmodem-fixture-{number}',
                  'IODialinDevice': f'/dev/tty.usbmodem-fixture-{number}'}
        interfaces.extend([
            {'bInterfaceNumber': number, 'bInterfaceClass': 2, 'bInterfaceSubClass': 2,
             'IORegistryEntryName': name, 'IORegistryEntryChildren': [] if data_parent else [serial]},
            {'bInterfaceNumber': number + 1, 'bInterfaceClass': 10,
             'IORegistryEntryChildren': [serial] if data_parent else []},
        ])
    return [{'idVendor': 0x0D28, 'idProduct': 0x0202, 'USB Serial Number': 'fixture',
             'IORegistryEntryChildren': interfaces}]


@pytest.mark.parametrize('platform_name', ['darwin', 'linux', 'win32'])
def test_hub_topology_is_never_an_interface(monkeypatch, platform_name):
    monkeypatch.setattr(usb_interfaces.sys, 'platform', platform_name)
    monkeypatch.setattr(usb_platform, 'macos_registry', lambda: [])
    monkeypatch.setattr(usb_platform, 'linux_interface_number', lambda _: None)
    assert usb_interfaces.usb_interface_number(port()) is None


@pytest.mark.parametrize('data_parent', [False, True])
def test_macos_three_identical_pyserial_metadata_ports_map_by_registry(monkeypatch, data_parent):
    from mklink import discovery
    from mklink.serial import _port
    ports = [port(f'/dev/cu.usbmodem-fixture-{i}') for i in (2, 4, 6)]
    monkeypatch.setattr(usb_interfaces.sys, 'platform', 'darwin')
    calls = []
    monkeypatch.setattr(usb_platform, 'macos_registry', lambda: calls.append(True) or registry(data_parent))
    monkeypatch.setattr(discovery.list_ports, 'comports', lambda: ports)
    monkeypatch.setattr(discovery.serial, 'Serial', lambda *a, **kw: pytest.fail('must not open a serial port'))
    assert discover_mklink_command_ports() == [ports[1]]
    assert len(calls) == 1
    assert [p['device'] for p in _port.list_uart_ports()] == [ports[0].device, ports[2].device]
    with pytest.raises(ValueError, match='command'):
        usb_interfaces.require_uart_port(ports[1].device)


def test_macos_never_guesses_bsd_node_suffix_or_missing_cdc_pair():
    assert usb_platform.macos_interface_from_registry(port('/dev/cu.usbmodem105'), []) is None
    tree = registry(True)
    tree[0]['IORegistryEntryChildren'][2]['IORegistryEntryName'] = 'unrecognized'
    assert usb_platform.macos_interface_from_registry(port('/dev/cu.usbmodem-fixture-4'), tree) is None


def test_macos_rejects_duplicate_nodes_and_mismatched_device():
    tree = registry()
    info = port('/dev/cu.usbmodem-fixture-4')
    assert usb_platform.macos_interface_from_registry(info, tree + tree) is None
    tree[0]['USB Serial Number'] = 'other'
    assert usb_platform.macos_interface_from_registry(info, tree) is None


def test_macos_supports_callout_and_dialin_without_suffix_assumptions():
    tree = registry()
    assert usb_platform.macos_interface_from_registry(port('/dev/tty.usbmodem-fixture-4'), tree) == 4


def test_linux_uses_location_field_even_with_interface_name(monkeypatch):
    monkeypatch.setattr(usb_interfaces.sys, 'platform', 'linux')
    info = port('/dev/ttyACM1')
    info.location = '1-2.3:1.4'
    info.interface = 'MKLink Python Console'
    assert usb_interfaces.usb_interface_number(info) == 4


def test_linux_sysfs_reads_hex_interface_and_checks_identity(tmp_path):
    root = tmp_path / 'tty'
    node = root / 'ttyACM1' / 'device'
    node.mkdir(parents=True)
    (node / 'bInterfaceNumber').write_text('04\n')
    (node.parent / 'idVendor').write_text('0d28\n')
    (node.parent / 'idProduct').write_text('0202\n')
    (node.parent / 'serial').write_text('fixture\n')
    info = port('/dev/ttyACM1')
    assert usb_platform.linux_interface_number(info, sysfs_root=root) == 4
    info.serial_number = 'other'
    assert usb_platform.linux_interface_number(info, sysfs_root=root) is None


def test_registry_failure_returns_unidentified(monkeypatch):
    monkeypatch.setattr(usb_platform.subprocess, 'run', lambda *a, **kw: (_ for _ in ()).throw(OSError('no ioreg')))
    assert usb_platform.macos_interface_number(port()) is None
