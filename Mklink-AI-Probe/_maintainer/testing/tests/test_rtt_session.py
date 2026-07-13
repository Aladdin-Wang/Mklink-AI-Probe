from mklink._types import DeviceState
from mklink.rtt import RTTSession


class StopSensitiveBridge:
    def __init__(self):
        self.state = DeviceState.RTT_STREAM
        self.raw_writes = []
        self.commands = []

    def _exit_stream(self):
        self.state = DeviceState.READY
        return "tail"

    def _write_raw(self, data):
        self.raw_writes.append(data)

    def send_command(self, command, timeout=5.0):
        self.commands.append(command)
        if command == "RTTView.stop()":
            self.state = DeviceState.ERROR
            raise TimeoutError("prompt is unavailable while stopping RTT")
        if self.state is not DeviceState.READY:
            raise ConnectionError("bridge is not immediately reusable")
        return (
            "Find SEGGER RTT addr 0x20000000\n"
            "UpBuffer Channel 0 Size: 1024 Mode: 0\n>>>"
        )

    def _enter_stream(self, state):
        self.state = state


def test_rtt_stop_uses_raw_stop_and_allows_immediate_restart():
    bridge = StopSensitiveBridge()
    session = RTTSession(bridge)
    session._running = True

    assert session.stop() == "tail"
    assert bridge.state is DeviceState.READY
    assert bridge.raw_writes == [b"RTTView.stop()\n"]
    assert "RTTView.stop()" not in bridge.commands

    result = session.start("0x20000000", search_size=1024)
    assert result["control_block_addr"] == "0x20000000"
    assert bridge.state is DeviceState.RTT_STREAM
