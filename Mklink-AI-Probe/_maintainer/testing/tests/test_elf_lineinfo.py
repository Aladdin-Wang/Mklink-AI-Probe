from types import SimpleNamespace

from mklink.elf_builtin import _line_ranges_from_program


class FakeAttribute:
    def __init__(self, value):
        self.value = value


class FakeCu:
    def __init__(self, comp_dir=b"C:\\project"):
        self._top = SimpleNamespace(
            attributes={"DW_AT_comp_dir": FakeAttribute(comp_dir)}
        )

    def get_top_DIE(self):
        return self._top


class FakeLineProgram:
    def __init__(self, states):
        self.header = SimpleNamespace(
            include_directory=[b"src"],
            file_entry=[SimpleNamespace(name=b"fault.c", dir_index=1)],
        )
        self._entries = [SimpleNamespace(state=state) for state in states]

    def get_entries(self):
        return iter(self._entries)


def state(address, *, line=1, end=False):
    return SimpleNamespace(address=address, file=1, line=line, end_sequence=end)


def test_line_ranges_close_at_end_sequence_and_do_not_cross_gap():
    program = FakeLineProgram(
        [
            state(0x08000100, line=40),
            state(0x08000104, line=42),
            state(0x08000108, end=True),
            state(0x08000200, line=7),
            state(0x08000204, end=True),
        ]
    )

    ranges = _line_ranges_from_program(FakeCu(), program)

    assert ranges == [
        (0x08000100, 0x08000104, r"C:\project\src\fault.c:40"),
        (0x08000104, 0x08000108, r"C:\project\src\fault.c:42"),
        (0x08000200, 0x08000204, r"C:\project\src\fault.c:7"),
    ]


def test_line_ranges_skip_zero_length_and_unknown_lines():
    program = FakeLineProgram(
        [
            state(0x08000100, line=None),
            state(0x08000100, line=2),
            state(0x08000104, end=True),
        ]
    )

    assert _line_ranges_from_program(FakeCu(), program) == [
        (0x08000100, 0x08000104, r"C:\project\src\fault.c:2")
    ]
