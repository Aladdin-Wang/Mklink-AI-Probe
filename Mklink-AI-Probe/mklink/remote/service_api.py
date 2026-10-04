"""Local authenticated controls for a probe's remote WebSocket listener."""
from dataclasses import fields, replace
import hashlib
import ipaddress
import secrets
import socket

from fastapi import APIRouter, HTTPException


def create_remote_service_router(controller, info):
    router = APIRouter(prefix='/remote-service')

    def status():
        from mklink.probes import load_aliases
        value = controller.status()
        token = controller.settings.token
        value.update(probe_id=info.get('probe_id'), probe_alias=load_aliases().get(info.get('probe_id'), ''),
                     token_fingerprint=hashlib.sha256(token.encode()).hexdigest()[:8] if token else None)
        return value

    @router.get('')
    async def get_status():
        return status()

    @router.get('/addresses')
    async def addresses():
        import asyncio
        def resolve():
            values = {'127.0.0.1'}
            try:
                for entry in socket.getaddrinfo(socket.gethostname(), None):
                    address = entry[4][0]
                    ip = ipaddress.ip_address(address)
                    if not ip.is_unspecified and not ip.is_multicast:
                        values.add(address)
            except OSError:
                pass
            return sorted(values)
        return await asyncio.to_thread(resolve)

    @router.post('/token')
    async def generate_token(body: dict):
        if set(body) != {'confirm'} or body['confirm'] is not True:
            raise HTTPException(422, 'Confirm token generation explicitly')
        async with controller._control_lock:
            if controller.status()['running']:
                raise HTTPException(409, 'Stop remote service before rotating its token')
            token = secrets.token_urlsafe(32)
            controller.settings = replace(controller.settings, token=token)
            return {'token': token, 'fingerprint': hashlib.sha256(token.encode()).hexdigest()[:8]}

    @router.post('')
    async def configure(body: dict):
        from mklink.remote.embedded_agent import EmbeddedAgentSettings
        from mklink.runtime_api import settle
        import asyncio
        allowed = {f.name for f in fields(EmbeddedAgentSettings)} - {'configuration_error', 'stcp_library'}
        if body.keys() - allowed:
            raise HTTPException(422, 'Unknown remote service setting')
        for key, value in body.items():
            if key in {'enabled', 'allow_lan'}:
                valid = type(value) is bool
            elif key in {'port', 'stcp_server_port'}:
                valid = type(value) is int and 1 <= value <= 65535
            else:
                valid = isinstance(value, str) and len(value) <= 1024
            if not valid:
                raise HTTPException(422, 'Invalid remote service setting: ' + key)
        if body.get('enabled') is True and not (body.get('token') or controller.settings.token):
            raise HTTPException(422, 'Generate an access token before starting remote service')
        try:
            await settle(asyncio.create_task(controller.configure({**body, 'configuration_error': None})))
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except Exception:
            raise HTTPException(503, 'Remote listener could not start; inspect service status and port availability') from None
        return status()

    @router.post('/stop')
    async def stop():
        from mklink.runtime_api import settle
        import asyncio
        await settle(asyncio.create_task(controller.configure({'enabled': False})))
        return status()

    return router
