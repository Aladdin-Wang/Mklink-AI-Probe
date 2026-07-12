"""Regression tests for the FastAPI remote API."""

from __future__ import annotations

import threading
from unittest.mock import patch

from fastapi.testclient import TestClient

from mklink.remote.api import create_app


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
