"""Hostile black-box contracts for opaque, atomic remote upload sessions."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import threading
from pathlib import Path

import pytest

from mklink.remote.transfer import (
    TransferIntegrityError,
    TransferLimitError,
    TransferLimits,
    TransferStateError,
    UploadManager,
)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _windows_acl(path: Path) -> dict:
    environment = os.environ.copy()
    environment["MKLINK_TEST_ACL_PATH"] = str(path)
    script = r"""
$ErrorActionPreference = "Stop"
$acl = Get-Acl -LiteralPath $env:MKLINK_TEST_ACL_PATH
$sidType = [System.Security.Principal.SecurityIdentifier]
$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$ownerSid = ([System.Security.Principal.NTAccount]$acl.Owner).Translate($sidType).Value
$rules = @(
    $acl.GetAccessRules($true, $true, $sidType) | ForEach-Object {
        [pscustomobject]@{
            Identity = $_.IdentityReference.Value
            Type = $_.AccessControlType.ToString()
            Rights = [int64]$_.FileSystemRights
            Inherited = [bool]$_.IsInherited
            Inheritance = $_.InheritanceFlags.ToString()
            Propagation = $_.PropagationFlags.ToString()
        }
    }
)
[pscustomobject]@{
    CurrentSid = $currentSid
    OwnerSid = $ownerSid
    Protected = [bool]$acl.AreAccessRulesProtected
    Rules = @($rules)
} | ConvertTo-Json -Depth 4 -Compress
"""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    assert completed.returncode == 0, (
        f"independent Windows ACL inspection failed: {completed.stderr.strip()}"
    )
    return json.loads(completed.stdout)


def _assert_restrictive(path, *, directory=False):
    path = Path(path)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if directory else 0o600)
        return

    acl = _windows_acl(path)
    assert acl["Protected"] is True, "DACL inheritance must be disabled"
    assert acl["OwnerSid"] == acl["CurrentSid"], "current identity must own the path"
    rules = acl["Rules"]
    if isinstance(rules, dict):
        rules = [rules]
    assert len(rules) == 1, "only one explicit current-identity ACE is allowed"
    rule = rules[0]
    assert rule["Identity"] == acl["CurrentSid"], (
        "the current identity must be the only allowed principal"
    )
    assert rule["Type"] == "Allow"
    assert rule["Inherited"] is False
    assert int(rule["Rights"]) & 0x001F01FF == 0x001F01FF, (
        "the current identity must have full required access"
    )
    inheritance = {
        item.strip() for item in rule["Inheritance"].split(",") if item.strip()
    }
    if directory:
        assert inheritance == {"ContainerInherit", "ObjectInherit"}, (
            "directory ACE must propagate to child files and directories"
        )
    else:
        assert inheritance in (set(), {"None"}), (
            "file ACE must not carry child-inheritance flags"
        )
    assert rule["Propagation"] == "None"


@pytest.mark.parametrize("filename", ["../escape.bin", "dir/file.bin", "dir\\file.bin", "", ".", "..", "bad\x00.bin"])
def test_upload_rejects_client_path_traversal_and_non_basename_names(tmp_path, filename):
    manager = UploadManager(tmp_path / "uploads")
    with pytest.raises(TransferStateError):
        manager.open(filename, 1)


def test_upload_rejects_client_destination_resume_and_quota_overcommit(tmp_path):
    manager = UploadManager(tmp_path / "uploads", limits=TransferLimits(
        max_file_bytes=8, max_total_bytes=10, max_chunk_bytes=4, max_active_sessions=2,
        idle_timeout_seconds=10,
    ))
    with pytest.raises(TransferStateError):
        manager.open("a.bin", 1, destination="C:/outside")
    with pytest.raises(TransferStateError):
        manager.open("a.bin", 1, resume=True)
    manager.open("a.bin", 8)
    with pytest.raises(TransferLimitError):
        manager.open("b.bin", 3)


def test_expiry_disconnect_cleanup_and_abort_remove_unpublished_parts(tmp_path):
    now = [100.0]
    manager = UploadManager(
        tmp_path / "uploads",
        limits=TransferLimits(max_file_bytes=16, max_total_bytes=16, max_chunk_bytes=8,
                              max_active_sessions=2, idle_timeout_seconds=5),
        clock=lambda: now[0],
    )
    session = manager.open("expired.bin", 2)["session_id"]
    now[0] = 105.0
    with pytest.raises(TransferStateError, match="expired"):
        manager.chunk(session, 0, 0, b"ok")
    assert list((tmp_path / "uploads" / "pending").iterdir()) == []

    session = manager.open("disconnect.bin", 2)["session_id"]
    assert manager.abort(session) is True
    assert manager.abort(session) is False
    manager.open("close.bin", 2)
    manager.close()
    assert list((tmp_path / "uploads" / "pending").iterdir()) == []
    assert list((tmp_path / "uploads" / "files").iterdir()) == []


def test_duplicate_out_of_order_offset_and_resume_attempts_are_rejected(tmp_path):
    manager = UploadManager(tmp_path / "uploads", limits=TransferLimits(
        max_file_bytes=16, max_total_bytes=16, max_chunk_bytes=8, max_active_sessions=2,
        idle_timeout_seconds=10,
    ))
    session = manager.open("ordered.bin", 4)["session_id"]
    assert manager.chunk(session, 0, 0, b"ab")["offset"] == 2
    for offset, sequence, resume in ((0, 0, False), (2, 0, False), (3, 1, False), (2, 1, True)):
        with pytest.raises(TransferStateError):
            manager.chunk(session, offset, sequence, b"cd", resume=resume)
    assert manager.chunk(session, 2, 1, b"cd")["offset"] == 4


def test_size_and_sha_failures_never_become_visible_and_clean_up(tmp_path):
    root = tmp_path / "uploads"
    manager = UploadManager(root, limits=TransferLimits(
        max_file_bytes=16, max_total_bytes=16, max_chunk_bytes=8, max_active_sessions=2,
        idle_timeout_seconds=10,
    ))
    session = manager.open("tampered.bin", 3)["session_id"]
    manager.chunk(session, 0, 0, b"abc")
    with pytest.raises(TransferIntegrityError, match="SHA"):
        manager.finalize(session, 3, _digest(b"other"))
    assert list((root / "pending").iterdir()) == []
    assert list((root / "files").iterdir()) == []

    session = manager.open("wrong-size.bin", 3)["session_id"]
    manager.chunk(session, 0, 0, b"abc")
    with pytest.raises(TransferIntegrityError, match="size"):
        manager.finalize(session, 2, _digest(b"abc"))
    assert list((root / "pending").iterdir()) == []


def test_same_name_concurrent_uploads_are_isolated_atomically_visible_and_restrictive(tmp_path):
    root = tmp_path / "uploads"
    manager = UploadManager(root, limits=TransferLimits(
        max_file_bytes=16, max_total_bytes=32, max_chunk_bytes=8, max_active_sessions=4,
        idle_timeout_seconds=10,
    ))
    first = manager.open("same.bin", 3)["session_id"]
    second = manager.open("same.bin", 3)["session_id"]
    manager.chunk(first, 0, 0, b"one")
    manager.chunk(second, 0, 0, b"two")
    assert list((root / "files").iterdir()) == [], "partial data became externally visible"
    results = []

    def finalize(session, data):
        results.append(manager.finalize(session, len(data), _digest(data)))

    threads = [
        threading.Thread(target=finalize, args=(first, b"one")),
        threading.Thread(target=finalize, args=(second, b"two")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert {result.name for result in results} == {"same.bin"}
    assert len({result.file_id for result in results}) == 2
    assert {manager.resolve(result).read_bytes() for result in results} == {b"one", b"two"}
    assert list((root / "pending").iterdir()) == []
    for directory in (root, root / "pending", root / "files"):
        _assert_restrictive(directory, directory=True)
    for result in results:
        _assert_restrictive(manager.resolve(result))
