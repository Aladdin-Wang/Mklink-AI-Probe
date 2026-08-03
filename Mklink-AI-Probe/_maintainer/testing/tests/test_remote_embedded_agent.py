from __future__ import annotations

import asyncio

import pytest

from mklink.remote.embedded_agent import (
    EmbeddedAgentSettings,
    EmbeddedSiteAgentController,
)
from mklink.remote.resource_manager import ResourceManager


class _Device:
    connected = True

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_disabled_environment_does_not_require_or_expose_credentials():
    settings = EmbeddedAgentSettings.from_environment({})

    assert settings.enabled is False
    assert settings.public()["token_configured"] is False
    assert "token" not in settings.public()


def test_configuration_error_environment_is_reduced_to_a_safe_message():
    settings = EmbeddedAgentSettings.from_environment(
        {"MKLINK_SITE_AGENT_CONFIGURATION_ERROR": "secret filesystem detail"}
    )

    assert settings.configuration_error == (
        "Site Agent configuration or credentials are invalid"
    )
    assert "secret filesystem detail" not in repr(settings.public())


def test_enabled_environment_validates_and_redacts_credentials():
    settings = EmbeddedAgentSettings.from_environment(
        {
            "MKLINK_SITE_AGENT_ENABLED": "true",
            "MKLINK_SITE_AGENT_HOST": "127.0.0.1",
            "MKLINK_SITE_AGENT_PORT": "9876",
            "MKLINK_REMOTE_TOKEN": "site-secret",
        }
    )

    assert settings.enabled is True
    assert settings.port == 9876
    assert settings.public()["token_configured"] is True
    assert "site-secret" not in repr(settings.public())


@pytest.mark.parametrize("value", ["maybe", "2", "enabled"])
def test_environment_rejects_ambiguous_boolean_values(value):
    with pytest.raises(ValueError, match="boolean"):
        EmbeddedAgentSettings.from_environment(
            {"MKLINK_SITE_AGENT_ENABLED": value}
        )


def test_embedded_controller_runs_with_shared_gui_device_and_resources(tmp_path):
    async def scenario():
        device = _Device()
        shared = {"device": device}
        resources = ResourceManager()
        controller = EmbeddedSiteAgentController(
            EmbeddedAgentSettings(
                enabled=True,
                port=0,
                token="site-secret",
            ),
            project_root=str(tmp_path),
            resource_manager=resources,
            device_getter=lambda: shared["device"],
            device_reconnector=lambda _config: shared["device"],
        )

        await controller.start()
        status = controller.status()
        assert status["running"] is True
        assert status["ready"] is True
        assert status["probe_connected"] is True
        assert "site-secret" not in repr(status)

        await controller.stop()
        assert device.closed is False
        assert controller.status()["running"] is False

    asyncio.run(scenario())


def test_main_api_exposes_sanitized_site_agent_status(monkeypatch):
    from fastapi.testclient import TestClient
    from mklink.remote.api import create_app

    monkeypatch.setenv("MKLINK_SITE_AGENT_ENABLED", "0")
    monkeypatch.delenv("MKLINK_SITE_AGENT_CONFIGURATION_ERROR", raising=False)
    app = create_app(auth_token=None, project_root=".")

    with TestClient(app) as client:
        response = client.get("/api/site-agent/status")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 8766,
        "allow_lan": False,
        "transport": "direct",
        "stcp_server_addr": "",
        "stcp_server_port": 7000,
        "stcp_user": "",
        "stcp_proxy_name": "",
        "token_configured": False,
        "stcp_credentials_configured": False,
        "configuration_error": None,
        "running": False,
        "ready": False,
        "probe_connected": False,
        "last_error": None,
    }
