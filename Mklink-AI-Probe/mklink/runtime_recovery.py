"""Recover only a lost transport on the same reserved physical probe.

No submitted command is replayed. A new read-only capture segment may resume;
explicit stop/switch, jobs and client lifetimes retain their normal authority.
"""
import asyncio
import logging
import time

from mklink.runtime_api import settle

logger = logging.getLogger(__name__)
RECOVERY_GRACE_SECONDS = 5.0


class TransportRecovery:
    def __init__(self, control):
        self.control = control
        self.device = None
        self.identity = None
        self.plan = []
        self.idcode = 0
        self.clock_hz = None
        self.pending = False
        self.attempts = 0
        self.next_attempt = 0
        self.lost_at = None
        self.expired = False
        self.status = {'state': 'idle', 'attempts': 0}

    def publish(self, state, **detail):
        self.status = {'state': state, 'attempts': self.attempts, **detail}
        self.control.app.state.mklink_state['connection_recovery'] = self.status

    def reset(self):
        self.device = None
        self.identity = None
        self.idcode = 0
        self.clock_hz = None
        self.plan = []
        self.pending = False
        self.attempts = 0
        self.next_attempt = 0
        self.lost_at = None
        self.expired = False
        self.publish('idle')

    def expire_if_due(self):
        if self.lost_at is not None and time.monotonic() - self.lost_at >= RECOVERY_GRACE_SECONDS:
            if not self.expired:
                self.expired = True
                self.plan = []
                self.publish('expired')
            return True
        return self.expired

    def retains_session(self):
        """Also cover the interval before the monitor observes the first error."""
        c = self.control
        device = c.app.state.mklink_state.get('device')
        return bool(not c.stopping and device is not None and not self.expire_if_due()
                    and c.info.get('probe_id') not in (None, 'lobby')
                    and self.attempts < 5
                    and ((self.pending and self.device is device and self.identity == c.info.get('probe_id'))
                         or isinstance(getattr(getattr(device, '_bridge', None), '_transport_error', None), BaseException)))

    async def tick(self):
        from mklink.remote.dashboards import get_managers
        c = self.control
        state = c.app.state.mklink_state
        c.prune()
        device = state.get('device')
        identity = c.info.get('probe_id')
        # Never create a connection merely because a probe is plugged in.
        if c.stopping or not device or identity in (None, 'lobby'):
            self.reset()
            return
        if self.device is not device or self.identity != identity:
            self.reset()
            self.device, self.identity = device, identity
        if self.expire_if_due():
            return
        if not (c.target_sessions or c.gui_active()):
            self.plan = []
            return
        if device.connected and not self.pending:
            self.idcode = device.idcode
            self.clock_hz = device.clock_hz
            self.plan = []
            for name, manager in get_managers().items():
                if name not in ('rtt', 'superwatch') or not manager.running:
                    continue
                restart = getattr(manager, '_restart_after_operation', None)
                if callable(restart):
                    if name == 'rtt' and hasattr(manager, '_line_assembler'):
                        encoding = manager._line_assembler.encoding
                        encodings = {ch: decoder._line_assembler.encoding
                                     for ch, decoder in manager._channel_decoders.items()}
                        def restart_rtt(start=restart, m=manager, default=encoding, channels=encodings):
                            start()
                            m.set_encoding(default)
                            for channel, value in channels.items():
                                m.set_encoding(value, channel)
                        restart = restart_rtt
                    collecting = getattr(manager, '_collecting', None)
                    paused = (not collecting.is_set() if collecting is not None
                              else bool(getattr(manager, 'paused', False)))
                    self.plan.append((name, manager, restart, paused,
                                      getattr(manager, '_explicit_stop_version', 0)))
            return
        if not self.pending:
            error = getattr(getattr(device, '_bridge', None), '_transport_error', None)
            if not isinstance(error, BaseException):
                return  # A target error/failed explicit connection is not USB loss.
            self.pending = True
            self.lost_at = time.monotonic()
            self.publish('waiting', error=str(error), grace_seconds=RECOVERY_GRACE_SECONDS)
        if self.attempts >= 5 or time.monotonic() < self.next_attempt:
            return
        if (c.lifecycle_pending or c.operation_lock.locked() or c.attach_lock.locked()
                or c.job_busy()):
            return
        from mklink.probes import select_probe
        try:
            selected = await asyncio.to_thread(select_probe, self.identity)
        except Exception:
            return  # Enumeration only while absent; no repeated open attempts.
        if selected['probe_id'] != self.identity:
            return

        async def recover():
            # Recheck after admission; a user may have disconnected or switched.
            if (state.get('device') is not device or c.info.get('probe_id') != self.identity
                    or not (c.target_sessions or c.gui_active())):
                self.reset()
                return
            if self.expire_if_due():
                return
            from mklink.remote.api import (
                _dashboard_start_lock, _dashboard_worker_alive,
                stop_dashboard_manager, _start_dashboard_manager_transaction,
            )
            self.attempts += 1
            self.publish('reconnecting')
            async with _dashboard_start_lock(state):
                drained = False
                try:
                    # Drain all bridge workers before closing their handle.
                    from mklink.remote.dashboards import BRIDGE_DASHBOARD_TYPES
                    for name, manager in get_managers().items():
                        if name in BRIDGE_DASHBOARD_TYPES:
                            try:
                                await asyncio.to_thread(stop_dashboard_manager, state, name, manager)
                            except Exception:
                                # A dead transport may reject STOP after its worker
                                # has exited. Only a live worker prevents closing.
                                if _dashboard_worker_alive(manager):
                                    raise
                            if _dashboard_worker_alive(manager):
                                raise RuntimeError(f'{name}: worker still stopping')
                    drained = True
                    # Keep parsed catalog and client symbol versions unchanged.
                    await asyncio.to_thread(device.close)
                    if self.expire_if_due():
                        return
                    current = await asyncio.to_thread(select_probe, self.identity)
                    if current['probe_id'] != self.identity:
                        raise RuntimeError('Probe identity changed')
                    if self.expire_if_due():
                        return
                    device._port = current['port']
                    await asyncio.to_thread(device._connect, load_symbols=False)
                    from mklink.device import initialize_target
                    actual_id = device.idcode if getattr(device, '_initialize_target_now', False) else await asyncio.to_thread(
                        initialize_target, device._bridge, device._flash,
                        mcu_hint=device._mcu_hint, project_root=device._project_root)
                    if self.clock_hz:
                        await asyncio.to_thread(device._flash.set_swd_clock, self.clock_hz)
                    if self.expire_if_due():
                        await asyncio.to_thread(device.close)
                        return
                except Exception as error:
                    if self.expire_if_due():
                        if drained:
                            await asyncio.to_thread(device.close)
                        return
                    self.next_attempt = time.monotonic() + min(10, 2 ** self.attempts)
                    self.publish('failed' if self.attempts >= 5 else 'waiting', error=str(error))
                    logger.warning('Same-probe transport recovery attempt %s: %s', self.attempts, error)
                    return
                # The transport recovered within the grace period. Capture
                # initialization may take longer without extending that period.
                self.lost_at = None
                restored, errors = [], []
                source_pending = bool((state.get('file_source_change') or {}).get('pending'))
                catalog = getattr(device, 'symbol_catalog', None)
                if catalog is not None:
                    try:
                        source_pending = source_pending or await asyncio.to_thread(catalog.is_stale)
                    except Exception as error:
                        source_pending = True
                        errors.append(f'symbols: {error}')
                # IDCODE is only a compatibility check, never proof of firmware identity.
                compatible = bool(self.idcode and actual_id == self.idcode)
                for name, manager, restart, paused, stop_version in self.plan:
                    if (getattr(manager, '_explicit_stop_version', 0) != stop_version
                            or not c.acquisition_owner(name)['active']):
                        continue
                    if not compatible:
                        errors.append(f'{name}: target ID changed or unavailable; start explicitly')
                        continue
                    if source_pending:
                        errors.append(f'{name}: firmware file changed; reload manually before resuming')
                        continue
                    try:
                        await _start_dashboard_manager_transaction(state, name, manager, restart)
                        if paused:
                            manager.pause()
                        restored.append(name)
                    except Exception as error:
                        errors.append(f'{name}: {error}')
                self.pending = False
                self.lost_at = None
                self.plan = []
                self.publish('restored', restored=restored, errors=errors,
                             data_gap=True, restored_at=time.time())
                self.attempts = 0
        await c.run_lifecycle('auto-reconnect', recover)


def install_transport_recovery(app, control):
    recovery = TransportRecovery(control)
    control.recovery = recovery
    task = None

    async def monitor():
        while True:
            await asyncio.sleep(.5)
            try:
                await recovery.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Transport recovery check failed')

    async def startup():
        nonlocal task
        task = asyncio.create_task(monitor())

    async def shutdown():
        if task:
            task.cancel()
            try:
                await settle(task)
            except asyncio.CancelledError:
                pass
    app.add_event_handler('startup', startup)
    app.add_event_handler('shutdown', shutdown)
