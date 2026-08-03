from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mklink.remote import cli, package_agent
from mklink.remote.stcp import (
    STCPProviderConfig,
    STCPSession,
    STCPVisitorConfig,
)


COMMON = {
    "server_addr": "192.0.2.10",
    "server_port": 7000,
    "auth_token": "frps-auth",
    "proxy_name": "mklink-field-a",
    "secret_key": "stcp-secret",
    "user": "field-a",
}


class FakeBridge:
    def __init__(self) -> None:
        self.payload = None
        self.stopped = []

    def start(self, payload):
        self.payload = json.loads(json.dumps(payload))
        return 42

    def status(self, handle):
        assert handle == 42
        return {"state": "ready", "ready": True, "mode": self.payload["mode"]}

    def stop(self, handle):
        self.stopped.append(handle)
        return True


def test_provider_keeps_secrets_out_of_repr_and_targets_loopback() -> None:
    config = STCPProviderConfig(**COMMON, local_port=8766)

    rendered = repr(config)
    assert "frps-auth" not in rendered
    assert "stcp-secret" not in rendered
    assert config.as_native_payload()["local_addr"] == "127.0.0.1"


@pytest.mark.parametrize("address", ["0.0.0.0", "192.0.2.20", "localhost"])
def test_provider_rejects_non_ip_or_non_loopback_backend(address: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        STCPProviderConfig(**COMMON, local_addr=address, local_port=8766)


@pytest.mark.parametrize("address", ["0.0.0.0", "192.0.2.20", "localhost"])
def test_visitor_rejects_non_ip_or_non_loopback_bind(address: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        STCPVisitorConfig(**COMMON, bind_addr=address, bind_port=8767)


def test_session_owns_in_process_bridge_lifecycle() -> None:
    bridge = FakeBridge()
    session = STCPSession(
        STCPVisitorConfig(**COMMON, bind_port=8767),
        bridge=bridge,
    )

    assert session.start() == {"state": "ready", "ready": True, "mode": "visitor"}
    assert bridge.payload["bind_addr"] == "127.0.0.1"
    assert session.running

    session.close()
    session.close()

    assert not session.running
    assert bridge.stopped == [42]


def _agent_arguments(**overrides):
    values = {
        "transport": "lan-stcp",
        "host": "127.0.0.1",
        "port": 8766,
        "stcp_server_addr": "192.0.2.10",
        "stcp_server_port": 7000,
        "stcp_user": "field-a",
        "stcp_proxy_name": "mklink-field-a",
        "stcp_auth_token_env": "TEST_FRP_TOKEN",
        "stcp_auth_token_file": None,
        "stcp_secret_env": "TEST_STCP_SECRET",
        "stcp_secret_file": None,
        "stcp_library": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "factory",
    [cli._agent_stcp_session, package_agent._stcp_session],
)
def test_field_session_keeps_three_security_layers_distinct(
    monkeypatch, factory
) -> None:
    monkeypatch.setenv("TEST_FRP_TOKEN", "frps-auth")
    monkeypatch.setenv("TEST_STCP_SECRET", "stcp-secret")

    class FakeSession:
        def __init__(self, config, *, library):
            self.config = config
            self.library = library

    monkeypatch.setattr("mklink.remote.stcp.STCPSession", FakeSession)
    session = factory(_agent_arguments(), "site-agent-token")

    assert session.config.local_addr == "127.0.0.1"
    assert session.config.local_port == 8766
    assert session.config.auth_token == "frps-auth"
    assert session.config.secret_key == "stcp-secret"

    monkeypatch.setenv("TEST_STCP_SECRET", "frps-auth")
    with pytest.raises(ValueError, match="must be distinct"):
        factory(_agent_arguments(), "site-agent-token")


def test_stcp_secret_values_are_rejected_from_command_line_without_echo(
    capsys,
) -> None:
    sentinel = "must-not-be-echoed"
    with pytest.raises(SystemExit) as exit_info:
        cli.build_parser().parse_args(
            [
                "stcp",
                "visitor",
                "--server-addr",
                "192.0.2.10",
                "--proxy-name",
                "mklink-field-a",
                "--bind-port",
                "8767",
                f"--stcp-secret={sentinel}",
            ]
        )

    assert exit_info.value.code == 2
    error = capsys.readouterr().err
    assert sentinel not in error
    assert "environment or file option" in error


def test_engineer_visitor_runs_in_process_and_stops_cleanly(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("TEST_FRP_TOKEN", "frps-auth")
    monkeypatch.setenv("TEST_STCP_SECRET", "stcp-secret")
    observed = {}

    class FakeSession:
        def __init__(self, config, *, library):
            observed["config"] = config
            observed["library"] = library
            observed["closed"] = False

        def start(self):
            return {"state": "ready", "ready": True, "mode": "visitor"}

        def close(self):
            observed["closed"] = True

    monkeypatch.setattr("mklink.remote.stcp.STCPSession", FakeSession)
    monkeypatch.setattr(
        cli.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    args = cli.build_parser().parse_args(
        [
            "stcp",
            "visitor",
            "--server-addr",
            "192.0.2.10",
            "--proxy-name",
            "mklink-field-a",
            "--bind-port",
            "8767",
            "--stcp-auth-token-env",
            "TEST_FRP_TOKEN",
            "--stcp-secret-env",
            "TEST_STCP_SECRET",
        ]
    )

    assert cli._run_stcp_visitor(args) == 130
    assert observed["config"].bind_addr == "127.0.0.1"
    assert observed["closed"] is True
    output = capsys.readouterr().out
    assert '"url": "ws://127.0.0.1:8767"' in output
    assert "frps-auth" not in output
    assert "stcp-secret" not in output
