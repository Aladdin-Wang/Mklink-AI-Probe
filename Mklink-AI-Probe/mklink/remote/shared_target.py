"""Site Agent target sessions; hardware ownership stays in the shared runtime."""
from __future__ import annotations

import base64
import threading
import time
import uuid

from mklink.remote.capabilities import CapabilityUnavailableError
from mklink.remote.protocol import AgentOperationError, RequestValidationError


OPERATIONS = frozenset({
    'probe.info', 'flash.program', 'flash.erase_chip', 'flash.erase_sector', 'target.reset',
    'target.halt', 'target.resume', 'target.step', 'breakpoint.set', 'breakpoint.clear',
    'breakpoint.clear_all', 'registers.core', 'memory.read', 'memory.write', 'register.read',
    'variable.read', 'variable.write', 'symbols.status', 'symbols.parse', 'symbols.list',
    'symbols.search', 'symbols.memory_map', 'hardfault.check', 'hardfault.decode',
})


class SharedTarget:
    """Lifecycle handle for SiteAgent, not a replacement Device implementation."""

    def __init__(self, project_root, select_probe):
        self.project_root = project_root
        self.select_probe = select_probe
        self.info = None
        self._clients = {}
        self._lock = threading.Lock()

    @property
    def connected(self):
        # Last known attachment state: diagnostics must not block on target I/O.
        return self.info is not None

    def connect(self, *, port=None, axf=None):
        from mklink.runtime import RuntimeClient
        probe = self.select_probe()
        if probe == 'lobby':
            raise CapabilityUnavailableError(data={'reason': 'select-physical-probe'})
        self.close()
        bootstrap = RuntimeClient(project_root=self.project_root, kind='sdk', name='Site Agent connection')
        try:
            bootstrap.connect(probe=probe, axf=axf)
            info = bootstrap.info
        finally:
            bootstrap.close()
        self.info = info
        return self

    def client_closed(self, client_id):
        with self._lock:
            client = self._clients.pop(client_id, None)
        if client is not None:
            client.close()

    def close(self):
        with self._lock:
            clients, self._clients = self._clients, {}
            self.info = None
        error = None
        for client in clients.values():
            try:
                client.close()
            except Exception as exc:
                error = error or exc
        if error is not None:
            raise error

    def _client(self, client_id):
        from mklink.runtime import RuntimeClient
        if self.info is None:
            raise CapabilityUnavailableError(data={'reason': 'call-agent.reconnect-first'})
        if not client_id:
            raise CapabilityUnavailableError(data={'reason': 'remote-client-identity-required'})
        with self._lock:
            client = self._clients.get(client_id)
            if client is None:
                client = RuntimeClient(info=self.info, project_root=self.project_root,
                                       kind='sdk', name='Agent '+client_id[:32])
                self._clients[client_id] = client
        if not client.session_id:
            client.connect()
        return client

    def dispatch(self, requested, operation, params, client_id, uploads):
        from mklink.runtime import RuntimeErrorResponse, request
        from mklink.remote.dispatcher import _integer, _text, _mapping, _bytes_result
        request_id = None
        job = None
        try:
            client = self._client(client_id)
            call = client.call
            if operation == 'probe.info':
                status = call('device_status')
                info = {'connected': status['connected'], 'idcode': int(status.get('idcode') or '0', 0),
                        'mcu_name': status.get('mcu') or ''}
                return info.get(requested, info)
            if operation in ('target.halt', 'target.resume', 'target.step'):
                return call(operation.split('.')[1])
            if operation == 'registers.core':
                return call('core_registers')['registers']
            if operation.startswith('breakpoint.'):
                action = operation.split('.')[1]
                arguments = {'action': action}
                if action == 'set':
                    arguments['target'] = hex(_integer(params.get('address'), 'address'))
                if params.get('slot') is not None:
                    arguments['slot'] = _integer(params['slot'], 'slot')
                result = call('breakpoints', arguments)
                if action == 'set': return {'slot': result['slot']}
                return {'cleared': True if action == 'clear' else len(result['cleared'])}
            if operation in ('memory.read', 'memory.write'):
                address = _integer(params.get('address'), 'address')
                if operation == 'memory.read':
                    size = _integer(params.get('size'), 'size', minimum=1)
                    result = call('read_memory', {'address': hex(address), 'size': size})
                    data = base64.b64decode(result['data_base64'], validate=True)
                    if len(data) != size:
                        raise AgentOperationError('Incomplete memory response; operation was not retried')
                    return _bytes_result(data)
                encoded = _text(params.get('data_b64'), 'data_b64')
                if len(encoded) > 5464:
                    raise RequestValidationError('Shared memory writes are limited to 4096 bytes')
                try:
                    data = base64.b64decode(encoded, validate=True)
                except ValueError:
                    raise RequestValidationError('Invalid memory payload') from None
                result = call('write_memory', {'address': hex(address), 'data_hex': data.hex(), 'verify': True})
                if result.get('verified') is not True:
                    raise AgentOperationError('Write verification failed; operation was not retried')
                return {'written': len(data)}
            if operation in ('variable.read', 'register.read'):
                return call('read_variable' if operation == 'variable.read' else 'read_register',
                            {'name': _text(params.get('name'), 'name')})['value']
            if operation == 'variable.write':
                call('write_variable', {'name': _text(params.get('name'), 'name'),
                                       'value': _integer(params.get('value'), 'value')})
                return {'written': True}
            if operation == 'symbols.status': return call('device_status')['axf']
            if operation == 'symbols.memory_map': return call('memory_map')
            if operation in ('symbols.list', 'symbols.search'):
                return call('symbol_catalog', {'q': str(params.get('query', '')),
                    'writable': bool(params.get('writable', False)),
                    'offset': _integer(params.get('offset', 0), 'offset'),
                    'limit': _integer(params.get('limit', 200), 'limit', minimum=1)})
            if operation == 'symbols.parse':
                source = uploads.resolve(_text(params.get('source'), 'source'))
                backend = params.get('elf_backend')
                if backend not in (None, 'builtin', 'external'):
                    raise RequestValidationError('Invalid ELF backend')
                # The normal backend route refuses a symbol change while any
                # other target client/GUI capture still uses the current catalog.
                self.client_closed(client_id)
                return request(self.info, 'POST', '/api/device/parse-axf',
                               {'axf': str(source), 'elf_backend': backend})
            if operation == 'hardfault.check': return call('hardfault_check')
            if operation == 'hardfault.decode':
                registers = params.get('fault_regs')
                arguments = {} if registers is None else {'fault_regs': dict(_mapping(registers, 'fault_regs'))}
                result = call('hardfault_decode', arguments)
                return {k: v for k, v in result.items() if k != 'fault'} if result.get('fault') else None
            if operation in ('flash.program', 'flash.erase_chip', 'flash.erase_sector', 'target.reset'):
                action = {'flash.program': 'flash', 'flash.erase_chip': 'erase',
                          'flash.erase_sector': 'erase_sector', 'target.reset': 'reset'}[operation]
                arguments = {}
                if action == 'flash':
                    arguments = {k: params[k] for k in ('target_part', 'base_address', 'board',
                        'hpm_flash_cfg', 'swd_clock', 'verify', 'reset_after') if k in params}
                    arguments['firmware'] = str(uploads.resolve(_text(params.get('firmware'), 'firmware')))
                elif action.startswith('erase'):
                    arguments = {k: params[k] for k in ('target_part', 'algorithm_id') if k in params}
                    if action == 'erase_sector': arguments['address'] = _integer(params.get('address'), 'address')
                request_id = params.get('request_id') or uuid.uuid4().hex
                job = client.start_job(action, request_id=request_id, confirm=True, arguments=arguments)
                while job['state'] not in ('succeeded', 'failed', 'unknown'):
                    time.sleep(.1)
                    job = client.job_status(job['job_id'])
                if job['state'] != 'succeeded':
                    raise AgentOperationError('Target job did not succeed; do not replay',
                        data={'job_id': job['job_id'], 'request_id': request_id, 'state': job['state']})
                if action == 'reset': return {'reset': True}
                if action.startswith('erase'): return bool(job['result']['success'])
                return job['result']
            raise CapabilityUnavailableError(data={'operation': operation})
        except RuntimeErrorResponse as exc:
            raise AgentOperationError('Shared target operation failed; no direct fallback or replay',
                                      data={'status': exc.status_code, **({'request_id': request_id,
                        'job_id': job.get('job_id') if job else None, 'state': 'unknown'}
                        if request_id is not None else {})}) from None
