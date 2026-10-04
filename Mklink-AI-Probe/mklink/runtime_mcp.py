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
        Use gui_call for uart_ports, serial/modbus start/status/stop, serial_send and modbus_transaction.
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
        or Modbus port/slave/registers settings. serial_send accepts port/data/hex; modbus_transaction
        accepts fc/start/quantity/values and optional slave (integer 1..247, defaults to the connected
        slave). The override affects only this request. Unknown fields are rejected; per-request
        timeout/retries are not supported. These explicit sends share the
        existing worker, may be issued by borrowers, and never retry an unknown result. Disconnect
        only detaches. Unsupported capabilities fail without a direct serial fallback.
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
