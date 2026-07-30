"""In-process FRP/STCP transport for LAN deployments.

The transport loads ``mklink-stcp.dll`` into the current process.  It never
extracts, renames, starts, or depends on ``frpc.exe``.  The native bridge uses
the official FRP client packages pinned by ``native/stcp_bridge/go.mod``.
"""

from __future__ import annotations

import ctypes
import ipaddress
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


_LIBRARY_ENV = "MKLINK_STCP_LIBRARY"


class STCPError(RuntimeError):
    """Public, secret-safe STCP transport failure."""


def _validate_port(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ValueError(f"{name} must be in range 1..65535")


def _validate_loopback(name: str, value: str) -> str:
    if not isinstance(value, str) or value.strip() != value:
        raise ValueError(f"{name} must be a loopback IP address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError(f"{name} must be a loopback IP address")
    return value


def _validate_common(
    *,
    server_addr: str,
    server_port: int,
    auth_token: str,
    proxy_name: str,
    secret_key: str,
    user: str,
) -> None:
    if (
        not isinstance(server_addr, str)
        or server_addr.strip() != server_addr
        or not server_addr
        or any(character.isspace() for character in server_addr)
    ):
        raise ValueError("server_addr is required and must not contain whitespace")
    try:
        address = ipaddress.ip_address(server_addr)
    except ValueError:
        address = None
    if address is not None and (address.is_unspecified or address.is_multicast):
        raise ValueError("server_addr must identify a concrete LAN server")
    _validate_port("server_port", server_port)
    if not isinstance(auth_token, str) or not auth_token:
        raise ValueError("FRP authentication token is required")
    if not isinstance(secret_key, str) or not secret_key:
        raise ValueError("STCP secret is required")
    if (
        not isinstance(proxy_name, str)
        or proxy_name.strip() != proxy_name
        or not proxy_name
        or any(character in "\r\n\t" for character in proxy_name)
    ):
        raise ValueError("proxy_name is invalid")
    if not isinstance(user, str) or user.strip() != user:
        raise ValueError("user is invalid")


@dataclass(frozen=True)
class STCPProviderConfig:
    """Field-side STCP proxy forwarding only to a loopback Site Agent."""

    server_addr: str
    server_port: int
    auth_token: str = field(repr=False)
    proxy_name: str
    secret_key: str = field(repr=False)
    local_port: int
    user: str = ""
    local_addr: str = "127.0.0.1"

    def __post_init__(self) -> None:
        _validate_common(
            server_addr=self.server_addr,
            server_port=self.server_port,
            auth_token=self.auth_token,
            proxy_name=self.proxy_name,
            secret_key=self.secret_key,
            user=self.user,
        )
        _validate_loopback("local_addr", self.local_addr)
        _validate_port("local_port", self.local_port)

    def as_native_payload(self) -> dict[str, Any]:
        return {
            "mode": "provider",
            "server_addr": self.server_addr,
            "server_port": self.server_port,
            "auth_token": self.auth_token,
            "user": self.user,
            "proxy_name": self.proxy_name,
            "secret_key": self.secret_key,
            "local_addr": self.local_addr,
            "local_port": self.local_port,
        }


@dataclass(frozen=True)
class STCPVisitorConfig:
    """Engineer-side STCP visitor exposing only a loopback listener."""

    server_addr: str
    server_port: int
    auth_token: str = field(repr=False)
    proxy_name: str
    secret_key: str = field(repr=False)
    bind_port: int
    user: str = ""
    bind_addr: str = "127.0.0.1"

    def __post_init__(self) -> None:
        _validate_common(
            server_addr=self.server_addr,
            server_port=self.server_port,
            auth_token=self.auth_token,
            proxy_name=self.proxy_name,
            secret_key=self.secret_key,
            user=self.user,
        )
        _validate_loopback("bind_addr", self.bind_addr)
        _validate_port("bind_port", self.bind_port)

    def as_native_payload(self) -> dict[str, Any]:
        return {
            "mode": "visitor",
            "server_addr": self.server_addr,
            "server_port": self.server_port,
            "auth_token": self.auth_token,
            "user": self.user,
            "proxy_name": self.proxy_name,
            "secret_key": self.secret_key,
            "bind_addr": self.bind_addr,
            "bind_port": self.bind_port,
        }


def _candidate_libraries(explicit: str | Path | None) -> list[Path]:
    candidates: list[Path] = []
    configured = explicit or os.environ.get(_LIBRARY_ENV)
    if configured:
        candidates.append(Path(configured).expanduser())
    executable_root = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            executable_root / "mklink-stcp.dll",
            executable_root / "lib" / "mklink-stcp.dll",
            Path(__file__).resolve().parents[2]
            / "native"
            / "stcp_bridge"
            / "build"
            / "mklink-stcp.dll",
        ]
    )
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key not in seen:
            result.append(candidate)
            seen.add(key)
    return result


class _NativeBridge:
    def __init__(self, library: str | Path | None = None):
        path = next(
            (candidate for candidate in _candidate_libraries(library) if candidate.is_file()),
            None,
        )
        if path is None:
            raise STCPError("in-process STCP transport library is unavailable")
        try:
            native = ctypes.CDLL(str(path.resolve()))
            native.MklinkSTCPStart.argtypes = [ctypes.c_char_p]
            native.MklinkSTCPStart.restype = ctypes.c_uint64
            native.MklinkSTCPStop.argtypes = [ctypes.c_uint64]
            native.MklinkSTCPStop.restype = ctypes.c_int
            native.MklinkSTCPStatus.argtypes = [ctypes.c_uint64]
            native.MklinkSTCPStatus.restype = ctypes.c_void_p
            native.MklinkSTCPLastError.argtypes = []
            native.MklinkSTCPLastError.restype = ctypes.c_void_p
            native.MklinkSTCPFree.argtypes = [ctypes.c_void_p]
            native.MklinkSTCPFree.restype = None
        except (AttributeError, OSError) as exc:
            raise STCPError("in-process STCP transport library could not be loaded") from exc
        self._native = native

    def _take_string(self, pointer: int | None) -> str:
        if not pointer:
            return ""
        try:
            return ctypes.string_at(pointer).decode("utf-8", errors="replace")
        finally:
            self._native.MklinkSTCPFree(pointer)

    def start(self, payload: Mapping[str, Any]) -> int:
        serialized = json.dumps(
            dict(payload),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        handle = int(self._native.MklinkSTCPStart(serialized))
        if not handle:
            detail = self._take_string(self._native.MklinkSTCPLastError())
            raise STCPError(detail or "in-process STCP transport failed to start")
        return handle

    def stop(self, handle: int) -> bool:
        return bool(self._native.MklinkSTCPStop(handle))

    def status(self, handle: int) -> dict[str, Any]:
        pointer = self._native.MklinkSTCPStatus(handle)
        if not pointer:
            detail = self._take_string(self._native.MklinkSTCPLastError())
            raise STCPError(detail or "in-process STCP transport status failed")
        try:
            value = json.loads(self._take_string(pointer))
        except json.JSONDecodeError as exc:
            raise STCPError("in-process STCP transport returned invalid status") from exc
        if not isinstance(value, dict):
            raise STCPError("in-process STCP transport returned invalid status")
        return value


class STCPSession:
    """Owned provider or visitor session inside the current process."""

    def __init__(
        self,
        config: STCPProviderConfig | STCPVisitorConfig,
        *,
        library: str | Path | None = None,
        bridge: _NativeBridge | None = None,
    ):
        self.config = config
        self._bridge = bridge or _NativeBridge(library)
        self._handle: int | None = None

    @property
    def running(self) -> bool:
        return self._handle is not None

    def start(self) -> dict[str, Any]:
        if self._handle is not None:
            return self.status()
        self._handle = self._bridge.start(self.config.as_native_payload())
        try:
            return self.status()
        except Exception:
            self.close()
            raise

    def status(self) -> dict[str, Any]:
        if self._handle is None:
            return {"state": "stopped", "ready": False}
        return self._bridge.status(self._handle)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            self._bridge.stop(handle)

    def __enter__(self) -> "STCPSession":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = [
    "STCPError",
    "STCPProviderConfig",
    "STCPSession",
    "STCPVisitorConfig",
]
