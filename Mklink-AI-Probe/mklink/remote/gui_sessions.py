"""Authenticated GUI sessions over the existing negotiated remote client."""
import asyncio
import base64
import json
import secrets
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import StreamingResponse
from mklink.remote.gui_bridge import allowed
from mklink.remote.protocol import PROTOCOL_VERSION
from mklink.remote.client import RemoteClient
from mklink.runtime_api import settle

@dataclass
class Window:
    client: RemoteClient
    identity: dict
    capabilities: list
    token: str = field(repr=False)
    sockets: set = field(default_factory=set)
    opening: int = 0
    touched: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    failed: bool = False

    def snapshot(self):
        return {'endpoint': self.client.url, 'identity': self.identity,
                'capabilities': self.capabilities, 'connected': not self.failed}


def install_remote_windows(app, api, *, client_factory=RemoteClient):
    router = APIRouter(prefix='/remote-windows')
    windows = {}
    creating = 0
    reaper = None
    app.state.remote_window_activity = lambda: bool(windows or creating)

    async def blocking(fn):
        return await settle(asyncio.create_task(asyncio.to_thread(fn)))

    async def close(key):
        window = windows.pop(key, None)
        if window:
            async with window.lock:
                window.failed = True
                await blocking(window.client.close)
                for socket in list(window.sockets): await socket.close()

    async def reap():
        while True:
            await asyncio.sleep(15)
            for key, window in list(windows.items()):
                if not window.lock.locked() and time.monotonic() - window.touched > 90:
                    await close(key)

    async def startup():
        nonlocal reaper
        reaper = asyncio.create_task(reap())

    async def shutdown():
        if reaper:
            reaper.cancel()
            try: await reaper
            except asyncio.CancelledError: pass
        for key in list(windows): await close(key)

    app.add_event_handler('startup', startup)
    app.add_event_handler('shutdown', shutdown)

    @router.post('')
    async def connect(body: dict):
        nonlocal creating
        if body.keys() != {'url', 'token'} or not isinstance(body['url'], str) or not isinstance(body['token'], str) or not 1 <= len(body['token']) <= 1024 or len(body['url']) > 2048:
            raise HTTPException(422, 'Supply a remote URL and access token')
        if len(windows) + creating >= 8:
            raise HTTPException(429, 'Close an existing remote window first')
        creating += 1
        holder = []
        def create():
            client = client_factory(body['url'], token=body['token'], timeout=8)
            holder.append(client)
            status = client.call('agent.connect')
            if not status.get('connected'):
                raise ValueError('Remote probe is not connected; connect it at the remote service first')
            identity = client.call('probe.info')
            if not isinstance(identity, dict) or not identity.get('probe_id'):
                raise ValueError('Remote service must provide a bound probe identity; update the remote service')
            capabilities = [name for name, capability in client.handshake().capabilities.items()
                            if capability.available and (name != 'stream.rtt' or str(capability.version) == '2')]
            if 'gui.bridge' not in capabilities or not identity.get('runtime_instance_id'):
                raise ValueError('Update the remote service to support the unified GUI')
            return Window(client, identity, capabilities, body['token'])
        try:
            window = await blocking(create)
            key = secrets.token_urlsafe(24)
            windows[key] = window
            return {'id': key, **window.snapshot()}
        except BaseException as error:
            for client in holder: await blocking(client.close)
            if isinstance(error, asyncio.CancelledError): raise
            if isinstance(error, ValueError): raise HTTPException(422, str(error)) from None
            raise HTTPException(502, 'Remote authentication or connection failed; no operation was retried') from None
        finally: creating -= 1

    def get(key):
        window = windows.get(key)
        if window is None: raise HTTPException(404, 'Remote window expired; reconnect explicitly')
        window.touched = time.monotonic()
        return window

    @router.get('/{key}')
    async def status(key: str):
        return get(key).snapshot()

    @router.post('/{key}/open')
    async def open_window(key: str):
        get(key)
        import webbrowser
        info = app.state.shared_runtime.info
        url = f"http://127.0.0.1:{info['port']}/_runtime/open?page=remote/{key}#{info['token']}"
        if not await asyncio.to_thread(webbrowser.open, url):
            raise HTTPException(503, 'Could not open the browser')
        return {'opened': True}

    @router.post('/{key}/close')
    async def disconnect(key: str):
        await close(key)
        return {'closed': True}

    async def tunnel(window, mode, path, method='GET', body=b''):
        from websockets.legacy.client import connect as ws_connect
        if window.failed: raise HTTPException(410, 'Remote session disconnected; reconnect explicitly')
        if len(window.sockets) + window.opening >= 32: raise HTTPException(429, 'Too many remote GUI streams')
        socket = None
        window.opening += 1
        try:
            socket = await ws_connect(window.client.url, max_size=4*1024*1024, max_queue=4,
                                      open_timeout=8, close_timeout=2, compression=None)
            window.sockets.add(socket)
            if window.failed: raise HTTPException(410, 'Remote session closed')
            await socket.send(json.dumps({'jsonrpc':'2.0','id':1,'method':'system.handshake',
                'params':{'protocol_version':PROTOCOL_VERSION,'token':window.token}}))
            hello = json.loads(await asyncio.wait_for(socket.recv(), 8))
            if 'error' in hello: raise ValueError('Remote authentication failed')
            await socket.send(json.dumps({'jsonrpc':'2.0','id':2,'method':'gui.tunnel',
                'params':{'mode':mode,'path':path,'method':method,
                          'instance_id':window.identity['runtime_instance_id'],
                          'body':base64.b64encode(body).decode('ascii')}}))
            response = json.loads(await asyncio.wait_for(socket.recv(), 35))
            if 'error' in response: raise ValueError('Remote GUI request rejected; update or reconnect explicitly')
            return socket, response['result']
        except BaseException:
            window.failed = True
            if socket:
                window.sockets.discard(socket)
                await socket.close()
            raise
        finally:
            window.opening -= 1

    @router.api_route('/{key}/api/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
    async def http_proxy(key: str, path: str, request: Request):
        window = get(key)
        target = '/api/' + path
        if request.url.query: target += '?' + request.url.query
        if not allowed(target, request.method):
            raise HTTPException(403, 'This operation is not available in the remote GUI')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 384*1024: raise HTTPException(413, 'Remote GUI request too large')
        try: socket, metadata = await tunnel(window, 'http', target, request.method, bytes(body))
        except Exception: raise HTTPException(410, 'Remote session lost; no local fallback or command replay') from None
        async def response_body():
            try:
                async for chunk in socket:
                    if not isinstance(chunk, bytes): raise ValueError('Invalid remote response')
                    yield chunk
            except Exception:
                window.failed = True
                raise
            finally:
                window.sockets.discard(socket)
                await socket.close()
        return StreamingResponse(response_body(), status_code=metadata['status'],
                                 headers={'Content-Type': metadata['content_type'], 'Cache-Control':'no-store'})

    @router.websocket('/{key}/ws/streams/{stream}')
    async def stream_proxy(key: str, stream: str, websocket: WebSocket):
        target = '/ws/streams/' + stream
        if not allowed(target, 'GET', socket=True):
            await websocket.close(code=1008)
            return
        socket = None
        window = None
        try:
            window = get(key)
            socket, _ = await tunnel(window, 'ws', target)
            await websocket.accept()
            async def send_remote():
                while True:
                    message = await websocket.receive()
                    if message['type'] == 'websocket.disconnect': return
                    await socket.send(message.get('bytes') if message.get('bytes') is not None else message.get('text'))
            async def send_gui():
                async for message in socket:
                    if isinstance(message, bytes): await websocket.send_bytes(message)
                    else: await websocket.send_text(message)
            tasks = [asyncio.create_task(send_remote()), asyncio.create_task(send_gui())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if tasks[1].done(): window.failed = True
                for task in tasks:
                    if task.done() and not task.cancelled() and task.exception():
                        window.failed = True
            finally:
                for task in tasks: task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            if window: window.failed = True
        finally:
            if socket:
                window.sockets.discard(socket)
                await socket.close()
            try: await websocket.close(code=1000 if window and not window.failed else 1011)
            except RuntimeError: pass

    api.include_router(router)
