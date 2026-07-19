"""FastAPI routes for structured MKLink offline-download deployment."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from typing import Dict, List, Mapping, Optional
import uuid

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile

from mklink.offline_download import (
    OfflineAlgorithm,
    OfflineDownloadConfig,
    OfflineDownloadError,
    deploy_offline_bundle,
    generate_offline_script,
    parse_offline_config,
)


_UPLOAD_CHUNK = 1024 * 1024
_MAX_UPLOAD_SIZE = 256 * 1024 * 1024
_MAX_TOTAL_UPLOAD_SIZE = 512 * 1024 * 1024
_TOKEN_SAFE = re.compile(r"^[A-Za-z0-9._:-]+$")


def detect_probe_model(port: Optional[str] = None, bridge: Optional[object] = None) -> dict:
    from mklink.discovery import find_mklink_cdc_port
    from mklink.firmware_check import read_bridge_version, read_device_version

    last_error: Optional[BaseException] = None
    for attempt in range(2):
        resolved_port = port or (None if bridge is not None else find_mklink_cdc_port())
        if bridge is not None or resolved_port:
            try:
                version = (
                    read_bridge_version(bridge)
                    if bridge is not None
                    else read_device_version(resolved_port)
                )
            except (ConnectionError, TimeoutError, OSError) as error:
                last_error = error
            else:
                if version is not None:
                    if version.major not in (2, 3, 4):
                        raise OfflineDownloadError(
                            "cmd.get_version() returned an unsupported version"
                        )
                    return {"model": f"V{version.major}", "version": str(version)}
        if attempt == 0:
            time.sleep(0.5)
    if last_error is not None:
        raise OfflineDownloadError(f"cmd.get_version() failed: {last_error}")
    raise OfflineDownloadError("cmd.get_version() did not return a version")


def _hex(value: int) -> str:
    return f"0x{value:08X}"


def _profile_candidates(part_number: str, disk_root: Optional[Path]) -> list[dict]:
    from mklink.discovery import check_flm_on_microkeen, resolve_keil_flm_path
    from mklink.profiles import load_mcu_profiles, match_mcu_by_device

    profiles = load_mcu_profiles()
    key = match_mcu_by_device(part_number, profiles)
    if not key:
        return []
    profile = profiles.get(key) or {}
    flm_path = str(profile.get("flm_path") or "")
    file_name = Path(flm_path).name
    if not file_name:
        return []
    local_path = resolve_keil_flm_path(file_name)
    on_probe, _probe_path = check_flm_on_microkeen(file_name)
    if disk_root is not None:
        on_probe = (disk_root / "FLM" / file_name).is_file()
    return [{
        "id": f"profile-{key}",
        "file_name": file_name,
        "flash_base": _hex(int(str(profile.get("flash_base") or "0"), 0)),
        "ram_base": _hex(int(str(profile.get("ram_base") or "0"), 0)),
        "source_kind": "profile" if local_path else "existing",
        "source_token": f"profile:{key}" if local_path else None,
        "origin": "MCU profile",
        "available": bool(local_path or on_probe),
        "on_probe": on_probe,
    }]


def _installed_pack_paths(paths: object) -> list[tuple[str, str, Path]]:
    state_file = Path(getattr(paths, "state_file"))
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    installed = payload.get("installed") if isinstance(payload, Mapping) else None
    if not isinstance(installed, Mapping):
        return []
    result = []
    for pack_id, versions in installed.items():
        if not isinstance(versions, Mapping):
            continue
        for version, raw_path in versions.items():
            path = Path(str(raw_path))
            if path.is_file():
                result.append((str(pack_id), str(version), path))
    return result


def _default_ram_start(device: object) -> int:
    for region in device.memory_map:
        if bool(getattr(region, "is_ram", False)):
            return int(region.start)
    return 0


def _pack_device_algorithms(pack_path: Path, part_number: str) -> list[tuple[object, object, int]]:
    from pyocd.target.pack.cmsis_pack import CmsisPack

    pack = CmsisPack(str(pack_path))
    devices = [
        device for device in pack.devices
        if str(device.part_number).casefold() == part_number.casefold()
    ]
    if len(devices) != 1:
        return []
    device = devices[0]
    default_ram = _default_ram_start(device)
    result = []
    for index, element in enumerate(getattr(device, "_info").algos):
        name = element.attrib.get("name")
        start = element.attrib.get("start")
        if not name or start is None:
            continue
        ram_start = element.attrib.get("RAMstart")
        result.append((device, element, default_ram if ram_start is None else int(ram_start, 0)))
    return result


def _pack_candidates(paths: object, part_number: str) -> list[dict]:
    candidates = []
    for pack_id, version, pack_path in _installed_pack_paths(paths):
        for index, (_device, element, ram_start) in enumerate(
            _pack_device_algorithms(pack_path, part_number)
        ):
            name = str(element.attrib["name"])
            token = f"pack:{pack_id}:{version}:{part_number}:{index}"
            candidates.append({
                "id": "pack-" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:12],
                "file_name": Path(name).name,
                "flash_base": _hex(int(element.attrib["start"], 0)),
                "ram_base": _hex(ram_start),
                "source_kind": "pack",
                "source_token": token,
                "origin": f"{pack_id}@{version}",
                "available": True,
                "on_probe": False,
            })
    unique = {}
    for candidate in candidates:
        key = (
            candidate["file_name"].casefold(),
            candidate["flash_base"],
            candidate["ram_base"],
        )
        unique.setdefault(key, candidate)
    return list(unique.values())


def discover_algorithms(paths: object, part_number: str, disk_root: Optional[Path]) -> list[dict]:
    from mklink.cmsis_dap.algorithm_catalog import discover_flash_algorithms

    catalog = discover_flash_algorithms(part_number, paths=paths)
    candidates = [{
        "id": "catalog-" + algorithm.algorithm_id[:12],
        "file_name": algorithm.file_name,
        "flash_base": _hex(algorithm.flash_start),
        "ram_base": _hex(algorithm.ram_start),
        "source_kind": "pack",
        "source_token": algorithm.source_token,
        "origin": algorithm.source_name,
        "available": True,
        "on_probe": False,
    } for algorithm in catalog]
    combined = candidates + _profile_candidates(part_number, disk_root)
    unique = {}
    for candidate in combined:
        key = (
            candidate["file_name"].casefold(),
            candidate["flash_base"],
            candidate["ram_base"],
        )
        unique.setdefault(key, candidate)
    return list(unique.values())


def _profile_source(token: str, disk_root: Path) -> Path:
    from mklink.discovery import resolve_keil_flm_path
    from mklink.profiles import load_mcu_profiles

    if not token.startswith("profile:"):
        raise OfflineDownloadError("invalid profile FLM token")
    key = token.split(":", 1)[1]
    profile = load_mcu_profiles().get(key) or {}
    file_name = Path(str(profile.get("flm_path") or "")).name
    if not file_name:
        raise OfflineDownloadError("profile does not define an FLM file")
    resolved = resolve_keil_flm_path(file_name)
    if resolved:
        return Path(resolved)
    existing = disk_root / "FLM" / file_name
    if existing.is_file():
        return existing
    raise OfflineDownloadError(f"FLM file is unavailable: {file_name}")


def _pack_source(paths: object, token: str, destination: Path) -> Path:
    if not _TOKEN_SAFE.fullmatch(token) or not token.startswith(("pack:", "catalog:", "custom:")):
        raise OfflineDownloadError("invalid Pack FLM token")
    if token.startswith(("catalog:", "custom:")):
        from mklink.cmsis_dap.algorithm_catalog import (
            discover_flash_algorithms,
            extract_algorithm,
            target_from_source_token,
        )

        try:
            part_number = target_from_source_token(token)
        except ValueError:
            raise OfflineDownloadError("invalid catalog FLM token")
        matches = [
            algorithm
            for algorithm in discover_flash_algorithms(part_number, paths=paths)
            if algorithm.source_token == token
        ]
        if len(matches) != 1:
            raise OfflineDownloadError("catalog FLM token is unavailable")
        payload = extract_algorithm(matches[0])
        if not isinstance(payload, bytes):
            raise OfflineDownloadError("catalog FLM extraction failed")
        destination.write_bytes(payload)
        return destination
    try:
        _prefix, pack_id, version, part_number, raw_index = token.rsplit(":", 4)
        index = int(raw_index)
    except (ValueError, TypeError):
        raise OfflineDownloadError("invalid Pack FLM token")
    matches = [
        path for candidate_id, candidate_version, path in _installed_pack_paths(paths)
        if candidate_id == pack_id and candidate_version == version
    ]
    if len(matches) != 1:
        raise OfflineDownloadError("installed Pack for FLM token is unavailable")
    algorithms = _pack_device_algorithms(matches[0], part_number)
    if index < 0 or index >= len(algorithms):
        raise OfflineDownloadError("Pack FLM token index is invalid")
    device, element, _ram_start = algorithms[index]
    with device.get_file(str(element.attrib["name"])) as source:
        destination.write_bytes(source.read())
    return destination


def _copy_upload(upload: UploadFile, destination: Path, total: list[int]) -> Path:
    size = 0
    with destination.open("wb") as stream:
        while True:
            chunk = upload.file.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            total[0] += len(chunk)
            if size > _MAX_UPLOAD_SIZE or total[0] > _MAX_TOTAL_UPLOAD_SIZE:
                raise OfflineDownloadError("offline upload size limit exceeded")
            stream.write(chunk)
    return destination


def _redact_trigger_output(response: str) -> list[str]:
    result = []
    for raw in response.splitlines()[-100:]:
        line = re.sub(r"(?i)(IDCODE\s*:\s*)0x[0-9a-f]+", r"\1<masked>", raw.strip())
        if line:
            result.append(line[:500])
    return result


def create_offline_download_router(
    online_services: object,
    resource_manager: object,
    device_provider: Optional[object] = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/offline-download", tags=["offline-download"])

    def _connected_bridge(port: Optional[str]) -> Optional[object]:
        device = device_provider() if callable(device_provider) else None
        if device is None or not bool(getattr(device, "connected", False)):
            return None
        device_port = getattr(device, "port", None)
        if port and device_port and str(port) != str(device_port):
            return None
        return getattr(device, "_bridge", None)

    async def _detect(port: Optional[str]) -> dict:
        from mklink.remote.resource_manager import ResourceGroup

        owner = f"user:offline-download:detect:{uuid.uuid4().hex}"
        try:
            resource_manager.acquire(ResourceGroup.MKLINK_BRIDGE, owner, preempt=False)
            return await asyncio.to_thread(
                detect_probe_model,
                port,
                _connected_bridge(port),
            )
        finally:
            resource_manager.release(owner)

    async def _resolved_model(payload: Mapping[str, object]) -> Optional[str]:
        if str(payload.get("model") or "auto").upper() != "AUTO":
            return None
        return (await _detect(payload.get("port")))["model"]

    @router.get("/status")
    async def status() -> object:
        from mklink.discovery import find_microkeen_disk

        disk = await asyncio.to_thread(find_microkeen_disk)
        root = Path(disk) if disk else None
        return {
            "available": root is not None,
            "disk_path": str(root) if root else None,
            "python_dir": str(root / "python") if root else None,
            "flm_dir": str(root / "FLM") if root else None,
        }

    @router.post("/detect-model")
    async def detect_model(port: Optional[str] = Body(default=None, embed=True)) -> object:
        try:
            return await _detect(port)
        except OfflineDownloadError as error:
            raise HTTPException(status_code=400, detail=str(error))

    @router.get("/algorithms")
    async def algorithms(part_number: str) -> object:
        from mklink.discovery import find_microkeen_disk

        disk = await asyncio.to_thread(find_microkeen_disk)
        root = Path(disk) if disk else None
        try:
            return await asyncio.to_thread(
                discover_algorithms,
                online_services.paths,
                part_number,
                root,
            )
        except (OfflineDownloadError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error))

    @router.post("/preview")
    async def preview(payload: dict = Body(...)) -> object:
        try:
            model = await _resolved_model(payload)
            config = parse_offline_config(payload, resolved_model=model)
            return {
                "model": config.model,
                "script_name": config.script_name,
                "script": generate_offline_script(config),
            }
        except OfflineDownloadError as error:
            raise HTTPException(status_code=422, detail=str(error))

    @router.post("/deploy")
    async def deploy(
        config_json: str = Form(...),
        firmware_files: List[UploadFile] = File(default=[]),
        flm_files: List[UploadFile] = File(default=[]),
    ) -> object:
        from mklink.discovery import find_microkeen_disk

        try:
            payload = json.loads(config_json)
            if not isinstance(payload, Mapping):
                raise OfflineDownloadError("offline config must be an object")
            model = await _resolved_model(payload)
            config = parse_offline_config(payload, resolved_model=model)
            disk = await asyncio.to_thread(find_microkeen_disk)
            if not disk:
                raise OfflineDownloadError("MICROKEEN disk is unavailable")
            disk_root = Path(disk)
            total = [0]
            with tempfile.TemporaryDirectory(prefix="mklink-offline-") as raw_temp:
                temp = Path(raw_temp)
                firmware_sources = []
                for index, upload in enumerate(firmware_files):
                    firmware_sources.append(
                        await asyncio.to_thread(
                            _copy_upload, upload, temp / f"firmware-{index}", total
                        )
                    )
                uploaded_flms = []
                for index, upload in enumerate(flm_files):
                    uploaded_flms.append(
                        await asyncio.to_thread(
                            _copy_upload, upload, temp / f"flm-{index}", total
                        )
                    )
                algorithm_sources: Dict[str, Path] = {}
                for algorithm in config.algorithms:
                    if algorithm.source_kind == "upload":
                        if algorithm.upload_index is None or algorithm.upload_index >= len(uploaded_flms):
                            raise OfflineDownloadError("missing uploaded FLM source")
                        algorithm_sources[algorithm.id] = uploaded_flms[algorithm.upload_index]
                    elif algorithm.source_kind == "profile":
                        algorithm_sources[algorithm.id] = await asyncio.to_thread(
                            _profile_source, algorithm.source_token or "", disk_root
                        )
                    elif algorithm.source_kind == "pack":
                        algorithm_sources[algorithm.id] = await asyncio.to_thread(
                            _pack_source,
                            online_services.paths,
                            algorithm.source_token or "",
                            temp / f"pack-{algorithm.id}.flm",
                        )
                return await asyncio.to_thread(
                    deploy_offline_bundle,
                    config,
                    disk_root,
                    firmware_sources=firmware_sources,
                    algorithm_sources=algorithm_sources,
                )
        except (OfflineDownloadError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=422, detail=str(error))
        finally:
            for upload in list(firmware_files) + list(flm_files):
                await upload.close()

    @router.post("/trigger")
    async def trigger(port: Optional[str] = Body(default=None, embed=True)) -> object:
        from mklink.bridge import MKLinkSerialBridge
        from mklink.discovery import find_mklink_cdc_port
        from mklink.remote.resource_manager import ResourceGroup

        active_bridge = _connected_bridge(port)
        resolved_port = port or (
            None if active_bridge is not None else await asyncio.to_thread(find_mklink_cdc_port)
        )
        if active_bridge is None and not resolved_port:
            raise HTTPException(status_code=400, detail="MKLink CDC port was not found")
        owner = f"user:offline-download:trigger:{uuid.uuid4().hex}"
        try:
            resource_manager.acquire_many(
                [ResourceGroup.MKLINK_BRIDGE, ResourceGroup.TARGET_DEBUG],
                owner,
                preempt=False,
            )

            def _run() -> str:
                if active_bridge is not None:
                    return active_bridge.send_command(
                        "load.offline()", timeout=600, echo=True
                    )
                bridge = MKLinkSerialBridge(resolved_port)
                try:
                    if not bridge.connect():
                        raise ConnectionError("Unable to connect to MKLink CDC port")
                    return bridge.send_command("load.offline()", timeout=600, echo=True)
                finally:
                    bridge.close()

            response = await asyncio.to_thread(_run)
        except Exception as error:
            raise HTTPException(status_code=409, detail=str(error))
        finally:
            resource_manager.release(owner)
        lines = _redact_trigger_output(response)
        text = "\n".join(lines).casefold()
        return {
            "status": "completed" if "finished" in text and "aborted" not in text else "failed",
            "lines": lines,
        }

    return router
