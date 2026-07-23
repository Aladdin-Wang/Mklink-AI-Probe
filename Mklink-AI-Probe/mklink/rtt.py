"""
MKLink Serial Bridge — RTT 会话管理。

依赖: 无外部依赖
内部依赖: mklink.bridge, mklink._types
"""

from __future__ import annotations

import re
import time

from mklink._types import DeviceState
from mklink.bridge import MKLinkSerialBridge


class RTTSession:
    """RTT 会话管理器。"""

    def __init__(self, bridge: MKLinkSerialBridge, channel: int = 0):
        self._bridge = bridge
        self._channel = channel
        self._running = False

    @staticmethod
    def _find_rtt_addr_from_config(project_root: str = ".") -> str | None:
        """从 .mklink/rtt_config.json 读取已保存的 RTT 地址."""
        import json
        from pathlib import Path

        config_path = Path(project_root) / ".mklink" / "rtt_config.json"
        if not config_path.exists():
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            addr = config.get("rtt_addr", "")
            if addr:
                return addr
        except (json.JSONDecodeError, IOError):
            pass
        return None

    def start(
        self,
        addr: str,
        search_size: int = 1024,
        project_root: str = ".",
        *,
        mode: int = 0,
    ) -> dict:
        """启动 RTT 并解析缓冲区配置。

        注意：先在 READY 状态下发送 RTTView.start 命令（send_command 要求 READY），
        成功后再切换到 RTT_STREAM 流模式。

        如果传入的 addr 为空或 None，会自动从 .mklink/rtt_config.json 读取已保存的地址。

        Args:
            addr: RTT 控制块地址。模式 0 下为搜索起点；模式 1 下必须为精确地址。
            search_size: 探针固件扫描字节数（仅模式 0 生效，模式 1 强制 0）。
            project_root: 项目根目录，用于从 .mklink/rtt_config.json 读取 addr。
            mode: RTT 控制块存储方式
                0 = 动态搜寻（默认，PC 从 MAP/ELF 找 _SEGGER_RTT，探针扫描）
                1 = 静态编译（用户在 C 代码用 SEGGER_RTT_SECTION 宏固定地址，
                              PC 直接用 addr 作为 CB 精确地址，探针 search_size=0）

        返回:
            dict: {
                "control_block_addr": str,
                "up_buffers": [...],
                "down_buffers": [...],
                "warnings": [...],  # 仅模式 1 且回执地址不匹配时存在
                "storage_mode": 0|1,  # 透传
            }
        """
        if mode not in (0, 1):
            raise ValueError(
                f"rtt_storage_mode 必须是 0 或 1，得到 {mode}"
            )

        # 如果未指定地址，尝试从项目配置读取
        if not addr:
            addr = self._find_rtt_addr_from_config(project_root)
            if addr:
                print(f"[OK] 从配置读取 RTT 地址: {addr}")
            else:
                addr = "0x20000000"  # 默认搜索地址
                print(f"[WARN] 未找到 RTT 配置，使用默认搜索地址: {addr}")

        if mode == 1:
            # 静态模式：rtt_addr 必须是 CB 精确地址，search_size 试探为 0
            if not addr:
                raise ValueError("静态模式 (mode=1) 必须指定 rtt_addr")
            actual_search_size = 0
        else:
            # 动态模式：rtt_addr 是搜索起点
            actual_search_size = search_size if search_size else 1024

        # 先在 READY 状态发送命令
        cmd = f"RTTView.start({addr},{actual_search_size},{self._channel})"
        resp = self._bridge.send_command(cmd, timeout=10.0)

        result = self._parse_rtt_startup(resp)
        result["storage_mode"] = mode

        # 静态模式下做回执地址断言：探针回执 != 传入说明它不区分扫描/直接
        if mode == 1 and result.get("control_block_addr"):
            reported = result["control_block_addr"].lower()
            requested = addr.lower()
            if reported != requested:
                warnings = result.setdefault("warnings", [])
                warnings.append(
                    f"探针回执地址 {reported} != 传入 {requested}，"
                    "可能探针固件不区分扫描/直接模式；RTT 流仍按回执地址工作"
                )
                print(
                    f"[WARN] 静态模式回执地址不匹配: 传入={requested}, 探针回执={reported}"
                )

        # 检查是否成功找到 RTT 控制块
        if not result.get("control_block_addr"):
            return result  # 失败时不切换到流模式

        # 命令成功，切换到 RTT_STREAM 流模式
        self._bridge._enter_stream(DeviceState.RTT_STREAM)
        self._running = True
        return result

    def read_output(self, duration: float = 10.0, callback=None) -> str:
        """读取 UpBuffer 输出 (MCU -> PC)。"""
        return self._bridge.read_stream(duration=duration)

    def read_output_bytes(self, duration: float = 10.0) -> bytes:
        """读取 UpBuffer 原始字节，供可选文本编码的客户端解码。"""
        return self._bridge.read_stream_bytes(duration=duration)

    def send_input(self, data: bytes) -> bool:
        """通过 DownBuffer 发送数据到 MCU (PC -> MCU)。

        RTT 启动后直接通过 CDC 串口发送，不需要 PikaScript 命令。
        """
        self._bridge._write_raw(data)
        return True

    def reset_failed_start(self) -> str:
        """Synchronize the probe after a start command returned no RTT address."""
        return self._bridge.send_command("RTTView.stop()", timeout=5.0)

    def stop(self) -> str:
        """停止 RTT 会话。"""
        # 先恢复 READY 状态以便 send_command 工作
        # Do not wait for a command prompt here: at high RTT rates the prompt
        # is not reliably observable, and send_command() marks the bridge ERROR
        # on timeout.  Raw stop + bounded drain mirrors SystemView shutdown.
        remaining = self._bridge._exit_stream()
        try:
            self._bridge._write_raw(b"RTTView.stop()\n")
            time.sleep(0.3)
        except Exception:
            pass  # 即使停止失败也继续恢复状态
        self._running = False
        return remaining

    @staticmethod
    def _parse_rtt_startup(output: str) -> dict:
        """解析 RTT 启动输出，提取控制块地址和缓冲区信息。"""
        result = {
            "control_block_addr": "",
            "up_buffers": [],
            "down_buffers": [],
        }

        # 提取控制块地址
        addr_match = re.search(
            r'Find SEGGER RTT addr\s+(0x[0-9a-fA-F]+)', output
        )
        if addr_match:
            result["control_block_addr"] = addr_match.group(1)

        # 支持 "Addr = 0x..., wSize = ..., Channel = ..." 前缀格式
        alt_match = re.search(r'Addr\s*=\s*(0x[0-9a-fA-F]+)', output)
        if alt_match and not result["control_block_addr"]:
            result["control_block_addr"] = alt_match.group(1)

        # 动态解析 UpBuffer/DownBuffer 通道（不硬编码数量）
        # 支持可选的 Name 字段: "... Mode: N Name: xxx"
        for m in re.finditer(
            r'UpBuffer\s+Channel\s+(\d+)\s+Size:\s+(\d+)\s+Mode:\s+(\d+)'
            r'(?:\s+Name:\s*(\S+))?',
            output,
        ):
            ch, size, mode = int(m.group(1)), int(m.group(2)), int(m.group(3))
            name = m.group(4) or ""
            result["up_buffers"].append({
                "channel": ch,
                "size": size,
                "mode": mode,
                "active": size > 0,
                "name": name,
            })

        for m in re.finditer(
            r'DownBuffer\s+Channel\s+(\d+)\s+Size:\s+(\d+)\s+Mode:\s+(\d+)'
            r'(?:\s+Name:\s*(\S+))?',
            output,
        ):
            ch, size, mode = int(m.group(1)), int(m.group(2)), int(m.group(3))
            name = m.group(4) or ""
            result["down_buffers"].append({
                "channel": ch,
                "size": size,
                "mode": mode,
                "active": size > 0,
                "name": name,
            })

        return result
