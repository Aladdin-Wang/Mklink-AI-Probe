from mklink.systemview_analyzer import analyze_events


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
