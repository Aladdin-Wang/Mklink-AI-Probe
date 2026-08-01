"""Capability dispatcher that delegates to existing public Mklink APIs."""

from __future__ import annotations

import base64
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from mklink.remote.agent import AgentDispatchContext
from mklink.remote.capabilities import (
    CapabilityUnavailableError,
    canonical_operation,
    capability_available,
    operation_schema,
    protocol_capabilities,
)
from mklink.remote.protocol import (
    AgentOperationError,
    MethodNotFoundError,
    RequestValidationError,
)
from mklink.remote.resource_manager import ResourceError, ResourceGroup
from mklink.remote.transfer import RemoteFile, TransferError, UploadManager


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise RequestValidationError(
            "Invalid operation parameters",
            data={"field": field},
        )
    try:
        result = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        raise RequestValidationError(
            "Invalid operation parameters",
            data={"field": field},
        ) from None
    if result < minimum:
        raise RequestValidationError(
            "Invalid operation parameters",
            data={"field": field},
        )
    return result


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise RequestValidationError(
            "Invalid operation parameters",
            data={"field": field},
        )
    return value


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RequestValidationError(
            "Invalid operation parameters",
            data={"field": field},
        )
    return value


def _confirmation(params: Mapping[str, Any], operation: str) -> None:
    if params.get("confirm") is not True:
        raise RequestValidationError(
            "Explicit confirmation required",
            data={"operation": operation, "field": "confirm"},
        )


def _remote_offline_config(value: Any) -> dict[str, Any]:
    """Adapt v0.1.4 offline source metadata to opaque Remote uploads."""

    payload = dict(_mapping(value, "config"))
    firmwares = payload.get("firmwares")
    if not isinstance(firmwares, list):
        return payload
    normalized: list[Any] = []
    for index, firmware in enumerate(firmwares):
        if not isinstance(firmware, Mapping):
            normalized.append(firmware)
            continue
        item = dict(firmware)
        if item.get("source_path") not in (None, ""):
            raise RequestValidationError(
                "Invalid operation parameters",
                data={"field": "config.firmwares.source_path"},
            )
        item.pop("source_path", None)
        item.setdefault("upload_index", index)
        normalized.append(item)
    payload["firmwares"] = normalized
    return payload


def _bytes_result(data: bytes) -> dict[str, str]:
    return {"__bytes__": base64.b64encode(data).decode("ascii")}


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return _bytes_result(value)
    if isinstance(value, RemoteFile):
        return value.as_dict()
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        # Paths are internal implementation details and never cross the wire.
        return value.name
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class OperationDispatcher:
    """Stateful agent-side router with transfer and resource ownership."""

    def __init__(
        self,
        project_root: str | Path = ".",
        *,
        upload_manager: UploadManager | None = None,
    ):
        self.project_root = Path(project_root).expanduser().resolve()
        self._uploads = upload_manager or UploadManager(
            self.project_root / ".mklink" / "remote-uploads",
        )
        self._target_lock = threading.RLock()
        self._serial_lock = threading.RLock()
        self._stream_owners: dict[str, str] = {}

    def capabilities(self):
        return protocol_capabilities()

    def close(self) -> None:
        self._uploads.close()

    def __call__(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: AgentDispatchContext,
    ) -> Any:
        return self.dispatch(operation, params, context)

    def dispatch(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: AgentDispatchContext,
    ) -> Any:
        return dispatch_capability(
            operation,
            params,
            context=context,
            upload_manager=self._uploads,
            target_lock=self._target_lock,
            serial_lock=self._serial_lock,
            stream_owners=self._stream_owners,
        )


def dispatch_capability(
    operation: str,
    params: Mapping[str, Any],
    context: AgentDispatchContext | None = None,
    *,
    upload_manager: UploadManager | None = None,
    target_lock: threading.RLock | None = None,
    serial_lock: threading.RLock | None = None,
    stream_owners: dict[str, str] | None = None,
) -> Any:
    """Dispatch one declared operation through existing public domain APIs."""

    if not isinstance(operation, str) or not isinstance(params, Mapping):
        raise RequestValidationError()
    requested_operation = operation
    operation = canonical_operation(operation)
    schema = operation_schema(operation)
    if schema is None:
        raise MethodNotFoundError(
            data={"method": requested_operation, "reason": "unsupported"},
        )
    if not capability_available(schema.capability):
        raise CapabilityUnavailableError(
            data={"capability": schema.capability, "operation": operation},
        )
    if schema.high_risk:
        _confirmation(params, operation)

    if operation.startswith("transfer."):
        if upload_manager is None:
            raise CapabilityUnavailableError(
                data={"capability": "transfer.upload", "reason": "not-configured"},
            )
        try:
            if operation == "transfer.open":
                return upload_manager.open(
                    _text(params.get("filename"), "filename"),
                    _integer(params.get("size"), "size"),
                    resume=bool(params.get("resume", False)),
                    offset=params.get("offset"),
                    destination=params.get("destination"),
                )
            if operation == "transfer.chunk":
                encoded = _text(
                    params.get("data", params.get("data_b64")),
                    "data",
                )
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError):
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "data"},
                    ) from None
                return upload_manager.chunk(
                    _text(params.get("session_id"), "session_id"),
                    _integer(params.get("offset"), "offset"),
                    _integer(params.get("sequence"), "sequence"),
                    data,
                    resume=bool(params.get("resume", False)),
                )
            if operation == "transfer.finalize":
                result = upload_manager.finalize(
                    _text(params.get("session_id"), "session_id"),
                    _integer(params.get("size"), "size"),
                    _text(params.get("sha256"), "sha256"),
                )
                return result.as_dict()
            return {
                "aborted": upload_manager.abort(
                    _text(params.get("session_id"), "session_id"),
                )
            }
        except TransferError:
            raise AgentOperationError("Transfer operation failed") from None

    if operation == "offline.preview":
        from mklink.offline_download import generate_offline_script, parse_offline_config

        config = parse_offline_config(_remote_offline_config(params.get("config")))
        return {
            "model": config.model,
            "script_name": config.script_name,
            "script": generate_offline_script(config),
        }

    if operation == "offline.deploy":
        if upload_manager is None:
            raise CapabilityUnavailableError(
                data={"capability": "transfer.upload", "reason": "not-configured"},
            )
        from mklink.discovery import find_microkeen_disk
        from mklink.offline_download import deploy_offline_bundle, parse_offline_config

        config = parse_offline_config(_remote_offline_config(params.get("config")))
        disk = find_microkeen_disk()
        if not disk:
            raise CapabilityUnavailableError(
                data={"capability": "flash.offline", "reason": "probe-disk-unavailable"},
            )
        firmware_refs = _mapping(params.get("firmware_files"), "firmware_files")
        algorithm_refs = _mapping(
            params.get("algorithm_files", {}),
            "algorithm_files",
        )
        firmware_sources = {
            str(key): upload_manager.resolve(_text(value, "firmware_files"))
            for key, value in firmware_refs.items()
        }
        algorithm_sources = {
            str(key): upload_manager.resolve(_text(value, "algorithm_files"))
            for key, value in algorithm_refs.items()
        }
        return deploy_offline_bundle(
            config,
            disk,
            firmware_sources=firmware_sources,
            algorithm_sources=algorithm_sources,
        )

    if operation.startswith("serial."):
        return _dispatch_serial(
            operation,
            params,
            context,
            serial_lock or threading.RLock(),
        )
    if operation.startswith("modbus."):
        return _dispatch_modbus(
            operation,
            params,
            context,
            serial_lock or threading.RLock(),
        )

    device = context.device if context is not None else None
    if device is None:
        raise CapabilityUnavailableError(
            data={"capability": schema.capability, "reason": "probe-disconnected"},
        )

    lock = target_lock or threading.RLock()
    owners = stream_owners if stream_owners is not None else {}
    with lock:
        return _dispatch_device(
            requested_operation,
            operation,
            params,
            device,
            context,
            upload_manager,
            owners,
        )


def _dispatch_device(
    requested_operation: str,
    operation: str,
    params: Mapping[str, Any],
    device: Any,
    context: AgentDispatchContext | None,
    uploads: UploadManager | None,
    stream_owners: dict[str, str],
) -> Any:
    manager = context.resource_manager if context is not None else None
    persistent = operation.startswith(("rtt.", "systemview."))
    owner_key = "rtt" if operation.startswith("rtt.") else "systemview"
    owner = stream_owners.get(owner_key)
    release_owner = False

    if manager is not None:
        if operation.endswith(".start"):
            owner = f"ai:remote:{owner_key}:{uuid.uuid4().hex}"
            try:
                manager.acquire(ResourceGroup.TARGET_DEBUG, owner)
            except ResourceError:
                raise CapabilityUnavailableError(
                    data={"capability": "target.debug", "reason": "resource-busy"},
                ) from None
        elif persistent and owner:
            pass
        else:
            owner = f"ai:remote:operation:{uuid.uuid4().hex}"
            try:
                manager.acquire(ResourceGroup.TARGET_DEBUG, owner)
            except ResourceError:
                raise CapabilityUnavailableError(
                    data={"capability": "target.debug", "reason": "resource-busy"},
                ) from None
            release_owner = True

    try:
        if operation == "probe.info":
            if requested_operation == "idcode":
                return int(device.idcode)
            if requested_operation == "mcu_name":
                return str(device.mcu_name)
            return {
                "connected": bool(device.connected),
                "idcode": int(device.idcode),
                "mcu_name": str(device.mcu_name),
            }
        if operation == "flash.program":
            if uploads is None:
                raise CapabilityUnavailableError(
                    data={"capability": "transfer.upload", "reason": "not-configured"},
                )
            firmware = uploads.resolve(_text(params.get("firmware"), "firmware"))
            allowed = {
                "target_part",
                "base_address",
                "board",
                "hpm_flash_cfg",
                "swd_clock",
                "verify",
                "reset_after",
            }
            options = {key: params[key] for key in allowed if key in params}
            return _json_value(device.flash(str(firmware), **options))
        if operation == "flash.erase_chip":
            return bool(device.erase_chip())
        if operation == "flash.erase_sector":
            return bool(device.erase_sector(_integer(params.get("address"), "address")))
        if operation == "target.reset":
            device.reset()
            return {"reset": True}
        if operation == "target.halt":
            return _json_value(device.halt())
        if operation == "target.resume":
            return _json_value(device.resume())
        if operation == "target.step":
            return _json_value(device.step())
        if operation == "breakpoint.set":
            slot = params.get("slot")
            return {
                "slot": int(
                    device.set_breakpoint(
                        _integer(params.get("address"), "address"),
                        None if slot is None else _integer(slot, "slot"),
                    )
                )
            }
        if operation == "breakpoint.clear":
            device.clear_breakpoint(_integer(params.get("slot"), "slot"))
            return {"cleared": True}
        if operation == "breakpoint.clear_all":
            return {"cleared": int(device.clear_all_breakpoints())}
        if operation == "registers.core":
            return _json_value(device.read_core_registers())
        if operation == "memory.read":
            size = _integer(params.get("size"), "size", minimum=1)
            if size > 1024 * 1024:
                raise RequestValidationError(
                    "Invalid operation parameters",
                    data={"field": "size"},
                )
            return _bytes_result(
                device.read_memory(
                    _integer(params.get("address"), "address"),
                    size,
                )
            )
        if operation == "memory.write":
            encoded = _text(params.get("data_b64"), "data_b64")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise RequestValidationError(
                    "Invalid operation parameters",
                    data={"field": "data_b64"},
                ) from None
            if not data or len(data) > 1024 * 1024:
                raise RequestValidationError(
                    "Invalid operation parameters",
                    data={"field": "data_b64"},
                )
            device.write_memory(
                _integer(params.get("address"), "address"),
                data,
            )
            return {"written": len(data)}
        if operation == "register.read":
            return int(device.read_register(_text(params.get("name"), "name")))
        if operation == "variable.read":
            return _json_value(device.read_variable(_text(params.get("name"), "name")))
        if operation == "variable.write":
            device.write_variable(
                _text(params.get("name"), "name"),
                _integer(params.get("value"), "value"),
            )
            return {"written": True}
        if operation == "symbols.status":
            return _json_value(device.axf_status)
        if operation == "symbols.parse":
            if uploads is None:
                raise CapabilityUnavailableError(
                    data={"capability": "transfer.upload", "reason": "not-configured"},
                )
            source = uploads.resolve(_text(params.get("source"), "source"))
            backend = params.get("elf_backend")
            if backend not in (None, "builtin", "external"):
                raise RequestValidationError(
                    "Invalid operation parameters",
                    data={"field": "elf_backend"},
                )
            return _json_value(device.parse_axf(str(source), elf_backend=backend))
        if operation in {"symbols.list", "symbols.search"}:
            catalog = device.symbol_catalog
            if catalog is None:
                raise CapabilityUnavailableError(
                    data={"capability": "target.symbols", "reason": "symbols-not-loaded"},
                )
            return catalog.to_page(
                query=str(params.get("query", "")),
                writable=bool(params.get("writable", False)),
                offset=_integer(params.get("offset", 0), "offset"),
                limit=_integer(params.get("limit", 200), "limit", minimum=1),
            )
        if operation == "symbols.memory_map":
            return _json_value(device.memory_map())
        if operation == "rtt.start":
            result = _json_value(
                device.rtt_start(
                    params.get("addr"),
                    channel=_integer(params.get("channel", 0), "channel"),
                    search_size=_integer(params.get("search_size", 1024), "search_size", minimum=1),
                    mode=params.get("mode"),
                )
            )
            if owner:
                stream_owners[owner_key] = owner
            return result
        if operation == "rtt.read":
            return str(device.rtt_read(float(params.get("duration", 2.0))))
        if operation == "rtt.write":
            return bool(device.rtt_write(_text(params.get("data"), "data", allow_empty=True)))
        if operation == "rtt.stop":
            return str(device.rtt_stop())
        if operation == "systemview.start":
            result = _json_value(
                device.systemview_start(
                    params.get("addr"),
                    channel=_integer(params.get("channel", 1), "channel"),
                    search_size=_integer(params.get("search_size", 1024), "search_size", minimum=1),
                    mode=params.get("mode"),
                )
            )
            if owner:
                stream_owners[owner_key] = owner
            return result
        if operation == "systemview.read":
            return _json_value(device.systemview_read(float(params.get("duration", 2.0))))
        if operation == "systemview.stop":
            device.systemview_stop()
            return {"stopped": True}
        if operation == "systemview.resolve_task_names":
            task_ids = params.get("task_ids")
            if not isinstance(task_ids, list):
                raise RequestValidationError(
                    "Invalid operation parameters",
                    data={"field": "task_ids"},
                )
            return _json_value(
                device.systemview_resolve_task_names(
                    [_integer(item, "task_ids") for item in task_ids[:256]]
                )
            )
        if operation == "hardfault.check":
            return _json_value(device.check_hardfault())
        if operation == "hardfault.decode":
            registers = params.get("fault_regs")
            if registers is not None:
                registers = dict(_mapping(registers, "fault_regs"))
            return _json_value(device.decode_hardfault(registers))
        raise MethodNotFoundError(data={"method": requested_operation})
    finally:
        if manager is not None and owner:
            if release_owner:
                manager.release(owner)
            elif operation.endswith(".stop"):
                manager.release(owner)
                stream_owners.pop(owner_key, None)
            elif operation.endswith(".start") and owner_key not in stream_owners:
                manager.release(owner)


def _dispatch_serial(
    operation: str,
    params: Mapping[str, Any],
    context: AgentDispatchContext | None,
    lock: threading.RLock,
) -> Any:
    if operation == "serial.list":
        from mklink.serial import list_uart_ports

        return list_uart_ports()
    from mklink.serial import SerialPort

    encoded = _text(params.get("data_b64"), "data_b64", allow_empty=True)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise RequestValidationError(
            "Invalid operation parameters",
            data={"field": "data_b64"},
        ) from None
    timeout = min(max(float(params.get("timeout", 0.1)), 0.0), 5.0)
    manager = context.resource_manager if context is not None else None
    owner = f"ai:remote:serial:{uuid.uuid4().hex}"
    with lock:
        if manager is not None:
            try:
                manager.acquire(ResourceGroup.SERIAL_PORT, owner)
            except ResourceError:
                raise CapabilityUnavailableError(
                    data={"capability": "serial", "reason": "resource-busy"},
                ) from None
        port = None
        try:
            port = SerialPort(
                _text(params.get("port"), "port"),
                baudrate=_integer(
                    params.get("baudrate", 115200),
                    "baudrate",
                    minimum=1,
                ),
                timeout=timeout,
            )
            if not port.open():
                raise CapabilityUnavailableError(
                    data={"capability": "serial", "reason": "port-unavailable"},
                )
            port.write(data)
            if timeout:
                time.sleep(timeout)
            return _bytes_result(port.read_available())
        finally:
            try:
                if port is not None:
                    port.close()
            finally:
                if manager is not None:
                    manager.release(owner)


def _dispatch_modbus(
    operation: str,
    params: Mapping[str, Any],
    context: AgentDispatchContext | None,
    lock: threading.RLock,
) -> Any:
    import math

    from mklink.modbus import ModbusClient, scan_slaves

    manager = context.resource_manager if context is not None else None
    owner = f"ai:remote:modbus:{uuid.uuid4().hex}"
    with lock:
        if manager is not None:
            try:
                manager.acquire(ResourceGroup.MODBUS_PORT, owner)
            except ResourceError:
                raise CapabilityUnavailableError(
                    data={"capability": "modbus", "reason": "resource-busy"},
                ) from None
        client = None
        try:
            port = _text(params.get("port"), "port")
            if not port.strip():
                raise RequestValidationError(
                    "Invalid operation parameters",
                    data={"field": "port"},
                )
            baudrate = _integer(
                params.get("baudrate", 9600),
                "baudrate",
                minimum=1,
            )
            if operation == "modbus.read":
                raw_timeout = params.get("timeout", 1.0)
                if isinstance(raw_timeout, bool):
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "timeout"},
                    )
                try:
                    timeout = float(raw_timeout)
                except (TypeError, ValueError):
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "timeout"},
                    ) from None
                if not math.isfinite(timeout):
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "timeout"},
                    )
                timeout = min(max(timeout, 0.05), 10.0)

                kind = _text(params.get("kind"), "kind")
                if kind != "holding":
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "kind"},
                    )
                address = _integer(params.get("address"), "address")
                count = _integer(params.get("count", 1), "count", minimum=1)
                slave = _integer(params.get("slave", 1), "slave", minimum=1)
                if address > 0xFFFF:
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "address"},
                    )
                if count > 125 or address + count > 0x10000:
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "count"},
                    )
                if slave > 247:
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "slave"},
                    )
            else:
                timeout = min(
                    max(float(params.get("timeout", 1.0)), 0.05),
                    10.0,
                )

            client = ModbusClient(
                port,
                baudrate=baudrate,
                timeout=timeout,
            )
            if not client.open():
                raise CapabilityUnavailableError(
                    data={"capability": "modbus", "reason": "port-unavailable"},
                )
            if operation == "modbus.scan":
                start = _integer(params.get("start", 1), "start", minimum=1)
                end = _integer(params.get("end", 247), "end", minimum=start)
                if end > 247:
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "end"},
                    )
                return scan_slaves(
                    client,
                    start_addr=start,
                    end_addr=end,
                    probe_register=_integer(params.get("address", 0), "address"),
                )
            if operation == "modbus.read":
                return client.read_holding_registers(address, count, slave)
            kind = _text(params.get("kind"), "kind")
            address = _integer(params.get("address"), "address")
            slave = _integer(params.get("slave", 1), "slave", minimum=1)
            value = params.get("value")
            if kind == "register":
                client.write_register(address, _integer(value, "value"), slave)
            elif kind == "registers" and isinstance(value, list):
                client.write_registers(
                    address,
                    [_integer(item, "value") for item in value],
                    slave,
                )
            elif kind == "coil":
                if not isinstance(value, bool):
                    raise RequestValidationError(
                        "Invalid operation parameters",
                        data={"field": "value"},
                    )
                client.write_coil(address, value, slave)
            elif kind == "coils" and isinstance(value, list) and all(
                isinstance(item, bool) for item in value
            ):
                client.write_coils(address, value, slave)
            else:
                raise RequestValidationError(
                    "Invalid operation parameters",
                    data={"field": "kind"},
                )
            return {"written": True}
        finally:
            try:
                if client is not None:
                    client.close()
            finally:
                if manager is not None:
                    manager.release(owner)


__all__ = ["OperationDispatcher", "dispatch_capability"]
