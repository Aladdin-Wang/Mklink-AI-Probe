"""Optional, acknowledged presentation on an existing GUI presence socket."""
import asyncio
import secrets
import time
from fastapi import HTTPException

TABS = frozenset({'superwatch', 'rtt', 'memory', 'symbols', 'hardfault', 'systemview'})


def windows(control):
    control.prune()
    return {'windows': [{'window_id': key, 'name': v['name']} for key, v in control.views.items()
                        if v.get('presentation') and v.get('live')]}


async def present(control, body):
    if (set(body) - {'window_id', 'tab'} or not isinstance(body.get('tab', 'superwatch'), str)
            or body.get('tab', 'superwatch') not in TABS):
        raise HTTPException(422, 'Choose a supported dashboard tab')
    key = body.get('window_id')
    if key is not None and (not isinstance(key, str) or not key or len(key) > 128):
        raise HTTPException(422, 'Invalid window_id')
    candidates = windows(control)['windows']
    if key is None:
        if len(candidates) != 1:
            raise HTTPException(409, {'reason': 'select_gui_window', **windows(control)})
        key = candidates[0]['window_id']
    view = control.views.get(key)
    if not view or not view.get('presentation'):
        raise HTTPException(404, 'GUI window unavailable or requires an update')
    if view.get('pending'):
        raise HTTPException(409, 'GUI presentation already pending')
    request_id = secrets.token_hex(12)
    future = asyncio.get_running_loop().create_future()
    view['pending'] = (request_id, future)
    try:
        await asyncio.wait_for(view['socket'].send_json({'type': 'present', 'request_id': request_id,
            'tab': body.get('tab', 'superwatch'), 'expires_at': time.time() + 3}), timeout=1)
        result = await asyncio.wait_for(future, timeout=3)
        return {'window_id': key, 'tab': body.get('tab', 'superwatch'), 'status': result}
    except (TimeoutError, RuntimeError, OSError):
        return {'window_id': key, 'status': 'unconfirmed', 'request_id': request_id}
    finally:
        view.pop('pending', None)


def acknowledge(view, message):
    pending = view.get('pending')
    if pending and message.get('type') == 'present_result' and message.get('request_id') == pending[0]:
        if not pending[1].done():
            pending[1].set_result('displayed' if message.get('ok') is True else 'rejected')
