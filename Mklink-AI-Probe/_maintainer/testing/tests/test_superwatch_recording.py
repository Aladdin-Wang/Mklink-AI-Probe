from array import array
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mklink.superwatch_recording import SuperWatchRecorder
from mklink.remote.dashboards import SuperWatchStreamManager


def rows(directory):
    return [json.loads(line) for path in sorted(directory.glob('*.jsonl'))
            for line in path.read_text(encoding='utf-8').splitlines()]


def manager():
    hub = SimpleNamespace(set_subscribe_callback=lambda callback: None, publish=lambda *a, **kw: None)
    sw = SuperWatchStreamManager(hub)
    sw._metadata_cache = (b'', '[{"name":"value"}]', 1)
    sw._running = True
    sw._collecting.set()
    return sw


def test_acquisition_does_not_record_until_explicit_start(tmp_path):
    sw = manager()
    for i in range(100):
        sw._publish_sample_values_locked([i], channel_count=1, sample_time=i)
    sw._flush_binary_batch()
    assert sw.recording_status() == {'state': 'idle', 'active': False}
    assert not list(tmp_path.iterdir())


def test_recording_keeps_all_samples_beyond_display_buffer_and_drains_tail(tmp_path):
    sw = manager()
    sw._publish_sample_values_locked([-1], channel_count=1, sample_time=0)
    sw.start_recording(str(tmp_path))
    for i in range(60_001):
        sw._publish_sample_values_locked([i], channel_count=1, sample_time=i / 10)
    result = sw.stop_recording()
    sw._publish_sample_values_locked([999999], channel_count=1, sample_time=6001)
    sw._flush_binary_batch()
    data = rows(tmp_path)
    assert result['state'] == 'completed' and result['samples'] == len(data) == 60_001
    assert [r['value'] for r in data] == list(range(60_001))
    assert data[-1]['_t'] == 6
    assert result['bytes'] == sum(p.stat().st_size for p in tmp_path.glob('*.jsonl'))


def test_parts_retain_every_row_and_layout_without_overwriting(tmp_path):
    recorder = SuperWatchRecorder(tmp_path, max_values=3)
    recorder.append(array('f', range(8)), array('d', range(8)), [{'name': 'value'}])
    recorder.append(array('f', [42]), array('d', [8]), [{'name': 'new_name'}])
    result = recorder.stop()
    assert result['parts'] == 4
    assert [r.get('value', r.get('new_name')) for r in rows(tmp_path)] == [*range(8), 42]
    second = SuperWatchRecorder(tmp_path)
    assert second.status()['path'] != result['path']
    second.stop()


def test_overflow_and_disk_error_are_visible_not_success(tmp_path):
    recorder = SuperWatchRecorder(tmp_path, queue_bytes=1)
    recorder.append(array('f', [1]), array('d', [0]), [{'name': 'v'}])
    assert recorder.stop()['state'] == 'failed'
    recorder = SuperWatchRecorder(tmp_path)
    recorder._file.close()
    recorder.append(array('f', [1]), array('d', [0]), [{'name': 'v'}])
    result = recorder.stop()
    assert result['state'] == 'failed' and result['error'] and not result['active']


def test_http_controls_share_manager_and_capture_stop_finalizes(tmp_path, monkeypatch):
    from mklink.remote import api, dashboards
    sw = manager()
    managers = {**dashboards.get_managers(), 'superwatch': sw}
    monkeypatch.setattr(dashboards, 'get_managers', lambda: managers)
    client = TestClient(api.create_app(auth_token=None, project_root=str(tmp_path)))
    base = '/api/dash/superwatch/recording/'
    assert client.post(base + 'start', json={'directory': 'relative'}).status_code == 400
    assert client.post(base + 'start', json={'directory': str(tmp_path)}).status_code == 200
    assert client.post(base + 'start', json={'directory': str(tmp_path)}).status_code == 409
    sw._publish_sample_values_locked([7], channel_count=1, sample_time=100)
    sw.stop()
    result = client.get(base + 'status').json()
    assert result['state'] == 'completed' and result['samples'] == 1
    assert client.post(base + 'stop').json() == result
    assert rows(tmp_path) == [{'value': 7, '_t': .1}]


def test_mcp_recording_actions_use_shared_capabilities(monkeypatch):
    import asyncio
    from fastmcp import Client
    from mklink.runtime_mcp import build_server
    calls = []
    class Adapter:
        info = {}
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): return {'connected': True}
        def call(self, capability, arguments=None):
            calls.append((capability, arguments))
            return {'state': 'completed'}
        def close(self): pass
    # Use the real MCP tool validation and dispatch without opening hardware.
    import mklink.runtime_mcp as runtime_mcp
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', Adapter)
    async def scenario():
        async with Client(build_server()) as client:
            await client.call_tool('connect', {})
            for action in ('recording_start', 'recording_status', 'recording_stop'):
                result = await client.call_tool('superwatch', {'action': action, 'arguments': {}})
                assert not result.is_error
    asyncio.run(scenario())
    assert [name for name, _ in calls] == ['superwatch_recording_start', 'superwatch_recording_status', 'superwatch_recording_stop']
