from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mklink._types import DeviceState
from mklink.debug_speed import apply_profile, profile_clock


def device(ident=0x1000563D, response='JTAG profile=20000000 scans=1', state=DeviceState.READY):
    return SimpleNamespace(_require_connected=Mock(), state=state, idcode=ident,
        _bridge=SimpleNamespace(state=state, idcode=ident, send_command=Mock(side_effect=lambda cmd: "set clock 1000000" if cmd == "cmd.set_swd_clock(1000000)" else response), _ctx=SimpleNamespace(swd_clock_hz=0)))


@pytest.mark.parametrize('name,hz', [('low',4000000),('medium',10000000),('high',20000000),('ultra',30000000)])
def test_qualified_profile(name,hz):
    d=device(response=f'JTAG profile={hz} scans=1')
    r=apply_profile(d,name)
    assert r['clock_hz']==hz and r['profile_confirmed']
    assert 'not identified by IDCODE' in r['qualification']
    assert 'HPM5301' not in r['qualification']
    d._bridge.send_command.assert_called_once_with(f'cmd.set_swd_clock({hz})')


def test_old_firmware_restores_conservative_clock():
    d=device(response='set clock 20000000\nJTAG profile=0 scans=1')
    with pytest.raises(ValueError,match='restored 1 MHz'): apply_profile(d,'high')
    assert d._bridge._ctx.swd_clock_hz==1000000
    assert d._bridge.send_command.call_args.args==('cmd.set_swd_clock(1000000)',)


def test_deferred_connection_can_confirm_jtag_before_target_id_is_known():
    d = device(ident=0, response='set clock 20000000\nJTAG profile=20000000')
    result = apply_profile(d, 'high')
    assert result['profile_confirmed'] and result['interface'] == 'JTAG'
    assert d._bridge._ctx.swd_clock_hz == 20000000


def test_unconfirmed_fallback_is_not_reported_as_a_safe_clock():
    from mklink.debug_speed import ClockProfileUnavailable
    d = device(response='unsupported')
    d._bridge.send_command.side_effect = ['unsupported', 'target busy']
    with pytest.raises(ValueError, match='fallback clock') as failure:
        apply_profile(d, 'high')
    assert not isinstance(failure.value, ClockProfileUnavailable)
    assert d._bridge._ctx.swd_clock_hz == 0


@pytest.mark.parametrize('profile,hz', [('low',4000000),('medium',10000000),('high',20000000),('ultra',30000000)])
def test_swd_exact_profile_ack(profile,hz):
    d=device(ident=0x1BA01477,response=f'set clock {hz}\nSWD profile={hz}')
    result=apply_profile(d,profile)
    assert result['profile_confirmed'] and result['interface']=='SWD'
    assert 'not identified by IDCODE' in result['qualification']


@pytest.mark.parametrize('response', ['SWD profile=4000000','SWD high speed not qualified; clock unchanged',''])
def test_swd_mismatch_or_rejection_does_not_update_requested_clock(response):
    d=device(ident=0x1BA01477,response=response)
    with pytest.raises(ValueError,match='restored 1 MHz'):
        apply_profile(d,'medium')
    assert d._bridge._ctx.swd_clock_hz==1000000


def test_legacy_swd_remains_explicitly_unconfirmed():
    d=device(ident=0x1BA01477,response='set clock 10000000')
    assert not apply_profile(d,'medium')['profile_confirmed']


@pytest.mark.parametrize('profile,hz', [('low', 4000000), ('medium', 10000000), ('high', 20000000), ('ultra', 30000000)])
@pytest.mark.parametrize('ident', [0, 0xffffffff, 0x1BA01477, 0x1000563D])
def test_probe_clock_setting_does_not_require_target_or_profile_ack(profile, hz, ident):
    d = device(ident=ident, response=(f'set clock {hz}\n'
        f'SWD requested={hz} transfers=10 wait=0 fault=0 error=0 invalid=10 exhausted=0'))
    result = apply_profile(d, profile)
    assert result['clock_hz'] == hz and not result['profile_confirmed']
    assert 'target timing not verified' in result['qualification']
    assert d._bridge._ctx.swd_clock_hz == hz
    d._bridge.send_command.assert_called_once_with(f'cmd.set_swd_clock({hz})')


def test_device_reports_fallback_clock_and_clears_warning_after_success():
    from mklink.device import Device
    from mklink.debug_speed import ClockProfileUnavailable
    dev = Device()
    dev._connected = True
    dev._bridge = device(ident=0x1BA01477, response='SWD profile=0')._bridge
    with pytest.raises(ClockProfileUnavailable):
        dev.set_debug_speed('high')
    assert dev.clock_hz == 1_000_000
    assert 'restored 1 MHz' in dev.clock_warning
    dev._bridge.send_command.side_effect = lambda cmd: 'set clock 20000000\nSWD profile=20000000'
    dev.set_debug_speed('high')
    assert dev.clock_hz == 20_000_000 and dev.clock_warning is None
    dev._bridge._ctx.swd_clock_hz = 0
    assert dev.clock_hz is None


@pytest.mark.parametrize('profile', ['high', 'ultra'])
@pytest.mark.parametrize('ident', [0x1BA01477, 0x12345678])
def test_explicit_profile_mismatch_is_not_silently_mislabeled(profile,ident):
    d=device(ident=ident, response='SWD profile=0')
    with pytest.raises(ValueError,match='restored 1 MHz'): apply_profile(d,profile)
    assert d._bridge._ctx.swd_clock_hz == 1000000
    assert d._bridge.send_command.call_args.args == ('cmd.set_swd_clock(1000000)',)


@pytest.mark.parametrize('profile', ['high', 'ultra'])
def test_live_stream_is_not_interrupted_by_raw_command(profile):
    d=device(state=DeviceState.DUMP_STREAM)
    with pytest.raises(ValueError,match='Stop'): apply_profile(d,profile)
    d._bridge.send_command.assert_not_called()


@pytest.mark.parametrize('response', ['cmd.set_swd_clock(30000000)\n0', 'SWD requested=30000000', 'set clock 300000000', 'set clock 30000000\n-1', 'JTAG profile=0', 'JTAG profile=20000000'])
def test_ultra_rejects_missing_setting_ack_or_explicit_failure(response):
    d=device(response=response)
    with pytest.raises(ValueError,match='restored 1 MHz'): apply_profile(d,'ultra')
    assert d._bridge._ctx.swd_clock_hz == 1000000
    assert d._bridge.send_command.call_args.args == ('cmd.set_swd_clock(1000000)',)


@pytest.mark.parametrize('profile', ['20M','fast',None,20,{},''])
def test_invalid_profile(profile):
    with pytest.raises(ValueError): profile_clock(profile)


def test_real_mcp_ultra_dispatch_preserves_profile_and_result(monkeypatch):
    import asyncio
    fastmcp=pytest.importorskip('fastmcp')
    from mklink import mcp_server
    expected={'profile':'ultra','clock_hz':30000000,'profile_confirmed':True}
    setter=Mock(return_value=expected)
    monkeypatch.setattr(mcp_server,'_connected_device',lambda:SimpleNamespace(set_debug_speed=setter))
    async def exchange():
        async with fastmcp.Client(mcp_server.build_server()) as client:
            tools=await client.list_tools()
            tool=next(t for t in tools if t.name=='set_debug_speed')
            assert 'ultra=30 MHz' in tool.description
            result=await client.call_tool('set_debug_speed',{'profile':'ultra'})
            return result.data
    assert asyncio.run(exchange())==expected
    setter.assert_called_once_with('ultra')
