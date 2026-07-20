import pytest

from mklink.elf_backend import (
    ElfBackendConfigError,
    elf_status,
    resolve_elf_backend,
)
from mklink.project_config import save_toolchain_config


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
