"""CLI adapters for shared capabilities. No direct serial fallback."""
from __future__ import annotations

import json
import math
import sys
import time
import webbrowser
import uuid
from mklink.runtime import RuntimeClient, RuntimeErrorResponse, browser_url

COMMANDS = {'read-ram', 'write-ram', 'read-variable', 'write-variable', 'device-status', 'rtt', 'superwatch', 'systemview', 'flash', 'erase', 'reset', 'halt', 'resume', 'step', 'read-flash'}


def run(args):
    project = getattr(args, 'project_root', None)
    if project in (None, '.'):
        project = getattr(args, 'project_root_positional', None)
    duration = getattr(args, 'duration', 0)
    if not math.isfinite(duration) or duration < 0:
        raise SystemExit('duration must be finite and nonnegative')
    if getattr(args, 'save', None):
        raise SystemExit('Shared memory reads do not support --save to probe storage')
    if any(getattr(args, key, None) for key in ('svd', 'chip', 'target_id')):
        raise SystemExit('Select the peripheral catalog in the shared GUI first')
    if (getattr(args, 'host', '127.0.0.1') != '127.0.0.1'
            or getattr(args, 'port_http', 0) != 0 or getattr(args, 'max_points', 500) != 500):
        raise SystemExit('Shared visualization uses the backend GUI; private host/port/chart overrides are unsupported')
    client = RuntimeClient(project_root=project or '.', kind='cli', name='CLI '+args.command)
    owned_stream = None
    try:
        client.connect(project_root=project, port=getattr(args, 'port', None), probe=getattr(args, 'probe', None),
                       axf=getattr(args, 'source', None), elf_backend=getattr(args, 'elf_backend', None))
        if args.command in {'flash', 'erase', 'reset'}:
            from mklink.runtime import request
            arguments = {}
            if args.command == 'flash':
                if not args.hex:
                    raise RuntimeErrorResponse('Shared flash requires an explicit --hex firmware path')
                from pathlib import Path
                arguments = {'firmware': str(Path(args.hex).resolve()), 'verify': True, 'reset_after': True}
            request_id = getattr(args, 'request_id', None) or str(uuid.uuid4())
            print(json.dumps({'request_id': request_id, 'action': args.command}), flush=True)
            result = request(client.info, 'POST', '/api/runtime/jobs/', {
                'action': args.command, 'arguments': arguments, 'request_id': request_id, 'confirm': True,
                'session_id': client.session_id})
            print(json.dumps({'job_id': result['job_id'], 'state': result['state']}), flush=True)
            while result['state'] not in {'succeeded', 'failed', 'unknown'}:
                time.sleep(.25)
                result = request(client.info, 'GET', '/api/runtime/jobs/'+result['job_id'])
            if result['state'] != 'succeeded':
                raise RuntimeErrorResponse(json.dumps(result, ensure_ascii=False))
        elif args.command == 'device-status':
            result = client.call('device_status')
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
                webbrowser.open(browser_url(client.info))
            deadline = time.monotonic()+duration if duration else None
            print(json.dumps({'capture': stream, 'shared': True, **started}, ensure_ascii=False), flush=True)
            try:
                while deadline is None or time.monotonic() < deadline:
                    time.sleep(min(.25, max(0, deadline-time.monotonic())) if deadline else .25)
            except KeyboardInterrupt:
                pass
            result = client.call(stream+('_values' if stream == 'superwatch' else '_history'))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeErrorResponse, ValueError) as exc:
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
