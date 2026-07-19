"""Lazy, serialised pyOCD backend for online flash operations."""

from __future__ import annotations

import hashlib
import io
import re
import threading
from pathlib import Path
from types import MethodType
from typing import Any, Callable, Iterator, Mapping, Optional, Tuple

from .errors import FlashError, FlashErrorCode
from .models import ImageInspection, MemoryRegion


_LOCKED_ERROR_PATTERN = re.compile(
    r"\bread(?:out)?\s+protection\b"
    r"|\b(?:target|device|flash)(?:\s+is)?\s+locked\b"
    r"|\brdp\s+level\s+(?:1(?:\s*/\s*2)?|2)\b"
    r"|\bmass\s+erase\s+disabled\s+due\s+protection\b",
    re.IGNORECASE,
)


class _CustomFlmDelegate:
    def __init__(self, payloads: Tuple[bytes, ...], next_delegate: Any = None) -> None:
        self._payloads = payloads
        self._next_delegate = next_delegate

    def will_init_target(self, target: Any, init_sequence: Any) -> None:
        callback = getattr(self._next_delegate, "will_init_target", None)
        if callable(callback):
            callback(target, init_sequence)
        init_sequence.insert_before(
            "create_flash",
            (
                "mklink_custom_flm",
                lambda: _install_custom_flm_regions(target, self._payloads),
            ),
        )

    def __getattr__(self, name: str) -> Any:
        if self._next_delegate is None:
            raise AttributeError(name)
        return getattr(self._next_delegate, name)


def _install_custom_flm_regions(target: Any, payloads: Tuple[bytes, ...]) -> None:
    from pyocd.core.memory_map import FlashRegion
    from pyocd.target.pack.flash_algo import PackFlashAlgo

    target.memory_map = target.memory_map.clone()
    existing = [region for region in target.memory_map if bool(getattr(region, "is_flash", False))]
    for index, payload in enumerate(payloads):
        try:
            algorithm = PackFlashAlgo(io.BytesIO(payload))
        except Exception:
            raise FlashError(
                FlashErrorCode.FILE_FORMAT_ERROR,
                "custom FLM could not be loaded",
            ) from None
        _enable_custom_flm_verify(algorithm)
        start = int(algorithm.flash_start)
        end = start + int(algorithm.flash_size)
        for region in list(existing):
            region_start = int(region.start)
            region_end = region_start + int(region.length)
            if start < region_end and region_start < end:
                if str(getattr(region, "name", "")).startswith("mklink_custom_flm_"):
                    raise FlashError(
                        FlashErrorCode.TARGET_NOT_SUPPORTED,
                        "custom FLM range overlaps another custom algorithm",
                    )
                target.memory_map.remove_region(region)
                existing.remove(region)
        region = FlashRegion(
            name="mklink_custom_flm_{}".format(index),
            start=start,
            length=int(algorithm.flash_size),
            flm=algorithm,
        )
        target.memory_map.add_region(region)
        existing.append(region)


def _enable_custom_flm_verify(algorithm: Any) -> None:
    symbols = getattr(algorithm, "symbols", None)
    verify_offset = symbols.get("Verify") if isinstance(symbols, dict) else None
    build_algo = getattr(algorithm, "get_pyocd_flash_algo", None)
    if (
        not isinstance(verify_offset, int)
        or isinstance(verify_offset, bool)
        or verify_offset < 0
        or not callable(build_algo)
    ):
        return

    def build_with_verify(self: Any, blocksize: int, ram_region: Any) -> Any:
        flash_algo = build_algo(blocksize, ram_region)
        if flash_algo is None:
            return None
        flash_algo = dict(flash_algo)
        flash_algo["pc_verify"] = (
            int(flash_algo["load_address"]) + 4 + verify_offset
        )
        flash_algo["mklink_custom_verify"] = True
        return flash_algo

    algorithm.get_pyocd_flash_algo = MethodType(build_with_verify, algorithm)


class HpmRomBackend:
    """Program HPMicro XPI Flash through the MKLink device-side ROM API."""

    def __init__(
        self,
        device_factory: Optional[Callable[..., Any]] = None,
        port_resolver: Optional[Callable[[Any], Optional[str]]] = None,
        *,
        verify_chunk_size: int = 4096,
    ) -> None:
        if not isinstance(verify_chunk_size, int) or verify_chunk_size <= 0:
            raise ValueError("verify_chunk_size must be a positive integer")
        self._device_factory = device_factory
        self._port_resolver = port_resolver
        self._verify_chunk_size = verify_chunk_size
        self._device: Any = None
        self._target = ""
        self._frequency = 1_000_000
        self._board: Optional[str] = None
        self._flash_cfg: Optional[Tuple[str, str, str, str]] = None
        self._lock = threading.RLock()

    def connect(
        self,
        probe: Any,
        target: str,
        frequency: int,
        pack: Optional[str] = None,
        custom_flm_paths: Tuple[str, ...] = (),
        custom_flm_digests: Tuple[str, ...] = (),
        connect_mode: str = "halt",
        reset_mode: str = "default",
        board: Optional[str] = None,
        hpm_flash_cfg: Optional[Tuple[str, str, str, str]] = None,
    ) -> None:
        del pack, custom_flm_paths, custom_flm_digests, connect_mode, reset_mode
        from mklink.hpm_config import (
            is_hpm_target,
            normalize_hpm_configuration,
        )

        if not is_hpm_target(target):
            raise FlashError(FlashErrorCode.TARGET_NOT_SUPPORTED, "target is not an HPM device")
        if not isinstance(frequency, int) or isinstance(frequency, bool) or not 1 <= frequency <= 10_000_000:
            raise ValueError("frequency must be between 1 and 10000000 Hz")
        resolved_board, resolved_cfg = normalize_hpm_configuration(
            target, board=board, flash_cfg=hpm_flash_cfg
        )
        with self._lock:
            self.disconnect()
            resolver = self._port_resolver
            if resolver is None:
                from mklink.discovery import find_mklink_cdc_port

                resolver = lambda identifier: find_mklink_cdc_port(serial_number=identifier)
            port = resolver(probe)
            if not port:
                raise FlashError(
                    FlashErrorCode.MKLINK_DAP_NOT_FOUND,
                    "MKLink CDC bridge was not found for the selected probe",
                )
            factory = self._device_factory
            if factory is None:
                from mklink.device import connect

                factory = connect
            try:
                self._device = factory(port=port)
                self._target = str(target)
                self._frequency = frequency
                self._board = resolved_board
                self._flash_cfg = resolved_cfg
            except FlashError:
                raise
            except Exception as error:
                raise FlashError(FlashErrorCode.CONNECT_FAIL, str(error)) from error

    def disconnect(self) -> None:
        with self._lock:
            device, self._device = self._device, None
            if device is not None:
                try:
                    device.close()
                except Exception as error:
                    raise FlashError(FlashErrorCode.CONNECT_FAIL, str(error)) from error

    def erase_chip(self) -> None:
        self._require_device()

    def erase_sectors(self, addresses: Any) -> None:
        del addresses
        self._require_device()

    def program(self, image: ImageInspection) -> None:
        with self._lock:
            device = self._require_device()
            path, base = self._validated_bin(image)
            try:
                result = device.flash(
                    str(path),
                    target_part=self._target,
                    base_address=base,
                    board=self._board,
                    hpm_flash_cfg=self._flash_cfg,
                    swd_clock=self._frequency,
                    verify=False,
                    reset_after=False,
                )
                if not isinstance(result, Mapping) or result.get("success") is not True:
                    raise FlashError(FlashErrorCode.PROGRAM_FAIL, "HPM ROM programming failed")
            except FlashError:
                raise
            except Exception as error:
                raise FlashError(FlashErrorCode.PROGRAM_FAIL, str(error)) from error

    def verify(self, image: ImageInspection) -> None:
        with self._lock:
            device = self._require_device()
            path, base = self._validated_bin(image)
            try:
                with path.open("rb") as stream:
                    offset = 0
                    while True:
                        expected = stream.read(self._verify_chunk_size)
                        if not expected:
                            break
                        actual = bytes(device.read_memory(base + offset, len(expected)))
                        if actual != expected:
                            mismatch = next(
                                (index for index, pair in enumerate(zip(expected, actual)) if pair[0] != pair[1]),
                                min(len(expected), len(actual)),
                            )
                            raise FlashError(
                                FlashErrorCode.VERIFY_FAIL,
                                "HPM Flash verification failed",
                                {"address": base + offset + mismatch},
                            )
                        offset += len(expected)
            except FlashError:
                raise
            except FileNotFoundError:
                raise FlashError(FlashErrorCode.FILE_NOT_FOUND, "firmware snapshot file was not found") from None
            except Exception as error:
                raise FlashError(FlashErrorCode.VERIFY_FAIL, str(error)) from error

    def reset_run(self, reset_mode: Optional[str] = None) -> None:
        del reset_mode
        try:
            self._require_device().reset()
        except FlashError:
            raise
        except Exception as error:
            raise FlashError(FlashErrorCode.RESET_FAIL, str(error)) from error

    def _require_device(self) -> Any:
        if self._device is None:
            raise FlashError(FlashErrorCode.CONNECT_FAIL, "HPM backend is not connected")
        return self._device

    @staticmethod
    def _validated_bin(image: ImageInspection) -> Tuple[Path, int]:
        if image.format.casefold() != "bin":
            raise FlashError(FlashErrorCode.FILE_FORMAT_ERROR, "HPM ROM API only supports BIN firmware")
        path = Path(image.file_path)
        if not path.is_file():
            raise FlashError(FlashErrorCode.FILE_NOT_FOUND, "firmware snapshot file was not found")
        if image.base_address is None:
            raise FlashError(FlashErrorCode.BIN_ADDRESS_MISSING, "HPM BIN firmware requires a base address")
        from mklink.hpm_config import normalize_hpm_address

        base, _formatted = normalize_hpm_address(image.base_address)
        return path, base


class RoutingFlashBackend:
    """Select the HPM ROM backend or pyOCD once per connection."""

    def __init__(
        self,
        pyocd_factory: Optional[Callable[[], Any]] = None,
        hpm_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._pyocd_factory = pyocd_factory or PyOcdBackend
        self._hpm_factory = hpm_factory or HpmRomBackend
        self._backend: Any = None

    def connect(self, probe: Any, target: str, frequency: int, **kwargs: Any) -> None:
        from mklink.hpm_config import is_hpm_target

        self.disconnect()
        if is_hpm_target(target):
            backend = self._hpm_factory()
        else:
            backend = self._pyocd_factory()
            kwargs.pop("board", None)
            kwargs.pop("hpm_flash_cfg", None)
        backend.connect(probe=probe, target=target, frequency=frequency, **kwargs)
        self._backend = backend

    def disconnect(self) -> None:
        backend, self._backend = self._backend, None
        if backend is not None:
            backend.disconnect()

    def __getattr__(self, name: str) -> Any:
        backend = self._backend
        if backend is None:
            raise AttributeError(name)
        return getattr(backend, name)


class PyOcdBackend:
    """Own a single pyOCD session without importing pyOCD at module import time."""

    def __init__(
        self,
        session_factory: Optional[Callable[..., Any]] = None,
        probe_provider: Optional[Callable[[], Any]] = None,
        programmer_factory: Optional[Callable[..., Any]] = None,
        eraser_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._session_factory = session_factory
        self._probe_provider = probe_provider
        self._programmer_factory = programmer_factory
        self._eraser_factory = eraser_factory
        self._session: Any = None
        self._reset_mode = "default"
        self._lock = threading.RLock()

    def connect(
        self,
        probe: Any,
        target: str,
        frequency: int,
        pack: Optional[str] = None,
        custom_flm_paths: Tuple[str, ...] = (),
        custom_flm_digests: Tuple[str, ...] = (),
        connect_mode: str = "halt",
        reset_mode: str = "default",
    ) -> None:
        with self._lock:
            self.disconnect()
            if not isinstance(frequency, int) or isinstance(frequency, bool) or frequency <= 0:
                raise ValueError("frequency must be a positive integer")
            resolved_pack: Optional[str] = None
            if pack is not None:
                pack_path = Path(pack).expanduser()
                if not pack_path.is_file():
                    raise FlashError(
                        FlashErrorCode.FILE_NOT_FOUND, "CMSIS-Pack file was not found"
                    )
                if pack_path.suffix.lower() != ".pack":
                    raise FlashError(
                        FlashErrorCode.TARGET_NOT_SUPPORTED,
                        "CMSIS-Pack path must name a .pack file",
                    )
                resolved_pack = str(pack_path.resolve())
            if len(custom_flm_paths) != len(custom_flm_digests):
                raise FlashError(
                    FlashErrorCode.PACK_INTEGRITY_ERROR,
                    "custom FLM integrity metadata is invalid",
                )
            resolved_flms = []
            for value, expected_digest in zip(custom_flm_paths, custom_flm_digests):
                flm_path = Path(value).expanduser()
                if not flm_path.is_file():
                    raise FlashError(FlashErrorCode.FILE_NOT_FOUND, "custom FLM file was not found")
                if flm_path.suffix.casefold() != ".flm":
                    raise FlashError(FlashErrorCode.FILE_FORMAT_ERROR, "custom algorithm must be an .flm file")
                digest = str(expected_digest).casefold()
                if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                    raise FlashError(
                        FlashErrorCode.PACK_INTEGRITY_ERROR,
                        "custom FLM integrity metadata is invalid",
                    )
                try:
                    payload = flm_path.read_bytes()
                except FileNotFoundError:
                    raise FlashError(
                        FlashErrorCode.FILE_NOT_FOUND,
                        "custom FLM file was not found",
                    ) from None
                except OSError:
                    raise FlashError(
                        FlashErrorCode.PACK_INTEGRITY_ERROR,
                        "custom FLM integrity check failed",
                    ) from None
                if hashlib.sha256(payload).hexdigest() != digest:
                    raise FlashError(
                        FlashErrorCode.PACK_INTEGRITY_ERROR,
                        "custom FLM integrity check failed",
                    )
                resolved_flms.append(payload)
            session = None
            try:
                resolved_probe = self._resolve_probe(probe)
                factory = self._session_factory
                if factory is None:
                    from pyocd.core.session import Session

                    factory = lambda selected_probe, selected_options: Session(
                        selected_probe, options=selected_options
                    )
                options = {
                    "target_override": target,
                    "frequency": frequency,
                    "connect_mode": connect_mode,
                    "auto_unlock": False,
                }
                if resolved_pack is not None:
                    options["pack"] = resolved_pack
                session = factory(resolved_probe, options)
                if resolved_flms:
                    session.delegate = _CustomFlmDelegate(
                        tuple(resolved_flms), getattr(session, "delegate", None)
                    )
                session.open()
                session.target.reset_and_halt()
                self._session = session
                self._reset_mode = reset_mode
            except FlashError:
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        pass
                raise
            except Exception as exc:
                if session is not None:
                    try:
                        session.close()
                    except Exception:
                        pass
                raise self._mapped_error(exc, FlashErrorCode.CONNECT_FAIL) from None

    def disconnect(self) -> None:
        with self._lock:
            session, self._session = self._session, None
            if session is not None:
                try:
                    session.close()
                except Exception as exc:
                    raise self._mapped_error(exc, FlashErrorCode.CONNECT_FAIL) from None

    def erase_chip(self) -> None:
        with self._lock:
            session = self._require_session()
            try:
                factory, mode = self._eraser(erase_mode="CHIP")
                factory(session, mode).erase()
            except FlashError:
                raise
            except Exception as exc:
                raise self._mapped_error(exc, FlashErrorCode.ERASE_FAIL) from None

    def erase_sectors(self, addresses: Any) -> None:
        with self._lock:
            session = self._require_session()
            try:
                unique = self._validated_sector_addresses(session.target, addresses)
                factory, mode = self._eraser(erase_mode="SECTOR")
                factory(session, mode).erase(unique)
            except FlashError:
                raise
            except Exception as exc:
                raise self._mapped_error(exc, FlashErrorCode.ERASE_FAIL) from None

    def program(self, image: ImageInspection) -> None:
        with self._lock:
            session = self._require_session()
            try:
                path = Path(image.file_path)
                if not path.is_file():
                    raise FlashError(
                        FlashErrorCode.FILE_NOT_FOUND,
                        "firmware snapshot file was not found",
                    )
                factory = self._programmer_factory
                if factory is None:
                    from pyocd.flash.file_programmer import FileProgrammer

                    factory = FileProgrammer
                programmer = factory(session)
                kwargs = {}
                if image.format.lower() == "bin":
                    kwargs["base_address"] = image.base_address
                programmer.program(str(path), **kwargs)
            except FlashError:
                self._close_after_failure()
                raise
            except FileNotFoundError:
                self._close_after_failure()
                raise FlashError(
                    FlashErrorCode.FILE_NOT_FOUND,
                    "firmware snapshot file was not found",
                ) from None
            except Exception as exc:
                self._close_after_failure()
                raise self._mapped_error(exc, FlashErrorCode.PROGRAM_FAIL) from None

    def verify(self, image: ImageInspection) -> None:
        with self._lock:
            session = self._require_session()
            try:
                for address, expected in self._iter_image_chunks(image):
                    self._verify_expected_bytes(session.target, address, expected)
            except FlashError:
                raise
            except FileNotFoundError:
                raise FlashError(
                    FlashErrorCode.FILE_NOT_FOUND,
                    "firmware snapshot file was not found",
                ) from None
            except Exception as exc:
                raise self._mapped_error(exc, FlashErrorCode.VERIFY_FAIL) from None

    @classmethod
    def _verify_expected_bytes(
        cls, target: Any, address: int, expected: bytes
    ) -> None:
        offset = 0
        while offset < len(expected):
            current = address + offset
            region = cls._flash_region_for_address(target, current)
            size = len(expected) - offset
            if region is not None:
                size = min(size, int(region.start) + int(region.length) - current)
            flash = getattr(region, "flash", None) if region is not None else None
            custom_verify = callable(getattr(flash, "verify_data", None))
            flash_algo = getattr(flash, "flash_algo", None)
            custom_verify = custom_verify or (
                isinstance(flash_algo, dict)
                and flash_algo.get("mklink_custom_verify") is True
            )
            if custom_verify:
                page_size = getattr(region, "page_size", None)
                if (
                    not isinstance(page_size, int)
                    or isinstance(page_size, bool)
                    or page_size <= 0
                ):
                    raise RuntimeError("custom FLM has no valid verification buffer size")
                size = min(size, page_size)
                result = cls._verify_with_flash_algorithm(
                    flash, current, expected[offset : offset + size]
                )
                success = current + size
                if result != success:
                    mismatch = (
                        result
                        if isinstance(result, int)
                        and not isinstance(result, bool)
                        and current <= result < success
                        else current
                    )
                    raise FlashError(
                        FlashErrorCode.VERIFY_FAIL,
                        f"verification mismatch at 0x{mismatch:X}",
                    )
            else:
                actual = cls._read_target_bytes(target, current, size)
                common = min(len(actual), size)
                mismatch = next(
                    (
                        index
                        for index in range(common)
                        if actual[index] != expected[offset + index]
                    ),
                    None,
                )
                if mismatch is None and len(actual) != size:
                    mismatch = common
                if mismatch is not None:
                    raise FlashError(
                        FlashErrorCode.VERIFY_FAIL,
                        f"verification mismatch at 0x{current + mismatch:X}",
                    )
            offset += size

    @staticmethod
    def _flash_region_for_address(target: Any, address: int) -> Any:
        memory_map = getattr(target, "memory_map", ())
        getter = getattr(memory_map, "get_region_for_address", None)
        if callable(getter):
            region = getter(address)
            if region is not None and bool(getattr(region, "is_flash", False)):
                return region
        for region in memory_map:
            if (
                bool(getattr(region, "is_flash", False))
                and int(region.start) <= address < int(region.start) + int(region.length)
            ):
                return region
        return None

    @staticmethod
    def _verify_with_flash_algorithm(flash: Any, address: int, data: bytes) -> Any:
        verifier = getattr(flash, "verify_data", None)
        if callable(verifier):
            return verifier(address, data)

        flash_algo = getattr(flash, "flash_algo", None)
        if (
            not isinstance(flash_algo, dict)
            or flash_algo.get("mklink_custom_verify") is not True
        ):
            raise RuntimeError("custom FLM verification is unavailable")
        pc_verify = flash_algo.get("pc_verify")
        page_buffers = getattr(flash, "page_buffers", ())
        if (
            not isinstance(pc_verify, int)
            or isinstance(pc_verify, bool)
            or not page_buffers
        ):
            raise RuntimeError("custom FLM verification entry is invalid")

        flash.init(flash.Operation.VERIFY)
        try:
            flash.target.write_memory_block8(page_buffers[0], data)
            timeout = flash.target.session.options.get("flash.timeout.program")
            result = flash._call_function_and_wait(
                pc_verify,
                address,
                len(data),
                page_buffers[0],
                timeout=timeout,
            )
            if result == flash.TIMEOUT_ERROR:
                raise RuntimeError("custom FLM verification timed out")
            return result
        finally:
            flash.uninit()

    def reset_run(self, reset_mode: Optional[str] = None) -> None:
        with self._lock:
            session = self._require_session()
            mode = self._reset_mode if reset_mode is None else reset_mode
            if mode not in {"default", "hardware", "software", "core", "system"}:
                raise ValueError(f"unknown reset mode: {mode}")
            try:
                if mode == "default":
                    session.target.reset()
                    return
                from pyocd.core.target import Target

                reset_types = {
                    "hardware": Target.ResetType.HARDWARE,
                    "software": Target.ResetType.DEFAULT,
                    "core": Target.ResetType.CORE,
                    "system": Target.ResetType.SYSTEM,
                }
                session.target.reset(reset_types[mode])
            except FlashError:
                raise
            except Exception as exc:
                raise self._mapped_error(exc, FlashErrorCode.RESET_FAIL) from None

    def memory_regions(self) -> Tuple[MemoryRegion, ...]:
        with self._lock:
            session = self._require_session()
            try:
                result = []
                for region in session.target.memory_map:
                    is_flash = bool(getattr(region, "is_flash", False))
                    is_ram = bool(getattr(region, "is_ram", False))
                    if not is_flash and not is_ram:
                        continue
                    blocksize = (
                        getattr(region, "blocksize", None) if is_flash else None
                    )
                    if (
                        not isinstance(blocksize, int)
                        or isinstance(blocksize, bool)
                        or blocksize <= 0
                    ):
                        blocksize = None
                    result.append(
                        MemoryRegion(
                            name=str(getattr(region, "name", "")),
                            start=int(region.start),
                            length=int(region.length),
                            is_flash=is_flash,
                            writable=(
                                self._is_programmable_flash(region)
                                if is_flash
                                else bool(getattr(region, "is_writable", True))
                            ),
                            sector_size=blocksize,
                        )
                    )
                return tuple(result)
            except Exception as exc:
                if self._is_locked_error(exc):
                    raise FlashError(
                        FlashErrorCode.TARGET_LOCKED,
                        "target memory map is protected",
                    ) from None
                raise FlashError(
                    FlashErrorCode.TARGET_NOT_SUPPORTED,
                    "target memory map is unavailable",
                ) from None

    @staticmethod
    def _iter_image_chunks(
        image: ImageInspection,
    ) -> Iterator[Tuple[int, bytes]]:
        path = Path(image.file_path)
        if image.format.lower() == "bin":
            if image.base_address is None:
                raise FlashError(
                    FlashErrorCode.VERIFY_FAIL, "BIN image has no base address"
                )
            if (
                not isinstance(image.size, int)
                or isinstance(image.size, bool)
                or image.size < 0
                or len(image.segments) != 1
            ):
                raise FlashError(
                    FlashErrorCode.VERIFY_FAIL,
                    "BIN image inspection is inconsistent",
                )
            segment = image.segments[0]
            if (
                image.start != image.base_address
                or image.end != image.start + image.size
                or segment.start != image.start
                or segment.end != image.end
                or segment.length != image.size
            ):
                raise FlashError(
                    FlashErrorCode.VERIFY_FAIL,
                    "BIN image inspection is inconsistent",
                )
            snapshot_size = path.stat().st_size
            if snapshot_size != image.size:
                mismatch = image.base_address + min(snapshot_size, image.size)
                raise FlashError(
                    FlashErrorCode.VERIFY_FAIL,
                    f"verification mismatch at 0x{mismatch:X}",
                )
            address = image.base_address
            remaining = image.size
            with path.open("rb") as stream:
                while remaining:
                    requested = min(4096, remaining)
                    payload = stream.read(requested)
                    if len(payload) != requested:
                        raise FlashError(
                            FlashErrorCode.VERIFY_FAIL,
                            f"verification mismatch at 0x{address + len(payload):X}",
                        )
                    yield address, payload
                    address += len(payload)
                    remaining -= len(payload)
                if stream.read(1):
                    raise FlashError(
                        FlashErrorCode.VERIFY_FAIL,
                        f"verification mismatch at 0x{address:X}",
                    )
            return

        from intelhex import IntelHex

        parsed = IntelHex(str(path))
        for segment in image.segments:
            address = segment.start
            while address < segment.end:
                size = min(4096, segment.end - address)
                yield address, bytes(parsed.tobinarray(start=address, size=size))
                address += size

    @staticmethod
    def _read_target_bytes(target: Any, address: int, size: int) -> bytes:
        read8 = getattr(target, "read_memory_block8", None)
        if callable(read8):
            result = read8(address, size)
            return bytes(result or ())
        read32 = getattr(target, "read_memory_block32", None)
        if callable(read32):
            words = read32(address, (size + 3) // 4)
            output = bytearray()
            for word in words or ():
                output.extend(int(word).to_bytes(4, "little"))
            return bytes(output[:size])
        raise RuntimeError("target does not support block memory reads")

    def _eraser(self, erase_mode: str) -> Any:
        from pyocd.flash.eraser import FlashEraser

        return self._eraser_factory or FlashEraser, FlashEraser.Mode[erase_mode]

    @staticmethod
    def _validated_sector_addresses(target: Any, addresses: Any) -> list[int]:
        values = list(addresses)
        if not values:
            raise FlashError(
                FlashErrorCode.IMAGE_OUT_OF_RANGE,
                "at least one sector address is required",
            )
        unique = sorted(set(values))
        if any(not isinstance(value, int) or isinstance(value, bool) for value in unique):
            raise FlashError(
                FlashErrorCode.IMAGE_OUT_OF_RANGE, "sector address is invalid"
            )
        regions = tuple(target.memory_map)
        for address in unique:
            containing = [
                region
                for region in regions
                if bool(getattr(region, "is_flash", False))
                and int(region.start) <= address < int(region.start) + int(region.length)
            ]
            if not containing:
                raise FlashError(
                    FlashErrorCode.IMAGE_OUT_OF_RANGE,
                    f"sector address 0x{address:X} is outside flash",
                )
            sizes = set()
            for region in containing:
                flash = getattr(region, "flash", None)
                get_sector_info = getattr(flash, "get_sector_info", None)
                if not callable(get_sector_info):
                    raise FlashError(
                        FlashErrorCode.TARGET_NOT_SUPPORTED,
                        "target does not expose reliable sector geometry",
                    )
                try:
                    info = get_sector_info(address)
                except Exception as exc:
                    raise PyOcdBackend._mapped_error(
                        exc, FlashErrorCode.ERASE_FAIL
                    ) from None
                if info is None:
                    raise FlashError(
                        FlashErrorCode.TARGET_NOT_SUPPORTED,
                        "target does not expose reliable sector geometry",
                    )
                try:
                    base = getattr(info, "base_addr", None)
                    size = getattr(info, "size", None)
                except Exception:
                    raise FlashError(
                        FlashErrorCode.TARGET_NOT_SUPPORTED,
                        "target does not expose reliable sector geometry",
                    ) from None
                if (
                    not isinstance(base, int)
                    or isinstance(base, bool)
                    or not isinstance(size, int)
                    or isinstance(size, bool)
                    or size <= 0
                    or base < int(region.start)
                    or base + size > int(region.start) + int(region.length)
                ):
                    raise FlashError(
                        FlashErrorCode.TARGET_NOT_SUPPORTED,
                        "target does not expose reliable sector geometry",
                    )
                if base != address:
                    raise FlashError(
                        FlashErrorCode.IMAGE_OUT_OF_RANGE,
                        f"address 0x{address:X} is not a sector start",
                    )
                sizes.add(size)
            if len(sizes) != 1:
                raise FlashError(
                    FlashErrorCode.TARGET_NOT_SUPPORTED,
                    "target exposes conflicting sector geometry",
                )
        return unique

    @staticmethod
    def _is_programmable_flash(region: Any) -> bool:
        if getattr(region, "flash", None) is not None:
            return True
        return getattr(region, "algo", None) is not None

    def _require_session(self) -> Any:
        if self._session is None:
            raise FlashError(FlashErrorCode.CONNECT_FAIL, "target is not connected")
        return self._session

    def _close_after_failure(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def _resolve_probe(self, probe: Any) -> Any:
        if not isinstance(probe, str):
            return probe
        provider = self._probe_provider
        if provider is None:
            from pyocd.probe.aggregator import DebugProbeAggregator

            provider = DebugProbeAggregator.get_all_connected_probes
        for candidate in provider():
            if getattr(candidate, "unique_id", None) == probe:
                return candidate
        raise FlashError(
            FlashErrorCode.MKLINK_DAP_NOT_FOUND,
            "requested MKLink DAP probe was not found",
        )

    @staticmethod
    def _mapped_error(exc: Exception, fallback: FlashErrorCode) -> FlashError:
        text = str(exc)
        if PyOcdBackend._is_locked_error(exc):
            return FlashError(FlashErrorCode.TARGET_LOCKED, text or "target is locked")
        return FlashError(fallback, text or fallback.value)

    @staticmethod
    def _is_locked_error(exc: Exception) -> bool:
        return _LOCKED_ERROR_PATTERN.search(str(exc)) is not None
