import asyncio
import json
from types import SimpleNamespace
import pytest

from mklink.peripheral_watch import (
    load_catalog,
    save_catalog_selection,
    svd_watch_items,
    read_item,
    capture_items,
)
from mklink.superwatch import (
    load_svd_registers,
    resolve_watch_items,
    build_read_blocks,
    compile_frame_decoder,
)
from mklink.device import Device
from test_peripheral_watch import SVD


@pytest.fixture
def selected(tmp_path):
    path = tmp_path / "test.svd"
    path.write_bytes(SVD)
    catalog = load_catalog(str(tmp_path), svd=str(path))
    save_catalog_selection(str(tmp_path), catalog)
    return path, catalog


def test_legacy_cli_adapter_and_shared_catalog_resolve_same_bit(selected):
    path, catalog = selected
    regs = load_svd_registers(str(path))
    names = ["GPIOB.12", "GPIOB.IDR.IDR12", "GPIOB.IDR"]
    items = resolve_watch_items(names, svd_registers=regs)
    assert items == [catalog.resolve(n) for n in names]
    blocks = build_read_blocks(items)
    assert len(blocks) == 1
    assert compile_frame_decoder(items, blocks).decode(
        {"regions": [(0, b"\x00\x10\x00\x00")]}
    ) == [1, 1, 4096]
    for name in ["GPIOB.CLEAR", "GPIOB.WRITE", "0x40010C10"]:
        with pytest.raises(KeyError):
            resolve_watch_items([name], svd_registers=regs)


def test_device_and_cli_decode_field_and_read_exact_register(
    selected, tmp_path, monkeypatch, capsys
):
    from mklink.peripheral_cli import run

    path, catalog = selected
    reads = []
    dev = Device.__new__(Device)
    dev._project_root = str(tmp_path)
    dev._require_connected = lambda: None
    dev.read_memory = lambda address, size: (
        reads.append((address, size)) or b"\x00\x10\x00\x80"
    )
    assert dev.read_register("GPIOB.12") == 1
    assert reads == [(0x40010C08, 4)]

    class Connection:
        def __enter__(self):
            return dev

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("mklink.device.connect", lambda **kwargs: Connection())
    run(
        SimpleNamespace(
            action="read",
            project_root=str(tmp_path),
            target_id=None,
            chip=None,
            svd=None,
            query="",
            port=None,
            names=["GPIOB.12"],
        )
    )
    assert json.loads(capsys.readouterr().out)["values"] == {"GPIOB.12": 1}
    with pytest.raises(KeyError):
        dev.read_register("GPIOB.CLEAR")
    assert len(reads) == 2


def test_mcp_register_tools_use_shared_device(selected, tmp_path, monkeypatch):
    import fastmcp
    from mklink import mcp_server

    dev = Device.__new__(Device)
    dev._project_root = str(tmp_path)
    dev._require_connected = lambda: None
    dev.read_memory = lambda address, size: b"\x00\x10\x00\x00"
    monkeypatch.setattr(mcp_server, "_connected_device", lambda: dev)
    monkeypatch.setattr(
        "mklink.mcp_stream_bridge.publish_mcp_superwatch", lambda *args: None
    )
    server = fastmcp.FastMCP("peripheral-contract")
    mcp_server._register_variable_tools(server)

    async def exchange():
        async with fastmcp.Client(server) as client:
            names = {t.name for t in await client.list_tools()}
            assert {
                "peripheral_targets",
                "select_peripherals",
                "list_peripherals",
                "capture_peripherals",
                "read_register",
            } <= names
            listing = await client.call_tool("list_peripherals", {"query": "GPIOB.12"})
            result = await client.call_tool("read_register", {"name": "GPIOB.12"})
            assert listing.data["items"][0]["bit_offset"] == 12
            assert result.data["value_int"] == 1

    asyncio.run(exchange())


def test_arm_clusters_named_indices_fields_and_qualified_inheritance():
    xml = b"""<device><name>ARM_TEST</name><addressUnitBits>8</addressUnitBits><width>32</width><size>32</size><access>read-only</access><peripherals>
    <peripheral><name>TIM</name><baseAddress>0x40000000</baseAddress><registers>
    <register><name>BASE</name><addressOffset>0</addressOffset><fields><field><name>X</name><bitRange>[23:16]</bitRange></field></fields></register>
    <cluster><name>CH%s</name><dim>2</dim><dimIndex>A-B</dimIndex><dimIncrement>0x40</dimIncrement><addressOffset>0x100</addressOffset>
    <register derivedFrom="TIM.BASE"><name>COUNT</name><addressOffset>4</addressOffset></register>
    <register><name>FLAGS</name><addressOffset>8</addressOffset><fields><field><name>BIT%s</name><dim>2</dim><dimIncrement>4</dimIncrement><bitOffset>0</bitOffset><bitWidth>1</bitWidth></field></fields></register>
    </cluster></registers></peripheral></peripherals></device>"""
    items, skipped = svd_watch_items(xml)
    assert not skipped
    assert items["TIM.CHB.COUNT.X"].address == 0x40000144
    assert items["TIM.CHB.COUNT.X"].metadata["bit_offset"] == 16
    assert items["TIM.CHA.FLAGS.BIT1"].metadata["bit_offset"] == 4


def test_read_side_effects_and_narrow_access_are_not_silently_emulated():
    xml = SVD.replace(
        b"<register><name>ODR</name><addressOffset>12</addressOffset></register>",
        b"""<register><name>BYTE</name><addressOffset>12</addressOffset><size>8</size></register>
    <register><name>HALF</name><addressOffset>14</addressOffset><size>16</size></register>
    <register><name>STATUS</name><addressOffset>28</addressOffset><fields><field><name>READY</name><bitWidth>1</bitWidth><bitOffset>0</bitOffset><description>Cleared when the register is read</description></field></fields></register>
    <register><name>CMD</name><addressOffset>32</addressOffset><fields><field><name>GO</name><bitWidth>1</bitWidth><bitOffset>0</bitOffset><access>write-only</access></field></fields></register>""",
    )
    items, _ = svd_watch_items(xml)
    assert all(
        not any(x in n for x in ("BYTE", "HALF", "STATUS", "CMD")) for n in items
    )


@pytest.mark.parametrize("dim", ["0", "4097"])
def test_expansion_limits(dim):
    xml = SVD.replace(
        b"<name>ODR</name>",
        f"<name>ODR%s</name><dim>{dim}</dim><dimIncrement>4</dimIncrement>".encode(),
    )
    with pytest.raises(ValueError):
        svd_watch_items(xml)


def test_bad_xml_and_ambiguous_selection_fail_closed(tmp_path, monkeypatch):
    from mklink.peripheral_watch import SvdTarget
    from mklink.registers import resolve_register

    with pytest.raises(ValueError):
        svd_watch_items(b"<!DOCTYPE x><device/>")
    monkeypatch.setattr(
        "mklink.peripheral_watch.discover_svd_targets",
        lambda p: [
            SvdTarget("A", "v1", tmp_path / "a.pdsc", "a.svd"),
            SvdTarget("A", "v2", tmp_path / "b.pdsc", "b.svd"),
        ],
    )
    with pytest.raises(ValueError, match="multiple"):
        load_catalog(tmp_path, chip="A")
    for address in ("-1", "0x100000000", "0x40000001"):
        with pytest.raises(ValueError):
            resolve_register(address)


@pytest.mark.parametrize(
    "duration,period", [(0, 0.01), (31, 0.01), (1, 0), (float("nan"), 0.01)]
)
def test_capture_limits_checked_before_io(duration, period):
    with pytest.raises(ValueError):
        capture_items(object(), [], duration=duration, period=period)


def test_empty_saved_selection_and_unsupported_catalog_do_not_fall_back(tmp_path):
    directory = tmp_path / ".mklink"
    directory.mkdir()
    (directory / "peripheral-selection.json").write_text("{}")
    with pytest.raises(ValueError, match="Invalid saved"):
        load_catalog(tmp_path)
    svd = tmp_path / "narrow.svd"
    svd.write_text(
        "<device><name>NARROW</name><addressUnitBits>8</addressUnitBits><width>32</width><size>16</size><peripherals><peripheral><name>P</name><baseAddress>0x40000000</baseAddress><registers><register><name>R</name><addressOffset>0</addressOffset><access>read-only</access></register></registers></peripheral></peripherals></device>"
    )
    with pytest.raises(ValueError, match="no supported"):
        load_catalog(tmp_path, svd=svd)


def test_short_register_read_is_not_zero_padded(selected):
    item = selected[1].resolve("GPIOB.IDR")
    for data in (b"", b"\x01", b"\x00" * 5):
        with pytest.raises(RuntimeError, match="Incomplete"):
            read_item(SimpleNamespace(read_memory=lambda address, size: data), item)


def test_inheritance_cycle_is_rejected():
    xml = b'<device><peripherals><peripheral derivedFrom="B"><name>A</name></peripheral><peripheral derivedFrom="A"><name>B</name></peripheral></peripherals></device>'
    with pytest.raises(ValueError, match="Cyclic"):
        svd_watch_items(xml)


def test_capture_no_samples_still_stops_session(selected, monkeypatch):
    events = []

    class Session:
        stats = {}

        def __init__(self, *args):
            pass

        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")

        def read_frames(self, **kwargs):
            return []

    monkeypatch.setattr("mklink.dump_memory.DumpMemoryStreamSession", Session)
    with pytest.raises(TimeoutError, match="No valid"):
        capture_items(
            SimpleNamespace(_bridge=None),
            [selected[1].resolve("GPIOB.IDR")],
            duration=0.001,
        )
    assert events == ["start", "stop"]


def test_capture_rejects_duplicate_channels_before_io(selected):
    item = selected[1].resolve("GPIOB.IDR")
    with pytest.raises(ValueError, match="unique"):
        capture_items(object(), [item, item])


@pytest.mark.parametrize("address", ["0xE000E010", "0xE000EDF0"])
def test_core_side_effects_are_filtered_even_when_svd_omits_read_action(address):
    xml = SVD.replace(b"0x40010c00", address.encode()).replace(
        b"<addressOffset>8</addressOffset>", b"<addressOffset>0</addressOffset>"
    )
    items, _ = svd_watch_items(xml)
    assert "GPIOB.IDR" not in items


@pytest.mark.parametrize("endian", ["big", "selectable"])
def test_non_little_endian_catalog_rejected(endian):
    xml = SVD.replace(
        b"<version>1</version>",
        f"<version>1</version><cpu><endian>{endian}</endian></cpu>".encode(),
    )
    with pytest.raises(ValueError, match="little-endian"):
        svd_watch_items(xml)
