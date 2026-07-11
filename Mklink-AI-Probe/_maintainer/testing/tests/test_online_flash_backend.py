from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from mklink.cmsis_dap.backend import PyOcdBackend
from mklink.cmsis_dap.errors import FlashError, FlashErrorCode
from mklink.cmsis_dap.models import ImageInspection, ImageSegment, MemoryRegion


class FakeTarget:
    def __init__(self, memory_map=()) -> None:
        self.reset_and_halt_calls = 0
        self.memory_map = memory_map
        self.reset_calls = []

    def reset_and_halt(self) -> None:
        self.reset_and_halt_calls += 1

    def reset(self, reset_type=None) -> None:
        self.reset_calls.append(reset_type)


class FakeSession:
    def __init__(self, target: FakeTarget | None = None) -> None:
        self.target = target or FakeTarget()
        self.open_calls = 0
        self.close_calls = 0

    def open(self) -> None:
        self.open_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class FakeProbe:
    def __init__(self, unique_id: str) -> None:
        self.unique_id = unique_id


class FakeRegion:
    def __init__(
        self,
        start: int,
        length: int,
        *,
        is_flash: bool = True,
        is_ram: bool = False,
        is_writable: bool = True,
        blocksize: int | None = 0x100,
        name: str = "region",
    ) -> None:
        self.start = start
        self.length = length
        self.end = start + length
        self.is_flash = is_flash
        self.is_ram = is_ram
        self.is_writable = is_writable
        self.blocksize = blocksize
        self.name = name
        self.flash = (
            UniformFlash(start, blocksize)
            if isinstance(blocksize, int) and blocksize > 0
            else None
        )


class FakeSectorInfo:
    def __init__(self, base_addr: int, size: int) -> None:
        self.base_addr = base_addr
        self.size = size


class UniformFlash:
    def __init__(self, start: int, size: int) -> None:
        self.start = start
        self.size = size

    def get_sector_info(self, address: int) -> FakeSectorInfo:
        base = self.start + ((address - self.start) // self.size) * self.size
        return FakeSectorInfo(base, self.size)


def assert_error(code: FlashErrorCode, call) -> FlashError:
    with pytest.raises(FlashError) as raised:
        call()
    assert raised.value.code is code
    return raised.value


def test_connect_halts_target_and_disconnect_closes_session() -> None:
    session = FakeSession()
    backend = PyOcdBackend(session_factory=lambda probe, options: session)

    backend.connect(object(), "HPM5300", 1_000_000)
    backend.disconnect()

    assert session.open_calls == 1
    assert session.target.reset_and_halt_calls == 1
    assert session.close_calls == 1


def test_session_factory_receives_probe_and_options_positionally() -> None:
    session = FakeSession()

    def positional_factory(probe, options, /):
        assert options["target_override"] == "HPM5300"
        return session

    backend = PyOcdBackend(session_factory=positional_factory)
    backend.connect(object(), "HPM5300", 1_000_000)
    backend.disconnect()


def test_disconnect_clears_session_even_when_close_fails() -> None:
    class BrokenClose(FakeSession):
        def close(self):
            self.close_calls += 1
            raise RuntimeError("USB close failed")

    session = BrokenClose()
    backend = PyOcdBackend(session_factory=lambda probe, options: session)
    backend.connect(object(), "HPM5300", 1_000_000)

    assert_error(FlashErrorCode.CONNECT_FAIL, backend.disconnect)
    backend.disconnect()
    assert session.close_calls == 1


def test_import_does_not_load_pyocd_or_usb() -> None:
    script = (
        "import sys; import mklink.cmsis_dap.backend; "
        "assert not any(n == 'pyocd' or n.startswith('pyocd.') for n in sys.modules); "
        "assert not any(n == 'usb' or n.startswith('usb.') for n in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", script], check=True)


def test_connect_resolves_only_an_exact_unique_probe_id() -> None:
    first = FakeProbe("FIRST")
    wanted = FakeProbe("WANTED")
    seen = []
    backend = PyOcdBackend(
        session_factory=lambda probe, options: seen.append(probe) or FakeSession(),
        probe_provider=lambda: [first, wanted],
    )

    backend.connect("WANTED", "HPM5300", 1_000_000)

    assert seen == [wanted]
    backend.disconnect()

    missing = PyOcdBackend(
        session_factory=lambda probe, options: pytest.fail("must not fall back"),
        probe_provider=lambda: [first],
    )
    assert_error(
        FlashErrorCode.MKLINK_DAP_NOT_FOUND,
        lambda: missing.connect("WANTED", "HPM5300", 1_000_000),
    )


def test_connect_builds_supported_options_and_reconnect_closes_old(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "target.pack"
    pack.write_bytes(b"pack")
    sessions = [FakeSession(), FakeSession()]
    calls = []

    def factory(probe, options):
        calls.append((probe, options))
        return sessions[len(calls) - 1]

    backend = PyOcdBackend(session_factory=factory)
    first_probe, second_probe = object(), object()
    backend.connect(
        first_probe,
        "HPM5300",
        2_000_000,
        pack=str(pack),
        connect_mode="under-reset",
        reset_mode="hardware",
    )
    backend.connect(second_probe, "HPM5361", 4_000_000)

    assert calls == [
        (
            first_probe,
            {
                "target_override": "HPM5300",
                "frequency": 2_000_000,
                "connect_mode": "under-reset",
                "auto_unlock": False,
                "pack": str(pack.resolve()),
            },
        ),
        (
            second_probe,
            {
                "target_override": "HPM5361",
                "frequency": 4_000_000,
                "connect_mode": "halt",
                "auto_unlock": False,
            },
        ),
    ]
    assert sessions[0].close_calls == 1
    backend.disconnect()


def test_connect_closes_partial_session_when_open_fails() -> None:
    class BrokenSession(FakeSession):
        def open(self) -> None:
            raise RuntimeError("transport failure")

    session = BrokenSession()
    backend = PyOcdBackend(session_factory=lambda probe, options: session)

    assert_error(
        FlashErrorCode.CONNECT_FAIL,
        lambda: backend.connect(object(), "HPM5300", 1_000_000),
    )
    assert session.close_calls == 1
    backend.disconnect()


@pytest.mark.parametrize("frequency", [0, -1, True])
def test_connect_rejects_invalid_frequency(frequency) -> None:
    backend = PyOcdBackend(session_factory=lambda probe, options: FakeSession())
    with pytest.raises(ValueError):
        backend.connect(object(), "HPM5300", frequency)


def test_connect_rejects_missing_or_non_pack_path(tmp_path: Path) -> None:
    backend = PyOcdBackend(session_factory=lambda probe, options: FakeSession())
    assert_error(
        FlashErrorCode.FILE_NOT_FOUND,
        lambda: backend.connect(object(), "HPM5300", 1, pack=str(tmp_path / "x.pack")),
    )
    wrong = tmp_path / "x.txt"
    wrong.write_text("x")
    assert_error(
        FlashErrorCode.TARGET_NOT_SUPPORTED,
        lambda: backend.connect(object(), "HPM5300", 1, pack=str(wrong)),
    )


def connected_backend(*, target=None, programmer_factory=None, eraser_factory=None):
    session = FakeSession(target or FakeTarget())
    backend = PyOcdBackend(
        session_factory=lambda probe, options: session,
        programmer_factory=programmer_factory,
        eraser_factory=eraser_factory,
    )
    backend.connect(object(), "HPM5300", 1_000_000)
    return backend, session


def test_operations_require_a_connected_session() -> None:
    backend = PyOcdBackend()
    for operation in (
        backend.erase_chip,
        lambda: backend.erase_sectors([0x80000000]),
        lambda: backend.program(ImageInspection("missing")),
        lambda: backend.verify(ImageInspection("missing")),
        backend.reset_run,
        backend.memory_regions,
    ):
        assert_error(FlashErrorCode.CONNECT_FAIL, operation)


def test_chip_and_sector_erase_use_exact_modes_and_sorted_unique_addresses() -> None:
    events = []

    class Eraser:
        def __init__(self, session, mode):
            events.append(("create", session, mode.name))

        def erase(self, addresses=None):
            events.append(("erase", addresses))

    target = FakeTarget((FakeRegion(0x80000000, 0x1000, blocksize=0x100),))
    backend, session = connected_backend(target=target, eraser_factory=Eraser)

    backend.erase_chip()
    backend.erase_sectors([0x80000200, 0x80000000, 0x80000200])

    assert events == [
        ("create", session, "CHIP"),
        ("erase", None),
        ("create", session, "SECTOR"),
        ("erase", [0x80000000, 0x80000200]),
    ]
    backend.disconnect()


@pytest.mark.parametrize(
    ("regions", "addresses", "code"),
    [
        ((FakeRegion(0x80000000, 0x1000),), [], FlashErrorCode.IMAGE_OUT_OF_RANGE),
        ((FakeRegion(0x80000000, 0x1000),), [0x80000001], FlashErrorCode.IMAGE_OUT_OF_RANGE),
        ((FakeRegion(0x80000000, 0x1000),), [0x90000000], FlashErrorCode.IMAGE_OUT_OF_RANGE),
        ((FakeRegion(0x80000000, 0x1000, blocksize=None),), [0x80000000], FlashErrorCode.TARGET_NOT_SUPPORTED),
    ],
)
def test_sector_erase_validates_flash_geometry(regions, addresses, code) -> None:
    backend, _ = connected_backend(target=FakeTarget(regions), eraser_factory=pytest.fail)
    assert_error(code, lambda: backend.erase_sectors(addresses))
    backend.disconnect()


def test_sector_erase_accepts_real_flash_region_with_rx_access() -> None:
    from pyocd.core.memory_map import FlashRegion

    erased = []

    class Eraser:
        def __init__(self, session, mode):
            pass

        def erase(self, addresses=None):
            erased.append(addresses)

    region = FlashRegion(start=0x80000000, length=0x1000, blocksize=0x100)
    region.flash = UniformFlash(region.start, region.blocksize)
    assert region.is_writable is False
    backend, _ = connected_backend(
        target=FakeTarget((region,)), eraser_factory=Eraser
    )

    backend.erase_sectors([0x80000000])

    assert erased == [[0x80000000]]
    backend.disconnect()


def test_program_bin_passes_base_and_hex_does_not(tmp_path: Path) -> None:
    calls = []

    class Programmer:
        def __init__(self, session):
            calls.append(("create", session))

        def program(self, path, **kwargs):
            calls.append(("program", path, kwargs))

    binary = tmp_path / "firmware.bin"
    binary.write_bytes(b"bin")
    ihex = tmp_path / "firmware.hex"
    ihex.write_text(":00000001FF\n", encoding="ascii")
    backend, session = connected_backend(programmer_factory=Programmer)

    backend.program(
        ImageInspection("bin", file_path=str(binary), format="bin", base_address=0x80000000)
    )
    backend.program(ImageInspection("hex", file_path=str(ihex), format="hex"))

    assert calls == [
        ("create", session),
        ("program", str(binary), {"base_address": 0x80000000}),
        ("create", session),
        ("program", str(ihex), {}),
    ]
    backend.disconnect()


def test_program_maps_locked_error_and_closes_session(tmp_path: Path) -> None:
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"x")

    class Programmer:
        def __init__(self, session):
            pass

        def program(self, path, **kwargs):
            raise RuntimeError("target locked")

    backend, session = connected_backend(programmer_factory=Programmer)
    assert_error(
        FlashErrorCode.TARGET_LOCKED,
        lambda: backend.program(
            ImageInspection("bin", file_path=str(firmware), format="bin", base_address=0)
        ),
    )
    assert session.close_calls == 1
    assert_error(FlashErrorCode.CONNECT_FAIL, backend.erase_chip)


def test_program_maps_file_disappearance_to_file_not_found(tmp_path: Path) -> None:
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"x")

    class VanishedProgrammer:
        def __init__(self, session):
            pass

        def program(self, path, **kwargs):
            raise FileNotFoundError("snapshot vanished")

    backend, _ = connected_backend(programmer_factory=VanishedProgrammer)
    assert_error(
        FlashErrorCode.FILE_NOT_FOUND,
        lambda: backend.program(
            ImageInspection("bin", file_path=str(firmware), format="bin", base_address=0)
        ),
    )


def test_sector_geometry_read_failure_maps_to_erase_fail() -> None:
    class BrokenTarget(FakeTarget):
        @property
        def memory_map(self):
            raise RuntimeError("memory map unavailable")

        @memory_map.setter
        def memory_map(self, value):
            pass

    backend, _ = connected_backend(target=BrokenTarget())
    assert_error(
        FlashErrorCode.ERASE_FAIL,
        lambda: backend.erase_sectors([0x80000000]),
    )
    backend.disconnect()


def test_sector_erase_uses_actual_variable_sector_geometry() -> None:
    events = []

    class VariableFlash:
        def get_sector_info(self, address):
            if address < 0x1000:
                return FakeSectorInfo(0, 0x1000)
            return FakeSectorInfo(0x1000, 0x2000)

    class Eraser:
        def __init__(self, session, mode):
            pass

        def erase(self, addresses=None):
            events.append(addresses)

    region = FakeRegion(0, 0x4000, blocksize=0x400)
    region.flash = VariableFlash()
    backend, _ = connected_backend(
        target=FakeTarget((region,)), eraser_factory=Eraser
    )

    assert_error(
        FlashErrorCode.IMAGE_OUT_OF_RANGE,
        lambda: backend.erase_sectors([0x400]),
    )
    backend.erase_sectors([0x1000, 0x1000])

    assert events == [[0x1000]]
    backend.disconnect()


@pytest.mark.parametrize("kind", ["missing", "none", "size", "base"])
def test_sector_erase_rejects_unreliable_sector_info(kind) -> None:
    class Flash:
        def get_sector_info(self, address):
            if kind == "none":
                return None
            if kind == "size":
                return FakeSectorInfo(address, 0)
            return type("Info", (), {"size": 0x100})()

    region = FakeRegion(0, 0x1000)
    if kind == "missing":
        del region.flash
    else:
        region.flash = Flash()
    backend, _ = connected_backend(target=FakeTarget((region,)))

    assert_error(
        FlashErrorCode.TARGET_NOT_SUPPORTED,
        lambda: backend.erase_sectors([0]),
    )
    backend.disconnect()


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("sector query failed", FlashErrorCode.ERASE_FAIL),
        ("flash locked", FlashErrorCode.TARGET_LOCKED),
    ],
)
def test_sector_info_query_exceptions_are_mapped(message, code) -> None:
    class Flash:
        def get_sector_info(self, address):
            raise RuntimeError(message)

    region = FakeRegion(0, 0x1000)
    region.flash = Flash()
    backend, _ = connected_backend(target=FakeTarget((region,)))

    assert_error(code, lambda: backend.erase_sectors([0]))
    backend.disconnect()


def test_sector_info_query_flash_error_is_remapped() -> None:
    class Flash:
        def get_sector_info(self, address):
            raise FlashError(FlashErrorCode.PROGRAM_FAIL, "sector query failed")

    region = FakeRegion(0, 0x1000)
    region.flash = Flash()
    backend, _ = connected_backend(target=FakeTarget((region,)))

    assert_error(FlashErrorCode.ERASE_FAIL, lambda: backend.erase_sectors([0]))
    backend.disconnect()


class MemoryTarget(FakeTarget):
    def __init__(self, data: dict[int, int]) -> None:
        super().__init__()
        self.data = data
        self.read_calls = []

    def read_memory_block8(self, address: int, size: int):
        self.read_calls.append((address, size))
        return [self.data[address + offset] for offset in range(size)]


def ihex_record(address: int, record_type: int, data: bytes = b"") -> str:
    payload = bytes((len(data), address >> 8, address & 0xFF, record_type)) + data
    return ":" + (payload + bytes((-sum(payload) & 0xFF,))).hex().upper()


def test_verify_bin_reads_in_bounded_chunks_and_reports_first_mismatch(
    tmp_path: Path,
) -> None:
    payload = bytes(range(256)) * 20
    base = 0x80000000
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(payload)
    target = MemoryTarget({base + index: value for index, value in enumerate(payload)})
    backend, _ = connected_backend(target=target)
    image = ImageInspection(
        "bin",
        file_path=str(firmware),
        format="bin",
        size=len(payload),
        start=base,
        end=base + len(payload),
        segments=(ImageSegment(base, base + len(payload)),),
        base_address=base,
    )

    backend.verify(image)

    assert target.read_calls == [(base, 4096), (base + 4096, len(payload) - 4096)]
    target.data[base + 4100] ^= 0xFF
    error = assert_error(FlashErrorCode.VERIFY_FAIL, lambda: backend.verify(image))
    assert "0x80001004" in error.message
    backend.disconnect()


def test_verify_short_read_reports_first_missing_address(tmp_path: Path) -> None:
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"abcd")

    class ShortTarget(FakeTarget):
        def read_memory_block8(self, address, size):
            return [ord("a"), ord("b")]

    backend, _ = connected_backend(target=ShortTarget())
    image = ImageInspection(
        "bin",
        file_path=str(firmware),
        format="bin",
        size=4,
        start=0x1000,
        end=0x1004,
        segments=(ImageSegment(0x1000, 0x1004),),
        base_address=0x1000,
    )
    error = assert_error(FlashErrorCode.VERIFY_FAIL, lambda: backend.verify(image))
    assert "0x1002" in error.message
    backend.disconnect()


@pytest.mark.parametrize(
    ("payload", "mismatch_address"),
    [(b"ab", 0x1002), (b"abcdef", 0x1004)],
)
def test_verify_bin_rejects_snapshot_size_change(
    tmp_path: Path, payload: bytes, mismatch_address: int
) -> None:
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(payload)
    target = MemoryTarget(
        {0x1000 + offset: value for offset, value in enumerate(b"abcd")}
    )
    backend, _ = connected_backend(target=target)
    image = ImageInspection(
        "bin",
        file_path=str(firmware),
        format="bin",
        size=4,
        start=0x1000,
        end=0x1004,
        segments=(ImageSegment(0x1000, 0x1004),),
        base_address=0x1000,
    )

    error = assert_error(FlashErrorCode.VERIFY_FAIL, lambda: backend.verify(image))

    assert f"0x{mismatch_address:X}" in error.message
    backend.disconnect()


def test_verify_sparse_hex_reads_only_inspected_segments(tmp_path: Path) -> None:
    first, second = 0x80000000, 0x80010000
    firmware = tmp_path / "firmware.hex"
    firmware.write_text(
        "\n".join(
            (
                ihex_record(0, 4, b"\x80\x00"),
                ihex_record(0, 0, b"ab"),
                ihex_record(0, 4, b"\x80\x01"),
                ihex_record(0, 0, b"cd"),
                ihex_record(0, 1),
            )
        )
        + "\n",
        encoding="ascii",
    )
    target = MemoryTarget(
        {first: ord("a"), first + 1: ord("b"), second: ord("c"), second + 1: ord("d")}
    )
    backend, _ = connected_backend(target=target)
    image = ImageInspection(
        "hex",
        file_path=str(firmware),
        format="hex",
        segments=(ImageSegment(first, first + 2), ImageSegment(second, second + 2)),
    )

    backend.verify(image)

    assert target.read_calls == [(first, 2), (second, 2)]
    backend.disconnect()


def test_verify_supports_word_read_api(tmp_path: Path) -> None:
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"abcde")

    class WordTarget(FakeTarget):
        def read_memory_block32(self, address, count):
            assert count == 2
            return [0x64636261, 0x00000065]

    backend, _ = connected_backend(target=WordTarget())
    backend.verify(
        ImageInspection(
            "bin",
            file_path=str(firmware),
            format="bin",
            size=5,
            start=0x1000,
            end=0x1005,
            segments=(ImageSegment(0x1000, 0x1005),),
            base_address=0x1000,
        )
    )
    backend.disconnect()


def test_reset_uses_stored_and_overridden_public_reset_types() -> None:
    target = FakeTarget()
    session = FakeSession(target)
    backend = PyOcdBackend(session_factory=lambda probe, options: session)
    backend.connect(object(), "HPM5300", 1_000_000, reset_mode="hardware")

    backend.reset_run()
    backend.reset_run("default")
    backend.reset_run("software")
    backend.reset_run("core")
    backend.reset_run("system")

    assert [getattr(value, "name", None) for value in target.reset_calls] == [
        "HARDWARE",
        None,
        "DEFAULT",
        "CORE",
        "SYSTEM",
    ]
    with pytest.raises(ValueError):
        backend.reset_run("mystery")
    backend.disconnect()


def test_memory_regions_converts_only_flash_and_ram() -> None:
    regions = (
        FakeRegion(0x80000000, 0x1000, blocksize=0x100, name="flash"),
        FakeRegion(0x10000000, 0x800, is_flash=False, is_ram=True, blocksize=None, name="ram"),
        FakeRegion(0x40000000, 0x100, is_flash=False, blocksize=None, name="device"),
    )
    backend, _ = connected_backend(target=FakeTarget(regions))

    assert backend.memory_regions() == (
        MemoryRegion("flash", 0x80000000, 0x1000, True, True, 0x100),
        MemoryRegion("ram", 0x10000000, 0x800, False, True, None),
    )
    backend.disconnect()


def test_memory_regions_marks_real_rx_flash_as_programmable() -> None:
    from pyocd.core.memory_map import FlashRegion

    region = FlashRegion(
        start=0x80000000,
        length=0x1000,
        blocksize=0x100,
        name="real-flash",
    )
    region.flash = UniformFlash(region.start, region.blocksize)
    assert region.is_writable is False
    backend, _ = connected_backend(target=FakeTarget((region,)))

    assert backend.memory_regions() == (
        MemoryRegion("real-flash", 0x80000000, 0x1000, True, True, 0x100),
    )
    backend.disconnect()


@pytest.mark.parametrize("failure", ["iteration", "property"])
def test_memory_regions_maps_memory_map_failures_without_leaking_details(failure) -> None:
    secret = "INTERNAL transport detail"

    class BrokenMap:
        def __iter__(self):
            raise RuntimeError(secret)

    class BrokenRegion:
        @property
        def is_flash(self):
            raise RuntimeError(secret)

    memory_map = BrokenMap() if failure == "iteration" else (BrokenRegion(),)
    backend, _ = connected_backend(target=FakeTarget(memory_map))

    error = assert_error(FlashErrorCode.TARGET_NOT_SUPPORTED, backend.memory_regions)
    assert error.message == "target memory map is unavailable"
    assert secret not in error.message
    backend.disconnect()


def test_memory_regions_maps_locked_failure_without_leaking_details() -> None:
    class LockedMap:
        def __iter__(self):
            raise RuntimeError("read protection internal detail")

    backend, _ = connected_backend(target=FakeTarget(LockedMap()))

    error = assert_error(FlashErrorCode.TARGET_LOCKED, backend.memory_regions)
    assert error.message == "target memory map is protected"
    backend.disconnect()


def test_memory_regions_remaps_flash_error_without_leaking_details() -> None:
    secret = "INTERNAL flash error detail"

    class BrokenRegion:
        @property
        def is_flash(self):
            raise FlashError(FlashErrorCode.PROGRAM_FAIL, secret)

    backend, _ = connected_backend(target=FakeTarget((BrokenRegion(),)))

    error = assert_error(FlashErrorCode.TARGET_NOT_SUPPORTED, backend.memory_regions)
    assert error.message == "target memory map is unavailable"
    assert secret not in error.message
    backend.disconnect()


def test_public_operations_are_serialized() -> None:
    state = {"active": 0, "maximum": 0}
    state_lock = threading.Lock()

    class SlowEraser:
        def __init__(self, session, mode):
            pass

        def erase(self, addresses=None):
            with state_lock:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            time.sleep(0.03)
            with state_lock:
                state["active"] -= 1

    backend, _ = connected_backend(eraser_factory=SlowEraser)
    threads = [threading.Thread(target=backend.erase_chip) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert state["maximum"] == 1
    backend.disconnect()


def test_connect_and_erase_map_locked_failures() -> None:
    class LockedSession(FakeSession):
        def open(self):
            raise RuntimeError("read protection enabled")

    assert_error(
        FlashErrorCode.TARGET_LOCKED,
        lambda: PyOcdBackend(
            session_factory=lambda probe, options: LockedSession()
        ).connect(object(), "HPM5300", 1),
    )

    class LockedEraser:
        def __init__(self, session, mode):
            pass

        def erase(self, addresses=None):
            raise RuntimeError("device locked")

    backend, _ = connected_backend(eraser_factory=LockedEraser)
    assert_error(FlashErrorCode.TARGET_LOCKED, backend.erase_chip)
    backend.disconnect()


@pytest.mark.parametrize(
    "message",
    [
        "read protection enabled",
        "readout protection enabled",
        "target locked",
        "device is locked",
        "flash locked",
        "RDP level 1",
        "RDP level 2",
        "mass erase disabled due protection",
    ],
)
def test_erase_maps_specific_lock_phrases(message) -> None:
    class LockedEraser:
        def __init__(self, session, mode):
            pass

        def erase(self, addresses=None):
            raise RuntimeError(message)

    backend, _ = connected_backend(eraser_factory=LockedEraser)

    assert_error(FlashErrorCode.TARGET_LOCKED, backend.erase_chip)
    backend.disconnect()


@pytest.mark.parametrize(
    "message", ["security extension unsupported", "protected method missing"]
)
def test_erase_does_not_treat_generic_security_words_as_locked(message) -> None:
    class BrokenEraser:
        def __init__(self, session, mode):
            pass

        def erase(self, addresses=None):
            raise RuntimeError(message)

    backend, _ = connected_backend(eraser_factory=BrokenEraser)

    assert_error(FlashErrorCode.ERASE_FAIL, backend.erase_chip)
    backend.disconnect()
