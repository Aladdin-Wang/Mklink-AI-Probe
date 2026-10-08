"""Validated security requests through the identity-bound shared runtime."""
from __future__ import annotations

import math
import time
import uuid
from pathlib import Path

_VOLTAGES_MV = frozenset({1800, 3300, 5000})


def validate_security_request(arguments):
    allowed = {'action', 'target_part', 'voltage_mv', 'confirm_user', 'confirm_data_loss',
               'firmware', 'base_address', 'frequency'}
    if not isinstance(arguments, dict) or set(arguments) - allowed:
        raise ValueError('Unsupported security arguments')
    action, target_part = arguments.get('action'), arguments.get('target_part')
    voltage_mv = arguments.get('voltage_mv')
    confirm_user = arguments.get('confirm_user', False)
    confirm_data_loss = arguments.get('confirm_data_loss', False)
    firmware, base_address = arguments.get('firmware'), arguments.get('base_address')
    frequency = arguments.get('frequency', 1_000_000)
    if not isinstance(action, str) or not isinstance(target_part, str):
        raise ValueError('action and target_part must be strings')
    if firmware is not None and not isinstance(firmware, str):
        raise ValueError('firmware must be a local path string')
    if type(confirm_data_loss) is not bool:
        raise ValueError('confirm_data_loss must be boolean')
    normalized_action = str(action or "").strip().casefold()
    if normalized_action not in {"lock", "unlock"}:
        raise ValueError("action must be lock or unlock")
    part = str(target_part or "").strip()
    if not part:
        raise ValueError("target_part is required")
    nrf54l_request = part.casefold() in {"nrf54l", "nrf54l15"}
    if nrf54l_request:
        if voltage_mv is not None:
            raise ValueError("nRF54L15 CTRL-AP security does not change VCC; omit voltage_mv")
    elif type(voltage_mv) is not int or voltage_mv not in _VOLTAGES_MV:
        raise ValueError("voltage_mv must be 1800, 3300, or 5000")
    if confirm_user is not True:
        raise ValueError("security operation requires explicit confirmation")
    if normalized_action == "unlock" and confirm_data_loss is not True:
        raise ValueError(
            "unlock requires explicit confirmation that protected nonvolatile data will be erased"
        )
    if normalized_action == "lock" and not str(firmware or "").strip():
        raise ValueError("lock requires a firmware image to verify immediately before protection")
    if (
        isinstance(frequency, bool)
        or not isinstance(frequency, int)
        or frequency < 1
        or frequency > 10_000_000
    ):
        raise ValueError("frequency must be between 1 and 10000000 Hz")
    if base_address is not None and (type(base_address) is not int or not 0 <= base_address <= 0xFFFFFFFF):
        raise ValueError('base_address must be a 32-bit integer')
    if normalized_action == 'unlock' and (firmware is not None or base_address is not None):
        raise ValueError('unlock does not accept firmware or base_address')
    return dict(action=normalized_action, target_part=part, voltage_mv=voltage_mv,
                confirm_user=True, confirm_data_loss=confirm_data_loss,
                firmware=str(Path(firmware).expanduser().resolve()) if firmware else None,
                base_address=base_address, frequency=frequency)


def submit_security_job(info, arguments, *, request_id):
    """Submit once through the common runtime journal; never attach or wait for hardware."""
    arguments = validate_security_request(arguments)
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        raise ValueError('request_id must contain 1..128 characters')
    from mklink.runtime import request, RuntimeErrorResponse
    try:
        return request(info, 'POST', '/api/runtime/jobs/', dict(
            action='security', arguments=arguments, confirm=True, request_id=request_id))
    except RuntimeErrorResponse as error:
        raise RuntimeErrorResponse(
            f'{error}. Query runtime jobs for probe {info["probe_id"]}, '
            f'request_id={request_id}; do not replay an uncertain operation') from error


def run_security_operation(action, target_part, *, voltage_mv, confirm_user,
                           confirm_data_loss=False, firmware=None, base_address=None,
                           probe_id=None, frequency=1_000_000, timeout=240.0,
                           request_id=None, project_root='.'):
    """Submit once; timeout ends observation, never the backend or its hardware job.

    probe_id selects the shared USB ID, alias or command port, not a CMSIS-DAP ID.
    Keep request_id and query runtime jobs after any uncertain result.
    """
    arguments = validate_security_request(dict(
        action=action, target_part=target_part, voltage_mv=voltage_mv,
        confirm_user=confirm_user, confirm_data_loss=confirm_data_loss,
        firmware=firmware, base_address=base_address, frequency=frequency))
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError('timeout must be finite and positive')
    request_id = uuid.uuid4().hex if request_id is None else request_id
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        raise ValueError('request_id must contain 1..128 characters')
    from mklink.runtime import ensure_runtime, request, RuntimeErrorResponse
    info = ensure_runtime(project_root=project_root, probe=probe_id)
    hint = f'Query runtime jobs for probe {info["probe_id"]}, request_id={request_id}; do not replay an uncertain operation'
    job = submit_security_job(info, arguments, request_id=request_id)
    try:
        deadline = time.monotonic() + timeout
        while job['state'] not in {'succeeded', 'failed', 'unknown'}:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeErrorResponse(f'Observation timed out; backend job {job["job_id"]} continues')
            time.sleep(min(.2, remaining))
            job = request(info, 'GET', '/api/runtime/jobs/' + job['job_id'], timeout=min(35, remaining))
        if job['state'] != 'succeeded':
            raise RuntimeErrorResponse(f'Security job {job["job_id"]}: {job["state"]}; {job.get("error") or job.get("result")}')
        return {**job['result'], 'job_id': job['job_id'], 'request_id': request_id}
    except RuntimeErrorResponse as error:
        raise RuntimeErrorResponse(f'{error}. {hint}') from error


def start_security_operation(services, arguments, *, probe_id):
    """Start within shared admission; the runtime journal observes completion separately."""
    values = validate_security_request(arguments)
    normalized_action, part = values['action'], values['target_part']
    voltage_mv, firmware = values['voltage_mv'], values['firmware']
    base_address, frequency = values['base_address'], values['frequency']
    from mklink.remote.online_flash_api import (
        JobBody, _selected_probe, _resolved_target, _start_job_with_configuration,
        _target_flash_configuration)
    from mklink.cmsis_dap.security import require_security_capability

    _selected_probe(services.probe_provider, probe_id)
    target = _resolved_target(services.catalog, part)
    security = require_security_capability(target.part_number)
    nrf54l_ctrl_ap = security.family == 'nrf54l15-ctrl-ap'
    inspection = None
    if normalized_action == "lock":
        regions, fingerprint, _configured_paths = _target_flash_configuration(
            services, target.part_number
        )
        inspection = services.image_inspector.inspect(
            str(firmware), regions, base_address=base_address
        )
        services.image_targets[inspection.image_id] = (
            target.part_number.casefold(), fingerprint
        )

    if nrf54l_ctrl_ap:
        connect_mode = "attach" if normalized_action == "unlock" else "halt"
    elif normalized_action == "unlock" and security.family not in {
        "py32f030x8-rdp1", "gd32f303xe-spc"
    }:
        connect_mode = "under-reset"
    else:
        connect_mode = "halt"

    body = JobBody(
        actions=(
            ["connect", "verify", "lock", "reset", "disconnect"]
            if normalized_action == "lock"
            else ["connect", "unlock", "reset", "disconnect"]
        ),
        image_id=inspection.image_id if inspection is not None else None,
        base_address=base_address,
        preempt_ai=True,
        probe_id=probe_id,
        target_part=target.part_number,
        frequency=frequency,
        connect_mode=connect_mode,
        reset_mode="default" if nrf54l_ctrl_ap else "power-cycle",
        reset_voltage_mv=None if nrf54l_ctrl_ap else voltage_mv,
    )
    job_id, _snapshot = _start_job_with_configuration(services, body, target)
    return {
        'online_job_id': job_id, 'action': normalized_action, 'target_part': target.part_number,
        'voltage_mv': None if nrf54l_ctrl_ap else voltage_mv,
        'connect_mode': body.connect_mode, 'reset_mode': body.reset_mode,
        'verified_sha256': inspection.sha256 if inspection is not None else None,
    }
