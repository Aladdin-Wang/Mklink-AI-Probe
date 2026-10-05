from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mklink.remote.gui_sessions import install_remote_windows
from mklink.remote.client import RemoteConnectionError

class Client:
    instances = []
    def __init__(self, url, **kwargs):
        self.url, self.calls, self.closed = url, [], False
        self.fail = False
        self.instances.append(self)
    def handshake(self):
        return SimpleNamespace(capabilities={name: SimpleNamespace(available=True,version=version) for name,version in [('gui.bridge','1'),('probe.diagnostics','1'),('target.memory','1'),('target.debug','1'),('stream.rtt','2')]})
    def call(self, method, **params):
        self.calls.append((method,params))
        if self.fail: raise RemoteConnectionError('synthetic disconnect')
        if method == 'agent.connect': return {'connected': True}
        if method == 'probe.info': return {'probe_id': self.url, 'runtime_instance_id': 'test-instance', 'connected': True, 'idcode': 123}
        return {'result': self.url}
    def close(self): self.closed = True

@pytest.fixture
def api():
    Client.instances = []
    app=FastAPI()
    install_remote_windows(app,app,client_factory=Client)
    with TestClient(app) as api: yield api
    assert all(c.closed for c in Client.instances)

def connect(api,url='ws://test:1'):
    r=api.post('/remote-windows',json={'url':url,'token':'secret'})
    assert r.status_code==200,r.text
    assert 'secret' not in r.text
    return '/remote-windows/'+r.json()['id']

def test_isolated_windows_route_to_their_own_clients_and_close_independently(api):
    a,b=connect(api),connect(api,'ws://test:2')
    assert api.get(a).json()['endpoint']=='ws://test:1'
    assert api.get(b).json()['endpoint']=='ws://test:2'
    assert api.post(a+'/close').status_code==200
    assert Client.instances[0].closed and not Client.instances[1].closed
    assert api.get(a).status_code==404
    assert api.get(b).json()['connected']

def test_limits_windows_and_reclaims_capacity(api):
    paths=[connect(api) for _ in range(8)]
    assert api.post('/remote-windows',json={'url':'ws://test:1','token':'secret'}).status_code==429
    api.post(paths[0]+'/close')
    connect(api)
