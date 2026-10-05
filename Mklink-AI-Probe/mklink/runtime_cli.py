"""CLI adapters for shared capabilities. No direct serial fallback."""
from __future__ import annotations

import json
import math
import sys
import time
import webbrowser
import uuid
from mklink.runtime import RuntimeClient, RuntimeErrorResponse, browser_url

COMMANDS = {'systemview-analyze', 'systemview-report', 'vofa', 'watch', 'dump-benchmark', 'flush-memory', 'read-ram', 'write-ram', 'read-variable', 'write-variable', 'device-status', 'rtt', 'superwatch', 'systemview', 'flash', 'erase', 'reset', 'halt', 'resume', 'step', 'read-flash', 'read-reg', 'hardfault', 'break', 'debug-speed', 'power-read', 'version', 'configuration', 'peripherals', 'dump-memory', 'dump'}


def run(args):
    if args.command in {"systemview-analyze", "systemview-report"}:
        from mklink.systemview_cli import run as run_systemview
        return run_systemview(args)
    if args.command == 'peripherals' and args.action == 'targets':
        from mklink.peripheral_cli import run_offline_targets
        return run_offline_targets(args)
    if args.command == 'configuration' and args.action != 'read':
        from mklink.device_configuration import run_offline_cli
        return run_offline_cli(args)
    if args.command in {'power-read', 'version'}:
        from mklink.runtime import query_probe
        from mklink.cli import _print_power_read, _print_probe_version
        try:
            result = query_probe('power_read' if args.command == 'power-read' else 'probe_version',
                                 probe=args.probe, port=args.port)
        except (RuntimeErrorResponse, ValueError) as error:
            raise SystemExit(str(error)) from error
        return (_print_power_read(result, args.json) if args.command == 'power-read'
                else _print_probe_version(result['raw'], args.all, args.raw))
    project = getattr(args, 'project_root', None)
    flash_arguments = None
    erase_arguments = None
    job_action = args.command
    if args.command == 'erase':
        from mklink.native_erase import validate_erase_request
        erase_arguments = {key: getattr(args, key) for key in ('target_part', 'algorithm_id', 'address')
                           if getattr(args, key, None) is not None}
        if 'address' in erase_arguments:
            job_action = 'erase_sector'
        try:
            erase_arguments = validate_erase_request(erase_arguments, sector=job_action == 'erase_sector')
        except ValueError as error:
            raise SystemExit(str(error)) from error
    if args.command == 'flash':
        from pathlib import Path
        from mklink.flash_request import validate_flash_request
        if not args.hex:
            raise SystemExit('Shared flash requires an explicit --firmware or --hex path')
        flash_arguments = {'firmware': str(Path(args.hex).resolve()),
                           'verify': not getattr(args, 'no_verify', False),
                           'reset_after': not getattr(args, 'no_reset', False)}
        for key in ('target_part', 'base_address', 'board', 'hpm_flash_cfg', 'swd_clock'):
            if getattr(args, key, None) is not None:
                flash_arguments[key] = getattr(args, key)
        try:
            flash_arguments = validate_flash_request(flash_arguments)
        except ValueError as error:
            raise SystemExit(str(error)) from error
    if project in (None, '.'):
        project = getattr(args, 'project_root_positional', None)
    duration = getattr(args, 'duration', 0)
    if not math.isfinite(duration) or duration < 0:
        raise SystemExit('duration must be finite and nonnegative')
    if getattr(args, 'save', None) and args.command not in {'dump-memory', 'dump'}:
        raise SystemExit('Shared memory reads do not support --save to probe storage')
    if args.command not in {'configuration', 'peripherals'} and any(getattr(args, key, None) for key in ('svd', 'chip', 'target_id')):
        raise SystemExit('Select the peripheral catalog in the shared GUI first')
    if (getattr(args, 'host', '127.0.0.1') != '127.0.0.1'
            or getattr(args, 'port_http', 0) != 0 or getattr(args, 'max_points', 500) != 500):
        raise SystemExit('Shared visualization uses the backend GUI; private host/port/chart overrides are unsupported')
    if args.command == 'watch':
        from mklink.watch import validate_watch_names, format_watch_rows
        try:
            if not math.isfinite(args.period) or args.period < 0:
                raise ValueError('Watch period must be finite and nonnegative')
            watch_names = [name.strip() for group in args.variables for name in group.split(',') if name.strip()]
            if args.profile:
                from pathlib import Path
                path = Path(args.profile)
                with path.open('rb') as stream:
                    contents = stream.read(65537)
                if len(contents) > 65536:
                    raise ValueError('Watch profile exceeds 64 KiB')
                profile = json.loads(contents)
                if not isinstance(profile, dict) or set(profile) != {'variables'} or not isinstance(profile['variables'], list):
                    raise ValueError('Watch profile must contain a variables list only')
                watch_names.extend(profile['variables'])
            watch_names = validate_watch_names(watch_names)
        except (ValueError, OSError) as error:
            raise SystemExit(str(error)) from error
    if args.command == 'vofa':
        from mklink.vofa_viewer import parse_vofa_inputs
        try:
            if args.period is not None and (not math.isfinite(args.period) or not 0 < args.period <= 60):
                raise ValueError('VOFA period must be finite and in (0, 60]')
            vofa_channels = parse_vofa_inputs(args.variables, args.names) if args.variables else None
            if args.names and not args.variables:
                raise ValueError('VOFA names require channel arguments')
        except ValueError as error:
            raise SystemExit(str(error)) from error
    debug_arguments = None
    if args.command == 'peripherals':
        selectors = {key: getattr(args, key) for key in ('svd', 'chip', 'target_id') if getattr(args, key, None)}
        if (args.action == 'select' and len(selectors) != 1) or (args.action != 'select' and selectors):
            raise SystemExit('Use peripherals select with exactly one --target-id, --chip or --svd')
        if args.action in {'read', 'capture'} and not args.names:
            raise SystemExit('Specify peripheral register or field names')
        if selectors.get('svd'):
            from pathlib import Path
            selectors['svd'] = str(Path(selectors['svd']).expanduser().resolve())
    if args.command in {'dump-memory', 'dump'}:
        from mklink.cli import _parse_dump_region
        from mklink.dump_memory import validate_dump_stream
        try:
            dump_regions = [{'address': address, 'size': size} for address, size in map(_parse_dump_region, args.regions)]
            dump_arguments = dict(regions=dump_regions, period=args.period, frames=args.frames,
                                  duration=args.duration, speed_profile=args.speed)
            validate_dump_stream(**dump_arguments)
        except ValueError as error:
            raise SystemExit(str(error)) from error
    if args.command == 'dump-benchmark':
        from mklink.cli import _parse_dump_region
        from mklink.dump_benchmark import validate_measurement
        try:
            pairs = list(map(_parse_dump_region, args.regions))
            validate_measurement(pairs, args.duration, args.period, args.speed)
            measure_arguments = {'regions': [{'address': a, 'size': n} for a, n in pairs],
                                 'duration': args.duration, 'period': args.period, 'speed_profile': args.speed}
        except ValueError as error:
            raise SystemExit(str(error)) from error
    if args.command == 'flush-memory':
        from mklink.cli import _parse_flush_item
        from mklink.memory_write import validate_writes
        try:
            if not 1 <= args.repeat <= 100 or not 0 <= args.interval_ms <= 30000:
                raise ValueError('repeat must be 1..100; interval-ms must be 0..30000')
            flush_writes = [{'address': address, 'data_hex': bytes(data).hex()}
                            for address, data in map(_parse_flush_item, args.items)]
            validate_writes(flush_writes)
        except ValueError as error:
            raise SystemExit(str(error)) from error
    if args.command == 'break':
        selected = [bool(args.target), args.list, args.status, args.clear is not None]
        if sum(selected) != 1 or (args.slot is not None and not args.target):
            raise SystemExit('Choose exactly one breakpoint target, --list, --status or --clear; --slot is for set only')
        action = 'set' if args.target else 'list' if args.list else 'status' if args.status else 'clear_all' if args.clear == 'all' else 'clear'
        debug_arguments = {'action': action}
        if args.target:
            debug_arguments['target'] = args.target
        try:
            slot = int(args.clear) if action == 'clear' else args.slot
            if slot is not None:
                if slot < 0:
                    raise ValueError()
                debug_arguments['slot'] = slot
        except ValueError:
            raise SystemExit('Breakpoint slot must be a nonnegative integer')
    if args.command == 'read-reg':
        if bool(args.register) == (args.addr is not None) or args.width != 32 or not 1 <= args.count <= 1024:
            raise SystemExit('Specify one register or --addr, width=32, count=1..1024')
    client = RuntimeClient(project_root=project or '.', kind='cli', name='CLI '+args.command)
    owned_stream = None
    try:
        client.connect(project_root=project, port=getattr(args, 'port', None), probe=getattr(args, 'probe', None),
                       axf=getattr(args, 'source', None), elf_backend=getattr(args, 'elf_backend', None))
        if args.command in {'flash', 'erase', 'reset'}:
            arguments = {}
            if args.command == 'flash':
                arguments = flash_arguments
            elif args.command == 'erase':
                arguments = erase_arguments
            request_id = getattr(args, 'request_id', None) or str(uuid.uuid4())
            print(json.dumps({'request_id': request_id, 'action': job_action}), flush=True)
            result = client.start_job(job_action, arguments=arguments, request_id=request_id, confirm=True)
            print(json.dumps({'job_id': result['job_id'], 'state': result['state']}), flush=True)
            while result['state'] not in {'succeeded', 'failed', 'unknown'}:
                time.sleep(.25)
                result = client.job_status(result['job_id'])
            if result['state'] != 'succeeded':
                raise RuntimeErrorResponse(json.dumps(result, ensure_ascii=False))
        elif args.command == 'watch':
            try:
                while True:
                    rows = client.call('watch', {'names': watch_names})['rows']
                    print(format_watch_rows(rows, as_json=args.json), flush=True)
                    if args.period == 0:
                        break
                    time.sleep(args.period)
            except KeyboardInterrupt:
                pass
            return
        elif args.command == 'read-reg':
            result = client.call('register_snapshot', {'register': args.register, 'address': args.addr,
                                'width': args.width, 'count': args.count, 'raw': args.raw})
            if args.raw:
                print(bytes.fromhex(result['data_hex']).hex(' '))
            else:
                print(f"{result['name']} @ 0x{result['address']:08X}")
                for index, value in enumerate(result['values']):
                    display = {'hex': f'0x{value:08X}', 'dec': str(value), 'bin': f'0b{value:032b}'}.get(args.format, f'0x{value:08X} ({value})')
                    suffix = f'[{index}]' if args.count > 1 else ''
                    print(f"  {result['name']}{suffix} = {display}")
            return
        elif args.command == 'hardfault':
            result = client.call('fault_snapshot', {'sp': args.sp})
            if args.sp is None:
                print('[INFO] No --sp supplied; fault registers only. The target was not paused.')
            print(result['report'])
            return
        elif args.command == 'break':
            result = client.call('breakpoints', debug_arguments)
        elif args.command == 'configuration':
            result = client.call('read_configuration', {'part_number': args.chip, 'model': args.model})
        elif args.command == 'peripherals':
            arguments = (selectors if args.action == 'select' else {'q': args.query} if args.action == 'list'
                         else {'names': args.names})
            if args.action == 'capture':
                arguments.update(duration=args.duration, period=args.period)
            result = client.call(args.action + '_peripherals', arguments)
        elif args.command in {'dump-memory', 'dump'}:
            result = client.call('capture_dump', dump_arguments)
            payloads = []
            try:
                if result['sample_count'] != len(result['samples']) or result['sample_count'] < 1:
                    raise ValueError('Invalid sample count')
                for sample in result['samples']:
                    if len(sample['regions']) != len(dump_regions):
                        raise ValueError('Invalid region count')
                    for row, expected in zip(sample['regions'], dump_regions):
                        payload = bytes.fromhex(row['data_hex'])
                        if row['address'] != f"0x{expected['address']:08X}" or row['size'] != expected['size'] or len(payload) != expected['size']:
                            raise ValueError('Invalid region response')
                        payloads.append(payload)
                if sum(map(len, payloads)) != result['total_bytes']:
                    raise ValueError('Invalid byte count')
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeErrorResponse('Invalid shared dump response; no file written or command retried') from error
            if args.save:
                from mklink.file_content import write_atomic_chunks
                write_atomic_chunks(args.save, payloads)
            if args.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(f"Collected {result['sample_count']} complete samples, {result['total_bytes']} bytes; stopped by {result['stopped_by']}")
                if args.save:
                    print(f'Saved to {args.save}')
            return
        elif args.command == 'dump-benchmark':
            result = client.call('measure_dump_memory', measure_arguments)
        elif args.command == 'flush-memory':
            for index in range(args.repeat):
                result = client.call('flush_memory', {'writes': flush_writes, 'verify': args.verify})
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if not result.get('ok') or (args.verify and not result.get('verified')):
                    raise RuntimeErrorResponse('Flush failed; remaining writes were not sent. Inspect target before another write')
                if index + 1 < args.repeat:
                    time.sleep(args.interval_ms / 1000)
            return
        elif args.command == 'device-status':
            result = client.call('device_status')
        elif args.command == 'debug-speed':
            result = client.call('set_debug_speed', {'profile': args.profile, 'save': args.persist_profile})
        elif args.command in {'halt', 'resume', 'step'}:
            result = client.call(args.command)
        elif args.command in {'read-ram', 'read-flash'}:
            result = client.call('read_memory', {'address': args.addr, 'size': args.size})
        elif args.command == 'write-ram':
            payload = bytes(int(value, 0) for value in args.data)
            result = client.call('write_memory', {'address': args.addr, 'data_hex': payload.hex(), 'verify': True})
            if not result['verified']:
                raise RuntimeErrorResponse('Write completed but verification differed; operation was not retried')
        elif args.command in {'read-variable', 'write-variable'}:
            arguments = {'name': args.name}
            if args.command == 'write-variable':
                arguments['value'] = int(args.value, 0)
            result = client.call(args.command.replace('-', '_'), arguments)
        else:
            stream = args.command
            status = client.call(stream+'_status')
            running = bool(status.get('running')) or status.get('state') in {'running', 'paused'}
            options = {}
            if stream == 'rtt':
                selected = getattr(args, 'channels', None)
                address = getattr(args, 'addr', None)
                if selected:
                    options.update(channels=selected, channel=selected[0])
                if address:
                    options['addr'] = address
            if stream == 'vofa':
                if running and (vofa_channels is not None or args.period is not None):
                    raise RuntimeErrorResponse('Capture already running; omit channels/period to subscribe')
                if not running:
                    options = {'interval': args.period if args.period is not None else .001}
                    if vofa_channels is not None:
                        options['channels'] = vofa_channels
            if stream == 'superwatch':
                if running and (args.variables or args.period != .001):
                    raise RuntimeErrorResponse('Capture already running; omit variable/period changes to subscribe')
                if not running:
                    for name in args.variables:
                        client.call('superwatch_add', {'name': name})
                    client.call('superwatch_interval', {'interval': args.period})
            if stream == 'systemview' and not running:
                options = {'channel': args.channel}
                if args.addr:
                    options['addr'] = args.addr
            elif stream == 'systemview' and running and (args.addr or args.channel != 1):
                raise RuntimeErrorResponse('Capture already running; omit configuration to subscribe')
            started = client.call(stream+'_start', options)
            if not started.get('reused'):
                owned_stream = stream
            if getattr(args, 'visualize', False) and not getattr(args, 'no_browser', False):
                webbrowser.open(browser_url(client.info, page="vofa" if stream == "vofa" else "config"))
            deadline = time.monotonic()+duration if duration else None
            print(json.dumps({'capture': stream, 'shared': True, **started}, ensure_ascii=False), flush=True)
            try:
                while deadline is None or time.monotonic() < deadline:
                    time.sleep(min(.25, max(0, deadline-time.monotonic())) if deadline else .25)
                    if stream == 'vofa':
                        current = client.call('vofa_status')
                        if current.get('error') or not current.get('running'):
                            raise RuntimeErrorResponse(current.get('error') or 'VOFA acquisition stopped')
            except KeyboardInterrupt:
                pass
            result = client.call(stream+('_values' if stream == 'superwatch' else '_history'))
            if stream == 'rtt' and getattr(args, 'channels', None):
                result = {'channels': [client.call('rtt_read_channel', {'channel': ch}) for ch in args.channels]}
            if stream == 'vofa':
                if result.get('error') or not result.get('completed_samples'):
                    raise RuntimeErrorResponse(result.get('error') or 'VOFA returned no complete samples')
                if owned_stream:
                    owned_stream = None  # Stop once; a failed confirmation must not be replayed in finally.
                    try:
                        client.call('vofa_stop')
                    except RuntimeErrorResponse as error:
                        if error.status_code != 409:
                            raise
                        print(f'Capture left running: {error}; detaching this client', file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeErrorResponse, ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        if owned_stream:
            try:
                client.call(owned_stream+'_stop')
            except RuntimeErrorResponse as exc:
                print(f'Capture left running: {exc}', file=sys.stderr)
        try:
            client.close()
        except RuntimeErrorResponse as exc:
            print(f'Could not detach from backend: {exc}; session will expire without replaying commands', file=sys.stderr)
