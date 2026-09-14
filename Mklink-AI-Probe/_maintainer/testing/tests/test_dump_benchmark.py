from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from mklink.dump_benchmark import measure


def run_frames(monkeypatch,frames,size):
    session=Mock()
    session.read_frames.return_value=frames
    session.stats={'parser_crc_errors':0,'parser_dropped_frames':0,'firmware_flagged_frames':0}
    monkeypatch.setattr('mklink.dump_memory.DumpMemoryStreamSession',lambda *a,**k:session)
    ticks=iter([0,.1,2])
    monkeypatch.setattr('mklink.dump_benchmark.time.monotonic',lambda:next(ticks))
    dev=SimpleNamespace(_require_connected=Mock(),set_debug_speed=Mock(),
        _bridge=SimpleNamespace(_ctx=SimpleNamespace(swd_clock_hz=20000000)))
    return dev,session


def test_b1_uses_first_block_time_and_counts_only_complete_samples(monkeypatch):
    frames=[]
    for ts in (0,100000,200000,300000,400000):
        for block in (0,1):
            frames.append({'flags':0,'timestamp_us':ts+block*1000,'regions':[(0,b'x'*2048)],
                           'format':'B1','block_index':block,'block_count':2})
    dev,session=run_frames(monkeypatch,frames,4096)
    r=measure(dev,[(0x90000,4096)],duration=1)
    assert r['samples']==3 and r['sample_hz']==10
    assert r['payload_bytes_per_second']==40960
    session.stop.assert_called_once()


def test_missing_b1_block_stops_and_fails(monkeypatch):
    frames=[{'flags':0,'timestamp_us':0,'regions':[(0,b'x'*2048)],
             'format':'B1','block_index':1,'block_count':2}]
    dev,session=run_frames(monkeypatch,frames,4096)
    with pytest.raises(RuntimeError,match='sequence'): measure(dev,[(0x90000,4096)],duration=1)
    session.stop.assert_called_once()


@pytest.mark.parametrize('kwargs',[{'duration':31},{'duration':float('nan')},{'period':0},{'period':float('inf')}])
def test_invalid_measurement_never_touches_device(kwargs):
    dev=Mock()
    with pytest.raises(ValueError):measure(dev,[(0x90000,4)],**kwargs)
    dev._require_connected.assert_not_called()
    dev.set_debug_speed.assert_not_called()
