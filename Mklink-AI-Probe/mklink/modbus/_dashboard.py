"""Profile dashboard presentation server; all Modbus I/O uses the shared runtime.

FastAPI owns HTTP/disconnect handling, AsyncBridge owns bounded SSE delivery,
and the runtime owns serial access and transaction cancellation. There is no
dashboard serial client, worker queue, or independently timed write operation.
"""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
import json
import math
from pathlib import Path
import secrets
import signal
import socket
import threading
import time
from typing import Literal
from urllib.parse import urlsplit
import webbrowser

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.concurrency import run_in_threadpool
import uvicorn

from mklink.modbus._format import RegisterSpec
from mklink.modbus._profile import build_addr_index, find_command, resolve_command, validate_param
from mklink.modbus._registers import read_register_values, validate_poll_interval, validate_register_specs
from mklink.modbus._session import validate_slave, validate_transaction
from mklink.remote.dashboards import AsyncBridge, _sse_json
from mklink.runtime import RuntimeClient, RuntimeErrorResponse


class _Body(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    token: str


class _Write(_Body):
    addr: StrictInt
    value: StrictInt


class _Command(_Body):
    action: str
    params: dict[str, StrictInt] = Field(default_factory=dict)


class _Read(_Body):
    fc: StrictInt
    start: StrictInt
    quantity: StrictInt = 1


class _DebugWrite(_Body):
    fc: StrictInt
    start: StrictInt
    values: list[StrictInt | StrictBool]


class _Language(_Body):
    lang: Literal['zh', 'en']


class ModbusDashboardServer:
    """Serve a profile UI using an attached RuntimeClient owned by the caller."""

    def __init__(self, client: RuntimeClient, slave: int, profile: dict,
                 host: str = '127.0.0.1', port: int = 0, max_points: int = 500,
                 fast_interval: float = 1.0, slow_interval: float = 5.0,
                 enable_remote_writes: bool = False, allow_arbitrary_writes: bool = False,
                 html_path: str | None = None, idle_timeout: float = 300.0):
        self._client = client
        self._slave = validate_slave(slave)
        self._profile = profile
        self._host, self._port = host, port
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('HTTP port must be in the range 0..65535')
        if type(max_points) is not int or not 1 <= max_points <= 10000:
            raise ValueError('max_points must be in the range 1..10000')
        if isinstance(idle_timeout, bool) or not math.isfinite(idle_timeout) or idle_timeout < 0:
            raise ValueError('idle_timeout must be finite and non-negative')
        self._max_points, self._idle_timeout = max_points, idle_timeout
        self._intervals = [validate_poll_interval(fast_interval), validate_poll_interval(slow_interval)]
        self._specs: list[list[RegisterSpec]] = [[], []]
        for group in profile.get('groups', []):
            poll_group = group.get('poll_group', 'fast')
            if poll_group not in ('fast', 'slow'):
                raise ValueError('Profile poll_group must be fast or slow')
            for reg in group.get('registers', []):
                if not reg.get('hidden'):
                    self._specs[poll_group == 'slow'].append(RegisterSpec(
                        addr=reg['addr'], type=reg.get('type', 'uint16'), name=reg.get('name', ''),
                        register_type=reg.get('register_type', 'holding')))
        validate_register_specs(self._specs[0] + self._specs[1])
        for specs in self._specs:
            specs.sort(key=lambda spec: (spec.register_type, spec.addr))
        self._addr_index = build_addr_index(profile)
        self._root = Path.cwd()
        self._html_path = Path(html_path).resolve() if html_path else None
        if self._html_path and not self._html_path.is_file():
            raise FileNotFoundError(self._html_path)
        self._enable_remote_writes = enable_remote_writes
        self._allow_arbitrary_writes = allow_arbitrary_writes
        self._csrf_token = secrets.token_hex(16)
        self._bridge = AsyncBridge()
        self._history: deque = deque(maxlen=max_points)
        self._latest: dict = {}
        self._stopping = threading.Event()
        self._finished = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self._error: BaseException | None = None
        self.app = self._create_app()

    def _transaction(self, fc, start, *, quantity=None, values=None):
        fc, start, quantity, values = validate_transaction(fc, start, quantity=quantity, values=values)
        if self._stopping.is_set():
            raise RuntimeErrorResponse('Dashboard is stopping', status_code=503)
        params = {'slave': self._slave, 'fc': fc, 'start': start}
        params.update({'quantity': quantity} if quantity is not None else {'values': values})
        return self._client.call('modbus_transaction', params)

    async def _poll(self):
        deadlines = [0.0, 0.0]
        idle_since = time.monotonic()
        try:
            while not self._stopping.is_set():
                now = time.monotonic()
                if self._bridge.client_count:
                    idle_since = now
                elif self._idle_timeout and now - idle_since >= self._idle_timeout:
                    self.request_stop()
                    break
                registers = {}
                for index, specs in enumerate(self._specs):
                    if specs and now >= deadlines[index] and not self._stopping.is_set():
                        data = await run_in_threadpool(read_register_values,
                            lambda fc, address, count: self._transaction(fc, address, quantity=count)['values'], specs)
                        registers.update(data)
                        deadlines[index] = time.monotonic() + self._intervals[index]
                if registers and not self._stopping.is_set():
                    self.push_snapshot({'_t': time.time(), 'registers': registers})
                delay = min([1.0] + [max(.01, deadlines[i] - time.monotonic())
                                      for i, specs in enumerate(self._specs) if specs])
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
        except Exception as exc:
            if not self._stopping.is_set():
                self._error = exc
                self.push_event('poll_error', {'error': str(exc), 'ok': False})
                self.request_stop()

    def _authorize(self, request: Request, body: _Body):
        if self._stopping.is_set():
            raise HTTPException(503, 'Dashboard is stopping')
        if not secrets.compare_digest(body.token.encode('utf-8'), self._csrf_token.encode('ascii')):
            raise HTTPException(403, 'CSRF token mismatch')
        origin = request.headers.get('origin')
        if origin and not self._enable_remote_writes:
            actual, expected = urlsplit(origin), urlsplit(str(request.base_url))
            if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
                raise HTTPException(403, 'Cross-origin writes are disabled')

    def _validate_write(self, addr, value):
        ok, message = validate_param(self._profile, addr, value)
        if not ok:
            raise ValueError(message)

    def _create_app(self):
        @asynccontextmanager
        async def lifespan(app):
            self._loop = asyncio.get_running_loop()
            self._wake = asyncio.Event()
            poll = asyncio.create_task(self._poll())
            try:
                yield
            finally:
                self.request_stop()
                # Drain the current RPC before the caller detaches its session.
                await poll

        app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

        async def error_response(request, exc):
            status = getattr(exc, 'status_code', None) or (502 if isinstance(exc, (OSError, RuntimeErrorResponse)) else 422)
            event = {'/write': 'write_result', '/command': 'command_result',
                     '/debug/read': 'debug_result', '/debug/write': 'debug_result'}.get(request.url.path)
            if event and isinstance(exc, (OSError, RuntimeErrorResponse)):
                self.push_event(event, {'ok': False, 'error': str(exc)})
            return JSONResponse({'ok': False, 'error': str(getattr(exc, 'detail', exc))}, status_code=status)

        for error in (ValueError, OSError, RuntimeErrorResponse, HTTPException, RequestValidationError):
            app.add_exception_handler(error, error_response)

        @app.get('/', response_class=HTMLResponse)
        @app.get('/index.html', response_class=HTMLResponse)
        def html():
            from mklink.modbus._dashboard_html import build_html
            path = self._html_path or self._root / '.mklink/modbus_dashboard.html'
            if path.is_file():
                return path.read_text(encoding='utf-8')
            return build_html(self._max_points, json.dumps(self._profile), self._csrf_token, project_root=self._root)

        @app.get('/profile')
        async def profile():
            return self._profile

        @app.get('/snapshot')
        async def snapshot():
            return self._latest

        @app.get('/csrf-token')
        async def csrf():
            return {'token': self._csrf_token}

        @app.get('/stream')
        async def stream():
            async def events():
                queue = self._bridge.add_client()
                try:
                    if self._stopping.is_set():
                        yield _sse_json({'_event': 'shutdown'})
                        return
                    for point in list(self._history):
                        yield _sse_json(point)
                    while True:
                        try:
                            data = await asyncio.wait_for(queue.get(), timeout=15)
                        except asyncio.TimeoutError:
                            yield ':ping\n\n'
                            continue
                        if data is None:
                            yield _sse_json({'_event': 'shutdown'})
                            return
                        yield _sse_json(data)
                finally:
                    self._bridge.remove_client(queue)
            return StreamingResponse(events(), media_type='text/event-stream',
                                     headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

        @app.post('/write')
        async def write(request: Request, body: _Write):
            self._authorize(request, body)
            self._validate_write(body.addr, body.value)
            await run_in_threadpool(self._transaction, 6, body.addr, values=[body.value])
            self.push_event('write_result', {'ok': True, 'addr': body.addr, 'value': body.value,
                                          'name': self._addr_index.get(body.addr, {}).get('name', str(body.addr))})
            return {'ok': True, 'message': 'Write successful'}

        @app.post('/command')
        async def command(request: Request, body: _Command):
            self._authorize(request, body)
            ok, address, value, message = resolve_command(self._profile, body.action)
            if not ok:
                raise ValueError(message)
            definition = find_command(self._profile, body.action)
            params = definition.get('params', [])
            # This protocol writes one register. Never silently discard parameters.
            if len(params) > 1 or set(body.params) != {p['name'] for p in params}:
                raise ValueError('Command requires its declared parameters and at most one value')
            for param in params:
                value = body.params[param['name']]
                if value < param.get('min', 0) or value > param.get('max', 65535):
                    raise ValueError(f"{param['name']} is out of range")
            await run_in_threadpool(self._transaction, 6, address, values=[value])
            self.push_event('command_result', {'ok': True, 'action': body.action,
                                              'write_addr': address, 'write_value': value})
            return {'ok': True, 'message': f"Command '{body.action}' sent"}

        @app.post('/debug/read')
        async def debug_read(request: Request, body: _Read):
            self._authorize(request, body)
            if body.fc not in (1, 2, 3, 4):
                raise ValueError('Read function code must be 1, 2, 3, or 4')
            result = await run_in_threadpool(self._transaction, body.fc, body.start, quantity=body.quantity)
            payload = {'ok': True, 'fc': body.fc, 'start': body.start, 'quantity': body.quantity,
                       'values': result['values']}
            self.push_event('debug_result', payload)
            return payload

        @app.post('/debug/write')
        async def debug_write(request: Request, body: _DebugWrite):
            self._authorize(request, body)
            if body.fc not in (5, 6, 15, 16):
                raise ValueError('Write function code must be 5, 6, 15, or 16')
            fc, start, _, values = validate_transaction(body.fc, body.start, values=body.values)
            if not self._allow_arbitrary_writes:
                for offset, value in enumerate(values):
                    self._validate_write(start + offset, value)
            await run_in_threadpool(self._transaction, fc, start, values=values)
            payload = {'ok': True, 'fc': fc, 'start': start, 'values': values}
            self.push_event('debug_result', payload)
            return payload

        @app.post('/api/lang')
        async def language(request: Request, body: _Language):
            self._authorize(request, body)
            def save():
                path = self._root / '.mklink/lang.json'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'lang': body.lang}), encoding='utf-8')
            await run_in_threadpool(save)
            return {'status': 'ok', 'lang': body.lang}

        from mklink._static import _STATIC_DIR
        app.mount('/static', StaticFiles(directory=_STATIC_DIR), name='static')
        return app

    def push_snapshot(self, data):
        """Called on the presentation loop after a complete polling cycle."""
        self._latest = {'_t': data['_t'], 'registers': {
            **self._latest.get('registers', {}), **data['registers']}}
        self._history.append(data)
        self._bridge.put(data)

    def push_event(self, event, payload):
        self._bridge.put({'_event': event, **payload})

    def request_stop(self):
        """Reject new operations and wake streams before uvicorn drains handlers."""
        self._stopping.set()
        self._bridge.stop()
        if self._loop and self._wake and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._wake.set)
        if self._server:
            self._server.should_exit = True

    def start(self) -> int:
        if self._thread is not None or self._stopping.is_set():
            raise RuntimeError('Dashboard instances may only be started once')
        listener = socket.socket(socket.AF_INET6 if ':' in self._host else socket.AF_INET)
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((self._host, self._port))
            self._port = listener.getsockname()[1]
            self._server = uvicorn.Server(uvicorn.Config(self.app, log_level='warning',
                lifespan='on', limit_concurrency=32))
            def serve():
                try:
                    self._server.run(sockets=[listener])
                except BaseException as exc:
                    self._error = exc
                finally:
                    listener.close()
                    self._finished.set()
            self._thread = threading.Thread(target=serve, name='modbus-dashboard-http', daemon=True)
            self._thread.start()
            deadline = time.monotonic() + 10
            while not self._server.started:
                if self._finished.wait(.01) or time.monotonic() >= deadline:
                    raise RuntimeErrorResponse(f'Dashboard failed to start: {self._error or "startup timeout"}')
            return self._port
        except BaseException:
            self.stop()
            listener.close()
            raise

    def stop(self):
        """Return only after handlers, polling and the HTTP thread have exited."""
        self.request_stop()
        if self._thread:
            if self._thread is threading.current_thread():
                raise RuntimeError('Use request_stop from the dashboard thread')
            self._thread.join()


def run_modbus_dashboard(client: RuntimeClient, slave: int, profile: dict, *,
                         no_browser: bool = False, duration: float = 0, **options) -> None:
    """Run the UI, draining it before the caller releases its shared session."""
    if isinstance(duration, bool) or not math.isfinite(duration) or duration < 0:
        raise ValueError('duration must be finite and non-negative')
    server = ModbusDashboardServer(client, slave, profile, **options)
    previous_signals = {}
    try:
        port = server.start()
        host = server._host
        url = f'http://{"[" + host + "]" if ":" in host else host}:{port}'
        print(f'[OK] Modbus Dashboard 已启动: {url}')
        if not no_browser:
            webbrowser.open(url)
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, getattr(signal, 'SIGBREAK', signal.SIGTERM)):
                if sig not in previous_signals:
                    previous_signals[sig] = signal.getsignal(sig)
                    signal.signal(sig, lambda *_: server.request_stop())
        deadline = time.monotonic() + duration if duration else math.inf
        while not server._finished.wait(.1) and time.monotonic() < deadline:
            pass
    except KeyboardInterrupt:
        print('\n[*] 用户中断')
    finally:
        server.stop()
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)
    if server._error:
        raise RuntimeErrorResponse(f'Dashboard stopped: {server._error}') from server._error
    print('[OK] Modbus Dashboard 已关闭')
