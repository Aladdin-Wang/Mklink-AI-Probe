from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from mklink.flash import MKLinkFlash, FlashError

@pytest.mark.parametrize('reply', ['cmd.set_swd_clock(4000000)\r\n-1', 'set clock 1000000\r\n0', ''])
def test_rejected_clock_does_not_update_known_clock(reply):
    bridge = SimpleNamespace(send_command=Mock(return_value=reply), _ctx=SimpleNamespace(swd_clock_hz=1000000))
    with pytest.raises(FlashError, match='acknowledge'):
        MKLinkFlash(bridge).set_swd_clock(4000000)
    assert bridge._ctx.swd_clock_hz == 1000000
