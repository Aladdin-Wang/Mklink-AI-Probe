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


@pytest.mark.parametrize('save', [False, True])
def test_debug_speed_cli_uses_selected_shared_probe_and_backend_persistence(adapter, monkeypatch, save):
    import sys
    from mklink import cli
    def forbidden(*args, **kwargs):
        raise AssertionError('CLI opened a direct device or wrote local configuration')
    monkeypatch.setattr('mklink.device.connect', forbidden)
    monkeypatch.setattr('mklink.project_config.save_config', forbidden)
    monkeypatch.setattr(sys, 'argv', ['mklink', 'debug-speed', 'low', '--probe', 'board'] + (['--save'] if save else []))
    cli.main()
    assert adapter[0][1]['probe'] == 'board'
    assert adapter[0][1]['project_root'] is None
    assert adapter[1] == ('set_debug_speed', {'profile': 'low', 'save': save})
    assert adapter[-1] == ('detach', None)


@pytest.mark.parametrize('command', ['halt', 'resume', 'step', 'read-flash'])
def test_debug_and_flash_read_cli_share_selected_backend(adapter, monkeypatch, command):
    import sys
    from mklink import cli
    monkeypatch.setattr(sys, 'argv', ['mklink', command, '--probe', 'board'])
    cli.main()
    assert adapter[0][1]['probe'] == 'board'
    assert adapter[1] == (('read_memory', {'address':'0x08000000', 'size':128})
                          if command == 'read-flash' else (command, None))
    assert adapter[-1] == ('detach', None)


def test_flash_read_rejects_probe_file_write_before_connect(adapter):
    with pytest.raises(SystemExit, match='--save'):
        runtime_cli.run(SimpleNamespace(command='read-flash', save='flash.bin'))
    assert adapter == []


def test_cli_rejects_private_capture_overrides_and_invalid_duration(adapter):
    with pytest.raises(SystemExit):
        runtime_cli.run(SimpleNamespace(command='superwatch',variables=['new'],period=.001,duration=.001))
    assert not any(name.endswith('_start') for name,_ in adapter)
    with pytest.raises(SystemExit):
        runtime_cli.run(SimpleNamespace(command='rtt',duration=float('nan')))


def test_existing_cli_is_shared_and_direct_switch_is_removed(monkeypatch):
    import sys
    from mklink import cli
    seen=[]
    monkeypatch.setattr(runtime_cli,'run',lambda args:seen.append(('shared',args.command)))
    monkeypatch.setattr(sys,'argv',['mklink','read-ram','--addr','0','--size','4'])
    cli.main()
    monkeypatch.setattr(sys,'argv',['mklink','read-ram','--addr','0','--size','4','--direct'])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert seen==[('shared','read-ram')]


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


def test_cli_submits_once_and_only_polls_an_unknown_job(monkeypatch, capsys):
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): pass
        def start_job(self, action, **kwargs):
            calls.append(('submit', action, kwargs))
            return {'job_id': 'a' * 32, 'state': 'running'}
        def job_status(self, job_id):
            calls.append(('query', job_id))
            return {'job_id': job_id, 'state': 'unknown'}
        def close(self): calls.append(('detach',))
    monkeypatch.setattr(runtime_cli, 'RuntimeClient', Client)
    monkeypatch.setattr(runtime_cli.time, 'sleep', lambda _: None)
    with pytest.raises(SystemExit, match='unknown'):
        runtime_cli.run(SimpleNamespace(command='reset', request_id='stable-request'))
    assert calls == [('submit', 'reset', {'arguments': {}, 'request_id': 'stable-request', 'confirm': True}),
                     ('query', 'a' * 32), ('detach',)]
    assert 'stable-request' in capsys.readouterr().out
