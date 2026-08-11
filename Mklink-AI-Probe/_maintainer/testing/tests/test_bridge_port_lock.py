"""Cross-process MKLink CMD port lock regression tests."""

from __future__ import annotations

from mklink.bridge import MKLinkSerialBridge


def test_mklink_bridges_lock_each_cmd_port_independently(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP", str(tmp_path))
    first = MKLinkSerialBridge("COM201")
    second = MKLinkSerialBridge("COM202")
    duplicate = MKLinkSerialBridge("COM201")

    try:
        assert first._port_lock.acquire()
        assert second._port_lock.acquire()
        assert not duplicate._port_lock.acquire()
    finally:
        duplicate._port_lock.release()
        second._port_lock.release()
        first._port_lock.release()
