from __future__ import annotations

from mklink.modbus._client import _PortLock


def test_com_device_name_uses_real_prefixed_lock_file_and_serializes(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("TEMP", str(tmp_path))
    first = _PortLock("COM6")
    second = _PortLock("com6")

    assert first.acquire() is True
    assert first._path.endswith("port_COM6.lock")
    assert second.acquire() is False

    first.release()
    assert second.acquire() is True
    second.release()
