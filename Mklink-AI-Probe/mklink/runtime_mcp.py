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
                "limits": {"direct_read_max_bytes": 4096},
                "guidance": "Call connect, then GUI capabilities. Read shared history while GUI captures. Disconnect detaches only this AI client."}

    @server.tool()
    def discover_probes() -> list[dict]:
        """List physical probes, stable IDs, current COM ports and local aliases without opening CDC."""
        from mklink.probes import inventory
        return inventory()

    @server.tool()
    def set_probe_alias(probe: str, alias: str) -> dict:
        """Set this computer's alias for a stable probe ID or COM port. Does not change firmware."""
        from mklink.probes import set_alias
        return set_alias(probe, alias)

    @server.tool()
    def connect(port: str | None = None, axf: str | None = None, mcu: str | None = None,
                project_root: str | None = None, elf_backend: str | None = None, probe: str | None = None,
                client_name: str = 'AI client') -> dict:
        """Attach to the GUI's CDC session. Omitted configuration adopts its project/symbols.

        Explicit conflicting project/probe/symbol settings fail without replacing the GUI session.
        """
        with lock:
            if "client" not in holder:
                holder["client"] = RuntimeClient(project_root=project_root or ".", name=client_name)
            return holder['client'].connect(port=port, probe=probe, axf=axf, mcu=mcu, project_root=project_root, elf_backend=elf_backend)

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
    def gui_call(capability: str, arguments: dict | None = None) -> dict:
        """Invoke an advertised GUI capability on the shared backend.

        ping lists names. rtt_history/status and superwatch_snapshot/status reuse GUI acquisition.
        rtt_start or superwatch_start with {} subscribes if already running. Stop requires ownership
        and no other subscriber. Unsupported capabilities fail without a direct serial fallback.
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
