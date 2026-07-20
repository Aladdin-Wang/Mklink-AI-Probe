import pytest

from mklink.elf_backend import ElfParseError, ElfSection
from mklink.elf_builtin import BuiltinElfBackend


class FakeSymbol:
    def __init__(
        self,
        name,
        *,
        kind,
        address,
        size,
        section=1,
        binding="STB_GLOBAL",
        visibility="STV_DEFAULT",
    ):
        self.name = name
        self.values = {
            "st_info": {"type": kind, "bind": binding},
            "st_other": {"visibility": visibility},
            "st_value": address,
            "st_size": size,
            "st_shndx": section,
        }

    def __getitem__(self, key):
        return self.values[key]


class FakeSymbolTable:
    def __init__(self, symbols):
        self._symbols = symbols

    def iter_symbols(self):
        return iter(self._symbols)


class FakeSection:
    def __init__(self, name, *, address, size, flags, section_type):
        self.name = name
        self.values = {
            "sh_addr": address,
            "sh_size": size,
            "sh_flags": flags,
            "sh_type": section_type,
        }

    def __getitem__(self, key):
        return self.values[key]


class FakeElf:
    def __init__(self, symbols=(), sections=()):
        self._symtab = FakeSymbolTable(symbols)
        self._sections = list(sections)

    def get_section_by_name(self, name):
        return self._symtab if name == ".symtab" else None

    def iter_sections(self):
        return iter(self._sections)


def make_backend(tmp_path, elf):
    source = tmp_path / "firmware.axf"
    source.write_bytes(b"fixture")
    return BuiltinElfBackend(elf_factory=lambda _stream: elf), str(source)


def test_builtin_symbols_normalize_defined_objects_and_functions(tmp_path):
    elf = FakeElf(
        symbols=[
            FakeSymbol(
                "g_counter", kind="STT_OBJECT", address=0x20000010, size=4
            ),
            FakeSymbol(
                "HardFault_Handler",
                kind="STT_FUNC",
                address=0x08000101,
                size=12,
            ),
            FakeSymbol(
                "missing", kind="STT_OBJECT", address=0, size=4, section="SHN_UNDEF"
            ),
            FakeSymbol("source.c", kind="STT_FILE", address=0, size=0),
        ]
    )
    backend, source = make_backend(tmp_path, elf)

    symbols = backend.symbols(source)

    assert [(item.name, item.kind, item.address, item.size) for item in symbols] == [
        ("g_counter", "object", 0x20000010, 4),
        ("HardFault_Handler", "function", 0x08000101, 12),
    ]
    assert symbols[0].binding == "global"
    assert symbols[0].visibility == "default"


def test_builtin_symbols_keep_static_and_unicode_names(tmp_path):
    elf = FakeElf(
        symbols=[
            FakeSymbol(
                "static_value",
                kind="STT_OBJECT",
                address=0x20000020,
                size=2,
                binding="STB_LOCAL",
            ),
            FakeSymbol(
                "sensor_\u6e29\u5ea6",
                kind="STT_OBJECT",
                address=0x20000024,
                size=4,
            ),
        ]
    )
    backend, source = make_backend(tmp_path, elf)

    symbols = backend.symbols(source)

    assert [item.name for item in symbols] == ["static_value", "sensor_\u6e29\u5ea6"]
    assert symbols[0].binding == "local"


def test_builtin_sections_preserve_header_fields(tmp_path):
    elf = FakeElf(
        sections=[
            FakeSection(
                ".text",
                address=0x08000000,
                size=0x120,
                flags=0x6,
                section_type="SHT_PROGBITS",
            ),
            FakeSection(
                ".bss",
                address=0x20000000,
                size=0x40,
                flags=0x3,
                section_type="SHT_NOBITS",
            ),
            FakeSection(
                "", address=0, size=0, flags=0, section_type="SHT_NULL"
            ),
        ]
    )
    backend, source = make_backend(tmp_path, elf)

    sections = backend.sections(source)

    assert sections == [
        ElfSection(".text", 0x08000000, 0x120, 0x6, "SHT_PROGBITS"),
        ElfSection(".bss", 0x20000000, 0x40, 0x3, "SHT_NOBITS"),
    ]


def test_builtin_invalid_input_has_clear_error(tmp_path):
    source = tmp_path / "not-elf.axf"
    source.write_bytes(b"not an elf")

    with pytest.raises(ElfParseError, match="Invalid ELF/AXF"):
        BuiltinElfBackend().symbols(str(source))
