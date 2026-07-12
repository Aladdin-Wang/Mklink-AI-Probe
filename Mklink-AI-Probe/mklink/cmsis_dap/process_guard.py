"""Ensure pack worker subprocesses cannot outlive their parent process."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import List, Sequence


class _NullGuard:
    def close(self) -> None:
        return None


_GO_TOKEN = "MKLINK-PROCESS-GUARD-GO\n"
_READY_TOKEN = "MKLINK-PROCESS-GUARD-READY\n"
_REAL_POPEN = subprocess.Popen


def guarded_process_command(command: Sequence[str]) -> List[str]:
    values = [str(value) for value in command]
    return [
        sys.executable,
        "-m",
        "mklink.cmsis_dap.process_guard_exec",
        str(os.getpid()),
    ] + values


def attach_parent_death_guard(process):
    if os.name != "nt":
        return _NullGuard()
    if not isinstance(process, _REAL_POPEN):
        return _NullGuard()
    if not hasattr(process, "_handle"):
        raise OSError("Windows process handle is unavailable")
    return _WindowsJobGuard(process)


def attach_and_release_guarded_process(
    process,
    guard_factory=attach_parent_death_guard,
):
    """Attach parent-death protection, then release a real wrapper to exec."""
    if not isinstance(process, _REAL_POPEN):
        return _NullGuard()
    guard = None
    try:
        guard = guard_factory(process)
        if process.stdin is None:
            raise OSError("guarded process requires a stdin pipe")
        if process.stdout is None:
            raise OSError("guarded process requires a stdout pipe")
        process.stdin.write(_GO_TOKEN)
        process.stdin.flush()
        if process.stdout.readline() != _READY_TOKEN:
            raise OSError("guarded process did not acknowledge GO")
        return guard
    except BaseException:
        if guard is not None:
            guard.close()
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except Exception:
            pass
        raise


class _WindowsJobGuard:
    _KILL_ON_JOB_CLOSE = 0x00002000
    _EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self, process) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._kernel32 = kernel32
        self._handle = handle
        self._close_lock = threading.Lock()
        try:
            limits = ExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = self._KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                handle,
                self._EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel32.AssignProcessToJobObject(handle, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            try:
                process.kill()
                process.wait()
            except Exception:
                pass
            raise

    def close(self) -> None:
        with self._close_lock:
            handle, self._handle = getattr(self, "_handle", None), None
            if handle:
                self._kernel32.CloseHandle(handle)
