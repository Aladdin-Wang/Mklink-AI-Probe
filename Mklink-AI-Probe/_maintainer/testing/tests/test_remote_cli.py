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


def test_packaged_entry_routes_only_runtime_serve_to_existing_backend(monkeypatch, tmp_path):
    from mklink.remote import package_agent
    calls = []
    monkeypatch.setattr('mklink.runtime.serve_runtime', lambda **kwargs: calls.append(kwargs))
    assert package_agent.main(['runtime', 'serve', '--project-root', str(tmp_path),
                               '--port', '0', '--probe-id', 'lobby']) == 0
    assert calls == [{'project_root': str(tmp_path), 'port': 0, 'probe_id': 'lobby'}]


def test_packaged_runtime_entry_keeps_direct_secret_rejection(capsys):
    import pytest
    from mklink.remote import package_agent
    with pytest.raises(SystemExit) as result:
        package_agent.main(['runtime', 'serve', '--token', 'must-not-be-echoed'])
    assert result.value.code == 2
    captured = capsys.readouterr()
    assert 'must-not-be-echoed' not in captured.out + captured.err
    assert 'direct token values are not supported' in captured.err

@pytest.mark.parametrize('command', ['connect', 'reconnect'])
def test_explicit_connect_and_reconnect_keep_distinct_semantics(monkeypatch, command):
    registry = _Registry()
    monkeypatch.setattr('mklink.remote.sites.default_registry', lambda: registry)
    monkeypatch.setattr('mklink.remote.sites.close_all', lambda: None)
    assert cli.main(['--site', 'field-bench', command]) == 0
    assert registry.client_instance.calls == [('agent.' + command, {})]

@pytest.mark.parametrize('arguments', [
    ['--channels',''], ['--channels','0,0'], ['--channels','8'], ['--channels','-1'],
    ['--channels','0,true'], ['--duration','nan'], ['--duration','inf'],
    ['--duration','0'], ['--duration','-1'], ['--addr','0x20000000'],
])
def test_rtt_invalid_cli_parameters_never_connect(monkeypatch, arguments):
    monkeypatch.setattr(cli, '_client', lambda _: pytest.fail('Invalid command connected'))
    with pytest.raises(SystemExit) as result:
        cli.main(['rtt', *arguments])
    assert result.value.code == 2


@pytest.mark.parametrize('failure', [None, 'read', 'interrupt'])
def test_rtt_cli_keeps_cursors_and_releases_connection_on_every_exit(monkeypatch, capsys, failure):
    import json
    calls, closed = [], []
    clock = [0.0]
    class Client:
        def supports(self, capability):return capability == 'stream.rtt'
        def call(self, operation, **params):
            calls.append((operation, params))
            if operation == 'agent.connect':return {'connected': True}
            if operation == 'rtt.start':return {'session':'one', 'reused':True}
            if failure == 'interrupt':raise KeyboardInterrupt()
            if failure == 'read':raise RuntimeError('lost response')
            return {'channel':params['channel'], 'cursor':params['cursor']+3,
                    'session':'one', 'data_hex':'00ff80','lost_bytes':5}
    monkeypatch.setattr(cli, '_client', lambda _: Client())
    monkeypatch.setattr('mklink.remote.sites.close_all', lambda: closed.append(True))
    monkeypatch.setattr(cli.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(cli.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    result=cli.main(['rtt','--channels','0,7','--duration','0.1'])
    assert result == {None:0, 'read':2, 'interrupt':130}[failure]
    assert closed == [True]
    assert calls[:2] == [('agent.connect',{}),('rtt.start',{})]
    reads=[params for op,params in calls if op == 'rtt.read_channel']
    if failure:
        assert reads == [{'channel':0,'cursor':0}]
    else:
        assert reads == [{'channel':0,'cursor':0},{'channel':7,'cursor':0},
                         {'channel':0,'cursor':3},{'channel':7,'cursor':3}]
        pages=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert len(pages)==5
        assert all(p['lost_bytes']==5 and p['data_hex']=='00ff80' for p in pages[1:])
