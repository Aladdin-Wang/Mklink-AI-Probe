from types import SimpleNamespace

from mklink import discovery
from mklink._types import MKLINK_IDENTITY_COMMAND, MKLINK_IDENTITY_TOKEN


def port(
    device,
    *,
    hwid="",
    vid=None,
    pid=None,
    manufacturer="",
    serial_number=None,
    location="",
    interface=None,
    description="",
):
    return SimpleNamespace(
        device=device,
        hwid=hwid,
        vid=vid,
        pid=pid,
        manufacturer=manufacturer,
        serial_number=serial_number,
        location=location,
        interface=interface,
        description=description,
    )


def test_discovery_selects_mi04_without_opening_other_interfaces(monkeypatch):
    ports = [
        port(
            "COM54",
            hwid="USB VID:PID=0D28:0202 LOCATION=1-2:x.2",
            vid=0x0D28,
            pid=0x0202,
            serial_number="probe-v4",
            location="1-2:x.2",
        ),
        port(
            "COM55",
            hwid="USB VID:PID=0D28:0202 LOCATION=1-2:x.4",
            vid=0x0D28,
            pid=0x0202,
            serial_number="probe-v4",
            location="1-2:x.4",
        ),
        port(
            "COM56",
            hwid="USB VID:PID=0D28:0202 LOCATION=1-2:x.6",
            vid=0x0D28,
            pid=0x0202,
            serial_number="probe-v4",
            location="1-2:x.6",
        ),
    ]
    monkeypatch.setattr(discovery.list_ports, "comports", lambda: ports)
    monkeypatch.setattr(
        discovery,
        "_probe_port",
        lambda _device: (_ for _ in ()).throw(
            AssertionError("descriptor-based discovery must not open a port")
        ),
    )

    assert discovery.find_mklink_cdc_port() == "COM55"
    assert discovery.find_mklink_cdc_port(serial_number="PROBE-V4") == "COM55"


def test_discover_all_command_ports_skips_non_command_and_bluetooth(monkeypatch):
    ports = [
        port(
            "COM227",
            hwid=r"USB\VID_0D28&PID_0202&MI_02",
            vid=0x0D28,
            pid=0x0202,
        ),
        port(
            "COM228",
            hwid=r"USB\VID_0D28&PID_0202&MI_04",
            vid=0x0D28,
            pid=0x0202,
        ),
        port(
            "COM229",
            hwid=r"USB\VID_0D28&PID_0202&MI_06",
            vid=0x0D28,
            pid=0x0202,
        ),
        port("COM98", hwid=r"BTHENUM\device"),
    ]
    monkeypatch.setattr(discovery.list_ports, "comports", lambda: ports)
    monkeypatch.setattr(
        discovery,
        "_probe_port",
        lambda _device: (_ for _ in ()).throw(
            AssertionError("known non-command and Bluetooth ports must not open")
        ),
    )

    assert [item.device for item in discovery.discover_mklink_command_ports()] == [
        "COM228"
    ]


def test_missing_interface_metadata_never_probes_serial_ports(monkeypatch):
    ports = [port('COM44', vid=0x0D28, pid=0x0202), port('COM45', hwid='USB OTHER')]
    monkeypatch.setattr(discovery.list_ports, 'comports', lambda: ports)
    monkeypatch.setattr(discovery, '_probe_port', lambda *_: (_ for _ in ()).throw(AssertionError('unexpected serial I/O')))
    assert discovery.discover_mklink_command_ports() == []
    assert discovery.find_mklink_cdc_port() is None


def test_discovery_uses_mi04_from_the_requested_composite_device(monkeypatch):
    ports = [
        port(
            "COM739",
            vid=0x0D28,
            pid=0x0202,
            serial_number="probe-v3",
            location="1-1.2:x.4",
        ),
        port(
            "COM55",
            vid=0x0D28,
            pid=0x0202,
            serial_number="probe-v4",
            location="1-2:x.4",
        ),
    ]
    monkeypatch.setattr(discovery.list_ports, "comports", lambda: ports)

    assert discovery.find_mklink_cdc_port(serial_number="probe-v4") == "COM55"


def test_missing_serial_never_falls_back_to_another_probe(monkeypatch):
    ports = [port('COM55', vid=0x0D28, pid=0x0202, serial_number='present', location='1-2:x.4')]
    monkeypatch.setattr(discovery.list_ports, 'comports', lambda: ports)
    assert discovery.find_mklink_cdc_port(serial_number='missing') is None


def test_multiple_command_ports_require_unique_identity(monkeypatch):
    ports = [port('COM55', vid=0x0D28, pid=0x0202, serial_number='one', location='1-2:x.4'),
             port('COM66', vid=0x0D28, pid=0x0202, serial_number='two', location='1-3:x.4')]
    monkeypatch.setattr(discovery.list_ports, 'comports', lambda: ports)
    assert discovery.find_mklink_cdc_port() is None
    assert discovery.find_mklink_cdc_port(serial_number='TWO') == 'COM66'
    ports[1].serial_number='one'
    assert discovery.find_mklink_cdc_port(serial_number='one') is None


def test_identity_response_rejects_a_generic_target_uart_prompt():
    assert not discovery._is_mklink_identity_response(b"target log\r\n>>> ")
    assert not discovery._is_mklink_identity_response(
        b">>> print('__mklink_probe_7f3a__')\r\n"
    )
    assert discovery._is_mklink_identity_response(
        b">>> print('__mklink_probe_7f3a__')\r\n"
        b"__mklink_probe_7f3a__\r\n>>> "
    )


def test_probe_port_terminates_a_partial_repl_line_before_identity(monkeypatch):
    class ProbeSerial:
        def __init__(self, *_args, timeout, **_kwargs):
            self.timeout = timeout
            self.is_open = True
            self.writes = []
            self.responses = [
                b"SyntaxError: invalid syntax\r\n>>> ",
                (
                    MKLINK_IDENTITY_COMMAND.encode("ascii")
                    + b"\r\n"
                    + MKLINK_IDENTITY_TOKEN.encode("ascii")
                    + b"\r\n>>> "
                ),
            ]

        def reset_input_buffer(self):
            pass

        def reset_output_buffer(self):
            pass

        def write(self, data):
            self.writes.append(data)

        def flush(self):
            pass

        def read_until(self, _expected, _size):
            return self.responses.pop(0)

        def close(self):
            self.is_open = False

    opened = []

    def open_serial(*args, **kwargs):
        instance = ProbeSerial(*args, **kwargs)
        opened.append(instance)
        return instance

    monkeypatch.setattr(discovery.serial, "Serial", open_serial)

    assert discovery._probe_port("TEST_CMD")
    assert opened[0].writes == [
        b"\n",
        (MKLINK_IDENTITY_COMMAND + "\n").encode("ascii"),
    ]


def test_unbound_disk_uses_probe_identity_not_label_or_override(monkeypatch):
    monkeypatch.setattr('mklink.probes._bound_probe', None)
    monkeypatch.setenv('MKLINK_MICROKEEN_DISK', 'E:')
    monkeypatch.setattr('mklink.probes.inventory', lambda: [{'probe_id': 'selected'}])
    resolved = []
    def resolve(probe_id):
        resolved.append(probe_id)
        return {'root': 'verified-volume'}
    monkeypatch.setattr('mklink.probe_volumes.resolve_volume', resolve)
    def forbidden(*args):
        raise AssertionError('Legacy label discovery ran')
    monkeypatch.setattr(discovery, '_windows_volume_label', forbidden)
    assert discovery.find_microkeen_disk() == 'verified-volume'
    assert resolved == ['selected']


def test_unbound_disk_rejects_missing_or_multiple_probes_before_volume_io(monkeypatch):
    import pytest
    from mklink.runtime import RuntimeErrorResponse
    monkeypatch.setattr('mklink.probes._bound_probe', None)
    monkeypatch.setenv('MKLINK_MICROKEEN_DISK', 'E:')
    monkeypatch.setattr('mklink.probe_volumes.resolve_volume', lambda *a: pytest.fail('Ambiguous disk resolution'))
    for devices, message in [([], 'No supported probe'), ([{}, {}], 'Multiple probes')]:
        monkeypatch.setattr('mklink.probes.inventory', lambda: devices)
        with pytest.raises(RuntimeErrorResponse, match=message):
            discovery.find_microkeen_disk()


def test_unbound_missing_volume_does_not_fall_back_to_label(monkeypatch):
    import pytest
    monkeypatch.setattr('mklink.probes._bound_probe', None)
    monkeypatch.setattr('mklink.probes.inventory', lambda: [{'probe_id': 'selected'}])
    def missing(probe_id):
        raise RuntimeError('identity missing')
    monkeypatch.setattr('mklink.probe_volumes.resolve_volume', missing)
    monkeypatch.setattr(discovery, '_windows_volume_label', lambda *a: pytest.fail('Label fallback'))
    with pytest.raises(RuntimeError, match='identity missing'):
        discovery.find_microkeen_disk()
