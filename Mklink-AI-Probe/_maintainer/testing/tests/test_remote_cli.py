"""Engineer-side remote CLI contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mklink.remote import cli


class _Client:
    def __init__(self):
        self.calls = []
        self.results = {}
        self.uploads = []

    def supports(self, _capability):
        return True

    def call(self, operation, **params):
        self.calls.append((operation, params))
        return self.results.get(operation, {"ok": True})

    def upload(self, path):
        self.uploads.append(Path(path))
        return SimpleNamespace(reference="remote-file:test-firmware")


class _Registry:
    def __init__(self):
        self.client_calls = []
        self.client_instance = _Client()

    def client(self, site, *, project_root):
        self.client_calls.append((site, Path(project_root)))
        return self.client_instance


def test_help_identifies_supported_lan_transports_and_high_risk_confirmation(capsys):
    parser = cli.build_parser()
    assert "direct LAN/VPN" in parser.description
    assert "in-process LAN STCP" in parser.description
    assert "no frpc executable" in parser.description

    with pytest.raises(SystemExit) as help_exit:
        parser.parse_args(["call", "--help"])
    assert help_exit.value.code == 0
    call_help = capsys.readouterr().out
    assert "high-risk" in call_help
    assert "--yes" in call_help

    with pytest.raises(SystemExit):
        parser.parse_args(["flash", "firmware.bin"])
    with pytest.raises(SystemExit):
        parser.parse_args(["stop-agent"])


def test_named_site_and_project_pointer_are_used_for_public_client_routing(
    monkeypatch, tmp_path, capsys
):
    registry = _Registry()
    monkeypatch.setattr("mklink.remote.sites.default_registry", lambda: registry)
    monkeypatch.setattr("mklink.remote.sites.close_all", lambda: None)

    result = cli.main(
        ["--site", "field-bench", "--project-root", str(tmp_path), "status"]
    )

    assert result == 0
    assert registry.client_calls == [("field-bench", tmp_path)]
    assert registry.client_instance.calls == [("agent.status", {})]
    assert '"ok": true' in capsys.readouterr().out


def test_generic_high_risk_call_is_rejected_locally_without_yes(
    monkeypatch, tmp_path, capsys
):
    registry = _Registry()
    monkeypatch.setattr("mklink.remote.sites.default_registry", lambda: registry)
    monkeypatch.setattr("mklink.remote.sites.close_all", lambda: None)

    result = cli.main(
        [
            "--site",
            "field-bench",
            "--project-root",
            str(tmp_path),
            "call",
            "memory.write",
            "--params",
            '{"address": 536870912, "data_b64": "AA=="}',
        ]
    )

    assert result == 2
    assert registry.client_instance.calls == []
    assert "operation failed" in capsys.readouterr().err


def test_generic_high_risk_call_adds_confirmation_only_after_yes(
    monkeypatch, tmp_path
):
    registry = _Registry()
    monkeypatch.setattr("mklink.remote.sites.default_registry", lambda: registry)
    monkeypatch.setattr("mklink.remote.sites.close_all", lambda: None)

    result = cli.main(
        [
            "--site",
            "field-bench",
            "--project-root",
            str(tmp_path),
            "call",
            "memory.write",
            "--params",
            '{"address": 536870912, "data_b64": "AA=="}',
            "--yes",
        ]
    )

    assert result == 0
    assert registry.client_instance.calls == [
        (
            "memory.write",
            {"address": 536870912, "data_b64": "AA==", "confirm": True},
        )
    ]


def test_dedicated_flash_returns_nonzero_for_terminal_failure(
    monkeypatch, tmp_path, capsys
):
    registry = _Registry()
    registry.client_instance.results["flash.program"] = {
        "state": "failed",
        "result": {"code": -32003, "message": "Agent operation failed"},
    }
    monkeypatch.setattr("mklink.remote.sites.default_registry", lambda: registry)
    monkeypatch.setattr("mklink.remote.sites.close_all", lambda: None)
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"fixture")

    result = cli.main(
        ["--site", "field-bench", "flash", str(firmware), "--yes"]
    )

    assert result == 2
    assert registry.client_instance.uploads == [firmware]
    assert registry.client_instance.calls == [
        (
            "flash.program",
            {
                "firmware": "remote-file:test-firmware",
                "confirm": True,
                "verify": True,
                "reset_after": True,
            },
        )
    ]
    assert '"state": "failed"' in capsys.readouterr().out


def test_generic_flash_call_returns_nonzero_for_completion_unknown(
    monkeypatch, tmp_path, capsys
):
    registry = _Registry()
    registry.client_instance.results["flash.program"] = {
        "state": "completion-unknown",
        "result": None,
    }
    monkeypatch.setattr("mklink.remote.sites.default_registry", lambda: registry)
    monkeypatch.setattr("mklink.remote.sites.close_all", lambda: None)

    result = cli.main(
        [
            "--site",
            "field-bench",
            "--project-root",
            str(tmp_path),
            "call",
            "flash.program",
            "--params",
            '{"firmware": "remote-file:test-firmware"}',
            "--yes",
        ]
    )

    assert result == 2
    assert '"state": "completion-unknown"' in capsys.readouterr().out
