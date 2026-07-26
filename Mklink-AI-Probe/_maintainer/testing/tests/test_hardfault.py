import struct
from types import SimpleNamespace

from mklink import mcp_server
from mklink.device import Device
from mklink.elf_backend import ElfSection, ElfSymbol
from mklink.hardfault import (
    addr2line,
    build_call_stack,
    find_exception_stack,
    format_hardfault_report,
    parse_exception_stack_frame,
)


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


def test_find_exception_stack_recovers_rt_thread_saved_psp_frame():
    psp = 0x20001000
    exc_return = 0xFFFFFFFD
    frame_values = [1, 2, 3, 4, 12, 0x08000211, 0x08000120, 0x21000000]
    words = [exc_return, *range(4, 12), *frame_values, 0x08000331]
    stack_data = struct.pack(f"<{len(words)}I", *words)

    located = find_exception_stack(
        {"lr": 0x08001001, "msp": 0x20002000, "psp": psp},
        {"psp": (psp, stack_data)},
        [(0x08000000, 0x08010000)],
    )

    assert located is not None
    assert located["pointer"] == "psp"
    assert located["frame_address"] == psp + 9 * 4
    assert located["exc_return"] == exc_return
    assert located["frame"]["pc"] == 0x08000120


def test_build_call_stack_resolves_fault_caller_and_bounded_stack_scan():
    frame_address = 0x20001024
    frame = {
        "r0": 0, "r1": 0, "r2": 0, "r3": 0, "r12": 0,
        "lr": 0x08000211, "pc": 0x08000120, "xpsr": 0x21000000,
    }
    prefix = bytes(frame_address + 32 - 0x20001000)
    stack_data = prefix + struct.pack("<4I", 0xDEADBEEF, 0x08000301, 0x08000301, 0)
    symbols = [
        ElfSymbol("fault_here", 0x08000101, 0x40, "function", "global", "default", 1),
        ElfSymbol("caller", 0x08000201, 0x40, "function", "global", "default", 1),
        ElfSymbol("thread_entry", 0x08000301, 0x60, "function", "global", "default", 1),
    ]

    call_stack = build_call_stack(
        frame,
        frame_address=frame_address,
        stack_base=0x20001000,
        stack_data=stack_data,
        executable_ranges=[(0x08000000, 0x08010000)],
        symbols=symbols,
    )

    assert [item["function"] for item in call_stack] == [
        "fault_here", "caller", "thread_entry",
    ]
    assert [item["source"] for item in call_stack] == [
        "exception_pc", "exception_lr", "stack_scan",
    ]
    assert call_stack[2]["stack_address"] == frame_address + 36


def test_device_hardfault_reads_exception_psp_instead_of_dcrdr(monkeypatch):
    psp = 0x20001000
    frame_values = [1, 2, 3, 4, 12, 0x08000211, 0x08000120, 0x21000000]
    words = [0xFFFFFFFD, *range(4, 12), *frame_values, 0x08000331]
    stack_data = struct.pack(f"<{len(words)}I", *words).ljust(512, b"\x00")
    reads = []
    device = Device(axf="firmware.axf")
    device._bridge = object()
    device._connected = True

    monkeypatch.setattr(device, "halt", lambda: None)
    monkeypatch.setattr(device, "read_core_registers", lambda: {
        "lr": 0x08001001, "msp": 0x20002000, "psp": psp,
    })

    def read_memory(address, size):
        reads.append((address, size))
        if address == psp:
            return stack_data
        raise RuntimeError("unavailable stack")

    monkeypatch.setattr(device, "read_memory", read_memory)
    monkeypatch.setattr("mklink.elf_backend.list_elf_sections", lambda *_args, **_kwargs: [
        ElfSection("ER_IROM1", 0x08000000, 0x10000, 0x6, "SHT_PROGBITS"),
    ])
    monkeypatch.setattr("mklink.elf_backend.list_elf_symbols", lambda *_args, **_kwargs: [
        ElfSymbol("fault_here", 0x08000101, 0x40, "function", "global", "default", 1),
        ElfSymbol("caller", 0x08000201, 0x40, "function", "global", "default", 1),
        ElfSymbol("thread_entry", 0x08000301, 0x60, "function", "global", "default", 1),
    ])
    monkeypatch.setattr("mklink.elf_backend.lookup_source_locations", lambda _source, addresses, **_kwargs: {
        address: f"fault.c:{index + 10}" for index, address in enumerate(addresses)
    })

    report = device.decode_hardfault({"SCB.CFSR": 1 << 16, "SCB.HFSR": 1 << 30})

    assert report is not None
    assert report.fault_function == "fault_here"
    assert report.exception_stack["pointer"] == "psp"
    assert [item["function"] for item in report.call_stack[:3]] == [
        "fault_here", "caller", "thread_entry",
    ]
    assert (0xE000EDF8, 32) not in reads
    assert (psp, 512) in reads


def test_mcp_hardfault_exposes_fault_function_and_call_stack(monkeypatch):
    tools = {}

    class FakeMcp:
        def tool(self):
            def register(function):
                tools[function.__name__] = function
                return function
            return register

    report = SimpleNamespace(
        cfsr=1 << 16,
        hfsr=1 << 30,
        cfsr_flags=["UNDEFINSTR: UsageFault: undefined instruction"],
        hfsr_flags=["FORCED: Configurable fault escalated to HardFault"],
        stack_frame={"pc": 0x08000120, "lr": 0x08000211},
        source_locations={0x08000120: "applications/main.c:471"},
        summary="undefined instruction",
        fault_function="mklink_hardfault_leaf",
        fault_location="applications/main.c:471",
        exception_stack={"pointer": "psp", "frame_address": 0x20001024},
        call_stack=[
            {
                "index": 0,
                "address": 0x08000120,
                "function": "mklink_hardfault_leaf",
                "location": "applications/main.c:471",
                "source": "exception_pc",
            },
            {
                "index": 1,
                "address": 0x08000211,
                "function": "mklink_hardfault_caller",
                "location": "applications/main.c:476",
                "source": "exception_lr",
            },
        ],
        core_registers={"pc": 0x08001000, "psp": 0x20001000},
    )
    fake_device = SimpleNamespace(decode_hardfault=lambda: report)
    monkeypatch.setattr(mcp_server, "_connected_device", lambda: fake_device)
    mcp_server._register_hardfault_tools(FakeMcp())

    result = tools["decode_hardfault"]()

    assert result["fault_function"] == "mklink_hardfault_leaf"
    assert result["fault_location"] == "applications/main.c:471"
    assert result["exception_stack"]["pointer"] == "psp"
    assert [frame["function"] for frame in result["call_stack"]] == [
        "mklink_hardfault_leaf", "mklink_hardfault_caller",
    ]
    assert result["core_registers"]["psp"] == 0x20001000
