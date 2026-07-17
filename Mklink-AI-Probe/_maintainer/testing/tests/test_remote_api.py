"""Regression tests for the FastAPI remote API."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from mklink.dwarf_parser import DwarfInfo, DwarfMember, DwarfStruct, DwarfVariable
from mklink.remote.api import create_app
from mklink.symbol_catalog import SymbolCatalog


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
