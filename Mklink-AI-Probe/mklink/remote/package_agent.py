"""Lifecycle entry point for the standalone Windows Site Agent package.

The packaged ``start`` process is the Site Agent.  It deliberately does not
spawn a supervisor or worker, which gives field operators a single foreground
process with ordinary console and service-manager ownership semantics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Sequence


_LIFECYCLE_SCHEMA = "mklink.site-agent.lifecycle.v1"
_DEFAULT_TOKEN_ENV = "MKLINK_REMOTE_TOKEN"
_DEFAULT_STCP_AUTH_ENV = "MKLINK_STCP_AUTH_TOKEN"
_DEFAULT_STCP_SECRET_ENV = "MKLINK_STCP_SECRET"


class _SecretSafeArgumentParser(argparse.ArgumentParser):
    """Reject obsolete direct-token inputs without echoing their values."""

    def parse_known_args(
        self,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> tuple[argparse.Namespace, list[str]]:
        values = list(sys.argv[1:] if args is None else args)
        if any(value == "--token" or value.startswith("--token=") for value in values):
            self.error(
                "direct token values are not supported; "
                "use --token-env or --token-file"
            )
        prohibited = ("--stcp-auth-token", "--stcp-secret")
        if any(
            value == name or value.startswith(f"{name}=")
            for value in values
            for name in prohibited
        ):
            self.error(
                "secret values are not supported on the command line; "
                "use the matching environment or file option"
            )
        return super().parse_known_args(values, namespace)


def _emit(event: str, **values: Any) -> None:
    """Write one machine-readable lifecycle event."""

    payload = {
        "schema": _LIFECYCLE_SCHEMA,
        "event": event,
        **values,
    }
    print(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        flush=True,
    )


def _write_ready_file(path: Path, payload: dict[str, Any]) -> None:
    """Atomically publish non-secret readiness state."""

    from mklink.remote.transfer import enforce_owner_only_permissions

    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        enforce_owner_only_permissions(temporary)
        os.replace(temporary, target)
        enforce_owner_only_permissions(target)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_ready_file(path: Path | None) -> None:
    if path is None:
        return
    target = path.expanduser().resolve()
    try:
        current = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(current, dict) and current.get("pid") == os.getpid():
            target.unlink(missing_ok=True)
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        pass


def _load_token(args: argparse.Namespace) -> str | None:
    """Load authentication without accepting a command-line token."""

    if args.no_token:
        if args.token_file is not None:
            raise ValueError("--no-token cannot be combined with --token-file")
        return None
    if args.token_file is not None:
        from mklink.remote.transfer import has_owner_only_permissions

        token_path = args.token_file.expanduser().resolve()
        if not token_path.is_file() or not has_owner_only_permissions(token_path):
            raise PermissionError("token file must exist and grant owner-only access")
        token = token_path.read_text(encoding="utf-8").strip()
    else:
        token = os.environ.get(args.token_env, "").strip()
    if not token:
        raise ValueError("the configured token source is empty")
    return token


def _load_required_secret(
    *,
    environment_name: str,
    file_path: Path | None,
    label: str,
) -> str:
    if file_path is not None:
        from mklink.remote.transfer import has_owner_only_permissions

        path = file_path.expanduser().resolve()
        if not path.is_file() or not has_owner_only_permissions(path):
            raise PermissionError(
                f"{label} file must exist and grant owner-only access"
            )
        value = path.read_text(encoding="utf-8").strip()
    else:
        value = os.environ.get(environment_name, "").strip()
    if not value:
        raise ValueError(f"the configured {label} source is empty")
    return value


def _stcp_session(args: argparse.Namespace, token: str | None):
    if args.transport != "lan-stcp":
        return None
    if token is None:
        raise ValueError("LAN STCP requires Site Agent authentication")
    auth_token = _load_required_secret(
        environment_name=args.stcp_auth_token_env,
        file_path=args.stcp_auth_token_file,
        label="FRP authentication token",
    )
    secret_key = _load_required_secret(
        environment_name=args.stcp_secret_env,
        file_path=args.stcp_secret_file,
        label="STCP secret",
    )
    if len({token, auth_token, secret_key}) != 3:
        raise ValueError(
            "Site Agent token, FRP authentication token, and STCP secret "
            "must be distinct"
        )
    from mklink.remote.stcp import STCPProviderConfig, STCPSession

    return STCPSession(
        STCPProviderConfig(
            server_addr=args.stcp_server_addr,
            server_port=args.stcp_server_port,
            auth_token=auth_token,
            user=args.stcp_user,
            proxy_name=args.stcp_proxy_name,
            secret_key=secret_key,
            local_addr=args.host,
            local_port=args.port,
        ),
        library=args.stcp_library,
    )


def _url(host: str, port: int) -> str:
    bracketed = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"ws://{bracketed}:{port}"


def _call(
    host: str,
    port: int,
    token: str | None,
    method: str,
    *,
    timeout: float,
) -> Any:
    from mklink.remote.client import RemoteClient

    with RemoteClient(_url(host, port), token=token, timeout=timeout) as client:
        return client.call(method)


def _install_signal_handlers(agent: Any) -> dict[int, Any]:
    previous: dict[int, Any] = {}
    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    for signum in signals:
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda *_ignored: agent.request_stop())
        except (OSError, RuntimeError, ValueError):
            pass
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except (OSError, RuntimeError, ValueError):
            pass


def _start(args: argparse.Namespace, token: str | None) -> int:
    from mklink.remote.agent import AgentConfig, SiteAgent
    from mklink.remote.dispatcher import OperationDispatcher

    ready_file = args.ready_file
    dispatcher = OperationDispatcher(args.project_root)
    transport = _stcp_session(args, token)

    def device_factory(*, port: str | None = None, axf: str | None = None):
        import mklink

        return mklink.connect(
            port=port,
            axf=axf,
            project_root=args.project_root,
        )

    def on_ready(status: dict[str, Any]) -> None:
        tunnel = (
            transport.start()
            if transport is not None
            else {"state": "not-required", "ready": True}
        )
        if not tunnel.get("ready"):
            raise RuntimeError("LAN STCP transport did not become ready")
        payload = {
            "schema": _LIFECYCLE_SCHEMA,
            "event": "ready",
            "ready": True,
            "host": status["host"],
            "port": status["port"],
            "pid": os.getpid(),
            "probe_connected": bool(status["probe_connected"]),
            "owned_children": 0,
            "transport": args.transport,
            "tunnel_ready": bool(tunnel["ready"]),
        }
        if ready_file is not None:
            _write_ready_file(ready_file, payload)
        _emit(
            "ready",
            ready=True,
            host=status["host"],
            port=status["port"],
            pid=os.getpid(),
            probe_connected=bool(status["probe_connected"]),
            owned_children=0,
            transport=args.transport,
            tunnel_ready=bool(tunnel["ready"]),
        )

    config = AgentConfig(
        host=args.host,
        port=args.port,
        token=token,
        allow_lan=args.allow_lan,
        device_port=args.device_port,
        axf=args.axf,
        project_root=args.project_root,
        transport=args.transport,
        transport_status=(
            transport.status
            if transport is not None
            else None
        ),
        ready_callback=on_ready,
    )
    agent = SiteAgent(
        config,
        device_factory,
        capability_provider=dispatcher.capabilities,
        request_dispatcher=dispatcher.dispatch,
    )
    previous = _install_signal_handlers(agent)
    try:
        result = asyncio.run(agent.serve())
        _emit("stopped", stopped=True, pid=os.getpid(), owned_children=0)
        return result
    finally:
        _restore_signal_handlers(previous)
        if transport is not None:
            transport.close()
        dispatcher.close()
        _remove_ready_file(ready_file)


def _restart(args: argparse.Namespace, token: str | None) -> int:
    from mklink.remote.client import RemoteConnectionError

    if args.port == 0:
        raise ValueError("restart requires a non-zero port")
    try:
        result = _call(
            args.host,
            args.port,
            token,
            "agent.stop",
            timeout=args.timeout,
        )
        _emit("restart_stop_requested", result=result, owned_children=0)
    except RemoteConnectionError:
        _emit("restart_previous_unavailable", owned_children=0)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            _call(
                args.host,
                args.port,
                token,
                "agent.health",
                timeout=min(0.5, args.timeout),
            )
        except RemoteConnectionError:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("previous agent did not stop before the restart timeout")
    return _start(args, token)


def build_parser() -> argparse.ArgumentParser:
    parser = _SecretSafeArgumentParser(
        prog="mklink-remote-agent",
        description=(
            "Standalone Mklink Site Agent for direct VPN/LAN or in-process "
            "LAN STCP without frpc.exe."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("start", "health", "status", "stop", "restart"),
        default="start",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--allow-lan", action="store_true")
    parser.add_argument(
        "--transport",
        choices=("direct", "lan-stcp"),
        default="direct",
        help="direct LAN/VPN or in-process LAN STCP (no frpc executable)",
    )
    parser.add_argument("--token-env", default=_DEFAULT_TOKEN_ENV)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument(
        "--no-token",
        action="store_true",
        help="allow an unauthenticated loopback listener for local development",
    )
    parser.add_argument("--device-port")
    parser.add_argument("--axf")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--stcp-server-addr")
    parser.add_argument("--stcp-server-port", type=int, default=7000)
    parser.add_argument("--stcp-user", default="")
    parser.add_argument("--stcp-proxy-name")
    auth_source = parser.add_mutually_exclusive_group()
    auth_source.add_argument("--stcp-auth-token-env", default=_DEFAULT_STCP_AUTH_ENV)
    auth_source.add_argument("--stcp-auth-token-file", type=Path)
    secret_source = parser.add_mutually_exclusive_group()
    secret_source.add_argument("--stcp-secret-env", default=_DEFAULT_STCP_SECRET_ENV)
    secret_source.add_argument("--stcp-secret-file", type=Path)
    parser.add_argument("--stcp-library", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.timeout <= 0:
            raise ValueError("timeout must be positive")
        token = _load_token(args)
        if args.command == "start":
            return _start(args, token)
        if args.command == "restart":
            return _restart(args, token)
        if args.port == 0:
            raise ValueError("lifecycle control requires a non-zero port")
        method = "agent.stop" if args.command == "stop" else f"agent.{args.command}"
        result = _call(
            args.host,
            args.port,
            token,
            method,
            timeout=args.timeout,
        )
        _emit(args.command, result=result, owned_children=0)
        return 0
    except KeyboardInterrupt:
        _emit("interrupted", stopped=True, pid=os.getpid(), owned_children=0)
        return 130
    except Exception:
        # Lifecycle failures are intentionally redacted: dependency errors can
        # include local paths and authentication failures must not echo secrets.
        _emit("error", error="site agent lifecycle operation failed", owned_children=0)
        return 2


__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
