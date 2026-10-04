"""Shared capture ownership for remote subscriptions; no device transport here."""
import logging

from mklink.remote.protocol import RequestValidationError
from mklink.runtime import RuntimeClient, RuntimeErrorResponse


class SharedCapture:
    def __init__(self, stream, info, project_root, client_id):
        self.stream = stream
        self.client = RuntimeClient(info=info, project_root=project_root,
                                    kind='sdk', name=f'Agent {stream} '+client_id[:32])
        self.started = False
        self.owned = False
        self.uncertain = False

    def start_capture(self, arguments):
        if self.uncertain:
            raise RequestValidationError('Previous start/stop outcome is unknown; reconnect this remote client')
        if self.started:
            if arguments:
                raise RequestValidationError('Already subscribed; stop before reconfiguring')
            return {'reused': not self.owned}
        self.client.connect()
        self.uncertain = True
        try:
            result = self.client.call(self.stream+'_start', arguments)
        except RuntimeErrorResponse as exc:
            self.uncertain = exc.status_code is None or exc.status_code >= 500
            raise
        self.owned = not result.get('reused', False)
        self.started = True
        self.uncertain = False
        return {**result, 'reused': not self.owned}

    def require_started(self):
        if not self.started:
            raise RequestValidationError(f'Call {self.stream}.start first')

    def stop_capture(self):
        self.require_started()
        if self.owned:
            try:
                self.client.call(self.stream+'_stop')
            except RuntimeErrorResponse as exc:
                if exc.status_code is None or exc.status_code >= 500:
                    self.owned = False  # A lost response must not cause cleanup to replay.
                    self.uncertain = True
                raise
        stopped = None if self.uncertain else self.owned
        self.started = self.owned = False
        self.client.close()
        return {'subscribed': False, 'capture_stopped': stopped}

    def close(self):
        try:
            if self.owned:
                try:
                    self.client.call(self.stream+'_stop')
                except RuntimeErrorResponse:
                    logging.getLogger(__name__).warning('%s left running or stop unconfirmed; detaching remote subscriber', self.stream)
        finally:
            self.started = self.owned = False
            self.client.close()
