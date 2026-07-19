"""Regression tests for the FastAPI remote API."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from mklink.dwarf_parser import DwarfInfo, DwarfMember, DwarfStruct, DwarfVariable
from mklink.remote.api import create_app
from mklink.symbol_catalog import SymbolCatalog


def _route_endpoint(app, path):
    return next(route.endpoint for route in app.routes if route.path == path)


def _request(client, path, responses, key):
    try:
        responses[key] = client.get(path)
    except BaseException as exc:  # Preserve failures raised in request threads.
        responses[key] = exc


def test_port_discovery_does_not_block_health_check():
    discovery_started = threading.Event()
    release_discovery = threading.Event()
    responses = {}

    def blocking_discovery():
        discovery_started.set()
        assert release_discovery.wait(timeout=2)
        return "COM42"

    app = create_app(auth_token=None, project_root=".")
    with patch(
        "mklink.discovery.find_mklink_cdc_port",
        side_effect=blocking_discovery,
    ), TestClient(app, raise_server_exceptions=False) as client:
        discover_thread = threading.Thread(
            target=_request,
            args=(client, "/api/ports/discover", responses, "discover"),
        )
        health_thread = threading.Thread(
            target=_request,
            args=(client, "/api/health", responses, "health"),
        )
        discover_thread.start()
        try:
            assert discovery_started.wait(timeout=1)
            health_thread.start()
            health_thread.join(timeout=0.5)
            assert not health_thread.is_alive(), (
                "health check was blocked by port discovery"
            )
        finally:
            release_discovery.set()
            discover_thread.join(timeout=2)
            if health_thread.ident is not None:
                health_thread.join(timeout=2)

        assert not discover_thread.is_alive()
        assert not health_thread.is_alive()
        assert responses["health"].status_code == 200
        assert responses["health"].json()["status"] == "ok"
        assert responses["discover"].status_code == 200
        assert responses["discover"].json() == {"port": "COM42"}


def test_port_discovery_failure_returns_500_and_server_remains_healthy():
    app = create_app(auth_token=None, project_root=".")
    with patch(
        "mklink.discovery.find_mklink_cdc_port",
        side_effect=RuntimeError("scan failed"),
    ), TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/ports/discover")
        health = client.get("/api/health")

    assert response.status_code == 500
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_config_api_rejects_swd_clock_above_10_mhz(tmp_path):
    app = create_app(auth_token=None, project_root=str(tmp_path))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put("/api/config", json={"swd_clock": "10000001"})

    assert response.status_code == 422
    assert "10 MHz" in response.json()["detail"]


def test_rtt_find_uses_explicit_source_without_persisting_project_config(tmp_path):
    source = tmp_path / "firmware.axf"
    result = SimpleNamespace(
        addr="0x20001A40",
        source="binary:firmware.axf",
        details=["resolved _SEGGER_RTT"],
        warnings=["symbol tool fallback used"],
    )
    with patch(
        "mklink.rtt_addr.diagnose_rtt_addr", return_value=result,
    ) as diagnose, patch(
        "mklink.project_config.load_keil_project",
        side_effect=AssertionError("explicit source must bypass project discovery"),
    ), patch("mklink.project_config.save_rtt_config") as save_rtt_config:
        app = create_app(auth_token=None, project_root=str(tmp_path))
        with TestClient(app) as client:
            response = client.post(
                "/api/rtt-find", json={"source_path": str(source)},
            )

    assert response.status_code == 200
    assert response.json() == {
        "found": True,
        "addr": "0x20001A40",
        "source": "binary:firmware.axf",
        "source_path": str(source),
        "details": ["resolved _SEGGER_RTT"],
        "warnings": ["symbol tool fallback used"],
    }
    diagnose.assert_called_once_with(str(source))
    save_rtt_config.assert_not_called()


def test_rtt_find_runs_symbol_diagnosis_outside_the_event_loop_thread(tmp_path):
    result = SimpleNamespace(
        addr="0x20001A40", source="binary:firmware.axf", details=[], warnings=[],
    )
    call_threads = []

    def diagnose(_path):
        call_threads.append(threading.get_ident())
        return result

    app = create_app(auth_token=None, project_root=str(tmp_path))
    endpoint = _route_endpoint(app, "/api/rtt-find")
    event_loop_thread = threading.get_ident()
    with patch("mklink.rtt_addr.diagnose_rtt_addr", side_effect=diagnose):
        response = asyncio.run(endpoint(source_path="firmware.axf"))

    assert response["found"] is True
    assert call_threads == [call_threads[0]]
    assert call_threads[0] != event_loop_thread


def test_rtt_find_explicit_map_returns_parser_details_without_persisting(tmp_path):
    source = tmp_path / "firmware.map"
    result = SimpleNamespace(
        addr=None,
        source="",
        details=["未找到 _SEGGER_RTT 地址"],
        warnings=["检查链接输出"],
    )
    with patch(
        "mklink.rtt_addr.diagnose_rtt_addr", return_value=result,
    ) as diagnose, patch("mklink.project_config.save_rtt_config") as save_rtt_config:
        app = create_app(auth_token=None, project_root=str(tmp_path))
        with TestClient(app) as client:
            response = client.post(
                "/api/rtt-find", json={"source_path": str(source)},
            )

    assert response.status_code == 200
    assert response.json() == {
        "found": False,
        "addr": None,
        "source": "",
        "source_path": str(source),
        "details": ["未找到 _SEGGER_RTT 地址"],
        "warnings": ["检查链接输出"],
    }
    diagnose.assert_called_once_with(str(source))
    save_rtt_config.assert_not_called()


def test_rtt_find_explicit_missing_file_returns_actionable_details(tmp_path):
    source = tmp_path / "missing.map"
    app = create_app(auth_token=None, project_root=str(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/rtt-find", json={"source_path": str(source)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False
    assert body["source_path"] == str(source)
    assert any("文件不存在" in detail for detail in body["details"])


def test_rtt_find_without_source_preserves_project_discovery_and_persistence(tmp_path):
    map_path = tmp_path / "firmware.map"
    result = SimpleNamespace(
        addr="0x20001A40",
        source="map:firmware.map",
        details=["resolved _SEGGER_RTT"],
        warnings=[],
    )
    with patch(
        "mklink.project_config.load_keil_project",
        return_value={"map_path": str(map_path)},
    ), patch(
        "mklink.rtt_addr.diagnose_rtt_addr", return_value=result,
    ) as diagnose, patch(
        "mklink.project_config.load_rtt_config", return_value={"mode": 0},
    ), patch("mklink.project_config.save_rtt_config") as save_rtt_config:
        app = create_app(auth_token=None, project_root=str(tmp_path))
        with TestClient(app) as client:
            response = client.post("/api/rtt-find")

    assert response.status_code == 200
    assert response.json() == {
        "found": True,
        "addr": "0x20001A40",
        "source": "map:firmware.map",
        "source_path": str(map_path),
        "details": ["resolved _SEGGER_RTT"],
        "warnings": [],
        "map_path": str(map_path),
    }
    diagnose.assert_called_once_with(str(map_path))
    save_rtt_config.assert_called_once_with(
        str(tmp_path), {"mode": 0, "rtt_addr": "0x20001A40"},
    )


def _connected_symbol_device(tmp_path):
    axf = tmp_path / "app.axf"
    axf.write_bytes(b"axf")
    dwarf = DwarfInfo(
        base_types={1: ("float", 4), 2: ("bool", 1)},
        structs={
            "Controller": DwarfStruct(
                "Controller",
                3,
                8,
                [
                    DwarfMember("target", 0, 1, "float", 4),
                    DwarfMember("enabled", 4, 2, "bool", 1),
                ],
            )
        },
        variables={
            "gain": DwarfVariable("gain", 10, 1, 0x20000010, 4, "float"),
            "controller": DwarfVariable("controller", 11, 3, 0x20000020, 8, "Controller"),
        },
    )
    catalog = SymbolCatalog.from_dwarf(
        dwarf,
        axf_path=str(axf),
        ram_ranges=[(0x20000000, 0x20010000)],
    )
    device = SimpleNamespace(
        connected=True,
        state=SimpleNamespace(name="READY"),
        mcu_name="STM32F103RC",
        idcode=0x1234,
        port="redacted",
        axf_status={"loaded": True},
        symbol_catalog=catalog,
        close=lambda: None,
    )
    device.parse_axf = lambda _path=None: {"loaded": True, "catalog_generation": catalog.generation}
    return device, axf


def test_symbol_catalog_api_lists_valid_variables_immediately(tmp_path):
    device, _axf = _connected_symbol_device(tmp_path)
    app = create_app(auth_token=None, project_root=".")

    with patch("mklink.connect", return_value=device), TestClient(app) as client:
        assert client.post("/api/device/connect", json={}).status_code == 200
        response = client.get("/api/symbols/catalog?limit=100")

    assert response.status_code == 200
    body = response.json()
    assert body["generation"] == 1
    assert [item["path"] for item in body["items"]] == [
        "controller.enabled", "controller.target", "gain",
    ]


def test_symbol_status_marks_changed_axf_stale(tmp_path):
    device, axf = _connected_symbol_device(tmp_path)
    app = create_app(auth_token=None, project_root=".")

    with patch("mklink.connect", return_value=device), TestClient(app) as client:
        assert client.post("/api/device/connect", json={}).status_code == 200
        time.sleep(0.01)
        axf.write_bytes(b"changed")
        response = client.get("/api/symbols/status")

    assert response.status_code == 200
    assert response.json()["stale"] is True


def test_superwatch_typed_write_route_passes_path_generation_and_value(tmp_path):
    from mklink.remote.dashboards import get_managers

    device, _axf = _connected_symbol_device(tmp_path)
    manager = get_managers()["superwatch"]
    manager._device = device
    app = create_app(auth_token=None, project_root=".")
    result = {"path": "gain", "generation": 1, "value": 1.5, "verified": True}

    with patch("mklink.connect", return_value=device), patch.object(
        manager, "write_symbol", return_value=result
    ) as write_symbol, TestClient(app) as client:
        assert client.post("/api/device/connect", json={}).status_code == 200
        response = client.post(
            "/api/dash/superwatch/write",
            json={"path": "gain", "generation": 1, "value": 1.5},
        )

    assert response.status_code == 200
    assert response.json() == result
    write_symbol.assert_called_once_with("gain", generation=1, value=1.5)


def test_superwatch_typed_write_reports_transaction_phase(tmp_path):
    from mklink.remote.dashboards import SuperWatchTransactionError, get_managers

    device, _axf = _connected_symbol_device(tmp_path)
    manager = get_managers()["superwatch"]
    manager._device = device
    app = create_app(auth_token=None, project_root=".")

    with patch("mklink.connect", return_value=device), patch.object(
        manager,
        "write_symbol",
        side_effect=SuperWatchTransactionError("write", RuntimeError("flush failed")),
    ), TestClient(app) as client:
        assert client.post("/api/device/connect", json={}).status_code == 200
        response = client.post(
            "/api/dash/superwatch/write",
            json={"path": "gain", "generation": 1, "value": 2.0},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "superwatch_transaction_failed",
        "phase": "write",
        "message": "flush failed",
    }


def test_symbol_reparse_uses_superwatch_transaction_when_prepared(tmp_path):
    from mklink.remote.dashboards import get_managers

    device, _axf = _connected_symbol_device(tmp_path)
    manager = get_managers()["superwatch"]
    manager._device = device
    manager._runtime = SimpleNamespace(items=[])
    app = create_app(auth_token=None, project_root=".")
    summary = {"preserved": ["gain"], "updated": [], "removed": []}

    with patch("mklink.connect", return_value=device), patch.object(
        manager, "reparse_symbols", return_value=summary
    ) as reparse, TestClient(app) as client:
        assert client.post("/api/device/connect", json={}).status_code == 200
        response = client.post("/api/symbols/reparse")

    assert response.status_code == 200
    assert response.json() == summary
    reparse.assert_called_once_with()
