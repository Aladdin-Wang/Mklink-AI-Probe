"""Probe queries and guarded updates executed by the selected shared backend."""
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
    manager.acquire_many((ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG, ResourceGroup.MUX_RTT, ResourceGroup.MUX_WATCH), owner)
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
        if capability == 'probe_idcode':
            from mklink.flash import IDCODEError, MKLinkFlash
            try:
                return {'idcode': MKLinkFlash(bridge).get_idcode()}
            except IDCODEError as error:
                raise HTTPException(400, str(error)) from error
        return {'raw': bridge.send_command('cmd.get_version()', timeout=5.0)}
    finally:
        try:
            if owned and bridge is not None:
                bridge.close()
        finally:
            manager.release(owner)


def check_firmware(state, firmware_root):
    """Keep the existing disk/catalog policy; route only CDC fallback via admission."""
    from mklink.firmware_check import check_probe_firmware, parse_probe_version
    from mklink.probes import select_probe

    selected = select_probe(state['shared_probe_id'])
    return check_probe_firmware(selected['port'], firmware_root, version_reader=lambda port:
                                parse_probe_version(_query(state, 'probe_version')['raw']))


def upgrade_firmware(state, firmware_root):
    """One identity-bound update; inability to enter UF2 becomes a manual path."""
    from mklink.firmware_check import upgrade_probe_firmware
    from mklink.probe_volumes import FirmwareVolumes
    from mklink.probes import select_probe
    if state.get('shared_probe_id') in (None, 'lobby'):
        return {'status': 'manual_required', 'message': '请先在本地设备页选择下载器，或选择型号下载固件后手动升级。'}
    try:
        selected = select_probe(state['shared_probe_id'])
        volumes = FirmwareVolumes(selected)
    except RuntimeError:
        return {'status': 'manual_required', 'message': '暂时无法识别下载器，请选择正确型号下载固件后手动升级。'}

    class CommandPort:
        def enter_bootloader(self):
            from mklink.bridge import MKLinkSerialBridge
            from mklink.remote.resource_manager import ResourceGroup
            manager = state['resource_manager']
            owner = 'user:api:firmware-upgrade'
            manager.acquire_many((ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG,
                                  ResourceGroup.MUX_RTT, ResourceGroup.MUX_WATCH), owner)
            device = state.get('device')
            bridge = None
            try:
                # Selection may have changed while the firmware was downloading.
                current = select_probe(state['shared_probe_id'])
                if device is not None and device.connected:
                    if device.port.casefold() != current['port'].casefold():
                        raise RuntimeError('Probe port changed')
                    device.enter_bootloader()
                else:
                    bridge = MKLinkSerialBridge(current['port'])
                    if not bridge.connect(recover_stream=False):
                        raise RuntimeError('Command port unavailable')
                    bridge.enter_bootloader()
            finally:
                try:
                    if bridge is not None:
                        bridge.close()
                finally:
                    manager.release(owner)

    return upgrade_probe_firmware(CommandPort(), firmware_root, confirm=True,
                                  disk_reader=volumes.find,
                                  bootloader_finder=lambda: volumes.find(bootloader=True))


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

    @router.post(PROBE_QUERIES['probe_idcode'])
    async def probe_idcode():
        return await execute('probe_idcode')

    return router
