from __future__ import annotations

import copy

import asyncio
from types import SimpleNamespace

import pytest

from mklink import mcp_server, mcp_stream_bridge, observe_bridge


def test_real_fastmcp_dump_memory_jsonrpc_result_snapshot(monkeypatch):
    fastmcp = pytest.importorskip("fastmcp")
    bridge = object()
    monkeypatch.setattr(
        mcp_server,
        "_connected_device",
        lambda: SimpleNamespace(_bridge=bridge),
    )
    monkeypatch.setattr(
        "mklink.dump_memory.read_dump_memory_regions_once",
        lambda actual_bridge, _pairs, *, timeout, cancelled=None: (
            b"AB" if actual_bridge is bridge and timeout == 0.1 else b"",
        ),
    )
    monkeypatch.setattr(
        mcp_stream_bridge,
        "publish_mcp_memory_regions",
        lambda *_args, **_kwargs: True,
    )
    server = fastmcp.FastMCP("memory-contract")
    mcp_server._register_memory_tools(server)

    async def exchange():
        async with fastmcp.Client(server) as client:
            tools = await client.list_tools()
            tool = next(item for item in tools if item.name == "dump_memory")
            result = await client.call_tool("dump_memory", {
                "regions": [{"address": 0x20000000, "size": 2}],
                "sample_count": 1,
                "timeout": 0.1,
            })
            return tool, result

    try:
        tool, result = asyncio.run(exchange())
    finally:
        observe_bridge.shutdown_process_observation(timeout=1.0)

    # FastMCP versions may add docstring descriptions; validate every wire
    # constraint while allowing this non-semantic documentation metadata.
    schema = copy.deepcopy(tool.inputSchema)
    for property_schema in schema.get("properties", {}).values():
        property_schema.pop("description", None)
    assert schema == {
        "additionalProperties": False,
        "properties": {
            "regions": {
                "items": {"additionalProperties": True, "type": "object"},
                "type": "array",
            },
            "sample_count": {"default": 1, "type": "integer"},
            "timeout": {"default": 10.0, "type": "number"},
            "speed_profile": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        },
        "required": ["regions"],
        "type": "object",
    }
    assert {
        "content": [
            item.model_dump(mode="json", by_alias=True, exclude_none=True)
            for item in result.content
        ],
        "structuredContent": result.structured_content,
        "isError": result.is_error,
    } == {
        "content": [{
            "type": "text",
            "text": (
                '{"sample_count":1,"region_count":1,"total_bytes":2,'
                '"samples":[{"sample_index":0,"regions":[{'
                '"address":"0x20000000","size":2,"data_hex":"4142"}]}]}'
            ),
        }],
        "structuredContent": {
            "sample_count": 1,
            "region_count": 1,
            "total_bytes": 2,
            "samples": [{
                "sample_index": 0,
                "regions": [{
                    "address": "0x20000000",
                    "size": 2,
                    "data_hex": "4142",
                }],
            }],
        },
        "isError": False,
    }
