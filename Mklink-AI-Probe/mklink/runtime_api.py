"""Shared runtime sessions and a bounded, explicit GUI capability surface."""
from __future__ import annotations

import asyncio
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

# These are GUI service operations, never raw Python method/attribute access.
CAPABILITIES = {
    "device_status": ("GET", "/api/device/status"),
    "resources": ("GET", "/api/resources/status"),
    "read_memory": ("POST", "/api/device/read-memory"),
    "read_variable": ("POST", "/api/device/read-variable"),
    "symbol_search": ("GET", "/api/symbols/search"),
    "symbol_typeinfo": ("GET", "/api/symbols/typeinfo"),
    "memory_map": ("GET", "/api/device/memory-map"),
    "rtt_status": ("GET", "/api/dash/rtt/status"),
    "rtt_history": ("GET", "/api/dash/rtt/history"),
    "rtt_start": ("POST", "/api/dash/rtt/start"),
    "rtt_stop": ("POST", "/api/dash/rtt/stop"),
    "superwatch_status": ("GET", "/api/dash/superwatch/status"),
    "superwatch_items": ("GET", "/api/dash/superwatch/items"),
    "superwatch_snapshot": ("GET", "/api/dash/superwatch/array-snapshot"),
    "superwatch_values": ("GET", "/api/dash/superwatch/latest"),
    "superwatch_start": ("POST", "/api/dash/superwatch/start"),
    "superwatch_stop": ("POST", "/api/dash/superwatch/stop"),
    "superwatch_add": ("POST", "/api/dash/superwatch/add"),
    "systemview_status": ("GET", "/api/dash/systemview/status"),
    "systemview_history": ("GET", "/api/dash/systemview/history"),
    "serial_status": ("GET", "/api/dash/serial/status"),
    "modbus_status": ("GET", "/api/dash/modbus/status"),
    "vofa_status": ("GET", "/api/dash/vofa/status"),
}


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
    expires: float = field(default_factory=lambda: time.monotonic() + 120)
    streams: set = field(default_factory=set)


class RuntimeControl:
    def __init__(self, app, info):
        self.app, self.info = app, info
        self.sessions: dict[str, Session] = {}
        self.created_streams: dict[str, str] = {}
        self.attach_lock = asyncio.Lock()
        self.operation_lock = asyncio.Lock()
        self.shutdown = None
        self.stopping = False

    def prune(self):
        now = time.monotonic()
        self.sessions = {key: session for key, session in self.sessions.items() if session.expires > now}

    def session(self, session_id):
        self.prune()
        if not isinstance(session_id, str):
            raise HTTPException(422, "session_id must be a string")
        session = self.sessions.get(session_id)
        if session is None:
            raise HTTPException(409, "Session expired or detached; connect again")
        session.expires = time.monotonic() + 120
        return session

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
        # Static assets, caches, and subscription reads never reserve the CDC.
        method = scope.get("method", "GET")
        hardware = path.startswith("/api/") and (
            method not in {"GET", "HEAD", "OPTIONS"}
            or path in {"/api/device/core-registers", "/api/device/hardfault", "/api/device/hardfault-detail"}
        ) and not path.startswith(("/api/browser-session/", "/api/session/"))
        if not hardware:
            return await self.app(scope, receive, send)
        from mklink.probes import inventory, select_probe
        from mklink.runtime import RuntimeErrorResponse
        if path in {"/api/probe/firmware-upgrade", "/api/offline-download/deploy", "/api/offline-download/trigger"} and len(inventory()) > 1:
            return await reject(409, "This disk-based operation is not yet bound to a probe identity; use a single-probe maintenance session")
        if path in {"/api/online-flash/jobs", "/api/online-flash/memory/read", "/api/online-flash/memory/read-stream"}:
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
            if not isinstance(body, dict) or str(body.get("probe_id", "")).casefold() != selected["serial_number"].casefold():
                return await reject(409, "CMSIS-DAP probe does not match this window's physical probe")
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
        session_id = headers.get(b"x-mklink-session", b"").decode()
        if path in {"/api/device/disconnect", "/api/project-root", "/api/symbols/reparse", "/api/symbols/c-layout", "/api/resources/release-all",
                    "/api/resources/release", "/api/device/reboot", "/api/probe/firmware-upgrade"} and (c.sessions or c.attach_lock.locked()):
            return await reject(409, "Other runtime clients are attached; detach them before changing the shared device/project")
        for stream in ("rtt", "superwatch", "systemview"):
            if path in {f"/api/dash/{stream}/stop", f"/api/dash/{stream}/pause"}:
                others = [key for key, s in c.sessions.items() if stream in s.streams and key != session_id]
                if others:
                    return await reject(409, "Other clients subscribe to this acquisition; detach them before stopping it")
        # Do not let a one-shot operation preempt the GUI's continuous capture.
        from mklink.remote.dashboards import get_managers
        active = [name for name, manager in get_managers().items() if manager.running]
        if path in {f"/api/dash/{name}/start" for name in ("rtt", "superwatch", "systemview", "vofa")}:
            if any(name in active for name in ("rtt", "superwatch", "systemview", "vofa")):
                return await reject(409, "A CDC acquisition is already running; subscribe to its cached data or stop it explicitly")
        if path.startswith("/api/device/") and path != "/api/device/connect":
            if active:
                return await reject(409, {"busy": active, "hint": "Read a shared dashboard snapshot or explicitly stop acquisition first"})
        if c.operation_lock.locked():
            return await reject(409, "Another shared operation is in flight; wait for completion")
        async with c.operation_lock:
            await settle(asyncio.create_task(self.app(scope, receive, send)))


def install_runtime(app, info):
    control = RuntimeControl(app, info)
    state = app.state.mklink_state
    state["shared_runtime"] = True
    state["shared_probe_id"] = info.get("probe_id")
    # The legacy remote listener dispatches directly to Device. Until it uses
    # the same admission/session model, it must not bypass shared arbitration.
    site_agent = getattr(app.state, "site_agent", None)
    if site_agent is not None and site_agent.settings.enabled:
        site_agent.settings = replace(site_agent.settings, enabled=False, configuration_error=
            "Site Agent is not yet supported by the shared runtime; use an explicit exclusive session")
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @api.get("/open", response_class=HTMLResponse)
    async def open_gui():
        return HTMLResponse("""<!doctype html><meta charset="utf-8"><title>MKLink Runtime</title>
<p id="status">正在连接共享后台…</p><script>
const token = location.hash.slice(1); history.replaceState(null, '', location.pathname);
fetch('/_runtime/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({token})})
.then(r => {if (!r.ok) throw Error('认证失败，请重新运行 mklink gui'); location.replace('/#/config')})
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

    @api.post("/attach")
    async def attach(body: dict):
        async with control.attach_lock:
            control.prune()
            if len(control.sessions) >= 128:
                raise HTTPException(429, "Too many attached clients")
            project = body.get("project_root")
            if any(body.get(key) is not None and not isinstance(body[key], str)
                   for key in ("project_root", "port", "axf", "mcu", "elf_backend", "session_id")):
                raise HTTPException(422, "Connection parameters must be strings or null")
            if project and not same_path(project, state["project_root"]):
                raise HTTPException(409, "Runtime has a different project; switch it explicitly after detaching clients")
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
            session_id = body.get("session_id")
            if session_id not in control.sessions:
                session_id = secrets.token_urlsafe(24)
            if session_id not in control.sessions:
                control.sessions[session_id] = Session(state["project_root"], (device_status.get("axf") or {}).get("axf_path"))
            else:
                control.session(session_id)
            return {**device_status, "session_id": session_id, "shared": True,
                    "instance_id": info["instance_id"], "probe_id": info.get("probe_id"), "capabilities": sorted(CAPABILITIES)}

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
        session = control.session(session_id)
        if not same_path(session.project_root, state["project_root"]):
            raise HTTPException(409, "Project changed; reconnect explicitly")
        active_axf = (getattr(state.get("device"), "axf_status", {}) or {}).get("axf_path")
        if session.axf != active_axf:
            raise HTTPException(409, "Symbols changed; reconnect explicitly before reading the new target layout")
        capability = body.get("capability")
        if not isinstance(capability, str) or capability not in CAPABILITIES:
            raise HTTPException(422, "Unsupported shared capability; no direct CDC fallback")
        arguments = body.get("arguments", {})
        if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 16384:
            raise HTTPException(422, "Arguments must be an object of at most 16 KiB")
        if capability == "read_memory":
            try:
                size = arguments["size"]
                address = int(str(arguments["address"]), 0)
                if type(size) is not int or not 1 <= size <= 4096 or not 0 <= address <= 0x100000000 - size:
                    raise ValueError()
                arguments["address"] = hex(address)
            except (KeyError, TypeError, ValueError):
                raise HTTPException(422, "read_memory requires a 32-bit address and 1..4096 bytes")
        stream = capability.split("_")[0]
        if capability.endswith("_start"):
            if control.operation_lock.locked():
                raise HTTPException(409, "Acquisition is changing; wait for the current operation before subscribing")
            from mklink.remote.dashboards import get_managers
            if get_managers()[stream].running:
                if arguments:
                    raise HTTPException(409, "Acquisition already runs; subscribe without reconfiguring it")
                session.streams.add(stream)
                return {"status": "subscribed", "reused": True}
        if capability.endswith("_stop"):
            if control.created_streams.get(stream) != session_id:
                raise HTTPException(409, "This acquisition was started by another client; detach instead")
        method, path = CAPABILITIES[capability]
        async def execute():
            result = await control.invoke(method, path, arguments, session_id=session_id)
            if capability.endswith("_start"):
                session.streams.add(stream)
                control.created_streams[stream] = session_id
            elif capability.endswith("_stop"):
                session.streams.discard(stream)
                control.created_streams.pop(stream, None)
            return result
        return await settle(asyncio.create_task(execute()))

    @api.post("/stop")
    async def stop(body: dict):
        control.prune()
        if control.sessions or control.operation_lock.locked() or control.attach_lock.locked():
            raise HTTPException(409, "Detach runtime clients and wait for hardware operations before stopping")
        if body.get("confirm") is not True:
            raise HTTPException(422, "Explicit confirm=true required")
        control.stopping = True
        if control.shutdown:
            control.shutdown()
        return {"status": "stopping"}

    app.router.routes.insert(0, Mount("/_runtime", app=api))
    app.add_middleware(RuntimeGate, control=control)
    app.state.shared_runtime = control
    return control
