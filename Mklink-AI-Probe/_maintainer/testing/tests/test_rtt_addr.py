from pathlib import Path
from types import SimpleNamespace

from mklink import rtt_addr
from mklink.elf_backend import ElfParseError


def test_binary_symbol_search_uses_builtin_pyelftools_without_subprocess(
    monkeypatch, tmp_path,
):
    binary = tmp_path / "app.axf"
    binary.write_bytes(b"ELF")
    monkeypatch.setattr(
        rtt_addr,
        "list_elf_symbols",
        lambda source, backend: [
            SimpleNamespace(name="other", address=0x08000000),
            SimpleNamespace(name="_SEGGER_RTT", address=0x20001A40),
        ],
    )
    monkeypatch.setattr(
        rtt_addr.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("external tools must not run after builtin parsing succeeds")
        ),
    )

    result = rtt_addr.diagnose_rtt_addr(str(binary))

    assert result.addr == "0x20001a40"
    assert result.details == ["内置 pyelftools 已解析 _SEGGER_RTT"]


def test_binary_symbol_search_accepts_portable_writable_memory_ranges(
    monkeypatch, tmp_path,
):
    binary = tmp_path / "hpm.elf"
    binary.write_bytes(b"ELF")
    monkeypatch.setattr(
        rtt_addr,
        "list_elf_symbols",
        lambda source, backend: [
            SimpleNamespace(name="_SEGGER_RTT", address=0x0008E488, size=168),
        ],
    )
    monkeypatch.setattr(
        rtt_addr,
        "writable_memory_ranges",
        lambda source, backend: ((0x00080000, 0x00100000),),
    )

    result = rtt_addr.diagnose_rtt_addr(str(binary))

    assert result.addr == "0x0008e488"
    assert result.details == ["内置 pyelftools 已解析 _SEGGER_RTT"]


def test_binary_symbol_search_does_not_fallback_when_builtin_has_no_symbol(
    monkeypatch, tmp_path,
):
    binary = tmp_path / "app.elf"
    binary.write_bytes(b"ELF")
    monkeypatch.setattr(rtt_addr, "list_elf_symbols", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        rtt_addr.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a valid builtin parse must not launch compatibility tools")
        ),
    )

    result = rtt_addr.diagnose_rtt_addr(str(binary))

    assert result.addr is None
    assert "未找到 _SEGGER_RTT" in result.details[0]


def test_binary_symbol_search_hides_native_tools_on_windows(monkeypatch, tmp_path):
    binary = tmp_path / "app.axf"
    binary.write_bytes(b"ELF")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="20001A40 B _SEGGER_RTT\n", stderr="")

    monkeypatch.setattr(rtt_addr.os, "name", "nt")
    monkeypatch.setattr(
        rtt_addr,
        "list_elf_symbols",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ElfParseError("IAR format")),
    )
    monkeypatch.setattr(rtt_addr.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(rtt_addr.subprocess, "run", run)

    result = rtt_addr.diagnose_rtt_addr(str(binary))

    assert result.addr == "0x20001A40"
    assert calls[0][1]["creationflags"] == 0x08000000


def test_binary_symbol_search_uses_portable_flags_off_windows(monkeypatch, tmp_path):
    binary = tmp_path / "app.elf"
    binary.write_bytes(b"ELF")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(rtt_addr.os, "name", "posix")
    monkeypatch.setattr(
        rtt_addr,
        "list_elf_symbols",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ElfParseError("IAR format")),
    )
    monkeypatch.setattr(rtt_addr.subprocess, "run", run)

    rtt_addr.diagnose_rtt_addr(str(binary))

    assert calls
    assert all(kwargs["creationflags"] == 0 for _command, kwargs in calls)
