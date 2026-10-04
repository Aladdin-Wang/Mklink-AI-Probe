from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import httpx

from mklink.runtime_proxy import create_proxy


def test_desktop_proxy_auth_stream_and_shutdown_do_not_stop_runtime():
    upstream = FastAPI()
    seen = []

    @upstream.get('/api/health')
    async def health(request: Request):
        seen.append(request.headers.get('x-auth-token'))
        return {'status': 'ok', 'shared_runtime': True}

    @upstream.post('/api/device/read-memory')
    async def read(request: Request):
        seen.append(await request.json())
        return {'data_hex': '12345678'}

    info = {'port': 8765, 'token': 'secret'}
    app = create_proxy(info, port=8766, instance_id='desktop', transport=httpx.ASGITransport(app=upstream))
    stopped = []
    app.state.shutdown = lambda: stopped.append('adapter')
    with TestClient(app, base_url='http://127.0.0.1:8766') as client:
        assert client.get('/api/health').json()['desktop_instance_id'] == 'desktop'
        assert seen == ['secret']
        assert client.post('/api/device/read-memory', json={'size': 4}).json() == {'data_hex': '12345678'}
        assert seen[-1] == {'size': 4}
        assert client.get('/api/health', headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.get('/_runtime/stop').status_code == 403
        response = client.post('/api/desktop/shutdown', json={'instance_id': 'desktop'})
        assert response.json()['shared_runtime_stopped'] is False
        assert stopped == ['adapter']


def test_desktop_proxy_cors_is_limited_to_native_origins():
    app = create_proxy({'port': 8765, 'token': 'secret'}, port=8766, instance_id='desktop')
    with TestClient(app, base_url='http://127.0.0.1:8766') as client:
        headers = {'Origin': 'http://tauri.localhost', 'Access-Control-Request-Method': 'POST'}
        assert client.options('/api/device/connect', headers=headers).status_code == 200
        headers['Origin'] = 'https://evil.example'
        assert client.options('/api/device/connect', headers=headers).status_code == 403


def test_remote_service_proxy_allowlist_preserves_internal_runtime_boundary():
    upstream = FastAPI()
    seen = []
    @upstream.api_route('/{path:path}', methods=['GET','POST','DELETE'])
    async def echo(request: Request, path: str):
        seen.append((request.method, path, request.headers.get('x-auth-token'), request.headers.get('origin')))
        return {'path':path}
    app = create_proxy({'port':8765,'token':'backend-secret'},port=8766,instance_id='desktop',transport=httpx.ASGITransport(app=upstream))
    with TestClient(app,base_url='http://127.0.0.1:8766') as client:
        headers = {'Origin':'http://tauri.localhost'}
        for method,path in [('GET','/_runtime/remote-service'),('POST','/_runtime/remote-service'),
                            ('GET','/_runtime/remote-service/addresses'),('POST','/_runtime/remote-service/token'),
                            ('POST','/_runtime/remote-service/stop')]:
            response=client.request(method,path,json={},headers=headers)
            assert response.status_code==200,response.text
            assert response.headers['access-control-allow-origin']==headers['Origin']
            assert seen[-1]==(method,path[1:],'backend-secret',None)
        before=len(seen)
        for method,path in [('POST','/_runtime/stop'),('GET','/_runtime/status'),('POST','/_runtime/call'),
                            ('POST','/_runtime/attach'),('DELETE','/_runtime/remote-service'),
                            ('POST','/_runtime/remote-service/extra'),('GET','/_runtime/remote-service/token')]:
            assert client.request(method,path,json={},headers=headers).status_code==403
        assert len(seen)==before
        assert client.options('/_runtime/remote-service',headers={**headers,'Access-Control-Request-Method':'POST'}).status_code==200
        assert client.options('/_runtime/stop',headers={**headers,'Access-Control-Request-Method':'POST'}).status_code==403
        assert client.post('/_runtime/remote-service',json={},headers={'Origin':'https://untrusted.invalid'}).status_code==403
