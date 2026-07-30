"""Transport policy gates for direct LAN and in-process LAN STCP modes."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REMOTE_ROOTS = (
    ROOT / "mklink" / "remote",
    ROOT / "packaging" / "site_agent",
    ROOT / "site-agent-gui" / "src-tauri" / "src",
)
FORBIDDEN_EXECUTABLE = re.compile(r"(?i)\bfrp(?:c|s)?(?:\.exe)?\b")


def _source_files():
    for root in REMOTE_ROOTS:
        if not root.exists():
            continue
        yield from (
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in {".py", ".rs", ".toml", ".json"}
            and "target" not in {part.casefold() for part in path.parts}
        )


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        parts = [function.attr]
        value = function.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def test_product_source_never_launches_an_frp_executable() -> None:
    violations = []
    process_calls = {
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "os.system",
        "Command.new",
    }
    for path in _source_files():
        if path.suffix.casefold() != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in process_calls:
                continue
            source = ast.get_source_segment(
                path.read_text(encoding="utf-8"),
                node,
            ) or ""
            if FORBIDDEN_EXECUTABLE.search(source):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_repository_contains_no_frpc_or_frps_executable() -> None:
    violations = [
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.name.casefold() in {"frpc.exe", "frps.exe", "frpc", "frps"}
        and "target" not in {part.casefold() for part in path.parts}
    ]
    assert violations == []


def test_native_bridge_is_a_pinned_library_not_a_renamed_client() -> None:
    bridge = ROOT / "native" / "stcp_bridge"
    module = (bridge / "go.mod").read_text(encoding="utf-8")
    source = (bridge / "main.go").read_text(encoding="utf-8")
    package_builder = (ROOT / "packaging" / "site_agent" / "build.py").read_text(
        encoding="utf-8"
    )

    assert "github.com/fatedier/frp v0.69.1" in module
    assert "client.NewService" in source
    assert "//export MklinkSTCPStart" in source
    assert "os/exec" not in source
    assert 'bundle / "mklink-stcp.dll"' in package_builder
    assert "frpc.exe is not accepted" in package_builder


def test_packaging_policy_allows_only_in_process_lan_stcp() -> None:
    source = (ROOT / "packaging" / "site_agent" / "build.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assignments = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id == "PROHIBITED_TUNNEL_ARCHIVE_PARTS"
    }
    prohibited = assignments["PROHIBITED_TUNNEL_ARCHIVE_PARTS"]
    assert {"frp", "frpc", "frps", "sitetunnel"}.issubset(prohibited)
    assert "stcp" not in prohibited
    assert '"mode": "direct-or-in-process-lan-stcp"' in source
    assert "public relay or public tunnel" in source


def test_site_agent_manifest_declares_no_frpc_executable_when_present() -> None:
    manifest = (
        ROOT
        / "release"
        / "site-agent"
        / "mklink-remote-site-agent-windows-x86_64.manifest.json"
    )
    if not manifest.is_file():
        return
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("network_policy", {}).get("mode") != (
        "direct-or-in-process-lan-stcp"
    ):
        # A prior direct-only candidate is stale rather than evidence for the
        # new build. The package build tests create and validate the new one.
        return
    transport = payload["dependencies"]["in_process_stcp"]
    assert transport["library"] == "mklink-stcp.dll"
    assert transport["frpc_executable"] is False
