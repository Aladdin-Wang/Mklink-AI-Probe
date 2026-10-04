"""Idle framing follows receive gaps, never GUI/CLI consumer scheduling."""
import csv
import json
import threading
import time
import pytest
from mklink.serial._frame import FrameParser
from mklink.serial._capture import SerialCapture
from mklink.serial._logger import FileLogger
from mklink.remote.serial_stream import SerialByteBatcher, SerialHistory
from mklink.remote.dashboards import SerialStreamManager
from test_serial_automation import ports, wait_for


def profile():
    return {'name':'Idle','version':'1','frame':{'header':'AA'},
            'fields':[{'name':'value','offset':1,'size':1,'type':'uint8'}]}


def test_gap_emits_old_frame_before_adding_next_and_polls_do_not_extend_gap():
    parser = FrameParser(profile())
    assert parser.feed(b'\xaa\x01', monotonic_time=0) == []
    for tick in (.01, .02, .03, .04):
        assert parser.feed(b'', monotonic_time=tick) == []
    assert [f.raw for f in parser.feed(b'\xaa\x02', monotonic_time=.1)] == [b'\xaa\x01']
    assert parser.feed(b'', monotonic_time=.14) == []
    result = parser.feed(b'', monotonic_time=.16)
    assert [f.raw for f in result] == [b'\xaa\x02']
    assert result[0].fields['value']['value'] == 2
    assert parser.feed(b'', monotonic_time=1) == []


def test_batch_span_and_idle_flush_before_buffer_limit():
    parser = FrameParser(profile(), max_buffer_bytes=8)
    assert parser.feed(b'\xaa1234567', monotonic_time=0, end_time=.04) == []
    assert parser.feed(b'', monotonic_time=.08) == []
    assert [f.raw for f in parser.feed(b'\xaa1234567', monotonic_time=.1)] == [b'\xaa1234567']


def test_wall_clock_changes_do_not_change_idle_gap(monkeypatch):
    parser = FrameParser(profile())
    monkeypatch.setattr('mklink.serial._frame.time.time', lambda: 1e9)
    parser.feed(b'\xaa\x01', monotonic_time=1)
    monkeypatch.setattr('mklink.serial._frame.time.time', lambda: 0)
    assert parser.feed(b'', monotonic_time=1.04) == []
    assert parser.feed(b'', monotonic_time=1.06)[0].raw == b'\xaa\x01'


@pytest.mark.parametrize('framing', [{'header':'AA','tail':'FF'},
    {'header':'AA','length_field':{'offset':1,'size':1,'includes_header':True}}])
def test_delimited_partial_frames_are_not_flushed_by_idle(framing):
    parser = FrameParser({'frame':framing})
    parser.feed(b'\xaa', monotonic_time=1)
    assert parser.feed(b'', monotonic_time=100) == []
    rest = b'\x01\xff' if 'tail' in framing else b'\x03\x01'
    assert parser.feed(rest, monotonic_time=101)[0].raw == b'\xaa'+rest


def test_partial_idle_header_is_discarded_without_inventing_frame():
    parser = FrameParser({'frame':{'header':'AA BB'}})
    parser.feed(b'\xaa', monotonic_time=1)
    assert parser.feed(b'', monotonic_time=1.1) == []
    assert parser.feed(b'\xbb', monotonic_time=1.2) == []
    assert parser.feed(b'', monotonic_time=2) == []


def test_profile_without_frame_uses_lines_and_idle():
    parser = FrameParser({'name':'Text','version':'1'})
    assert [f.raw for f in parser.feed(b'a\nb', monotonic_time=1)] == [b'a']
    assert parser.feed(b'', monotonic_time=1.06)[0].raw == b'b'
    parser.feed(b'old', monotonic_time=2); parser.reset()
    assert parser.feed(b'', monotonic_time=3) == []


def test_batcher_preserves_receive_gaps_when_flush_thread_cannot_run():
    history = SerialHistory(); initial = history.read()
    def publish(data, direction, port, first, last):
        history.append(data, direction, port, first_time=first, last_time=last)
    batcher = SerialByteBatcher(publish)
    # Deliberately never start the timer: producer gap detection must suffice.
    batcher.feed(b'\xaa', 'RX', 'A', monotonic_time=1)
    batcher.feed(b'\x01', 'RX', 'A', monotonic_time=1.01)
    batcher.feed(b'\xaa\x02', 'RX', 'A', monotonic_time=1.11)
    batcher.close()
    entries = history.read(initial['session'], 0)['entries']
    assert [(e['hex'],e['first_monotonic'],e['last_monotonic']) for e in entries] == [
        ('aa01',1,1.01),('aa02',1.11,1.11)]


def test_capture_backlog_uses_receive_gaps_and_idle_annotations_do_not_repeat_bytes(tmp_path):
    history = SerialHistory()
    class Client:
        def call(self, capability, args=None):
            args = args or {}
            return {**history.read(args.get('session'), args.get('after'), args.get('limit',256)),
                    'running':True,'ports':{'A':'open'},'idle_cutoffs':{'A':1.3}}
    path = tmp_path/'idle.csv'
    with FileLogger(str(path), 'csv') as logger:
        capture = SerialCapture(Client(), {'A':FrameParser(profile())}, logger)
        history.append(b'\xaa\x01','RX','A',first_time=1,last_time=1)
        history.append(b'\xaa\x02','RX','A',first_time=1.1,last_time=1.1)
        capture.page(); capture.page()
    with path.open(encoding='utf-8',newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert ''.join(row['raw_hex'] for row in rows) == 'AA01AA02'
    frames = [f['raw_hex'] for row in rows for f in json.loads(row['decoded_json'] or '[]')]
    assert frames == ['aa01','aa02']
    assert [(r['direction'],r['raw_hex']) for r in rows] == [('RX','AA01'),('RX','AA02'),('PARSED','')]


def test_idle_manager_parses_each_port_without_more_input_and_does_not_duplicate_history(ports):
    manager = SerialStreamManager(); manager.start([{'port':'A'},{'port':'B'}],profile=profile())
    initial = manager.get_history()
    try:
        a,b = ports.instances[-2:]
        a.rx.put(b'\xaa\x01'); b.rx.put(b'\xaa\x02')
        wait_for(lambda:len(manager.get_status()['latest_frames']) == 2)
        result = manager.get_status()['latest_frames']
        assert result['A']['fields']['value']['value'] == 1
        assert result['B']['fields']['value']['value'] == 2
        time.sleep(.08)
        assert manager.get_status()['latest_frames'] == result
        manager.stop()
        history = manager.get_history(initial['session'], initial['next_seq'])
        assert sum(e['size'] for e in history['entries']) == 4
        assert not manager.worker_alive
    finally: manager.stop()


def test_capture_does_not_idle_flush_while_history_pages_are_still_pending():
    class Client:
        def call(self, capability, args=None):
            after = args['after'] if args else 2
            data = {0:'aa01',1:'aa02'}.get(after)
            entries = [dict(seq=after+1,port='A',direction='RX',hex=data,timestamp_ns=1,
                            first_monotonic=1+after*.02,last_monotonic=1+after*.02)] if data else []
            return dict(session='one',next_seq=0,latest_seq=2,entries=entries,
                        idle_cutoffs={'A':2},running=True,ports={'A':'open'},dropped_batches=0)
    class Sink:
        frames = []
        def log(self,*args,frames,**kw): self.frames.extend(frames)
    sink = Sink(); capture = SerialCapture(Client(),{'A':FrameParser(profile())},sink)
    capture.page()
    assert sink.frames == []
    capture.page()
    assert [f['raw_hex'] for f in sink.frames] == ['aa01aa02']


def test_per_port_completed_reader_cutoff_prevents_premature_idle_during_inflight_chunk():
    history = SerialHistory(); cutoffs = {'A':1.02,'B':2.}
    class Client:
        def call(self, capability, args=None):
            return {**history.read(**(args or {})), 'idle_cutoffs':dict(cutoffs),
                    'running':True,'ports':{'A':'open','B':'open'}}
    class Sink:
        frames = []
        def log(self,direction,port,data,*,frames,**kw):
            self.frames.extend((port,f['raw_hex']) for f in frames)
    sink = Sink(); capture = SerialCapture(Client(),{p:FrameParser(profile()) for p in ('A','B')},sink)
    for port in ('A','B'): history.append(b'\xaa\x01','RX',port,first_time=1,last_time=1)
    capture.page()
    assert sink.frames == [('B','aa01')]
    # A's reader sampled this earlier but had not completed/published it at the query.
    history.append(b'\x02','RX','A',first_time=1.03,last_time=1.03)
    cutoffs['A'] = 2.
    capture.page()
    assert sink.frames == [('B','aa01'),('A','aa0102')]


def test_actual_reader_cutoff_waits_for_callback_and_other_port_keeps_advancing(ports):
    cfg = profile(); cfg['frame']['tail'] = 'FF'
    manager = SerialStreamManager(); manager.start([{'port':'A'},{'port':'B'}],profile=cfg)
    entered, release = threading.Event(), threading.Event()
    original = manager._monitor._event_callback
    def blocked(event):
        original(event)
        if event.port == 'A':
            entered.set(); assert release.wait(2)
    manager._monitor._event_callback = blocked
    try:
        ports.instances[-2].rx.put(b'\xaa\x01\xff')
        assert entered.wait(1)
        before = manager.get_history()['idle_cutoffs']
        wait_for(lambda: manager.get_history()['idle_cutoffs']['B'] > before['B'])
        assert manager.get_history()['idle_cutoffs']['A'] == before['A']
        release.set()
        wait_for(lambda: manager.get_history()['idle_cutoffs']['A'] > before['A'])
        manager.stop()
        frozen = manager.get_history()['idle_cutoffs']
        assert manager.get_history()['idle_cutoffs'] == frozen
        assert not manager.worker_alive
    finally:
        release.set(); manager.stop()


def test_raw_history_delivery_failure_is_visible_instead_of_advancing_silently(ports, monkeypatch):
    manager = SerialStreamManager(); manager.start([{'port':'A'}],profile=profile())
    def fail(*args, **kwargs): raise RuntimeError('raw history unavailable')
    monkeypatch.setattr(manager._byte_batcher, 'feed', fail)
    try:
        ports.instances[-1].rx.put(b'\xaa\x01')
        wait_for(lambda: manager.get_history()['ports']['A'].startswith('error:'))
        wait_for(lambda: not ports.instances[-1].is_open)
        assert 'raw history unavailable' in manager.get_history()['ports']['A']
        assert manager.get_status()['latest_frames'] == {}
        manager.stop()
        assert not manager.worker_alive
    finally: manager.stop()
