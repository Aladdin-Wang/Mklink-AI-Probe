import asyncio
from types import SimpleNamespace
import pytest
from mklink.runtime_idle import check_idle
from mklink.runtime_api import RuntimeControl
from fastapi import FastAPI


def control():
    app=FastAPI();app.state.mklink_state={}
    c=RuntimeControl(app,{})
    c.last_activity=0
    c.shutdown=lambda: setattr(app.state, 'stopped', True)
    return c

def test_no_clients_exits_once_after_grace():
    c=control()
    assert not check_idle(c,now=4)
    assert check_idle(c,now=5)
    assert c.stopping and c.app.state.stopped
    assert not check_idle(c,now=120)

@pytest.mark.parametrize('kind',['gui','session','http','operation','attach','uart','job','remote_window','remote_socket'])
def test_each_owner_protects_backend_and_restarts_grace(kind):
    c=control()
    if kind=='gui':c.views['v']={'expires':float('inf')}
    if kind=='session':c.sessions['s']=SimpleNamespace(expires=float('inf'))
    if kind=='http':c.inflight_requests=1
    if kind=='operation':c.operation_lock=SimpleNamespace(locked=lambda:True)
    if kind=='attach':c.attach_lock=SimpleNamespace(locked=lambda:True)
    if kind=='uart':c.uart_operations['u']='write'
    if kind=='job':c.jobs=SimpleNamespace(active=True)
    if kind=='remote_window':c.app.state.remote_window_activity=lambda:True
    if kind=='remote_socket':c.app.state.site_agent=SimpleNamespace(active_connections=1)
    assert not check_idle(c,now=100)
    if kind not in ('gui','session','remote_window','remote_socket'):
        assert c.last_activity==100
    assert not c.stopping
    c.last_activity=100
    c.views.clear();c.sessions.clear();c.inflight_requests=0;c.uart_operations.clear();c.jobs=None
    c.operation_lock=asyncio.Lock();c.attach_lock=asyncio.Lock()
    c.app.state.remote_window_activity=lambda:False
    c.app.state.site_agent=SimpleNamespace(active_connections=0)
    assert not check_idle(c,now=104)
    assert check_idle(c,now=105)

def test_expired_owners_and_idle_listener_do_not_pin_backend():
    c=control();c.views['expired']={'expires':0}
    c.sessions['expired']=SimpleNamespace(expires=0)
    c.app.state.site_agent=SimpleNamespace(active_connections=0)
    assert check_idle(c,now=5)

def test_no_shutdown_hook_and_failed_activity_check_never_stop():
    c=control();c.shutdown=None
    assert not check_idle(c,now=1000) and not c.stopping
    c=control();c.app.state.remote_window_activity=lambda:1/0
    with pytest.raises(ZeroDivisionError):check_idle(c,now=1000)
    assert not c.stopping

@pytest.mark.parametrize('path,authorized,active', [('/_runtime/status',True,False),('/api/health',True,True),('/api/health',False,False)])
def test_gate_distinguishes_discovery_work_and_unauthorized_requests(path, authorized, active):
    from mklink.runtime_api import RuntimeGate
    c=control();c.info={'port':8765,'instance_id':'test','token':'secret'}
    seen=[]
    async def app(scope, receive, send):
        seen.append(c.inflight_requests)
    async def receive():return {'type':'http.request','body':b''}
    async def send(message):pass
    headers=[(b'host',b'127.0.0.1:8765')]
    if authorized:headers.append((b'x-auth-token',b'secret'))
    asyncio.run(RuntimeGate(app,control=c)({'type':'http','path':path,'method':'GET','headers':headers},receive,send))
    assert c.inflight_requests==0
    assert (c.last_activity>0)==active
    assert seen==([int(active)] if authorized else [])


def test_expired_lease_does_not_add_a_second_idle_grace():
    c=control();c.sessions['dead']=SimpleNamespace(expires=0)
    assert check_idle(c,now=5)


def test_gui_socket_presence_lifecycle(runtime):
    from mklink.runtime_idle import idle_blocked
    client,c,_,_,_=runtime
    with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/first') as a:
        assert a.receive_json()['registered']
        with client.websocket_connect('ws://127.0.0.1:8765/api/runtime/control/view/second') as b:
            assert b.receive_json()['registered']
            c.prune()
            assert len(c.views)==2 and idle_blocked(c)
            response=client.get('/api/runtime/control/status')
            assert response.status_code==200
            assert all(v['expires_in'] is None for v in response.json()['clients'])
        assert set(c.views)=={'first'}
        assert c.inflight_requests==1
    assert not c.views and c.inflight_requests==0

from test_shared_runtime import runtime
