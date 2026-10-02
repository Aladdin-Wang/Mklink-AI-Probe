import struct
import threading
from types import SimpleNamespace

import pytest

from mklink.dump_memory import decode_frame_to_points
from mklink.rtt_viewer import VisualizationServer
from mklink.superwatch import WatchItem, build_read_blocks, _run_visualizer_stream


@pytest.mark.parametrize("regions,flags", [
    ([(0, b"")], 0), ([(0, b"\x01")], 0), ([], 0),
    ([(1, b"1234")], 0), ([(0, b"1234"), (0, b"1234")], 0),
    ([(0, b"1234")], 4),
])
def test_corrupt_samples_never_become_empty_points(regions, flags):
    with pytest.raises(ValueError):
        decode_frame_to_points({"timestamp_us": 123, "regions": regions, "flags": flags},
                               [(0x20000000, 4, [("value", "float", 0, None)])], None)


def test_sample_health_uses_arrival_time_and_expires(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("mklink.rtt_viewer.time.monotonic", lambda: now[0])
    server = VisualizationServer(mode="SuperWatch", idle_timeout=0)
    server._interval = .05
    server._running.set()
    server.push_data_point({"_t": 0, "timestamp_us": 1})
    assert server._history == []
    for i in range(5):
        now[0] = 100 + i * .05
        server.push_data_point({"_t": i * .05, "timestamp_us": i, "a": i})
        server.push_data_point({"_t": i * .05, "timestamp_us": i, "b": i})
    assert server.sample_health()["estimated_rate"] == pytest.approx(20)
    now[0] += 6
    assert server.sample_health()["state"] == "stalled"
    assert server.sample_health()["estimated_rate"] == 0
    server.set_stream_health("error", "recovery exhausted")
    assert server.sample_health()["stream_error"] == "recovery exhausted"
    server._collection_state = "paused"
    assert server.sample_health()["state"] == "paused"


@pytest.mark.parametrize("first_fault", ["empty", "short", "flags"])
def test_stream_fault_rebuilds_session_and_resumes_values(monkeypatch, first_fault):
    from mklink import dump_memory
    now = [0.0]
    stop = threading.Event()
    sessions = []
    frame = {"timestamp_us": 100, "regions": [(0, struct.pack('<f', 2.5))]}

    class Session:
        def __init__(self, *args):
            self.index = len(sessions)
            self.stopped = False
            sessions.append(self)
        def start(self):
            pass
        def read_frames(self):
            now[0] += 1
            if self.index == 0:
                if first_fault == "empty":
                    return []
                return [{**frame, "flags": 4}] if first_fault == "flags" else [
                    {**frame, "regions": [(0, b"")]}
                ]
            return [frame]
        def stop(self):
            self.stopped = True

    monkeypatch.setattr(dump_memory, "DumpMemoryStreamSession", Session)
    server = VisualizationServer(mode="SuperWatch", idle_timeout=0)
    server._interval = .05
    server._running.set()
    pushed = []
    def push(point):
        pushed.append(point)
        stop.set()
    server.push_data_point = push
    runtime = SimpleNamespace(blocks=build_read_blocks([WatchItem('a', 0x20000000, 'float', 4)]), blocks_version=0)
    _run_visualizer_stream(None, server, runtime, stop, threading.Event(), clock=lambda: now[0], stall_timeout=.1)
    assert len(sessions) == 2
    assert all(session.stopped for session in sessions)
    assert pushed == [{"_t": 0, "timestamp_us": 100, "a": 2.5}]


@pytest.mark.parametrize("stop_failure", [False, True])
def test_recovery_is_bounded_and_failed_stop_never_restarts(monkeypatch, stop_failure):
    from mklink import dump_memory
    sessions = []
    class Session:
        def __init__(self, *args):
            sessions.append(self)
        def start(self):
            pass
        def read_frames(self):
            return [{"timestamp_us": 0, "regions": [], "flags": 4}]
        def stop(self):
            if stop_failure:
                raise TimeoutError('no prompt')
    monkeypatch.setattr(dump_memory, "DumpMemoryStreamSession", Session)
    server = VisualizationServer(mode="SuperWatch", idle_timeout=0)
    server._interval = .05
    runtime = SimpleNamespace(blocks=build_read_blocks([WatchItem('a', 0x20000000, 'float', 4)]), blocks_version=0)
    _run_visualizer_stream(None, server, runtime, threading.Event(), threading.Event(), max_recoveries=1)
    assert len(sessions) == (1 if stop_failure else 2)
    assert server.sample_health()["state"] == "error"
