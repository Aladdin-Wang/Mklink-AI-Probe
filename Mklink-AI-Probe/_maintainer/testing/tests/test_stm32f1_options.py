import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from mklink.stm32f1_options import OptionPlan, fields, script_block, validate_changes
from mklink.offline_download import (
    parse_offline_config,
    generate_offline_script,
    deploy_offline_bundle,
    OfflineDownloadError,
)


ORIGINAL = bytes.fromhex("a55aff00ff00ff00ff00ff00ff00ff00")


class Target:
    def __init__(self):
        self.raw = ORIGINAL
        self.writes = []
        self.short = False
        self.reset_works = True
        self.corrupt_write = False
        self.words = {0xE0042000: 0x10036414, 0x1FFFF7E0: 0xFFFF0200}
        self.set_reset()
        self.writes.clear()

    def cpu_halt(self):
        return 0

    def read_flash(self, address, size, path):
        assert size in (4, 8, 16)
        data = (
            self.raw
            if address == 0x1FFFF800
            else b"".join(
                self.words[address + i].to_bytes(4, "little") for i in range(0, size, 4)
            )
        )
        Path(path).write_bytes(data[:-1] if self.short else data)

    def set_reset(self):
        self.writes.append("reset")
        if self.reset_works:
            self.words[0x4002201C] = (
                ((self.raw[2] & 7) << 2) | (self.raw[4] << 10) | (self.raw[6] << 18)
            )
            self.words[0x40022020] = sum(
                self.raw[8 + i * 2] << (8 * i) for i in range(4)
            )

    def flm(self, path, address, ram):
        assert (path, address, ram) == ("FLM/STM32F10x_OPT.FLM", 0x1FFFF800, 0x20000000)
        self.writes.append("load")
        return 0

    def hex(self, path):
        lines = Path(path).read_text().splitlines()
        assert lines[0] == ":020000041FFFDC" and lines[1].startswith(":10F80000")
        assert lines[2] == lines[1] and lines[3] == ":00000001FF"
        for line in lines:
            assert sum(bytes.fromhex(line[1:])) & 255 == 0
        data = bytes.fromhex(lines[1][9:-2])
        assert len(data) == 16 and data[:2] == ORIGINAL[:2]
        self.writes.append("erase-program")
        self.raw = data if not self.corrupt_write else ORIGINAL
        return 0


def run_script(tmp_path, monkeypatch, target, changes):
    monkeypatch.chdir(tmp_path)
    Path("CFG/STM32F103xE").mkdir(parents=True, exist_ok=True)
    plan = OptionPlan("STM32F103xE", changes, Path("unused"), "")
    scope = dict(cmd=target, load=target, time=SimpleNamespace(sleep_ms=lambda _: None))
    exec("\n".join(script_block(plan, True, "")), scope)
    return scope["option_rc"]


def test_inline_transaction_does_not_cache_functions():
    import ast

    plan = OptionPlan("STM32F103xE", {"DATA0": 1}, Path("unused"), "")
    block = "\n".join(script_block(plan, True, ""))
    tree = ast.parse(block)
    assert not any(
        isinstance(
            node, (ast.FunctionDef, ast.ClassDef, ast.Return, ast.Break, ast.Continue)
        )
        for node in ast.walk(tree)
    )
    assert "def " not in block and "class " not in block


@pytest.mark.parametrize(
    "fault,expected", [("identity", -202), ("firmware", -212), ("none", 0)]
)
def test_combined_preflight_precedes_firmware_and_failure_blocks_options(
    tmp_path, monkeypatch, fault, expected
):
    monkeypatch.chdir(tmp_path)
    Path("CFG/STM32F103xE").mkdir(parents=True)
    target = Target()
    if fault == "identity":
        target.words[0xE0042000] = 0x410
    calls = []

    def program_firmware():
        calls.append("firmware")
        assert not target.writes
        return -1 if fault == "firmware" else 0

    plan = OptionPlan("STM32F103xE", {"DATA0": 90}, Path("unused"), "")
    lines = ["if program_firmware() != 0:", "    abort = True", "    break"]
    scope = dict(
        cmd=target,
        load=target,
        time=SimpleNamespace(sleep_ms=lambda _: None),
        program_firmware=program_firmware,
    )
    exec("\n".join(script_block(plan, True, "", lines)), scope)
    assert scope["option_rc"] == expected
    assert calls == ([] if fault == "identity" else ["firmware"])
    if expected:
        assert not target.writes
    else:
        assert target.raw[4] == 90


def test_script_preserves_rdp_reserved_bits_and_untouched_fields(tmp_path, monkeypatch):
    target = Target()
    assert (
        run_script(
            tmp_path, monkeypatch, target, {"DATA0": 0x5A, "nRST_STOP": 0, "WRP3": 0x7F}
        )
        == 0
    )
    assert target.raw[:2] == ORIGINAL[:2]
    assert target.raw[2] == 0xFD and target.raw[4] == 0x5A and target.raw[14] == 0x7F
    assert target.raw[6:14] == ORIGINAL[6:14]
    assert all(target.raw[i] ^ target.raw[i + 1] == 255 for i in range(0, 16, 2))
    assert target.writes == ["load", "erase-program", "reset"]


@pytest.mark.parametrize(
    "fault,code",
    [
        ("id", -202),
        ("density", -202),
        ("short", -203),
        ("rdp", -204),
        ("inverse", -205),
        ("shadow", -206),
    ],
)
def test_script_preflight_failures_never_erase(tmp_path, monkeypatch, fault, code):
    target = Target()
    if fault == "id":
        target.words[0xE0042000] = 0x410
    if fault == "density":
        target.words[0x1FFFF7E0] = 0xFFFF0100
    if fault == "short":
        target.short = True
    if fault == "rdp":
        target.raw = b"\x00\xff" + ORIGINAL[2:]
    if fault == "inverse":
        target.raw = ORIGINAL[:5] + b"\x01" + ORIGINAL[6:]
    if fault == "shadow":
        target.words[0x4002201C] ^= 4
    assert run_script(tmp_path, monkeypatch, target, {"DATA0": 1}) == code
    assert not target.writes


def test_script_noop_and_both_verification_failures(tmp_path, monkeypatch):
    target = Target()
    assert run_script(tmp_path, monkeypatch, target, {"DATA0": 255}) == 0
    assert not target.writes
    target.corrupt_write = True
    assert run_script(tmp_path, monkeypatch, target, {"DATA0": 1}) == -210
    assert "reset" not in target.writes
    target = Target()
    target.reset_works = False
    assert run_script(tmp_path, monkeypatch, target, {"DATA0": 1}) == -211


@pytest.mark.parametrize(
    "part,model,changes",
    [
        ("STM32F103xE", "V4", {"RDP": 165}),
        ("HPM5301", "V4", {"DATA0": 1}),
        ("STM32F103xG", "V4", {"DATA0": 1}),
        ("STM32F103xE", "V2", {"DATA0": 1}),
        ("STM32F103xE", "V4", {"DATA0": 256}),
        ("STM32F103xE", "V4", {"DATA0": True}),
        ("STM32F103xE", "V4", {"WDG_SW": 2}),
        ("STM32F103x4", "V4", {"WRP0": 0}),
        ("STM32F103x8", "V4", {"WRP2": 255}),
    ],
)
def test_reject_invalid_or_unsupported_changes(part, model, changes):
    with pytest.raises(ValueError):
        validate_changes(part, model, changes)


def test_descriptions_follow_density_and_parse_hex():
    assert validate_changes("STM32F103xE", "V4", {"DATA0": "0x5a"}) == {"DATA0": 90}
    high = {f["id"]: f for f in fields("STM32F103xE")}
    low = {f["id"]: f for f in fields("STM32F103x4")}
    assert "62–255" in high["WRP3"]["description"]
    assert low["WRP0"]["allowed_mask"] == 15 and not low["WRP1"]["writable"]


def test_cli_mcp_and_web_generate_the_same_guarded_script(capability, tmp_path, capsys):
    import asyncio
    import json
    import fastmcp
    from fastapi.testclient import TestClient
    from mklink import mcp_server
    from mklink.device_configuration import run_cli
    from mklink.remote.api import create_app

    run_cli(
        SimpleNamespace(
            action="generate", chip="STM32F103xE", model="V4", set=["DATA0=0x5A"]
        )
    )
    cli = json.loads(capsys.readouterr().out)
    with TestClient(create_app(project_root=str(tmp_path))) as client:
        web = client.post("/api/offline-download/preview", json=cli["config"])
        assert web.status_code == 200
        assert web.json()["script"] == cli["script"]
    server = fastmcp.FastMCP("option-script-contract")
    mcp_server._register_variable_tools(server)

    async def check():
        async with fastmcp.Client(server) as client:
            result = await client.call_tool(
                "configuration_script",
                {"part_number": "STM32F103xE", "changes": {"DATA0": 90}, "model": "V4"},
            )
            assert result.data["script"] == cli["script"]

    asyncio.run(check())


@pytest.fixture
def capability(tmp_path, monkeypatch):
    path = tmp_path / "option.flm"
    path.write_bytes(b"verified fixture")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "mklink.stm32f1_options.security_capability",
        lambda _: SimpleNamespace(
            supported=True, algorithm_path=path, algorithm_sha256=digest
        ),
    )
    return path


def test_configuration_only_bundle_and_tampered_algorithm(tmp_path, capability):
    payload = dict(
        model="V4",
        target_part="STM32F103xE",
        script_name="options.py",
        option_bytes={"DATA0": 90},
        algorithms=[],
        firmwares=[],
    )
    config = parse_offline_config(payload)
    script = generate_offline_script(config)
    assert (
        "MKLINK_OPTIONS_VERIFIED" in script
        and "cmd.unlock" not in script
        and "cmd.lock" not in script
    )
    assert "set_power" not in script and "erase_sector_flash" not in script
    disk = tmp_path / "disk"
    disk.mkdir()
    result = deploy_offline_bundle(
        config, disk_root=disk, firmware_sources=[], algorithm_sources=[]
    )
    assert "CFG/STM32F103xE/options.json" in [
        p.replace("\\", "/") for p in result["files"]
    ]
    assert (disk / "FLM/STM32F10x_OPT.FLM").read_bytes() == capability.read_bytes()
    capability.write_bytes(b"corrupt")
    with pytest.raises(OfflineDownloadError, match="integrity"):
        deploy_offline_bundle(
            config, disk_root=disk, firmware_sources=[], algorithm_sources=[]
        )


def test_empty_configuration_and_configuration_only_erase_rejected(capability):
    payload = dict(model="V4", target_part="STM32F103xE", algorithms=[], firmwares=[])
    with pytest.raises(OfflineDownloadError):
        parse_offline_config(payload)
    payload.update(option_bytes={"DATA0": 1}, erase_all_before_download=True)
    with pytest.raises(OfflineDownloadError, match="Configuration-only"):
        parse_offline_config(payload)
