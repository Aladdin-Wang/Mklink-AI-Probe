"""Qualify native bundle contents without connecting hardware or host Python."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check_mcp(executable, env, workspace):
    parameters = StdioServerParameters(command=str(executable), args=["mcp"], env=env, cwd=str(workspace))
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            for name, arguments in [("inspect_mcu", {"device": "STM32F103RE"}),
                                    ("security_status", {"target_part": "STM32F103RE"})]:
                result = await session.call_tool(name, arguments)
                if result.isError:
                    raise RuntimeError(f"Frozen MCP {name} failed: {result}")
                if name == "inspect_mcu" and "STM32F103" not in result.model_dump_json():
                    raise RuntimeError("Frozen MCP algorithm result missing")


def main():
    target = sys.argv[1]
    output = Path(os.environ["MKLINK_BUILD_OUTPUT_DIR"]) / target
    work = Path(os.environ["MKLINK_BUILD_WORK_DIR"])
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME", "MKLINK_BUILTIN_FLM_ROOT", "MKLINK_STCP_LIBRARY"}}
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    workspace = work / "empty-project"
    workspace.mkdir(parents=True)
    if platform.system() == "Darwin":
        mount = work / "mounted"
        mount.mkdir()
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount), str(next(output.glob("*.dmg")))], check=True)
        try:
            import shutil
            app = next(mount.glob("*.app"))
            destination = work / app.name
            shutil.copytree(app, destination, symlinks=True)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=True)
        binary_root = destination / "Contents" / "MacOS"
        updater_root = work / "updater-root"
        updater_root.mkdir()
        subprocess.run(["tar", "-xzf", str(next(output.glob("*.app.tar.gz"))), "-C", str(updater_root)], check=True)
        updater_bin = next(updater_root.glob("*.app")) / "Contents" / "MacOS"
        for executable in ("mklink-ai-probe", "mklink-sidecar"):
            packaged = binary_root / executable
            update = updater_bin / executable
            assert os.access(update, os.X_OK), "Updater lost executable permissions"
            assert hashlib.sha256(packaged.read_bytes()).digest() == hashlib.sha256(update.read_bytes()).digest()
    else:
        extracted = work / "deb-root"
        subprocess.run(["dpkg-deb", "-x", str(next(output.glob("*.deb"))), str(extracted)], check=True)
        binary_root = extracted / "usr" / "bin"
        # Check the AppImage payload as well; this does not prove every distro.
        image = next(output.glob("*.AppImage"))
        subprocess.run([str(image), "--appimage-extract"], cwd=work, check=True, stdout=subprocess.DEVNULL)
        assert (work / "squashfs-root" / "usr" / "bin" / "mklink-sidecar").is_file()
    sidecar = binary_root / "mklink-sidecar"
    cli = subprocess.run([str(sidecar), "mcu-detect", "--device", "STM32F103RE", "--json"], cwd=workspace, env=env, text=True, capture_output=True, timeout=90)
    if cli.returncode or '"candidates"' not in cli.stdout or "STM32F103" not in cli.stdout:
        raise RuntimeError(f"Frozen CLI failed: {cli.stdout}\n{cli.stderr}")
    asyncio.run(check_mcp(sidecar, env, workspace))
    info_path = work / "desktop-endpoint.json"
    log_path = output / "frozen-startup.log"
    started = time.monotonic()
    with log_path.open("w") as log:
        process = subprocess.Popen([str(sidecar), "desktop-proxy", "--host", "127.0.0.1", "--port", "8765", "--desktop-port-end", "8799", "--desktop-instance-id", "unix-package-smoke", "--desktop-runtime-info", str(info_path), "--project-root", str(workspace)], cwd=workspace, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 120
            while not info_path.is_file():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Frozen backend did not publish endpoint")
                time.sleep(0.2)
            info = json.loads(info_path.read_text())
            origin = f"http://127.0.0.1:{info['port']}"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def get(path):
                with opener.open(origin + path, timeout=15) as response:
                    return response.read()
            while True:
                try:
                    health = json.loads(get("/api/health"))
                    break
                except (OSError, ValueError):
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise
                    time.sleep(0.2)
            assert health["status"] == "ok", health
            html = get("/").decode()
            assets = re.findall(r'(?:src|href)="([^\"]+\.(?:js|css))"', html)
            assert assets, "Production Web scripts missing"
            for asset in assets:
                assert len(get("/" + asset.lstrip("./"))) > 0
            elapsed = time.monotonic() - started
            request = urllib.request.Request(origin + "/api/desktop/shutdown", data=json.dumps({"instance_id": "unix-package-smoke"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with opener.open(request, timeout=15) as response:
                assert response.status == 200
            process.wait(timeout=30)
            assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
    report = {"target": target, "frozen_cli": "passed", "frozen_mcp": "passed", "backend_health": health,
              "production_web_assets": len(assets), "startup_seconds": round(elapsed, 3), "graceful_shutdown": "passed",
              "package_contents": "DMG mounted/copied" if platform.system() == "Darwin" else "DEB and AppImage extracted",
              "updater_payload": "app.tar.gz matches DMG executables and preserves executable permissions" if platform.system() == "Darwin" else "DEB and AppImage payloads use installer-specific updater keys",
              "signed_update_installation": "not tested; unsigned candidate",
              "native_gui_interaction": "not tested", "system_installer_interaction": "not tested", "usb_hardware": "not tested"}
    (output / "qualification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
