"""Optional FastMCP surface for registered direct remote sites.

Importing this module never imports FastMCP.  The optional dependency is
loaded only by :func:`build_server` or :func:`main`.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


def register_tools(mcp: Any, registry: Any | None = None) -> None:
    """Register capability-gated tools on a FastMCP-compatible object."""

    if registry is None:
        from mklink.remote.sites import default_registry

        registry = default_registry()

    def client_for(site: str):
        return registry.client(site or None)

    def supported(client: Any, capability: str) -> None:
        if not client.supports(capability):
            raise RuntimeError(f"site does not advertise capability {capability!r}")

    @mcp.tool()
    def remote_sites() -> list[dict[str, Any]]:
        """List registered direct VPN/LAN sites; authentication tokens are omitted."""

        return registry.list()

    @mcp.tool()
    def remote_status(site: str = "") -> dict[str, Any]:
        """Return probe-independent status for a registered field site."""

        return client_for(site).call("agent.status")

    @mcp.tool()
    def remote_capabilities(site: str = "") -> dict[str, Any]:
        """Return the capabilities negotiated before any target operation."""

        client = client_for(site)
        return {
            name: capability.as_dict()
            for name, capability in client.handshake().capabilities.items()
        }

    @mcp.tool()
    def remote_call(
        operation: str,
        params: dict[str, Any] | None = None,
        site: str = "",
        confirm: bool = False,
    ) -> Any:
        """Invoke a declared operation.

        High-risk operations such as flash, erase, reset, breakpoint changes,
        memory/variable writes, serial writes, and Modbus writes require
        ``confirm=True`` and are rejected again by the field agent otherwise.
        """

        from mklink.remote.capabilities import operation_schema

        schema = operation_schema(operation)
        if schema is None:
            raise ValueError("operation is not declared")
        client = client_for(site)
        supported(client, schema.capability)
        values = dict(params or {})
        if schema.high_risk:
            if not confirm:
                raise ValueError("explicit confirmation is required")
            values["confirm"] = True
        return client.call(operation, **values)

    @mcp.tool()
    def remote_upload(path: str, site: str = "") -> dict[str, Any]:
        """Atomically upload a local engineer file and return an opaque reference."""

        client = client_for(site)
        supported(client, "transfer.upload")
        return client.upload(Path(path)).as_dict()

    @mcp.tool()
    def remote_flash(
        firmware: str,
        site: str = "",
        target_part: str | None = None,
        base_address: str | None = None,
        verify: bool = True,
        reset_after: bool = True,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """HIGH RISK: upload and program firmware; requires ``confirm=True``."""

        if not confirm:
            raise ValueError("explicit confirmation is required")
        client = client_for(site)
        supported(client, "transfer.upload")
        supported(client, "flash.online")
        remote_file = client.upload(Path(firmware))
        values: dict[str, Any] = {
            "firmware": remote_file.reference,
            "verify": verify,
            "reset_after": reset_after,
            "confirm": True,
        }
        if target_part is not None:
            values["target_part"] = target_part
        if base_address is not None:
            values["base_address"] = base_address
        return client.call("flash.program", **values)

    @mcp.tool()
    def remote_write_memory(
        address: int,
        data_hex: str,
        site: str = "",
        confirm: bool = False,
    ) -> dict[str, Any]:
        """HIGH RISK: write target memory; requires ``confirm=True``."""

        if not confirm:
            raise ValueError("explicit confirmation is required")
        try:
            data = bytes.fromhex(data_hex)
        except ValueError:
            raise ValueError("data_hex must contain hexadecimal bytes") from None
        client = client_for(site)
        supported(client, "target.memory")
        return client.call(
            "memory.write",
            address=address,
            data_b64=base64.b64encode(data).decode("ascii"),
            confirm=True,
        )


def build_server(registry: Any | None = None) -> Any:
    """Build the optional stdio server, importing FastMCP only on demand."""

    try:
        from fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(
            'fastmcp not installed. Run: pip install -e ".[mcp]"'
        ) from exc
    server = FastMCP("mklink-remote")
    register_tools(server, registry)
    return server


def main() -> int:
    server = build_server()
    server.run(transport="stdio")
    return 0


__all__ = ["build_server", "main", "register_tools"]


if __name__ == "__main__":
    raise SystemExit(main())
