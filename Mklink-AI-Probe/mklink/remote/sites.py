"""Named direct-site registry and isolated per-site client pool."""

from __future__ import annotations

import json
import inspect
import os
import re
import secrets
import stat
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from mklink.remote.client import RemoteClient, connect_remote, validate_endpoint
from mklink.remote.transfer import (
    enforce_owner_only_permissions,
    has_owner_only_permissions,
)


_SITE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_PROJECT_POINTER = Path(".mklink") / "remote.json"


class SiteError(Exception):
    """A redacted public site-registry or connection-pool error."""


@dataclass(frozen=True)
class SiteConfig:
    name: str
    url: str
    token: str = field(repr=False)
    note: str = ""

    def storage_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "token": self.token,
            "note": self.note,
        }

    def public_dict(self, *, active: bool, connected: bool) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "note": self.note,
            "active": active,
            "connected": connected,
            "token_configured": bool(self.token),
        }


def default_sites_path(environment: Mapping[str, str] | None = None) -> Path:
    """Return an OS user-data path and never a package/source directory."""

    env = os.environ if environment is None else environment
    if sys.platform == "win32":
        base = env.get("LOCALAPPDATA") or env.get("APPDATA")
        if base:
            return Path(base) / "MKLink" / "remote" / "sites.json"
        return Path.home() / "AppData" / "Local" / "MKLink" / "remote" / "sites.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MKLink" / "remote" / "sites.json"
    base = env.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "mklink" / "remote" / "sites.json"
    return Path.home() / ".local" / "share" / "mklink" / "remote" / "sites.json"


def _restrict(path: Path, *, directory: bool = False) -> None:
    enforce_owner_only_permissions(path, directory=directory)


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not _SITE_NAME_RE.fullmatch(name):
        raise ValueError("site name must be 1-64 letters, digits, dots, underscores, or hyphens")
    return name


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _restrict(path.parent, directory=True)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(
        str(temporary),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    try:
        _restrict(temporary)
    except Exception:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            try:
                os.fsync(output.fileno())
            except OSError:
                pass
        os.replace(temporary, path)
        _restrict(path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class SiteRegistry:
    """Persist direct sites and serialize calls independently per site."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        client_factory: Callable[..., RemoteClient] = connect_remote,
        timeout: float = 10.0,
    ):
        self.path = (default_sites_path() if path is None else Path(path)).expanduser().resolve()
        self._client_factory = client_factory
        self._timeout = float(timeout)
        self._sites: dict[str, SiteConfig] = {}
        self._active: str | None = None
        self._clients: dict[str, RemoteClient] = {}
        self._site_locks: dict[str, threading.RLock] = {}
        self._lock = threading.RLock()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if not self.path.is_file():
                self._sites = {}
                self._active = None
                return
            try:
                value = json.loads(self.path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SiteError("Unable to load the site registry") from exc
            if not isinstance(value, Mapping) or not isinstance(value.get("sites", []), list):
                raise SiteError("Invalid site registry")
            loaded: dict[str, SiteConfig] = {}
            try:
                for item in value.get("sites", []):
                    if not isinstance(item, Mapping):
                        raise ValueError
                    config = SiteConfig(
                        name=_validate_name(item.get("name")),
                        url=validate_endpoint(item.get("url")),
                        token=str(item.get("token", "")),
                        note=str(item.get("note", "")),
                    )
                    if not config.token:
                        raise ValueError
                    loaded[config.name] = config
            except (TypeError, ValueError) as exc:
                raise SiteError("Invalid site registry") from exc
            active = value.get("active")
            self._sites = loaded
            self._active = active if isinstance(active, str) and active in loaded else None
            _restrict(self.path.parent, directory=True)
            _restrict(self.path)

    @property
    def active(self) -> str | None:
        with self._lock:
            return self._active

    def add(
        self,
        name: str,
        url: str,
        token: str,
        *,
        note: str = "",
        make_active: bool | None = None,
    ) -> dict[str, Any]:
        name = _validate_name(name)
        url = validate_endpoint(url)
        if not isinstance(token, str) or not token:
            raise ValueError("site token is required")
        config = SiteConfig(name=name, url=url, token=token, note=str(note))
        lock = self._lock_for(name)
        with lock:
            with self._lock:
                overwrote = name in self._sites
                old_client = self._clients.pop(name, None)
                self._sites[name] = config
                selected = (
                    self._active is None
                    if make_active is None
                    else bool(make_active)
                )
                if selected:
                    self._active = name
                self._persist_locked()
            if old_client is not None:
                old_client.close()
        return {
            "added": True,
            "name": name,
            "overwrote": overwrote,
            "active": self._active == name,
        }

    def remove(self, name: str) -> dict[str, Any]:
        name = _validate_name(name)
        lock = self._lock_for(name)
        with lock:
            with self._lock:
                if name not in self._sites:
                    raise SiteError(f"Site '{name}' doesn't exist")
                was_active = self._active == name
                client = self._clients.pop(name, None)
                del self._sites[name]
                if was_active:
                    self._active = None
                self._persist_locked()
            if client is not None:
                client.close()
        return {"removed": True, "name": name, "was_active": was_active}

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                config.public_dict(
                    active=name == self._active,
                    connected=bool(
                        self._clients.get(name)
                        and self._clients[name].connected
                    ),
                )
                for name, config in sorted(self._sites.items())
            ]

    def get(self, name: str | None = None, *, project_root: Path | None = None) -> SiteConfig:
        target = self.resolve_name(name, project_root=project_root)
        with self._lock:
            config = self._sites.get(target)
            if config is None:
                raise SiteError(f"Site '{target}' doesn't exist")
            return config

    def resolve_name(self, name: str | None = None, *, project_root: Path | None = None) -> str:
        if name:
            return _validate_name(name)
        if project_root is not None:
            pointed = self.read_project_site(project_root)
            with self._lock:
                if pointed in self._sites:
                    return pointed
        with self._lock:
            if self._active is None:
                raise SiteError("No active site is configured")
            return self._active

    def switch(self, name: str, *, connect: bool = False) -> dict[str, Any]:
        name = _validate_name(name)
        with self._lock:
            if name not in self._sites:
                raise SiteError(f"Site '{name}' doesn't exist")
            changed = self._active != name
            self._active = name
            self._persist_locked()
            url = self._sites[name].url
        connected = False
        if connect:
            connected = self.client(name).connected
        else:
            with self._lock:
                existing = self._clients.get(name)
                connected = bool(existing and existing.connected)
        return {
            "switched": changed,
            "name": name,
            "url": url,
            "connected": connected,
        }

    def client(self, name: str | None = None, *, project_root: Path | None = None) -> RemoteClient:
        target = self.resolve_name(name, project_root=project_root)
        lock = self._lock_for(target)
        with lock:
            with self._lock:
                config = self._sites.get(target)
                if config is None:
                    raise SiteError(f"Site '{target}' doesn't exist")
                current = self._clients.get(target)
            if current is not None and current.connected:
                return current
            if current is not None:
                current.close()
            try:
                parameters = inspect.signature(self._client_factory).parameters.values()
                accepts_timeout = any(
                    parameter.name == "timeout"
                    or parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                )
                kwargs: dict[str, Any] = {"token": config.token}
                if accepts_timeout:
                    kwargs["timeout"] = self._timeout
                created = self._client_factory(config.url, **kwargs)
            except Exception as exc:
                raise SiteError(f"Unable to connect site '{target}'") from exc
            with self._lock:
                if target not in self._sites:
                    created.close()
                    raise SiteError(f"Site '{target}' was removed")
                self._clients[target] = created
            return created

    def call(
        self,
        name: str | None,
        method: str,
        *,
        project_root: Path | None = None,
        **params: Any,
    ) -> Any:
        target = self.resolve_name(name, project_root=project_root)
        lock = self._lock_for(target)
        with lock:
            client = self.client(target)
            try:
                return client.call(method, **params)
            except Exception:
                with self._lock:
                    if self._clients.get(target) is client:
                        self._clients.pop(target, None)
                client.close()
                raise

    def reconnect(self, name: str | None = None) -> RemoteClient:
        target = self.resolve_name(name)
        lock = self._lock_for(target)
        with lock:
            with self._lock:
                old_client = self._clients.pop(target, None)
            if old_client is not None:
                old_client.close()
            return self.client(target)

    def close_site(self, name: str) -> None:
        name = _validate_name(name)
        lock = self._lock_for(name)
        with lock:
            with self._lock:
                client = self._clients.pop(name, None)
            if client is not None:
                client.close()

    def close(self) -> None:
        with self._lock:
            names = list(self._clients)
        for name in names:
            self.close_site(name)

    def write_project_site(self, project_root: Path, name: str) -> dict[str, Any]:
        name = _validate_name(name)
        with self._lock:
            if name not in self._sites:
                raise SiteError(f"Site '{name}' doesn't exist")
        root = Path(project_root).expanduser().resolve()
        pointer = root / _PROJECT_POINTER
        _atomic_json(pointer, {"active_site": name})
        ignored = self._ensure_gitignored(root, _PROJECT_POINTER.as_posix())
        return {
            "site": name,
            "project_file": str(pointer),
            "gitignore_updated": ignored,
        }

    @staticmethod
    def read_project_site(project_root: Path) -> str | None:
        pointer = Path(project_root).expanduser().resolve() / _PROJECT_POINTER
        if not pointer.is_file():
            return None
        try:
            value = json.loads(pointer.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        name = value.get("active_site") if isinstance(value, Mapping) else None
        return name if isinstance(name, str) and _SITE_NAME_RE.fullmatch(name) else None

    def _lock_for(self, name: str) -> threading.RLock:
        with self._lock:
            lock = self._site_locks.get(name)
            if lock is None:
                lock = threading.RLock()
                self._site_locks[name] = lock
            return lock

    def _persist_locked(self) -> None:
        _atomic_json(
            self.path,
            {
                "version": 1,
                "active": self._active,
                "sites": [
                    config.storage_dict()
                    for _, config in sorted(self._sites.items())
                ],
            },
        )

    @staticmethod
    def _ensure_gitignored(root: Path, entry: str) -> bool:
        if not (root / ".git").exists():
            return False
        ignore_file = root / ".gitignore"
        try:
            existing = (
                ignore_file.read_text(encoding="utf-8")
                if ignore_file.is_file()
                else ""
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise SiteError("Unable to read project .gitignore") from exc
        lines = {line.strip() for line in existing.splitlines()}
        if entry in lines:
            return False
        separator = "" if not existing or existing.endswith("\n") else "\n"
        try:
            with ignore_file.open("a", encoding="utf-8") as output:
                output.write(f"{separator}{entry}\n")
        except OSError as exc:
            raise SiteError("Unable to update project .gitignore") from exc
        return True


_DEFAULT: SiteRegistry | None = None
_DEFAULT_LOCK = threading.RLock()


def default_registry() -> SiteRegistry:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = SiteRegistry()
        return _DEFAULT


def bootstrap() -> None:
    default_registry().reload()


def add_site(name: str, url: str, token: str, note: str = "") -> dict[str, Any]:
    return default_registry().add(name, url, token, note=note)


def remove_site(name: str) -> dict[str, Any]:
    return default_registry().remove(name)


def list_sites() -> list[dict[str, Any]]:
    return default_registry().list()


def switch_site(name: str, connect: bool = False) -> dict[str, Any]:
    return default_registry().switch(name, connect=connect)


def use_site(name: str, project_root: Path | str = ".") -> dict[str, Any]:
    return default_registry().write_project_site(Path(project_root), name)


def get_device(site: str | None = None) -> RemoteClient:
    return default_registry().client(site)


def rpc(method: str, site: str = "", **params: Any) -> Any:
    return default_registry().call(site or None, method, **params)


def serve_call(method: str, site: str = "", **params: Any) -> Any:
    return rpc(method, site=site, **params)


def current_site(site: str = "") -> dict[str, Any]:
    registry = default_registry()
    config = registry.get(site or None)
    matching = next(item for item in registry.list() if item["name"] == config.name)
    return matching


def close_all() -> None:
    default_registry().close()


__all__ = [
    "SiteConfig",
    "SiteError",
    "SiteRegistry",
    "add_site",
    "bootstrap",
    "close_all",
    "current_site",
    "default_registry",
    "default_sites_path",
    "get_device",
    "has_owner_only_permissions",
    "list_sites",
    "remove_site",
    "rpc",
    "serve_call",
    "switch_site",
    "use_site",
]
