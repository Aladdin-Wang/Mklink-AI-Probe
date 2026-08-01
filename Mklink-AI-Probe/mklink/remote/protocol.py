"""Versioned JSON-RPC contract for the direct Mklink site agent.

This module deliberately contains no transport code.  Keeping validation and
envelope construction here makes the WebSocket service small, predictable,
and usable by future supported clients without copying stringly-typed errors.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


PROTOCOL_VERSION = "1.0"
JSONRPC_VERSION = "2.0"


@dataclass(frozen=True)
class ProtocolLimits:
    """Limits enforced by the direct agent transport."""

    max_message_bytes: int = 1_048_576
    max_queue: int = 32
    request_timeout_seconds: float = 15.0
    handshake_timeout_seconds: float = 5.0
    close_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.max_message_bytes <= 0 or self.max_queue <= 0:
            raise ValueError("protocol size and queue limits must be positive")
        if min(
            self.request_timeout_seconds,
            self.handshake_timeout_seconds,
            self.close_timeout_seconds,
        ) <= 0:
            raise ValueError("protocol time limits must be positive")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Capability:
    """A stable, discoverable feature description."""

    available: bool
    version: str = "1"
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {"available": self.available, "version": self.version}
        if self.detail:
            result["detail"] = self.detail
        return result


@dataclass(frozen=True)
class Handshake:
    """Compatibility information returned before agent operations."""

    protocol_version: str
    mklink_version: str
    capabilities: Mapping[str, Capability]
    limits: ProtocolLimits

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "mklink_version": self.mklink_version,
            "capabilities": {
                name: capability.as_dict()
                for name, capability in self.capabilities.items()
            },
            "limits": self.limits.as_dict(),
        }


class ProtocolError(Exception):
    """A public JSON-RPC error with a stable, non-secret message."""

    code = -32000
    public_message = "Agent protocol error"

    def __init__(self, message: str | None = None, *, data: Mapping[str, Any] | None = None):
        self.message = message or self.public_message
        self.data = dict(data or {})
        super().__init__(self.message)

    def as_error(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data:
            error["data"] = self.data
        return error


class AuthenticationError(ProtocolError):
    code = -32001
    public_message = "Authentication required"


class CompatibilityError(ProtocolError):
    code = -32002
    public_message = "Incompatible protocol version"


class RequestValidationError(ProtocolError):
    code = -32600
    public_message = "Invalid request"


class MethodNotFoundError(ProtocolError):
    code = -32601
    public_message = "Method not found"


class AgentOperationError(ProtocolError):
    code = -32003
    public_message = "Agent operation failed"


@dataclass(frozen=True)
class RequestEnvelope:
    method: str
    params: Mapping[str, Any]
    request_id: str | int | None

    @classmethod
    def parse(cls, value: Any) -> "RequestEnvelope":
        if not isinstance(value, Mapping) or value.get("jsonrpc") != JSONRPC_VERSION:
            raise RequestValidationError()
        method = value.get("method")
        params = value.get("params", {})
        request_id = value.get("id")
        if (
            not isinstance(method, str)
            or not method
            or not isinstance(params, Mapping)
            or isinstance(request_id, bool)
            or not isinstance(request_id, (str, int, type(None)))
        ):
            raise RequestValidationError()
        return cls(method=method, params=params, request_id=request_id)


def result_envelope(result: Any, request_id: str | int | None) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "result": result, "id": request_id}


def error_envelope(error: ProtocolError, request_id: str | int | None) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "error": error.as_error(), "id": request_id}


def compatible_version(version: Any) -> bool:
    """Accept protocol versions in the current major compatibility family."""

    if not isinstance(version, str) or not version:
        return False
    return version.split(".", 1)[0] == PROTOCOL_VERSION.split(".", 1)[0]


def redact(value: Any) -> Any:
    """Return diagnostics suitable for responses/logs without leaking secrets."""

    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if str(key).lower() in {"token", "authorization", "secret", "password"}
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


__all__ = [
    "AgentOperationError", "AuthenticationError", "Capability", "CompatibilityError",
    "Handshake", "JSONRPC_VERSION", "MethodNotFoundError", "PROTOCOL_VERSION",
    "ProtocolError", "ProtocolLimits", "RequestEnvelope", "RequestValidationError",
    "compatible_version", "error_envelope", "redact", "result_envelope",
]
