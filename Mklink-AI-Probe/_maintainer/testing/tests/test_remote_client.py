"""Black-box tests for the negotiated public remote client API."""

from __future__ import annotations

import json
import threading
import time

import pytest

from mklink.remote.agent import AgentConfig, SiteAgent
from mklink.remote.client import (
    DEFAULT_FLASH_TIMEOUT_SECONDS,
    RemoteClient,
    RemoteConnectionError,
    RemoteProtocolError,
    connect_remote,
)
from mklink.remote.protocol import PROTOCOL_VERSION


class _AgentServer:
    def __enter__(self):
        self.agent = SiteAgent(AgentConfig(port=0), device_factory=lambda: None)
        self.error = []

        def serve():
            try:
                import asyncio
                asyncio.run(self.agent.serve())
            except BaseException as exc:  # surfaced in the calling test thread
                self.error.append(exc)

        self.thread = threading.Thread(target=serve)
        self.thread.start()
        deadline = time.monotonic() + 2
        while not self.agent.ready and time.monotonic() < deadline:
            time.sleep(0.01)
        assert self.agent.ready, "agent did not become ready"
        return self.agent

    def __exit__(self, *_exc):
        self.agent.request_stop()
        self.thread.join(timeout=2)
        assert not self.thread.is_alive()
        if self.error:
            raise self.error[0]


class _FakeRPCWebSocket:
    """Deterministic fake transport for deadline and delivery-state tests."""

    def __init__(self, actions=None):
        self.actions = dict(actions or {})
        self.attempted_requests = []
        self.recv_timeouts = []
        self.closed = False
        self._pending_request = None

    def send(self, payload):
        request = json.loads(payload)
        self._pending_request = request
        self.attempted_requests.append(request)
        action = self.actions.get(request["method"], {})
        error = action.get("send_error")
        if error is not None:
            raise error

    def recv(self, timeout):
        request = self._pending_request
        assert request is not None, "recv called without a pending request"
        method = request["method"]
        self.recv_timeouts.append((method, timeout))

        if method == "system.handshake":
            result = {
                "protocol_version": PROTOCOL_VERSION,
                "mklink_version": "test",
                "capabilities": {},
                "limits": {
                    "max_message_bytes": 1024 * 1024,
                    "max_queue": 64,
                    "request_timeout_seconds": 10.0,
                    "handshake_timeout_seconds": 5.0,
                    "close_timeout_seconds": 2.0,
                },
            }
            return json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result})

        action = self.actions.get(method, {})
        delay = float(action.get("delay", 0.0))
        if delay > timeout:
            time.sleep(timeout)
            raise TimeoutError("fake receive deadline elapsed")
        if delay:
            time.sleep(delay)
        error = action.get("recv_error")
        if error is not None:
            raise error
        if "error" in action:
            response = {"jsonrpc": "2.0", "id": request["id"], "error": action["error"]}
        else:
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": action.get("result"),
            }
        return json.dumps(response)

    def close(self):
        self.closed = True


def _connect_fake(
    monkeypatch,
    actions=None,
    *,
    timeout=0.01,
    flash_timeout=DEFAULT_FLASH_TIMEOUT_SECONDS,
):
    websocket = _FakeRPCWebSocket(actions)
    monkeypatch.setattr(
        "websockets.sync.client.connect",
        lambda *_args, **_kwargs: websocket,
    )
    client = RemoteClient(
        "ws://fake.invalid",
        token=None,
        timeout=timeout,
        flash_timeout=flash_timeout,
    )
    return client, websocket


def test_public_client_negotiates_before_using_public_rpc_and_closes_cleanly():
    with _AgentServer() as agent:
        with connect_remote(f"ws://127.0.0.1:{agent.port}", token=None) as client:
            assert isinstance(client, RemoteClient)
            assert client.connected is True
            assert client.url == f"ws://127.0.0.1:{agent.port}"
            assert client.port == f"remote:{client.url}"
            handshake = client.handshake()
            assert handshake.protocol_version
            assert client.supports("agent.lifecycle") is True
            assert client.call("agent.health") == {
                "ready": True,
                "listener": True,
                "probe_connected": False,
            }
            assert client.call_raw("agent.status")["device_state"] == "disconnected"
            with pytest.raises(RemoteProtocolError) as unknown:
                client.call("not.a.public.method")
            assert unknown.value.code == -32601
        assert client.connected is False

@pytest.mark.parametrize(
    "url",
    ["", "https://site.example", "ws://user:secret@site.example", "ws://site.example/#x"],
)
def test_public_client_rejects_unsafe_or_non_websocket_endpoints(url):
    with pytest.raises(ValueError):
        connect_remote(url, token=None)


def test_public_client_reports_connection_failure_without_a_caller_socket_handle():
    with pytest.raises(RemoteConnectionError):
        connect_remote("ws://127.0.0.1:1", token=None, timeout=0.05)


def test_flash_program_waits_beyond_generic_timeout_and_returns_terminal_wrapper(
    monkeypatch,
):
    client, websocket = _connect_fake(
        monkeypatch,
        {"flash.program": {"delay": 0.02, "result": {"verified": True}}},
        timeout=0.005,
    )

    started = time.monotonic()
    result = client.flash("fixture.bin")
    elapsed = time.monotonic() - started

    assert elapsed >= 0.015, "fake flash did not wait beyond the generic RPC deadline"
    assert result == {"state": "succeeded", "result": {"verified": True}}
    assert websocket.recv_timeouts[-1] == (
        "flash.program",
        DEFAULT_FLASH_TIMEOUT_SECONDS,
    )
    client.close()


@pytest.mark.parametrize(
    "flash_timeout",
    [0, -1, float("inf"), float("nan"), "not-a-number"],
)
def test_flash_timeout_must_be_a_positive_finite_number(flash_timeout):
    with pytest.raises(ValueError, match="flash_timeout must be positive"):
        RemoteClient(
            "ws://fake.invalid",
            token=None,
            flash_timeout=flash_timeout,
        )


@pytest.mark.parametrize(
    "action,flash_timeout",
    [
        pytest.param({"delay": 0.02}, 0.005, id="receive-timeout"),
        pytest.param(
            {"recv_error": ConnectionError("fake transport loss")},
            0.05,
            id="receive-loss",
        ),
    ],
)
def test_flash_program_receive_failure_marks_completion_unknown(
    monkeypatch,
    action,
    flash_timeout,
):
    client, websocket = _connect_fake(
        monkeypatch,
        {"flash.program": action},
        flash_timeout=flash_timeout,
    )

    result = client.call("flash.program", firmware="fixture.bin")

    assert result == {"state": "completion-unknown", "result": None}
    assert websocket.closed is True
    assert client.connected is False


def test_flash_program_send_failure_is_cancelled_before_start(monkeypatch):
    client, websocket = _connect_fake(
        monkeypatch,
        {
            "flash.program": {
                "send_error": ConnectionError("fake pre-dispatch transport loss")
            }
        },
    )

    result = client.call("flash.program", firmware="fixture.bin")

    assert result == {"state": "cancelled-before-start", "result": None}
    assert websocket.closed is True
    assert client.connected is False
    assert websocket.recv_timeouts[-1][0] == "system.handshake"


def test_flash_program_structured_rpc_error_returns_failed_terminal_wrapper(monkeypatch):
    terminal_error = {
        "code": -32042,
        "message": "program rejected",
        "data": {"phase": "preflight"},
    }
    client, _websocket = _connect_fake(
        monkeypatch,
        {"flash.program": {"error": terminal_error}},
    )

    result = client.call("flash.program", firmware="fixture.bin")

    assert result == {"state": "failed", "result": terminal_error}
    assert client.connected is True
    client.close()


def test_non_flash_rpc_keeps_generic_receive_timeout(monkeypatch):
    generic_timeout = 0.005
    client, websocket = _connect_fake(
        monkeypatch,
        {"agent.health": {"delay": 0.02, "result": {"ready": True}}},
        timeout=generic_timeout,
        flash_timeout=0.2,
    )

    with pytest.raises(RemoteConnectionError):
        client.call("agent.health")

    assert websocket.recv_timeouts[-1] == ("agent.health", generic_timeout)
    assert websocket.closed is True
    assert client.connected is False
