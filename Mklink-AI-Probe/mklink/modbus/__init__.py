"""MKLink Modbus RTU 调试模块 — 基于 pymodbus。"""

from mklink.modbus._client import ModbusClient
from mklink.modbus._format import RegisterSpec, format_registers, parse_register_spec
from mklink.modbus._scanner import scan_slaves
from mklink.modbus._poller import poll_registers
from mklink.modbus._monitor import monitor_traffic
from mklink.modbus._profile import load_profile


def __getattr__(name: str):
    # The base Modbus package also serves offline/profile and RTU-only callers.
    # Load optional Web dependencies only when a dashboard is requested.
    if name == 'ModbusDashboardServer':
        from mklink.modbus._dashboard import ModbusDashboardServer
        return ModbusDashboardServer
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

__all__ = [
    "ModbusClient",
    "format_registers",
    "parse_register_spec",
    "scan_slaves",
    "poll_registers",
    "RegisterSpec",
    "monitor_traffic",
    "load_profile",
    "ModbusDashboardServer",
]

