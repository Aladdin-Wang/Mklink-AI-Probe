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


def test_shared_stdio_does_not_import_legacy_device_server():
    result = subprocess.run([sys.executable, '-c', '''
import sys
from mklink import runtime_mcp
runtime_mcp.build_server()
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
