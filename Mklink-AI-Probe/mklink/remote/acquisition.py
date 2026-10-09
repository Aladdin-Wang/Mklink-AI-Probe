"""Temporarily yield target capture to a download, retaining subscriptions.

The caller must retain runtime admission until this context exits (including
the entire online worker lifetime). Independent UART producers are untouched.
"""
import asyncio
from contextlib import asynccontextmanager
import logging
import json
from copy import deepcopy

from fastapi import HTTPException

logger = logging.getLogger(__name__)


@asynccontextmanager
async def suspend_acquisition(state, control=None):
    from mklink.remote.api import (
        _dashboard_start_lock, _dashboard_worker_alive,
        _start_dashboard_manager_transaction, stop_dashboard_manager,
    )
    from mklink.remote.dashboards import BRIDGE_DASHBOARD_TYPES, get_managers

    report = {'state': 'pausing', 'paused': [], 'restored': [], 'errors': []}
    state['acquisition_transition'] = report
    device, dispatcher = state.get('device'), state.get('dispatcher')
    was_connected = bool(device is not None and device.connected)
    saved = []
    attempted = set()
    async with _dashboard_start_lock(state):
        try:
            # Validate the whole restore plan before stopping its first producer.
            for name, manager in get_managers().items():
                if name not in BRIDGE_DASHBOARD_TYPES or not _dashboard_worker_alive(manager):
                    continue
                restart = getattr(manager, '_restart_after_operation', None)
                if not callable(restart):
                    raise HTTPException(409, f'{name}: acquisition restart configuration is unavailable')
                if name == 'vofa':
                    channels, interval = deepcopy(manager._channel_specs), manager._interval
                    restart = lambda m=manager, ch=channels, dt=interval: m.start(state['device'], ch, dt)
                elif name == 'rtt' and hasattr(manager, '_line_assembler'):
                    encoding = manager._line_assembler.encoding
                    encodings = {ch: decoder._line_assembler.encoding
                                 for ch, decoder in manager._channel_decoders.items()}
                    def restart_rtt(start=restart, m=manager, default=encoding, per_channel=encodings):
                        start()
                        m.set_encoding(default)
                        for channel, value in per_channel.items():
                            m.set_encoding(value, channel)
                    restart = restart_rtt
                elif name == 'systemview' and getattr(manager, '_recording', None) is not None:
                    def restart_recording(start=restart, m=manager):
                        start()
                        m.start_recording()
                    restart = restart_recording
                collecting = getattr(manager, '_collecting', None)
                paused = not collecting.is_set() if collecting is not None else bool(getattr(manager, 'paused', False))
                saved.append((name, manager, restart, paused))
            for name, manager, _, _ in saved:
                # Do not clear RuntimeControl ownership/subscribers: this is a
                # temporary suspension, not an explicit user stop.
                attempted.add(name)
                try:
                    await asyncio.to_thread(stop_dashboard_manager, state, name, manager)
                except Exception as error:
                    raise HTTPException(409, f'Could not pause {name}: {error}; download did not start') from error
                report['paused'].append(name)
            report['state'] = 'suspended'
            yield report
        finally:
            report['state'] = 'restoring'
            try:
                # HPM and power-cycle downloads close the shared command handle.
                # Reopen only the same bound USB identity, preserving symbol state.
                if was_connected and not device.connected:
                    if any(_dashboard_worker_alive(manager) for _, manager, _, _ in saved):
                        raise RuntimeError('A capture worker still owns the connection')
                    if control is not None and control.info.get('probe_id'):
                        from mklink.probes import select_probe
                        selected = await asyncio.to_thread(select_probe, control.info['probe_id'])
                        device._port = selected['port']
                    close = getattr(device, 'close', None)
                    if callable(close):
                        await asyncio.to_thread(close)
                    await asyncio.to_thread(device._connect)
                    state['device'], state['dispatcher'] = device, dispatcher
            except Exception as error:
                report['errors'].append(f'connection: {error}')
            for name, manager, restart, paused in saved:
                if name not in attempted:
                    continue
                if _dashboard_worker_alive(manager):
                    # A stop timeout must never create a second reader.
                    if name not in report['paused']:
                        report['errors'].append(f'{name}: worker has not stopped')
                    continue
                try:
                    if device is None or not device.connected:
                        raise RuntimeError('Device not connected')
                    await _start_dashboard_manager_transaction(state, name, manager, restart)
                    if paused:
                        manager.pause()
                    report['restored'].append(name)
                except Exception as error:
                    report['errors'].append(f'{name}: {error}')
            report['state'] = 'failed' if report['errors'] else 'restored'
            if report['errors']:
                logger.warning('Acquisition restore: %s', '; '.join(report['errors']))


async def download_response(app, scope, receive, send, state, control):
    """Keep the final response chunk until restoration; stream progress normally."""
    start = pending = None
    sent_start = False

    async def emit(message):
        nonlocal sent_start
        if not sent_start:
            await send(start)
            sent_start = True
        await send(message)

    async def capture(message):
        nonlocal start, pending
        if message['type'] == 'http.response.start':
            start = message
        elif message['type'] == 'http.response.body':
            if pending is not None and not message.get('body') and not message.get('more_body'):
                pending = {**pending, 'more_body': False}
            else:
                if pending is not None:
                    await emit(pending)
                pending = message
        else:
            await send(message)

    async with suspend_acquisition(state, control) as report:
        await app(scope, receive, capture)
    if pending is None:
        return
    content_type = dict(start.get('headers', [])).get(b'content-type', b'')
    if (report['paused'] or report['errors']) and (b'application/json' in content_type or b'application/x-ndjson' in content_type):
        try:
            payload = json.loads(pending.get('body', b''))
            if isinstance(payload, dict):
                destination = payload.get('result') if payload.get('type') == 'result' else payload
                if isinstance(destination, dict):
                    destination['acquisition'] = report
                    body = json.dumps(payload, ensure_ascii=False).encode()
                    if b'ndjson' in content_type:
                        body += b'\n'
                    pending = {**pending, 'body': body}
                    if not sent_start:
                        start['headers'] = [(k, v) for k, v in start['headers'] if k.lower() != b'content-length']
                        start['headers'].append((b'content-length', str(len(body)).encode()))
        except (ValueError, UnicodeError):
            pass
    await emit(pending)
