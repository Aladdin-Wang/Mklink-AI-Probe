from mklink.systemview_analyzer import analyze_events, task_intervals
from mklink.systemview_report import compute_intervals, generate_html_report


def test_freertos_implicit_switches_share_analysis_and_html_intervals():
    events = [
        {'kind': 'task_start_exec', 'task_id': 1, 'task_name': 'Wave', 't_us': 0},
        {'kind': 'task_start_exec', 'task_id': 2, 'task_name': 'Telemetry', 't_us': 10},
        {'kind': 'idle', 't_us': 30},
        {'kind': 'task_start_exec', 'task_id': 1, 't_us': 100},
        {'kind': 'trace_stop', 't_us': 110},
    ]
    expected = [
        {'tid': 1, 'name': 'Wave', 'start': 0, 'end': 10},
        {'tid': 2, 'name': 'Telemetry', 'start': 10, 'end': 30},
        {'tid': 1, 'name': 'Wave', 'start': 100, 'end': 110},
    ]
    assert task_intervals(events) == compute_intervals(events) == expected
    report = analyze_events(events)
    assert {t['name']: t['run_us'] for t in report['tasks']} == {'Wave': 20, 'Telemetry': 20}
    assert report['summary']['task_count'] == 2
    assert report['summary']['idle_pct'] == 63.64
    assert {t['cpu_pct'] for t in report['tasks']} == {18.18}
    assert not any(a['kind'] in ('cpu_starvation', 'near_capacity') for a in report['anomalies'])
    html = generate_html_report(report, events)
    assert 'Wave' in html and 'Telemetry' in html
    assert '<script type="module">' in html
    assert 'export function exactTickFromOffset' in html
    assert 'export class SvTimeline' in html


def test_nested_interrupts_exclude_isr_time_and_scheduler_does_not_resume_task():
    events = [
        {'kind': 'task_start_exec', 'task_id': 1, 't_us': 0},
        {'kind': 'isr_enter', 't_us': 10},
        {'kind': 'isr_enter', 't_us': 12},
        {'kind': 'isr_exit', 't_us': 14},
        {'kind': 'isr_exit', 't_us': 20},
        {'kind': 'isr_enter', 't_us': 30},
        {'kind': 'isr_to_scheduler', 't_us': 40},
        {'kind': 'isr_exit', 't_us': 45},
        {'kind': 'task_start_exec', 'task_id': 2, 't_us': 50},
        {'kind': 'task_stop_exec', 'task_id': 1, 't_us': 60},
        {'kind': 'task_stop_exec', 'task_id': 2, 't_us': 70},
    ]
    assert [(i['tid'], i['start'], i['end']) for i in task_intervals(events)] == [
        (1, 0, 10), (1, 20, 30), (2, 50, 70),
    ]
    report = analyze_events(events)
    assert report['isr']['total_us'] == 20  # Not 22: nested ISR is not double-counted.
    assert report['summary']['idle_pct'] is None
    assert not any(a['kind'] == 'near_capacity' for a in report['anomalies'])


def test_overflow_discards_open_slice_and_capture_end_does_not_invent_stop():
    events = [
        {'kind': 'task_start_exec', 'task_id': 1, 't_us': 0},
        {'kind': 'overflow', 't_us': 1000},
        {'kind': 'task_stop_exec', 'task_id': 1, 't_us': 1001},
        {'kind': 'task_start_exec', 'task_id': 2, 't_us': 1010},
        {'kind': 'task_stop_ready', 'task_id': 2, 't_us': 1020},
        {'kind': 'task_start_exec', 'task_id': 3, 't_us': 1030},
        {'kind': 'task_info', 'task_id': 2, 'name': 'Named later', 't_us': 1040},
    ]
    assert task_intervals(events) == [
        {'tid': 2, 'name': 'Named later', 'start': 1010, 'end': 1020},
    ]


def test_analysis_starts_after_latest_target_overflow_gap():
    events = [
        {"kind": "task_start_exec", "task_id": 1, "t_us": 10.0},
        {
            "kind": "overflow",
            "drop_count": 1234,
            "t_us": 35_000_000.0,
        },
        {"kind": "task_start_exec", "task_id": 2, "t_us": 35_000_100.0},
        {"kind": "task_stop_exec", "task_id": 2, "t_us": 35_000_300.0},
        {"kind": "isr_enter", "t_us": 35_000_400.0},
        {"kind": "isr_exit", "t_us": 35_000_450.0},
        {"kind": "idle", "t_us": 35_001_100.0},
    ]

    report = analyze_events(events)

    assert report["summary"]["event_count"] == 7
    assert report["summary"]["analyzed_event_count"] == 5
    assert report["summary"]["observed_us"] == 1000.0
    assert report["summary"]["target_overflow_events"] == 1
    assert report["summary"]["target_drop_count"] == 1234
    assert report["tasks"][0]["id"] == 2
    assert report["isr"]["cpu_pct"] == 5.0
    assert any(item["kind"] == "trace_overflow" for item in report["anomalies"])
