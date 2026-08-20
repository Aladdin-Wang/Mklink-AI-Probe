from __future__ import annotations

import json
import socket
import time

import pytest

from mklink.hil_lock import HilFileLock, HilLockHeld


def _write_holder(lock: HilFileLock, *, hostname: str, pid: int) -> None:
    lock.root.mkdir(parents=True, exist_ok=True)
    lock.path.write_text(
        json.dumps({
            "owner_id": "previous-owner",
            "pid": pid,
            "hostname": hostname,
            "acquired_at": time.time(),
            "lease_s": 3600,
            "expires_at": time.time() + 3600,
        }),
        encoding="utf-8",
    )


def test_acquire_reclaims_unexpired_lock_from_dead_same_host_pid(
    tmp_path, monkeypatch,
):
    lock = HilFileLock("transport_usb-serial_TEST", root=tmp_path)
    _write_holder(lock, hostname=socket.gethostname(), pid=12345)
    monkeypatch.setattr("mklink.local_resources._pid_exists", lambda _pid: False)

    lock.acquire()

    holder = json.loads(lock.path.read_text(encoding="utf-8"))
    assert holder["owner_id"] == lock.owner_id
    assert lock.release() is True


@pytest.mark.parametrize(
    ("hostname", "owner_alive"),
    [(socket.gethostname(), True), ("another-host", False)],
)
def test_acquire_keeps_unexpired_lock_when_owner_may_still_be_valid(
    tmp_path, monkeypatch, hostname, owner_alive,
):
    lock = HilFileLock("transport_usb-serial_TEST", root=tmp_path)
    _write_holder(lock, hostname=hostname, pid=12345)
    monkeypatch.setattr(
        "mklink.local_resources._pid_exists", lambda _pid: owner_alive,
    )

    with pytest.raises(HilLockHeld):
        lock.acquire()
