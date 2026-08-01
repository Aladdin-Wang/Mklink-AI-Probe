"""Negotiated public client for the direct Mklink Site Agent."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Any, Mapping, TypedDict
from urllib.parse import urlsplit

from mklink.remote.protocol import (
    Capability,
    Handshake,
    JSONRPC_VERSION,
    PROTOCOL_VERSION,
    ProtocolLimits,
    compatible_version,
)
from mklink.remote.transfer import RemoteFile


DEFAULT_FLASH_TIMEOUT_SECONDS = 300.0
"""Deadline for the complete remote program, verify, and reset operation."""


class FlashResult(TypedDict):
    state: str
    result: Mapping[str, Any] | None


class RemoteClientError(Exception):
    """Base error for public remote-client operations."""


class RemoteConnectionError(RemoteClientError):
    """The direct WebSocket connection isn't usable."""


class RemoteProtocolError(RemoteClientError):
    """A structured error returned by the Site Agent."""

    def __init__(
        self,
        code: int,
        message: str,
        *,
        data: Mapping[str, Any] | None = None,
    ):
        self.code = int(code)
        self.message = str(message)
        self.data = dict(data or {})
        super().__init__(f"Remote RPC error [{self.code}]: {self.message}")


_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def validate_endpoint(url: str) -> str:
    """Validate and canonicalize a credential-free direct WebSocket endpoint."""

    if not isinstance(url, str) or not url:
        raise ValueError("a WebSocket URL is required")
    if url != url.strip() or any(ord(character) < 0x20 for character in url):
        raise ValueError("remote URL must not contain whitespace or control characters")
    if "?" in url or "#" in url:
        raise ValueError("remote URL query and fragment components are not supported")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError("remote URL is malformed") from exc
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        raise ValueError("remote URL must use ws:// or wss:// with a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials must not be embedded in the remote URL")
    if parsed.path not in {"", "/"}:
        raise ValueError("remote URL must contain only a host and optional port")

    hostname = parsed.hostname
    if "%" in hostname:
        raise ValueError("remote URL host is malformed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("remote URL port is invalid") from exc
    if parsed.netloc.endswith(":") or port == 0:
        raise ValueError("remote URL port is invalid")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            canonical_host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("remote URL host is malformed") from exc
        labels = canonical_host.rstrip(".").split(".")
        if (
            not canonical_host
            or len(canonical_host) > 253
            or any(not _HOST_LABEL_RE.fullmatch(label) for label in labels)
            or (
                all(character.isdigit() or character == "." for character in canonical_host)
                and not _valid_ip_address(canonical_host)
            )
        ):
            raise ValueError("remote URL host is malformed")
    else:
        canonical_host = f"[{address.compressed}]" if address.version == 6 else address.compressed

    canonical_port = f":{port}" if port is not None else ""
    return f"{parsed.scheme}://{canonical_host}{canonical_port}"


def _valid_ip_address(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def _handshake_from_mapping(value: Any) -> Handshake:
    if not isinstance(value, Mapping):
        raise RemoteConnectionError("Invalid handshake response")
    capabilities_value = value.get("capabilities")
    limits_value = value.get("limits")
    if not isinstance(capabilities_value, Mapping) or not isinstance(limits_value, Mapping):
        raise RemoteConnectionError("Incomplete handshake response")
    try:
        capabilities = {
            str(name): Capability(
                available=bool(item["available"]),
                version=str(item.get("version", "1")),
                detail=str(item["detail"]) if item.get("detail") is not None else None,
            )
            for name, item in capabilities_value.items()
            if isinstance(item, Mapping)
        }
        limits = ProtocolLimits(
            max_message_bytes=int(limits_value["max_message_bytes"]),
            max_queue=int(limits_value["max_queue"]),
            request_timeout_seconds=float(limits_value["request_timeout_seconds"]),
            handshake_timeout_seconds=float(limits_value["handshake_timeout_seconds"]),
            close_timeout_seconds=float(limits_value["close_timeout_seconds"]),
        )
        return Handshake(
            protocol_version=str(value["protocol_version"]),
            mklink_version=str(value["mklink_version"]),
            capabilities=capabilities,
            limits=limits,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteConnectionError("Invalid handshake response") from exc


class RemoteClient:
    """Thread-safe public RPC client with mandatory version negotiation."""

    def __init__(
        self,
        url: str,
        *,
        token: str | None,
        timeout: float = 10.0,
        flash_timeout: float = DEFAULT_FLASH_TIMEOUT_SECONDS,
    ):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        try:
            normalized_flash_timeout = float(flash_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("flash_timeout must be positive") from exc
        if not math.isfinite(normalized_flash_timeout) or normalized_flash_timeout <= 0:
            raise ValueError("flash_timeout must be positive")
        self._url = validate_endpoint(url)
        self._token = token
        self._timeout = float(timeout)
        self._flash_timeout = normalized_flash_timeout
        self._websocket: Any | None = None
        self._negotiated: Handshake | None = None
        self._request_id = 0
        self._lock = threading.RLock()
        self.reconnect()

    def __enter__(self) -> "RemoteClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        with self._lock:
            websocket = self._websocket
            if websocket is None:
                return False
            closed = getattr(websocket, "closed", False)
            return not bool(closed)

    @property
    def url(self) -> str:
        return self._url

    @property
    def port(self) -> str:
        return f"remote:{self._url}"

    def handshake(self) -> Handshake:
        """Return the immutable handshake negotiated during connection."""

        with self._lock:
            if self._negotiated is None:
                raise RemoteConnectionError("Remote client isn't connected")
            return self._negotiated

    def supports(self, capability: str) -> bool:
        descriptor = self.handshake().capabilities.get(capability)
        return bool(descriptor and descriptor.available)

    def reconnect(self) -> Handshake:
        """Replace only this client's connection and renegotiate the protocol."""

        with self._lock:
            self._close_locked()
            try:
                from websockets.sync.client import connect

                websocket = connect(
                    self._url,
                    open_timeout=self._timeout,
                    close_timeout=self._timeout,
                    max_size=ProtocolLimits().max_message_bytes,
                )
                self._websocket = websocket
                self._request_id = 0
                result = self._exchange_locked(
                    "system.handshake",
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        **({"token": self._token} if self._token is not None else {}),
                    },
                )
                negotiated = _handshake_from_mapping(result)
                if not compatible_version(negotiated.protocol_version):
                    raise RemoteConnectionError("Incompatible remote protocol version")
                self._negotiated = negotiated
                return negotiated
            except RemoteClientError:
                self._close_locked()
                raise
            except Exception as exc:
                self._close_locked()
                raise RemoteConnectionError("Unable to connect to the remote agent") from exc

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        websocket, self._websocket = self._websocket, None
        self._negotiated = None
        if websocket is not None:
            try:
                websocket.close()
            except Exception:
                pass

    def call(self, method: str, **params: Any) -> Any:
        """Invoke a public RPC method on the negotiated connection."""

        if not isinstance(method, str) or not method:
            raise ValueError("RPC method must be a non-empty string")
        with self._lock:
            if self._negotiated is None or self._websocket is None:
                raise RemoteConnectionError("Remote client isn't connected")
            return self._exchange_locked(method, params)

    def call_raw(self, method: str, **params: Any) -> Any:
        """Compatibility alias that remains fully public."""

        return self.call(method, **params)

    def _exchange_locked(self, method: str, params: Mapping[str, Any]) -> Any:
        websocket = self._websocket
        if websocket is None:
            raise RemoteConnectionError("Remote client isn't connected")
        self._request_id += 1
        request_id = self._request_id
        payload = json.dumps(
            {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "method": method,
                "params": dict(params),
            },
            separators=(",", ":"),
        )
        try:
            websocket.send(payload)
        except Exception as exc:
            self._close_locked()
            if method == "flash.program":
                return FlashResult(state="cancelled-before-start", result=None)
            raise RemoteConnectionError("Remote connection closed during RPC") from exc
        try:
            raw = websocket.recv(
                timeout=self._flash_timeout if method == "flash.program" else self._timeout
            )
        except Exception as exc:
            self._close_locked()
            if method == "flash.program":
                return FlashResult(state="completion-unknown", result=None)
            raise RemoteConnectionError("Remote connection closed during RPC") from exc
        if not isinstance(raw, str):
            raise RemoteConnectionError("Remote agent returned a non-text RPC response")
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RemoteConnectionError("Remote agent returned invalid JSON") from exc
        if not isinstance(response, Mapping) or response.get("id") != request_id:
            raise RemoteConnectionError("Remote agent returned a mismatched response")
        error = response.get("error")
        if isinstance(error, Mapping):
            if method == "flash.program":
                return FlashResult(state="failed", result=dict(error))
            raise RemoteProtocolError(
                int(error.get("code", -32000)),
                str(error.get("message", "Remote operation failed")),
                data=error.get("data") if isinstance(error.get("data"), Mapping) else None,
            )
        if "result" not in response:
            raise RemoteConnectionError("Remote agent returned an incomplete response")
        if method == "flash.program":
            result = response["result"]
            if result is not None and not isinstance(result, Mapping):
                raise RemoteConnectionError("Remote agent returned an invalid flash result")
            return FlashResult(
                state="succeeded",
                result=dict(result) if isinstance(result, Mapping) else None,
            )
        return response["result"]

    def upload(self, path: Path, *, chunk_size: int | None = None) -> RemoteFile:
        """Upload one local file through opaque transfer-session RPCs."""

        local_path = Path(path)
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        size = local_path.stat().st_size
        digest = hashlib.sha256()
        with local_path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        sha256 = digest.hexdigest()

        opened = self.call(
            "transfer.open",
            filename=local_path.name,
            size=size,
        )
        if not isinstance(opened, Mapping) or not isinstance(opened.get("session_id"), str):
            raise RemoteConnectionError("Remote agent returned an invalid upload session")
        session_id = opened["session_id"]
        server_limit = int(opened.get("chunk_limit", 64 * 1024))
        selected_chunk = server_limit if chunk_size is None else int(chunk_size)
        if selected_chunk <= 0 or selected_chunk > server_limit:
            raise ValueError("chunk_size must be positive and within the server limit")

        offset = 0
        sequence = 0
        try:
            with local_path.open("rb") as source:
                while True:
                    chunk = source.read(selected_chunk)
                    if not chunk:
                        break
                    self.call(
                        "transfer.chunk",
                        session_id=session_id,
                        offset=offset,
                        sequence=sequence,
                        data=base64.b64encode(chunk).decode("ascii"),
                    )
                    offset += len(chunk)
                    sequence += 1
            finalized = self.call(
                "transfer.finalize",
                session_id=session_id,
                size=size,
                sha256=sha256,
            )
        except Exception:
            try:
                self.call("transfer.abort", session_id=session_id)
            except Exception:
                pass
            raise
        return RemoteFile.from_mapping(finalized)

    # Compatibility device-shaped helpers. Capability mapping remains Group 3.
    @property
    def idcode(self) -> int:
        return int(self.call("idcode"))

    @property
    def mcu_name(self) -> str:
        return str(self.call("mcu_name"))

    def flash(self, firmware: str, **params: Any) -> FlashResult:
        return self.call("flash.program", firmware=firmware, **params)

    def erase_chip(self) -> bool:
        return bool(self.call("erase_chip"))

    def reset(self) -> None:
        self.call("reset")

    def rtt_start(self, addr: str | None = None, **params: Any) -> dict[str, Any]:
        return self.call("rtt_start", addr=addr, **params)

    def rtt_read(self, duration: float = 10.0) -> str:
        return str(self.call("rtt_read", duration=duration))

    def rtt_write(self, data: bytes | str) -> bool:
        text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
        return bool(self.call("rtt_write", data=text))

    def rtt_stop(self) -> str:
        return str(self.call("rtt_stop"))

    def wait_for_rtt(self, pattern: str | None = None, *, timeout: float = 10.0) -> str:
        import re

        deadline = time.monotonic() + timeout
        collected = ""
        while time.monotonic() < deadline:
            chunk = self.rtt_read(min(2.0, max(0.0, deadline - time.monotonic())))
            collected += chunk
            if pattern and (pattern in collected or re.search(pattern, collected)):
                break
        return collected

    def read_memory(self, address: int, size: int) -> bytes:
        result = self.call("read_memory", address=address, size=size)
        if isinstance(result, Mapping) and isinstance(result.get("__bytes__"), str):
            return base64.b64decode(result["__bytes__"], validate=True)
        raise RemoteConnectionError("Remote memory response isn't binary data")

    def write_memory(self, address: int, data: bytes) -> None:
        self.call(
            "write_memory",
            address=address,
            data_b64=base64.b64encode(data).decode("ascii"),
        )

    def read_variable(self, name: str) -> Any:
        return self.call("read_variable", name=name)

    def write_variable(self, name: str, value: int) -> None:
        self.call("write_variable", name=name, value=value)

    def read_register(self, name: str) -> int:
        return int(self.call("read_register", name=name))

    def halt(self) -> dict[str, Any]:
        return self.call("halt")

    def resume(self) -> dict[str, Any]:
        return self.call("resume")

    def step(self) -> dict[str, Any]:
        return self.call("step")

    def set_breakpoint(self, address: int, slot: int | None = None) -> int:
        return int(self.call("set_breakpoint", address=address, slot=slot))

    def clear_breakpoint(self, slot: int) -> None:
        self.call("clear_breakpoint", slot=slot)

    def read_core_registers(self) -> dict[str, Any]:
        return self.call("read_core_registers")

    def check_hardfault(self) -> dict[str, Any] | None:
        return self.call("check_hardfault")

    def decode_hardfault(
        self,
        fault_regs: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self.call("decode_hardfault", fault_regs=fault_regs)


def connect_remote(
    url: str,
    *,
    token: str | None,
    timeout: float = 10.0,
    flash_timeout: float = DEFAULT_FLASH_TIMEOUT_SECONDS,
) -> RemoteClient:
    """Connect directly to a Site Agent and negotiate protocol compatibility."""

    return RemoteClient(
        url,
        token=token,
        timeout=timeout,
        flash_timeout=flash_timeout,
    )


# Source-compatible names for callers that previously imported the legacy proxy.
RemoteDevice = RemoteClient
RemoteDeviceError = RemoteClientError


__all__ = [
    "DEFAULT_FLASH_TIMEOUT_SECONDS",
    "FlashResult",
    "RemoteClient",
    "RemoteClientError",
    "RemoteConnectionError",
    "RemoteDevice",
    "RemoteDeviceError",
    "RemoteProtocolError",
    "connect_remote",
    "validate_endpoint",
]
