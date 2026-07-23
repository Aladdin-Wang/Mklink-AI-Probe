"""A minimal single-worker executor whose worker never blocks process exit."""

from __future__ import annotations

from concurrent.futures import Future
import queue
import threading
from typing import Callable


_STOP = object()


class DaemonSingleExecutor:
    """Future-compatible executor backed by one daemon worker thread.

    Normal ``shutdown(wait=True)`` remains graceful. The daemon flag only
    provides process-exit degradation when native backend code never returns.
    """

    def __init__(self, thread_name: str = "mklink-online-flash") -> None:
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._shutdown = False
        self._stop_queued = False
        self._thread = threading.Thread(
            target=self._worker,
            name=thread_name,
            daemon=True,
        )
        self._thread.start()

    def submit(self, function: Callable, *args, **kwargs) -> Future:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("cannot schedule new futures after shutdown")
            future = Future()
            self._queue.put((future, function, args, kwargs))
            return future

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        with self._lock:
            self._shutdown = True
            if cancel_futures:
                self._cancel_queued_locked()
            if not self._stop_queued:
                self._queue.put(_STOP)
                self._stop_queued = True
        if wait:
            self._thread.join()

    def _cancel_queued_locked(self) -> None:
        retained = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _STOP:
                retained.append(item)
            else:
                item[0].cancel()
        for item in retained:
            self._queue.put(item)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            future, function, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(function(*args, **kwargs))
            except BaseException as error:
                future.set_exception(error)
