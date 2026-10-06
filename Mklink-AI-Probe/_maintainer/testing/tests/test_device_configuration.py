import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mklink.device_configuration import (
    describe_configuration,
    read_configuration,
)
from test_runtime_probe import probe


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
        return {0xF3050500: 0x11705142, 0xF3050510: 0x12345678, 0xF3050110: 0xABCD9876}.get(
            address, 0
        ).to_bytes(4, "little")


def test_hpm_reads_only_public_words_and_keeps_shadow_distinct():
    dev = HpmDevice()
    result = read_configuration(dev, "HPM5301xEGx")
    assert dev.reads == [(0xF3050500, 4)] + [
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


@pytest.mark.parametrize("blocked_value", [0, 0x20150407, 0xFFFFFFFF])
def test_hpm_cached_name_does_not_bypass_live_chip_identity(blocked_value):
    dev = HpmDevice()
    def protected_read(address, size):
        dev.reads.append((address, size))
        return blocked_value.to_bytes(4, "little")
    dev.read_memory = protected_read
    with pytest.raises(ValueError, match="debug access may be protected"):
        read_configuration(dev, "HPM5301")
    assert dev.reads == [(0xF3050500, 4)]


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


@pytest.mark.parametrize("model", ["V2", "V3"])
@pytest.mark.parametrize("part", ["HPM5301", "HPM5301XEGX"])
def test_hpm_configuration_rejects_unsupported_probe_before_io(model, part):
    description = describe_configuration(part, model)
    assert not description["supported"] and not description["read_supported"]
    device = HpmDevice()
    with pytest.raises(ValueError, match="HPM targets require V4"):
        read_configuration(device, part, model)
    assert device.reads == []


def test_legacy_mcp_uses_the_same_snapshot(monkeypatch):
    import fastmcp
    from mklink import mcp_server

    dev = HpmDevice()

    expected = read_configuration(dev, 'HPM5301')
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
            assert result.data["fields"] == expected["fields"]

    asyncio.run(exchange())


def test_shared_configuration_reuses_route_identity_and_resource_admission(probe):
    from mklink._types import DeviceState
    client, control, state, _, _, managers, _ = probe
    device = HpmDevice()
    device.port = 'COM9'
    device.state = DeviceState.READY
    device.axf_status = {'loaded': False}
    state['device'] = device
    session = client.post('/_runtime/attach', json={}).json()['session_id']
    def read(part='HPM5301', model='V4'):
        return client.post('/_runtime/call', json={'session_id': session, 'capability': 'read_configuration',
                           'arguments': {'part_number': part, 'model': model}})
    managers['rtt'].running = True
    assert read().status_code == 409
    assert device.reads == [] and managers['rtt'].running
    managers['rtt'].running = False
    assert read(model='V1').status_code == 422 and device.reads == []
    device.idcode = 0
    assert read().status_code == 422 and device.reads == []
    device.idcode = 0x1000563D
    response = read()
    assert response.status_code == 200, response.text
    assert response.json()['fields'] == read_configuration(HpmDevice(), 'HPM5301')['fields']
    assert len(device.reads) == 9 and not state['resource_manager'].get_status()
    device.reads.clear()
    def failed_read(address, size):
        device.reads.append((address, size))
        raise TimeoutError('unknown read result')
    device.read_memory = failed_read
    response = read()
    assert response.status_code == 422 and len(device.reads) == 1
    assert not control.operation_lock.locked() and not state['resource_manager'].get_status()


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
