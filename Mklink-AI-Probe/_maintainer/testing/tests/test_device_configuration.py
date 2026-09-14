import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mklink.device_configuration import (
    describe_configuration,
    read_configuration,
    run_cli,
)


class HpmDevice:
    mcu_name = "HPMicro HPM5301"
    idcode = 0x1000563D
    connected = True

    def __init__(self):
        self.reads = []

    def read_memory(self, address, size):
        self.reads.append((address, size))
        assert size == 4
        # Public USB configuration: different fuse and shadow values.
        return {0xF3050510: 0x12345678, 0xF3050110: 0xABCD9876}.get(
            address, 0
        ).to_bytes(4, "little")


def test_hpm_reads_only_public_words_and_keeps_shadow_distinct():
    dev = HpmDevice()
    result = read_configuration(dev, "HPM5301xEGx")
    assert dev.reads == [
        (base + index * 4, 4)
        for index in (0, 1, 3, 68)
        for base in (0xF3050400, 0xF3050000)
    ]
    fields = {field["id"]: field for field in result["fields"]}
    assert fields["USB_VID"]["current"] == 0x1234
    assert fields["USB_VID"]["shadow"] == 0xABCD
    assert fields["USB_PID"]["current"] == 0x5678
    assert result["snapshot_only"] and result["read_at"]
    assert all(not field["writable"] for field in fields.values())
    assert all(
        field["current"] is None
        for field in describe_configuration("HPM5301")["fields"]
    )


@pytest.mark.parametrize(
    "name,code", [("HPMicro HPM6200", 0x1000563D), ("HPMicro HPM5301", 0)]
)
def test_hpm_identity_checked_before_any_memory_access(name, code):
    dev = HpmDevice()
    dev.mcu_name, dev.idcode = name, code
    with pytest.raises(ValueError, match="does not match"):
        read_configuration(dev, "HPM5301")
    assert not dev.reads


def test_short_read_and_unknown_chip_are_not_zero_snapshots():
    dev = HpmDevice()
    dev.read_memory = lambda *_: b"\x00\x00"
    with pytest.raises(RuntimeError, match="incomplete"):
        read_configuration(dev, "HPM5301")
    for chip in ("HPM6200", "HPM5301INVALID", "UNSUPPORTED"):
        assert not describe_configuration(chip)["read_supported"]
    with pytest.raises(ValueError):
        describe_configuration("HPM5301", "V1")


@pytest.mark.parametrize(
    "part,family",
    [
        ("STM32F103C8", "stm32f103-rdp1"),
        ("GD32F303VET6", "gd32f303xe-spc"),
        ("STM32G474RET6", "stm32g474-rdp1"),
        ("PY32F030K28T6", "py32f030x8-rdp1"),
    ],
)
def test_arm_uses_existing_recipe_identity_and_status(part, family, monkeypatch):
    # Asset availability is separate from register decoding; use production recipes.
    monkeypatch.setattr(
        "mklink.offline_security.offline_security_capability",
        lambda *_: {"supported": True, "family": family},
    )
    from mklink.device_configuration import _profile

    cfg = _profile(part, "V4")[1]
    memory = {
        int(cfg["id_address"], 0): int(cfg["id_expected"], 0),
        int(cfg["status_address"], 0): 0,
    }
    if not int(cfg["status_protected_mask"], 0):
        memory[int(cfg["shadow_word0_address"], 0)] = 0xAA
    if part.startswith('STM32F103'):
        from mklink.stm32f1_options import geometry
        memory[0x1FFFF7E0] = geometry(part).flash_kib
        memory[0x40022020] = 0xFFFFFFFF
    dev = SimpleNamespace(mcu_name=part, read_memory=lambda a, n:
        bytes.fromhex('a55aff00ff00ff00ff00ff00ff00ff00') if a == 0x1FFFF800
        else memory[a].to_bytes(4, 'little'))
    assert read_configuration(dev, part)["fields"][0]["current"] == "unprotected"
    if int(cfg["status_protected_mask"], 0):
        memory[int(cfg["status_address"], 0)] = int(cfg["status_protected_mask"], 0)
    else:
        memory[int(cfg["shadow_word0_address"], 0)] = 0xBB
    assert read_configuration(dev, part)["fields"][0]["current"] == "protected"
    if not int(cfg["status_protected_mask"], 0):
        memory[int(cfg["shadow_word0_address"], 0)] = 0xCC
        assert read_configuration(dev, part)["fields"][0]["current"] == "permanent"
    if int(cfg["status_error_mask"], 0):
        memory[int(cfg["status_address"], 0)] = int(cfg["status_error_mask"], 0)
        with pytest.raises(RuntimeError, match="status reports an error"):
            read_configuration(dev, part)
    memory[int(cfg["id_address"], 0)] = 0
    with pytest.raises(ValueError, match="device ID"):
        read_configuration(dev, part)


def test_description_preserves_probe_model_restrictions():
    # Existing G474/PY32 offline recipes are V3-only; do not advertise V4 writes.
    for part in ("STM32G474RET6", "PY32F030K28T6"):
        result = describe_configuration(part, "V4")
        assert not result["supported"]
        assert not result["security"]["lock_supported"]


def test_cli_and_mcp_share_the_same_snapshot(monkeypatch, capsys):
    import fastmcp
    from mklink import mcp_server

    dev = HpmDevice()

    class Connection:
        def __enter__(self):
            return dev

        def __exit__(self, *_):
            pass

    monkeypatch.setattr("mklink.device.connect", lambda **_: Connection())
    run_cli(
        SimpleNamespace(
            action="read", chip="HPM5301", model="V4", port=None, project_root="."
        )
    )
    cli = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(mcp_server, "_connected_device", lambda: dev)
    server = fastmcp.FastMCP("configuration-contract")
    mcp_server._register_variable_tools(server)

    async def exchange():
        async with fastmcp.Client(server) as client:
            description = await client.call_tool(
                "configuration_description", {"part_number": "HPM5301"}
            )
            result = await client.call_tool(
                "read_configuration", {"part_number": "HPM5301"}
            )
            assert description.data["read_supported"]
            assert result.data["fields"] == cli["fields"]

    asyncio.run(exchange())


def test_web_description_offline_and_read_requires_connection(tmp_path):
    from mklink.remote.api import create_app

    app = create_app(project_root=str(tmp_path))
    with TestClient(app) as client:
        assert client.get(
            "/api/device/configuration", params={"part_number": "HPM5301"}
        ).json()["read_supported"]
        assert (
            client.post(
                "/api/device/configuration/read", json={"part_number": "HPM5301"}
            ).status_code
            == 400
        )
        assert (
            client.get(
                "/api/device/configuration",
                params={"part_number": "HPM5301", "model": "V1"},
            ).status_code
            == 422
        )
        dev = HpmDevice()
        app.state.mklink_state["device"] = dev
        response = client.post(
            "/api/device/configuration/read", json={"part_number": "HPM5301"}
        )
        assert response.status_code == 200, response.text
        assert (
            response.json()["fields"]
            == read_configuration(HpmDevice(), "HPM5301")["fields"]
        )
        app.state.mklink_state["device"] = None
