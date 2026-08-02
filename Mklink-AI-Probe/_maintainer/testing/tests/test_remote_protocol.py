"""Black-box contract tests for the direct Site Agent protocol.

Traces: TEST-001, SPEC-001..003, API-001, REQ-001/003, INV-01/02/06.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from contextlib import asynccontextmanager

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from mklink.remote.agent import AgentConfig, SiteAgent, validate_bind
from mklink.remote.protocol import PROTOCOL_VERSION, ProtocolLimits


def _run(coro):
    return asyncio.run(coro)


@asynccontextmanager
async def _agent(*, token=None, limits=None):
    agent = SiteAgent(
        AgentConfig(port=0, token=token, limits=limits or ProtocolLimits()),
        device_factory=lambda: None,
    )
    task = asyncio.create_task(agent.serve())
    try:
        for _ in range(100):
            if agent.ready:
                break
            await asyncio.sleep(0.01)
        assert agent.ready, "agent did not become ready"
        yield agent
    finally:
        agent.request_stop()
        await asyncio.wait_for(task, timeout=2)


def _rpc(method, params=None, request_id=1):
    return json.dumps({
        "jsonrpc": "2.0", "id": request_id, "method": method,
        "params": params or {},
    }, separators=(",", ":"))


async def _recv_json(websocket):
    return json.loads(await websocket.recv())


def _masked_frame(payload, *, opcode=1, final=True):
    payload = payload.encode() if isinstance(payload, str) else payload
    assert len(payload) < 126
    mask = b"mask"
    first = (0x80 if final else 0) | opcode
    encoded = bytes(item ^ mask[index % 4] for index, item in enumerate(payload))
    return bytes((first, 0x80 | len(payload))) + mask + encoded


async def _read_frame(reader):
    first, second = await reader.readexactly(2)
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")
    payload = await reader.readexactly(length)
    return first & 0x0F, payload


async def _raw_upgrade(port, *, valid=True):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    key = base64.b64encode(b"0123456789abcdef").decode() if valid else "not base64"
    writer.write(
        (
            "GET / HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    await writer.drain()
    header = await reader.readuntil(b"\r\n\r\n")
    return reader, writer, header, key


def test_websocket_upgrade_accept_and_invalid_upgrade_are_validated():
    async def scenario():
        async with _agent() as agent:
            reader, writer, header, key = await _raw_upgrade(agent.port)
            try:
                assert header.startswith(b"HTTP/1.1 101")
                expected = base64.b64encode(
                    hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
                )
                assert f"Sec-WebSocket-Accept: {expected.decode()}".encode() in header
            finally:
                writer.close()
                await writer.wait_closed()

            _reader, bad_writer, bad_header, _key = await _raw_upgrade(agent.port, valid=False)
            try:
                assert not bad_header.startswith(b"HTTP/1.1 101")
            finally:
                bad_writer.close()
                await bad_writer.wait_closed()

    _run(scenario())


def test_websocket_accepts_masked_fragmented_and_coalesced_messages():
    async def scenario():
        async with _agent() as agent:
            reader, writer, _header, _key = await _raw_upgrade(agent.port)
            try:
                handshake = _rpc("system.handshake", {"protocol_version": PROTOCOL_VERSION})
                split = len(handshake) // 2
                first = _masked_frame(handshake[:split], final=False)
                second = _masked_frame(handshake[split:], opcode=0)
                # Partial TCP writes and multiple RFC 6455 frames are distinct
                # from JSON-RPC messages and must not alter message parsing.
                writer.write(first[:3])
                await writer.drain()
                writer.write(first[3:] + second)
                await writer.drain()
                opcode, payload = await _read_frame(reader)
                assert opcode == 1
                assert json.loads(payload)["result"]["protocol_version"] == PROTOCOL_VERSION

                writer.write(
                    _masked_frame(_rpc("agent.health", request_id=2))
                    + _masked_frame(_rpc("agent.status", request_id=3))
                )
                await writer.drain()
                replies = [json.loads((await _read_frame(reader))[1]) for _ in range(2)]
                assert {reply["id"] for reply in replies} == {2, 3}
                assert all("result" in reply for reply in replies)
            finally:
                writer.close()
                await writer.wait_closed()

    _run(scenario())


def test_websocket_rejects_an_unmasked_client_frame_and_enforces_message_limit():
    async def scenario():
        async with _agent() as agent:
            reader, writer, _header, _key = await _raw_upgrade(agent.port)
            try:
                # RFC 6455 requires client-to-server masking.
                payload = _rpc("system.handshake", {"protocol_version": PROTOCOL_VERSION}).encode()
                writer.write(bytes((0x81, len(payload))) + payload)
                await writer.drain()
                opcode, close_payload = await _read_frame(reader)
                assert opcode == 8
                assert int.from_bytes(close_payload[:2], "big") == 1002
            finally:
                writer.close()
                await writer.wait_closed()

        async with _agent(limits=ProtocolLimits(max_message_bytes=128)) as agent:
            with pytest.raises(ConnectionClosed) as closed:
                async with websockets.connect(f"ws://127.0.0.1:{agent.port}") as websocket:
                    await websocket.send("x" * 129)
                    await websocket.recv()
            assert closed.value.rcvd.code == 1009

    _run(scenario())


def test_websocket_ping_pong_and_close_lifecycle():
    async def scenario():
        async with _agent() as agent:
            async with websockets.connect(f"ws://127.0.0.1:{agent.port}") as websocket:
                pong_waiter = await websocket.ping(b"probe")
                await asyncio.wait_for(pong_waiter, timeout=1)
                await websocket.close(code=1000, reason="test complete")
                # Both legacy and current clients expose these only after the
                # closing handshake, while the current API removed ``closed``.
                assert websocket.close_code == 1000
                assert websocket.close_reason == "test complete"

    _run(scenario())


def test_authentication_precedes_privilege_and_errors_are_stable_and_redacted():
    async def scenario():
        async with _agent(token="server-only-token") as agent:
            async with websockets.connect(f"ws://127.0.0.1:{agent.port}") as websocket:
                await websocket.send(_rpc("agent.status", request_id=7))
                error = await _recv_json(websocket)
                assert error == {
                    "jsonrpc": "2.0",
                    "error": {"code": -32001, "message": "Authentication required"},
                    "id": 7,
                }
                with pytest.raises(ConnectionClosed) as closed:
                    await websocket.recv()
                assert closed.value.rcvd.code == 1008

            async with websockets.connect(f"ws://127.0.0.1:{agent.port}") as websocket:
                await websocket.send(_rpc(
                    "system.handshake",
                    {"protocol_version": PROTOCOL_VERSION, "token": "client-secret"},
                ))
                response = await _recv_json(websocket)
                serialized = json.dumps(response)
                assert response["error"] == {"code": -32001, "message": "Authentication required"}
                assert "server-only-token" not in serialized
                assert "client-secret" not in serialized

    _run(scenario())


def test_incompatible_version_returns_upgrade_guidance_before_any_privileged_operation():
    async def scenario():
        async with _agent(token="server-only-token") as agent:
            async with websockets.connect(f"ws://127.0.0.1:{agent.port}") as websocket:
                await websocket.send(_rpc("system.handshake", {
                    "protocol_version": "99.0", "token": "server-only-token",
                }))
                response = await _recv_json(websocket)
                assert response["error"] == {
                    "code": -32002,
                    "message": "Incompatible protocol version",
                    "data": {
                        "supported_protocol_version": PROTOCOL_VERSION,
                        "action": "upgrade_client",
                    },
                }
                await websocket.send(_rpc("agent.status", request_id=2))
                denied = await _recv_json(websocket)
                assert denied["error"]["code"] == -32001

    _run(scenario())


def test_bind_defaults_to_loopback_and_requires_explicit_token_authenticated_lan_opt_in():
    assert AgentConfig().host == "127.0.0.1"
    for unsafe_host in ("0.0.0.0", "::", "192.0.2.10", "vpn.example.test"):
        with pytest.raises(ValueError):
            validate_bind(unsafe_host, None)
    with pytest.raises(ValueError):
        validate_bind("192.0.2.10", "token", allow_lan=False)

    validate_bind("127.0.0.1", None)
    validate_bind("localhost", None)
    validate_bind("192.0.2.10", "token", allow_lan=True)
    validate_bind("vpn.example.test", "token", allow_lan=True)
