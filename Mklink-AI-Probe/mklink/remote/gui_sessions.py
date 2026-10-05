"""Authenticated GUI sessions over the existing negotiated remote client."""
import asyncio
import secrets
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException
from mklink.remote.client import RemoteClient, RemoteConnectionError, RemoteProtocolError
from mklink.runtime_api import settle

OPERATIONS = {
    'probe.info': 'probe.diagnostics',
    'memory.read': 'target.memory', 'memory.write': 'target.memory',
    'target.halt': 'target.debug', 'target.resume': 'target.debug',
    'target.step': 'target.debug', 'registers.core': 'target.debug',
    'rtt.start': 'stream.rtt', 'rtt.read': 'stream.rtt',
    'rtt.write': 'stream.rtt', 'rtt.stop': 'stream.rtt',
}

@dataclass
class Window:
    client: RemoteClient
    identity: dict
    capabilities: list
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

    async def blocking(fn):
        return await settle(asyncio.create_task(asyncio.to_thread(fn)))

    async def close(key):
        window = windows.pop(key, None)
        if window:
            async with window.lock:
                window.failed = True
                await blocking(window.client.close)

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
            return Window(client, identity, capabilities)
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

    @router.post('/{key}/call')
    async def call(key: str, body: dict):
        window = get(key)
        method, params = body.get('method'), body.get('params', {})
        if not isinstance(method, str) or method not in OPERATIONS or not isinstance(params, dict) or body.keys() - {'method', 'params'}:
            raise HTTPException(422, 'Unsupported remote dashboard operation')
        if OPERATIONS[method] not in window.capabilities:
            raise HTTPException(409, 'Remote capability is unavailable')
        if method == 'memory.read' and (type(params.get('size')) is not int or not 1 <= params['size'] <= 4096):
            raise HTTPException(422, 'Read 1..4096 bytes at a time')
        if window.lock.locked(): raise HTTPException(409, 'This remote window already has an operation in progress')
        async with window.lock:
            if window.failed: raise HTTPException(410, 'Remote connection lost; reconnect explicitly, do not replay commands')
            try:
                return await blocking(lambda: window.client.call(method, **params))
            except RemoteProtocolError as error:
                raise HTTPException(409, error.message) from None
            except RemoteConnectionError:
                window.failed = True
                await blocking(window.client.close)
                raise HTTPException(410, 'Remote connection lost; result may be unknown. No local fallback or retry occurred') from None
            finally: window.touched = time.monotonic()

    api.include_router(router)
