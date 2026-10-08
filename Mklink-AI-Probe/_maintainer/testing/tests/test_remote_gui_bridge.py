import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from websockets.legacy.client import connect

from mklink.remote.agent import AgentConfig, SiteAgent
from mklink.remote.gui_bridge import GuiBridge, allowed
from mklink.remote.gui_sessions import install_remote_windows
from mklink.remote.protocol import RequestValidationError
from test_remote_agent import _running, _Device


@pytest.mark.parametrize('path,method', [('/_runtime/stop','POST'),('/api/runtime/select','POST'),
    ('/api/device/reboot','POST'),('/api/device/power','POST'),('/api/config','POST'),
    ('http://evil/api/health','GET'),('//evil/api/health','GET'),('/api/dash/rtt/../stop','POST'),
    ('/api/dash/rtt/%2e%2e/stop','POST'),('/api/project-root/browse','GET')])
def test_bridge_rejects_host_management_and_path_escape(path, method):
    assert not allowed(path,method)


def test_existing_dashboard_requests_and_raw_streams_are_supported():
    assert allowed('/api/device/read-memory','POST')
    assert allowed('/api/dash/superwatch/workspace','PUT')
    assert allowed('/api/symbols/catalog?offset=0&limit=500','GET')
    assert allowed('/ws/streams/rtt-terminal','GET',socket=True)
    assert not allowed('/ws/streams/serial','GET',socket=True)


def test_runtime_identity_change_rejected_before_opening_upstream():
    bridge=GuiBridge({'instance_id':'fixed','port':1,'token':'private'})
    request=SimpleNamespace(params={'mode':'http','path':'/api/health','instance_id':'different'},request_id=1)
    with pytest.raises(RequestValidationError): asyncio.run(bridge(None, request))
    assert bridge.active == 0


def test_authenticated_end_to_end_gui_http_uses_only_bound_runtime(monkeypatch):
    seen=[]
    original=httpx.AsyncClient
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'data_hex':'534547474552','address':'0x20000000'})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: original(**kw,transport=httpx.MockTransport(handler)))
    info={'instance_id':'fixed','port':18765,'token':'runtime-secret'}
    def dispatch(method, params, context):
        if method=='probe.info': return {'probe_id':'remote-probe','runtime_instance_id':'fixed','connected':True}
        raise AssertionError(method)
    async def scenario():
        agent=SiteAgent(AgentConfig(port=0,token='remote-secret'),device_factory=lambda **kw:_Device(),
                        request_dispatcher=dispatch,gui_bridge=GuiBridge(info))
        async with _running(agent):
            def exercise():
                app=FastAPI();install_remote_windows(app,app)
                with TestClient(app) as client:
                    r=client.post('/remote-windows',json={'url':f'ws://127.0.0.1:{agent.port}','token':'remote-secret'})
                    assert r.status_code==200,r.text
                    prefix='/remote-windows/'+r.json()['id']
                    response=client.post(prefix+'/api/device/read-memory',json={'address':'0x20000000','size':6})
                    assert response.status_code==200,response.text
                    assert response.json()['data_hex']=='534547474552'
                    assert len(seen)==1
                    assert str(seen[0].url)=='http://127.0.0.1:18765/api/device/read-memory'
                    assert seen[0].headers['x-auth-token']=='runtime-secret'
                    assert client.post(prefix+'/api/device/power',json={}).status_code==403
                    assert len(seen)==1
                    agent.request_stop()
                    assert client.get(prefix+'/api/health').status_code==410
                    assert client.get(prefix+'/api/health').status_code==410
                    assert len(seen)==1
                    client.post(prefix+'/close')
                    assert client.get(prefix+'/api/health').status_code==404
            await asyncio.to_thread(exercise)
    asyncio.run(scenario())


def test_tunnel_requires_authentication_before_dispatch():
    calls=[]
    async def bridge(socket,request): calls.append(request)
    async def scenario():
        agent=SiteAgent(AgentConfig(port=0,token='secret'),device_factory=lambda **kw:_Device(),gui_bridge=bridge)
        async with _running(agent):
            async with connect(f'ws://127.0.0.1:{agent.port}') as socket:
                await socket.send(json.dumps({'jsonrpc':'2.0','id':1,'method':'gui.tunnel','params':{}}))
                response=json.loads(await socket.recv())
                assert 'error' in response
        assert not calls
    asyncio.run(scenario())

def test_binary_stream_preserves_frames_and_closes_only_its_transport():
    from websockets.legacy.server import serve
    seen=[]
    async def upstream(socket, path):
        assert path=='/ws/streams/rtt-terminal'
        assert socket.request_headers['x-auth-token']=='private-runtime'
        await socket.send(b'original-binary-frame')
        seen.append(await socket.recv())
        await socket.send(b'next-frame')
        await socket.wait_closed()
    async def scenario():
        async with serve(upstream,'127.0.0.1',0) as server:
            info={'instance_id':'fixed','port':server.sockets[0].getsockname()[1],'token':'private-runtime'}
            def dispatch(method,params,context):
                return {'probe_id':'fixed-probe','runtime_instance_id':'fixed','connected':True}
            agent=SiteAgent(AgentConfig(port=0,token='secret'),device_factory=lambda **kw:_Device(),
                            request_dispatcher=dispatch,gui_bridge=GuiBridge(info))
            async with _running(agent):
                def exercise():
                    app=FastAPI();install_remote_windows(app,app)
                    with TestClient(app) as client:
                        s=client.post('/remote-windows',json={'url':f'ws://127.0.0.1:{agent.port}','token':'secret'}).json()
                        path='/remote-windows/'+s['id']
                        with client.websocket_connect(path+'/ws/streams/rtt-terminal') as socket:
                            assert socket.receive_bytes()==b'original-binary-frame'
                            socket.send_text('viewer-control')
                            assert socket.receive_bytes()==b'next-frame'
                        assert client.get(path).json()['connected']
                        client.post(path+'/close')
                await asyncio.to_thread(exercise)
        assert seen==['viewer-control']
    asyncio.run(scenario())
