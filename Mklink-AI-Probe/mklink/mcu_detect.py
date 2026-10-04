"""Read-only MCU inspection using the application's unified algorithm catalog."""
from __future__ import annotations

from typing import Callable


def _read_idcode(port: str | None) -> int | None:
    if not port:
        return None
    from mklink.runtime import query_probe
    return query_probe('probe_idcode', port=port)['idcode']


def inspect_mcu(*, project_root=".", device=None, flm=None, port=None,
                read_idcode=False, idcode_reader: Callable | None = None, paths=None):
    """Inspect an exact target without writing profiles, project files or probe disks.

    ``flm`` selects an algorithm ID or an unambiguous filename. IDCODE is optional
    diagnostic data, never used to guess an exact target or choose an algorithm.
    """
    from mklink.project_config import load_project_info
    from mklink.hpm_config import is_hpm_target
    from mklink.cmsis_dap.algorithm_catalog import discover_flash_algorithms

    project = (load_project_info(project_root) or {}) if not device else {}
    target = str(device or project.get('device') or project.get('target_part') or '').strip()
    if not target:
        return {'status': 'error', 'message': 'Specify --device or initialize a project with an exact target'}
    result = {'device': target, 'profile_written': False, 'flm_copied': False}
    if is_hpm_target(target):
        if flm:
            return {**result, 'status': 'error', 'message': 'HPM uses ROM API; FLM selection is unsupported'}
        result.update(status='detected', backend='hpm-rom', candidates=[])
    else:
        algorithms = discover_flash_algorithms(target, paths=paths)
        candidates = [{
            'algorithm_id': a.algorithm_id, 'name': a.file_name, 'size': a.flash_size,
            'flash_base': a.flash_start, 'ram_base': a.ram_start, 'ram_size': a.ram_size,
            'page_size': a.page_size, 'sector_sizes': list(a.sector_sizes),
            'source_kind': a.source_kind, 'source_name': a.source_name,
        } for a in algorithms]
        result.update(backend='flm', candidates=candidates)
        if not candidates:
            return {**result, 'status': 'unsupported',
                    'message': 'No local catalog algorithm matches this exact target; install its Pack or configure a custom algorithm'}
        selected = candidates
        if flm:
            key = str(flm).casefold()
            selected = [c for c in candidates if key in {c['algorithm_id'].casefold(), c['name'].casefold()}]
            if not selected:
                return {**result, 'status': 'error', 'message': 'Requested algorithm is not a candidate for this target'}
        if len(selected) != 1:
            result.update(status='needs_selection', message='Select an explicit algorithm_id; inspection does not choose by order')
        else:
            result.update(status='detected', selected_algorithm=selected[0])
    if read_idcode:
        result['idcode'] = (idcode_reader or _read_idcode)(port)
    return result
