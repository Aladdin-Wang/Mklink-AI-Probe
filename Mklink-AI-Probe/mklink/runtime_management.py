"""Local operator controls. Every hardware action still uses shared admission."""
from __future__ import annotations

import time
from fastapi import FastAPI, HTTPException
from starlette.routing import Mount
from mklink.runtime_capabilities import STREAMS


def install_management(app, control):
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def confirmed(body):
        if body.get('confirm') is not True:
            raise HTTPException(422, 'confirm=true required')
        if control.operation_lock.locked() or control.attach_lock.locked():
            raise HTTPException(409, 'An operation is still running; wait for completion')
        control.prune()

    def no_capture():
        from mklink.remote.dashboards import get_managers
        active = [name for name, manager in get_managers().items() if manager.running]
        if active:
            raise HTTPException(409, {'reason': 'capture_active', 'streams': active})

    @api.get('/status')
    async def status():
        return await control.snapshot()

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
        confirmed(body)
        key = next((key for key, value in control.sessions.items() if value.public_id == body.get('client_id')), None)
        if key is None:
            raise HTTPException(404, 'Client already detached or expired')
        control.sessions.pop(key)
        return {'detached': True, 'device_closed': False}

    @api.post('/stop-acquisition')
    async def stop_acquisition(body: dict):
        confirmed(body)
        stream = body.get('stream')
        if stream not in STREAMS:
            raise HTTPException(422, 'Select RTT, SuperWatch or SystemView')
        result = await control.invoke('POST', f'/api/dash/{stream}/stop')
        control.created_streams.pop(stream, None)
        return result

    @api.post('/release-device')
    async def release_device(body: dict):
        confirmed(body)
        if control.sessions:
            raise HTTPException(409, 'Detach AI/CLI clients before releasing the physical device')
        no_capture()
        return await control.invoke('POST', '/api/device/disconnect')

    @api.post('/stop-backend')
    async def stop_backend(body: dict):
        confirmed(body)
        if control.sessions or len(control.views) > 1:
            raise HTTPException(409, 'Detach AI/CLI clients and close other GUI windows first')
        no_capture()
        control.stopping = True
        if control.shutdown:
            control.shutdown()
        return {'status': 'stopping'}

    app.router.routes.insert(0, Mount('/api/runtime/control', app=api))
