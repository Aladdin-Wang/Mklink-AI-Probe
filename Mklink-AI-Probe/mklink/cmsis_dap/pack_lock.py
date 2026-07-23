"""Cross-process, cancellable lock for one managed CMSIS-Pack root."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import threading
import time
from typing import Iterator, Optional

from .errors import FlashError, FlashErrorCode


_POLL_INTERVAL = 0.05
_REGISTRY_GUARD = threading.Lock()
_REGISTRY = {}


class _LockEntry:
    def __init__(self) -> None:
        self.gate = threading.Lock()
        self.owner = None  # type: Optional[int]
        self.depth = 0
        self.handle = None


def _entry(path: Path) -> _LockEntry:
    key = os.path.normcase(str(path.resolve()))
    with _REGISTRY_GUARD:
        entry = _REGISTRY.get(key)
        if entry is None:
            entry = _LockEntry()
            _REGISTRY[key] = entry
        return entry


def _try_os_lock(handle) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (BlockingIOError, OSError):
        return False


def _unlock_os(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class PackRootLock:
    """One re-entrant process lock backed by ``pack.lock`` in the cache root."""

    def __init__(self, root: Path) -> None:
        self.path = Path(root).resolve() / "pack.lock"
        self._entry = _entry(self.path)

    def acquire(
        self,
        *,
        cancel_event: Optional[threading.Event] = None,
        timeout: float = 30.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("pack lock timeout must be positive")
        thread_id = threading.get_ident()
        with _REGISTRY_GUARD:
            if self._entry.owner == thread_id:
                self._entry.depth += 1
                return

        deadline = time.monotonic() + timeout
        while not self._entry.gate.acquire(timeout=_POLL_INTERVAL):
            self._check_wait(cancel_event, deadline)
        handle = None
        acquired = False
        try:
            self._check_wait(cancel_event, deadline)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            while not _try_os_lock(handle):
                self._check_wait(cancel_event, deadline)
                time.sleep(_POLL_INTERVAL)
            with _REGISTRY_GUARD:
                self._entry.owner = thread_id
                self._entry.depth = 1
                self._entry.handle = handle
            acquired = True
            handle = None
        finally:
            if not acquired:
                if handle is not None:
                    handle.close()
                self._entry.gate.release()

    def release(self) -> None:
        thread_id = threading.get_ident()
        with _REGISTRY_GUARD:
            if self._entry.owner != thread_id or self._entry.depth <= 0:
                raise RuntimeError("pack root lock is not owned by this thread")
            self._entry.depth -= 1
            if self._entry.depth:
                return
            handle = self._entry.handle
            self._entry.owner = None
            self._entry.handle = None
        try:
            _unlock_os(handle)
        finally:
            handle.close()
            self._entry.gate.release()

    @staticmethod
    def _check_wait(
        cancel_event: Optional[threading.Event], deadline: float
    ) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise FlashError(FlashErrorCode.USER_ABORT, "pack operation cancelled")
        if time.monotonic() >= deadline:
            raise FlashError(FlashErrorCode.PROBE_BUSY, "pack cache is busy")

    @contextmanager
    def hold(
        self,
        *,
        cancel_event: Optional[threading.Event] = None,
        timeout: float = 30.0,
    ) -> Iterator[None]:
        self.acquire(cancel_event=cancel_event, timeout=timeout)
        try:
            yield
        finally:
            self.release()
