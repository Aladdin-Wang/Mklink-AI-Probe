"""Shared GUI/MCP/CLI capability contract and transport-independent validation."""
from __future__ import annotations

from fastapi import HTTPException

STREAMS = ('rtt', 'superwatch', 'systemview')
CAPABILITIES = {
    'device_status': ('GET', '/api/device/status'),
    'halt': ('POST', '/api/device/halt'),
    'resume': ('POST', '/api/device/resume'),
    'step': ('POST', '/api/device/step'),
    'resources': ('GET', '/api/resources/status'),
    'read_memory': ('POST', '/api/device/read-memory'),
    'write_memory': ('POST', '/api/device/write-memory'),
    'read_variable': ('POST', '/api/device/read-variable'),
    'write_variable': ('POST', '/api/device/write-variable'),
    'register_snapshot': ('POST', '/api/device/register-snapshot'),
    'fault_snapshot': ('POST', '/api/device/fault-snapshot'),
    'breakpoints': ('POST', '/api/device/breakpoints'),
    'read_register': ('POST', '/api/device/read-register'),
    'core_registers': ('GET', '/api/device/core-registers'),
    'hardfault': ('GET', '/api/device/hardfault-detail'),
    'symbol_search': ('GET', '/api/symbols/search'),
    'symbol_status': ('GET', '/api/symbols/status'),
    'symbol_typeinfo': ('GET', '/api/symbols/typeinfo'),
    'memory_map': ('GET', '/api/device/memory-map'),
    'superwatch_items': ('GET', '/api/dash/superwatch/items'),
    'superwatch_snapshot': ('GET', '/api/dash/superwatch/array-snapshot'),
    'superwatch_values': ('GET', '/api/dash/superwatch/latest'),
    'superwatch_add': ('POST', '/api/dash/superwatch/add'),
    'superwatch_remove': ('POST', '/api/dash/superwatch/remove'),
    'superwatch_write': ('POST', '/api/dash/superwatch/write'),
    'superwatch_interval': ('POST', '/api/dash/superwatch/interval'),
    'rtt_write': ('POST', '/api/dash/rtt/write'),
}
for stream in STREAMS:
    for action in ('status', 'start', 'stop', 'pause', 'resume'):
        CAPABILITIES[f'{stream}_{action}'] = ('GET' if action == 'status' else 'POST', f'/api/dash/{stream}/{action}')
for stream in ('rtt', 'systemview'):
    CAPABILITIES[f'{stream}_history'] = ('GET', f'/api/dash/{stream}/history')
for stream in ('serial', 'modbus', 'vofa'):
    CAPABILITIES[f'{stream}_status'] = ('GET', f'/api/dash/{stream}/status')


def validate_arguments(capability, arguments):
    """Reject malformed/range-overflow writes before a device is touched."""
    arguments = dict(arguments)
    if capability in {'read_memory', 'write_memory'}:
        try:
            address = int(str(arguments['address']), 0)
            if capability == 'write_memory':
                raw = arguments['data_hex']
                if not isinstance(raw, str) or not raw or len(raw) > 8192 or len(raw) % 2:
                    raise ValueError()
                if any(c not in '0123456789abcdefABCDEF' for c in raw):
                    raise ValueError()
                size = len(bytes.fromhex(raw))
            else:
                size = arguments['size']
            if type(size) is not int or not 1 <= size <= 4096 or not 0 <= address <= 0x100000000 - size:
                raise ValueError()
            arguments['address'] = hex(address)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, 'Memory operations require a 32-bit address and 1..4096 bytes; writes use even hexadecimal')
    if capability == 'write_variable' and type(arguments.get('value')) is not int:
        raise HTTPException(422, 'write_variable requires an integer; use typed superwatch_write for other types')
    if capability == 'rtt_write':
        try:
            raw = arguments['data_hex']
            if not isinstance(raw, str) or not raw or len(raw) > 512 or len(raw) % 2:
                raise ValueError()
            if any(c not in '0123456789abcdefABCDEF' for c in raw):
                raise ValueError()
            data = bytes.fromhex(raw)
            if not 1 <= len(data) <= 256:
                raise ValueError()
            data.decode('utf-8')
            if b'RTTView.stop()' in data:
                raise ValueError()
        except (KeyError, ValueError, UnicodeError):
            raise HTTPException(422, 'RTT input must contain 1..256 UTF-8 bytes encoded as hexadecimal')
    return arguments
