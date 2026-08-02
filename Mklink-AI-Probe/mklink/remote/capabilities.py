"""Stable capability and operation contracts for direct remote debugging.

The catalog describes existing public Mklink APIs; it deliberately contains no
device access or transport code.  Optional dependencies are probed without
importing them so ordinary client and agent imports stay lightweight.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from types import MappingProxyType
from typing import Any, Mapping

from mklink.remote.protocol import Capability as ProtocolCapability
from mklink.remote.protocol import ProtocolError


@dataclass(frozen=True)
class Capability:
    """One versioned feature group exposed during protocol negotiation."""

    name: str
    version: int
    operations: tuple[str, ...]
    optional: bool = False


@dataclass(frozen=True)
class OperationSchema:
    """Small machine-readable operation contract used by CLI and MCP gates."""

    capability: str
    parameters: tuple[str, ...] = ()
    high_risk: bool = False


class CapabilityUnavailableError(ProtocolError):
    """A declared feature cannot service the requested operation."""

    code = -32004
    public_message = "Capability unavailable"


_CAPABILITIES = {
    "probe.diagnostics": Capability(
        "probe.diagnostics",
        1,
        ("probe.info",),
    ),
    "flash.online": Capability(
        "flash.online",
        1,
        ("flash.program", "flash.erase_chip", "flash.erase_sector"),
    ),
    "flash.offline": Capability(
        "flash.offline",
        1,
        ("offline.preview", "offline.deploy"),
    ),
    "target.debug": Capability(
        "target.debug",
        1,
        (
            "target.reset",
            "target.halt",
            "target.resume",
            "target.step",
            "breakpoint.set",
            "breakpoint.clear",
            "breakpoint.clear_all",
            "registers.core",
        ),
    ),
    "target.memory": Capability(
        "target.memory",
        1,
        (
            "memory.read",
            "memory.write",
            "register.read",
            "variable.read",
            "variable.write",
        ),
    ),
    "target.symbols": Capability(
        "target.symbols",
        1,
        (
            "symbols.status",
            "symbols.parse",
            "symbols.list",
            "symbols.search",
            "symbols.memory_map",
        ),
    ),
    "stream.rtt": Capability(
        "stream.rtt",
        1,
        ("rtt.start", "rtt.read", "rtt.write", "rtt.stop"),
    ),
    "stream.systemview": Capability(
        "stream.systemview",
        1,
        (
            "systemview.start",
            "systemview.read",
            "systemview.stop",
            "systemview.resolve_task_names",
        ),
    ),
    "target.hardfault": Capability(
        "target.hardfault",
        1,
        ("hardfault.check", "hardfault.decode"),
    ),
    "transfer.upload": Capability(
        "transfer.upload",
        1,
        ("transfer.open", "transfer.chunk", "transfer.finalize", "transfer.abort"),
    ),
    "serial": Capability(
        "serial",
        1,
        ("serial.list", "serial.exchange"),
        optional=True,
    ),
    "modbus": Capability(
        "modbus",
        1,
        ("modbus.read", "modbus.write", "modbus.scan"),
        optional=True,
    ),
}

CAPABILITIES: Mapping[str, Capability] = MappingProxyType(_CAPABILITIES)

_SCHEMAS = {
    "probe.info": OperationSchema("probe.diagnostics"),
    "flash.program": OperationSchema(
        "flash.online",
        ("firmware", "verify", "reset_after", "confirm"),
        high_risk=True,
    ),
    "flash.erase_chip": OperationSchema(
        "flash.online",
        ("confirm",),
        high_risk=True,
    ),
    "flash.erase_sector": OperationSchema(
        "flash.online",
        ("address", "confirm"),
        high_risk=True,
    ),
    "offline.preview": OperationSchema("flash.offline", ("config",)),
    "offline.deploy": OperationSchema(
        "flash.offline",
        ("config", "firmware_files", "algorithm_files", "confirm"),
        high_risk=True,
    ),
    "target.reset": OperationSchema("target.debug", ("confirm",), high_risk=True),
    "target.halt": OperationSchema("target.debug"),
    "target.resume": OperationSchema("target.debug"),
    "target.step": OperationSchema("target.debug"),
    "breakpoint.set": OperationSchema(
        "target.debug",
        ("address", "confirm"),
        high_risk=True,
    ),
    "breakpoint.clear": OperationSchema(
        "target.debug",
        ("slot", "confirm"),
        high_risk=True,
    ),
    "breakpoint.clear_all": OperationSchema(
        "target.debug",
        ("confirm",),
        high_risk=True,
    ),
    "registers.core": OperationSchema("target.debug"),
    "memory.read": OperationSchema("target.memory", ("address", "size")),
    "memory.write": OperationSchema(
        "target.memory",
        ("address", "data_b64", "confirm"),
        high_risk=True,
    ),
    "register.read": OperationSchema("target.memory", ("name",)),
    "variable.read": OperationSchema("target.memory", ("name",)),
    "variable.write": OperationSchema(
        "target.memory",
        ("name", "value", "confirm"),
        high_risk=True,
    ),
    "symbols.status": OperationSchema("target.symbols"),
    "symbols.parse": OperationSchema("target.symbols", ("source",)),
    "symbols.list": OperationSchema("target.symbols"),
    "symbols.search": OperationSchema("target.symbols", ("query",)),
    "symbols.memory_map": OperationSchema("target.symbols"),
    "rtt.start": OperationSchema("stream.rtt"),
    "rtt.read": OperationSchema("stream.rtt"),
    "rtt.write": OperationSchema("stream.rtt", ("data",)),
    "rtt.stop": OperationSchema("stream.rtt"),
    "systemview.start": OperationSchema("stream.systemview"),
    "systemview.read": OperationSchema("stream.systemview"),
    "systemview.stop": OperationSchema("stream.systemview"),
    "systemview.resolve_task_names": OperationSchema(
        "stream.systemview",
        ("task_ids",),
    ),
    "hardfault.check": OperationSchema("target.hardfault"),
    "hardfault.decode": OperationSchema("target.hardfault"),
    "transfer.open": OperationSchema("transfer.upload", ("filename", "size")),
    "transfer.chunk": OperationSchema(
        "transfer.upload",
        ("session_id", "offset", "sequence", "data"),
    ),
    "transfer.finalize": OperationSchema(
        "transfer.upload",
        ("session_id", "size", "sha256"),
    ),
    "transfer.abort": OperationSchema("transfer.upload", ("session_id",)),
    "serial.list": OperationSchema("serial"),
    "serial.exchange": OperationSchema(
        "serial",
        ("port", "data_b64", "confirm"),
        high_risk=True,
    ),
    "modbus.read": OperationSchema(
        "modbus",
        ("port", "kind", "address", "count", "slave"),
    ),
    "modbus.write": OperationSchema(
        "modbus",
        ("port", "kind", "address", "value", "slave", "confirm"),
        high_risk=True,
    ),
    "modbus.scan": OperationSchema("modbus", ("port",)),
}

OPERATION_SCHEMAS: Mapping[str, OperationSchema] = MappingProxyType(_SCHEMAS)

OPERATION_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "idcode": "probe.info",
        "mcu_name": "probe.info",
        "flash": "flash.program",
        "erase_chip": "flash.erase_chip",
        "erase_sector": "flash.erase_sector",
        "reset": "target.reset",
        "halt": "target.halt",
        "resume": "target.resume",
        "step": "target.step",
        "set_breakpoint": "breakpoint.set",
        "clear_breakpoint": "breakpoint.clear",
        "read_core_registers": "registers.core",
        "read_memory": "memory.read",
        "write_memory": "memory.write",
        "read_register": "register.read",
        "read_variable": "variable.read",
        "write_variable": "variable.write",
        "rtt_start": "rtt.start",
        "rtt_read": "rtt.read",
        "rtt_write": "rtt.write",
        "rtt_stop": "rtt.stop",
        "check_hardfault": "hardfault.check",
        "decode_hardfault": "hardfault.decode",
    }
)


def canonical_operation(operation: str) -> str:
    return OPERATION_ALIASES.get(operation, operation)


def operation_schema(operation: str) -> OperationSchema | None:
    return OPERATION_SCHEMAS.get(canonical_operation(operation))


def capability_available(name: str) -> bool:
    if name == "serial":
        return find_spec("serial") is not None
    if name == "modbus":
        return find_spec("pymodbus") is not None
    return name in CAPABILITIES


def protocol_capabilities() -> dict[str, ProtocolCapability]:
    """Return deterministic handshake descriptors for the agent seam."""

    return {
        name: ProtocolCapability(
            capability_available(name),
            version=str(spec.version),
            detail=", ".join(spec.operations),
        )
        for name, spec in CAPABILITIES.items()
    }


def capability_catalog() -> dict[str, dict[str, Any]]:
    """Return a JSON-safe catalog including schemas and risk metadata."""

    return {
        name: {
            "name": spec.name,
            "version": spec.version,
            "optional": spec.optional,
            "available": capability_available(name),
            "operations": [
                {
                    "name": operation,
                    "parameters": list(OPERATION_SCHEMAS[operation].parameters),
                    "high_risk": OPERATION_SCHEMAS[operation].high_risk,
                }
                for operation in spec.operations
            ],
        }
        for name, spec in CAPABILITIES.items()
    }


__all__ = [
    "CAPABILITIES",
    "OPERATION_ALIASES",
    "OPERATION_SCHEMAS",
    "Capability",
    "CapabilityUnavailableError",
    "OperationSchema",
    "canonical_operation",
    "capability_available",
    "capability_catalog",
    "operation_schema",
    "protocol_capabilities",
]
