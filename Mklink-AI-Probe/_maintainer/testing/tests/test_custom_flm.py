from pathlib import Path

import pytest

from mklink.cmsis_dap.custom_flm import CustomFlmCatalog
from mklink.cmsis_dap.errors import FlashError, FlashErrorCode
from mklink.cmsis_dap.models import MemoryRegion


class ParsedFlm:
    flash_start = 0x90000000
    flash_size = 0x800000
    page_size = 0x1000
    sector_sizes = ((0, 0x1000),)


def test_custom_flm_is_content_addressed_persistent_and_target_scoped(tmp_path: Path):
    source = tmp_path / "user.FLM"
    source.write_bytes(b"custom-algorithm")
    catalog = CustomFlmCatalog(tmp_path / "cache", parser=lambda _path: ParsedFlm())

    record = catalog.add(
        source,
        "STM32H7B0_QSPI.FLM",
        "STM32H7B0VBTx",
        (MemoryRegion("internal", 0x08000000, 0x20000, True, True, 0x20000),),
    )

    assert record.target_part == "STM32H7B0VBTx"
    assert record.file_name == "STM32H7B0_QSPI.FLM"
    assert record.flash_start == 0x90000000
    assert record.flash_size == 0x800000
    assert record.page_size == 0x1000
    assert record.sector_sizes == ((0, 0x1000),)
    assert Path(record.file_path).is_file()
    assert Path(record.file_path).parent == (tmp_path / "cache" / "custom-flm")

    reloaded = CustomFlmCatalog(tmp_path / "cache", parser=lambda _path: ParsedFlm())
    assert reloaded.list("stm32h7b0vbtx") == (record,)
    assert reloaded.regions("STM32H7B0VBTx") == (
        MemoryRegion(
            "custom-flm-{}".format(record.algorithm_id[:12]),
            0x90000000,
            0x800000,
            True,
            True,
            0x1000,
        ),
    )


def test_custom_flm_rejects_overlap_with_pack_flash(tmp_path: Path):
    source = tmp_path / "user.flm"
    source.write_bytes(b"custom-algorithm")
    catalog = CustomFlmCatalog(tmp_path / "cache", parser=lambda _path: ParsedFlm())

    with pytest.raises(FlashError) as raised:
        catalog.add(
            source,
            source.name,
            "STM32H7B0VBTx",
            (MemoryRegion("existing", 0x90000000, 0x1000, True, True, 0x1000),),
        )

    assert raised.value.code is FlashErrorCode.TARGET_NOT_SUPPORTED
    assert catalog.list("STM32H7B0VBTx") == ()


def test_custom_flm_maps_parser_failures_to_a_safe_format_error(tmp_path: Path):
    source = tmp_path / "broken.flm"
    source.write_bytes(b"not-an-elf")
    catalog = CustomFlmCatalog(
        tmp_path / "cache",
        parser=lambda _path: (_ for _ in ()).throw(RuntimeError("private parser detail")),
    )

    with pytest.raises(FlashError) as raised:
        catalog.add(source, source.name, "Target", ())

    assert raised.value.code is FlashErrorCode.FILE_FORMAT_ERROR
    assert "private parser detail" not in raised.value.message


def test_custom_flm_remove_deletes_unreferenced_payload(tmp_path: Path):
    source = tmp_path / "user.flm"
    source.write_bytes(b"custom-algorithm")
    catalog = CustomFlmCatalog(tmp_path / "cache", parser=lambda _path: ParsedFlm())
    record = catalog.add(source, source.name, "Target", ())

    catalog.remove("Target", record.algorithm_id)

    assert catalog.list("Target") == ()
    assert not Path(record.file_path).exists()


def test_custom_flm_detects_a_tampered_persistent_payload(tmp_path: Path):
    source = tmp_path / "user.flm"
    source.write_bytes(b"custom-algorithm")
    catalog = CustomFlmCatalog(tmp_path / "cache", parser=lambda _path: ParsedFlm())
    record = catalog.add(source, source.name, "Target", ())
    Path(record.file_path).write_bytes(b"tampered")

    with pytest.raises(FlashError) as raised:
        catalog.list("Target")

    assert raised.value.code is FlashErrorCode.PACK_INTEGRITY_ERROR
