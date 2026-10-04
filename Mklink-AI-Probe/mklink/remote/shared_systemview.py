"""Per-remote-client subscriptions to the existing shared SystemView capture."""
from __future__ import annotations

import logging

from mklink.remote.protocol import RequestValidationError
from mklink.runtime import RuntimeClient, RuntimeErrorResponse


class SharedSystemView:
    def __init__(self, info, project_root, client_id):
        self.client = RuntimeClient(info=info, project_root=project_root,
                                    kind='sdk', name='Agent SystemView '+client_id[:32])
        self.session = None
        self.after = 0
        self.owned = False
        self.uncertain = False

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
            if self.uncertain:
                raise RequestValidationError('Previous start/stop outcome is unknown; reconnect this remote client before a new subscription')
            arguments = {k: v for k, v in params.items() if v is not None}
            if self.session is not None:
                if arguments:
                    raise RequestValidationError('Already subscribed; stop this subscription before reconfiguring')
                self.client.call('systemview_capture_history', {'session': self.session, 'after': self.after, 'limit': 1})
                return {'session': self.session, 'after': self.after, 'reused': not self.owned}
            self.client.connect()
            self.uncertain = True
            try:
                started = self.client.call('systemview_start', arguments)
            except RuntimeErrorResponse as exc:
                self.uncertain = exc.status_code is None or exc.status_code >= 500
                raise
            self.owned = not started.get('reused', False)
            cursor = self.client.call('systemview_capture_history')
            self.session = cursor['session']
            self.after = 0 if self.owned else cursor['next_seq']
            self.uncertain = False
            return {**started, 'session': self.session, 'after': self.after, 'reused': not self.owned}
        if self.session is None:
            raise RequestValidationError('Call systemview.start before reading or stopping this subscription')
        if action == 'stop':
            if self.owned:
                # Backend admission refuses borrowed ownership and other subscribers.
                try:
                    self.client.call('systemview_stop')
                except RuntimeErrorResponse as exc:
                    if exc.status_code is None or exc.status_code >= 500:
                        self.owned = False  # Never replay a stop whose response was lost.
                        self.uncertain = True
                    raise
            stopped = None if self.uncertain else self.owned
            self.session = None
            self.owned = False
            self.client.close()
            return {'subscribed': False, 'capture_stopped': stopped}
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

    def close(self):
        try:
            if self.owned:
                try:
                    self.client.call('systemview_stop')
                except RuntimeErrorResponse:
                    # Do not stop a borrowed capture or replay an uncertain stop.
                    logging.getLogger(__name__).warning('SystemView left running or stop unconfirmed; detaching remote subscriber')
        finally:
            self.session = None
            self.owned = False
            self.client.close()
