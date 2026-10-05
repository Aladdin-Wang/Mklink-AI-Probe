"""Peripheral adapters use the real shared API and the GUI catalog manager."""
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace
from unittest.mock import Mock, ANY

from fastapi.testclient import TestClient
import pytest

from mklink.remote.api import create_app
from mklink.remote.dashboards import SuperWatchStreamManager
from mklink.remote.resource_manager import ResourceGroup
from mklink.runtime_api import Session, install_runtime
from test_peripheral_watch import SVD


@pytest.fixture
def peripheral(monkeypatch, tmp_path):
    path = tmp_path / 'test.svd'
    path.write_bytes(SVD)
    managers = {name: SimpleNamespace(running=False) for name in ('rtt', 'systemview', 'vofa', 'serial', 'modbus')}
    managers['superwatch'] = SuperWatchStreamManager()
    monkeypatch.setattr('mklink.remote.dashboards.get_managers', lambda: managers)
    app = create_app(project_root=str(tmp_path))
    state = app.state.mklink_state
    device = SimpleNamespace(connected=True, port='COM9', _project_root=str(tmp_path), symbol_catalog=None,
                             axf_status={}, close=Mock(), read_memory=Mock(return_value=b'\x00\x10\x00\x80'),
                             capture_peripherals=Mock(return_value={'channels':['GPIOB.12'],'samples':[[1]]}))
    state['device'] = device
    control = install_runtime(app, {'port':8765, 'token':'fixture', 'instance_id':'fixture'})
    with TestClient(app, base_url='http://127.0.0.1:8765', headers={'X-Auth-Token':'fixture'}) as client:
        assert client.post('/api/dash/superwatch/peripherals/select', json={'svd':str(path)}).status_code == 200
        yield client, control, state, device, managers, path
        managers['superwatch']._running = False
        managers['rtt'].running = False
        state['device'] = None


def test_selection_and_field_reads_use_the_gui_catalog(peripheral):
    client, _, state, device, managers, path = peripheral
    listing = client.get('/api/dash/superwatch/peripherals', params={'q':'GPIOB.12'}).json()
    assert listing == managers['superwatch'].peripheral_catalog('GPIOB.12')
    assert listing['selection']['svd'] == str(path)
    assert listing['items'][0]['bit_offset'] == 12
    response = client.post('/api/device/peripherals/read', json={'names':['GPIOB.12','GPIOB.IDR']})
    assert response.json() == {'values':{'GPIOB.12':1,'GPIOB.IDR':0x80001000}}
    assert device.read_memory.call_args_list == [((0x40010C08,4),),((0x40010C08,4),)]
    assert not state['resource_manager'].get_status()


@pytest.mark.parametrize('names', [[], ['GPIOB.CLEAR'], ['GPIOB.12','gpiob.12'], ['GPIOB.12']*65, [None]])
def test_invalid_or_side_effectful_selection_never_reads_hardware(peripheral, names):
    client, _, state, device, _, _ = peripheral
    response = client.post('/api/device/peripherals/read', json={'names':names})
    assert response.status_code == 422, response.text
    device.read_memory.assert_not_called()
    assert not state['resource_manager'].get_status()


def test_catalog_mutation_requires_other_clients_to_detach(peripheral):
    client, control, state, _, _, path = peripheral
    selection = path.parent / '.mklink/peripheral-selection.json'
    before = selection.read_bytes()
    control.sessions['owner'] = Session(str(path.parent), None)
    control.sessions['other'] = Session(str(path.parent), None)
    body = {'svd':str(path)}
    assert client.post('/api/dash/superwatch/peripherals/select',json=body,headers={'X-MKLink-Session':'owner'}).status_code==409
    assert client.post('/api/dash/superwatch/peripherals/select',json=body).status_code==409
    assert selection.read_bytes()==before
    control.sessions.pop('other')
    assert client.post('/api/dash/superwatch/peripherals/select',json=body,headers={'X-MKLink-Session':'owner'}).status_code==200
    assert list(control.sessions)==['owner'] and not state['resource_manager'].get_status()


def test_capture_rejects_gui_conflict_without_stopping_it_or_replaying(peripheral):
    client, _, state, device, managers, _ = peripheral
    managers['rtt'].running=True
    body={'names':['GPIOB.12'],'duration':.1,'period':.01}
    assert client.post('/api/device/peripherals/capture',json=body).status_code==409
    assert managers['rtt'].running
    device.capture_peripherals.assert_not_called()
    managers['rtt'].running=False
    device.capture_peripherals.side_effect=TimeoutError('unknown capture result')
    assert client.post('/api/device/peripherals/capture',json=body).status_code==500
    device.capture_peripherals.assert_called_once_with(['GPIOB.12'],duration=.1,period=.01,cancelled=ANY)
    assert not state['resource_manager'].get_status()


def test_capture_holds_admission_until_worker_finishes_but_metadata_remains_readable(peripheral):
    client, control, state, device, _, path = peripheral
    entered, release=threading.Event(),threading.Event()
    def capture(*args,**kwargs):
        entered.set()
        assert release.wait(5)
        return {'samples':[[1]]}
    device.capture_peripherals.side_effect=capture
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(client.post,'/api/device/peripherals/capture',json={'names':['GPIOB.12']})
        try:
            assert entered.wait(3) and control.operation_lock.locked()
            assert state['resource_manager'].get_active_lease(ResourceGroup.TARGET_DEBUG) is not None
            assert client.post('/api/dash/superwatch/peripherals/select',json={'svd':str(path)}).status_code==409
            assert client.post('/api/device/peripherals/read',json={'names':['GPIOB.12']}).status_code==409
            assert client.get('/api/dash/superwatch/peripherals',params={'q':'GPIOB.12'}).status_code==200
        finally:
            release.set()
        assert future.result().status_code==200
    assert not control.operation_lock.locked() and not state['resource_manager'].get_status()


@pytest.mark.parametrize('duration,period', [(True,.01), ('1',.01), (1,False), (0,.01), (31,.01), (1,-1)])
def test_capture_rejects_non_numeric_timing_before_device_call(peripheral,duration,period):
    client,_,state,device,_,_=peripheral
    assert client.post('/api/device/peripherals/capture',json={'names':['GPIOB.12'],'duration':duration,'period':period}).status_code==422
    device.capture_peripherals.assert_not_called()
    assert not state['resource_manager'].get_status()


def test_disconnected_capture_holds_admission_until_worker_cleanup(peripheral, monkeypatch):
    import time, asyncio
    from starlette.requests import Request
    client,control,state,device,_,_=peripheral
    entered,disconnect,cleaning,release=(threading.Event() for _ in range(4))
    async def receive_disconnect():
        while not disconnect.is_set():
            await asyncio.sleep(.005)
        return {'type':'http.disconnect'}
    monkeypatch.setattr(Request,'receive',property(lambda self: receive_disconnect))
    def worker(*args,cancelled,**kwargs):
        entered.set()
        deadline=time.monotonic()+5
        while not cancelled():
            assert time.monotonic()<deadline
            time.sleep(.005)
        cleaning.set()
        assert release.wait(5)
        raise InterruptedError('cancelled after cleanup')
    device.capture_peripherals.side_effect=worker
    with ThreadPoolExecutor() as pool:
        result=pool.submit(client.post,'/api/device/peripherals/capture',
                           json={'names':['GPIOB.IDR']})
        assert entered.wait(5)
        try:
            disconnect.set()
            assert cleaning.wait(5)
            assert control.operation_lock.locked()
            assert state['resource_manager'].get_status()
            assert client.post('/api/dash/rtt/start',json={}).status_code==409
        finally:
            release.set()
        response=result.result(timeout=5)
    assert response.status_code==500 and 'cancelled after cleanup' in response.text
    assert not control.operation_lock.locked()
    assert not state['resource_manager'].get_status()

