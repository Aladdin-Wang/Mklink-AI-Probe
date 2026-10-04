"""Direct WebSocket Site Agent lifecycle.

The agent intentionally starts without opening a probe.  This keeps readiness,
diagnostics, and repair of a temporarily disconnected probe independent from
the existing GUI/``serve`` lifecycle.
"""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
import json
import logging
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from mklink.remote.protocol import (
    AgentOperationError,
    AuthenticationError,
    Capability,
    CompatibilityError,
    Handshake,
    MethodNotFoundError,
    PROTOCOL_VERSION,
    ProtocolError,
    ProtocolLimits,
    RequestEnvelope,
    compatible_version,
    error_envelope,
    result_envelope,
)
from mklink.remote.resource_manager import ResourceManager


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentDispatchContext:
    """Services for a dispatcher; client_id identifies a socket, not authorization.

    None is reserved for direct in-process dispatch without a socket lifetime.
    """

    device: Any | None
    resource_manager: ResourceManager
    client_id: str | None = None


class CapabilityProvider(Protocol):
    """Structural contract for deterministic handshake capability injection."""

    def __call__(self) -> Mapping[str, Capability]:
        ...


class RequestDispatcher(Protocol):
    """Structural contract for delegated non-lifecycle RPC operations."""

    def __call__(
        self,
        method: str,
        params: Mapping[str, Any],
        context: AgentDispatchContext,
    ) -> Any:
        ...


class _TargetLifecycleCoordinator:
    """Coordinate concurrent dispatches with exclusive target lifecycle work."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active_dispatches = 0
        self._lifecycle_waiters = 0
        self._lifecycle_active = False
        self._closing = False

    def enter_dispatch(self) -> None:
        with self._condition:
            while (
                not self._closing
                and (self._lifecycle_active or self._lifecycle_waiters)
            ):
                self._condition.wait()
            if self._closing:
                raise AgentOperationError("Agent is stopping")
            self._active_dispatches += 1

    def leave_dispatch(self) -> None:
        with self._condition:
            if self._active_dispatches <= 0:
                raise RuntimeError("target dispatch coordination is unbalanced")
            self._active_dispatches -= 1
            if self._active_dispatches == 0:
                self._condition.notify_all()

    def request_close(self) -> None:
        with self._condition:
            self._closing = True
            self._condition.notify_all()

    @property
    def closing(self) -> bool:
        with self._condition:
            return self._closing

    @contextmanager
    def lifecycle(self):
        with self._condition:
            self._lifecycle_waiters += 1
            try:
                while self._lifecycle_active or self._active_dispatches:
                    self._condition.wait()
                self._lifecycle_active = True
            finally:
                self._lifecycle_waiters -= 1
        try:
            yield
        finally:
            with self._condition:
                self._lifecycle_active = False
                self._condition.notify_all()


def validate_bind(host: str, token: str | None, *, allow_lan: bool = False) -> None:
    """Reject unsafe listener choices before any socket is opened.

    Loopback is always allowed.  Any other concrete interface requires an
    explicit opt-in and a non-empty token.  Wildcard and unspecified listeners
    are never valid because they make accidental broader exposure too easy.
    """

    if not isinstance(host, str) or not host.strip():
        raise ValueError("a non-empty bind host is required")
    host = host.strip()
    if host.lower() == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Interface DNS names are useful with managed VPN adapters.  They are
        # treated as non-loopback rather than guessed/resolved at import time.
        if not allow_lan or not token:
            raise ValueError("non-loopback binds require allow_lan=True and a token")
        return
    if address.is_loopback:
        return
    if address.is_unspecified or address.is_multicast:
        raise ValueError("wildcard, unspecified, and multicast binds are not allowed")
    if not allow_lan or not token:
        raise ValueError("non-loopback binds require allow_lan=True and a token")


@dataclass
class AgentConfig:
    host: str = "127.0.0.1"
    port: int = 8766
    token: str | None = None
    allow_lan: bool = False
    device_port: str | None = None
    axf: str | None = None
    project_root: str = "."
    transport: str = "direct"
    transport_status: Callable[[], Mapping[str, Any]] | None = field(
        default=None,
        repr=False,
    )
    limits: ProtocolLimits = field(default_factory=ProtocolLimits)
    ready_callback: Callable[[dict[str, Any]], None] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 0 <= self.port <= 65535:
            raise ValueError("port must be in range 0..65535")
        if self.transport not in {"direct", "lan-stcp"}:
            raise ValueError("transport must be direct or lan-stcp")
        validate_bind(self.host, self.token, allow_lan=self.allow_lan)


class SiteAgent:
    """State owner for one direct agent listener.

    It is intentionally public so a package wrapper can request a cooperative
    stop without owning the asyncio loop.  Device creation is serialized, but
    health and status never attempt a probe connection.  The device factory
    accepts port and axf keyword arguments; a failed call is never retried.
    Dispatchers accept method, params and context. client_closed runs once after
    a socket's in-flight dispatch settles, including cancellation and rejection.
    """

    def __init__(
        self,
        config: AgentConfig,
        device_factory: Callable[..., Any],
        *,
        capability_provider: CapabilityProvider | None = None,
        request_dispatcher: RequestDispatcher | None = None,
        client_closed: Callable[[str], Any] | None = None,
        device_getter: Callable[[], Any | None] | None = None,
        device_reconnector: Callable[[AgentConfig], Any | None] | None = None,
        resource_manager: ResourceManager | None = None,
    ):
        self.config = config
        self._device_factory = device_factory
        self._capability_provider = capability_provider
        self._request_dispatcher = request_dispatcher
        self._client_closed = client_closed
        self._device: Any | None = None
        self._device_getter = device_getter
        self._device_reconnector = device_reconnector
        self._owns_device = device_getter is None
        self._target_lifecycle = _TargetLifecycleCoordinator()
        self._resources = resource_manager or ResourceManager()
        self._owns_resources = resource_manager is None
        self._stop_requested = threading.Event()
        self._ready = threading.Event()
        self._bound_port: int | None = None
        self._last_error: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_stop: asyncio.Event | None = None

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    @property
    def port(self) -> int | None:
        return self._bound_port

    def request_stop(self) -> None:
        """Request a graceful stop; safe from a signal or another thread."""

        self._target_lifecycle.request_close()
        self._stop_requested.set()
        loop, event = self._loop, self._async_stop
        if loop is not None and event is not None and loop.is_running():
            loop.call_soon_threadsafe(event.set)

    def handshake(self) -> Handshake:
        try:
            from mklink import __version__ as mklink_version
        except (ImportError, AttributeError):
            mklink_version = "unknown"
        capabilities = {
            "agent.lifecycle": Capability(
                True,
                detail="health/status/ports/reconnect/stop",
            ),
            "probe.connection": Capability(
                True,
                detail="explicit reconnect; probe optional",
            ),
        }
        if self._capability_provider is not None:
            try:
                injected = self._capability_provider()
                if not isinstance(injected, Mapping):
                    raise TypeError
                for name in sorted(injected):
                    descriptor = injected[name]
                    if (
                        not isinstance(name, str)
                        or not name
                        or not isinstance(descriptor, Capability)
                    ):
                        raise TypeError
                    # Agent-owned lifecycle descriptors cannot be replaced.
                    if name not in capabilities:
                        capabilities[name] = descriptor
            except Exception:
                raise AgentOperationError(
                    "Capability provider failed",
                ) from None
        return Handshake(
            protocol_version=PROTOCOL_VERSION,
            mklink_version=str(mklink_version),
            capabilities=capabilities,
            limits=self.config.limits,
        )

    def health(self) -> dict[str, Any]:
        result = {
            "ready": self.ready,
            "listener": self.ready,
            "probe_connected": self._device_connected(),
        }
        if self.config.transport != "direct":
            tunnel = self._transport_status()
            result.update(
                {
                    "transport": self.config.transport,
                    "transport_ready": bool(tunnel.get("ready")),
                }
            )
        return result

    def _transport_status(self) -> Mapping[str, Any]:
        provider = self.config.transport_status
        if provider is None:
            return {"state": "not-configured", "ready": False}
        try:
            value = provider()
        except Exception:
            return {"state": "failed", "ready": False}
        return value if isinstance(value, Mapping) else {
            "state": "failed",
            "ready": False,
        }

    def status(self) -> dict[str, Any]:
        result = {
            **self.health(),
            "host": self.config.host,
            "port": self._bound_port,
            "device_state": "connected" if self._device_connected() else "disconnected",
            "last_error": self._last_error,
            "resources": self._resources.get_status(),
        }
        if self.config.transport != "direct":
            result["transport_status"] = dict(self._transport_status())
        return result

    def ports(self) -> list[Any]:
        try:
            from mklink.discovery import list_available_ports
            result = list_available_ports()
            return result if isinstance(result, list) else []
        except Exception:
            # Discovery must not turn an otherwise healthy no-probe agent into
            # a failed listener.  Detailed OS errors can expose local paths.
            self._last_error = "Port discovery failed"
            return []

    def reconnect(self) -> dict[str, Any]:
        """Open/reopen a probe without interrupting the listener."""

        with self._target_lifecycle.lifecycle():
            if self._target_lifecycle.closing:
                return {"connected": False, "error": "Agent is stopping"}
            if self._device_reconnector is not None:
                try:
                    self._device_reconnector(self.config)
                except (Exception, SystemExit):
                    self._last_error = "Device connection failed"
                    return {"connected": False, "error": self._last_error}
                self._last_error = None
                return {"connected": self._device_connected()}
            self._close_device_locked()
            try:
                kwargs = {"port": self.config.device_port, "axf": self.config.axf}
                self._device = self._device_factory(**kwargs)
            except (Exception, SystemExit):
                self._device = None
                self._last_error = "Device connection failed"
                return {"connected": False, "error": self._last_error}
            self._last_error = None
            return {"connected": self._device_connected()}

    def close(self) -> None:
        self._target_lifecycle.request_close()
        with self._target_lifecycle.lifecycle():
            if self._owns_device:
                self._close_device_locked()
            if self._owns_resources:
                self._resources.release_all()

    async def _enter_target_dispatch(self) -> None:
        admission = asyncio.create_task(
            asyncio.to_thread(self._target_lifecycle.enter_dispatch)
        )
        try:
            await asyncio.shield(admission)
        except BaseException:
            def release_if_admitted(task: asyncio.Task[None]) -> None:
                try:
                    task.result()
                except BaseException:
                    return
                self._target_lifecycle.leave_dispatch()

            admission.add_done_callback(release_if_admitted)
            raise

    @staticmethod
    async def _wait_for_lower_level(awaitable: Any) -> Any:
        operation = asyncio.ensure_future(awaitable)
        cancellation: asyncio.CancelledError | None = None
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError as exc:
                if cancellation is None:
                    cancellation = exc
            except BaseException:
                break
        if cancellation is None:
            return operation.result()
        if not operation.cancelled():
            try:
                operation.result()
            except BaseException:
                pass
        raise cancellation

    @classmethod
    async def _invoke_lower_level(cls, callback, *arguments):
        async def invoke():
            call = getattr(callback, "__call__", callback)
            is_async = inspect.iscoroutinefunction(callback) or (
                call is not callback and inspect.iscoroutinefunction(call)
            )
            result = callback(*arguments) if is_async else await asyncio.to_thread(callback, *arguments)
            return await result if inspect.isawaitable(result) else result

        # Shield both phases, including a sync callback returning an awaitable.
        return await cls._wait_for_lower_level(invoke())

    def _close_device_locked(self) -> None:
        device, self._device = self._device, None
        if device is not None:
            close = getattr(device, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug("Device close failed during agent cleanup", exc_info=True)

    def _device_connected(self) -> bool:
        # Device mutation is serialized, but diagnostics must not wait behind
        # a slow factory or lower-level reconnect.  Reconnect publishes None
        # before opening and atomically replaces this reference on success.
        device = self._current_device()
        if device is None:
            return False
        try:
            return bool(getattr(device, "connected", True))
        except Exception:
            return False

    def _current_device(self) -> Any | None:
        if self._device_getter is None:
            return self._device
        try:
            return self._device_getter()
        except Exception:
            return None

    async def serve(self) -> int:
        """Run the standards-compliant WebSocket listener until stopped."""

        try:
            from websockets.server import serve
        except ImportError as exc:  # pragma: no cover - packaging failure path
            raise RuntimeError("The site agent requires the declared websockets dependency") from exc

        self._loop = asyncio.get_running_loop()
        self._async_stop = asyncio.Event()
        if self._stop_requested.is_set():
            self._async_stop.set()
        try:
            async with serve(
                self._handle_connection,
                self.config.host,
                self.config.port,
                max_size=self.config.limits.max_message_bytes,
                max_queue=self.config.limits.max_queue,
                open_timeout=self.config.limits.handshake_timeout_seconds,
                close_timeout=self.config.limits.close_timeout_seconds,
                ping_interval=20,
                ping_timeout=20,
            ) as server:
                sockets = server.sockets or []
                if not sockets:
                    raise RuntimeError("agent listener did not expose a socket")
                self._bound_port = int(sockets[0].getsockname()[1])
                self._ready.set()
                if self.config.ready_callback:
                    self.config.ready_callback(self.status())
                await self._async_stop.wait()
        finally:
            self._ready.clear()
            await asyncio.to_thread(self.close)
            self._bound_port = None
            self._async_stop = None
            self._loop = None
        return 0

    async def _handle_connection(self, websocket: Any, *_path: Any) -> None:
        client_id = secrets.token_hex(16)
        try:
            await self._serve_connection(websocket, client_id)
        finally:
            if self._client_closed is not None:
                try:
                    await self._invoke_lower_level(self._client_closed, client_id)
                except Exception:
                    logger.exception("Site agent client cleanup failed; not retried")

    async def _serve_connection(self, websocket: Any, client_id: str) -> None:
        from websockets.exceptions import ConnectionClosed

        authenticated = False
        first_request = True
        while True:
            request_id: str | int | None = None
            try:
                if first_request:
                    raw = await asyncio.wait_for(
                        websocket.recv(), timeout=self.config.limits.handshake_timeout_seconds,
                    )
                else:
                    raw = await websocket.recv()
                first_request = False
                if not isinstance(raw, str):
                    raise ProtocolError("Text JSON-RPC messages are required")
                request = RequestEnvelope.parse(json.loads(raw))
                request_id = request.request_id
                if request.method == "system.handshake":
                    # A failed re-handshake must revoke any prior session state.
                    # Authentication is committed only after every handshake
                    # phase, including capability construction, succeeds.
                    authenticated = False
                    token_authenticated = self._authenticate(request.params)
                    version = request.params.get("protocol_version", request.params.get("version"))
                    if not compatible_version(version):
                        raise CompatibilityError(
                            data={"supported_protocol_version": PROTOCOL_VERSION, "action": "upgrade_client"},
                        )
                    handshake = self.handshake()
                    authenticated = token_authenticated
                    response = result_envelope(handshake.as_dict(), request_id)
                else:
                    if not authenticated:
                        raise AuthenticationError()
                    response = result_envelope(await self._dispatch(request, client_id=client_id), request_id)
                await websocket.send(json.dumps(response, separators=(",", ":")))
            except asyncio.TimeoutError:
                await websocket.close(code=1008, reason="Handshake timeout")
                return
            except ProtocolError as exc:
                await websocket.send(json.dumps(error_envelope(exc, request_id), separators=(",", ":")))
                if isinstance(exc, AuthenticationError):
                    await websocket.close(code=1008, reason="Authentication required")
                    return
            except json.JSONDecodeError:
                error = ProtocolError("Invalid JSON")
                await websocket.send(json.dumps(error_envelope(error, request_id), separators=(",", ":")))
            except ConnectionClosed:
                return
            except Exception:
                logger.exception("Site agent request failed")
                error = AgentOperationError()
                await websocket.send(json.dumps(error_envelope(error, request_id), separators=(",", ":")))

    def _authenticate(self, params: Any) -> bool:
        if not isinstance(params, dict):
            raise AuthenticationError()
        if self.config.token is None:
            return True
        supplied = params.get("token")
        if not isinstance(supplied, str) or not secrets.compare_digest(supplied, self.config.token):
            raise AuthenticationError()
        return True

    async def _dispatch(self, request: RequestEnvelope, *, client_id: str | None = None) -> Any:
        handlers: dict[str, Callable[[], Any]] = {
            "agent.health": self.health,
            "agent.status": self.status,
            "agent.ports": self.ports,
            "agent.stop": self.request_stop,
        }
        if request.method == "agent.reconnect":
            return await self._invoke_lower_level(self.reconnect)
        handler = handlers.get(request.method)
        if handler is not None:
            result = handler()
            if inspect.isawaitable(result):
                result = await result
            if request.method == "agent.stop":
                return {"stopping": True}
            return result

        dispatcher = self._request_dispatcher
        if dispatcher is None:
            raise MethodNotFoundError(
                data={"method": request.method, "reason": "unsupported"},
            )
        await self._enter_target_dispatch()
        try:
            context = AgentDispatchContext(
                device=self._current_device(),
                resource_manager=self._resources,
                client_id=client_id,
            )
            return await self._invoke_lower_level(
                dispatcher, request.method, request.params, context,
            )
        except ProtocolError:
            raise
        except Exception:
            raise AgentOperationError() from None
        finally:
            self._target_lifecycle.leave_dispatch()


def run_agent(
    config: AgentConfig,
    *,
    device_factory: Callable[..., Any],
    capability_provider: CapabilityProvider | None = None,
    request_dispatcher: RequestDispatcher | None = None,
    client_closed: Callable[[str], Any] | None = None,
) -> int:
    """Run a direct Site Agent and return ``0`` after a cooperative stop."""

    validate_bind(config.host, config.token, allow_lan=config.allow_lan)
    return asyncio.run(
        SiteAgent(
            config,
            device_factory,
            capability_provider=capability_provider,
            request_dispatcher=request_dispatcher,
            client_closed=client_closed,
        ).serve()
    )


__all__ = [
    "AgentConfig",
    "AgentDispatchContext",
    "CapabilityProvider",
    "RequestDispatcher",
    "SiteAgent",
    "run_agent",
    "validate_bind",
]
