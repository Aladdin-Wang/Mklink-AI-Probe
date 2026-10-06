"""Graceful per-probe idle exit; no direct process termination or serial handling."""
from __future__ import annotations
import asyncio
import logging
import time

IDLE_SECONDS = 5.0

def idle_blocked(control):
    control.prune()
    agent = getattr(control.app.state, 'site_agent', None)
    remote = getattr(control.app.state, 'remote_window_activity', lambda: False)
    return bool(control.sessions or control.views or control.inflight_requests
                or control.operation_lock.locked() or control.attach_lock.locked()
                or control.uart_operations or control.job_busy()
                or remote() or (agent and agent.active_connections))

def check_idle(control, *, now=None, timeout=IDLE_SECONDS):
    """Event-loop-only admission check, with no await between check and stop."""
    now = time.monotonic() if now is None else now
    if control.stopping:
        return False
    if idle_blocked(control):
        # Lease expiry and the idle deadline overlap. Only ongoing work extends
        # the deadline here; renewing a lease already records real HTTP activity.
        if (control.inflight_requests or control.operation_lock.locked()
                or control.attach_lock.locked() or control.uart_operations or control.job_busy()):
            control.last_activity = now
        return False
    if now-control.last_activity < timeout or not callable(control.shutdown):
        return False
    control.stopping = True
    logging.getLogger(__name__).info('No runtime clients for %.0fs; closing idle backend', timeout)
    control.shutdown()  # uvicorn runs the existing stream/device shutdown handlers
    return True

def install_idle_shutdown(app, control):
    task = None
    async def monitor():
        while True:
            # Keep the one-second activity scan, but wake at a nearer idle
            # deadline instead of rounding it up to the next scan. If expired
            # owners still block shutdown, retain the normal scan cadence.
            remaining = IDLE_SECONDS - (time.monotonic() - control.last_activity)
            await asyncio.sleep(remaining if 0 < remaining < 1 else 1)
            try:
                if check_idle(control):
                    return
            except Exception:
                # Unknown activity is not permission to terminate hardware work.
                control.last_activity = time.monotonic()
                logging.getLogger(__name__).exception('Idle activity check failed; keeping runtime alive')
    async def startup():
        nonlocal task
        task = asyncio.create_task(monitor())
    async def shutdown():
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
    app.add_event_handler('startup', startup)
    app.add_event_handler('shutdown', shutdown)
