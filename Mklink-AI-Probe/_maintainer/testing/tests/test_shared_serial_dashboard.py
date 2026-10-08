"""Shared dashboard replacement, bounded files, and honest broadcast outcomes."""
from types import SimpleNamespace
import pytest
from mklink.remote.dashboards import SerialStreamManager
from mklink.serial._sequence import file_commands
from test_serial_autoreply import ports, wait_for
from test_runtime_uart import uart_app, client_factory, uart_attach, call
from test_shared_modbus_scan import scan_cli


def test_broadcast_reports_each_port_and_never_retries_partial_write(ports):
    manager=SerialStreamManager();manager.start([{'port':'A'},{'port':'B'}]);a,b=ports.instances[-2:];a.fail=True
    try:
        result=manager.send_all(b'Q')
        assert result['ok'] is False and not result['results']['A']['ok']
        assert result['results']['B']=={'ok':True,'bytes':1}
        assert len(a.writes)==len(b.writes)==1
    finally:manager.stop()


@pytest.mark.parametrize('hex_file',[False,True])
def test_file_uses_same_reader_sequence_and_preserves_exact_bytes(ports,tmp_path,hex_file):
    payload=bytes(range(256))*33
    path=tmp_path/'input';path.write_bytes(payload.hex(' ').encode() if hex_file else payload)
    manager=SerialStreamManager();manager.start([{'port':'A'}])
    try:
        result=manager.send_file('A',str(path),hex_file)
        assert result['bytes']==len(payload)
        wait_for(lambda:manager.get_status()['send_sequences']['A']['state']=='completed')
        writes=ports.instances[-1].writes
        assert b''.join(data for data,_ in writes)==payload
        assert all(name=='serial-reader-A' and len(data)<=4096 for data,name in writes)
        assert len(ports.instances)==1
    finally:manager.stop()


@pytest.mark.parametrize('content,is_hex',[(b'',False),(b'x'*65537,False),(b'xx',True),(b'\xff',True),(b'0'*262145,True)], ids=['empty','raw-too-large','invalid-hex','non-ascii','input-too-large'])
def test_invalid_files_are_rejected_before_admission(content,is_hex):
    with pytest.raises(ValueError):file_commands(content,is_hex)


def test_file_does_not_replace_running_sequence_or_create_another_reader(ports,tmp_path):
    path=tmp_path/'input';path.write_bytes(b'file')
    manager=SerialStreamManager();manager.start([{'port':'A'}])
    try:
        manager.start_sequence('A',[{'data':'Q'}],1000,0)
        with pytest.raises(RuntimeError,match='already active'):manager.send_file('A',str(path))
        assert len(ports.instances)==1
        with pytest.raises(ValueError):manager.send_file('A',str(tmp_path))
    finally:manager.stop()


def test_upload_stream_limit_and_rpc_file_and_broadcast(ports,monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from mklink.remote.api import create_app
    from mklink.remote import dashboards
    from mklink.runtime_api import install_runtime
    monkeypatch.setattr(dashboards,'_managers',{})
    app=create_app(project_root=str(tmp_path));control=install_runtime(app,{'probe_id':'lobby','port':8765,'token':'test-secret','instance_id':'file'})
    with TestClient(app,base_url='http://127.0.0.1:8765',headers={'X-Auth-Token':'test-secret'}) as client:
        session=uart_attach(client)
        try:
            assert client.post('/api/dash/serial/start',json={'ports':[{'port':'A'}]}).status_code==200
            manager=dashboards.get_managers()['serial']
            assert client.post('/api/dash/serial/file/upload?port=A',content=b'x'*262145).status_code==413
            assert ports.instances[-1].writes==[]
            response=client.post('/api/dash/serial/file/upload?port=A&hex=true',content=b'00 ff')
            assert response.status_code==200 and response.json()['bytes']==2
            wait_for(lambda:manager.get_status()['send_sequences']['A']['state']=='completed')
            path=tmp_path/'file';path.write_bytes(b'Q')
            assert call(client,session,'serial_send_file',{'port':'A','path':str(path)}).status_code==200
            wait_for(lambda:manager.get_status()['send_sequences']['A']['state']=='completed')
            response=call(client,session,'serial_broadcast',{'data':'Z'})
            assert response.json()['results']['A']['ok']
            assert b''.join(d for d,_ in ports.instances[-1].writes)==b'\0\xffQZ'
        finally:control.sessions.clear();dashboards.get_managers()['serial'].stop()


@pytest.mark.parametrize('existing',[False,True])
def test_dashboard_cli_leaves_shared_uart_running_and_opens_authenticated_serial_page(scan_cli,uart_app,monkeypatch,existing):
    cli,_,http,control,_,_=scan_cli
    urls=[];monkeypatch.setattr('webbrowser.open',urls.append)
    if existing:assert http.post('/api/dash/serial/start',json={'ports':[{'port':'TEST'}]}).status_code==200
    args=SimpleNamespace(serial_command='dashboard',port=['TEST'],baud=115200,databits=8,stop=1,parity='N',profile=None,probe=None,no_browser=False)
    cli._cli_serial_dispatch(args)
    assert uart_app[2]['serial'].running and not control.sessions
    assert urls==['http://127.0.0.1:8765/_runtime/open?page=serial#test-secret']
    assert control.app.state.mklink_state['device'] is None
    response=http.get('/_runtime/open?page=serial')
    assert 'dashboard?tab=serial' in response.text and response.headers['cache-control']=='no-store'


def test_dashboard_cli_rejects_settings_conflict_without_changing_owner(scan_cli,uart_app):
    cli,_,http,_,_,_=scan_cli
    assert http.post('/api/dash/serial/start',json={'ports':[{'port':'TEST','baudrate':9600}]}).status_code==200
    args=SimpleNamespace(serial_command='dashboard',port=['TEST'],baud=115200,databits=8,stop=1,parity='N',profile=None,probe=None,no_browser=True)
    with pytest.raises(SystemExit):cli._cli_serial_dispatch(args)
    assert uart_app[2]['serial'].get_status()['config'][0]['baudrate']==9600
