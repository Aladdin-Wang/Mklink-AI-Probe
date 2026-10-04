"""Replies belong to one reader and must not survive ownership boundaries."""
import queue
import threading
import time
from dataclasses import FrozenInstanceError
import pytest
from mklink.serial._autoreply import AutoReplyEngine,AutoReplyRule
from mklink.serial import _monitor
from mklink.serial._monitor import SerialMonitor


def rule(**changes):
    return dict(dict(match_contains='Q',reply_ascii='R',delay=.02),**changes)


def wait_for(predicate):
    end=time.monotonic()+2
    while not predicate():
        assert time.monotonic()<end,'condition timed out'
        time.sleep(.002)


@pytest.fixture
def ports(monkeypatch):
    class Port:
        instances=[]
        def __init__(self,**kwargs):
            self.name=kwargs['port'];self.is_open=False;self.rx=queue.Queue();self.writes=[];self.fail=False
            self.instances.append(self)
        def open(self):self.is_open=True;return True
        def close(self):self.is_open=False
        def read_available(self):
            try:return self.rx.get_nowait()
            except queue.Empty:return b''
        def write(self,data):
            self.writes.append((bytes(data),threading.current_thread().name))
            if self.fail:raise OSError('partial physical write')
    monkeypatch.setattr(_monitor,'SerialPort',Port)
    monkeypatch.setattr(threading,'Timer',lambda *a,**kw:pytest.fail('per-reply timer created'))
    return Port


@pytest.mark.parametrize('delay',[0,.02])
def test_replies_run_on_existing_reader(ports,delay):
    chunks=[]
    monitor=SerialMonitor([{'port':'TEST'}],auto_reply_rules=[rule(delay=delay)],chunk_callback=lambda p,d,b,t:chunks.append((d,b)))
    monitor.start();port=ports.instances[-1]
    try:
        port.rx.put(b'Q\n');wait_for(lambda:len(port.writes)==1)
        assert port.writes==[(b'R','serial-reader-TEST')]
        wait_for(lambda:('TX',b'R') in chunks)
    finally:monitor.stop()
    assert not monitor.worker_alive and not port.is_open


def test_normal_and_automatic_send_share_protocol_stop_guards(ports):
    monitor=SerialMonitor([{'port':'TEST'}],auto_reply_rules=[rule(delay=0)])
    port=ports(port='TEST');port.open();monitor._serial_ports['TEST']=port
    monitor._handle_auto_reply('TEST',b'Q')
    monitor._protocol_queues['TEST']=queue.Queue()
    assert monitor.send('TEST',b'normal') is False
    monitor._drain_auto_replies('TEST')
    monitor._handle_auto_reply('TEST',b'Q')
    assert not port.writes and not monitor._pending_replies
    monitor._protocol_queues.clear();monitor._stop_event.set()
    monitor._handle_auto_reply('TEST',b'Q');monitor._drain_auto_replies('TEST')
    assert monitor.send('TEST',b'normal') is False and not port.writes
    monitor.stop()


def test_stop_restart_cancels_old_delayed_reply(ports):
    monitor=SerialMonitor([{'port':'TEST'}],auto_reply_rules=[rule(delay=.15)])
    monitor.start();old=ports.instances[-1]
    old.rx.put(b'Q\n');wait_for(lambda:bool(monitor._pending_replies.get('TEST')))
    monitor.stop();assert not monitor._pending_replies
    monitor.start();fresh=ports.instances[-1]
    try:
        time.sleep(.2)
        assert not old.writes and not fresh.writes and not old.is_open
        fresh.rx.put(b'Q\n');wait_for(lambda:len(fresh.writes)==1)
    finally:monitor.stop()


def test_ymodem_cancels_only_selected_port_and_does_not_resume_old_reply(ports,monkeypatch):
    entered,release=threading.Event(),threading.Event()
    class Sender:
        def __init__(self,read,write,**kw):self.write=write
        def send(self,*args):
            entered.set();assert release.wait(2);self.write(b'PROTOCOL')
    monkeypatch.setattr('mklink.serial._ymodem.YModemSender',Sender)
    monitor=SerialMonitor([{'port':'TEST'},{'port':'OTHER'}],auto_reply_rules=[rule(delay=.1)])
    monitor.start();a,b=ports.instances[-2:]
    for port in (a,b):port.rx.put(b'Q\n')
    wait_for(lambda:all(monitor._pending_replies.get(p) for p in ('TEST','OTHER')))
    transfer=threading.Thread(target=monitor.send_ymodem,args=('TEST',b'data','file'))
    transfer.start();assert entered.wait(1)
    try:
        wait_for(lambda:bool(b.writes))
        assert not a.writes and 'TEST' not in monitor._pending_replies
        release.set();transfer.join(2);assert not transfer.is_alive()
        time.sleep(.05);assert [v for v,_ in a.writes]==[b'PROTOCOL']
        a.rx.put(b'Q\n');wait_for(lambda:len(a.writes)==2)
        assert a.writes[-1]==(b'R','serial-reader-TEST')
    finally:
        release.set();transfer.join(2);monitor.stop()


def test_fast_protocol_boundary_rejects_reply_from_inflight_match(ports,monkeypatch):
    matched,release=threading.Event(),threading.Event()
    class Sender:
        def __init__(self,*a,**kw):pass
        def send(self,*a):pass
    monkeypatch.setattr('mklink.serial._ymodem.YModemSender',Sender)
    monitor=SerialMonitor([{'port':'TEST'}],auto_reply_rules=[rule(delay=0)])
    check=monitor._auto_reply_engine.check
    def blocked(data):
        result=check(data)
        if not matched.is_set():matched.set();assert release.wait(2)
        return result
    monkeypatch.setattr(monitor._auto_reply_engine,'check',blocked)
    monitor.start();port=ports.instances[-1]
    try:
        port.rx.put(b'Q\n');assert matched.wait(1)
        monitor.send_ymodem('TEST',b'data','file')
        release.set();time.sleep(.04)
        assert not port.writes and not monitor._pending_replies.get('TEST')
        port.rx.put(b'Q\n');wait_for(lambda:len(port.writes)==1)
    finally:release.set();monitor.stop()


def test_queue_overflow_and_write_error_are_visible_and_never_retried(ports):
    monitor=SerialMonitor([{'port':'TEST'}],auto_reply_rules=[rule(delay=3600)])
    monitor.start();port=ports.instances[-1]
    port.rx.put(b'Q\n'*129)
    wait_for(lambda:not monitor.worker_alive)
    assert '128 entries' in monitor.port_status['TEST'] and not port.writes
    assert not monitor._pending_replies
    monitor.stop()
    monitor=SerialMonitor([{'port':'TEST'}],auto_reply_rules=[rule(delay=0)])
    monitor.start();port=ports.instances[-1];port.fail=True;port.rx.put(b'Q\n')
    wait_for(lambda:not monitor.worker_alive)
    assert len(port.writes)==1 and 'not retried' in monitor.port_status['TEST']
    monitor.stop()


@pytest.mark.parametrize('change',[dict(delay=-1),dict(delay=True),dict(delay=float('nan')),dict(delay=float('inf')),
    dict(delay=3601),dict(match_contains=''),dict(match_regex='['),dict(match_hex='ZZ'),dict(match_hex='  '),
    dict(reply_ascii=''),dict(reply_ascii='a'*4097),dict(reply_hex='GG',reply_ascii=None),
    dict(reply_hex='00'),dict(reply_ascii=None),dict(unknown=True),dict(description=5)])
def test_bad_rules_fail_before_any_port_open(monkeypatch,change):
    monkeypatch.setattr(_monitor,'SerialPort',lambda **kw:pytest.fail('bad rule opened port'))
    with pytest.raises(ValueError):
        monitor=SerialMonitor([{'port':'TEST'}],auto_reply_rules=[rule(**change)])
        monitor.start()


def test_rule_count_atomic_loading_immutable_rules_and_utf8():
    engine=AutoReplyEngine();engine.load_rules([rule(reply_ascii='温度\\r\\n')])
    assert engine.check(b'Q')[0][0]=='温度\r\n'.encode()
    with pytest.raises(ValueError):engine.load_rules([rule(),rule(delay=-1)])
    assert len(engine.rules)==1
    with pytest.raises(FrozenInstanceError):engine.rules[0].delay=-1
    engine.load_rules([rule()]*63)
    with pytest.raises(ValueError):engine.add_rule(AutoReplyRule(**rule()))
    with pytest.raises(ValueError):engine.load_rules([rule()])
    assert len(engine.rules)==64
    normalized=AutoReplyRule(match_hex='AA 55',reply_hex='00')
    assert AutoReplyEngine([normalized]).check(bytes.fromhex('AA55'))==[(b'\x00',0)]


def test_equal_deadlines_keep_rule_order(ports):
    monitor=SerialMonitor([{'port':'TEST'}],auto_reply_rules=[rule(delay=0,reply_ascii=x) for x in ('Z','A','B')])
    port=ports(port='TEST');port.open();monitor._serial_ports['TEST']=port
    monitor._handle_auto_reply('TEST',b'Q');monitor._drain_auto_replies('TEST')
    assert [data for data,_ in port.writes]==[b'Z',b'A',b'B']
    monitor.stop()


@pytest.mark.parametrize('short_write', [False, True])
def test_actual_serial_port_reply_and_short_write_release(monkeypatch, short_write):
    """Keep real port locking/write validation; fake only the OS transport."""
    import serial
    from mklink.serial._port import SerialPort

    class Wire:
        instances = []

        def __init__(self, **settings):
            self.is_open = True
            self.pending = b'Q\n'
            self.writes = []
            self.instances.append(self)

        @property
        def in_waiting(self):
            return len(self.pending)

        def read(self, count):
            data, self.pending = self.pending[:count], self.pending[count:]
            return data

        def write(self, data):
            self.writes.append(bytes(data))
            return len(data) - int(short_write)

        def close(self):
            self.is_open = False

    monkeypatch.setattr(serial, 'Serial', Wire)
    chunks = []
    monitor = SerialMonitor(
        [{'port': 'SIM_REPLY'}], auto_reply_rules=[rule(delay=0)],
        chunk_callback=lambda p, d, b, t: chunks.append((d, b)),
    )
    monitor.start()
    wire = Wire.instances[-1]
    try:
        wait_for(lambda: bool(wire.writes))
        if short_write:
            wait_for(lambda: not monitor.worker_alive)
            assert 'not retried' in monitor.port_status['SIM_REPLY']
            assert not any(direction == 'TX' for direction, _ in chunks)
        else:
            wait_for(lambda: ('TX', b'R') in chunks)
            assert monitor.worker_alive
        assert wire.writes == [b'R']
    finally:
        monitor.stop()
    assert not wire.is_open and not monitor.worker_alive
    # A fresh owner can acquire the same actual advisory port lock.
    with SerialPort('SIM_REPLY') as reopened:
        assert reopened.is_open


def test_live_profile_overflow_stops_reader(ports):
    monitor = SerialMonitor(
        [{'port': 'TEST'}],
        profile={'frame': {'header': 'AA', 'tail': 'FF'}, 'fields': []},
    )
    monitor.start()
    port = ports.instances[-1]
    try:
        port.rx.put(b'\xaa' + b'\x00' * (1024 * 1024))
        wait_for(lambda: not monitor.worker_alive)
        assert monitor.port_status['TEST'].startswith('error:')
        assert not port.is_open and not port.writes
    finally:
        monitor.stop()
