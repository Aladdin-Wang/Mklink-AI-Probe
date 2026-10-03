from types import SimpleNamespace
import pytest
from mklink import runtime_cli
from mklink.runtime import RuntimeErrorResponse


@pytest.fixture
def adapter(monkeypatch):
    calls=[]
    class Client:
        info = {'port':8765,'token':'test'}
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): calls.append(('connect',kwargs))
        def call(self, name, arguments=None):
            calls.append((name,arguments))
            if name.endswith('_status'): return {'state':'running'}
            if name.endswith('_start'): return {'reused':True}
            return {'sample':{'values':[42]}}
        def close(self): calls.append(('detach',None))
    monkeypatch.setattr(runtime_cli,'RuntimeClient',Client)
    return calls


def test_cli_capture_subscribes_and_does_not_stop_gui(adapter):
    runtime_cli.run(SimpleNamespace(command='superwatch', variables=[], period=.001, duration=.001))
    assert ('superwatch_start',{}) in adapter
    assert ('superwatch_values',None) in adapter
    assert not any(name=='superwatch_stop' for name,_ in adapter)
    assert adapter[-1][0]=='detach'


def test_cli_read_routes_to_shared_backend(adapter):
    runtime_cli.run(SimpleNamespace(command='read-ram', addr='0x20000000',size=4,probe='board'))
    assert adapter[0][1]['probe']=='board'
    assert ('read_memory',{'address':'0x20000000','size':4}) in adapter


def test_cli_rejects_private_capture_overrides_and_invalid_duration(adapter):
    with pytest.raises(SystemExit):
        runtime_cli.run(SimpleNamespace(command='superwatch',variables=['new'],period=.001,duration=.001))
    assert not any(name.endswith('_start') for name,_ in adapter)
    with pytest.raises(SystemExit):
        runtime_cli.run(SimpleNamespace(command='rtt',duration=float('nan')))


def test_existing_cli_defaults_to_shared_and_direct_is_explicit(monkeypatch):
    import sys
    from mklink import cli
    seen=[]
    monkeypatch.setattr(runtime_cli,'run',lambda args:seen.append(('shared',args.command)))
    monkeypatch.setattr(cli,'_cli_read_ram',lambda *args,**kwargs:seen.append(('direct','read-ram')))
    monkeypatch.setattr(sys,'argv',['mklink','read-ram','--addr','0','--size','4'])
    cli.main()
    monkeypatch.setattr(sys,'argv',['mklink','read-ram','--addr','0','--size','4','--direct'])
    cli.main()
    assert seen==[('shared','read-ram'),('direct','read-ram')]


def test_cli_rejects_ignored_visualization_overrides_before_connect(adapter):
    with pytest.raises(SystemExit, match='private host/port/chart'):
        runtime_cli.run(SimpleNamespace(command='rtt', port_http=9999))
    assert adapter == []


def test_cli_lost_backend_during_detach_preserves_primary_failure(monkeypatch, capsys):
    class Client:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): raise RuntimeErrorResponse('original connection failure')
        def close(self): raise RuntimeErrorResponse('backend gone')
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', Client)
    with pytest.raises(SystemExit, match='original connection failure'):
        runtime_cli.run(SimpleNamespace(command='device-status'))
    assert 'session will expire' in capsys.readouterr().err
