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
        allowed = {'start': {'addr', 'channel', 'channels', 'mode', 'search_size', 'encoding'},
                   'read': {'timeout'}, 'read_channel': {'channel', 'cursor'},
                   'write': {'data', 'data_hex', 'channel'}, 'stop': set()}[action]
        if params.keys()-allowed:
            raise RequestValidationError('Unsupported RTT parameters')
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
        if action == 'read_channel':
            channel, cursor = params.get('channel', 0), params.get('cursor', 0)
            if type(channel) is not int or not 0 <= channel <= 7 or type(cursor) is not int or cursor < 0:
                raise RequestValidationError('channel must be 0..7 and cursor a nonnegative integer')
            result = self.client.call('rtt_read_channel', {
                'channel': channel, 'cursor': cursor, 'session': self.session})
            self._status()
            return result
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
        channel = params.get('channel')
        if channel is not None and (type(channel) is not int or not 0 <= channel <= 7):
            raise RequestValidationError('channel must be 0..7')
        if ('data' in params) == ('data_hex' in params):
            raise RequestValidationError('Supply exactly one of data or data_hex')
        data = params.get('data')
        try:
            if 'data_hex' in params:
                value = params['data_hex']
                if (not isinstance(value, str) or not 2 <= len(value) <= 512 or len(value) % 2
                        or any(c not in '0123456789abcdefABCDEF' for c in value)):
                    raise ValueError('Invalid HEX')
                encoded = bytes.fromhex(value)
            else:
                encoded = data.encode('utf-8') if isinstance(data, str) else b''
        except ValueError:
            encoded = b''
        if not 1 <= len(encoded) <= 256:
            raise RequestValidationError('RTT write requires 1..256 bytes')
        arguments = {'data_hex': encoded.hex()}
        if channel is not None:
            arguments['channel'] = channel
        return self.client.call('rtt_write', arguments)

    def _close_reader(self):
        reader, self.reader = self.reader, None
        if reader is not None:
            reader.close()

    def close(self):
        try:
            self._close_reader()
        finally:
            super().close()
