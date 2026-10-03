"""MCP adapter for the shared GUI backend. No Device or bridge is created here."""
from __future__ import annotations

import atexit
import threading

from mklink.runtime import RuntimeClient, VERSION


def build_server():
    from fastmcp import FastMCP
    from mklink.runtime_api import CAPABILITIES

    server = FastMCP("mklink-shared-runtime")
    holder = {}
    lock = threading.Lock()

    def client():
        if "client" not in holder:
            holder["client"] = RuntimeClient()
        return holder["client"]

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
                project_root: str | None = None, elf_backend: str | None = None, probe: str | None = None) -> dict:
        """Attach to the GUI's CDC session. Omitted configuration adopts its project/symbols.

        Explicit conflicting project/probe/symbol settings fail without replacing the GUI session.
        """
        with lock:
            if "client" not in holder:
                holder["client"] = RuntimeClient(project_root=project_root or ".")
            return client().connect(port=port, probe=probe, axf=axf, mcu=mcu, project_root=project_root, elf_backend=elf_backend)

    @server.tool()
    def disconnect() -> dict:
        """Detach this AI session. The GUI, acquisition, and device remain connected."""
        with lock:
            current = holder.pop("client", None)
            if current:
                current.close()
        return {"detached": True, "device_closed": False}

    @server.tool()
    def device_status() -> dict:
        """Read the shared device status without touching CDC."""
        return client().call("device_status")

    @server.tool()
    def read_memory(address: int, size: int) -> dict:
        """Read 1..4096 bytes through the shared backend. Busy during continuous acquisition."""
        return client().call("read_memory", {"address": hex(address), "size": size})

    @server.tool()
    def read_variable(name: str) -> dict:
        """Read one variable using the GUI's symbols. For live capture use a shared snapshot."""
        return client().call("read_variable", {"name": name})

    @server.tool()
    def gui_call(capability: str, arguments: dict | None = None) -> dict:
        """Invoke an advertised GUI capability on the shared backend.

        ping lists names. rtt_history/status and superwatch_snapshot/status reuse GUI acquisition.
        rtt_start or superwatch_start with {} subscribes if already running. Stop requires ownership
        and no other subscriber. Unsupported legacy tools require explicit exclusive --direct mode.
        """
        return client().call(capability, arguments)

    def close():
        try:
            current = holder.get("client")
            if current:
                current.close()
        except Exception:
            pass

    atexit.register(close)
    return server


def run():
    from mklink.mcp_server import _isolate_stdio_protocol
    with _isolate_stdio_protocol():
        build_server().run(transport="stdio", show_banner=False)
