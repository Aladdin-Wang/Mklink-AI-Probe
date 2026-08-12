from types import SimpleNamespace

from mklink import discovery


def port(
    device,
    *,
    hwid="",
    vid=None,
    pid=None,
    manufacturer="",
    serial_number=None,
):
    return SimpleNamespace(
        device=device,
        hwid=hwid,
        vid=vid,
        pid=pid,
        manufacturer=manufacturer,
        serial_number=serial_number,
    )


def test_discovery_probes_usb_before_virtual_and_skips_bluetooth(monkeypatch):
    ports = [
        port("COM98", hwid="BTHENUM\\device", manufacturer="Microsoft"),
        port("COM9", hwid="VSBC\\device", manufacturer="ELTIMA Software"),
        port("COM228", hwid="USB VID:PID=0D28:0202", vid=0x0D28, pid=0x0202),
        port("COM227", hwid="USB VID:PID=0D28:0202", vid=0x0D28, pid=0x0202),
    ]
    probed = []
    monkeypatch.setattr(discovery.list_ports, "comports", lambda: ports)
    monkeypatch.setattr(
        discovery,
        "_probe_port",
        lambda device: probed.append(device) or device == "COM227",
    )

    assert discovery.find_mklink_cdc_port() == "COM227"
    assert probed == ["COM228", "COM227"]


def test_discovery_probes_composite_interfaces_with_same_serial(monkeypatch):
    ports = [
        port(
            "COM221",
            hwid="USB VID:PID=0D28:0202",
            vid=0x0D28,
            pid=0x0202,
            serial_number="probe-1",
        ),
        port(
            "COM220",
            hwid="USB VID:PID=0D28:0202",
            vid=0x0D28,
            pid=0x0202,
            serial_number="probe-1",
        ),
        port(
            "COM219",
            hwid="USB VID:PID=0D28:0202",
            vid=0x0D28,
            pid=0x0202,
            serial_number="probe-1",
        ),
    ]
    probed = []
    monkeypatch.setattr(discovery.list_ports, "comports", lambda: ports)
    monkeypatch.setattr(
        discovery,
        "_probe_port",
        lambda device: probed.append(device) or device == "COM220",
    )

    assert discovery.find_mklink_cdc_port(serial_number="probe-1") == "COM220"
    assert probed == ["COM221", "COM220"]


def test_discovery_excludes_a_cmd_port_claimed_by_another_instance(monkeypatch):
    ports = [
        port("COM46", hwid="USB VID:PID=0D28:0202"),
        port("COM47", hwid="USB VID:PID=0D28:0202"),
        port("COM228", hwid="USB VID:PID=0D28:0202"),
    ]
    probed = []
    monkeypatch.setattr(discovery.list_ports, "comports", lambda: ports)
    monkeypatch.setattr(
        discovery,
        "_probe_port",
        lambda device: probed.append(device) or device == "COM228",
    )

    assert discovery.find_mklink_cdc_port(exclude_ports={"com46"}) == "COM228"
    assert probed == ["COM47", "COM228"]


def test_identity_response_rejects_a_generic_target_uart_prompt():
    assert not discovery._is_mklink_identity_response(b"target log\r\n>>> ")
    assert not discovery._is_mklink_identity_response(
        b">>> print('__mklink_probe_7f3a__')\r\n"
    )
    assert discovery._is_mklink_identity_response(
        b">>> print('__mklink_probe_7f3a__')\r\n"
        b"__mklink_probe_7f3a__\r\n>>> "
    )


def test_microkeen_disk_reads_volume_labels_without_console_process(monkeypatch):
    monkeypatch.setattr(discovery.os, "name", "nt")
    monkeypatch.setattr(
        discovery.os.path,
        "exists",
        lambda path: path in {"C:\\", "G:\\"},
    )
    labels = []
    monkeypatch.setattr(
        discovery,
        "_windows_volume_label",
        lambda path: labels.append(path) or ("MICROKEEN" if path == "G:\\" else "System"),
    )

    assert discovery.find_microkeen_disk() == "G:\\"
    assert labels == ["C:\\", "G:\\"]


def test_microkeen_disk_accepts_only_a_label_verified_configured_root(monkeypatch):
    monkeypatch.setattr(discovery.os, "name", "nt")
    monkeypatch.setenv("MKLINK_MICROKEEN_DISK", "E:")
    monkeypatch.setattr(discovery.os.path, "isdir", lambda path: path == "E:\\")
    monkeypatch.setattr(
        discovery,
        "_windows_volume_label",
        lambda path: "MICROKEEN" if path == "E:\\" else None,
    )

    assert discovery.find_microkeen_disk() == "E:\\"

    monkeypatch.setattr(discovery, "_windows_volume_label", lambda _path: "OTHER")
    assert discovery.find_microkeen_disk() is None
