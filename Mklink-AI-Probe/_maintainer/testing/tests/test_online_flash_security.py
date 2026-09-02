from pathlib import Path

import pytest

from mklink.cmsis_dap.builtin_flm_bundle import BuiltinOptionAlgorithm
from mklink.cmsis_dap.errors import FlashError, FlashErrorCode
from mklink.cmsis_dap.security import (
    STM32F1_OPTION_FLM_SHA256,
    STM32F4_OPTION_FLM_SHA256,
    STM32G4_OPTION_FLM_SHA256,
    require_security_capability,
    security_capability,
)


def _algorithm(tmp_path: Path, digest: str = STM32F1_OPTION_FLM_SHA256):
    return BuiltinOptionAlgorithm(
        target_part="STM32F103xE",
        file_name="STM32F10x_OPT.FLM",
        path=tmp_path / "STM32F10x_OPT.FLM",
        sha256=digest,
        ram_start=0x20000000,
        ram_size=0x10000,
    )


def test_stm32f103_is_enabled_only_with_pinned_option_algorithm(monkeypatch, tmp_path):
    algorithm = _algorithm(tmp_path)
    monkeypatch.setattr(
        "mklink.cmsis_dap.security.discover_builtin_option_algorithm",
        lambda part: algorithm if part == "STM32F103xE" else None,
    )

    capability = security_capability("STM32F103RE")

    assert capability.supported is True
    assert capability.family == "stm32f103-rdp1"
    assert capability.unlock_erases_flash is True
    assert capability.reversible_lock is True
    assert capability.option_address == 0x1FFFF800
    assert capability.option_size == 16
    assert security_capability("STM32F103VE").supported is True
    assert security_capability("STM32F103xE").supported is True


def test_gd32_remains_disabled_until_hardware_validation():
    capability = security_capability("GD32F103RE")

    assert capability.supported is False
    assert "真机验证" in capability.reason
    with pytest.raises(FlashError) as raised:
        require_security_capability("GD32F103RE")
    assert raised.value.code is FlashErrorCode.SECURITY_NOT_SUPPORTED


def test_stm32f103_fails_closed_when_option_algorithm_hash_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "mklink.cmsis_dap.security.discover_builtin_option_algorithm",
        lambda _part: _algorithm(tmp_path, "0" * 64),
    )

    capability = security_capability("STM32F103RE")

    assert capability.supported is False
    assert "白名单" in capability.reason


def test_stm32f413_exact_order_code_uses_only_pinned_option_algorithm(monkeypatch, tmp_path):
    algorithm = BuiltinOptionAlgorithm(
        target_part="STM32F413xG",
        file_name="STM32F413xx_423xx_OPT.FLM",
        path=tmp_path / "STM32F413xx_423xx_OPT.FLM",
        sha256=STM32F4_OPTION_FLM_SHA256,
        ram_start=0x20000000,
        ram_size=0x50000,
    )
    monkeypatch.setattr(
        "mklink.cmsis_dap.security.discover_builtin_option_algorithm",
        lambda part: algorithm if part == "STM32F413xG" else None,
    )

    capability = security_capability("STM32F413VGHx")

    assert capability.supported is True
    assert capability.family == "stm32f413-rdp1"
    assert capability.option_address == 0x1FFFC000
    assert capability.option_size == 4


def test_stm32g474_512k_order_codes_use_only_pinned_option_algorithm(monkeypatch, tmp_path):
    algorithm = BuiltinOptionAlgorithm(
        target_part="STM32G474xE",
        file_name="STM32G4xx_DB_OPT.FLM",
        path=tmp_path / "STM32G4xx_DB_OPT.FLM",
        sha256=STM32G4_OPTION_FLM_SHA256,
        ram_start=0x20000000,
        ram_size=0x20000,
    )
    monkeypatch.setattr(
        "mklink.cmsis_dap.security.discover_builtin_option_algorithm",
        lambda part: algorithm if part == "STM32G474xE" else None,
    )

    capability = security_capability("STM32G474RETx")

    assert capability.supported is True
    assert capability.family == "stm32g474-rdp1"
    assert capability.option_address == 0x1FFF7800
    assert capability.option_size == 84
    assert security_capability("STM32G474xE").supported is True
    assert security_capability("STM32G474RCTx").supported is False


def test_stm32g474_fails_closed_when_option_algorithm_hash_changes(monkeypatch, tmp_path):
    algorithm = BuiltinOptionAlgorithm(
        target_part="STM32G474xE",
        file_name="STM32G4xx_DB_OPT.FLM",
        path=tmp_path / "STM32G4xx_DB_OPT.FLM",
        sha256="0" * 64,
        ram_start=0x20000000,
        ram_size=0x20000,
    )
    monkeypatch.setattr(
        "mklink.cmsis_dap.security.discover_builtin_option_algorithm",
        lambda _part: algorithm,
    )

    capability = security_capability("STM32G474RETx")

    assert capability.supported is False
    assert "白名单" in capability.reason
