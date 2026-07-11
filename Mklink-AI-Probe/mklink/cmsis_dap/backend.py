"""Lazy, serialised pyOCD backend for online flash operations."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Tuple

from .errors import FlashError, FlashErrorCode
from .models import ImageInspection, MemoryRegion


_LOCKED_ERROR_PATTERN = re.compile(
    r"\bread(?:out)?\s+protection\b"
    r"|\b(?:target|device|flash)(?:\s+is)?\s+locked\b"
    r"|\brdp\s+level\s+(?:1(?:\s*/\s*2)?|2)\b"
    r"|\bmass\s+erase\s+disabled\s+due\s+protection\b",
    re.IGNORECASE,
)


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
                    actual = self._read_target_bytes(session.target, address, len(expected))
                    common = min(len(actual), len(expected))
                    mismatch = next(
                        (
                            offset
                            for offset in range(common)
                            if actual[offset] != expected[offset]
                        ),
                        None,
                    )
                    if mismatch is None and len(actual) != len(expected):
                        mismatch = common
                    if mismatch is not None:
                        raise FlashError(
                            FlashErrorCode.VERIFY_FAIL,
                            f"verification mismatch at 0x{address + mismatch:X}",
                        )
            except FlashError:
                raise
            except FileNotFoundError:
                raise FlashError(
                    FlashErrorCode.FILE_NOT_FOUND,
                    "firmware snapshot file was not found",
                ) from None
            except Exception as exc:
                raise self._mapped_error(exc, FlashErrorCode.VERIFY_FAIL) from None

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
