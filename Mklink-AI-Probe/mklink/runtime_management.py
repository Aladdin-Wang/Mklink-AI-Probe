"""Local operator controls. Every hardware action still uses shared admission."""
from __future__ import annotations

import time
import json
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from starlette.routing import Mount
from mklink.runtime_capabilities import STREAMS, LIFECYCLE_CAPABILITIES, CAPABILITIES


def confirm_idle(control, body, *, target=True):
    if body.get('confirm') is not True:
        raise HTTPException(422, 'confirm=true required')
    if target and (control.operation_lock.locked() or control.attach_lock.locked() or control.job_busy()):
        raise HTTPException(409, 'An operation is still running; wait for completion')
    control.prune()


def stop_backend(control, body):
    """One shutdown policy for both CLI and GUI management adapters."""
    confirm_idle(control, body)
    if control.uart_operations:
        raise HTTPException(409, 'Independent UART operations are still running; wait for completion')
    if control.sessions or len(control.views) > 1:
        raise HTTPException(409, 'Detach AI/CLI/SDK clients and close other GUI windows first')
    from mklink.remote.dashboards import get_managers
    from mklink.remote.api import _dashboard_worker_alive
    active = [name for name, manager in get_managers().items() if _dashboard_worker_alive(manager)]
    if active:
        raise HTTPException(409, {'reason': 'capture_active', 'streams': active})
    control.stopping = True
    if control.shutdown:
        control.shutdown()
    return {'status': 'stopping'}


def install_management(app, control):
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def no_capture():
        from mklink.remote.dashboards import active_bridge_dashboards
        active = active_bridge_dashboards()
        if active:
            raise HTTPException(409, {'reason': 'capture_active', 'streams': active})

    @api.get('/status')
    async def status():
        return await control.snapshot()

    @api.get('/volume')
    async def volume():
        import asyncio
        from mklink.probe_volumes import resolve_volume
        try:
            return await asyncio.to_thread(resolve_volume, control.info.get('probe_id'))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @api.get('/windows')
    async def windows():
        from mklink.runtime_presentation import windows
        return windows(control)

    @api.post('/present')
    async def present(body: dict):
        from mklink.runtime_presentation import present
        return await present(control, body)

    @api.websocket('/view/{key}')
    async def live_view(socket: WebSocket, key: str):
        if not 1 <= len(key) <= 128 or key in control.views or len(control.views) >= 128:
            await socket.close(code=1008)
            return
        record = {'joined': time.monotonic(), 'expires': float('inf'), 'name': 'GUI window', 'live': True}
        record.update(socket=socket, presentation=socket.query_params.get('presentation') == '1')
        control.views[key] = record
        try:
            await socket.accept()
            await socket.send_json({'registered': True})
            while True:
                message = await socket.receive()
                if message['type'] == 'websocket.disconnect':
                    break
                raw = message.get('text', '')
                if len(raw) <= 1024:
                    try:
                        payload = json.loads(raw)
                        if isinstance(payload, dict):
                            from mklink.runtime_presentation import acknowledge
                            acknowledge(record, payload)
                    except ValueError:
                        pass
        except WebSocketDisconnect:
            pass
        finally:
            if record.get('pending') and not record['pending'][1].done():
                record['pending'][1].set_result('disconnected')
            if control.views.get(key) is record:
                control.views.pop(key, None)

    @api.post('/view')
    async def view(body: dict):
        key = body.get('client_id')
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise HTTPException(422, 'Invalid window identity')
        control.prune()
        if body.get('release') is True:
            control.views.pop(key, None)
        else:
            if key not in control.views and len(control.views) >= 128:
                raise HTTPException(429, 'Too many GUI windows')
            previous = control.views.get(key, {})
            control.views[key] = {'joined': previous.get('joined', time.monotonic()),
                                  'expires': time.monotonic()+5, 'name': 'GUI window'}
        return {'registered': key in control.views, 'device_closed': False}

    @api.post('/detach-client')
    async def detach(body: dict):
        confirm_idle(control, body)
        key = next((key for key, value in control.sessions.items() if value.public_id == body.get('client_id')), None)
        if key is None:
            raise HTTPException(404, 'Client already detached or expired')
        control.sessions.pop(key)
        return {'detached': True, 'device_closed': False}

    @api.post('/stop-acquisition')
    async def stop_acquisition(body: dict):
        stream = body.get('stream')
        capability = f'{stream}_stop'
        if capability not in LIFECYCLE_CAPABILITIES:
            raise HTTPException(422, 'Select a supported acquisition')
        confirm_idle(control, body, target=stream in STREAMS)
        method, path = CAPABILITIES[capability]
        return await control.invoke(method, path)

    @api.post('/release-device')
    async def release_device(body: dict):
        confirm_idle(control, body)
        if control.target_sessions:
            raise HTTPException(409, 'Detach AI/CLI/SDK clients before releasing the physical device')
        no_capture()
        return await control.invoke('POST', '/api/device/disconnect')

    @api.post('/stop-backend')
    async def stop(body: dict):
        return stop_backend(control, body)

    app.router.routes.insert(0, Mount('/api/runtime/control', app=api))
