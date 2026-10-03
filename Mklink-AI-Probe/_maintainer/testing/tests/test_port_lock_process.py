"""Real process locks, with different runtime registries and temporary directories."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from mklink.local_resources import local_resource_status, release_serial_resources, serial_lock_path
from mklink.serial._port import _PortLock


OWNER = '''
import json, sys
from pathlib import Path
from mklink.serial._port import _PortLock
lock = _PortLock('COM901')
assert lock.acquire()
Path(sys.argv[1]).write_text(json.dumps({'path': lock._path}), encoding='utf-8')
try:
    sys.stdin.readline()
finally:
    lock.release()
'''


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv('MKLINK_LOCK_DIR', str(tmp_path / 'locks'))
    monkeypatch.setenv('TEMP', str(tmp_path / 'client-temp'))
    env = dict(os.environ, TEMP=str(tmp_path / 'backend-temp'),
               MKLINK_RUNTIME_DIR=str(tmp_path / 'backend-registry'))
    ready = tmp_path / 'ready.json'
    process = subprocess.Popen([sys.executable, '-c', OWNER, str(ready)], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists(), 'Lock owner did not start'
        yield process, json.loads(ready.read_text(encoding='utf-8'))
    finally:
        if process.poll() is None:
            process.communicate('\n', timeout=10)
        else:
            process.communicate(timeout=10)


@pytest.mark.parametrize('adapter', ['mklink.serial._port', 'mklink.modbus._client'])
def test_same_port_excluded_across_adapters_and_temp_directories(owner, adapter):
    process, info = owner
    assert info['path'] == serial_lock_path('com901')
    code = f'''from {adapter} import _PortLock
same, other = _PortLock('com901'), _PortLock('COM902')
assert not same.acquire(), 'same physical port acquired twice'
assert other.acquire(), 'independent port blocked'
other.release()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert process.poll() is None


def test_status_and_nonforce_cleanup_preserve_live_owner(owner):
    process, _ = owner
    status = local_resource_status('COM901')['serial_locks'][0]
    assert status['owner_pid'] == process.pid and status['owner_alive']
    result = release_serial_resources(port='COM901')
    assert result['serial_locks'][0]['action'] == 'live_owner'
    assert process.poll() is None
    duplicate = _PortLock('COM901')
    assert not duplicate.acquire()


@pytest.mark.parametrize('crash', [False, True])
def test_process_exit_releases_lock_without_deleting_registry(owner, crash):
    process, info = owner
    if crash:
        process.kill()
    process.communicate('\n' if not crash else None, timeout=10)
    lock = _PortLock('COM901')
    try:
        assert lock.acquire()
        assert local_resource_status('COM901')['serial_locks'][0]['owner_pid'] == os.getpid()
    finally:
        lock.release()
    assert Path(info['path']).exists()


def test_default_lock_directory_ignores_temp_and_runtime_override(tmp_path, monkeypatch):
    monkeypatch.delenv('MKLINK_LOCK_DIR', raising=False)
    monkeypatch.setattr('mklink.web_entry.platform_data_dir', lambda: tmp_path / 'web-entry')
    monkeypatch.setenv('TEMP', str(tmp_path / 'first-temp'))
    first = serial_lock_path('COM901')
    monkeypatch.setenv('TEMP', str(tmp_path / 'second-temp'))
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path / 'runtime'))
    assert serial_lock_path('COM901') == first
    assert Path(first).is_relative_to(tmp_path / 'locks')


def test_cleanup_cannot_unlink_live_lock_when_pid_metadata_is_missing(owner):
    process, info = owner
    path = Path(info['path'])
    with path.open('r+b') as handle:
        handle.seek(1)
        handle.truncate()  # Simulate interrupted metadata publication.
    before = path.stat().st_ino
    result = release_serial_resources(port='COM901')
    assert result['serial_locks'][0]['action'] == 'locked_or_unavailable'
    assert path.stat().st_ino == before and process.poll() is None
    duplicate = _PortLock('COM901')
    assert not duplicate.acquire()


def test_stale_cleanup_preserves_inode_and_reacquisition(owner):
    process, info = owner
    process.kill()
    process.communicate(timeout=10)
    path = Path(info['path'])
    before = path.stat().st_ino
    result = release_serial_resources(port='COM901')
    assert result['serial_locks'][0]['action'] == 'cleared_stale_lock'
    assert path.stat().st_ino == before
    assert local_resource_status('COM901')['serial_locks'][0]['owner_pid'] == 0
    lock = _PortLock('COM901')
    try:
        assert lock.acquire()
    finally:
        lock.release()


def test_force_cleanup_terminates_only_the_test_owner_and_retains_lock(owner):
    process, info = owner
    result = release_serial_resources(port='COM901', force=True)
    assert result['serial_locks'][0]['action'] == 'terminated_owner'
    process.wait(timeout=10)
    assert Path(info['path']).exists()
    assert local_resource_status('COM901')['serial_locks'][0]['owner_pid'] == 0


def test_resource_cleanup_has_no_legacy_temp_lock_path(tmp_path, monkeypatch):
    monkeypatch.setenv('TEMP', str(tmp_path))
    legacy = tmp_path / 'mklink_serial_lock'
    legacy.write_text('99999999', encoding='utf-8')
    status = local_resource_status()
    assert set(status) == {'port', 'serial_locks'}
    result = release_serial_resources()
    assert set(result) == {'port', 'force', 'serial_locks'}
    assert legacy.read_text(encoding='utf-8') == '99999999'
