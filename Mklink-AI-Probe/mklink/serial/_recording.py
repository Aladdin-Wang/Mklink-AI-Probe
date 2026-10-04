"""One bounded-history file consumer; never owns or reads a serial handle."""
import threading
import time

from mklink.serial._capture import SerialCapture
from mklink.serial._logger import FileLogger


class SerialRecorder:
    """Single-use recorder. Its owner serializes start/stop and retains live workers.

    read_history must not acquire the owner's lifecycle lock: stop joins this
    worker while holding that lock. Stop producers before stop() to include
    their final batches; stopping recording alone takes a bounded history tail.
    """

    def __init__(self, read_history, parsers, path, format='txt', max_size=0):
        self._logger = FileLogger(path, format, max_size)
        self._capture = SerialCapture(read_history, parsers, self._logger)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name='serial-recording', daemon=True)
        self._status = dict(state='idle', path=str(path), format=format, max_size=max_size,
                            ports=list(parsers), session=self._capture.session,
                            started_at=None, stopped_at=None, error='')

    @property
    def worker_alive(self):
        return self._thread.is_alive()

    def status(self):
        with self._lock:
            return dict(self._status, ports=list(self._status['ports']), active=self.worker_alive)

    def start(self):
        with self._lock:
            if self._status['state'] != 'idle':
                raise RuntimeError('Recording has already been started')
            self._status.update(state='starting', started_at=time.time())
        try:
            # Across independent backends, an existing output must never be truncated.
            self._logger.start(exclusive=True)
            with self._lock:
                self._status['state'] = 'running'
            self._thread.start()
        except Exception as error:
            try:
                self._logger.close()
            finally:
                with self._lock:
                    self._status.update(state='failed', error=str(error), stopped_at=time.time())
            raise

    def stop(self, timeout=2.0):
        with self._lock:
            if self.worker_alive and self._status['state'] in ('starting', 'running'):
                self._status['state'] = 'stopping'
        self._cancel.set()
        if self._thread.ident is not None:
            self._thread.join(timeout)
        if self.worker_alive:
            raise TimeoutError('Recording is still draining; retry stop before restarting')
        return self.status()

    def _run(self):
        error = ''
        try:
            # The owner, not a transient port snapshot, defines the producer's end.
            while not self._cancel.is_set():
                page = self._capture.page()
                if self._capture.cursor >= page['latest_seq']:
                    self._cancel.wait(.02)
            self._capture.drain()
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        finally:
            try:
                self._logger.close()
            except Exception as exc:
                detail = str(exc) or type(exc).__name__
                error = f'{error}; close: {detail}' if error else detail
            with self._lock:
                self._status.update(state='failed' if error else 'completed', error=error,
                                    stopped_at=time.time())
