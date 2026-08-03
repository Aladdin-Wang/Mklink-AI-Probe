from types import SimpleNamespace

from mklink import discovery


def port(device, *, hwid="", vid=None, pid=None, manufacturer=""):
    return SimpleNamespace(
        device=device,
        hwid=hwid,
        vid=vid,
        pid=pid,
        manufacturer=manufacturer,
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
