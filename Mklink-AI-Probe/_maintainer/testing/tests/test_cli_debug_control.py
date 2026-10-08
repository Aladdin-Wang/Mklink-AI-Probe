"""Migrated debug CLI must never instantiate a direct serial bridge."""
import sys
import pytest
from mklink import cli, runtime_cli


@pytest.mark.parametrize('argv, capability, arguments', [
    (['read-reg','SCB.CPUID'], 'register_snapshot', {'register':'SCB.CPUID','address':None,'width':32,'count':1,'raw':False}),
    (['hardfault'], 'fault_snapshot', {'sp':None}),
    (['break','--status'], 'breakpoints', {'action':'status'}),
    (['break','--list'], 'breakpoints', {'action':'list'}),
    (['break','--clear'], 'breakpoints', {'action':'clear_all'}),
    (['break','--clear','2'], 'breakpoints', {'action':'clear','slot':2}),
    (['break','main','--slot','1'], 'breakpoints', {'action':'set','target':'main','slot':1}),
])
def test_commands_use_selected_shared_backend(monkeypatch, argv, capability, arguments):
    calls=[]
    class Client:
        def __init__(self, **kwargs): pass
        def connect(self, **kwargs): calls.append(('connect',kwargs))
        def call(self, name, args):
            calls.append((name,args))
            return {'name':'SCB.CPUID','address':0xe000ed00,'values':[0x411fc231], 'data_hex':'31c21f41', 'report':'fault snapshot'}
        def close(self): calls.append(('close',None))
    monkeypatch.setattr(runtime_cli,'RuntimeClient',Client)
    monkeypatch.setattr('mklink.bridge.MKLinkSerialBridge',lambda *a,**k:pytest.fail('direct serial opened'))
    monkeypatch.setattr(sys,'argv',['mklink',*argv,'--probe','chosen'])
    cli.main()
    assert calls[0][1]['probe']=='chosen'
    assert calls[1]==(capability,arguments)
    assert calls[-1]==('close',None)


@pytest.mark.parametrize('argv', [
    ['break'], ['break','main','--clear'], ['break','--list','--status'],
    ['break','--clear','-1'], ['break','--clear','wrong'], ['break','--list','--slot','2'],
    ['read-reg'], ['read-reg','SCB.CPUID','--addr','0'], ['read-reg','--addr','0','--count','1025'],
    ['read-reg','SCB.CPUID','--width','8'],
])
def test_invalid_cli_options_do_not_connect(monkeypatch,argv):
    monkeypatch.setattr(runtime_cli,'RuntimeClient',lambda **k:pytest.fail('connected'))
    monkeypatch.setattr(sys,'argv',['mklink',*argv])
    with pytest.raises(SystemExit):cli.main()
