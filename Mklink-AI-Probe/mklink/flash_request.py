"""Validate the shared flash request before accepting a persistent job."""
from __future__ import annotations


def validate_flash_request(arguments: dict) -> dict:
    allowed = {'firmware', 'verify', 'reset_after', 'target_part', 'base_address',
               'board', 'hpm_flash_cfg', 'swd_clock'}
    if not isinstance(arguments, dict) or arguments.keys() - allowed:
        raise ValueError('Unsupported flash arguments')
    result = dict(arguments)
    firmware = result.get('firmware')
    if not isinstance(firmware, str) or not firmware.strip() or len(firmware) > 4096:
        raise ValueError('An explicit firmware file is required')
    for key in ('verify', 'reset_after'):
        if key in result and type(result[key]) is not bool:
            raise ValueError(f'{key} must be a boolean')
    for key in ('target_part', 'board'):
        if key in result:
            value = result[key]
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError(f'{key} must be a nonempty string of at most 128 characters')
    if 'board' in result:
        from mklink.hpm_config import normalize_hpm_board
        result['board'] = normalize_hpm_board(result['board'])
    if 'base_address' in result:
        from mklink.hpm_config import normalize_hpm_address
        value = result['base_address']
        if type(value) not in (int, str):
            raise ValueError('base_address must be an integer or integer string')
        result['base_address'] = normalize_hpm_address(value)[0]
    if 'hpm_flash_cfg' in result:
        from mklink.hpm_config import normalize_hpm_flash_cfg
        value = result['hpm_flash_cfg']
        if not isinstance(value, list) or not all(isinstance(word, str) for word in value):
            raise ValueError('hpm_flash_cfg must contain four hexadecimal strings')
        words = normalize_hpm_flash_cfg(value)
        if any(int(word.rstrip('uU'), 16) > 0xffffffff for word in words):
            raise ValueError('hpm_flash_cfg words must fit in 32 bits')
        result['hpm_flash_cfg'] = list(words)
    if 'swd_clock' in result:
        from mklink.debug_speed import validate_clock_hz
        if type(result['swd_clock']) is not int:
            raise ValueError('swd_clock must be an integer')
        validate_clock_hz(result['swd_clock'])
    return result
