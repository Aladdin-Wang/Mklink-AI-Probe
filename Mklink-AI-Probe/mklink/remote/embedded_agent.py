"""Site Agent lifecycle hosted inside the main GUI sidecar process."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from mklink.remote.agent import AgentConfig, SiteAgent
from mklink.remote.dispatcher import OperationDispatcher
from mklink.remote.resource_manager import ResourceManager


def _boolean(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError("Site Agent boolean setting is invalid")


def _port(value: str | None, *, default: int) -> int:
    try:
        result = default if value is None else int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Site Agent port setting is invalid") from exc
    if not 1 <= result <= 65535:
        raise ValueError("Site Agent port setting is invalid")
    return result


@dataclass(frozen=True)
class EmbeddedAgentSettings:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8766
    allow_lan: bool = False
    transport: str = "direct"
    token: str | None = None
    stcp_server_addr: str = ""
    stcp_server_port: int = 7000
    stcp_user: str = ""
    stcp_proxy_name: str = ""
    stcp_auth_token: str | None = None
    stcp_secret: str | None = None
    stcp_library: str | None = None
    configuration_error: str | None = None

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "EmbeddedAgentSettings":
        values = os.environ if environment is None else environment
        configuration_error = (
            "Site Agent configuration or credentials are invalid"
            if values.get("MKLINK_SITE_AGENT_CONFIGURATION_ERROR", "").strip()
            else None
        )
        enabled = _boolean(values.get("MKLINK_SITE_AGENT_ENABLED"))
        if not enabled:
            return cls(configuration_error=configuration_error)
        token = values.get("MKLINK_REMOTE_TOKEN", "").strip()
        if not token:
            raise ValueError("Site Agent access token is not configured")
        transport = values.get("MKLINK_SITE_AGENT_TRANSPORT", "direct").strip()
        settings = cls(
            enabled=True,
            host=values.get("MKLINK_SITE_AGENT_HOST", "127.0.0.1").strip(),
            port=_port(values.get("MKLINK_SITE_AGENT_PORT"), default=8766),
            allow_lan=_boolean(values.get("MKLINK_SITE_AGENT_ALLOW_LAN")),
            transport=transport,
            token=token,
            stcp_server_addr=values.get("MKLINK_STCP_SERVER_ADDR", "").strip(),
            stcp_server_port=_port(
                values.get("MKLINK_STCP_SERVER_PORT"), default=7000,
            ),
            stcp_user=values.get("MKLINK_STCP_USER", "").strip(),
            stcp_proxy_name=values.get("MKLINK_STCP_PROXY_NAME", "").strip(),
            stcp_auth_token=values.get("MKLINK_STCP_AUTH_TOKEN", "").strip() or None,
            stcp_secret=values.get("MKLINK_STCP_SECRET", "").strip() or None,
            stcp_library=values.get("MKLINK_STCP_LIBRARY", "").strip() or None,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        AgentConfig(
            host=self.host,
            port=self.port,
            token=self.token,
            allow_lan=self.allow_lan,
            transport=self.transport,
        )
        if self.transport != "lan-stcp":
            return
        if not self.stcp_auth_token or not self.stcp_secret:
            raise ValueError("LAN STCP credentials are not configured")
        if len({self.token, self.stcp_auth_token, self.stcp_secret}) != 3:
            raise ValueError(
                "Site Agent, FRP authentication, and STCP credentials must be distinct"
            )

    def public(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "allow_lan": self.allow_lan,
            "transport": self.transport,
            "stcp_server_addr": self.stcp_server_addr,
            "stcp_server_port": self.stcp_server_port,
            "stcp_user": self.stcp_user,
            "stcp_proxy_name": self.stcp_proxy_name,
            "token_configured": bool(self.token),
            "stcp_credentials_configured": bool(
                self.stcp_auth_token and self.stcp_secret
            ),
            "configuration_error": self.configuration_error,
        }


class EmbeddedSiteAgentController:
    """Own the listener and tunnel while borrowing GUI device state."""

    def __init__(
        self,
        settings: EmbeddedAgentSettings,
        *,
        project_root: str,
        resource_manager: ResourceManager,
        device_getter: Callable[[], Any | None],
        device_reconnector: Callable[[AgentConfig], Any | None],
    ):
        self.settings = settings
        self.project_root = project_root
        self._resource_manager = resource_manager
        self._device_getter = device_getter
        self._device_reconnector = device_reconnector
        self._agent: SiteAgent | None = None
        self._dispatcher: OperationDispatcher | None = None
        self._transport: Any | None = None
        self._task: asyncio.Task[int] | None = None
        self._last_error: str | None = None
        self._stopping = False

    def _create_transport(self):
        if self.settings.transport != "lan-stcp":
            return None
        from mklink.remote.stcp import STCPProviderConfig, STCPSession

        return STCPSession(
            STCPProviderConfig(
                server_addr=self.settings.stcp_server_addr,
                server_port=self.settings.stcp_server_port,
                auth_token=self.settings.stcp_auth_token or "",
                user=self.settings.stcp_user,
                proxy_name=self.settings.stcp_proxy_name,
                secret_key=self.settings.stcp_secret or "",
                local_addr=self.settings.host,
                local_port=self.settings.port,
            ),
            library=self.settings.stcp_library,
        )

    async def start(self) -> None:
        if not self.settings.enabled or self._task is not None:
            return
        self._dispatcher = OperationDispatcher(self.project_root)
        self._transport = self._create_transport()

        def ready(_status: dict[str, Any]) -> None:
            if self._transport is not None:
                transport_status = self._transport.start()
                if not transport_status.get("ready"):
                    raise RuntimeError("LAN STCP transport did not become ready")

        config = AgentConfig(
            host=self.settings.host,
            port=self.settings.port,
            token=self.settings.token,
            allow_lan=self.settings.allow_lan,
            project_root=self.project_root,
            transport=self.settings.transport,
            transport_status=(
                self._transport.status if self._transport is not None else None
            ),
            ready_callback=ready,
        )
        self._agent = SiteAgent(
            config,
            device_factory=lambda **_kwargs: None,
            capability_provider=self._dispatcher.capabilities,
            request_dispatcher=self._dispatcher.dispatch,
            device_getter=self._device_getter,
            device_reconnector=self._device_reconnector,
            resource_manager=self._resource_manager,
        )
        self._stopping = False
        self._last_error = None
        self._task = asyncio.create_task(self._agent.serve())
        for _ in range(100):
            if self._agent.ready:
                return
            if self._task.done():
                try:
                    self._task.result()
                except BaseException as exc:
                    self._last_error = "Site Agent listener failed to start"
                    raise RuntimeError(self._last_error) from exc
                raise RuntimeError("Site Agent listener stopped during startup")
            await asyncio.sleep(0.01)
        self._last_error = "Site Agent listener startup timed out"
        await self.stop()
        raise RuntimeError(self._last_error)

    async def stop(self) -> None:
        self._stopping = True
        task, agent = self._task, self._agent
        if agent is not None:
            agent.request_stop()
        if task is not None:
            try:
                await task
            except BaseException:
                if self._last_error is None:
                    self._last_error = "Site Agent listener stopped unexpectedly"
        if self._transport is not None:
            self._transport.close()
        if self._dispatcher is not None:
            self._dispatcher.close()
        self._task = None
        self._agent = None
        self._transport = None
        self._dispatcher = None

    def status(self) -> dict[str, Any]:
        result = self.settings.public()
        if not self.settings.enabled:
            return {
                **result,
                "running": False,
                "ready": False,
                "probe_connected": False,
                "last_error": self.settings.configuration_error,
            }
        task = self._task
        if task is not None and task.done() and self._last_error is None:
            try:
                task.result()
            except BaseException:
                self._last_error = "Site Agent listener stopped unexpectedly"
            else:
                if not self._stopping:
                    self._last_error = "Site Agent listener stopped unexpectedly"
        agent_status = self._agent.status() if self._agent is not None else {}
        return {
            **result,
            "ready": False,
            "listener": False,
            "probe_connected": False,
            **agent_status,
            "running": bool(task is not None and not task.done()),
            "last_error": self._last_error or agent_status.get("last_error"),
        }


__all__ = ["EmbeddedAgentSettings", "EmbeddedSiteAgentController"]
