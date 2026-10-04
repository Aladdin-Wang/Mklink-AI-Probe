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


def test_device_status_cli_reuses_backend_and_only_detaches(adapter, monkeypatch, capsys):
    import json, sys
    from mklink import cli
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge', lambda *a, **kw: pytest.fail('Diagnostic opened CDC'))
    monkeypatch.setattr(sys, 'argv', ['mklink', 'device-status', '--probe', 'board'])
    cli.main()
    assert adapter[0][1]['probe'] == 'board'
    assert adapter[1:] == [('device_status', None), ('detach', None)]
    assert json.loads(capsys.readouterr().out) == {'state': 'running'}


def test_configuration_read_cli_uses_shared_backend_and_adopts_project(adapter, monkeypatch, capsys):
    import sys
    from mklink import cli
    def forbidden(**kwargs):
        raise AssertionError('Configuration CLI opened target directly')
    monkeypatch.setattr('mklink.device.connect', forbidden)
    monkeypatch.setattr(sys, 'argv', ['mklink', 'configuration', 'read', '--chip', 'STM32F103RET6', '--probe', 'board'])
    cli.main()
    assert adapter[0][1]['probe'] == 'board' and adapter[0][1]['project_root'] is None
    assert adapter[1] == ('read_configuration', {'part_number': 'STM32F103RET6', 'model': 'V4'})
    assert adapter[-1] == ('detach', None)
    assert 'sample' in capsys.readouterr().out


def test_configuration_description_cli_stays_offline(adapter, monkeypatch, capsys):
    import json, sys
    from mklink import cli
    monkeypatch.setattr(sys, 'argv', ['mklink', 'configuration', 'describe', '--chip', 'HPM5301'])
    cli.main()
    assert not adapter
    assert json.loads(capsys.readouterr().out)['read_supported']


@pytest.mark.parametrize('arguments,capability,body', [
    (['select','--chip','TEST'],'select_peripherals',{'chip':'TEST'}),
    (['list','--query','GPIO'],'list_peripherals',{'q':'GPIO'}),
    (['read','GPIOB.12'],'read_peripherals',{'names':['GPIOB.12']}),
    (['capture','GPIOB.12','--duration','.1'],'capture_peripherals',{'names':['GPIOB.12'],'duration':.1,'period':.01}),
])
def test_peripheral_cli_adopts_shared_backend_without_direct_connection(adapter,monkeypatch,arguments,capability,body):
    import sys
    from mklink import cli
    def forbidden(*args,**kwargs):
        raise AssertionError('Peripheral CLI opened CDC directly')
    monkeypatch.setattr('mklink.device.connect',forbidden)
    monkeypatch.setattr(sys,'argv',['mklink','peripherals',*arguments,'--probe','selected'])
    cli.main()
    assert adapter[0][1]['probe']=='selected' and adapter[0][1]['project_root'] is None
    assert adapter[1]==(capability,body) and adapter[-1]==('detach',None)


def test_peripheral_targets_cli_is_offline(adapter,monkeypatch,capsys):
    import sys,json
    from mklink import cli
    monkeypatch.setattr('mklink.peripheral_watch.list_svd_targets',lambda root,q:{'targets':[root,q]})
    monkeypatch.setattr(sys,'argv',['mklink','peripherals','targets','--project-root','selected','--query','GPIO'])
    cli.main()
    assert not adapter
    assert json.loads(capsys.readouterr().out)=={'targets':['selected','GPIO']}


@pytest.mark.parametrize('command', ['power-read', 'version'])
def test_probe_queries_do_not_create_target_session_or_retry(adapter, monkeypatch, capsys, command):
    import sys
    from mklink import cli
    seen = []
    def query(capability, **kwargs):
        seen.append((capability, kwargs))
        raise RuntimeErrorResponse('unavailable; no replay')
    monkeypatch.setattr('mklink.runtime.query_probe', query)
    monkeypatch.setattr(sys, 'argv', ['mklink', command, '--probe', 'chosen'])
    with pytest.raises(SystemExit, match='no replay'):
        cli.main()
    assert seen == [('power_read' if command == 'power-read' else 'probe_version', {'probe': 'chosen', 'port': None})]
    assert not adapter and not capsys.readouterr().out


@pytest.mark.parametrize('flag', ['', '--all', '--raw'])
def test_version_cli_retains_output_options_without_direct_bridge(adapter, monkeypatch, capsys, flag):
    import sys
    from mklink import cli
    response = 'cmd.get_version()\nV4.5.2\nLatest changes\nV4.5.1\nOlder changes\n>>> '
    monkeypatch.setattr('mklink.runtime.query_probe', lambda *a, **kw: {'raw': response})
    monkeypatch.setattr(sys, 'argv', ['mklink', 'version', '--probe', 'chosen'] + ([flag] if flag else []))
    cli.main()
    output = capsys.readouterr().out
    assert 'V4.5.2' in output and 'V4.5.1' in output and not adapter
    assert ('Older changes' in output) is bool(flag)


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


@pytest.mark.parametrize('command',['dump-memory','dump'])
def test_dump_cli_uses_shared_capture_and_saves_complete_sample_bytes(monkeypatch,tmp_path,capsys,command):
    import json,sys
    from mklink import cli
    calls=[]
    result={'sample_count':1,'region_count':1,'total_bytes':4,'stopped_by':'frames',
            'samples':[{'sample_index':0,'regions':[{'address':'0x20000000','size':4,'data_hex':'01020304'}]}]}
    class Client:
        def __init__(self,**kwargs): pass
        def connect(self,**kwargs):calls.append(('connect',kwargs))
        def call(self,name,args):calls.append((name,args));return result
        def close(self):calls.append(('detach',None))
    monkeypatch.setattr(runtime_cli,'RuntimeClient',Client)
    def forbidden(*args,**kwargs):raise AssertionError('dump CLI opened CDC')
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge',forbidden)
    target=tmp_path/'sample.bin'
    monkeypatch.setattr(sys,'argv',['mklink',command,'0x20000000:4','--probe','chosen','--period','.01','--frames','1','--save',str(target),'--json'])
    cli.main()
    assert target.read_bytes()==b'\x01\x02\x03\x04'
    assert json.loads(capsys.readouterr().out)==result
    assert calls[0][1]['probe']=='chosen'
    assert calls[1]==('capture_dump',{'regions':[{'address':0x20000000,'size':4}],'period':.01,'frames':1,'duration':2.0,'speed_profile':None})
    assert calls[-1]==('detach',None)


def test_dump_cli_failure_preserves_file_and_detaches_without_retry(monkeypatch,tmp_path):
    import sys
    from mklink import cli
    calls=[]
    target=tmp_path/'existing.bin';target.write_bytes(b'preserve')
    class Client:
        def __init__(self,**kwargs):pass
        def connect(self,**kwargs):pass
        def call(self,*args):calls.append('call');return {'sample_count':1,'samples':[]}
        def close(self):calls.append('detach')
    monkeypatch.setattr(runtime_cli,'RuntimeClient',Client)
    monkeypatch.setattr(sys,'argv',['mklink','dump-memory','0x20000000:4','--save',str(target)])
    with pytest.raises(SystemExit,match='Invalid shared dump'):
        cli.main()
    assert calls==['call','detach'] and target.read_bytes()==b'preserve'

@pytest.mark.parametrize('fail', [False, True])
def test_copy_flm_cli_selects_shared_backend_and_never_retries(tmp_path, monkeypatch, capsys, fail):
    import sys
    from mklink import cli
    source = tmp_path / 'test.FLM'; source.write_bytes(b'algorithm')
    calls = []
    def ensure(**kwargs):
        calls.append(('select', kwargs))
        return {'port': 8765, 'token': 'test'}
    def request(info, method, path, body, **kwargs):
        calls.append((method, path, body))
        if fail:
            raise RuntimeErrorResponse('response lost')
        return {'files': ['FLM/test.FLM'], 'job_id': 'job'}
    monkeypatch.setattr('mklink.runtime.ensure_runtime', ensure)
    monkeypatch.setattr('mklink.runtime.request', request)
    monkeypatch.setattr('mklink.discovery.find_microkeen_disk', lambda: pytest.fail('CLI selected a disk directly'))
    monkeypatch.setattr(sys, 'argv', ['mklink', 'copy-flm', '--probe', 'second', '--flm', str(source), '--request-id', 'copy-once'])
    assert cli.main() == int(fail)
    assert len(calls) == 2 and calls[0][1]['probe'] == 'second'
    assert calls[1] == ('POST', '/api/offline-download/algorithm',
                        {'source_path': str(source.resolve()), 'file_name': 'test.FLM', 'request_id': 'copy-once'})
    output = capsys.readouterr().out
    assert 'request_id=copy-once' in output
    if fail:
        assert '不要重新提交' in output

@pytest.mark.parametrize('status,exit_code', [('detected', 0), ('unsupported', 1)])
def test_mcu_detect_cli_uses_read_only_catalog_contract(monkeypatch, capsys, status, exit_code):
    import sys, json
    from mklink import cli
    calls = []
    def inspect(**kwargs):
        calls.append(kwargs)
        return {'status': status, 'device': 'TEST', 'backend': 'flm', 'profile_written': False, 'flm_copied': False}
    monkeypatch.setattr('mklink.mcu_detect.inspect_mcu', inspect)
    monkeypatch.setattr(sys, 'argv', ['mklink', 'mcu-detect', '--device', 'TEST', '--flm', 'algorithm-id', '--json'])
    assert cli.main() == exit_code
    assert calls[0]['flm'] == 'algorithm-id' and calls[0]['read_idcode'] is False
    assert 'write_profile' not in calls[0] and 'copy_flm' not in calls[0]
    assert json.loads(capsys.readouterr().out)['profile_written'] is False
