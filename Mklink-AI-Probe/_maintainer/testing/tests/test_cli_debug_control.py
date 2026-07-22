from types import SimpleNamespace

import pytest

import mklink.cli as cli
from mklink.debug_control import DebugState


class _Bridge:
    instances = []

    def __init__(self, port):
        self.port = port
        self.closed = False
        self.__class__.instances.append(self)

    def connect(self):
        return True

    def close(self):
        self.closed = True


@pytest.fixture
def debug_cli(monkeypatch):
    resolved = []
    _Bridge.instances = []
    monkeypatch.setattr(cli, "_resolve_port", lambda port: resolved.append(port) or "COM_TEST")
    monkeypatch.setattr(cli, "_init_target_bridge", lambda bridge: None)
    monkeypatch.setattr("mklink.bridge.MKLinkSerialBridge", _Bridge)
    monkeypatch.setattr(
        "mklink.debug_control.halt_cpu",
        lambda bridge: DebugState(halted=True, dhcsr_raw=0x00020003),
    )
    monkeypatch.setattr(
        "mklink.debug_control.resume_cpu",
        lambda bridge: DebugState(halted=False, dhcsr_raw=0x00000001),
    )
    monkeypatch.setattr(
        "mklink.debug_control.step_cpu",
        lambda bridge: DebugState(halted=True, dhcsr_raw=0x00020003),
    )
    monkeypatch.setattr(
        "mklink.debug_control.read_debug_state",
        lambda bridge: DebugState(halted=False, dhcsr_raw=0x00000001, num_breakpoints=6),
    )
    return resolved


@pytest.mark.parametrize(
    "invoke",
    [
        lambda: cli._cli_halt(None),
        lambda: cli._cli_resume(None),
        lambda: cli._cli_step(None),
        lambda: cli._cli_break(SimpleNamespace(port=None, status=True)),
    ],
    ids=("halt", "resume", "step", "break-status"),
)
def test_debug_cli_commands_use_shared_port_resolver(debug_cli, invoke):
    invoke()

    assert debug_cli == [None]
    assert len(_Bridge.instances) == 1
    assert _Bridge.instances[0].port == "COM_TEST"
    assert _Bridge.instances[0].closed is True
