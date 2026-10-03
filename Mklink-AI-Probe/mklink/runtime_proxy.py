"""Desktop-owned HTTP/WS adapter; the CDC runtime outlives this process.

The existing Tauri child/job lifecycle owns only this adapter. It never owns a
Device. Native windows can keep their existing API URLs and stream protocols.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.middleware.cors import CORSMiddleware

DESKTOP_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"}
HOP_HEADERS = {"host", "connection", "transfer-encoding", "content-length", "keep-alive", "upgrade", "cookie", "origin", "x-auth-token"}


def create_proxy(info, *, port, instance_id, transport=None):
    base = f"http://127.0.0.1:{info['port']}"

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(base_url=base, transport=transport, timeout=None, trust_env=False) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.shutdown = None
    origins = DESKTOP_ORIGINS | {f"http://127.0.0.1:{port}"}
    app.add_middleware(CORSMiddleware, allow_origins=sorted(origins), allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def local_only(request, call_next):
        if request.headers.get("host") != f"127.0.0.1:{port}" or (
            request.headers.get("origin") and request.headers["origin"] not in origins
        ):
            return JSONResponse({"detail": "Local desktop origin required"}, status_code=403)
        if request.url.path.startswith("/_runtime/"):
            return JSONResponse({"detail": "Use mklink runtime to manage the shared backend"}, status_code=403)
        return await call_next(request)

    @app.post("/api/desktop/shutdown")
    async def shutdown(body: dict):
        if body.get("instance_id") != instance_id:
            return JSONResponse({"detail": "Desktop instance does not match"}, status_code=403)
        if app.state.shutdown:
            app.state.shutdown()
        return {"status": "shutting_down", "shared_runtime_stopped": False}

    @app.get("/api/health")
    async def health():
        try:
            response = await app.state.client.get(f"http://127.0.0.1:{info['port']}/api/health", headers={"X-Auth-Token": info["token"]}, timeout=3)
            response.raise_for_status()
            return {**response.json(), "backend_port": port, "desktop_instance_id": instance_id}
        except httpx.HTTPError:
            return JSONResponse({"detail": "Shared runtime is unavailable"}, status_code=503)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def forward(request: Request, path: str):
        headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP_HEADERS}
        headers["X-Auth-Token"] = info["token"]
        url = httpx.URL(f"http://127.0.0.1:{info['port']}/{path}").copy_with(query=request.url.query.encode())
        upstream = app.state.client.build_request(request.method, url, headers=headers, content=request.stream())
        try:
            response = await app.state.client.send(upstream, stream=True)
        except httpx.HTTPError:
            return JSONResponse({"detail": "Shared runtime unavailable; CDC not reopened"}, status_code=503)
        if path == "api/runtime/select" and response.status_code == 200:
            await response.aread()
            selection = response.json()
            await response.aclose()
            if selection.get("runtime_url"):
                from mklink.runtime import discover
                selected = await asyncio.to_thread(discover, selection["probe_id"])
                if not selected:
                    return JSONResponse({"detail": "Selected runtime unavailable"}, status_code=503)
                info.clear()
                info.update(selected)
                return {"same_runtime": False, "reload": True, "probe_id": selected["probe_id"]}
            return selection
        headers = {key: value for key, value in response.headers.items()
                   if key.lower() not in HOP_HEADERS and key.lower() != "set-cookie"}
        return StreamingResponse(response.aiter_raw(), status_code=response.status_code, headers=headers,
                                 background=BackgroundTask(response.aclose))

    @app.websocket("/{path:path}")
    async def forward_socket(websocket: WebSocket, path: str):
        if websocket.headers.get("host") != f"127.0.0.1:{port}" or (
            websocket.headers.get("origin") and websocket.headers["origin"] not in origins
        ):
            await websocket.close(code=1008)
            return
        # Legacy client also supports the declared websockets>=11 baseline and
        # never routes loopback IPC through environment-configured proxies.
        from websockets.legacy.client import connect
        target = f"ws://127.0.0.1:{info['port']}/{path}"
        if websocket.url.query:
            target += "?" + websocket.url.query
        try:
            async with connect(target, extra_headers={"X-Auth-Token": info["token"]},
                               compression=None, max_size=4 * 1024 * 1024) as upstream:
                await websocket.accept()

                async def to_runtime():
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        await upstream.send(message.get("bytes") if message.get("bytes") is not None else message["text"])

                async def to_gui():
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = [asyncio.create_task(to_runtime()), asyncio.create_task(to_gui())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            try:
                await websocket.close(code=1011)
            except RuntimeError:
                pass

    return app


def serve_desktop_proxy(args):
    import uvicorn
    from mklink.runtime import ensure_runtime
    from mklink.remote.api import _bind_desktop_server_socket, _write_desktop_runtime_info
    info = ensure_runtime(project_root=args.project_root, port=args.port, allow_lobby=True)
    listener, selected = _bind_desktop_server_socket(args.host, args.port, args.desktop_port_end)
    try:
        app = create_proxy(info, port=selected, instance_id=args.desktop_instance_id)
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, ws="websockets-sansio", ws_per_message_deflate=False))
        app.state.shutdown = lambda: setattr(server, "should_exit", True)
        _write_desktop_runtime_info(args.desktop_runtime_info, port=selected, instance_id=args.desktop_instance_id)
        server.run(sockets=[listener])
    finally:
        listener.close()
