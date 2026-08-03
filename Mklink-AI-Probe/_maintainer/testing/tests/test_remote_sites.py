"""Black-box site registry, pointer, privacy, and isolation contracts."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import threading
from pathlib import Path

import pytest

from mklink.remote.sites import SiteError, SiteRegistry, default_sites_path


class _Client:
    def __init__(self, url, *, token, timeout=0):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.connected = True
        self.closed = False
        self.calls = []

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "fail":
            raise RuntimeError("site-side failure")
        return {"site": self.url, "method": method, "params": params}

    def close(self):
        self.closed = True
        self.connected = False


def _factory(created):
    def create(url, *, token, timeout=0):
        client = _Client(url, token=token, timeout=timeout)
        created.append(client)
        return client

    return create


def _windows_acl(path: Path) -> dict:
    environment = os.environ.copy()
    # Windows PowerShell 5.1 cannot load PowerShell 7's Security module.
    for name in tuple(environment):
        if name.casefold() == "psmodulepath":
            environment.pop(name)
    environment["MKLINK_TEST_ACL_PATH"] = str(path)
    script = r"""
$ErrorActionPreference = "Stop"
$acl = Get-Acl -LiteralPath $env:MKLINK_TEST_ACL_PATH
$sidType = [System.Security.Principal.SecurityIdentifier]
$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$ownerSid = ([System.Security.Principal.NTAccount]$acl.Owner).Translate($sidType).Value
$rules = @(
    $acl.GetAccessRules($true, $true, $sidType) | ForEach-Object {
        [pscustomobject]@{
            Identity = $_.IdentityReference.Value
            Type = $_.AccessControlType.ToString()
            Rights = [int64]$_.FileSystemRights
            Inherited = [bool]$_.IsInherited
            Inheritance = $_.InheritanceFlags.ToString()
            Propagation = $_.PropagationFlags.ToString()
        }
    }
)
[pscustomobject]@{
    CurrentSid = $currentSid
    OwnerSid = $ownerSid
    Protected = [bool]$acl.AreAccessRulesProtected
    Rules = @($rules)
} | ConvertTo-Json -Depth 4 -Compress
"""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    assert completed.returncode == 0, (
        f"independent Windows ACL inspection failed: {completed.stderr.strip()}"
    )
    return json.loads(completed.stdout)


def _assert_restrictive(path: Path, *, directory: bool = False):
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if directory else 0o600)
        return

    acl = _windows_acl(path)
    assert acl["Protected"] is True, "DACL inheritance must be disabled"
    assert acl["OwnerSid"] == acl["CurrentSid"], "current identity must own the path"
    rules = acl["Rules"]
    if isinstance(rules, dict):
        rules = [rules]
    assert len(rules) == 1, "only one explicit current-identity ACE is allowed"
    rule = rules[0]
    assert rule["Identity"] == acl["CurrentSid"], (
        "the current identity must be the only allowed principal"
    )
    assert rule["Type"] == "Allow"
    assert rule["Inherited"] is False
    assert int(rule["Rights"]) & 0x001F01FF == 0x001F01FF, (
        "the current identity must have full required access"
    )
    inheritance = {
        item.strip() for item in rule["Inheritance"].split(",") if item.strip()
    }
    if directory:
        assert inheritance == {"ContainerInherit", "ObjectInherit"}, (
            "directory ACE must propagate to child files and directories"
        )
    else:
        assert inheritance in (set(), {"None"}), (
            "file ACE must not carry child-inheritance flags"
        )
    assert rule["Propagation"] == "None"


def test_registry_is_user_data_only_redacts_tokens_and_uses_restrictive_permissions(tmp_path):
    if os.name == "nt":
        chmod_only = tmp_path / "chmod-only"
        chmod_only.mkdir()
        chmod_only.chmod(0o700)
        with pytest.raises(AssertionError, match="DACL inheritance"):
            _assert_restrictive(chmod_only, directory=True)

    path = tmp_path / "user-data" / "sites.json"
    created = []
    registry = SiteRegistry(path, client_factory=_factory(created))
    result = registry.add("lab", "ws://vpn.example:8765", "registry-secret", note="bench")

    assert result == {"added": True, "name": "lab", "overwrote": False, "active": True}
    public = registry.list()
    assert public == [{
        "name": "lab", "url": "ws://vpn.example:8765", "note": "bench",
        "active": True, "connected": False, "token_configured": True,
    }]
    serialized = path.read_text(encoding="utf-8")
    assert "registry-secret" not in json.dumps(public)
    assert "registry-secret" in serialized
    assert "mklink" not in {part.lower() for part in path.parts}
    assert path.parent != Path.cwd()
    _assert_restrictive(path)
    _assert_restrictive(path.parent, directory=True)


def test_default_registry_location_is_user_data_not_source_or_current_directory(tmp_path):
    environment = (
        {"LOCALAPPDATA": str(tmp_path / "local")}
        if os.name == "nt"
        else {"XDG_DATA_HOME": str(tmp_path / "xdg")}
    )
    expected_base = Path(next(iter(environment.values())))
    location = default_sites_path(environment)
    assert location.is_relative_to(expected_base)
    assert not location.is_relative_to(Path.cwd())
    assert location.name == "sites.json"


def test_project_pointer_is_gitignored_once_and_selects_its_registered_site(tmp_path):
    created = []
    registry = SiteRegistry(tmp_path / "data" / "sites.json", client_factory=_factory(created))
    registry.add("alpha", "ws://alpha.example", "token-a")
    registry.add("beta", "ws://beta.example", "token-b", make_active=False)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()

    first = registry.write_project_site(project, "beta")
    second = registry.write_project_site(project, "beta")
    pointer = project / ".mklink" / "remote.json"
    assert first["gitignore_updated"] is True
    assert second["gitignore_updated"] is False
    assert json.loads(pointer.read_text()) == {"active_site": "beta"}
    assert (project / ".gitignore").read_text().splitlines().count(".mklink/remote.json") == 1
    assert registry.resolve_name(project_root=project) == "beta"
    _assert_restrictive(pointer)
    _assert_restrictive(pointer.parent, directory=True)


def test_same_site_calls_are_serial_and_cross_site_calls_are_parallel(tmp_path):
    entered = {"alpha": threading.Event(), "beta": threading.Event()}
    release = threading.Event()
    state = {"active": 0, "maximum": 0}
    state_lock = threading.Lock()

    class BlockingClient(_Client):
        def call(self, method, **params):
            site = self.url.removeprefix("ws://")
            with state_lock:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            entered[site].set()
            assert release.wait(timeout=2)
            with state_lock:
                state["active"] -= 1
            return site

    def factory(url, *, token, timeout=0):
        return BlockingClient(url, token=token, timeout=timeout)

    registry = SiteRegistry(tmp_path / "sites.json", client_factory=factory)
    registry.add("alpha", "ws://alpha", "a")
    registry.add("beta", "ws://beta", "b", make_active=False)
    same_a = threading.Thread(target=registry.call, args=("alpha", "status"))
    same_b = threading.Thread(target=registry.call, args=("alpha", "status"))
    same_a.start()
    assert entered["alpha"].wait(timeout=1)
    same_b.start()
    beta = threading.Thread(target=registry.call, args=("beta", "status"))
    beta.start()
    assert entered["beta"].wait(timeout=1)
    with state_lock:
        assert state["maximum"] == 2, "different sites were serialized together"
    release.set()
    for thread in (same_a, same_b, beta):
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert state["maximum"] == 2, "same-site calls were not serialized"


def test_site_failures_and_removal_do_not_affect_another_site(tmp_path):
    created = []
    registry = SiteRegistry(tmp_path / "sites.json", client_factory=_factory(created))
    registry.add("broken", "ws://broken", "broken-secret")
    registry.add("healthy", "ws://healthy", "healthy-secret", make_active=False)
    broken_client = registry.client("broken")
    healthy_client = registry.client("healthy")

    with pytest.raises(RuntimeError):
        registry.call("broken", "fail")
    assert broken_client.closed is True
    assert registry.call("healthy", "status")["site"] == "ws://healthy"
    assert registry.remove("broken") == {"removed": True, "name": "broken", "was_active": True}
    assert healthy_client.closed is False
    assert registry.client("healthy") is healthy_client
    with pytest.raises(SiteError):
        registry.client("broken")
