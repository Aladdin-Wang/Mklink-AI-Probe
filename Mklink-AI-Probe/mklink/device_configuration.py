"""Read-only option-byte/OTP inspection shared by CLI, MCP and Web.

Writing remains owned by the existing validated offline security recipes.
No arbitrary addresses or secret OTP words are accepted by this interface.
"""

from __future__ import annotations
import re
from datetime import datetime, timezone


def _profile(part: str, model: str):
    from .offline_security import offline_security_capability, _offline_profile

    part = part.strip().upper()
    if model not in ("V2", "V3", "V4"):
        raise ValueError("Select a V2/V3/V4 probe model")
    if part in ("HPM5301", "HPM5301XEGX"):
        # SDK 1.11.0 HPM5301: hpm_otp_table.h and hpm_soc_ip.h.
        rows = [
            ("HARD_LOCK", "永久锁定位", 0, 0, 32, "锁定位仅解释原始位图，不修改"),
            ("LIFECYCLE_A", "生命周期 A", 1, 0, 4, "原始编码；生命周期转换需专用流程"),
            ("LIFECYCLE_B", "生命周期 B", 1, 28, 4, "原始编码；不推断可逆状态"),
            ("JTAG_DISABLE", "JTAG 禁用位", 1, 16, 1, "永久禁用可能阻断调试访问"),
            ("DEBUG_DISABLE", "调试禁用位", 1, 17, 1, "永久禁用可能阻断调试访问"),
            ("SW_VER", "软件版本字段", 3, 0, 32, "原始版本位图，不解释为普通版本序号"),
            ("USB_VID", "USB VID", 68, 16, 16, "USB 厂商标识"),
            ("USB_PID", "USB PID", 68, 0, 16, "USB 产品标识"),
        ]
        fields = [
            dict(
                id=id,
                label=label,
                word=word,
                bit_offset=shift,
                bit_width=width,
                description=desc,
                writable=False,
                current=None,
                shadow=None,
            )
            for id, label, word, shift, width, desc in rows
        ]
        return dict(
            part_number=part,
            model=model,
            kind="otp",
            supported=True,
            read_supported=True,
            fields=fields,
            source="HPM SDK 1.11.0 / HPM5301",
            reason="公开 OTP 配置只读；熔丝值与影子值分别显示，永久写入暂不支持。",
            security=None,
        ), None
    capability = offline_security_capability(model, part)
    recipe = (
        _offline_profile(part, str(capability["family"]))
        if capability["supported"]
        else None
    )
    if recipe is None:
        return dict(
            part_number=part,
            model=model,
            kind="option_bytes",
            supported=False,
            read_supported=False,
            fields=[],
            source="",
            security=capability,
            reason=capability["reason"] or "该型号尚无配置读取描述",
        ), None
    cfg = dict(
        line.split("=", 1)
        for line in recipe.config_factory("lock", recipe.voltage_mv, part)
        .decode()
        .splitlines()
    )
    field = dict(
        id="RDP",
        label="读保护状态",
        writable=True,
        current=None,
        shadow=None,
        description="通过下方已验证的解锁/加锁选项生成脚本；其他选项字节保持不变。",
    )
    from .stm32f1_options import fields as option_fields

    extra = option_fields(part)
    return dict(
        part_number=part,
        model=model,
        kind="option_bytes",
        supported=True,
        read_supported=True,
        fields=[field, *extra],
        shadow_supported=bool(extra),
        option_write_supported=bool(extra),
        source="Validated offline security recipe",
        security=capability,
        reason=(
            "USER / DATA / 写保护可配置；空白表示保持。读保护使用下方加解锁流程。"
            if extra
            else "目前支持读保护配置；BOR、看门狗、启动及写保护字段尚未开放。"
        ),
    ), cfg


def describe_configuration(part_number: str, model: str = "V4") -> dict:
    return _profile(part_number, model)[0]


def read_configuration(device, part_number: str, model: str = "V4") -> dict:
    result, cfg = _profile(part_number, model)
    if not result["read_supported"]:
        raise ValueError(result["reason"])

    def word(address):
        data = device.read_memory(address, 4)
        if len(data) != 4:
            raise RuntimeError(f"Configuration read incomplete at 0x{address:08X}")
        return int.from_bytes(data, "little")

    name = device.mcu_name.upper()
    if result["kind"] == "otp":
        if not re.search(r"\bHPM5301\b", name) or device.idcode != 0x1000563D:
            raise ValueError("Connected target does not match the HPM5301 description")
        snapshots = {}
        for index in sorted({field["word"] for field in result["fields"]}):
            # Read only the explicit public configuration words, never a bulk OTP dump.
            snapshots[index] = (
                word(0xF3050400 + index * 4),
                word(0xF3050000 + index * 4),
            )
        for field in result["fields"]:
            raw, shadow = snapshots[field["word"]]
            mask = (1 << field["bit_width"]) - 1
            field["current"] = (raw >> field["bit_offset"]) & mask
            field["shadow"] = (shadow >> field["bit_offset"]) & mask
    else:
        if "HPM" in name:
            raise ValueError(
                "Connected HPM target cannot use an ARM option-byte description"
            )
        actual = word(int(cfg["id_address"], 0))
        if actual & int(cfg["id_mask"], 0) != int(cfg["id_expected"], 0):
            raise ValueError(
                "Connected target device ID does not match the selected recipe"
            )
        status = word(int(cfg["status_address"], 0))
        if status & int(cfg["status_error_mask"], 0):
            raise RuntimeError(
                "Option-byte status reports an error; snapshot is not valid"
            )
        protected_mask = int(cfg["status_protected_mask"], 0)
        if protected_mask:
            state = "protected" if status & protected_mask else "unprotected"
        else:
            raw = word(int(cfg["shadow_word0_address"], 0)) & 0xFF
            state = (
                "unprotected"
                if raw == int(cfg["unprotected_value"], 0)
                else "permanent"
                if raw == int(cfg["forbidden_value"], 0)
                else "protected"
            )
        result["fields"][0]["current"] = state
        if result.get("shadow_supported"):
            from .stm32f1_options import geometry

            if word(0x1FFFF7E0) & 0xFFFF != geometry(result["part_number"]).flash_kib:
                raise ValueError(
                    "Connected target Flash density does not match the selected part"
                )
            wrp = word(0x40022020)
            shadow = {
                2: (status >> 2) & 255,
                4: (status >> 10) & 255,
                6: (status >> 18) & 255,
                **{8 + i * 2: (wrp >> (8 * i)) & 255 for i in range(4)},
            }
            raw = None
            if state == "unprotected":
                raw = device.read_memory(0x1FFFF800, 16)
                if len(raw) != 16 or any(
                    raw[i] ^ raw[i + 1] != 255 for i in range(0, 16, 2)
                ):
                    raise RuntimeError(
                        "Option-byte storage length/complement validation failed"
                    )
                result["raw_options_hex"] = raw.hex()
            for field in result["fields"][1:]:
                offset, shift = field["byte_offset"], field["bit_offset"]
                mask = (1 << field["bit_width"]) - 1
                field["current"] = (
                    (raw[offset] >> shift) & mask if raw is not None else None
                )
                field["shadow"] = (shadow[offset] >> shift) & mask
    result["read_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result["snapshot_only"] = True
    return result


def configuration_script(part_number: str, changes: dict, model: str = "V4") -> dict:
    from .offline_download import parse_offline_config, generate_offline_script

    payload = dict(
        model=model,
        target_part=part_number,
        script_name="option-config.py",
        option_bytes=changes,
        algorithms=[],
        firmwares=[],
    )
    config = parse_offline_config(payload)
    return dict(
        config=payload,
        script_name=config.script_name,
        script=generate_offline_script(config),
        algorithm="STM32F10x_OPT.FLM",
    )


def run_cli(args):
    import json

    if args.action == "describe":
        result = describe_configuration(args.chip, args.model)
    elif args.action == "generate":
        changes = {}
        for assignment in args.set:
            name, separator, value = assignment.partition("=")
            if not separator or name in changes:
                raise ValueError("Each --set must be a unique FIELD=VALUE")
            changes[name] = value
        result = configuration_script(args.chip, changes, args.model)
    else:
        from .device import connect

        with connect(port=args.port, project_root=args.project_root) as device:
            result = read_configuration(device, args.chip, args.model)
    print(json.dumps(result, ensure_ascii=False))
