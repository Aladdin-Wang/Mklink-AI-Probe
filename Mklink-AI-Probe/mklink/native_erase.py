"""Prepare native FLM erasure from the exact target's existing algorithm catalog."""
from __future__ import annotations


def validate_erase_request(arguments, *, sector=False):
    allowed = {'target_part', 'algorithm_id'} | ({'address'} if sector else set())
    if not isinstance(arguments, dict) or arguments.keys() - allowed:
        raise ValueError('Unsupported erase arguments')
    result = dict(arguments)
    for key in ('target_part', 'algorithm_id'):
        if key in result and (not isinstance(result[key], str) or not result[key].strip() or len(result[key]) > 128):
            raise ValueError(f'{key} must be a nonempty string of at most 128 characters')
    if sector:
        value = result.get('address')
        if type(value) not in (str, int):
            raise ValueError('Sector address must be a 32-bit integer or integer string')
        from mklink.hpm_config import normalize_hpm_address
        result['address'] = normalize_hpm_address(value)[0]
    return result


def prepare_erase(device, *, address=None, target_part=None, algorithm_id=None):
    from mklink.device import DeviceError
    from mklink.project_config import load_project_info
    from mklink.profiles import load_mcu_profiles
    from mklink.hpm_config import is_hpm_target
    from mklink.cmsis_dap.algorithm_catalog import (
        discover_flash_algorithms, resolve_firmware_algorithms, deploy_algorithm_to_probe,
    )
    project = (load_project_info(device._project_root) or {}) if device._project_root else {}
    target = target_part or project.get('device') or project.get('target_part')
    if not target and device._mcu_hint not in load_mcu_profiles():
        target = device._mcu_hint
    if not isinstance(target, str) or not target.strip():
        raise DeviceError('Erasure requires an exact target_part or project device; family IDCODE is insufficient')
    if is_hpm_target(target, vendor=project.get('vendor'), board=project.get('board')) or device.idcode == 0x1000563D:
        raise DeviceError('Native FLM erasure is unavailable for HPM; use the HPM ROM programming path')
    if not device.idcode:
        raise DeviceError('Target IDCODE is unavailable; no erase operation was prepared')
    algorithms = discover_flash_algorithms(target.strip())
    if algorithm_id is not None:
        algorithms = [a for a in algorithms if a.algorithm_id == algorithm_id]
    elif address is None and any(a.default for a in algorithms):
        algorithms = [a for a in algorithms if a.default]
    if address is not None:
        if type(address) is not int or not 0 <= address <= 0xffffffff:
            raise ValueError('Sector address must be a 32-bit integer')
        algorithms = [a for a in algorithms if a.flash_start <= address < a.flash_start + a.flash_size]
    if not algorithms:
        raise DeviceError('No exact target Flash algorithm covers the requested erase operation')
    # Bank modes and overlapping FLMs cannot be guessed from an IDCODE. Even
    # whole-chip erasure must not silently pick a smaller region or another mode.
    shapes = {(a.flash_start, a.flash_size, tuple(a.sector_sizes)) for a in algorithms}
    if len(shapes) != 1:
        raise DeviceError('Ambiguous Flash algorithms; select an explicit algorithm_id and inspect its erase scope')
    start, size, _ = next(iter(shapes))
    if start < 0 or size <= 0 or start + size > 0x100000000:
        raise DeviceError('Invalid Flash algorithm range')
    algorithm = resolve_firmware_algorithms(algorithms, [(start, start + size)])[0].algorithm
    if algorithm.ram_start <= 0:
        raise DeviceError('Flash algorithm has no declared RAM base')
    if address is not None:
        from mklink.cmsis_dap.algorithm_catalog import algorithm_regions
        regions = algorithm_regions(algorithm, 'erase')
        region = next((r for r in regions if r.start <= address < r.end), None)
        if region is None or not region.sector_size or (address - region.start) % region.sector_size:
            raise DeviceError('Erasure requires a known, complete sector boundary')
    from pathlib import Path
    from mklink.probes import bound_probe, select_probe
    from mklink.probe_volumes import resolve_volume
    selected = select_probe(device.port)
    bound = bound_probe()
    if not selected['identity_stable'] or (bound is not None and selected['probe_id'] != bound):
        raise DeviceError('Erase algorithm deployment requires the command probe stable USB identity')
    disk = Path(resolve_volume(selected['probe_id'])['root'])
    path = deploy_algorithm_to_probe(algorithm, disk_root=disk)
    if not device._flash.load_flm(path, f'0x{start:08X}', f'0x{algorithm.ram_start:08X}'):
        raise DeviceError('FLM initialization failed; no erase command was sent')
    return start
