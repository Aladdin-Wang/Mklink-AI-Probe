"""Per-remote-client subscriptions to the existing shared SystemView capture."""
from __future__ import annotations

from mklink.remote.protocol import RequestValidationError
from mklink.remote.shared_capture import SharedCapture


class SharedSystemView(SharedCapture):
    def __init__(self, info, project_root, client_id):
        super().__init__('systemview', info, project_root, client_id)
        self.session = None
        self.after = 0

    def dispatch(self, operation, params):
        action = operation.split('.')[1]
        allowed = {
            'start': {'addr', 'channel', 'mode', 'search_size'},
            'read': {'session', 'after', 'limit'},
            'stop': set(), 'resolve_task_names': {'task_ids'},
        }[action]
        if params.keys() - allowed:
            raise RequestValidationError('Unsupported SystemView v2 parameters; reads use session/after/limit, not duration')
        if action == 'start':
            arguments = {k: v for k, v in params.items() if v is not None}
            started = self.start_capture(arguments)
            if self.session is None:
                cursor = self.client.call('systemview_capture_history')
                self.session = cursor['session']
                self.after = 0 if self.owned else cursor['next_seq']
            else:
                self.client.call('systemview_capture_history', {'session': self.session, 'after': self.after, 'limit': 1})
            return {**started, 'session': self.session, 'after': self.after}
        self.require_started()
        if action == 'stop':
            try:
                return self.stop_capture()
            finally:
                if not self.started:
                    self.session = None
        if self.session is None:
            raise RequestValidationError('History initialization failed; stop or close this subscription')
        if action == 'read':
            if ('session' in params) != ('after' in params):
                raise RequestValidationError('Continuation requires both session and after')
            session = params.get('session', self.session)
            after = params.get('after', self.after)
            limit = params.get('limit', 500)
            if session != self.session or type(after) is not int or after < 0:
                raise RequestValidationError('Invalid subscription cursor')
            if type(limit) is not int or not 1 <= limit <= 500:
                raise RequestValidationError('limit must be an integer in 1..500')
            status = self.client.call('systemview_status')
            page = self.client.call('systemview_capture_history', {'session': session, 'after': after, 'limit': limit})
            self.after = page['next_seq']
            return {**page, 'capture': {key: status.get(key) for key in (
                'running', 'paused', 'synced', 'cpu_freq', 'stats', 'progress_state',
                'progress_error', 'dropped_bytes', 'dropped_packets',
                'target_overflow_events', 'target_dropped_packets_since_baseline')}}
        task_ids = params.get('task_ids')
        if (not isinstance(task_ids, list) or len(task_ids) > 256
                or any(type(value) is not int or not 0 <= value <= 0xffffffff for value in task_ids)):
            raise RequestValidationError('task_ids must contain at most 256 unsigned 32-bit integers')
        # Check capture identity without advancing this client's cursor.
        self.client.call('systemview_capture_history', {'session': self.session, 'after': self.after, 'limit': 1})
        status = self.client.call('systemview_status')
        names = status.get('task_names', {})
        resolved = {str(value): names.get(str(value), names.get(value)) for value in task_ids}
        return {'source': 'capture_cache', 'task_names': {k: v for k, v in resolved.items() if v},
                'unresolved': [value for value in task_ids if not resolved[str(value)]]}
