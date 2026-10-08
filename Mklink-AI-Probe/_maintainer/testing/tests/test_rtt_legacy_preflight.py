"""Unsupported legacy requests must fail before admission or stream replacement."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from mklink.device import Device, DeviceError
from mklink.remote import api


@pytest.mark.parametrize('channel,channels', [(0, [0, 1]), (3, None), (7, [7])])
def test_legacy_rtt_rejects_unsupported_channels_without_touching_stream(channel, channels):
    device = object.__new__(Device)
    device._bridge = SimpleNamespace(supports_multiplex=lambda: False)
    device._rtt_session = Mock()
    with pytest.raises(DeviceError, match='select one channel or update'):
        device.validate_rtt_channels(channel, channels)
    device._rtt_session.stop.assert_not_called()


@pytest.mark.parametrize('multiplex,channel,channels', [
    (False, 0, None), (False, 1, [1]), (False, 2, [2]),
    (True, 7, [7]), (True, 0, list(range(8))),
])
def test_supported_rtt_requests_remain_available(multiplex, channel, channels):
    device = object.__new__(Device)
    device._bridge = SimpleNamespace(supports_multiplex=lambda: multiplex)
    device.validate_rtt_channels(channel, channels)


def test_http_legacy_failure_keeps_health_and_existing_capture(tmp_path, monkeypatch):
    app = api.create_app(project_root=str(tmp_path))
    device = SimpleNamespace(connected=True, _axf=None,
                             _bridge=SimpleNamespace(supports_multiplex=lambda: False))
    device.validate_rtt_channels = lambda channel, channels: Device.validate_rtt_channels(device, channel, channels)
    start = Mock(side_effect=AssertionError('invalid request must not acquire or replace a stream'))
    monkeypatch.setattr(api, 'start_dashboard_manager', start)
    with TestClient(app) as client:
        app.state.mklink_state['device'] = device
        try:
            response = client.post('/api/dash/rtt/start', json={'addr': '0x20000000', 'channels': [0, 1]})
            assert response.status_code == 422
            assert 'select one channel or update' in response.json()['detail']
            assert client.get('/api/health').status_code == 200
            start.assert_not_called()
        finally:
            app.state.mklink_state['device'] = None
