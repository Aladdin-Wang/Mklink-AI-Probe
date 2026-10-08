"""Observe existing shared RTU trace events; no second UART reader or log buffer."""
from __future__ import annotations

import datetime
import sys
import time
from collections.abc import Callable
from typing import TextIO

from mklink.modbus._registers import validate_poll_interval


def validate_monitor(interval: float, output_format: str, count: int | None) -> None:
    validate_poll_interval(interval)
    if output_format not in ('decoded', 'hex', 'both'):
        raise ValueError('Monitor format must be decoded, hex or both')
    if count is not None and (type(count) is not int or count < 1):
        raise ValueError('Monitor count must be a positive integer')


def _format_frame(event: dict, output_format: str) -> str:
    payload = bytes.fromhex(event['hex'])
    stamp = datetime.datetime.fromtimestamp(event['timestamp']).isoformat(timespec='milliseconds')
    prefix = f"[{stamp}] #{event['seq']} {event['direction'].upper()}"
    decoded = f"Slave={payload[0]} FC={payload[1]:02X}" if len(payload) > 1 else 'partial frame'
    if event['complete']:
        decoded += f" CRC={'OK' if event['crc_ok'] else 'BAD'}"
        if not event['crc_ok']:
            decoded += ' invalid payload'
        elif payload[1] & 0x80 and len(payload) >= 5:
            decoded += f' Exception={payload[2]}'
        elif event['direction'] == 'tx' and payload[1] in (1, 2, 3, 4) and len(payload) == 8:
            decoded += f' Address={int.from_bytes(payload[2:4])} Count={int.from_bytes(payload[4:6])}'
        elif event['direction'] == 'rx' and payload[1] in (3, 4, 23):
            decoded += ' Values=[' + ', '.join(f'0x{int.from_bytes(payload[i:i+2]):04X}' for i in range(3, len(payload)-2, 2)) + ']'
    else:
        decoded += ' incomplete/unknown'
    content = event['hex'] if output_format == 'hex' else decoded
    if output_format == 'both':
        content += f" | {event['hex']}"
    return f'{prefix} {content}'


def monitor_traffic(call: Callable, slave: int, interval: float = 2.0,
                    output_format: str = 'decoded', count: int | None = None,
                    output: TextIO | None = None, passive: bool = False) -> None:
    """Log all new shared frames, optionally issuing one FC03 read per round.

    `call` is the existing runtime capability dispatcher. `count` counts rounds
    (history polls in passive mode), not packets. Start at the current tail;
    report retention loss and fail closed on connection replacement or errors.
    """
    validate_monitor(interval, output_format, count)

    def emit(line: str) -> None:
        print(line, flush=True)
        if output is not None:
            output.write(line + '\n')
            output.flush()

    initial = call('modbus_history', {})
    if not initial['running'] or initial['stopping']:
        raise OSError('Modbus monitor requires a running connection')
    session, cursor = initial['session'], initial['next_seq']
    emit(f"[*] Modbus session={session} connection={initial['connection']}")
    emit('[*] Passive: observe all shared traffic; no probe requests' if passive else
         f'[*] Active: FC03 slave={slave} address=0 count=10 every {interval}s; observe all shared traffic')

    def drain() -> None:
        nonlocal cursor
        # At most two pages per round: history holds 500 events, each page <=256.
        # A busy producer cannot keep this foreground loop draining forever.
        for _ in range(2):
            page = call('modbus_history', {'session': session, 'after': cursor, 'limit': 256})
            if page['session'] != session:
                raise OSError('Modbus history session changed; reopen explicitly')
            if page['dropped']:
                emit(f"[WARN] Lost {page['dropped']} retained events before seq={cursor + page['dropped'] + 1}")
            for event in page['entries']:
                if event['event'] == 'frame':
                    emit(_format_frame(event, output_format))
                elif event['event'] == 'error':
                    emit(f"[ERROR] #{event['seq']} {event['message']}")
            cursor = page['next_seq']
            if not page['running'] or page['stopping']:
                raise OSError('Modbus connection stopped; reopen explicitly')
            if cursor >= page['latest_seq']:
                break

    rounds = 0
    try:
        while count is None or rounds < count:
            if not passive:
                try:
                    call('modbus_transaction', {'fc': 3, 'start': 0, 'quantity': 10, 'slave': slave})
                except Exception as error:
                    # Preserve any TX/exception reply even if the transaction failed.
                    # A history failure must not mask the original operation failure.
                    try:
                        drain()
                        emit(f'[ERROR] {error}')
                    except Exception as history_error:
                        print(f'[WARN] Cannot save final trace: {history_error}', file=sys.stderr, flush=True)
                    raise
            drain()
            rounds += 1
            if count is None or rounds < count:
                time.sleep(interval)
    except KeyboardInterrupt:
        emit(f'[*] Monitor stopped after {rounds} rounds')
