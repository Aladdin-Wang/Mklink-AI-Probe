"""Local resource operations for CLI/skill use without FastAPI.

This module deals with process/file locks used by the local mklink tools.  It
does not require a running REST server; FastAPI can call into this layer when it
needs the same cleanup behavior for dashboard flows.
"""

from __future__ import annotations

import glob
import os
import re
import signal
import subprocess
import time
import threading
from typing import Any


def port_lock_dir() -> str:
    """One per-user namespace, independent of process scratch/runtime directories.

    MKLINK_LOCK_DIR is for explicitly isolated tests/deployments; every process
    accessing the same ports must share it. It is never derived from TEMP.
    """
    override = os.environ.get('MKLINK_LOCK_DIR')
    if override:
        return os.path.abspath(override)
    from mklink.web_entry import platform_data_dir
    return str(platform_data_dir().parent / 'locks')


def _safe_port_name(port: str) -> str:
    from mklink.usb_interfaces import canonical_serial_port
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", canonical_serial_port(port).upper())


def serial_lock_path(port: str) -> str:
    lock_dir = port_lock_dir()
    return os.path.join(lock_dir, f"serial_{_safe_port_name(port)}.lock")


def serial_lock_paths(port: str | None = None) -> list[str]:
    if port:
        return [serial_lock_path(port)]
    lock_dir = port_lock_dir()
    return sorted(glob.glob(os.path.join(lock_dir, "serial_*.lock")))


# ---------------------------------------------------------------------------
# Shared cross-process lock for CMD, UART and Modbus ports
# ---------------------------------------------------------------------------
class _PortLock:
    """Cross-process advisory lock for one serial port."""

    _guard = threading.Lock()

    def __init__(self, port: str):
        self._path = serial_lock_path(port)
        self._fd = None
        self._locked = False

    @classmethod
    def from_path(cls, path: str):
        """Use an enumerated registry path for conservative resource cleanup."""
        lock = cls.__new__(cls)
        lock._path, lock._fd, lock._locked = path, None, False
        return lock

    def acquire(self) -> bool:
        if self._locked:
            return True
        with self._guard:
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
                self._fd = os.fdopen(fd, "r+b")
                if os.fstat(fd).st_size == 0:
                    self._fd.write(b"\0")
                    self._fd.flush()
                self._fd.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Keep the lock byte intact, and PID outside the locked range.
                self._write_owner(os.getpid())
            except OSError:
                if self._fd is not None:
                    self._fd.close()  # Also releases any acquired OS lock.
                self._fd = None
                return False
            self._locked = True
            return True

    def _write_owner(self, pid: int) -> None:
        self._fd.seek(1)
        self._fd.truncate()
        self._fd.write(str(pid).encode('ascii'))
        self._fd.flush()

    def release(self) -> None:
        if not self._locked or self._fd is None:
            return
        try:
            self._write_owner(0)
        finally:
            # Closing the descriptor releases the OS lock, even if metadata
            # cleanup fails. Keep the file so all waiters lock the same inode.
            self._fd.close()
            self._fd = None
            self._locked = False


def _read_owner_pid(path: str) -> int | None:
    try:
        with open(path, "rb") as f:
            # Byte zero is OS-locked on Windows. Metadata must be readable
            # without touching that byte, including from another process.
            f.seek(1)
            raw = f.read(32).decode('ascii', errors='ignore').strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _pid_exists(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            # OpenProcess alone is not proof that a process is still running:
            # Windows can keep a terminated process object alive while another
            # handle references it.  Query the exit code so stale serial-lock
            # owners are not reported as live indefinitely.
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            get_exit_code = kernel32.GetExitCodeProcess
            get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            get_exit_code.restype = wintypes.BOOL
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL

            process_query_limited_information = 0x1000
            error_invalid_parameter = 87
            still_active = 259
            handle = open_process(process_query_limited_information, False, pid)
            if not handle:
                # ERROR_INVALID_PARAMETER is the documented result for a PID
                # that no longer identifies a process.  Access-denied and
                # unknown failures stay conservative so a live owner's lock is
                # never removed merely because it cannot be inspected.
                return ctypes.get_last_error() != error_invalid_parameter
            try:
                exit_code = wintypes.DWORD()
                if not get_exit_code(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == still_active
            finally:
                close_handle(handle)
        except Exception:
            # Failure to inspect is not proof of death.  Keep the lock rather
            # than risking concurrent access to a live serial owner.
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        return False

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return True
        time.sleep(0.05)
    return not _pid_exists(pid)


def _cleanup_port_lock(path: str, *, force: bool) -> dict[str, Any]:
    """Clear metadata only after acquiring the same OS lock; never unlink it.

    Unlinking a POSIX lock file can create two independently locked inodes.
    A PID is diagnostic metadata, not proof that the OS lock is available.
    """
    info = _inspect_lock_file(path)
    info['action'] = 'missing'
    if not info['exists']:
        return info
    owner, alive = info['owner_pid'], info['owner_alive']
    terminated = False
    if alive:
        if not force or owner == os.getpid():
            info['action'] = 'live_owner'
            return info
        terminated = _terminate_pid(owner)
        if not terminated:
            info['action'] = 'terminate_failed'
            return info
        info['owner_alive'] = False
    lock = _PortLock.from_path(info['path'])
    if not lock.acquire():
        info['action'] = 'locked_or_unavailable'
        return info
    lock.release()
    info['action'] = 'terminated_owner' if terminated else 'cleared_stale_lock'
    return info


def _inspect_lock_file(path: str) -> dict[str, Any]:
    owner_pid = _read_owner_pid(path) if os.path.exists(path) else None
    owner_alive = _pid_exists(owner_pid)
    return {
        "resource": "serial_port",
        "path": path,
        "exists": os.path.exists(path),
        "owner_pid": owner_pid,
        "owner_alive": owner_alive,
    }


def local_resource_status(port: str | None = None) -> dict[str, Any]:
    """Inspect local lock files without requiring FastAPI."""
    return {
        "port": port,
        "serial_locks": [
            _inspect_lock_file(path)
            for path in serial_lock_paths(port)
        ],
    }


def release_serial_resources(
    *,
    port: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Release local serial resources without starting FastAPI.

    Default behavior is conservative: stale port metadata is cleared, but live
    owner processes are reported rather than killed.  Use ``force=True`` only
    when the caller explicitly wants to terminate the owner process. Current
    port lock files are retained to preserve the OS lock identity.
    """
    return {
        "port": port,
        "force": force,
        "serial_locks": [
            _cleanup_port_lock(path, force=force)
            for path in serial_lock_paths(port)
        ],
    }
