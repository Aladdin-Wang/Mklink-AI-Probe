"""Engineer CLI and standalone field-agent entry points for direct sites."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


_DEFAULT_TOKEN_ENV = "MKLINK_REMOTE_TOKEN"
_DEFAULT_STCP_AUTH_ENV = "MKLINK_STCP_AUTH_TOKEN"
_DEFAULT_STCP_SECRET_ENV = "MKLINK_STCP_SECRET"


class _SecretSafeArgumentParser(argparse.ArgumentParser):
    """Reject deprecated direct-token inputs without echoing their values."""

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


def _emit(value: Any) -> None:
    print(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        flush=True,
    )


def _object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("expected a JSON object") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return parsed


def _token(args: argparse.Namespace) -> str:
    token_file = getattr(args, "token_file", None)
    if token_file is not None:
        from mklink.remote.transfer import has_owner_only_permissions

        try:
            path = Path(token_file).expanduser().resolve()
            if not path.is_file() or not has_owner_only_permissions(path):
                raise PermissionError
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                "token file must exist and grant owner-only access"
            ) from exc
    else:
        name = getattr(args, "token_env", None) or _DEFAULT_TOKEN_ENV
        value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError("the configured token source is empty")
    return value


def _required_secret(
    *,
    environment_name: str,
    file_path: Path | None,
    label: str,
) -> str:
    if file_path is not None:
        from mklink.remote.transfer import has_owner_only_permissions

        try:
            path = file_path.expanduser().resolve()
            if not path.is_file() or not has_owner_only_permissions(path):
                raise PermissionError
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                f"{label} file must exist and grant owner-only access"
            ) from exc
    else:
        value = os.environ.get(environment_name, "").strip()
    if not value:
        raise ValueError(f"the configured {label} source is empty")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = _SecretSafeArgumentParser(
        prog="mklink-remote",
        description=(
            "Mklink site client for direct LAN/VPN or in-process LAN STCP "
            "(no frpc executable)."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--site", default=None, help="registered site name")
    parser.add_argument(
        "--project-root",
        default=".",
        help="project root used for its active-site pointer",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    sites = commands.add_parser("sites", help="manage owner-only site records")
    site_commands = sites.add_subparsers(dest="sites_command", required=True)
    add = site_commands.add_parser("add", help="register a direct ws:// or wss:// site")
    add.add_argument("name")
    add.add_argument("url")
    token_source = add.add_mutually_exclusive_group()
    token_source.add_argument("--token-env", default=_DEFAULT_TOKEN_ENV)
    token_source.add_argument("--token-file", type=Path)
    add.add_argument("--note", default="")
    remove = site_commands.add_parser("remove", help="remove a site")
    remove.add_argument("name")
    site_commands.add_parser("list", help="list sites without tokens")
    switch = site_commands.add_parser("switch", help="set the user-wide active site")
    switch.add_argument("name")
    switch.add_argument("--connect", action="store_true")
    use = site_commands.add_parser("use", help="set this project's active site")
    use.add_argument("name")

    commands.add_parser("status", help="probe-independent agent status")
    commands.add_parser("health", help="probe-independent agent health")
    commands.add_parser("ports", help="list probe ports at the field site")
    commands.add_parser("capabilities", help="show negotiated capability descriptors")
    commands.add_parser("reconnect", help="connect or reconnect the field probe")

    call = commands.add_parser("call", help="invoke a declared capability operation")
    call.add_argument("operation")
    call.add_argument("--params", type=_object, default={})
    call.add_argument(
        "--yes",
        action="store_true",
        help="explicitly confirm a named high-risk operation",
    )

    upload = commands.add_parser("upload", help="atomically upload a local file")
    upload.add_argument("path", type=Path)

    flash = commands.add_parser(
        "flash",
        help="HIGH RISK: upload and program firmware at the selected site",
    )
    flash.add_argument("path", type=Path)
    flash.add_argument("--target-part")
    flash.add_argument("--base-address")
    flash.add_argument("--board")
    flash.add_argument("--no-verify", action="store_true")
    flash.add_argument("--no-reset", action="store_true")
    flash.add_argument(
        "--yes",
        action="store_true",
        required=True,
        help="confirm target flash modification",
    )

    stop = commands.add_parser(
        "stop-agent",
        help="HIGH RISK: stop the standalone field agent",
    )
    stop.add_argument("--yes", action="store_true", required=True)

    stcp = commands.add_parser(
        "stcp",
        help="run an in-process LAN STCP visitor without frpc.exe",
    )
    stcp_commands = stcp.add_subparsers(dest="stcp_command", required=True)
    visitor = stcp_commands.add_parser(
        "visitor",
        help="bind a loopback port for one registered STCP provider",
    )
    visitor.add_argument("--server-addr", required=True)
    visitor.add_argument("--server-port", type=int, default=7000)
    visitor.add_argument("--user", default="")
    visitor.add_argument("--proxy-name", required=True)
    visitor.add_argument("--bind-addr", default="127.0.0.1")
    visitor.add_argument("--bind-port", type=int, required=True)
    auth_source = visitor.add_mutually_exclusive_group()
    auth_source.add_argument("--stcp-auth-token-env", default=_DEFAULT_STCP_AUTH_ENV)
    auth_source.add_argument("--stcp-auth-token-file", type=Path)
    secret_source = visitor.add_mutually_exclusive_group()
    secret_source.add_argument("--stcp-secret-env", default=_DEFAULT_STCP_SECRET_ENV)
    secret_source.add_argument("--stcp-secret-file", type=Path)
    visitor.add_argument("--stcp-library", type=Path)
    return parser


def _run_stcp_visitor(args: argparse.Namespace) -> int:
    from mklink.remote.stcp import STCPSession, STCPVisitorConfig

    auth_token = _required_secret(
        environment_name=args.stcp_auth_token_env,
        file_path=args.stcp_auth_token_file,
        label="FRP authentication token",
    )
    secret_key = _required_secret(
        environment_name=args.stcp_secret_env,
        file_path=args.stcp_secret_file,
        label="STCP secret",
    )
    if auth_token == secret_key:
        raise ValueError("FRP authentication token and STCP secret must be distinct")
    session = STCPSession(
        STCPVisitorConfig(
            server_addr=args.server_addr,
            server_port=args.server_port,
            auth_token=auth_token,
            user=args.user,
            proxy_name=args.proxy_name,
            secret_key=secret_key,
            bind_addr=args.bind_addr,
            bind_port=args.bind_port,
        ),
        library=args.stcp_library,
    )
    try:
        status = session.start()
        _emit(
            {
                **status,
                "url": f"ws://{args.bind_addr}:{args.bind_port}",
            }
        )
        while True:
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 130
    finally:
        session.close()


def _client(args: argparse.Namespace):
    from mklink.remote.sites import default_registry

    return default_registry().client(
        args.site,
        project_root=Path(args.project_root),
    )


def _require_support(client: Any, capability: str) -> None:
    if not client.supports(capability):
        raise RuntimeError(f"site does not advertise capability {capability!r}")


def _invoke(args: argparse.Namespace, operation: str, params: Mapping[str, Any]) -> Any:
    from mklink.remote.capabilities import operation_schema

    client = _client(args)
    schema = operation_schema(operation)
    if schema is not None:
        _require_support(client, schema.capability)
    return client.call(operation, **dict(params))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "stcp":
            return _run_stcp_visitor(args)
        if args.command == "sites":
            from mklink.remote.sites import default_registry

            registry = default_registry()
            if args.sites_command == "add":
                result = registry.add(
                    args.name,
                    args.url,
                    _token(args),
                    note=args.note,
                )
            elif args.sites_command == "remove":
                result = registry.remove(args.name)
            elif args.sites_command == "list":
                result = registry.list()
            elif args.sites_command == "switch":
                result = registry.switch(args.name, connect=args.connect)
            else:
                result = registry.write_project_site(
                    Path(args.project_root),
                    args.name,
                )
            _emit(result)
            return 0

        if args.command == "capabilities":
            client = _client(args)
            _emit(
                {
                    name: capability.as_dict()
                    for name, capability in client.handshake().capabilities.items()
                }
            )
            return 0
        if args.command in {"status", "health", "ports"}:
            result = _client(args).call(f"agent.{args.command}")
            _emit(result)
            return 0
        if args.command == "reconnect":
            _emit(_client(args).call("agent.reconnect"))
            return 0
        if args.command == "stop-agent":
            _emit(_client(args).call("agent.stop"))
            return 0
        if args.command == "call":
            from mklink.remote.capabilities import operation_schema

            schema = operation_schema(args.operation)
            if schema is None:
                raise ValueError("operation is not declared")
            if schema.high_risk and not args.yes:
                raise ValueError("explicit confirmation is required")
            params = dict(args.params)
            if args.yes:
                params["confirm"] = True
            _emit(_invoke(args, args.operation, params))
            return 0
        if args.command == "upload":
            client = _client(args)
            _require_support(client, "transfer.upload")
            _emit(client.upload(args.path).as_dict())
            return 0
        if args.command == "flash":
            client = _client(args)
            _require_support(client, "transfer.upload")
            _require_support(client, "flash.online")
            remote_file = client.upload(args.path)
            params = {
                "firmware": remote_file.reference,
                "confirm": True,
                "verify": not args.no_verify,
                "reset_after": not args.no_reset,
            }
            for name in ("target_part", "base_address", "board"):
                value = getattr(args, name)
                if value is not None:
                    params[name] = value
            _emit(client.call("flash.program", **params))
            return 0
    except Exception as exc:
        # Structured protocol errors are already public and redacted by the
        # field agent.  Other exceptions may contain local paths or secrets.
        from mklink.remote.client import RemoteProtocolError

        message = str(exc) if isinstance(exc, RemoteProtocolError) else "operation failed"
        print(f"mklink remote: {message}", file=sys.stderr)
        return 2
    finally:
        try:
            from mklink.remote.sites import close_all

            close_all()
        except Exception:
            pass
    return 2


def build_agent_parser() -> argparse.ArgumentParser:
    parser = _SecretSafeArgumentParser(
        prog="mklink-remote-agent",
        description="Standalone direct VPN/LAN field agent.",
        allow_abbrev=False,
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
    token_source = parser.add_mutually_exclusive_group()
    token_source.add_argument("--token-env", default=_DEFAULT_TOKEN_ENV)
    token_source.add_argument("--token-file", type=Path)
    token_source.add_argument(
        "--no-token",
        action="store_true",
        help="allow an unauthenticated loopback listener for local development",
    )
    parser.add_argument("--device-port")
    parser.add_argument("--axf")
    parser.add_argument("--project-root", default=".")
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


def _agent_stcp_session(args: argparse.Namespace, token: str | None):
    if args.transport != "lan-stcp":
        return None
    if token is None:
        raise ValueError("LAN STCP requires Site Agent authentication")
    auth_token = _required_secret(
        environment_name=args.stcp_auth_token_env,
        file_path=args.stcp_auth_token_file,
        label="FRP authentication token",
    )
    secret_key = _required_secret(
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


def agent_main(argv: Sequence[str] | None = None) -> int:
    args = build_agent_parser().parse_args(list(argv) if argv is not None else None)
    try:
        token = None if args.no_token else _token(args)
    except ValueError as exc:
        print(f"mklink remote agent: {exc}", file=sys.stderr)
        return 2

    try:
        transport = _agent_stcp_session(args, token)
    except Exception:
        print("mklink remote agent: transport configuration failed", file=sys.stderr)
        return 2

    from mklink.remote.agent import AgentConfig, run_agent
    from mklink.remote.dispatcher import OperationDispatcher

    dispatcher = OperationDispatcher(args.project_root)
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
        ready_callback=(
            (lambda _status: transport.start())
            if transport is not None
            else None
        ),
    )

    def device_factory(*, port: str | None = None, axf: str | None = None):
        import mklink

        return mklink.connect(
            port=port,
            axf=axf,
            project_root=args.project_root,
        )

    try:
        return run_agent(
            config,
            device_factory=device_factory,
            capability_provider=dispatcher.capabilities,
            request_dispatcher=dispatcher.dispatch,
        )
    except KeyboardInterrupt:
        return 130
    finally:
        if transport is not None:
            transport.close()
        dispatcher.close()


__all__ = ["agent_main", "build_agent_parser", "build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
