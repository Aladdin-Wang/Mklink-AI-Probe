"""Exercise the active shared MCP adapter, separately from legacy tool tests."""
import asyncio
import io
import subprocess
import sys

import pytest
from fastmcp import Client

from mklink import runtime_mcp
from test_shared_device import shared
from test_shared_runtime import runtime


@pytest.mark.parametrize('legacy', [False, True])
def test_offline_analysis_available_without_connect_and_preserves_trace_gaps(monkeypatch, legacy):
    from mklink import mcp_server
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline analysis attempted a device connection')
    monkeypatch.setattr(runtime_mcp, 'RuntimeClient', forbidden)
    monkeypatch.setattr(mcp_server, '_connected_device', forbidden)
    server = mcp_server.build_server() if legacy else runtime_mcp.build_server()
    async def scenario():
        async with Client(server) as mcp:
            names = [tool.name for tool in await mcp.list_tools()]
            assert names.count('systemview_decode') == names.count('systemview_analyze_events') == 1
            decoded = await mcp.call_tool('systemview_decode', {'hex_bytes': '11 01'})
            assert decoded.data['events'] == [{'kind': 'idle', 'delta_ticks': 1, 't_ticks': 1}]
            assert decoded.data['event_count'] == 1 and decoded.data['bytes_read'] == 2
            assert decoded.data['dropped_bytes'] == decoded.data['dropped_packets'] == 0
            invalid = await mcp.call_tool('systemview_decode', {'hex_bytes': '0x11'}, raise_on_error=False)
            assert invalid.is_error
            report = await mcp.call_tool('systemview_analyze_events', {'events': [
                {'kind': 'task_start_exec', 'task_id': 1, 't_us': 10},
                {'kind': 'overflow', 'drop_count': 1234, 't_us': 35000000},
                {'kind': 'task_start_exec', 'task_id': 2, 't_us': 35000100},
                {'kind': 'task_stop_exec', 'task_id': 2, 't_us': 35000300},
                {'kind': 'idle', 't_us': 35001100},
            ]})
            assert report.data['summary']['target_drop_count'] == 1234
            assert report.data['summary']['observed_us'] == 1000
            assert [task['id'] for task in report.data['tasks']] == [2]
            empty = await mcp.call_tool('systemview_analyze_events', {'events': []})
            assert empty.data['anomalies'][0]['kind'] == 'no_data'
    asyncio.run(scenario())


def test_mcp_debug_speed_uses_shared_admission_without_retry(shared):
    _, _, calls, managers, app = shared
    from fastapi import HTTPException
    @app.post('/api/device/debug-speed')
    async def speed(body: dict):
        calls.append(body)
        raise HTTPException(500, 'unknown clock result')
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect', {'probe': 'test'})
            managers['rtt'].running = True
            refused = await mcp.call_tool('set_debug_speed', {'profile': 'low'}, raise_on_error=False)
            assert refused.is_error and not calls and managers['rtt'].running
            # Offline tools remain available even while capture owns the bridge.
            assert not (await mcp.call_tool('systemview_decode', {'hex_bytes': '1101'})).is_error
            managers['rtt'].running = False
            failed = await mcp.call_tool('set_debug_speed', {'profile': 'low'}, raise_on_error=False)
            assert failed.is_error
    asyncio.run(scenario())
    assert calls == [{'profile': 'low'}]


def test_shared_stdio_does_not_import_legacy_device_server():
    result = subprocess.run([sys.executable, '-c', '''
import sys
import asyncio
from fastmcp import Client
from mklink import runtime_mcp
async def offline():
    async with Client(runtime_mcp.build_server()) as client:
        assert not (await client.call_tool('systemview_decode', {'hex_bytes': '1101'})).is_error
        assert not (await client.call_tool('systemview_analyze_events', {'events': []})).is_error
asyncio.run(offline())
assert 'mklink.mcp_server' not in sys.modules
assert 'mklink.mcp_stream_bridge' not in sys.modules
class Server:
    def run(self, **kwargs):
        assert kwargs == {'transport': 'stdio', 'show_banner': False}
        assert 'mklink.mcp_server' not in sys.modules
        assert 'mklink.mcp_stream_bridge' not in sys.modules
runtime_mcp.build_server = Server
runtime_mcp.run()
assert 'mklink.mcp_server' not in sys.modules
'''], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_shared_stdio_restores_stdout_on_transport_error(monkeypatch):
    raw = io.BytesIO()
    protocol = io.TextIOWrapper(raw, encoding='utf-8')
    diagnostics = io.StringIO()
    class Server:
        def run(self, **kwargs):
            print('diagnostic')
            sys.stdout.buffer.write(b'{"jsonrpc":"2.0"}\n')
            sys.stdout.buffer.flush()
            raise RuntimeError('transport exit')
    monkeypatch.setattr(runtime_mcp, 'build_server', Server)
    monkeypatch.setattr(sys, 'stdout', protocol)
    monkeypatch.setattr(sys, 'stderr', diagnostics)
    with pytest.raises(RuntimeError, match='transport exit'):
        runtime_mcp.run()
    assert sys.stdout is protocol
    assert raw.getvalue() == b'{"jsonrpc":"2.0"}\n'
    assert diagnostics.getvalue() == 'diagnostic\n'


def test_mcp_lifespan_detaches_only_its_session_and_keeps_gui_capture(shared):
    http, control, calls, managers, _ = shared
    other = http.post('/_runtime/attach', json={'kind': 'sdk'}).json()['session_id']
    managers['rtt'].running = True
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect', {'probe': 'test'})
            assert len(control.sessions) == 2
            await mcp.call_tool('rtt_start')
            result = await mcp.call_tool('rtt_history')
            assert not result.is_error
            # Exit without the disconnect tool: the server lifecycle owns cleanup.
        assert list(control.sessions) == [other]
    asyncio.run(scenario())
    assert managers['rtt'].running and calls == []


def test_mcp_job_submission_uses_shared_session_and_can_query_after_disconnect(shared):
    _, control, calls, _, app = shared
    from fastapi import HTTPException
    @app.post('/api/device/reset')
    async def reset():
        calls.append('reset')
        raise HTTPException(500, 'unknown transport result')
    async def scenario():
        async with Client(runtime_mcp.build_server()) as mcp:
            await mcp.call_tool('connect', {'probe': 'test'})
            refused = await mcp.call_tool('start_job', {'action': 'reset', 'request_id': 'once'}, raise_on_error=False)
            assert refused.is_error and calls == []
            result = await mcp.call_tool('start_job', {'action': 'reset', 'request_id': 'once', 'confirm': True})
            job_id = result.data['job_id']
            for _ in range(100):
                status = await mcp.call_tool('job_status', {'job_id': job_id})
                if status.data['state'] != 'running':
                    break
                await asyncio.sleep(.01)
            assert status.data['state'] == 'unknown'
            duplicate = await mcp.call_tool('start_job', {'action': 'reset', 'request_id': 'once', 'confirm': True})
            assert duplicate.data['job_id'] == job_id
            await mcp.call_tool('disconnect')
            assert not control.sessions
            assert (await mcp.call_tool('job_status', {'job_id': job_id})).data['state'] == 'unknown'
        assert not control.sessions
    asyncio.run(scenario())
    assert calls == ['reset']
