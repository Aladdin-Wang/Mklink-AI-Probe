import pytest
from types import SimpleNamespace

from mklink.elf_backend import (
    ElfSection,
    ElfSymbol,
    ElfBackendConfigError,
    elf_status,
    resolve_elf_backend,
)
from mklink.elf_external import ExternalElfBackend
from mklink.memmap import analyze_memmap
from mklink.project_config import save_toolchain_config
from mklink.superwatch import _symbol_size_lookup
from mklink.vofa_viewer import resolve_variable_names


def test_backend_defaults_to_builtin_when_external_tool_exists(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("MKLINK_ELF_BACKEND", raising=False)
    monkeypatch.setattr("mklink.toolchain.resolve_readelf", lambda: "readelf.exe")

    assert resolve_elf_backend(project_root=tmp_path) == "builtin"


def test_tool_paths_alone_do_not_activate_external_backend(monkeypatch, tmp_path):
    monkeypatch.delenv("MKLINK_ELF_BACKEND", raising=False)
    save_toolchain_config(tmp_path, {"readelf": "C:/tools/readelf.exe"})

    assert resolve_elf_backend(project_root=tmp_path) == "builtin"


def test_project_config_can_explicitly_select_external(monkeypatch, tmp_path):
    monkeypatch.delenv("MKLINK_ELF_BACKEND", raising=False)
    save_toolchain_config(tmp_path, {"elf_backend": "external"})

    assert resolve_elf_backend(project_root=tmp_path) == "external"


def test_explicit_selection_precedes_environment_and_project(monkeypatch, tmp_path):
    save_toolchain_config(tmp_path, {"elf_backend": "external"})
    monkeypatch.setenv("MKLINK_ELF_BACKEND", "external")

    assert resolve_elf_backend("builtin", project_root=tmp_path) == "builtin"


def test_environment_precedes_project_config(monkeypatch, tmp_path):
    save_toolchain_config(tmp_path, {"elf_backend": "builtin"})
    monkeypatch.setenv("MKLINK_ELF_BACKEND", "external")

    assert resolve_elf_backend(project_root=tmp_path) == "external"


@pytest.mark.parametrize("value", ["", "auto", "gnu", "other"])
def test_invalid_backend_is_rejected(monkeypatch, tmp_path, value):
    monkeypatch.delenv("MKLINK_ELF_BACKEND", raising=False)

    with pytest.raises(ElfBackendConfigError, match="Invalid ELF backend"):
        resolve_elf_backend(value, project_root=tmp_path)


def test_status_separates_builtin_and_external_availability(monkeypatch, tmp_path):
    monkeypatch.delenv("MKLINK_ELF_BACKEND", raising=False)
    monkeypatch.setattr("mklink.toolchain.resolve_readelf", lambda: None)
    monkeypatch.setattr("mklink.toolchain.resolve_addr2line", lambda: None)

    status = elf_status(project_root=tmp_path)

    assert status["elf_backend"] == "builtin"
    assert status["builtin_elf_available"] is True
    assert status["elf_available"] is True
    assert status["external_elf_available"] is False
    assert status["readelf_available"] is False


def test_external_backend_normalizes_readelf_symbols(monkeypatch):
    output = """
   1: 20000010     4 OBJECT  GLOBAL DEFAULT    3 g_counter
   2: 08000101    12 FUNC    GLOBAL DEFAULT    1 HardFault_Handler
   3: 00000000     4 OBJECT  GLOBAL DEFAULT  UND missing
"""
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr("mklink.elf_external.subprocess.run", run)
    backend = ExternalElfBackend(readelf="readelf.exe")

    symbols = backend.symbols("firmware.axf")

    assert [(item.name, item.kind) for item in symbols] == [
        ("g_counter", "object"),
        ("HardFault_Handler", "function"),
    ]
    assert calls[0][0] == ["readelf.exe", "-sW", "firmware.axf"]


def test_builtin_consumers_use_structured_service_without_subprocess(monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("unexpected GNU subprocess")

    monkeypatch.setattr("subprocess.run", unexpected)
    monkeypatch.setattr(
        "mklink.elf_backend.list_elf_sections",
        lambda *_args, **_kwargs: [
            ElfSection(".data", 0x20000000, 16, 0x3, "SHT_PROGBITS")
        ],
    )
    monkeypatch.setattr(
        "mklink.elf_backend.list_elf_symbols",
        lambda *_args, **_kwargs: [
            ElfSymbol(
                "g_counter", 0x20000010, 4, "object", "global", "default", 3
            )
        ],
    )

    summary = analyze_memmap("firmware.axf", backend="builtin")
    sizes = _symbol_size_lookup("firmware.axf", backend="builtin")
    resolved = resolve_variable_names(
        ["g_counter", "uint32_t"], "firmware.axf", backend="builtin"
    )

    assert summary["ram_used"] == 16
    assert sizes == {"g_counter": 4}
    assert resolved == ["0x20000010", "uint32_t"]
