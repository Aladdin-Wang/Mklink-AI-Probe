"""Shared GUI/MCP/CLI capability contract and transport-independent validation."""
from __future__ import annotations

from fastapi import HTTPException

STREAMS = ('rtt', 'superwatch', 'systemview', 'vofa')
CAPABILITIES = {
    'uart_ports': ('GET', '/api/ports/uart'),
    'device_status': ('GET', '/api/device/status'),
    'debug_speed': ('GET', '/api/device/debug-speed'),
    'set_debug_speed': ('POST', '/api/device/debug-speed'),
    'halt': ('POST', '/api/device/halt'),
    'resume': ('POST', '/api/device/resume'),
    'step': ('POST', '/api/device/step'),
    'resources': ('GET', '/api/resources/status'),
    'read_memory': ('POST', '/api/device/read-memory'),
    'measure_dump_memory': ('POST', '/api/device/dump-memory/measure'),
    'capture_dump': ('POST', '/api/device/dump-memory/capture'),
    'flush_memory': ('POST', '/api/device/flush-memory'),
    'dump_memory': ('POST', '/api/device/dump-memory'),
    'read_memory_regions': ('POST', '/api/device/read-memory-regions'),
    'read_configuration': ('POST', '/api/device/configuration/read'),
    'peripheral_targets': ('GET', '/api/dash/superwatch/peripherals/targets'),
    'select_peripherals': ('POST', '/api/dash/superwatch/peripherals/select'),
    'list_peripherals': ('GET', '/api/dash/superwatch/peripherals'),
    'read_peripherals': ('POST', '/api/device/peripherals/read'),
    'capture_peripherals': ('POST', '/api/device/peripherals/capture'),
    'write_memory': ('POST', '/api/device/write-memory'),
    'watch': ('POST', '/api/device/watch'),
    'read_variable': ('POST', '/api/device/read-variable'),
    'write_variable': ('POST', '/api/device/write-variable'),
    'register_snapshot': ('POST', '/api/device/register-snapshot'),
    'fault_snapshot': ('POST', '/api/device/fault-snapshot'),
    'breakpoints': ('POST', '/api/device/breakpoints'),
    'read_register': ('POST', '/api/device/read-register'),
    'core_registers': ('GET', '/api/device/core-registers'),
    'symbol_catalog': ('GET', '/api/symbols/catalog'),
    'hardfault_check': ('GET', '/api/device/hardfault'),
    'hardfault_decode': ('POST', '/api/device/hardfault-detail'),
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
    'systemview_capture_history': ('GET', '/api/dash/systemview/history/cursor'),
    'rtt_read_channel': ('GET', '/api/dash/rtt/channels/read'),
    'rtt_write': ('POST', '/api/dash/rtt/write'),
}
# These operations only use Device's framed memory path. Configuration, flash,
# debug control and legacy acquisition retain their explicit stop boundary.
MUX_MEMORY_CAPABILITIES = frozenset({'read_memory', 'write_memory', 'read_variable',
                                    'write_variable', 'read_register', 'read_memory_regions'})
MUX_MEMORY_PATHS = frozenset(CAPABILITIES[name][1] for name in MUX_MEMORY_CAPABILITIES)


def multiplex_enabled(state):
    """Cached negotiation only: safe on the HTTP event loop, never serial I/O."""
    return getattr(getattr(state.get('device'), '_bridge', None), '_mux_supported', None) is True


for stream in STREAMS:
    for action in ('status', 'start', 'stop', 'pause', 'resume'):
        CAPABILITIES[f'{stream}_{action}'] = ('GET' if action == 'status' else 'POST', f'/api/dash/{stream}/{action}')
for stream in ('rtt', 'systemview', 'vofa'):
    CAPABILITIES[f'{stream}_history'] = ('GET', f'/api/dash/{stream}/history')
for stream in ('serial', 'modbus'):
    for action in ('status', 'start', 'stop'):
        CAPABILITIES[f'{stream}_{action}'] = ('GET' if action == 'status' else 'POST', f'/api/dash/{stream}/{action}')
CAPABILITIES.update({
    'serial_broadcast': ('POST', '/api/dash/serial/broadcast'),
    'serial_send_file': ('POST', '/api/dash/serial/file'),
    'serial_sequence_start': ('POST', '/api/dash/serial/sequence/start'),
    'serial_sequence_stop': ('POST', '/api/dash/serial/sequence/stop'),
    'serial_recording_start': ('POST', '/api/dash/serial/recording/start'),
    'serial_recording_stop': ('POST', '/api/dash/serial/recording/stop'),
    'serial_history': ('POST', '/api/dash/serial/history'),
    'serial_ymodem_start': ('POST', '/api/dash/serial/ymodem/file'),
    'serial_ymodem_status': ('GET', '/api/dash/serial/ymodem/status'),
    'serial_ymodem_trace': ('GET', '/api/dash/serial/ymodem/trace'),
    'serial_ymodem_cancel': ('POST', '/api/dash/serial/ymodem/cancel'),
    'serial_exchange': ('POST', '/api/dash/serial/exchange'),
    'serial_send': ('POST', '/api/dash/serial/send'),
    'modbus_transaction': ('POST', '/api/dash/modbus/transaction'),
    'modbus_probe': ('POST', '/api/dash/modbus/probe'),
    'modbus_history': ('POST', '/api/dash/modbus/history'),
    'modbus_loop_start': ('POST', '/api/dash/modbus/loop/start'),
    'modbus_loop_stop': ('POST', '/api/dash/modbus/loop/stop'),
})
LIFECYCLE_CAPABILITIES = {
    f'{stream}_{action}': (stream, action)
    for stream in (*STREAMS, 'serial', 'modbus')
    for action in ('start', 'stop', 'pause', 'resume')
    if f'{stream}_{action}' in CAPABILITIES
}


PROBE_QUERIES = {'power_read': '/api/probe/power-read', 'probe_version': '/api/probe/version',
                 'probe_idcode': '/api/probe/idcode'}
CAPABILITIES.update({name: ('POST', path) for name, path in PROBE_QUERIES.items()})


def is_uart_path(path: str) -> bool:
    """Independent UART routes never reserve the target's command bridge."""
    return path == '/api/ports/uart' or path.startswith(('/api/dash/serial/', '/api/dash/modbus/'))


UART_CAPABILITIES = frozenset(name for name, (_, path) in CAPABILITIES.items() if is_uart_path(path))


def validate_arguments(capability, arguments):
    """Reject malformed/range-overflow writes before a device is touched."""
    arguments = dict(arguments)
    if capability == 'select_peripherals':
        if (arguments.keys() - {'target_id', 'chip', 'svd'} or len(arguments) != 1
                or any(not isinstance(value, str) or not value.strip() for value in arguments.values())):
            raise HTTPException(422, 'Select exactly one nonempty target_id, chip or SVD')
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
            channel = arguments.get('channel')
            if channel is not None and (type(channel) is not int or not 0 <= channel < 8):
                raise ValueError()
        except (KeyError, ValueError, UnicodeError):
            raise HTTPException(422, 'RTT input must contain 1..256 bytes encoded as hexadecimal; channel must be 0..7')
    return arguments
