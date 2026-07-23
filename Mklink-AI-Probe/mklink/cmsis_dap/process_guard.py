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
_PARENT_JOB_ENV = "MKLINK_PARENT_JOB_BREAKAWAY_OK"
_KILL_ON_JOB_CLOSE = 0x00002000
_BREAKAWAY_OK = 0x00000800
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def _current_job_limit_flags() -> int:
    if os.name != "nt":
        return 0
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
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.IsProcessInJob.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.BOOL),
    ]
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    process = kernel32.GetCurrentProcess()
    in_job = wintypes.BOOL()
    if not kernel32.IsProcessInJob(process, None, ctypes.byref(in_job)):
        return 0
    if not in_job.value:
        return 0
    limits = ExtendedLimitInformation()
    if not kernel32.QueryInformationJobObject(
        None,
        9,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
        None,
    ):
        return 0
    return int(limits.BasicLimitInformation.LimitFlags)


def guarded_process_command(command: Sequence[str]) -> List[str]:
    values = [str(value) for value in command]
    if getattr(sys, "frozen", False):
        return [
            sys.executable,
            "--internal-process-guard",
            str(os.getpid()),
        ] + values
    if os.name == "nt":
        # Python 3.13+ venv launchers may proxy through another process, which
        # changes the wrapper's parent PID. Run the stdlib-only guard script
        # with the base interpreter so Popen owns the process we attach.
        interpreter = getattr(sys, "_base_executable", None) or sys.executable
        guard_script = os.path.join(
            os.path.dirname(__file__), "process_guard_exec.py"
        )
        return [interpreter, guard_script, str(os.getpid())] + values
    return [
        sys.executable,
        "-m",
        "mklink.cmsis_dap.process_guard_exec",
        str(os.getpid()),
    ] + values


def guarded_process_creationflags() -> int:
    if os.name != "nt" or os.environ.get(_PARENT_JOB_ENV) != "1":
        return 0
    required = _KILL_ON_JOB_CLOSE | _BREAKAWAY_OK
    if _current_job_limit_flags() & required != required:
        return 0
    return _CREATE_BREAKAWAY_FROM_JOB


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
