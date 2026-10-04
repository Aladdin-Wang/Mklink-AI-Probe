"""RTT remote operations consume the shared terminal stream, never the Device."""
import math

from mklink.remote.protocol import AgentOperationError, RequestValidationError
from mklink.remote.shared_capture import SharedCapture
from mklink.remote.rtt_subscription import RttSubscription


class SharedRtt(SharedCapture):
    def __init__(self, info, project_root, client_id):
        super().__init__('rtt', info, project_root, client_id)
        self.reader = None
        self.session = None

    def _status(self):
        status = self.client.call('rtt_status')
        if not self.session or status.get('session') != self.session:
            raise AgentOperationError('RTT capture changed; stop and start this subscription explicitly')
        return status

    def dispatch(self, operation, params):
        action = operation.split('.')[1]
        allowed = {'start': {'addr', 'channel', 'mode', 'search_size', 'encoding'},
                   'read': {'timeout'}, 'write': {'data'}, 'stop': set()}[action]
        if params.keys()-allowed:
            raise RequestValidationError('Unsupported RTT v2 parameters; read accepts timeout in 0..5 seconds')
        if action == 'start':
            new_reader = self.reader is None
            if new_reader:
                self.reader = RttSubscription(self.client.info)
            try:
                result = self.start_capture({k: v for k, v in params.items() if v is not None})
                status = self.client.call('rtt_status')
                if self.session is not None and status.get('session') != self.session:
                    raise AgentOperationError('RTT capture changed; stop before subscribing again')
                self.session = status.get('session')
                if not self.session:
                    raise AgentOperationError('Shared runtime lacks RTT capture identity; restart the backend')
                return {**result, 'session': self.session}
            except Exception:
                if new_reader:
                    self._close_reader()
                raise
        self.require_started()
        if action == 'stop':
            try:
                return self.stop_capture()
            finally:
                if not self.started:
                    self._close_reader()
                    self.session = None
        status = self._status()
        if action == 'read':
            timeout = params.get('timeout', 1)
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 5:
                raise RequestValidationError('timeout must be finite and in 0..5 seconds')
            if self.reader is None:
                raise AgentOperationError('RTT subscription failed; stop before restarting')
            result = self.reader.read(timeout)
            status = self._status()  # Reject mixed data if capture changed during the wait.
            return {**result, 'session': self.session,
                    'capture': {k: status.get(k) for k in ('running', 'paused', 'error', 'encoding', 'line_parser')}}
        data = params.get('data')
        try:
            encoded = data.encode('utf-8') if isinstance(data, str) else b''
        except UnicodeError:
            encoded = b''
        if not 1 <= len(encoded) <= 256:
            raise RequestValidationError('RTT write requires 1..256 UTF-8 bytes')
        return self.client.call('rtt_write', {'data_hex': encoded.hex()})

    def _close_reader(self):
        reader, self.reader = self.reader, None
        if reader is not None:
            reader.close()

    def close(self):
        try:
            self._close_reader()
        finally:
            super().close()
