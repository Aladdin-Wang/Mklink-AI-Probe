"""Read-only probe commands, executed only by the selected shared backend."""
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from mklink._types import DeviceState
from mklink.runtime_capabilities import PROBE_QUERIES


def _query(state, capability):
    if capability not in PROBE_QUERIES:
        raise ValueError('Unsupported probe query')
    from mklink.bridge import MKLinkSerialBridge
    from mklink.power import read_power
    from mklink.probes import select_probe
    from mklink.remote.resource_manager import ResourceGroup

    selected = select_probe(state['shared_probe_id'])
    device = state.get('device')
    if device is not None and (not device.connected or device.port.casefold() != selected['port'].casefold()):
        raise HTTPException(409, 'Release the stale connection explicitly before querying this probe')
    manager = state['resource_manager']
    owner = 'user:api:' + capability
    manager.acquire_many((ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG), owner)
    bridge = None
    owned = device is None
    try:
        bridge = MKLinkSerialBridge(selected['port']) if owned else device._bridge
        if owned and not bridge.connect(recover_stream=False):
            raise HTTPException(409, 'Probe command port unavailable or not idle; no stream recovery attempted')
        if bridge.state != DeviceState.READY:
            raise HTTPException(409, 'Stop the active acquisition explicitly before querying the probe')
        if capability == 'power_read':
            return read_power(bridge)
        return {'raw': bridge.send_command('cmd.get_version()', timeout=5.0)}
    finally:
        try:
            if owned and bridge is not None:
                bridge.close()
        finally:
            manager.release(owner)


def create_probe_router(state):
    router = APIRouter()

    async def execute(capability):
        from mklink.remote.resource_manager import ResourceError
        from mklink.runtime import RuntimeErrorResponse
        try:
            return await run_in_threadpool(_query, state, capability)
        except (ResourceError, RuntimeErrorResponse) as error:
            raise HTTPException(409, str(error)) from error
        except (ConnectionError, TimeoutError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @router.post(PROBE_QUERIES['power_read'])
    async def power_read():
        return await execute('power_read')

    @router.post(PROBE_QUERIES['probe_version'])
    async def probe_version():
        return await execute('probe_version')

    return router
