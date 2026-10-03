"""Local operator controls. Every hardware action still uses shared admission."""
from __future__ import annotations

import time
from fastapi import FastAPI, HTTPException
from starlette.routing import Mount
from mklink.runtime_capabilities import STREAMS


def confirm_idle(control, body):
    if body.get('confirm') is not True:
        raise HTTPException(422, 'confirm=true required')
    if control.operation_lock.locked() or control.attach_lock.locked() or control.job_busy():
        raise HTTPException(409, 'An operation is still running; wait for completion')
    control.prune()


def stop_backend(control, body):
    """One shutdown policy for both CLI and GUI management adapters."""
    confirm_idle(control, body)
    if control.sessions or len(control.views) > 1:
        raise HTTPException(409, 'Detach AI/CLI/SDK clients and close other GUI windows first')
    from mklink.remote.dashboards import get_managers
    active = [name for name, manager in get_managers().items() if manager.running]
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
                                  'expires': time.monotonic()+45, 'name': 'GUI window'}
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
        confirm_idle(control, body)
        stream = body.get('stream')
        if stream not in STREAMS:
            raise HTTPException(422, 'Select RTT, SuperWatch or SystemView')
        result = await control.invoke('POST', f'/api/dash/{stream}/stop')
        control.created_streams.pop(stream, None)
        return result

    @api.post('/release-device')
    async def release_device(body: dict):
        confirm_idle(control, body)
        if control.sessions:
            raise HTTPException(409, 'Detach AI/CLI/SDK clients before releasing the physical device')
        no_capture()
        return await control.invoke('POST', '/api/device/disconnect')

    @api.post('/stop-backend')
    async def stop(body: dict):
        return stop_backend(control, body)

    app.router.routes.insert(0, Mount('/api/runtime/control', app=api))
