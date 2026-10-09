"""Tests for SWD DP / IDCODE initialization (``mklink.device.initialize_target``).

Regression coverage for the MCP ``connect`` idcode=0 bug: every target debug
session — ``Device._connect``, ``memory_access.read_memory`` fresh-bridge path,
and the CLI one-shot target ops — must call ``get_idcode()``, write
``_ctx.idcode``, and match the MCU, instead of leaving idcode at 0 (which left
the DAP uninitialized in long-lived sessions and made halt/read return 0).
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from mklink.device import Device, DeviceNotConnectedError, initialize_target


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _bridge():
    """A mock bridge with a writable _ctx (idcode/current_mcu)."""
    bridge = MagicMock()
    ctx = MagicMock()
    ctx.idcode = 0
    ctx.current_mcu = ""
    bridge._ctx = ctx
    return bridge


def _flash(*, idcode=None, raises=None):
    flash = MagicMock()
    if raises is not None:
        flash.get_idcode = MagicMock(side_effect=raises)
    else:
        flash.get_idcode = MagicMock(return_value=idcode)
    return flash


def _api_client_and_state():
    """Build a FastAPI TestClient + its shared _state (mirrors the api tests)."""
    from mklink.remote.api import create_app
    app = create_app(auth_token=None, project_root=".")
    return TestClient(app), app.state.mklink_state


# ----------------------------------------------------------------------
# initialize_target logic
# ----------------------------------------------------------------------

class TestInitializeTarget:
    def test_writes_idcode_and_matches_by_idcode(self):
        bridge = _bridge()
        flash = _flash(idcode=0x2BA01477)
        profiles = {"stm32f4": {"name": "STM32F4", "idcode_pattern": "0x2BA01477"}}
        with patch("mklink.profiles.load_mcu_profiles", return_value=profiles), \
             patch("mklink.project_config.load_config", return_value={}):
            rc = initialize_target(bridge, flash, project_root=".")
        assert rc == 0x2BA01477
        assert bridge._ctx.idcode == 0x2BA01477
        assert bridge._ctx.current_mcu == "STM32F4"
        flash.get_idcode.assert_called_once()

    def test_mcu_hint_wins_over_idcode_match(self):
        """Explicit hint beats idcode match (compatible chips share IDCODE)."""
        bridge = _bridge()
        flash = _flash(idcode=0x2BA01477)
        profiles = {
            "stm32f4": {"name": "STM32F4", "idcode_pattern": "0x2BA01477"},
            "hc32f4a0": {"name": "HC32F4A0", "idcode_pattern": "0x2BA01477"},
        }
        with patch("mklink.profiles.load_mcu_profiles", return_value=profiles), \
             patch("mklink.project_config.load_config", return_value={}):
            initialize_target(bridge, flash, mcu_hint="hc32f4a0", project_root=".")
        assert bridge._ctx.current_mcu == "HC32F4A0"

    def test_config_mcu_key_beats_idcode_match(self):
        bridge = _bridge()
        flash = _flash(idcode=0x2BA01477)
        profiles = {"stm32f4": {"name": "STM32F4", "idcode_pattern": "0x2BA01477"}}
        with patch("mklink.profiles.load_mcu_profiles", return_value=profiles), \
             patch("mklink.project_config.load_config", return_value={"mcu_key": "stm32f4"}):
            initialize_target(bridge, flash, project_root=".")
        assert bridge._ctx.current_mcu == "STM32F4"

    def test_no_profile_match_still_sets_idcode(self):
        bridge = _bridge()
        flash = _flash(idcode=0xDEADBEEF)
        with patch("mklink.profiles.load_mcu_profiles", return_value={}), \
             patch("mklink.project_config.load_config", return_value={}):
            rc = initialize_target(bridge, flash, project_root=".")
        assert rc == 0xDEADBEEF
        assert bridge._ctx.idcode == 0xDEADBEEF

    def test_tolerant_when_get_idcode_fails(self):
        """No target / broken SWD / timeout → return 0, do not raise, leave ctx at 0."""
        bridge = _bridge()
        flash = _flash(raises=RuntimeError("IDCODEError: timeout"))
        rc = initialize_target(bridge, flash, project_root=".")
        assert rc == 0
        assert bridge._ctx.idcode == 0  # unchanged


# ----------------------------------------------------------------------
# Device._connect wires it in
# ----------------------------------------------------------------------

class TestDeviceConnectInitializesTarget:
    @pytest.mark.parametrize('fallback', ['set clock 1000000\r\n', 'Error: busy'])
    def test_saved_high_clock_only_keeps_connection_after_confirmed_fallback(self, fallback):
        from mklink._types import DeviceState
        dev = Device(port='COM6', initialize_target_now=False)
        bridge = MagicMock()
        bridge.connect.return_value = True
        bridge.state = DeviceState.READY
        bridge.idcode = 0x1BA01477
        bridge.send_command.side_effect = ['set clock 20000000', fallback]
        with patch('mklink.bridge.MKLinkSerialBridge', return_value=bridge), \
             patch('mklink.project_config.load_config', return_value={'swd_clock': '20000000'}):
            if fallback.startswith('set clock'):
                dev._connect()
                assert dev.connected
                assert bridge._ctx.swd_clock_hz == 1000000
                assert 'restored 1 MHz' in dev.clock_warning
                dev.close()
            else:
                with pytest.raises(Exception, match='fallback clock'):
                    dev._connect()
                assert not dev.connected
                bridge.close.assert_called_once()

    def test_deferred_connection_applies_saved_clock(self):
        dev = Device(port="COM6", initialize_target_now=False)
        bridge = MagicMock()
        bridge.connect.return_value = True
        bridge.send_command.return_value = 'set clock 4000000\r\n0\r\n'
        with patch('mklink.bridge.MKLinkSerialBridge', return_value=bridge), \
             patch('mklink.project_config.load_config', return_value={'com_port': 'COM6', 'swd_clock': '4000000'}), \
             patch('mklink.device.initialize_target') as initialize:
            dev._connect()
        initialize.assert_not_called()
        bridge.send_command.assert_called_once_with('cmd.set_swd_clock(4000000)', echo=True)
        assert bridge._ctx.swd_clock_hz == 4000000
        dev.close()

    def test_connect_calls_initialize_target(self):
        dev = Device()
        new_bridge = MagicMock()
        new_bridge.connect.return_value = True
        with patch("mklink.bridge.MKLinkSerialBridge", return_value=new_bridge), \
             patch("mklink.project_config.load_config", return_value={"com_port": "COM6"}), \
             patch("mklink.device.initialize_target") as mock_init:
            dev._port = "COM6"
            dev._connect()
        mock_init.assert_called_once()
        args, kwargs = mock_init.call_args
        assert args[0] is new_bridge            # bridge
        assert kwargs.get("project_root") == "."
        assert dev.connected is True

    def test_previously_selected_port_failure_never_scans_or_retries(self, tmp_path):
        bridge = MagicMock()
        bridge.connect.return_value = False
        dev = Device(preferred_port='COM46', project_root=str(tmp_path))
        with patch('mklink.bridge.MKLinkSerialBridge', return_value=bridge) as factory, \
             patch('mklink.discovery.find_mklink_cdc_port') as discover, \
             patch('mklink.project_config.save_config') as save:
            with pytest.raises(DeviceNotConnectedError, match='no fallback'):
                dev._connect()
        factory.assert_called_once_with('COM46')
        bridge.connect.assert_called_once()
        bridge.close.assert_called_once()
        discover.assert_not_called()
        save.assert_not_called()

    def test_explicit_port_does_not_fall_back(self, tmp_path):
        bridge = MagicMock()
        bridge.connect.return_value = False
        dev = Device(port="COM46", project_root=str(tmp_path))

        with patch("mklink.bridge.MKLinkSerialBridge", return_value=bridge), \
             patch("mklink.discovery.find_mklink_cdc_port") as discover, \
             patch("mklink.project_config.load_config", return_value={}):
            with pytest.raises(DeviceNotConnectedError):
                dev._connect()

        discover.assert_not_called()
        assert bridge.connect.call_count == 1


# ----------------------------------------------------------------------
# memory_access fresh-bridge path wires it in
# ----------------------------------------------------------------------

class TestMemoryAccessFreshBridgeInit:
    def test_read_memory_fresh_bridge_initializes_target(self):
        from mklink import memory_access
        fake_bridge = MagicMock()
        fake_bridge.connect.return_value = True
        fake_bridge.send_command.return_value = "20000000  AA BB CC DD"
        with patch("mklink.bridge.MKLinkSerialBridge", return_value=fake_bridge), \
             patch("mklink.cli._resolve_port", return_value="COM7"), \
             patch("mklink.device.initialize_target") as mock_init:
            data, raw = memory_access.read_memory(None, 0x20000000, 4)
        mock_init.assert_called_once()
        assert isinstance(data, bytes)


# ----------------------------------------------------------------------
# API /api/device/connect response shape (now includes idcode/port/axf_loaded)
# ----------------------------------------------------------------------

class TestApiConnectShape:
    @pytest.fixture(autouse=True)
    def isolated_dashboard_managers(self, monkeypatch):
        # Connection preparation mutates the process-local manager catalog.
        # Keep these fake devices out of subsequent API/symbol tests.
        monkeypatch.setattr('mklink.remote.dashboards._managers', {})

    def test_connect_response_includes_idcode_port_axf(self):
        client, _ = _api_client_and_state()
        dev = MagicMock()
        dev.connected = True
        dev.mcu_name = "STM32F40x"
        dev.idcode = 0x2BA01477
        dev.port = "COM5"
        dev._dwarf_info = object()  # truthy → axf_loaded True
        with patch("mklink.connect", return_value=dev):
            resp = client.post("/api/device/connect", json={"port": "COM5"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "connected"
        assert data["idcode"] == hex(0x2BA01477)
        assert data["port"] == "COM5"
        assert data["axf_loaded"] is True

    def test_already_connected_response_includes_idcode_port_axf(self):
        client, state = _api_client_and_state()
        dev = MagicMock()
        dev.connected = True
        dev.mcu_name = "STM32F40x"
        dev.idcode = 0x2BA01477
        dev.port = "COM5"
        dev._dwarf_info = None
        state["device"] = dev
        resp = client.post("/api/device/connect", json={"port": "COM5"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_connected"
        assert data["idcode"] == hex(0x2BA01477)
        assert data["port"] == "COM5"
        assert data["axf_loaded"] is False
