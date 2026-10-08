"""SystemView analysis uses the existing shared capture and local report renderer."""
from __future__ import annotations

import math
from pathlib import Path
import sys
import time
import webbrowser

from mklink.runtime import RuntimeClient, RuntimeErrorResponse


def collect(client, duration):
    """Subscribe to one capture; never stop a capture borrowed from another client."""
    owned = False
    try:
        started = client.call('systemview_start')
        owned = not started.get('reused')
        cursor = client.call('systemview_capture_history')
        session = cursor['session']
        after = 0 if owned else cursor['next_seq']
        events = []
        deadline = time.monotonic() + duration
        while True:
            status = client.call('systemview_status')
            if status.get('progress_error') or not status.get('running'):
                raise RuntimeErrorResponse(status.get('progress_error') or 'SystemView capture stopped')
            if status.get('paused'):
                raise RuntimeErrorResponse('SystemView capture is paused; report was not generated')
            # Drain only the tail observed at this iteration, even if capture outruns us.
            page = client.call('systemview_capture_history', {'session': session, 'after': after})
            tail = page['latest_seq']
            while True:
                if page['dropped']:
                    raise RuntimeErrorResponse('SystemView history lost events; report was not generated')
                events.extend(event for event in page['points'] if event['capture_seq'] <= tail)
                after = min(page['next_seq'], tail)
                if after >= tail:
                    break
                page = client.call('systemview_capture_history', {'session': session, 'after': after})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                names = status.get('task_names', {})
                for event in events:
                    name = names.get(str(event.get('task_id')), names.get(event.get('task_id')))
                    if name:
                        event['task_name'] = name
                return events, status
            time.sleep(min(.1, remaining))
    finally:
        if owned:
            try:
                client.call('systemview_stop')
            except RuntimeErrorResponse as exc:
                # Another subscriber can prevent stopping; detach without replaying.
                print(f'Capture left running or stop unconfirmed: {exc}', file=sys.stderr)


def run(args):
    if not math.isfinite(args.duration) or args.duration <= 0:
        raise SystemExit('Report duration must be finite and positive')
    project = getattr(args, 'project_root', None)
    if project in (None, '.'):
        project = getattr(args, 'project_root_positional', None)
    client = RuntimeClient(project_root=project or '.', kind='cli', name='CLI '+args.command)
    try:
        client.connect(project_root=project, port=args.port, probe=args.probe)
        events, status = collect(client, args.duration)
    except (RuntimeErrorResponse, ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        try:
            client.close()
        except RuntimeErrorResponse as exc:
            print(f'Could not detach from backend: {exc}', file=sys.stderr)
    from mklink.systemview_analyzer import analyze_events, format_report
    report = analyze_events(events)
    if args.command == 'systemview-analyze':
        print(format_report(report))
        return
    from mklink.systemview_report import generate_html_report
    html = generate_html_report(report, events, meta={'cpu_freq': status.get('cpu_freq', 0)},
                                title='SystemView RTOS 报告')
    out = Path(args.out).expanduser().resolve()
    out.write_text(html, encoding='utf-8')
    print(f'[OK] 报告已生成: {out} ({len(events)} 事件)')
    if not args.no_browser:
        webbrowser.open(out.as_uri())
