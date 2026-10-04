from __future__ import annotations

import asyncio

import pytest

from mklink.remote.embedded_agent import (
    EmbeddedAgentSettings,
    EmbeddedSiteAgentController,
)


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


def test_controller_refuses_to_reopen_an_unshared_gui_device(tmp_path):
    async def scenario():
        controller = EmbeddedSiteAgentController(
            EmbeddedAgentSettings(enabled=True, port=0, token='site-secret'),
            project_root=str(tmp_path))
        await controller.start()
        assert controller.status()['ready'] is False
        assert 'physical probe shared runtime' in controller.status()['last_error']
        await controller.stop()
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
