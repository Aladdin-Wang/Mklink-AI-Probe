from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from mklink._types import DeviceState
from mklink.flash import MKLinkFlash, FlashError
from mklink.remote.online_flash_api import JobBody, ReadMemoryBody


@pytest.mark.parametrize('hz', [1, 1_000_000, 4_000_000, 10_000_000, 20_000_000, 30_000_000])
def test_online_entrypoints_accept_supported_clocks(hz):
    assert JobBody(actions=['connect'], frequency=hz).frequency == hz
    assert ReadMemoryBody(address=0, size=4, target_part='STM32F103RE', frequency=hz).frequency == hz


@pytest.mark.parametrize('hz', [0, -1, True, 1.5, 10_000_001, 25_000_000, 30_000_001])
def test_online_entrypoints_reject_unsupported_clocks(hz):
    with pytest.raises(ValueError):
        JobBody(actions=['connect'], frequency=hz)
    with pytest.raises(ValueError):
        ReadMemoryBody(address=0, size=4, target_part='STM32F103RE', frequency=hz)


@pytest.mark.parametrize('hz', [20_000_000, 30_000_000])
@pytest.mark.parametrize('hpm', [False, True])
def test_flash_requires_exact_high_profile_ack(hz, hpm):
    interface = 'JTAG' if hpm else 'SWD'
    bridge = SimpleNamespace(state=DeviceState.READY, idcode=0x1000563D if hpm else 0x1BA01477,
        send_command=Mock(return_value=f'set clock {hz}\n{interface} profile={hz}\n'),
        _ctx=SimpleNamespace(swd_clock_hz=1_000_000))
    MKLinkFlash(bridge).set_swd_clock(hz)
    assert bridge._ctx.swd_clock_hz == hz
    bridge.send_command.return_value = f'set clock {hz}\n'
    with pytest.raises(FlashError, match='restored 1 MHz'):
        MKLinkFlash(bridge).set_swd_clock(hz)
    assert bridge._ctx.swd_clock_hz == 1_000_000
