"""Real backend shutdown after broken binary-stream clients; no probe I/O."""
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

import pytest

from mklink.runtime import control_runtime, discover, request, runtime_lock


@pytest.mark.parametrize('disconnect', ['reset', 'fin', 'open'])
def test_backend_exits_and_releases_owner_after_stream_clients(tmp_path, monkeypatch, disconnect):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR', str(tmp_path / 'runtime'))
    source = Path(__file__).resolve().parents[3]
    environment = dict(os.environ, PYTHONPATH=str(source))
    endpoint = tmp_path / 'runtime/probes/lobby/endpoint.json'
    peers = []
    with (tmp_path / 'launcher.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(
            [sys.executable, '-m', 'mklink', 'runtime', 'serve', '--project-root', str(tmp_path),
             '--port', '0', '--probe-id', 'lobby'],
            cwd=source, env=environment, stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        try:
            deadline = time.monotonic() + 20
            info = None
            while process.poll() is None and time.monotonic() < deadline:
                info = discover('lobby')
                if info is not None:
                    break
                time.sleep(.02)
            assert info is not None, 'Backend never became ready'
            for _ in range(30):
                peer = socket.create_connection(('127.0.0.1', info['port']), timeout=3)
                peers.append(peer)
                peer.sendall((
                    f"GET /ws/streams/superwatch HTTP/1.1\r\nHost: 127.0.0.1:{info['port']}\r\n"
                    "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n"
                    f"Authorization: Bearer {info['token']}\r\n\r\n"
                ).encode())
                header = b''
                while b'\r\n\r\n' not in header:
                    chunk = peer.recv(4096)
                    assert chunk, 'Disconnected before WebSocket upgrade'
                    header += chunk
                assert header.startswith(b'HTTP/1.1 101')
                if disconnect == 'reset':
                    peer.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                    struct.pack('HH' if os.name == 'nt' else 'ii', 1, 0))
                    peer.close()
                elif disconnect == 'fin':
                    peer.shutdown(socket.SHUT_WR)
                    peer.close()
            snapshot = control_runtime(probe='lobby')
            assert snapshot['pid'] == process.pid and snapshot['clients'] == []
            assert control_runtime('stop-backend', probe='lobby', confirm=True) == {'status': 'stopping'}
            assert process.wait(timeout=10) == 0
            assert not endpoint.exists()
            with runtime_lock('owner.lock', 'lobby'):
                pass
        finally:
            for peer in peers:
                peer.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

def test_stalled_listener_drain_still_runs_lifespan_and_releases_owner(tmp_path, monkeypatch):
    monkeypatch.setenv('MKLINK_RUNTIME_DIR',str(tmp_path/'runtime'))
    source=Path(__file__).resolve().parents[3]
    code="""import asyncio
async def stalled(self):
    await asyncio.Event().wait()
asyncio.Server.wait_closed=stalled
from mklink.runtime import serve_runtime
serve_runtime(project_root=%r,port=0,probe_id='lobby')
"""%str(tmp_path)
    with (tmp_path/'stalled.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([sys.executable,'-c',code],cwd=source,
            env=dict(os.environ,PYTHONPATH=str(source)),stdout=log,stderr=log,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+20
            while process.poll() is None and time.monotonic()<deadline:
                info=discover('lobby')
                if info:break
                time.sleep(.02)
            else:pytest.fail('Backend not ready')
            assert request(info,'POST','/_runtime/stop',{'confirm':True})['status']=='stopping'
            assert process.wait(timeout=8)==0
            assert not (tmp_path/'runtime/probes/lobby/endpoint.json').exists()
            with runtime_lock('owner.lock','lobby'):pass
        finally:
            if process.poll() is None:process.terminate();process.wait(5)
    assert 'Application shutdown complete' in (tmp_path/'runtime/probes/lobby/runtime.log').read_text(encoding='utf-8')
