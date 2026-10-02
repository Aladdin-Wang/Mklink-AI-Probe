import pytest

from mklink.offline_security import offline_security_capability, resolve_offline_security
from mklink.offline_download import _security_lines


def test_recovery_has_no_power_or_option_algorithm_and_is_unlock_only():
    capability = offline_security_capability('V4', 'nRF54L15')
    assert capability['unlock_supported']
    assert not capability['lock_supported']
    assert capability['voltage_options_mv'] == []
    plan = resolve_offline_security({'unlock_before_download': True},
                                    model='V4', part_number='nRF54L15')
    assert plan.algorithm_path is None
    assert plan.unlock_config == (b'format=mklink-ctrl-ap-recover-v1\n'
        b'targetid=0x001c0289\nctrl_ap_idr=0x32880000\n'
        b'partid_addr=0x00ffc31c\npartid=0x00054b15\n'
        b'action=unlock\nerase_all=1\n')
    script = '\n'.join(_security_lines(plan, action='unlock', indent='    '))
    assert 'load.flm' not in script
    assert 'cmd.unlock("Python/CFG/nRF54L15/unlock.cfg")' in script
    assert 'if security_unlock_rc != 0:' in script
    assert 'abort = True' in script


def test_catalog_alias_exposes_ctrl_ap_unlock():
    capability = offline_security_capability('V4', 'nrf54l')
    assert capability['part_number'] == 'nRF54L15'
    assert capability['unlock_supported']
    assert not capability['lock_supported']


@pytest.mark.parametrize('model,part,payload', [
    ('V3', 'nRF54L15', {'unlock_before_download': True}),
    ('V4', 'nRF54L10', {'unlock_before_download': True}),
    ('V4', 'nRF54L15', {'lock_after_download': True}),
])
def test_unsupported_recovery_actions_fail_closed(model, part, payload):
    with pytest.raises(ValueError):
        resolve_offline_security(payload, model=model, part_number=part)


def test_default_does_not_recover_or_erase():
    assert resolve_offline_security({}, model='V4', part_number='nRF54L15') is None
