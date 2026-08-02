"""Permanent regressions for the R.1 remote-review repairs.

These tests exercise public boundaries where practical and use controlled
in-memory or temporary-directory doubles only for transports, devices, and
optional hardware providers.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import threading
import tomllib
import types
from pathlib import Path

import pytest

from mklink.remote.agent import AgentConfig, AgentDispatchContext, SiteAgent
from mklink.remote import cli as remote_cli
from mklink.remote import package_agent
from mklink.remote.client import (
    RemoteClient,
    RemoteConnectionError,
    validate_endpoint,
)
from mklink.remote.dispatcher import dispatch_capability
from mklink.remote.protocol import ProtocolLimits, RequestEnvelope
from mklink.remote.resource_manager import ResourceGroup, ResourceManager
from mklink.remote.sites import SiteRegistry
from mklink.remote.transfer import (
    TransferLimitError,
    TransferLimits,
    TransferStateError,
    UploadManager,
    enforce_owner_only_permissions,
)


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIRECT_TOKEN_MIGRATION = (
    "direct token values are not supported; use --token-env or --token-file"
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ws://field-host:8766", "ws://field-host:8766"),
        ("WSS://FIELD-HOST:443/", "wss://field-host:443"),
        ("ws://127.0.0.1", "ws://127.0.0.1"),
        ("ws://[2001:db8::1]:8766", "ws://[2001:db8::1]:8766"),
    ],
)
def test_public_client_and_registry_share_canonical_endpoint_policy(
    tmp_path, monkeypatch, value, expected
):
    assert validate_endpoint(value) == expected
    monkeypatch.setattr(RemoteClient, "reconnect", lambda self: None)
    client = RemoteClient(value, token="inert")
    assert client.url == expected

    created = []

    def factory(url, *, token, timeout=10.0):
        created.append((url, token, timeout))
        return object()

    registry = SiteRegistry(path=tmp_path / "sites.json", client_factory=factory)
    registry.add("field", value, "inert")
    assert registry.get("field").url == expected


@pytest.mark.parametrize(
    "value",
    [
        "ws://user@field-host:8766",
        "ws://field-host:8766?auth=x",
        "ws://field-host:8766#fragment",
        "ws://field-host:8766/not-root",
        "ws://",
        "ws://field host:8766",
        "ws://field-host:0",
        "ws://field-host:65536",
        "ws://field-host:not-a-port",
        "ws://[2001:db8::1",
    ],
)
def test_invalid_endpoints_fail_before_sdk_transport_or_registry_factory(
    tmp_path, monkeypatch, value
):
    reconnects = []
    monkeypatch.setattr(
        RemoteClient, "reconnect", lambda self: reconnects.append(self.url)
    )
    with pytest.raises((TypeError, ValueError)):
        RemoteClient(value, token="inert")
    assert reconnects == []

    created = []
    registry = SiteRegistry(
        path=tmp_path / "sites.json",
        client_factory=lambda *args, **kwargs: created.append((args, kwargs)),
    )
    with pytest.raises((TypeError, ValueError)):
        registry.add("field", value, "inert")
    assert created == []


def test_incompatible_client_handshake_closes_and_cannot_dispatch(monkeypatch):
    class FakeTransport:
        def __init__(self):
            self.sent = []
            self.closed = 0

        def send(self, payload):
            self.sent.append(json.loads(payload))

        def recv(self, timeout=None):
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": self.sent[-1]["id"],
                    "result": {
                        "protocol_version": "99.0",
                        "mklink_version": "test",
                        "capabilities": {},
                        "limits": ProtocolLimits().as_dict(),
                    },
                }
            )

        def close(self):
            self.closed += 1

    transport = FakeTransport()
    monkeypatch.setattr(
        "websockets.sync.client.connect", lambda *args, **kwargs: transport
    )
    client = object.__new__(RemoteClient)
    with pytest.raises(
        RemoteConnectionError, match="Incompatible remote protocol version"
    ):
        RemoteClient.__init__(
            client, "ws://127.0.0.1:8766", token="inert"
        )
    assert transport.closed == 1
    assert len(transport.sent) == 1
    assert client.connected is False
    with pytest.raises(RemoteConnectionError):
        client.handshake()
    with pytest.raises(RemoteConnectionError):
        client.call("agent.status")
    assert len(transport.sent) == 1


def _assert_pyinstaller_dependency_contract(document: str) -> None:
    parsed = tomllib.loads(document)
    project = parsed["project"]
    base = project.get("dependencies", [])
    extras = project.get("optional-dependencies", {})
    pin = "pyinstaller==6.18.0"
    assert base.count(pin) == 0
    assert extras["test"].count(pin) == 1
    assert extras["site-agent-build"].count(pin) == 1
    for name, dependencies in extras.items():
        if name not in {"test", "site-agent-build"}:
            assert all(
                not dependency.lower().startswith("pyinstaller")
                for dependency in dependencies
            ), name


def test_gui_test_extra_declares_exact_archive_audit_pin_and_runtime_boundaries():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    _assert_pyinstaller_dependency_contract(text)


def test_dependency_comments_and_irrelevant_strings_cannot_satisfy_contract():
    comment_only = """
[project]
name = "fixture"
version = "0"
dependencies = []

[project.optional-dependencies]
test = [
  "pytest",
  # "pyinstaller==6.18.0"
]
site-agent-build = [
  "build",
  # "pyinstaller==6.18.0"
]
remote = []
mcp = []

[tool.fixture]
irrelevant = "pyinstaller==6.18.0"
"""
    with pytest.raises(AssertionError):
        _assert_pyinstaller_dependency_contract(comment_only)


@pytest.mark.parametrize("builder", [remote_cli.build_parser, remote_cli.build_agent_parser])
@pytest.mark.parametrize(
    "obsolete",
    [["--token", "sensitive-sentinel"], ["--token=sensitive-sentinel"]],
)
def test_engineer_and_legacy_parsers_reject_direct_secret_values_redacted(
    builder, obsolete, capsys
):
    parser = builder()
    argv = (
        ["sites", "add", "field", "ws://127.0.0.1:8766", *obsolete]
        if builder is remote_cli.build_parser
        else obsolete
    )
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(argv)
    assert exc.value.code == 2
    diagnostics = capsys.readouterr().err
    assert "sensitive-sentinel" not in diagnostics
    assert "--token-env" in diagnostics
    assert "--token-file" in diagnostics


@pytest.mark.parametrize(
    "surface",
    ["engineer", "root", "legacy-agent"],
)
@pytest.mark.parametrize("spelling", ["separate", "equals"])
def test_real_cli_surfaces_reject_obsolete_direct_secret_input_redacted(
    surface, spelling
):
    sentinel = "r1-sensitive-sentinel"
    obsolete = (
        ["--token", sentinel]
        if spelling == "separate"
        else [f"--token={sentinel}"]
    )
    site_args = [
        "sites",
        "add",
        "field",
        "ws://127.0.0.1:8766",
        *obsolete,
    ]
    if surface == "engineer":
        command = [sys.executable, "-m", "mklink.remote.cli", *site_args]
    elif surface == "root":
        command = [sys.executable, "-m", "mklink", "remote", *site_args]
    else:
        command = [
            sys.executable,
            "-c",
            (
                "import sys; from mklink.remote.cli import agent_main; "
                "raise SystemExit(agent_main(sys.argv[1:]))"
            ),
            *obsolete,
        ]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    diagnostics = completed.stdout + completed.stderr
    assert completed.returncode == 2
    assert sentinel not in diagnostics
    assert "--token-env" in diagnostics
    assert "--token-file" in diagnostics


@pytest.mark.parametrize("surface", ["engineer", "root", "legacy-agent"])
def test_real_cli_help_has_protected_sources_and_no_direct_value_option(surface):
    if surface == "engineer":
        command = [
            sys.executable,
            "-m",
            "mklink.remote.cli",
            "sites",
            "add",
            "--help",
        ]
    elif surface == "root":
        command = [
            sys.executable,
            "-m",
            "mklink",
            "remote",
            "sites",
            "add",
            "--help",
        ]
    else:
        command = [
            sys.executable,
            "-c",
            (
                "from mklink.remote.cli import build_agent_parser; "
                "build_agent_parser().print_help()"
            ),
        ]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    help_text = completed.stdout + completed.stderr
    assert completed.returncode == 0
    assert "--token-env" in help_text
    assert "--token-file" in help_text
    assert re.search(r"--token(?:[ =]|$)", help_text) is None


@pytest.mark.parametrize("spelling", ["separate", "equals"])
def test_package_source_entry_rejects_direct_token_before_operation(
    spelling, tmp_path
):
    sentinel = f"package-source-direct-token-{spelling}"
    obsolete = (
        ["--token", sentinel]
        if spelling == "separate"
        else [f"--token={sentinel}"]
    )
    ready_file = tmp_path / "must-not-exist-ready.json"
    project_root = tmp_path / "must-not-exist-project"
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["MKLINK_REMOTE_TOKEN"] = "inert-protected-source"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mklink.remote.package_agent",
            "start",
            "--port",
            "0",
            "--ready-file",
            str(ready_file),
            "--project-root",
            str(project_root),
            *obsolete,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert sentinel not in completed.stderr
    assert completed.stderr.count(PACKAGE_DIRECT_TOKEN_MIGRATION) == 1
    assert not ready_file.exists()
    assert not project_root.exists()


def test_package_source_help_and_protected_token_sources_remain(
    monkeypatch, tmp_path
):
    parser = package_agent.build_parser()
    assert parser.allow_abbrev is False
    help_text = parser.format_help()
    assert "--token-env" in help_text
    assert "--token-file" in help_text
    assert re.search(r"--token(?:[ =]|$)", help_text) is None

    monkeypatch.setenv("R3_PACKAGE_TOKEN", "from-protected-environment")
    environment_args = parser.parse_args(
        ["health", "--token-env", "R3_PACKAGE_TOKEN"]
    )
    assert package_agent._load_token(environment_args) == (
        "from-protected-environment"
    )

    token_file = tmp_path / "package-token.txt"
    token_file.write_text("from-protected-file\n", encoding="utf-8")
    enforce_owner_only_permissions(token_file)
    file_args = parser.parse_args(["health", "--token-file", str(token_file)])
    assert package_agent._load_token(file_args) == "from-protected-file"

    no_token_args = parser.parse_args(["start", "--port", "0", "--no-token"])
    assert package_agent._load_token(no_token_args) is None


def test_protected_token_sources_and_loopback_no_token_remain(monkeypatch, tmp_path):
    monkeypatch.setenv("R1_REPAIR_TOKEN", "from-environment")
    env_args = remote_cli.build_parser().parse_args(
        [
            "sites",
            "add",
            "field",
            "ws://127.0.0.1:8766",
            "--token-env",
            "R1_REPAIR_TOKEN",
        ]
    )
    assert remote_cli._token(env_args) == "from-environment"

    token_file = tmp_path / "token.txt"
    token_file.write_text("from-file\n", encoding="utf-8")
    enforce_owner_only_permissions(token_file)
    file_args = remote_cli.build_parser().parse_args(
        [
            "sites",
            "add",
            "field",
            "ws://127.0.0.1:8766",
            "--token-file",
            str(token_file),
        ]
    )
    assert remote_cli._token(file_args) == "from-file"

    no_token = remote_cli.build_agent_parser().parse_args(
        ["--host", "127.0.0.1", "--no-token"]
    )
    assert no_token.no_token is True
    AgentConfig(host=no_token.host, token=None, allow_lan=no_token.allow_lan)
    with pytest.raises(ValueError):
        AgentConfig(host="192.0.2.1", token=None, allow_lan=True)


@pytest.mark.parametrize("cancel_count", [0, 1, 5])
def test_repeated_cancellation_holds_lifecycle_until_one_worker_finishes(
    cancel_count,
):
    async def scenario():
        worker_started = threading.Event()
        worker_release = threading.Event()
        worker_finished = threading.Event()
        device_closed = threading.Event()
        early_close = []
        calls = []
        factory_calls = []

        class Device:
            connected = True

            def close(self):
                early_close.append(not worker_finished.is_set())
                device_closed.set()

        def dispatcher(method, params, context):
            calls.append((method, params, context.device))
            worker_started.set()
            assert worker_release.wait(timeout=2), "worker release timed out"
            worker_finished.set()
            return {"done": True}

        device = Device()

        def factory(**_kwargs):
            factory_calls.append(True)
            return device

        agent = SiteAgent(
            AgentConfig(),
            device_factory=factory,
            request_dispatcher=dispatcher,
        )
        assert agent.reconnect() == {"connected": True}
        operation = asyncio.create_task(
            agent._dispatch(RequestEnvelope("test.block", {}, 1))
        )
        assert await asyncio.to_thread(worker_started.wait, 1)

        reconnect_task = asyncio.create_task(asyncio.to_thread(agent.reconnect))
        await asyncio.sleep(0)
        agent.request_stop()
        close_task = asyncio.create_task(asyncio.to_thread(agent.close))
        for _ in range(cancel_count):
            operation.cancel()
            await asyncio.sleep(0)

        assert calls == [("test.block", {}, device)]
        assert not worker_finished.is_set()
        assert not device_closed.is_set(), "device closed before worker completion"
        assert not close_task.done(), "lifecycle admission was released early"
        assert not reconnect_task.done(), "reconnect passed active admission early"
        assert agent.health()["probe_connected"] is True
        status_task = asyncio.create_task(asyncio.to_thread(agent.status))
        status = await asyncio.wait_for(status_task, timeout=1)
        assert status["device_state"] == "connected"

        worker_release.set()
        if cancel_count:
            with pytest.raises(asyncio.CancelledError):
                await operation
            assert operation.cancelled()
        else:
            assert await operation == {"done": True}
            assert not operation.cancelled()
        reconnect_result = await asyncio.wait_for(reconnect_task, timeout=1)
        await asyncio.wait_for(close_task, timeout=1)
        assert reconnect_result == {
            "connected": False,
            "error": "Agent is stopping",
        }
        assert factory_calls == [True]
        assert worker_finished.is_set()
        assert device_closed.is_set()
        assert early_close == [False]
        await asyncio.sleep(0)
        leftovers = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        assert leftovers == []

    asyncio.run(scenario())


@pytest.mark.parametrize("provider", ["serial", "modbus"])
@pytest.mark.parametrize("failure", ["conversion", "constructor", "open", "close"])
def test_serial_and_modbus_failures_release_lease_and_close_only_owned_object(
    monkeypatch, provider, failure
):
    manager = ResourceManager()
    context = AgentDispatchContext(device=None, resource_manager=manager)
    events = []

    class Provider:
        def __init__(self, port, *, baudrate, timeout):
            events.append("construct")
            if failure == "constructor":
                raise RuntimeError("constructor failed")

        def open(self):
            events.append("open")
            if failure == "open":
                raise RuntimeError("open failed")
            return True

        def close(self):
            events.append("close")
            if failure == "close":
                raise RuntimeError("close failed")

        def write(self, _data):
            events.append("write")

        def read_available(self):
            return b""

        def read_holding_registers(self, _address, _count, _slave):
            return [1]

        read_input_registers = read_holding_registers
        read_coils = read_holding_registers
        read_discrete_inputs = read_holding_registers

    monkeypatch.setattr(
        "mklink.remote.dispatcher.capability_available", lambda _name: True
    )
    if provider == "serial":
        module = types.ModuleType("mklink.serial")
        module.SerialPort = Provider
        module.list_uart_ports = lambda: []
        monkeypatch.setitem(sys.modules, "mklink.serial", module)
        operation = "serial.exchange"
        params = {
            "port": None if failure == "conversion" else "test-port",
            "baudrate": 115200,
            "timeout": 0,
            "data_b64": "",
            "confirm": True,
        }
        resource = ResourceGroup.SERIAL_PORT
    else:
        module = types.ModuleType("mklink.modbus")
        module.ModbusClient = Provider
        module.scan_slaves = lambda *_args, **_kwargs: []
        monkeypatch.setitem(sys.modules, "mklink.modbus", module)
        operation = "modbus.read"
        params = {
            "port": None if failure == "conversion" else "test-port",
            "baudrate": 9600,
            "timeout": 0.1,
            "kind": "holding",
            "address": 0,
            "count": 1,
            "slave": 1,
        }
        resource = ResourceGroup.MODBUS_PORT

    with pytest.raises(Exception):
        dispatch_capability(
            operation,
            params,
            context=context,
            serial_lock=threading.RLock(),
        )
    assert manager.get_status() == {}
    if failure in {"conversion", "constructor"}:
        assert "close" not in events
    else:
        assert events.count("close") == 1

    lease = manager.acquire(resource, "test:next-owner")
    assert lease.owner == "test:next-owner"
    assert manager.release("test:next-owner") == [resource]


def _windows_security_snapshot(root: Path) -> dict[str, tuple[str, bool, str]]:
    if os.name != "nt":
        return {}
    environment = os.environ.copy()
    environment["MKLINK_TEST_ACL_ROOT"] = str(root)
    script = r"""
$ErrorActionPreference = "Stop"
$root = (Get-Item -LiteralPath $env:MKLINK_TEST_ACL_ROOT).FullName
$sidType = [System.Security.Principal.SecurityIdentifier]
$items = @((Get-Item -LiteralPath $root)) + @(
    Get-ChildItem -LiteralPath $root -Force -Recurse
)
$rows = @($items | ForEach-Object {
    $acl = Get-Acl -LiteralPath $_.FullName
    $ownerSid = ([System.Security.Principal.NTAccount]$acl.Owner).Translate($sidType).Value
    $relative = if ($_.FullName -eq $root) {
        "."
    } else {
        $_.FullName.Substring($root.Length).TrimStart("\").Replace("\", "/")
    }
    [pscustomobject]@{
        Relative = $relative
        OwnerSid = $ownerSid
        Protected = [bool]$acl.AreAccessRulesProtected
        Sddl = [string]$acl.Sddl
    }
})
ConvertTo-Json -InputObject @($rows) -Depth 3 -Compress
"""
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr.strip()
    rows = json.loads(completed.stdout)
    if isinstance(rows, dict):
        rows = [rows]
    return {
        row["Relative"]: (
            row["OwnerSid"],
            bool(row["Protected"]),
            row["Sddl"],
        )
        for row in rows
    }


def _tree_snapshot(root: Path):
    security = _windows_security_snapshot(root)
    snapshot = []
    for path in [root, *sorted(root.rglob("*"))]:
        metadata = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        payload = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if stat.S_ISREG(metadata.st_mode)
            else None
        )
        snapshot.append(
            (
                relative,
                stat.S_IFMT(metadata.st_mode),
                stat.S_IMODE(metadata.st_mode),
                getattr(metadata, "st_uid", None),
                getattr(metadata, "st_gid", None),
                metadata.st_size,
                getattr(metadata, "st_file_attributes", None),
                payload,
                security.get(relative),
            )
        )
    return snapshot


def _old_tree_snapshot_projection(snapshot):
    return [row[:-1] for row in snapshot]


def _make_directory_redirect(kind: str, link: Path, target: Path) -> None:
    if kind == "symlink":
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            message = (
                "directory symlink capability could not be established: "
                f"{type(exc).__name__}"
            )
            if os.name == "nt":
                pytest.fail(message)
            pytest.skip(message)
        assert link.is_symlink()
        return
    if os.name != "nt":
        pytest.skip("Windows junction coverage is only applicable on Windows")
    completed = subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            "Windows junction capability could not be established: "
            f"exit {completed.returncode}"
        )
    attributes = getattr(link.lstat(), "st_file_attributes", 0)
    assert attributes & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x00000400
    )


def _remove_directory_redirect(link: Path) -> None:
    if link.is_symlink():
        link.unlink()
    else:
        os.rmdir(link)


@pytest.mark.skipif(os.name != "nt", reason="Windows DACL counterfactual")
def test_windows_security_snapshot_detects_dacl_only_mutation(tmp_path):
    outside = tmp_path / "acl-counterfactual"
    outside.mkdir()
    sentinel = outside / "sentinel.bin"
    sentinel.write_bytes(b"unchanged-bytes")
    before = _tree_snapshot(outside)

    enforce_owner_only_permissions(sentinel)
    after = _tree_snapshot(outside)

    assert _old_tree_snapshot_projection(before) == (
        _old_tree_snapshot_projection(after)
    ), "the pre-fix snapshot projection should miss a DACL-only mutation"
    assert before != after, "owner/protection/SDDL must expose the DACL mutation"


def test_restart_retained_and_active_actual_bytes_enforce_total_quota(tmp_path):
    limits = TransferLimits(
        max_file_bytes=10,
        max_total_bytes=10,
        max_chunk_bytes=10,
        max_active_sessions=4,
        idle_timeout_seconds=30,
    )

    restart_root = tmp_path / "restart"
    pending = restart_root / "pending"
    pending.mkdir(parents=True)
    retained = pending / f".{'a' * 32}.part"
    retained.write_bytes(b"12345678")
    restarted = UploadManager(restart_root, limits=limits)
    with pytest.raises(TransferLimitError):
        restarted.open("blocked.bin", 3)
    exact = restarted.open("exact.bin", 2)
    assert restarted.abort(exact["session_id"])
    assert retained.read_bytes() == b"12345678"
    restarted.close()

    active = UploadManager(tmp_path / "active", limits=limits)
    first = active.open("first.bin", 2)
    parts = list((tmp_path / "active" / "pending").glob("*.part"))
    assert len(parts) == 1
    parts[0].write_bytes(b"12345678")
    with pytest.raises(TransferLimitError):
        active.open("blocked.bin", 3)
    second = active.open("exact.bin", 2)
    assert active.abort(first["session_id"])
    assert active.abort(second["session_id"])
    active.close()


@pytest.mark.parametrize("kind", ["symlink", "junction"])
@pytest.mark.parametrize("controlled", ["root", "pending", "files"])
def test_precreated_controlled_directory_redirect_is_rejected_without_external_io(
    tmp_path, kind, controlled
):
    outside = tmp_path / f"outside-{kind}-{controlled}"
    outside.mkdir()
    (outside / "sentinel.bin").write_bytes(b"outside-sentinel")
    before = _tree_snapshot(outside)
    root = tmp_path / f"uploads-{kind}-{controlled}"
    if controlled != "root":
        root.mkdir()
        redirect = root / controlled
    else:
        redirect = root

    _make_directory_redirect(kind, redirect, outside)
    try:
        with pytest.raises(TransferStateError):
            UploadManager(root)
        assert _tree_snapshot(outside) == before
    finally:
        _remove_directory_redirect(redirect)


_RUNTIME_REDIRECT_ROUTES = [
    ("root", "open"),
    ("pending", "open"),
    ("pending", "chunk"),
    ("pending", "abort"),
    ("pending", "cleanup_idle"),
    ("pending", "close"),
    ("files", "finalize"),
    ("files", "resolve"),
]


def _observe_runtime_redirect(
    tmp_path: Path,
    kind: str,
    controlled: str,
    operation: str,
):
    outside = tmp_path / f"runtime-outside-{kind}-{controlled}"
    outside.mkdir()
    (outside / "sentinel.bin").write_bytes(b"outside-sentinel")
    before = _tree_snapshot(outside)
    root = tmp_path / f"runtime-uploads-{kind}-{controlled}-{operation}"
    manager = UploadManager(root)
    session_id = None
    remote_file = None
    payload = b"x"
    if operation in {
        "chunk",
        "abort",
        "cleanup_idle",
        "close",
        "finalize",
        "resolve",
    }:
        opened = manager.open("fixture.bin", len(payload))
        session_id = opened["session_id"]
    if operation in {"finalize", "resolve"}:
        manager.chunk(session_id, 0, 0, payload)
    if operation == "resolve":
        remote_file = manager.finalize(
            session_id,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
        session_id = None

    original = root if controlled == "root" else root / controlled
    backup = original.with_name(f"{original.name}-original")
    original.rename(backup)
    _make_directory_redirect(kind, original, outside)
    rejected = False
    try:
        try:
            if operation == "open":
                manager.open("blocked.bin", 1)
            elif operation == "chunk":
                manager.chunk(session_id, 0, 0, payload)
            elif operation == "abort":
                manager.abort(session_id)
            elif operation == "cleanup_idle":
                manager.cleanup_idle(now=10**9)
            elif operation == "close":
                manager.close()
            elif operation == "finalize":
                manager.finalize(
                    session_id,
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                )
            else:
                manager.resolve(remote_file)
        except TransferStateError:
            rejected = True
        after = _tree_snapshot(outside)
        return rejected, before, after
    finally:
        _remove_directory_redirect(original)
        backup.rename(original)
        manager.close()


@pytest.mark.parametrize("kind", ["symlink", "junction"])
@pytest.mark.parametrize(
    ("controlled", "operation"),
    _RUNTIME_REDIRECT_ROUTES,
)
def test_runtime_controlled_directory_redirect_is_rejected_without_external_io(
    tmp_path, kind, controlled, operation
):
    rejected, before, after = _observe_runtime_redirect(
        tmp_path, kind, controlled, operation
    )
    assert rejected, f"{controlled}/{operation} did not fail closed"
    assert after == before


def test_abort_path_counterfactual_is_detected_by_runtime_matrix(
    tmp_path, monkeypatch
):
    def unsafe_abort(self, _session_id):
        (self._pending_dir / "outside-mutation.bin").write_bytes(b"mutation")
        return True

    monkeypatch.setattr(UploadManager, "abort", unsafe_abort)
    rejected, before, after = _observe_runtime_redirect(
        tmp_path, "symlink", "pending", "abort"
    )
    assert rejected is False
    assert _old_tree_snapshot_projection(before) != (
        _old_tree_snapshot_projection(after)
    )
    assert before != after
