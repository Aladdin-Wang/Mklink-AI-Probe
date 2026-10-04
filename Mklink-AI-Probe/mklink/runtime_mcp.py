"""MCP adapter for the shared GUI backend. No Device or bridge is created here."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import threading

from mklink.runtime import RuntimeClient, RuntimeErrorResponse, VERSION


def build_server():
    from fastmcp import FastMCP
    from mklink.runtime_capabilities import CAPABILITIES
    from mklink.memory_access import BATCH_READ_MAX_REGIONS, BATCH_READ_MAX_TOTAL_BYTES

    holder = {}
    lock = threading.Lock()

    def close():
        with lock:
            current = holder.pop('client', None)
            if current:
                holder['last_info'] = current.info
                current.close()

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(close)
            except Exception:
                logging.getLogger(__name__).warning('Shared MCP detach failed; session will expire', exc_info=True)

    server = FastMCP("mklink-shared-runtime", lifespan=lifespan)
    from mklink.mcp_analysis import register_systemview_offline_tools
    register_systemview_offline_tools(server)
    from mklink.mcp_configuration import register_configuration_offline_tools
    register_configuration_offline_tools(server)
    from mklink.mcp_peripheral import register_peripheral_offline_tools
    register_peripheral_offline_tools(server)

    def client():
        with lock:
            current = holder.get('client')
            if current is None:
                raise RuntimeErrorResponse('Call connect first')
            return current

    @server.tool()
    def ping(force_update_check: bool = False) -> dict:
        """Shared-runtime health and supported GUI capabilities; does not open CDC."""
        from mklink.update_check import check_for_update
        return {"ok": True, "version": VERSION, "mode": "shared-cdc", "capabilities": sorted(CAPABILITIES),
                "update": check_for_update(force=force_update_check),
                "limits": {"direct_read_max_bytes": 4096, "batch_read_max_regions": BATCH_READ_MAX_REGIONS,
                           "batch_read_max_total_bytes": BATCH_READ_MAX_TOTAL_BYTES},
                "guidance": "Call connect, then GUI capabilities. Read shared history while GUI captures. Disconnect detaches only this AI client."}

    @server.tool()
    def discover_probes() -> list[dict]:
        """List physical probes, stable IDs, current COM ports and local aliases without opening CDC."""
        from mklink.probes import inventory
        return inventory()

    @server.tool()
    def get_power(probe: str | None = None) -> dict:
        """Read probe VCC telemetry via the shared backend, without target initialization.

        Does not change power or clocks. Requires idle CDC; never stops capture.
        Uses the attached probe when omitted, otherwise select a probe ID/alias.
        """
        from mklink.runtime import query_probe
        with lock:
            current = holder.get('client')
            info = current.info if current and not probe else None
        return query_probe('power_read', info=info, probe=probe)

    @server.tool()
    def read_configuration(part_number: str, model: str = "V4") -> dict:
        """Read bounded public option-byte/OTP fields via the connected shared backend.

        Requires explicit connect and idle CDC. Validates the target identity;
        never changes protection, writes OTP or stops another client's capture.
        """
        return client().call('read_configuration', {'part_number': part_number, 'model': model})

    @server.tool()
    def measure_dump_memory(regions: list[dict], duration: float = 3.0,
                            period: float = 0.000001, speed_profile: str | None = None) -> dict:
        """Measure complete dump samples through the selected shared backend.

        1..15 regions, at most 4096 bytes, 0.5..30 seconds; first sample has
        a 2s startup allowance, then duration includes 200ms warmup. Returns
        rate/interval percentiles and integrity counters, not raw samples.
        Requires idle CDC; never stops GUI capture or replays a failed run.
        Omit speed_profile to retain the shared clock.
        """
        return client().call('measure_dump_memory', {'regions': regions, 'duration': duration,
                            'period': period, 'speed_profile': speed_profile})

    @server.tool()
    def dump_memory(regions: list[dict], sample_count: int = 1, timeout: float = 10.0,
                    speed_profile: str | None = None) -> dict:
        """Capture 1..64 complete one-shot samples through the shared backend.

        1..8 integer address/size regions, at most 512 KiB over all samples.
        Timeout is per sample (0.001..60 seconds). An explicit speed_profile
        changes the shared probe clock; omitted retains it. Requires idle CDC,
        never stops GUI capture or repeats a failed sample. Returns only after
        command mode has been confirmed; detached callers do not cancel work.
        """
        return client().call('dump_memory', {'regions': regions, 'sample_count': sample_count,
                                           'timeout': timeout, 'speed_profile': speed_profile})

    @server.tool()
    def flush_memory(writes: list[dict], verify: bool = True) -> dict:
        """Write 1..8 regions (12 KiB total) through the shared backend.

        Reads each batch back by default. Stops on the first error, never
        retries or interrupts GUI capture. Writes are ordered, not atomic;
        earlier batches may remain written after failure.
        """
        return client().call('flush_memory', {'writes': writes, 'verify': verify})

    @server.tool()
    def read_memory_regions(regions: list[dict]) -> dict:
        """Read 1..16 regions, at most 4096 bytes, through the shared backend.

        Each region has integer address and size. Results preserve order;
        adjacent/overlapping ranges share a read, gaps are never read.
        Separate reads are not atomic. Requires idle CDC; never stops GUI
        capture or retries a failed/partial response.
        """
        return client().call('read_memory_regions', {'regions': regions})

    @server.tool()
    def select_peripherals(target_id: str = "", chip: str = "", svd: str = "") -> dict:
        """Select one peripheral catalog through the GUI's manager.

        Other AI/SDK clients must detach first. Stop SuperWatch explicitly;
        never changes another probe or silently stops an acquisition.
        """
        if svd:
            from pathlib import Path
            svd = str(Path(svd).expanduser().resolve())
        return client().call('select_peripherals', {
            key: value for key, value in {'target_id': target_id, 'chip': chip, 'svd': svd}.items() if value})

    @server.tool()
    def list_peripherals(query: str = "") -> dict:
        """List readable register/field metadata from the connected GUI catalog."""
        return client().call('list_peripherals', {'q': query})

    @server.tool()
    def capture_peripherals(names: list[str], duration: float = 1.0, period: float = .01) -> dict:
        """Sample selected side-effect-free peripheral channels for up to 30 seconds.

        Requires idle CDC; no automatic stop, reconnect or replay. Maximum 64
        channels / 15 regions; finite buffered result, not an atomic snapshot.
        """
        return client().call('capture_peripherals', {'names': names, 'duration': duration, 'period': period})

    @server.tool()
    def set_probe_alias(probe: str, alias: str) -> dict:
        """Set this computer's alias for a stable probe ID or COM port. Does not change firmware."""
        from mklink.probes import set_alias
        return set_alias(probe, alias)

    @server.tool()
    def connect(port: str | None = None, axf: str | None = None, mcu: str | None = None,
                project_root: str | None = None, elf_backend: str | None = None, probe: str | None = None,
                client_name: str = 'AI client', scope: str = 'target') -> dict:
        """Attach to the shared backend: target (default) or independent UART scope.

        Explicit conflicting project/probe/symbol settings fail without replacing the GUI session.
        scope='uart' attaches without MCU/CDC initialization, including the unselected lobby.
        Use gui_call for uart_ports, serial/modbus start/status/stop, serial_send, modbus_transaction
        and modbus_probe (one read-only address probe through the existing worker).
        Use probe to choose a backend; target port/AXF/MCU options require scope='target'.
        """
        with lock:
            if "client" not in holder:
                holder["client"] = RuntimeClient(project_root=project_root or ".", name=client_name)
            return holder['client'].connect(port=port, probe=probe, axf=axf, mcu=mcu, project_root=project_root, elf_backend=elf_backend, scope=scope)

    @server.tool()
    def disconnect() -> dict:
        """Detach this AI session. The GUI, acquisition, and device remain connected."""
        close()
        return {"detached": True, "device_closed": False}

    @server.tool()
    def device_status() -> dict:
        """Read the shared device status without touching CDC."""
        return client().call("device_status")

    @server.tool()
    def set_debug_speed(profile: str) -> dict:
        """Set low/medium/high/ultra through the shared backend; busy during capture.

        Changes this probe's debug clock and saves the project profile after success.
        All attached clients share it. Inspect gui_call('debug_speed') for cached status.
        """
        return client().call('set_debug_speed', {'profile': profile})

    @server.tool()
    def read_memory(address: int, size: int) -> dict:
        """Read 1..4096 bytes through the shared backend. Busy during continuous acquisition."""
        return client().call("read_memory", {"address": hex(address), "size": size})

    @server.tool()
    def read_variable(name: str) -> dict:
        """Read one variable using the GUI's symbols. For live capture use a shared snapshot."""
        return client().call("read_variable", {"name": name})

    @server.tool()
    def write_memory(address: int, data_hex: str) -> dict:
        """Write 1..4096 bytes via shared admission. Busy during capture; never retries."""
        return client().call('write_memory', {'address': hex(address), 'data_hex': data_hex})

    @server.tool()
    def write_variable(name: str, value: int) -> dict:
        """Write an integer variable through the shared symbols. Busy during capture."""
        return client().call('write_variable', {'name': name, 'value': value})

    @server.tool()
    def read_register(name: str) -> dict:
        """Read one named register through the shared device, subject to capture conflicts."""
        return client().call('read_register', {'name': name})

    @server.tool()
    def search_symbols(query: str) -> dict:
        """Search the backend's loaded symbols without reading hardware."""
        return client().call('symbol_search', {'q': query})

    @server.tool()
    def runtime_status() -> dict:
        """Inspect bound probe presence, GUI/AI/CLI clients, captures and current operation."""
        from mklink.runtime import request
        current = client()
        if current.info is None:
            raise RuntimeErrorResponse('Connect to a selected probe first')
        return request(current.info, 'GET', '/api/runtime/control/status')

    @server.tool()
    def rtt_start(addr: str | None = None, channel: int | None = None, mode: int | None = None,
                  search_size: int | None = None, encoding: str | None = None) -> dict:
        """Start RTT or subscribe to existing RTT when all options are omitted."""
        options = {'addr': addr, 'channel': channel, 'mode': mode, 'search_size': search_size, 'encoding': encoding}
        return client().call('rtt_start', {k: v for k, v in options.items() if v is not None})

    @server.tool()
    def rtt_stop() -> dict:
        """Stop only RTT owned by this session with no other subscribers; otherwise detach."""
        return client().call('rtt_stop')

    @server.tool()
    def rtt_history() -> dict:
        """Read the bounded backend RTT history; does not create another serial reader."""
        return client().call('rtt_history')

    @server.tool()
    def rtt_write(text: str) -> dict:
        """Send at most 256 UTF-8 bytes through active RTT; reserved stop sequences are rejected."""
        return client().call('rtt_write', {'data_hex': text.encode('utf-8').hex()})

    @server.tool()
    def superwatch(action: str = 'status', arguments: dict | None = None) -> dict:
        """Shared SuperWatch: status/items/values/snapshot/add/remove/start/stop/pause/resume/interval/write.

        write requires path, generation from gui_call('symbol_status'), and value. It uses the existing typed
        live-write transaction. Start with empty arguments subscribes to an existing capture.
        """
        if action not in {'status', 'items', 'values', 'snapshot', 'add', 'remove', 'start', 'stop', 'pause', 'resume', 'interval', 'write'}:
            raise ValueError('Unsupported SuperWatch action')
        return client().call('superwatch_'+action, arguments)

    @server.tool()
    def systemview(action: str = 'status', arguments: dict | None = None) -> dict:
        """Shared SystemView: status/history/start/stop/pause/resume. No private CDC reader."""
        if action not in {'status', 'history', 'start', 'stop', 'pause', 'resume'}:
            raise ValueError('Unsupported SystemView action')
        return client().call('systemview_'+action, arguments)

    @server.tool()
    def gui_call(capability: str, arguments: dict | None = None) -> dict | list[dict]:
        """Invoke an advertised GUI capability on the shared backend.

        ping lists names. rtt_history/status and superwatch_snapshot/status reuse GUI acquisition.
        Acquisition start with {} subscribes if already running; new settings require an idle manager.
        Stop requires ownership and no other subscriber. UART start accepts serial ports [{port, baudrate}]
        plus optional profile/auto_reply_rules, executed once by the backend. serial_status.automation
        reports the validated profile/rules; borrowers subscribe with {} and compare explicit settings,
        never replace them. Shared arguments including automation remain limited to 16 KiB.
        serial_status also returns session/latest_frames, one parsed RX snapshot per port from
        the backend parser: per-port seq, timestamp, size, a 256-byte hex_preview/truncated flag,
        crc_valid and fields (value/raw/unit). This is latest state, not lossless frame history.
        Restart changes session and clears snapshots. Nonfinite device floats are strings, not zero.
        serial_exchange accepts port, data (hexadecimal, at most 4096 decoded bytes), timeout 0..5 seconds.
        It writes once and returns data (hex) and bytes (at most 65536). Zero timeout does not wait for RX.
        Same-port sends, auto replies and sequences cannot interleave; other ports remain usable.
        RX may include buffered or unsolicited device bytes, not a proven protocol response.
        Its raw RX/TX is visible in the ordinary GUI/history/recording channel, without auto replies.
        Modbus start accepts port/slave/registers settings. serial_send accepts port/data/hex; modbus_transaction
        accepts fc/start/quantity/values and optional slave (integer 1..247, defaults to the connected
        slave). The override affects only this request. Unknown fields are rejected.
        FC07 accepts fc/slave only and returns status. FC22 accepts start/and_mask/or_mask;
        it acknowledges masks without claiming a resulting register value. FC23 accepts
        start/quantity for reading and write_start/values for writing (at most 125 reads and
        121 writes), in one RTU transaction; returned values are the read result.
        Per-request timeout/retries are not supported. These explicit sends share the
        existing worker and may be issued by borrowers. The runtime never replays an unknown
        HTTP result; Modbus still honors the connection's configured protocol retries, which
        can retransmit a write when its response is lost. Disconnect
        only detaches. Unsupported capabilities fail without a direct serial fallback.
        serial_broadcast accepts data and optional hex and sends once to every configured port,
        returning per-port results. Partial/unknown writes must not be retried automatically.
        serial_send_file accepts port, path (regular file on the backend computer), optional hex
        (ASCII hex file). Decoded payload is 1..65536 bytes; input file at most 256 KiB. It starts
        the existing per-port sequence in 4096-byte chunks, 20 ms apart, with no acknowledgement
        from the target. Monitor/cancel via serial_status.send_sequences/serial_sequence_stop.
        serial_sequence_start accepts port, commands [{data, hex?}], interval_ms 20..3600000,
        repeat 1..1000000 (0 runs until stopped). At most 64 commands, each 1..4096 bytes,
        total 64 KiB and the normal RPC body limit. The existing reader sends in order;
        serial_status.send_sequences reports per-port sent counts and state. One sequence
        per port; serial_sequence_stop accepts port. Client disconnect keeps it running.
        Stop/protocol handoff cancels it. Failed/possibly partial writes are never retried.
        serial_recording_start starts one shared backend file logger: path (new file on backend
        machine), format txt/csv, max_size rotation bytes (0 disables), optional configured ports.
        It survives client disconnects; serial_status.recording reports running/stopping/completed/failed
        and error. serial_recording_stop drains a bounded history tail; serial_stop drains producer
        shutdown bytes too. Existing files and concurrent recorders are rejected. Disk/ring overflow
        errors mean incomplete recording, never success. Ordinary UART only, not YMODEM trace.
        serial_history reads raw ordinary UART batches from the existing producer, including
        unterminated data, without opening or sending on a port. {} opens at the tail;
        continue with session/after=next_seq and limit (1..256). Each entry contains seq,
        port, direction, hex, size, batch-publication timestamp_ns and first_monotonic/last_monotonic
        receive times (seconds on this host's monotonic clock). idle_cutoffs contains each port's
        completed-reader time for idle parsing after all history pages have been consumed. The response includes
        config/running/ports/latest_seq and dropped_batches across all ports.
        ports reports each reader state; an error is not a successful end of capture. Retention is 512
        batches of at most 4096 bytes; callers filter ports after advancing the global cursor.
        Stop retains final batches; restart changes session and old cursors fail with 409.
        This excludes YMODEM trace and parsed profile fields; it is not lossless capture.
        modbus_history reads the existing 500-event history without sending on the UART.
        Call with {} to open at the current tail, then session/after=next_seq and optional
        limit (1..256). Entries contain seq/session, frames contain actual hex/direction/CRC.
        The response includes connection, running, latest_seq and dropped (all event types).
        A changed session fails with 409; explicitly reopen, never carry a cursor to another
        connection. This is bounded best-effort history, not lossless capture.
        modbus_probe accepts slave/address; it probes one FC03 register with a 150ms timeout,
        zero retries and restores the connection's timing after completion. The result distinguishes
        a response (including an exception code) from no response; transport errors abort the request.
        modbus_loop_start uses the open connection's default slave and accepts fc/start,
        quantity or values, interval (0.02..3600 seconds), and count (0..100000; zero continuous).
        It shares the GUI loop: a second active loop is rejected. Each successful transaction
        is followed by the full interval; the first error stops the loop without closing the port.
        Disconnect keeps it running. Inspect modbus_status.loop, then explicitly call
        modbus_loop_stop with {} to stop the shared loop. An in-flight write cannot be undone.
        serial_ymodem_start accepts port and path to a regular file on the backend computer
        (1..32 MiB; UTF-8 basename at most 31 bytes, no control characters). It returns the
        existing GUI transfer_id immediately; acceptance is not completed delivery. Disconnect
        does not cancel. Query serial_ymodem_status and serial_ymodem_trace (after/limit) and
        explicitly call serial_ymodem_cancel with {} to cancel the current shared transfer.
        Cancellation cannot undo received data. Do not blindly resubmit after an uncertain reply.
        Only one transfer runs per backend; other open ports remain usable.
        """
        return client().call(capability, arguments)

    @server.tool()
    def start_job(action: str, request_id: str, confirm: bool = False, arguments: dict | None = None) -> dict:
        """Submit flash/erase/reset to this probe. Requires explicit confirm and a unique request_id.

        Stop capture first. Disconnect does not cancel. Keep the returned job_id and query job_status;
        never retry an unknown hardware result. Deduplication retains only the latest 64 jobs.
        flash arguments: firmware (explicit local path), verify and reset_after (booleans).
        """
        return client().start_job(action, request_id=request_id, confirm=confirm, arguments=arguments)

    @server.tool()
    def job_status(job_id: str | None = None, probe: str | None = None) -> dict:
        """Read retained exclusive-job results without touching hardware. Unknown is never success."""
        from mklink.runtime import job_status as query_jobs, selected_runtime
        current = holder.get('client')
        info = selected_runtime(probe) if probe else (current.info if current else holder.get('last_info'))
        return query_jobs(info, job_id)
    return server


def run():
    from mklink.mcp_stdio import isolate_stdio_protocol
    with isolate_stdio_protocol():
        build_server().run(transport="stdio", show_banner=False)
