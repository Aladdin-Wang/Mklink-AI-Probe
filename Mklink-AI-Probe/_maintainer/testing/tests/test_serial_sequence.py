"""Command sequences use existing readers and never replay failed writes."""
import threading
import time
import pytest
from mklink.serial._sequence import SendSequence
from mklink.serial._monitor import SerialMonitor
from mklink.remote.dashboards import SerialStreamManager
from test_serial_autoreply import ports, wait_for


def commands(): return [{'data':'A'}, {'data':'00ff','hex':True}]


def test_order_repeat_and_per_port_execution_use_existing_readers(ports):
    monitor=SerialMonitor([{'port':'A'},{'port':'B'}]); monitor.start()
    a,b=ports.instances[-2:]
    try:
        monitor.start_sequence('A',commands(),20,2)
        monitor.start_sequence('B',[{'data':'B'}],20,1)
        wait_for(lambda:monitor.sequence_status()['A']['state']=='completed')
        assert a.writes==[(x,'serial-reader-A') for x in (b'A',b'\0\xff',b'A',b'\0\xff')]
        assert b.writes==[(b'B','serial-reader-B')]
        assert len(monitor._threads)==2 and len(ports.instances)==2
        assert monitor.sequence_status()['A']['sent']==4
    finally: monitor.stop()


def test_cancel_and_duplicate_admission_never_replace_active_commands(ports):
    monitor=SerialMonitor([{'port':'A'}]);monitor.start();a=ports.instances[-1]
    try:
        monitor.start_sequence('A',commands(),1000,0)
        wait_for(lambda:len(a.writes)==1)
        with pytest.raises(RuntimeError,match='already active'):monitor.start_sequence('A',[{'data':'wrong'}],20)
        assert monitor.stop_sequence('A')['state']=='cancelled'
        time.sleep(.04); assert len(a.writes)==1
        monitor.start_sequence('A',[{'data':'new'}],20)
        wait_for(lambda:monitor.sequence_status()['A']['state']=='completed')
        assert [x[0] for x in a.writes]==[b'A',b'new']
    finally:monitor.stop()


def test_failed_write_is_not_retried_and_other_port_continues(ports):
    monitor=SerialMonitor([{'port':'A'},{'port':'B'}]);monitor.start();a,b=ports.instances[-2:];a.fail=True
    try:
        monitor.start_sequence('A',commands(),20,0)
        monitor.start_sequence('B',[{'data':'ok'}],20,2)
        wait_for(lambda:monitor.sequence_status()['A']['state']=='failed')
        wait_for(lambda:monitor.sequence_status()['B']['state']=='completed')
        assert len(a.writes)==1 and len(b.writes)==2
        assert 'partial' in monitor.sequence_status()['A']['error']
        wait_for(lambda:not a.is_open)
        assert b.is_open
    finally:monitor.stop()


def test_manager_stop_retains_cancelled_result_and_restart_has_no_old_sends(ports):
    manager=SerialStreamManager();manager.start([{'port':'A'}]);a=ports.instances[-1]
    manager.start_sequence('A',commands(),1000,0);wait_for(lambda:len(a.writes)==1)
    manager.stop()
    assert manager.get_status()['send_sequences']['A']['state']=='cancelled'
    assert not manager.worker_alive
    manager.start([{'port':'A'}])
    try:
        time.sleep(.04)
        assert ports.instances[-1].writes==[] and manager.get_status()['send_sequences']=={}
    finally:manager.stop()


def test_stop_waits_for_inflight_write_and_no_next_command_runs(ports,monkeypatch):
    entered,release=threading.Event(),threading.Event()
    original=ports.write
    def slow(self,data):entered.set();assert release.wait(3);return original(self,data)
    monkeypatch.setattr(ports,'write',slow)
    monitor=SerialMonitor([{'port':'A'}]);monitor.start();monitor._stop_timeout=.02
    try:
        monitor.start_sequence('A',commands(),20,0);assert entered.wait(1)
        with pytest.raises(TimeoutError):monitor.stop()
        assert monitor.worker_alive
        release.set();monitor.stop()
        assert len(ports.instances[-1].writes)==1
        assert monitor.sequence_status()['A']['state']=='cancelled'
    finally:release.set();monitor.stop()


@pytest.mark.parametrize('kwargs',[dict(interval_ms=True),dict(interval_ms=19),dict(interval_ms=3600001),
    dict(repeat=True),dict(repeat=-1),dict(commands=[]),dict(commands=[{'data':''}]),
    dict(commands=[{'data':'x','hex':'false'}]),dict(commands=[{'data':'gg','hex':True}]),
    dict(commands=[{'data':'x','extra':1}]),dict(commands=[{'data':'x'*4097}]),
    dict(commands=[{'data':'x'*4096}]*17),dict(commands=[{'data':'x'}]*65)])
def test_invalid_sequences_rejected_before_admission(kwargs):
    with pytest.raises(ValueError):SendSequence(**dict(dict(commands=commands()),**kwargs))


def test_delayed_execution_does_not_catch_up_in_bursts(monkeypatch):
    import mklink.serial._sequence as module
    now=[0.];monkeypatch.setattr(module.time,'monotonic',lambda:now[0])
    sequence=SendSequence(commands(),100,2)
    now[0]=10;sequence.sent=1;sequence.finish_send()
    assert sequence.due==10.1 and sequence.active


def test_protocol_handoff_cancels_only_that_port_without_resuming(ports, monkeypatch):
    class Sender:
        def __init__(self,*args,**kw):pass
        def send(self,*args):pass
    monkeypatch.setattr('mklink.serial._ymodem.YModemSender',Sender)
    monitor=SerialMonitor([{'port':'A'},{'port':'B'}]);monitor.start();a,b=ports.instances[-2:]
    try:
        monitor.start_sequence('A',commands(),1000,0)
        monitor.start_sequence('B',commands(),20,2)
        wait_for(lambda:len(a.writes)==1)
        monitor.send_ymodem('A',b'file','data')
        assert monitor.sequence_status()['A']['state']=='cancelled'
        wait_for(lambda:monitor.sequence_status()['B']['state']=='completed')
        assert len(a.writes)==1 and len(b.writes)==4
    finally:monitor.stop()


def test_http_and_shared_clients_use_same_sequence_and_disconnect_does_not_cancel(ports, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from mklink.remote.api import create_app
    from mklink.remote import dashboards
    from mklink.runtime_api import install_runtime
    from test_runtime_uart import uart_attach, call
    monkeypatch.setattr(dashboards,'_managers',{})
    app=create_app(project_root=str(tmp_path))
    control=install_runtime(app,{'probe_id':'lobby','port':8765,'token':'test-secret','instance_id':'sequence'})
    with TestClient(app,base_url='http://127.0.0.1:8765',headers={'X-Auth-Token':'test-secret'}) as client:
        owner,peer=uart_attach(client),uart_attach(client)
        try:
            assert client.post('/api/dash/serial/start',json={'ports':[{'port':'A'}]}).status_code==200
            request=dict(port='A',commands=commands(),interval_ms=1000,repeat=0)
            result=call(client,owner,'serial_sequence_start',request)
            assert result.status_code==200,result.text
            assert call(client,peer,'serial_sequence_start',request).status_code==409
            assert client.post('/_runtime/detach',json={'session_id':owner}).status_code==200
            assert call(client,peer,'serial_status').json()['send_sequences']['A']['active']
            assert client.post('/api/dash/serial/sequence/stop',json={'port':'A'}).json()['state']=='cancelled'
            assert call(client,peer,'serial_sequence_start',dict(request,interval_ms=True)).status_code==422
            assert call(client,peer,'serial_sequence_start',dict(request,commands=[])).status_code==400
        finally:
            control.sessions.clear();dashboards.get_managers()['serial'].stop()


def test_history_failure_after_physical_write_is_failed_without_replay(ports):
    def broken(port,direction,data,timestamp,monotonic):
        if direction=='TX':raise OSError('history unavailable after write')
    monitor=SerialMonitor([{'port':'A'}],chunk_callback=broken);monitor.start()
    try:
        monitor.start_sequence('A',commands(),20,0)
        wait_for(lambda:monitor.sequence_status()['A']['state']=='failed')
        state=monitor.sequence_status()['A']
        assert state['sent']==1 and 'after write' in state['error']
        wait_for(lambda:not ports.instances[-1].is_open)
        assert len(ports.instances[-1].writes)==1
    finally:monitor.stop()
