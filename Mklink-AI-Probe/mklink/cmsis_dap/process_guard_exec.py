"""Linux exec wrapper that applies a parent-death signal without preexec_fn."""

import ctypes
import os
import signal
import sys


def main() -> int:
    if len(sys.argv) < 4:
        return 2
    expected_parent = int(sys.argv[1])
    executable = sys.argv[2]
    arguments = sys.argv[2:]
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != expected_parent:
        os.kill(os.getpid(), signal.SIGKILL)
    os.execv(executable, arguments)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
