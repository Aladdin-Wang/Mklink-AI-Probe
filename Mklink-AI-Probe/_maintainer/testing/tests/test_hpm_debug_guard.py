from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mklink.device import Device


@pytest.mark.parametrize('mcu', ['HPM6E80', 'Unknown'])
@pytest.mark.parametrize('method,args', [
    ('halt', ()), ('resume', ()), ('step', ()),
    ('set_breakpoint', (0x80000400,)), ('clear_breakpoint', (0,)),
    ('clear_all_breakpoints', ()), ('read_core_registers', ()),
])
def test_hpm_rejects_cortex_debug_without_target_access(method, args, mcu):
    device = SimpleNamespace(mcu_name=mcu, _require_connected=Mock(), _bridge=Mock(idcode=0x1000563D))
    device._require_cortex_m_debug = lambda: Device._require_cortex_m_debug(device)
    with pytest.raises(ValueError, match='Cortex-M'):
        getattr(Device, method)(device, *args)
    device._require_connected.assert_called_once()
    assert device._bridge.mock_calls == []


@pytest.mark.parametrize('method,implementation', [('halt','halt_cpu'),('resume','resume_cpu'),('step','step_cpu')])
def test_arm_debug_still_dispatches(monkeypatch, method, implementation):
    device = SimpleNamespace(mcu_name='STM32F103RE', _require_connected=Mock(), _bridge=Mock())
    device._require_cortex_m_debug = lambda: Device._require_cortex_m_debug(device)
    operation = Mock(return_value='state')
    monkeypatch.setattr('mklink.debug_control.'+implementation, operation)
    assert getattr(Device, method)(device) == 'state'
    operation.assert_called_once_with(device._bridge)

@pytest.mark.parametrize('mcu', ['HPM6E80', 'Unknown'])
def test_hpm_hardfault_rejected_without_read(mcu):
    device = SimpleNamespace(mcu_name=mcu, _require_connected=Mock(), _bridge=Mock(idcode=0x1000563D), read_memory=Mock())
    with pytest.raises(ValueError, match='Cortex-M'):
        Device.check_hardfault(device)
    device.read_memory.assert_not_called()


def test_shared_hpm_id_rejects_cortex_named_register(monkeypatch):
    device = SimpleNamespace(mcu_name='Unknown', _require_connected=Mock(), _bridge=Mock(idcode=0x1000563D), _project_root=None, read_memory=Mock())
    monkeypatch.setattr('mklink.peripheral_watch.load_catalog', lambda _: None)
    with pytest.raises(ValueError, match='HPM peripheral catalog'):
        Device.read_register(device, 'SCB.CFSR')
    device.read_memory.assert_not_called()

@pytest.mark.parametrize('method,path,body', [
    ('GET','/api/device/hardfault',None),
    ('GET','/api/device/hardfault-detail',None),
    ('POST','/api/device/hardfault-detail',{'fault_regs':{'SCB.CFSR':0,'SCB.HFSR':0}}),
    ('POST','/api/device/hardfault-detail',{'fault_regs':{'SCB.CFSR':65536}}),
])
def test_hpm_fault_http_returns_actionable_rejection(monkeypatch,tmp_path,method,path,body):
    from fastapi.testclient import TestClient
    from mklink.remote.api import create_app
    managers={name:SimpleNamespace(running=False) for name in ('rtt','superwatch','systemview','vofa','serial','modbus')}
    monkeypatch.setattr('mklink.remote.dashboards.get_managers',lambda:managers)
    app=create_app(project_root=str(tmp_path))
    device=Device(project_root=str(tmp_path))
    device._connected=True
    device._bridge=SimpleNamespace(current_mcu='Unknown',idcode=0x1000563D)
    device.read_memory=Mock()
    device.halt=Mock()
    device.close=Mock()
    app.state.mklink_state['device']=device
    with TestClient(app,raise_server_exceptions=False) as client:
        response=client.request(method,path,json=body)
        assert response.status_code==422,response.text
        assert 'Cortex-M' in response.json()['detail']
    device.read_memory.assert_not_called()
    device.halt.assert_not_called()
