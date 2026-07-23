import struct

from mklink.hardfault import addr2line, format_hardfault_report, parse_exception_stack_frame


def test_addr2line_uses_selected_elf_backend(monkeypatch):
    observed = {}

    def lookup(source, addresses, **kwargs):
        observed.update(source=source, addresses=tuple(addresses), kwargs=kwargs)
        return {0x08000101: "fault.c:42"}

    monkeypatch.setattr("mklink.elf_backend.lookup_source_locations", lookup)

    assert addr2line(
        "firmware.axf",
        0x08000101,
        backend="builtin",
        project_root="project",
    ) == {0x08000101: "fault.c:42"}
    assert observed == {
        "source": "firmware.axf",
        "addresses": (0x08000101,),
        "kwargs": {"backend": "builtin", "project_root": "project"},
    }


def test_hardfault_report_keeps_stack_frame_without_source_locations():
    values = [1, 2, 3, 4, 12, 0x080000F1, 0x08000101, 0x21000000]
    frame = parse_exception_stack_frame(struct.pack("<8I", *values))

    report = format_hardfault_report(
        {"SCB.CFSR": 1 << 25, "SCB.HFSR": 1 << 30},
        frame=frame,
        locations={},
    )

    assert "DIVBYZERO" in report
    assert "FORCED" in report
    assert "PC = 0x08000101" in report


def test_addr2line_failure_is_best_effort(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("bad line table")

    monkeypatch.setattr("mklink.elf_backend.lookup_source_locations", fail)

    assert addr2line("firmware.axf", 0x08000101) == {}
