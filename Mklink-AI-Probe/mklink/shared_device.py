"""Python SDK for the shared backend; never opens a serial port or retries hardware."""
from __future__ import annotations

import base64
import binascii

from mklink.runtime import RuntimeClient, RuntimeErrorResponse, request


class SharedDevice:
    """One client session. Closing it detaches only this client, including on error.

    Call connect() or use a with block before capabilities. Arguments omitted at
    connection adopt the backend's current project/symbols. Calls are sequential;
    acquisition conflicts return busy rather than stopping another client's work.
    This is an explicit shared API, not a drop-in replacement for low-level Device.
    """

    def __init__(self, *, probe=None, port=None, project_root=None, axf=None,
                 elf_backend=None, name='Python SDK'):
        self._options = dict(probe=probe, port=port, project_root=project_root,
                             axf=axf, elf_backend=elf_backend)
        self._client = RuntimeClient(project_root=project_root or '.', kind='sdk', name=name)

    def connect(self):
        self._client.connect(**self._options)
        return self

    def close(self):
        self._client.close()

    def __enter__(self):
        return self if self._client.session_id else self.connect()

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close()
        except RuntimeErrorResponse as error:
            if exc is None:
                raise
            message = f'Shared session detach failed: {error}'
            if callable(getattr(exc, 'add_note', None)):
                exc.add_note(message)
            else:  # Python 3.9/3.10 have no exception notes.
                import logging
                logging.getLogger(__name__).warning(message)
        return False

    def call(self, capability, arguments=None):
        """Invoke an advertised capability; stream ownership rules also apply here."""
        return self._client.call(capability, arguments)

    def read_memory(self, address: int, size: int) -> bytes:
        result = self.call('read_memory', {'address': hex(address), 'size': size})
        try:
            data = base64.b64decode(result['data_base64'], validate=True)
            if len(data) != size:
                raise ValueError('Short memory response')
        except (KeyError, ValueError, TypeError, binascii.Error) as exc:
            raise RuntimeErrorResponse('Invalid shared memory response; command was not retried') from exc
        return data

    def write_memory(self, address: int, data: bytes, *, verify: bool = True):
        if not isinstance(data, (bytes, bytearray)) or type(verify) is not bool:
            raise ValueError('data must be bytes and verify must be boolean')
        result = self.call('write_memory', {'address': hex(address), 'data_hex': data.hex(), 'verify': verify})
        if verify and result.get('verified') is not True:
            raise RuntimeErrorResponse('Memory write verification failed; command was not retried')
        return result

    def read_register(self, name: str) -> int:
        return self.call('read_register', {'name': name})['value']

    def halt(self):
        return self.call('halt')

    def resume(self):
        return self.call('resume')

    def step(self):
        return self.call('step')

    def start_job(self, action: str, *, request_id: str, confirm: bool = False, arguments=None):
        """Submit once and return a job record. Close/timeout is never cancellation.

        Query job_status after submission. Never automatically repeat an unknown
        result. The backend retains request-ID deduplication for its last 64 jobs.
        """
        if not self._client.session_id:
            raise RuntimeErrorResponse('Connect to the selected probe first')
        return request(self._client.info, 'POST', '/api/runtime/jobs/', {
            'action': action, 'request_id': request_id, 'confirm': confirm,
            'arguments': arguments if arguments is not None else {}, 'session_id': self._client.session_id})

    def job_status(self, job_id=None):
        """Read retained results even after close(); does not reconnect hardware."""
        if self._client.info is None:
            raise RuntimeErrorResponse('Select a runtime by connecting first')
        if job_id is not None and (not isinstance(job_id, str) or len(job_id) != 32
                                   or any(c not in '0123456789abcdef' for c in job_id)):
            raise ValueError('Invalid job ID')
        return request(self._client.info, 'GET', '/api/runtime/jobs/' + (job_id or ''))


def connect_shared(**options) -> SharedDevice:
    """Connect to a selected shared backend. Prefer use as a context manager."""
    return SharedDevice(**options).connect()
