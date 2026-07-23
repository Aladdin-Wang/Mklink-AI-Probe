"""Exec wrapper that coordinates parent-death protection before startup."""

import ctypes
import os
import signal
import subprocess
import sys


_GO_TOKEN = "MKLINK-PROCESS-GUARD-GO\n"
_READY_TOKEN = "MKLINK-PROCESS-GUARD-READY\n"


def main() -> int:
    if len(sys.argv) < 4:
        return 2
    expected_parent = int(sys.argv[1])
    executable = sys.argv[2]
    arguments = sys.argv[2:]
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        if os.getppid() != expected_parent:
            os.kill(os.getpid(), signal.SIGKILL)
    if sys.stdin.readline() != _GO_TOKEN:
        return 3
    if os.getppid() != expected_parent:
        return 4
    sys.stdout.write(_READY_TOKEN)
    sys.stdout.flush()
    if os.name == "nt":
        child = subprocess.Popen(
            arguments,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        return child.wait()
    os.execv(executable, arguments)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
