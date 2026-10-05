"""Authenticated, fixed-runtime transport for the existing GUI HTTP and WS APIs."""
import asyncio
import base64
import json
import re
from urllib.parse import urlsplit

import httpx
from mklink.remote.protocol import RequestValidationError, result_envelope

# This is an application API boundary, never an arbitrary host/file proxy.
READ_PATHS = {
    '/api/health', '/api/device/status', '/api/resources/status', '/api/dash/conflict-check',
    '/api/config/status', '/api/config', '/api/project', '/api/rtt-config', '/api/profiles',
}
DEVICE_PATHS = {
    'read-memory', 'write-memory', 'halt', 'resume', 'step', 'core-registers',
    'hardfault', 'hardfault-detail', 'debug-speed', 'symbols', 'symbol-catalog',
}
STREAMS = {'rtt', 'rtt-terminal', 'superwatch', 'systemview'}


def allowed(path, method, *, socket=False):
    if not isinstance(path, str) or len(path) > 4096:
        return False
    parsed = urlsplit(path)
    route = parsed.path
    if parsed.scheme or parsed.netloc or parsed.fragment or '%' in route or '\\' in route or '..' in route:
        return False
    if socket:
        return method == 'GET' and route in {f'/ws/streams/{name}' for name in STREAMS} and not parsed.query
    if method == 'GET' and route in READ_PATHS:
        return True
    if route == '/api/rtt-find':
        return method == 'POST'
    if route == '/api/runtime/control/view':
        return method == 'POST'
    if route.startswith('/api/device/') and route.removeprefix('/api/device/') in DEVICE_PATHS:
        return method in {'GET', 'POST'}
    if re.fullmatch(r'/api/dash/(rtt|superwatch|systemview)/[a-zA-Z0-9_/-]+', route):
        return method in {'GET', 'POST', 'PUT', 'DELETE'} and not any(word in route for word in ('logs', 'recording', 'download'))
    if route.startswith('/api/symbols/'):
        return method == 'GET'
    return False


async def relay(left, right):
    async def pipe(source, destination):
        async for message in source:
            await destination.send(message)
    tasks = [asyncio.create_task(pipe(left, right)), asyncio.create_task(pipe(right, left))]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class GuiBridge:
    def __init__(self, info):
        self.info = info
        self.active = 0

    async def __call__(self, socket, request):
        p = request.params
        mode, path, method = p.get('mode'), p.get('path'), p.get('method', 'GET')
        if mode not in {'http', 'ws'} or not allowed(path, method, socket=mode == 'ws'):
            raise RequestValidationError('This remote GUI operation is unavailable')
        if p.get('instance_id') != self.info['instance_id']:
            raise RequestValidationError('Remote backend changed; connect again explicitly')
        if self.active >= 64:
            raise RequestValidationError('Remote GUI connection limit reached')
        self.active += 1
        headers = {'X-Auth-Token': self.info['token']}
        try:
            if mode == 'ws':
                from websockets.legacy.client import connect
                async with connect(f"ws://127.0.0.1:{self.info['port']}{path}", extra_headers=headers,
                                   max_size=4*1024*1024, max_queue=4, compression=None) as upstream:
                    await socket.send(json.dumps(result_envelope({'status': 101}, request.request_id)))
                    await relay(socket, upstream)
                return
            encoded = p.get('body', '')
            if not isinstance(encoded, str) or len(encoded) > 512*1024:
                raise RequestValidationError('Remote GUI request is too large')
            try: body = base64.b64decode(encoded, validate=True)
            except ValueError: raise RequestValidationError('Invalid remote GUI body') from None
            headers['Content-Type'] = 'application/json'
            async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
                async with client.stream(method, f"http://127.0.0.1:{self.info['port']}{path}",
                                         content=body, headers=headers) as response:
                    await socket.send(json.dumps(result_envelope({'status': response.status_code,
                        'content_type': response.headers.get('content-type', 'application/octet-stream')}, request.request_id)))
                    async for chunk in response.aiter_bytes():
                        await socket.send(chunk)
        finally:
            self.active -= 1
            await socket.close()
