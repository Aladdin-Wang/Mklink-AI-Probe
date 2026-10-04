"""Passive shared monitor: source isolation, bounded rendering and common lifetime."""
from functools import partial
import csv
import json
from types import SimpleNamespace
import pytest
from mklink.serial._capture import SerialCapture
from mklink.serial._console_monitor import ConsoleMonitor
from mklink.serial._frame import FrameParser
from mklink.serial._logger import FileLogger
from test_shared_modbus_scan import scan_cli
from test_runtime_uart import uart_app, client_factory


def arguments(**changes):
    return SimpleNamespace(**dict(dict(serial_command='monitor',port=['TEST','OTHER'],baud=19200,
        databits=8,stop=1,parity='N',probe=None,mode='ascii',profile=None,filter=None,
        log=None,duration=.01), **changes))


def test_utf8_is_separate_by_port_and_direction_and_idle_flushes(monkeypatch,capsys):
    from mklink.serial import _console_monitor
    now=[0.0]
    monkeypatch.setattr(_console_monitor.time,'monotonic',lambda:now[0])
    monitor=ConsoleMonitor()
    raw='温'.encode()
    monitor.log('RX','A',raw[:2],timestamp=1)
    monitor.log('TX','A',b'transmit\n',timestamp=2)
    monitor.log('RX','B',b'other\n',timestamp=3)
    monitor.log('RX','A',raw[2:]+b' tail',timestamp=4)
    monitor.tick()
    first=capsys.readouterr().out
    assert 'transmit' in first and 'other' in first and '温' not in first
    now[0]=.11;monitor.tick()
    tail=capsys.readouterr().out
    assert 'RX A [partial]: 温 tail' in tail and '�' not in tail
    monitor.finish();assert not monitor._sources


def test_filter_spans_chunks_but_does_not_filter_log(tmp_path,capsys):
    path=tmp_path/'raw.csv'
    with FileLogger(str(path),'csv') as logger:
        monitor=ConsoleMonitor(filter_pattern='温度',logger=logger)
        monitor.log('RX','A','温'.encode(),timestamp=1)
        monitor.log('RX','A','度\n'.encode(),timestamp=2)
        monitor.log('RX','A',b'hidden\n',timestamp=3)
        monitor.finish()
    shown=capsys.readouterr().out
    assert '温度' in shown and 'hidden' not in shown
    rows=list(csv.DictReader(path.open(encoding='utf-8',newline='')))
    assert bytes.fromhex(''.join(row['raw_hex'] for row in rows))=='温度\nhidden\n'.encode()


def test_console_is_bounded_and_escapes_terminal_controls(capsys):
    monitor=ConsoleMonitor()
    monitor.log('RX','A',b'x'*10000,timestamp=1)
    assert len(monitor._sources[('A','RX')]['text']) < 4096
    monitor.log('RX','A',b'\x1b[2J\r',timestamp=2)
    monitor.finish()
    shown=capsys.readouterr().out
    assert '\x1b' not in shown and '\\x1b[2J\\r' in shown
    assert shown.count('[partial]') == 3


def test_hex_outputs_without_line_or_utf8_decoding(capsys):
    monitor=ConsoleMonitor('hex', '00 FF')
    monitor.log('RX','A',b'\x00\xff',timestamp=1)
    monitor.log('TX','B',b'other',timestamp=2)
    assert 'RX A: 00 FF' in capsys.readouterr().out
    assert not monitor._sources


@pytest.mark.parametrize('params',[dict(port=[]),dict(port=['COM7','com7']),dict(port=[str(i) for i in range(17)]),
    dict(filter='['),dict(mode='bad'),dict(duration=-1),dict(duration=float('inf')),dict(duration=float('nan')),
    dict(profile='missing.json'),dict(baud=0)])
def test_invalid_monitor_before_attach(monkeypatch,params):
    from mklink import cli
    monkeypatch.setattr('mklink.runtime.RuntimeClient',lambda **kw:pytest.fail('invalid monitor attached'))
    with pytest.raises(SystemExit): cli._cli_serial_dispatch(arguments(**params))


@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('with_log',[False,True])
def test_monitor_passive_multiport_and_lifetime(scan_cli,uart_app,monkeypatch,tmp_path,capsys,existing,with_log):
    cli,_,http,control,_,_=scan_cli
    manager=uart_app[2]['serial']
    if existing:
        assert http.post('/api/dash/serial/start',json={'ports':[{'port':port,'baudrate':19200}
            for port in ('TEST','OTHER','UNSELECTED')]}).status_code==200
    original_run=SerialCapture.run
    def run(capture,duration,**kwargs):
        manager._byte_batcher.feed(b'A\n','RX','TEST')
        manager._byte_batcher.feed(b'B\n','RX','OTHER')
        manager._byte_batcher.feed(b'WRONG\n','RX','UNSELECTED')
        manager._byte_batcher.flush()
        original_run(capture,duration,**kwargs)
        if not existing:manager._byte_batcher.feed(b'last','RX','OTHER')
    monkeypatch.setattr(SerialCapture,'run',run)
    path=tmp_path/'monitor.csv'
    cli._cli_serial_dispatch(arguments(log=str(path) if with_log else None))
    shown=capsys.readouterr().out
    assert 'RX TEST: A' in shown and 'RX OTHER: B' in shown and 'WRONG' not in shown
    assert ('RX OTHER [partial]: last' in shown) == (not existing)
    assert not uart_app[4].sent and not control.sessions and manager.running==existing
    if with_log:
        rows=list(csv.DictReader(path.open(encoding='utf-8',newline='')))
        assert {row['port'] for row in rows}=={'TEST','OTHER'}
    else:assert not path.exists()


def test_conflict_on_second_port_preserves_borrowed_session_and_file(scan_cli,uart_app,tmp_path):
    cli,_,http,control,_,_=scan_cli
    settings={'ports':[{'port':'TEST','baudrate':19200},{'port':'OTHER','baudrate':9600}]}
    assert http.post('/api/dash/serial/start',json=settings).status_code==200
    before=uart_app[2]['serial'].get_status()['config']
    output=tmp_path/'keep.csv';output.write_text('KEEP')
    with pytest.raises(SystemExit,match='different port/settings'):
        cli._cli_serial_dispatch(arguments(log=str(output)))
    assert output.read_text()=='KEEP' and not control.sessions and uart_app[2]['serial'].running
    assert uart_app[2]['serial'].get_status()['config']==before


def test_selected_port_failure_aborts_without_sending(scan_cli,uart_app,monkeypatch,capsys):
    cli,_,_,control,_,_=scan_cli
    manager=uart_app[2]['serial'];original=SerialCapture.run
    def run(capture,duration,**kwargs):
        manager._monitor.port_status['OTHER']='error: unplugged'
        original(capture,duration,**kwargs)
    monkeypatch.setattr(SerialCapture,'run',run)
    with pytest.raises(SystemExit,match='OTHER.*unplugged'):
        cli._cli_serial_dispatch(arguments())
    assert not manager.worker_alive and not control.sessions and not uart_app[4].sent
    assert '监听已结束' not in capsys.readouterr().out


def test_profile_buffers_do_not_cross_ports(capsys):
    profile={'frame':{'header':'AA','tail':'FF'},'fields':[]}
    class Client:
        count=0
        def call(self,capability,args=None):
            self.count+=1
            chunks=[] if self.count==1 else [('A','aa01'),('B','ff'),('A','ff'),('B','aa02ff')]
            return dict(session='one',next_seq=0,running=True,ports={'A':'open','B':'open'},
                latest_seq=len(chunks),dropped_batches=0,idle_cutoffs={'TEST':1.,'A':1.,'B':1.},entries=[dict(seq=i+1,port=p,direction='RX',hex=data,timestamp_ns=1,first_monotonic=1.,last_monotonic=1.)
                    for i,(p,data) in enumerate(chunks)])
    capture=SerialCapture(partial(Client().call, 'serial_history'),{p:FrameParser(profile) for p in ('A','B')},ConsoleMonitor('hex'))
    capture.page()
    text=capsys.readouterr().out
    assert 'RX A: decoded: {"raw_hex": "aa01ff"' in text
    assert 'RX B: decoded: {"raw_hex": "aa02ff"' in text


def test_broken_console_does_not_leak_owner(scan_cli,uart_app,monkeypatch):
    cli,_,_,control,_,_=scan_cli
    manager=uart_app[2]['serial'];original=SerialCapture.run
    def run(capture,duration,**kwargs):
        manager._byte_batcher.feed(b'data\n','RX','TEST');manager._byte_batcher.flush()
        original(capture,duration,**kwargs)
    monkeypatch.setattr(SerialCapture,'run',run)
    monkeypatch.setattr(ConsoleMonitor,'_write',lambda *a,**kw:(_ for _ in ()).throw(BrokenPipeError('output closed')))
    with pytest.raises(SystemExit,match='output closed'):cli._cli_serial_dispatch(arguments())
    assert not manager.worker_alive and not control.sessions
