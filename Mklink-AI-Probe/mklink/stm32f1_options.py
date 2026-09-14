"""STM32F103 non-RDP options and a guarded script for the existing probe ABI.

PM0075: USER bits 0..2, DATA0/1, and active-low WRP; XL-density parts
need a separate description. Never accept a raw RDP value in this path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .offline_security import _stm32f1_geometry
from .cmsis_dap.security import security_capability


def geometry(part: str):
    value = _stm32f1_geometry(part)
    return (
        value
        if part.upper().startswith("STM32F103")
        and value
        and value.device_id in (0x410, 0x412, 0x414)
        else None
    )


def fields(part: str) -> list[dict]:
    geo = geometry(part)
    if geo is None:
        return []
    rows = [
        (
            "WDG_SW",
            "看门狗模式",
            2,
            0,
            1,
            "0：硬件看门狗；1：软件看门狗。硬件模式会在复位后自动启动。",
        ),
        ("nRST_STOP", "STOP 复位行为", 2, 1, 1, "0：进入 STOP 时复位；1：不产生复位。"),
        (
            "nRST_STDBY",
            "STANDBY 复位行为",
            2,
            2,
            1,
            "0：进入 STANDBY 时复位；1：不产生复位。",
        ),
        ("DATA0", "用户数据 0", 4, 0, 8, "独立的 8 位用户数据，可能被应用程序使用。"),
        ("DATA1", "用户数据 1", 6, 0, 8, "独立的 8 位用户数据，可能被应用程序使用。"),
    ]
    result = [
        dict(
            id=name,
            label=label,
            byte_offset=offset,
            bit_offset=shift,
            bit_width=width,
            description=description,
            writable=True,
            current=None,
            shadow=None,
            allowed_mask=(1 << width) - 1,
        )
        for name, label, offset, shift, width, description in rows
    ]
    valid_bits = 32 if geo.flash_kib >= 128 else geo.flash_kib // 4
    for index in range(4):
        mask = ((1 << valid_bits) - 1) >> (8 * index) & 255
        if geo.flash_kib >= 256:
            span = f"页 {index * 16}–{index * 16 + 15}，每位 2 页"
            if index == 3:
                span = f"位 0–6：页 48–61；位 7：页 62–{geo.flash_kib // 2 - 1}"
        else:
            span = (
                f"页 {index * 32}–{min(index * 32 + 31, geo.flash_kib - 1)}，每位 4 页"
            )
        result.append(
            dict(
                id=f"WRP{index}",
                label=f"写保护组 {index}",
                byte_offset=8 + index * 2,
                bit_offset=0,
                bit_width=8,
                allowed_mask=mask,
                writable=bool(mask),
                current=None,
                shadow=None,
                description=f"{span}；0：保护，1：不保护。有效位掩码 0x{mask:02X}。"
                if mask
                else "该容量没有此写保护组。",
            )
        )
    return result


def validate_changes(part: str, model: str, changes: object) -> dict[str, int]:
    if not isinstance(changes, dict):
        raise ValueError("option_bytes must be an object")
    if not changes:
        return {}
    if geometry(part) is None or model not in ("V3", "V4"):
        raise ValueError(
            "USER/DATA/WRP configuration supports STM32F103 non-XL parts on V3/V4 only"
        )
    descriptors = {field["id"]: field for field in fields(part)}
    result = {}
    for name, value in changes.items():
        field = descriptors.get(name)
        if field is None or not field["writable"]:
            raise ValueError(
                f"Unsupported option field: {name}; RDP uses the separate security workflow"
            )
        if isinstance(value, str):
            try:
                value = (
                    int(value, 0) if value.lower().startswith("0x") else int(value, 10)
                )
            except ValueError:
                raise ValueError(f"{name} must be an integer") from None
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value < (1 << field["bit_width"])
        ):
            raise ValueError(f"{name} must fit {field['bit_width']} bits")
        unused = ((1 << field["bit_width"]) - 1) ^ field["allowed_mask"]
        if value & unused != unused:
            raise ValueError(f"{name}: unused write-protection bits must remain 1")
        result[name] = value
    return dict(sorted(result.items()))


@dataclass(frozen=True)
class OptionPlan:
    part_number: str
    changes: dict[str, int]
    algorithm_path: Path
    algorithm_sha256: str

    @property
    def config_dir(self):
        return geometry(self.part_number).bundle_part


def resolve_plan(part: str, model: str, changes: object) -> OptionPlan | None:
    values = validate_changes(part, model, changes)
    if not values:
        return None
    capability = security_capability(part)
    if not capability.supported or capability.algorithm_path is None:
        raise ValueError(
            capability.reason or "Validated STM32F103 option algorithm unavailable"
        )
    path = Path(capability.algorithm_path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != capability.algorithm_sha256:
        raise ValueError("Option algorithm integrity check failed")
    return OptionPlan(part, values, path, capability.algorithm_sha256)


def script_block(
    plan: OptionPlan,
    program: bool,
    indent: str = "    ",
    firmware_lines: list[str] | None = None,
) -> list[str]:
    """Emit one flat transaction, with no cached Pika function definitions.

    Stage 0 validates and merges, stage 1 verifies storage before reset, stage 2
    verifies storage and loaded shadow. Error codes gate writes and end the stage loop without nested jumps.
    A shared read loop bounds parser memory on existing probe firmware.
    """
    geo = geometry(plan.part_number)
    updates = []
    for field in fields(plan.part_number):
        if field["id"] in plan.changes:
            offset, shift = field["byte_offset"], field["bit_offset"]
            mask = field["allowed_mask"] << shift
            updates.append(
                f"                v[{offset // 2}] = (v[{offset // 2}] & {255 ^ mask}) | {plan.changes[field['id']] << shift & mask}"
            )
    code = r"""
option_rc = 0
p = "CFG/@DIR@/read.bin"
desired = b""
stage = 0
while stage < 3 and option_rc == 0:
    if stage == 0:
        if cmd.cpu_halt() != 0:
            option_rc = -201
    addresses = [0x1FFFF800, 0x4002201C]
    sizes = [16, 8]
    if stage == 0:
        addresses = [0x1FFFF800, 0x4002201C, 0xE0042000, 0x1FFFF7E0]
        sizes = [16, 8, 4, 4]
    packets = []
    for j in range(len(sizes)):
        f = open(p, "wb")
        f.close()
        cmd.read_flash(addresses[j], sizes[j], p)
        f = open(p, "rb")
        d = f.read(sizes[j]+1)
        f.close()
        if len(d) != sizes[j]:
            option_rc = -203
        packets.append(d)
    if option_rc == 0:
        b = packets[0]
        s = packets[1]
        if stage > 0 and b != desired:
            option_rc = -209-stage
        if stage == 1 and option_rc == 0:
            cmd.set_reset()
            time.sleep_ms(50)
        if stage != 1:
            obr = s[0] | (s[1]<<8) | (s[2]<<16) | (s[3]<<24)
            wrp = s[4] | (s[5]<<8) | (s[6]<<16) | (s[7]<<24)
            e = ((b[2]&7)<<2) | (b[4]<<10) | (b[6]<<18)
            w = b[8] | (b[10]<<8) | (b[12]<<16) | (b[14]<<24)
            if (obr&3) != 0 or (obr&0x03FFFC1C) != e or wrp != w:
                option_rc = -206
                if stage == 2:
                    option_rc = -211
        if stage == 2 and option_rc == 0:
            print("MKLINK_OPTIONS_VERIFIED")
        if stage == 0:
            d = packets[2]
            identity = d[0] | (d[1]<<8)
            d = packets[3]
            density = d[0] | (d[1]<<8)
            if (identity&4095) != @ID@ or density != @DENSITY@:
                option_rc = -202
            if b[0] != 165 or b[1] != 90:
                option_rc = -204
            v = []
            for j in range(8):
                if (b[j*2] ^ b[j*2+1]) != 255:
                    option_rc = -205
                v.append(b[j*2])
@FIRMWARE@
            if option_rc == 0:
@UPDATES@
                desired = b""
                for value in v:
                    desired = desired + bytes([value, value ^ 255])
                if @PROGRAM@ == 0:
                    stage = 3
                else:
                    if desired == b:
                        print("MKLINK_OPTIONS_UNCHANGED")
                        stage = 3
                    else:
                        if load.flm("FLM/STM32F10x_OPT.FLM", 0x1FFFF800, 0x20000000) != 0:
                            option_rc = -207
                        digits = "0123456789ABCDEF"
                        record = ":10F80000"
                        for j in range(16):
                            value = desired[j]
                            record = record + digits[value >> 4] + digits[value & 15]
                        record = record + "00\n"
                        hex_data = ":020000041FFFDC\n" + record + record + ":00000001FF\n"
                        f = open("CFG/@DIR@/desired.hex", "w")
                        f.write(hex_data)
                        f.close()
                        f = open("CFG/@DIR@/desired.hex", "r")
                        stored = f.read(len(hex_data)+1)
                        f.close()
                        if stored != hex_data:
                            option_rc = -208
                        if option_rc == 0:
                            if load.hex("CFG/@DIR@/desired.hex") != 0:
                                option_rc = -209
    stage += 1
"""
    # Legacy decoder buffers short records without programming. Repeating the
    # identical 16-byte record makes the next address nonsequential and starts
    # its flash manager; no data is ever placed outside the option region.
    # Eight value/complement pairs plus the HEX length/address sum to 0 mod 256.
    firmware = []
    for line in firmware_lines or []:
        if not line.startswith(" "):
            firmware.append("            if option_rc == 0:")
        if line.strip() == "break":
            continue
        firmware.append(
            "                " + line.replace("abort = True", "option_rc = -212")
        )
    code = (
        code.replace("@DIR@", plan.config_dir)
        .replace("@ID@", str(geo.device_id))
        .replace("@DENSITY@", str(geo.flash_kib))
        .replace("@PROGRAM@", str(int(program)))
        .replace("@UPDATES@", "\n".join(updates))
        .replace("@FIRMWARE@", "\n".join(firmware))
    )
    return [indent + line for line in code.strip().splitlines()]
