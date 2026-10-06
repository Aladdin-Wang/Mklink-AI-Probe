"""Shared runtime sessions and a bounded, explicit GUI capability surface."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
import hmac
import json
from pathlib import Path
import secrets
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount

from mklink.runtime import PROTOCOL, VERSION
from mklink.runtime_capabilities import CAPABILITIES, STREAMS, LIFECYCLE_CAPABILITIES, UART_CAPABILITIES, is_uart_path, validate_arguments

RESOURCE_RELEASE_PATHS = frozenset({'/api/resources/release-all', '/api/resources/release'})
active_operation = ContextVar('mklink_runtime_operation', default=None)


def operation_session_ended():
    """Read-only worker check; admission stays held until cooperative cleanup."""
    active = active_operation.get()
    if not active or not active[1]:
        return False
    control, session_id = active
    session = control.sessions.get(session_id)
    return session is None or session.expires <= time.monotonic()


async def settle(task):
    """Cancellation cannot release admission while a hardware worker runs."""
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.done():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result


def same_path(left, right):
    return str(Path(left).resolve()).casefold() == str(Path(right).resolve()).casefold()


@dataclass
class Session:
    project_root: str
    axf: str | None
    kind: str = 'mcp'
    name: str = 'AI client'
    symbol_version: tuple | None = None
    public_id: str = field(default_factory=lambda: secrets.token_hex(8))
    joined: float = field(default_factory=time.monotonic)
    expires: float = field(default_factory=lambda: time.monotonic() + 5)
    streams: set = field(default_factory=set)
    scope: str = 'target'


class RuntimeControl:
    def __init__(self, app, info):
        self.app, self.info = app, info
        self.sessions: dict[str, Session] = {}
        self.created_streams: dict[str, str] = {}
        self.attach_lock = asyncio.Lock()
        self.operation_lock = asyncio.Lock()
        self.shutdown = None
        self.stopping = False
        self.views = {}
        self.current_operation = None
        self.last_operation = None
        self.uart_operations: dict[asyncio.Task, str] = {}
        self.started = time.monotonic()
        self.last_activity = self.started
        self.inflight_requests = 0
        self.jobs = None

    @property
    def target_sessions(self):
        return {key: session for key, session in self.sessions.items() if session.scope == 'target'}

    def require_acquisition_control(self, stream, session_id):
        self.prune()
        recover = False
        if session_id:
            session = self.validate_session(session_id, target=stream in STREAMS)
            owner = self.created_streams.get(stream)
            # An explicit control command may recover an abandoned acquisition.
            # No owner entry denotes GUI ownership, which must not be claimed.
            recover = owner is not None and owner not in self.sessions and stream in session.streams
            if owner != session_id and not recover:
                raise HTTPException(409, 'This acquisition was started by another client; detach instead')
        if any(stream in session.streams for key, session in self.sessions.items() if key != session_id):
            raise HTTPException(409, 'Other clients subscribe to this acquisition; detach them before stopping it')
        if recover:
            self.created_streams[stream] = session_id

    def acquisition_stopped(self, stream):
        self.created_streams.pop(stream, None)
        for session in self.sessions.values():
            session.streams.discard(stream)

    def acquisition_started(self, stream, session_id):
        # Called inside the existing manager start transaction, before unlock or
        # HTTP response delivery. A new producer cannot inherit old subscribers.
        self.acquisition_stopped(stream)
        if session_id:
            self.created_streams[stream] = session_id
            session = self.sessions.get(session_id)
            if session is not None:
                session.streams.add(stream)

    def online_job(self):
        services = getattr(self.app.state, 'online_flash', None)
        if services is None:
            return None
        from mklink.remote.online_flash_api import _active_snapshot, _safe_job_snapshot
        return _safe_job_snapshot(_active_snapshot(services.job_manager))

    def job_busy(self):
        return bool((self.jobs and self.jobs.active) or self.online_job())

    def prune(self):
        now = time.monotonic()
        self.sessions = {key: session for key, session in self.sessions.items() if session.expires > now}
        self.views = {key: view for key, view in self.views.items() if view['expires'] > now}

    def presence(self):
        from mklink.probes import inventory
        probes = inventory()
        selected = next((p for p in probes if p['probe_id'] == self.info.get('probe_id')), None)
        device = self.app.state.mklink_state.get('device')
        status = 'present' if selected else 'missing'
        if self.info.get('probe_id') == 'lobby':
            status = 'unselected'
        elif selected and device and device.connected and device.port.casefold() != selected['port'].casefold():
            status = 'port_changed'
        return {'status': status, 'probe': selected, 'probes': probes}

    def require_identity(self):
        if not self.info.get('probe_id'):  # isolated API fixtures
            return
        presence = self.presence()
        if presence['status'] != 'present':
            raise HTTPException(409, {'reason': presence['status'], 'message': 'Bound probe unavailable or port changed; release the old connection and reconnect this same identity explicitly'})

    async def snapshot(self):
        from mklink.remote.dashboards import get_managers
        self.prune()
        now = time.monotonic()
        clients = [{'id': s.public_id, 'kind': s.kind, 'name': s.name, 'scope': s.scope, 'streams': sorted(s.streams),
                    'age_seconds': now-s.joined, 'expires_in': max(0, s.expires-now)} for s in self.sessions.values()]
        clients += [{'id': key, 'kind': 'gui', 'name': view['name'], 'streams': [],
                     'age_seconds': now-view['joined'], 'expires_in': None if view.get('live') else max(0, view['expires']-now)} for key, view in self.views.items()]
        device = self.app.state.mklink_state.get('device')
        return {'protocol': PROTOCOL, 'version': VERSION, 'probe_id': self.info.get('probe_id'),
                'instance_id': self.info['instance_id'], 'pid': self.info.get('pid'),
                'project_root': self.app.state.mklink_state['project_root'], 'transport': 'cdc',
                'uptime_seconds': now-self.started, 'clients': clients, 'busy': self.operation_lock.locked() or self.job_busy(),
                'jobs': list(reversed(list(self.jobs.jobs.values())))[:8] if self.jobs else [], 'online_job': self.online_job(),
                'operation': self.current_operation, 'last_operation': self.last_operation,
                'uart_operations': list(self.uart_operations.values()),
                'connected': bool(device and device.connected),
                'streams': [{'name': name, 'running': manager.running,
                             'subscribers': sum(name in s.streams for s in self.sessions.values())}
                            for name, manager in get_managers().items()],
                **await asyncio.to_thread(self.presence)}

    def session(self, session_id):
        self.prune()
        if not isinstance(session_id, str):
            raise HTTPException(422, "session_id must be a string")
        session = self.sessions.get(session_id)
        if session is None:
            raise HTTPException(409, "Session expired or detached; connect again")
        session.expires = time.monotonic() + 5
        return session

    def symbol_version(self):
        device = self.app.state.mklink_state.get('device')
        catalog = getattr(device, 'symbol_catalog', None)
        if catalog is None:
            return None
        return (catalog.generation, catalog.fingerprint.sha256)

    def validate_session(self, session_id, *, target=True):
        session = self.session(session_id)
        if target and session.scope != 'target':
            raise HTTPException(409, 'UART-only session cannot access the target; detach and attach a target session explicitly')
        state = self.app.state.mklink_state
        if not same_path(session.project_root, state['project_root']):
            raise HTTPException(409, 'Project changed; reconnect explicitly')
        if not target:
            return session
        active_axf = (getattr(state.get('device'), 'axf_status', {}) or {}).get('axf_path')
        if session.axf != active_axf or session.symbol_version != self.symbol_version():
            raise HTTPException(409, 'Symbols changed; reconnect explicitly before reading the new target layout')
        return session

    def require_symbol_change(self):
        from mklink.remote.dashboards import active_bridge_dashboards
        self.prune()
        self.require_identity()
        if self.target_sessions:
            raise HTTPException(409, 'Detach shared clients before changing symbols')
        active = active_bridge_dashboards()
        if active:
            raise HTTPException(409, {'busy': active, 'hint': 'Stop acquisition explicitly before changing symbols'})

    async def run_operation(self, name, operation, *, session_id=None, configuration=False, online_stop=False):
        """Shared admission for HTTP adapters and internal application work.

        Check and reserve without an await gap. Cancellation retains ownership
        until the worker settles; no caller may bypass this by invoking a handler.
        """
        from mklink.runtime_jobs import executing_job
        own_job = self.jobs and self.jobs.active and executing_job.get() == self.jobs.active['job_id']
        if self.stopping:
            raise HTTPException(503, 'Runtime is stopping')
        async def execute():
            token = active_operation.set((self, session_id))
            try:
                return await operation()
            finally:
                active_operation.reset(token)
        if is_uart_path(name):
            if self.current_operation and self.current_operation['path'] in RESOURCE_RELEASE_PATHS:
                raise HTTPException(409, 'Resource release is in progress; wait before using UART')
            if session_id:
                self.validate_session(session_id, target=False)
            if len(self.uart_operations) >= 64:
                raise HTTPException(429, 'Too many independent UART operations in flight')
            # Managers retain their existing port/worker admission. Track these
            # requests only for bounded ingress and safe backend shutdown.
            task = asyncio.create_task(execute())
            self.uart_operations[task] = name
            try:
                return await settle(task)
            finally:
                self.uart_operations.pop(task, None)
        if self.operation_lock.locked() or (self.job_busy() and not own_job and not online_stop):
            raise HTTPException(409, 'Another shared operation or exclusive job is active')
        self.prune()
        if configuration:
            if self.attach_lock.locked():
                raise HTTPException(409, 'Wait for the attaching client before changing symbols')
            self.require_symbol_change()
        session = self.validate_session(session_id) if session_id else None
        async with self.operation_lock:
            started = time.monotonic()
            record = {'path': name, 'client': session.name if session else 'GUI / API',
                      'started_at': time.time(), 'http_status': None}
            self.current_operation = record
            try:
                return await settle(asyncio.create_task(execute()))
            finally:
                self.last_operation = {**record, 'duration_seconds': time.monotonic() - started}
                self.current_operation = None

    async def invoke(self, method, path, arguments=None, *, session_id=None):
        import httpx
        headers = {"X-Auth-Token": self.info["token"]}
        if session_id:
            headers["X-MKLink-Session"] = session_id
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                    base_url=f"http://127.0.0.1:{self.info['port']}") as client:
            kwargs = {"params" if method == "GET" else "json": arguments or {}}
            response = await client.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            raise HTTPException(response.status_code, response.json())
        return response.json()


class RuntimeGate:
    """Authenticate HTTP + WebSocket, protect local origin, serialize hardware."""
    def __init__(self, app, *, control):
        self.app, self.control = app, control

    async def __call__(self, scope, receive, send):
        try:
            return await self._dispatch(scope, receive, send)
        finally:
            if scope.pop("mklink_idle_admitted", False):
                self.control.inflight_requests -= 1
                self.control.last_activity = time.monotonic()

    async def _dispatch(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        c = self.control
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode()
        expected = f"127.0.0.1:{c.info['port']}"
        origin = headers.get(b"origin", b"").decode()
        valid_origin = not origin or origin == f"http://{expected}"

        async def reject(code, detail):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await JSONResponse({"detail": detail}, status_code=code)(scope, receive, send)

        if host != expected or not valid_origin:
            return await reject(403, "Shared runtime requires a local, same-origin client")
        path = scope["path"]
        token = headers.get(b"x-auth-token", b"").decode()
        if not token:
            authorization = headers.get(b"authorization", b"").decode()
            if authorization.startswith("Bearer "):
                token = authorization[7:]
        if not token:
            from http.cookies import SimpleCookie
            cookie = SimpleCookie()
            try:
                cookie.load(headers.get(b"cookie", b"").decode())
                item = cookie.get("mklink_runtime_" + c.info["instance_id"])
                token = item.value if item else ""
            except Exception:
                token = ""
        public = path in {"/_runtime/open", "/_runtime/login"} and scope["type"] == "http"
        if not public and not hmac.compare_digest(token, c.info["token"]):
            return await reject(401, "Open the GUI using mklink gui, or authenticate with the runtime token")
        if c.stopping:
            return await reject(503, "Runtime is stopping")
        # Discovery alone must not keep an abandoned backend alive. Authenticated
        # HTTP/WS work is protected until its response/connection completes.
        if path != "/_runtime/status":
            scope["mklink_idle_admitted"] = True
            c.inflight_requests += 1
            c.last_activity = time.monotonic()
        # Static assets, caches, and subscription reads never reserve the CDC.
        method = scope.get("method", "GET")
        hardware = path.startswith("/api/") and (
            method not in {"GET", "HEAD", "OPTIONS"}
            or path in {"/api/device/core-registers", "/api/device/hardfault", "/api/device/hardfault-detail",
                        "/api/dash/superwatch/inspect", "/api/probe/firmware-check"}
        ) and not path.startswith(("/api/browser-session/", "/api/runtime/"))
        if not hardware:
            return await self.app(scope, receive, send)
        session_id = headers.get(b"x-mklink-session", b"").decode()
        if is_uart_path(path):
            try:
                return await c.run_operation(path, lambda: self.app(scope, receive, send), session_id=session_id)
            except HTTPException as exc:
                return await reject(exc.status_code, exc.detail)
        from mklink.runtime_jobs import PATHS, executing_job
        own_job = c.jobs and c.jobs.active and executing_job.get() == c.jobs.active['job_id']
        if path in PATHS.values() and not own_job:
            return await reject(409, 'Submit this operation through /api/runtime/jobs/ with confirm and request_id')
        online_stop = path.startswith('/api/online-flash/jobs/') and path.endswith('/stop')
        if c.job_busy() and not own_job and not online_stop:
            return await reject(409, 'An exclusive job is active; inspect its result before further hardware operations')
        from mklink.probes import select_probe
        from mklink.runtime import RuntimeErrorResponse
        if (path.startswith(('/api/device/', '/api/dash/', '/api/probe/')) or path == '/api/mcu-detect') and not path.endswith(('/stop', '/disconnect')):
            try:
                c.require_identity()
            except HTTPException as exc:
                return await reject(exc.status_code, exc.detail)
        if path == '/api/probe/firmware-upgrade':
            return await reject(409, 'Bootloader re-enumeration is not identity-bound yet; use an explicit maintenance session')
        if path in {'/api/offline-download/deploy', '/api/offline-download/trigger', '/api/offline-download/algorithm'}:
            try:
                c.require_identity()
                from mklink.probe_volumes import resolve_volume
                await asyncio.to_thread(resolve_volume, c.info.get('probe_id'))
            except (RuntimeError, HTTPException) as exc:
                return await reject(409, str(exc))
        validated_capability = next((name for name in ('read_memory', 'write_memory', 'write_variable', 'rtt_write')
                                     if CAPABILITIES[name][1] == path), None)
        online_flash = path in {"/api/online-flash/jobs", "/api/online-flash/memory/read", "/api/online-flash/memory/read-stream"}
        if online_flash or validated_capability:
            if online_flash:
                try:
                    selected = select_probe(c.info.get("probe_id"))
                except RuntimeErrorResponse as exc:
                    return await reject(409, str(exc))
            chunks = bytearray()
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    return
                chunks.extend(message.get("body", b""))
                if len(chunks) > 64 * 1024:
                    return await reject(413, "Control request exceeds 64 KiB")
                if not message.get("more_body"):
                    break
            try:
                body = json.loads(chunks)
            except (ValueError, UnicodeError):
                return await reject(422, "Invalid JSON control request")
            if not isinstance(body, dict):
                return await reject(422, 'Control body must be an object')
            if online_flash and str(body.get("probe_id", "")).casefold() != selected["serial_number"].casefold():
                return await reject(409, "CMSIS-DAP probe does not match this window's physical probe")
            if validated_capability:
                try:
                    chunks = json.dumps(validate_arguments(validated_capability, body)).encode('utf-8')
                except HTTPException as exc:
                    return await reject(exc.status_code, exc.detail)
            original_receive = receive
            replayed = False
            async def replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": bytes(chunks), "more_body": False}
                return await original_receive()
            receive = replay
        c.prune()
        if path == '/api/dash/superwatch/peripherals/select' and (
                c.attach_lock.locked() or any(key != session_id for key in c.target_sessions)):
            return await reject(409, 'Detach other shared clients before changing the peripheral catalog')
        if path in {"/api/device/disconnect", "/api/symbols/reparse", "/api/symbols/c-layout",
                    "/api/device/reboot", "/api/probe/firmware-upgrade"} and (c.target_sessions or c.attach_lock.locked()):
            return await reject(409, "Other runtime clients are attached; detach them before changing the shared device/project")
        if path in RESOURCE_RELEASE_PATHS and (c.sessions or c.attach_lock.locked() or c.uart_operations):
            return await reject(409, 'Detach clients and finish independent UART operations before releasing resources')
        for stream in STREAMS:
            if path == f"/api/dash/{stream}/pause" or (stream == "vofa" and path == "/api/dash/vofa/interval"):
                others = [key for key, s in c.sessions.items() if stream in s.streams and key != session_id]
                if others:
                    return await reject(409, "Other clients subscribe to this acquisition; detach them before stopping it")
        # Do not let a one-shot operation preempt the GUI's continuous capture.
        from mklink.remote.dashboards import BRIDGE_DASHBOARD_TYPES, active_bridge_dashboards
        active = active_bridge_dashboards()
        if active and (path.startswith('/api/offline-download/') or online_flash):
            return await reject(409, 'Stop acquisition explicitly before offline/online target operations')
        from mklink.runtime_capabilities import multiplex_enabled, MUX_MEMORY_PATHS
        mux_active = multiplex_enabled(c.app.state.mklink_state) and set(active) <= {'rtt', 'superwatch'}
        if path in {f"/api/dash/{name}/start" for name in BRIDGE_DASHBOARD_TYPES}:
            if active and not (mux_active and path in {'/api/dash/rtt/start', '/api/dash/superwatch/start'}):
                return await reject(409, "A CDC acquisition is already running; subscribe to its cached data or stop it explicitly")
        if (path.startswith(("/api/device/", "/api/probe/")) and path != "/api/device/connect") or path in {'/api/dash/superwatch/inspect', '/api/mcu-detect'}:
            if active and not (mux_active and path in MUX_MEMORY_PATHS):
                return await reject(409, {"busy": active, "hint": "Read a shared dashboard snapshot or explicitly stop acquisition first"})
        async def observe(message):
            if message['type'] == 'http.response.start':
                c.current_operation['http_status'] = message['status']
            await send(message)
        try:
            await c.run_operation(path, lambda: self.app(scope, receive, observe), session_id=session_id,
                                  configuration=path in {'/api/device/parse-axf', '/api/symbols/reparse', '/api/symbols/c-layout'},
                                  online_stop=online_stop)
        except HTTPException as exc:
            return await reject(exc.status_code, exc.detail)


def install_runtime(app, info):
    control = RuntimeControl(app, info)
    state = app.state.mklink_state
    state["shared_runtime"] = True
    state["shared_probe_id"] = info.get("probe_id")
    site_agent = getattr(app.state, "site_agent", None)
    if site_agent is not None:
        site_agent.runtime_info = info
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    if site_agent is not None:
        from mklink.remote.service_api import create_remote_service_router
        api.include_router(create_remote_service_router(site_agent, info))

    from mklink.remote.gui_sessions import install_remote_windows
    install_remote_windows(app, api)

    @api.get("/open", response_class=HTMLResponse)
    async def open_gui():
        return HTMLResponse("""<!doctype html><meta charset="utf-8"><title>MKLink Runtime</title>
<p id="status">正在连接共享后台…</p><script>
const requested = new URLSearchParams(location.search).get('page');
const remote = /^remote[/][A-Za-z0-9_-]{32}$/.test(requested || '') ? requested.slice(7) : null;
const page = remote ? 'dashboard' : requested === 'serial' ? 'dashboard?tab=serial' : 'config';
const token = location.hash.slice(1); history.replaceState(null, '', location.pathname);
fetch('/_runtime/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({token})})
.then(r => {if (!r.ok) throw Error('认证失败，请重新运行 mklink gui'); location.replace((remote ? '/?remote=' + remote : '/') + '#/' + page)})
.catch(e => document.getElementById('status').textContent = e.message);
</script>""", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    @api.post("/login")
    async def login(body: dict):
        token = body.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token, info["token"]):
            raise HTTPException(401, "Unauthorized")
        response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
        response.set_cookie("mklink_runtime_" + info["instance_id"], token, httponly=True, samesite="strict")
        return response

    @api.get("/status")
    async def status():
        control.prune()
        return {"protocol": PROTOCOL, "version": VERSION, "instance_id": info["instance_id"],
                "pid": info.get("pid"), "project_root": state["project_root"], "transport": "cdc",
                "probe_id": info.get("probe_id"), "clients": len(control.sessions), "busy": control.operation_lock.locked(),
                "capabilities": sorted(CAPABILITIES)}

    def attached(body, scope, device_status):
        session_id = body.get('session_id')
        session = control.sessions.get(session_id)
        axf = (device_status.get('axf') or {}).get('axf_path')
        symbol_version = control.symbol_version() if scope == 'target' else None
        if session is None:
            if len(control.sessions) >= 128:
                raise HTTPException(429, 'Too many attached clients')
            session_id = secrets.token_urlsafe(24)
            control.sessions[session_id] = Session(state['project_root'], axf,
                kind=body.get('kind', 'mcp'), name=body.get('name', 'AI client').strip(),
                symbol_version=symbol_version, scope=scope)
        else:
            session = control.session(session_id)
            session.project_root, session.axf, session.symbol_version = state['project_root'], axf, symbol_version
        capabilities = UART_CAPABILITIES if scope == 'uart' else CAPABILITIES
        return {**device_status, 'session_id': session_id, 'shared': True, 'scope': scope,
                'instance_id': info['instance_id'], 'probe_id': info.get('probe_id'),
                'capabilities': sorted(capabilities)}

    @api.post("/attach")
    async def attach(body: dict):
        scope = body.get('scope', 'target')
        if scope not in ('target', 'uart'):
            raise HTTPException(422, 'Session scope must be target or uart')
        kind, name = body.get('kind', 'mcp'), body.get('name', 'AI client')
        if kind not in ('mcp', 'cli', 'sdk') or not isinstance(name, str) or not 1 <= len(name.strip()) <= 64:
            raise HTTPException(422, 'Client kind must be mcp/cli/sdk and name must contain 1..64 characters')
        if any(body.get(key) is not None and not isinstance(body[key], str)
               for key in ('project_root', 'port', 'axf', 'mcu', 'elf_backend', 'session_id')):
            raise HTTPException(422, 'Connection parameters must be strings or null')
        project = body.get('project_root')
        if project and not same_path(project, state['project_root']):
            raise HTTPException(409, "Runtime has a different project; detach clients, stop this probe's backend explicitly, then start it with the requested project")
        control.prune()
        session = control.sessions.get(body.get('session_id'))
        if session and session.scope != scope:
            raise HTTPException(409, 'Detach before changing the session scope')
        if session is None and len(control.sessions) >= 128:
            raise HTTPException(429, 'Too many attached clients')
        if scope == 'uart':
            if any(body.get(key) is not None for key in ('port', 'axf', 'mcu', 'elf_backend')):
                raise HTTPException(422, 'UART-only attachment does not accept target connection settings')
            return attached(body, scope, {'attached': True})
        async with control.attach_lock:
            if control.operation_lock.locked() or control.job_busy():
                raise HTTPException(409, 'Wait for the active operation before attaching a client')
            control.require_identity()
            dev = state.get("device")
            if dev and dev.connected:
                if body.get("port") and body["port"].casefold() != dev.port.casefold():
                    raise HTTPException(409, "Runtime already owns a different probe")
                axf = (getattr(dev, "axf_status", {}) or {}).get("axf_path")
                if body.get("axf") and (not axf or not same_path(body["axf"], axf)):
                    raise HTTPException(409, "Runtime already has different symbols; change them explicitly in the GUI")
                if body.get("mcu") or body.get("elf_backend"):
                    previous = state.get("last_device_connection") or {}
                    for key in ("mcu", "elf_backend"):
                        if body.get(key) and body[key] != previous.get(key):
                            raise HTTPException(409, f"Shared {key} differs from the requested configuration")
            else:
                arguments = {key: body[key] for key in ("port", "axf", "mcu", "elf_backend") if body.get(key)}
                if info.get("probe_id"):
                    from mklink.probes import select_probe
                    from mklink.runtime import RuntimeErrorResponse
                    try:
                        selected = select_probe(body.get("port") or info["probe_id"])
                    except RuntimeErrorResponse as exc:
                        raise HTTPException(409, str(exc)) from exc
                    if selected["probe_id"] != info["probe_id"]:
                        raise HTTPException(409, "Runtime belongs to another probe")
                    arguments["port"] = selected["port"]
                await settle(asyncio.create_task(control.invoke("POST", "/api/device/connect", arguments)))
            device_status = await control.invoke("GET", "/api/device/status")
            return attached(body, scope, device_status)

    @api.post("/heartbeat")
    async def heartbeat(body: dict):
        control.session(body.get("session_id"))
        return {"ok": True}

    @api.post("/detach")
    async def detach(body: dict):
        if not isinstance(body.get("session_id"), str):
            raise HTTPException(422, "session_id must be a string")
        control.sessions.pop(body.get("session_id"), None)
        return {"detached": True, "device_closed": False}

    @api.post("/call")
    async def call(body: dict):
        session_id = body.get("session_id")
        capability = body.get("capability")
        if not isinstance(capability, str) or capability not in CAPABILITIES:
            raise HTTPException(422, "Unsupported shared capability; no direct CDC fallback")
        session = control.validate_session(session_id, target=capability not in UART_CAPABILITIES)
        arguments = body.get("arguments", {})
        # Flush carries up to 12 KiB as hex (optionally space-separated), plus
        # eight region headers. Its decoded write bounds remain enforced below.
        argument_limit = 48 * 1024 if capability == 'flush_memory' else 16 * 1024
        if not isinstance(arguments, dict) or len(json.dumps(arguments)) > argument_limit:
            raise HTTPException(422, f"Arguments must be an object of at most {argument_limit // 1024} KiB")
        arguments = validate_arguments(capability, arguments)
        stream, action = LIFECYCLE_CAPABILITIES.get(capability, (None, None))
        if action == 'start':
            if stream in STREAMS and control.operation_lock.locked():
                raise HTTPException(409, "Acquisition is changing; wait for the current operation before subscribing")
            from mklink.remote.dashboards import get_managers
            from mklink.remote.api import _dashboard_start_lock
            start_lock = _dashboard_start_lock(state, stream)
            if start_lock.locked():
                raise HTTPException(409, 'Acquisition is changing; wait before starting or subscribing')
            async with start_lock:
                session = control.validate_session(session_id, target=stream in STREAMS)
                if get_managers()[stream].running:
                    if arguments:
                        raise HTTPException(409, "Acquisition already runs; subscribe without reconfiguring it")
                    session.streams.add(stream)
                    return {"status": "subscribed", "reused": True}
        if action in ('pause', 'resume'):
            control.require_acquisition_control(stream, session_id)
        method, path = CAPABILITIES[capability]
        return await settle(asyncio.create_task(control.invoke(method, path, arguments, session_id=session_id)))

    @api.post("/stop")
    async def stop(body: dict):
        from mklink.runtime_management import stop_backend
        return stop_backend(control, body)

    app.router.routes.insert(0, Mount("/_runtime", app=api))
    app.add_middleware(RuntimeGate, control=control)
    app.state.shared_runtime = control
    from mklink.runtime_probe import create_probe_router
    app.router.routes[0:0] = create_probe_router(state).routes
    from mklink.runtime_management import install_management
    install_management(app, control)
    from mklink.runtime_jobs import install_jobs
    install_jobs(app, control)
    from mklink.runtime_idle import install_idle_shutdown
    install_idle_shutdown(app, control)
    return control
