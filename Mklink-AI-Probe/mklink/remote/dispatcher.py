"""Capability dispatcher that delegates to existing public Mklink APIs."""

from __future__ import annotations

import base64
import threading
from dataclasses import replace
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
from mklink.remote.transfer import TransferError, UploadManager


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


class OperationDispatcher:
    """Stateful agent-side router with transfer and resource ownership."""

    def __init__(
        self,
        project_root: str | Path = ".",
        *,
        upload_manager: UploadManager | None = None,
        runtime_probe: str | None = None,
        runtime_info: dict | None = None,
    ):
        self.project_root = Path(project_root).expanduser().resolve()
        self.runtime_probe = runtime_probe
        self._bound_runtime_probe = None
        self._runtime_probe_lock = threading.Lock()
        self._uploads = upload_manager or UploadManager(
            self.project_root / ".mklink" / "remote-uploads",
        )
        from mklink.remote.shared_target import SharedTarget
        self._target = SharedTarget(str(self.project_root), self._shared_probe, runtime_info=runtime_info)

    def capabilities(self):
        capabilities = protocol_capabilities()
        capabilities['stream.rtt'] = replace(capabilities['stream.rtt'],
            detail=capabilities['stream.rtt'].detail + '; shared terminal and per-channel raw cursor reads with loss diagnostics')
        capabilities['stream.systemview'] = replace(capabilities['stream.systemview'],
            detail='Shared capture; v2 bounded cursor pages and cached task names; stop detaches borrowers')
        capabilities['target.memory'] = replace(capabilities['target.memory'],
            detail='Shared backend; memory transfers limited to 4096 bytes per request')
        return capabilities

    def connect_target(self, *, port=None, axf=None):
        return self._target.connect(port=port, axf=axf)

    def client_closed(self, client_id):
        self._target.client_closed(client_id)

    def close(self) -> None:
        try:
            self._target.close()
        finally:
            self._uploads.close()

    def _shared_probe(self):
        from mklink.probes import select_probe
        from mklink.runtime import RuntimeErrorResponse
        # Only identity initialization is serialized, never UART I/O or target work.
        with self._runtime_probe_lock:
            if self._bound_runtime_probe is None:
                try:
                    selected = select_probe(self.runtime_probe, allow_lobby=True)
                except RuntimeErrorResponse:
                    raise CapabilityUnavailableError(data={'capability': 'uart',
                        'reason': 'probe-identity-unavailable'}) from None
                if selected['probe_id'] != 'lobby' and not selected['identity_stable']:
                    raise CapabilityUnavailableError(data={'capability': 'uart',
                        'reason': 'stable-probe-identity-required'})
                self._bound_runtime_probe = selected['probe_id']
            return self._bound_runtime_probe

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
            shared_target=self._target,
            project_root=self.project_root,
            runtime_probe=self._shared_probe() if operation in (
                'modbus.read', 'modbus.write', 'modbus.scan', 'serial.list', 'serial.exchange') else None,
        )


def dispatch_capability(
    operation: str,
    params: Mapping[str, Any],
    context: AgentDispatchContext | None = None,
    *,
    upload_manager: UploadManager | None = None,
    shared_target=None,
    project_root: str | Path = ".",
    runtime_probe: str | None = None,
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

    if operation.startswith("serial."):
        return _dispatch_serial(operation, params, context,
                                project_root=project_root, probe=runtime_probe)
    if operation.startswith("modbus."):
        return _dispatch_modbus(operation, params, context,
                                project_root=project_root, probe=runtime_probe)

    from mklink.remote.shared_target import OPERATIONS
    if operation in OPERATIONS and shared_target is not None:
        if context is None or context.device is not shared_target:
            raise CapabilityUnavailableError(data={'reason': 'call-agent.reconnect-first'})
        return shared_target.dispatch(requested_operation, operation, params,
                                      context.client_id, upload_manager)
    raise CapabilityUnavailableError(data={'capability': schema.capability,
        'reason': 'shared-target-required' if operation in OPERATIONS else 'shared-stream-migration-pending'})


def _dispatch_serial(operation, params, context, *, project_root, probe):
    import math
    from mklink.runtime import RuntimeClient, RuntimeErrorResponse
    from mklink.uart_session import uart_session, require_serial_connection
    from mklink.usb_interfaces import canonical_serial_port
    name = f"Agent Serial {(context.client_id or 'local') if context else 'local'}"
    if operation == 'serial.list':
        client = RuntimeClient(project_root=project_root, kind='sdk', name=name)
        try:
            client.connect(scope='uart', probe=probe)
            return client.call('uart_ports')
        finally:
            client.close()
    encoded = _text(params.get('data_b64'), 'data_b64', allow_empty=True)
    try:
        if len(encoded) > 5464:
            raise ValueError('payload too large')
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 4096:
            raise ValueError('payload too large')
    except (ValueError, TypeError):
        raise RequestValidationError('Invalid operation parameters', data={'field': 'data_b64'}) from None
    timeout = params.get('timeout', .1)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 <= timeout <= 5:
        raise RequestValidationError('Invalid operation parameters', data={'field': 'timeout'})
    port = _text(params.get('port'), 'port').strip()
    if not port:
        raise RequestValidationError('Invalid operation parameters', data={'field': 'port'})
    baud = _integer(params.get('baudrate', 115200), 'baudrate', minimum=1)
    if baud > 4000000:
        raise RequestValidationError('Invalid operation parameters', data={'field': 'baudrate'})
    connection = {'port': canonical_serial_port(port), 'baudrate': baud,
                  'databits': 8, 'stopbits': 1, 'parity': 'N'}
    try:
        with uart_session('serial', {'ports': [connection]}, project_root=project_root,
                          probe=probe, kind='sdk', name=name) as client:
            require_serial_connection(client.call('serial_status'), connection)
            result = client.call('serial_exchange', {'port': connection['port'],
                                 'data': data.hex(), 'timeout': timeout})
            return _bytes_result(bytes.fromhex(result['data']))
    except RuntimeErrorResponse as error:
        raise AgentOperationError('Shared serial exchange failed; write result may be unknown; do not retry automatically',
                                  data={'capability': 'serial', 'status': error.status_code}) from None


def _dispatch_modbus(operation, params, context, *, project_root, probe):
    import math
    from mklink.modbus._scanner import scan_slaves, validate_scan_range
    from mklink.modbus._session import validate_slave, validate_transaction
    from mklink.uart_session import modbus_session
    from mklink.usb_interfaces import canonical_serial_port
    from mklink.runtime import RuntimeErrorResponse

    def invalid(field):
        raise RequestValidationError("Invalid operation parameters", data={"field": field})

    port = _text(params.get('port'), 'port').strip()
    if not port:
        invalid('port')
    connection = {'port': canonical_serial_port(port),
                  'baudrate': _integer(params.get('baudrate', 9600), 'baudrate', minimum=1),
                  'bytesize': 8, 'parity': 'N', 'stopbits': 1}
    # Omitted timing borrows the current worker unchanged. Explicit timing must match.
    if 'timeout' in params:
        value = params['timeout']
        if isinstance(value, bool):
            invalid('timeout')
        try:
            value = float(value)
        except (TypeError, ValueError):
            invalid('timeout')
        if not math.isfinite(value):
            invalid('timeout')
        connection['timeout'] = min(max(value, .05), 10.0)
    address = _integer(params.get('address', 0) if operation == 'modbus.scan'
                       else params.get('address'), 'address')
    if address > 65535:
        invalid('address')
    if operation == 'modbus.scan':
        start = _integer(params.get('start', 1), 'start', minimum=1)
        end = _integer(params.get('end', 247), 'end', minimum=start)
        try:
            validate_scan_range(start, end, address)
        except ValueError:
            invalid('range')
    else:
        slave = _integer(params.get('slave', 1), 'slave', minimum=1)
        try:
            validate_slave(slave)
        except ValueError:
            invalid('slave')
        kind = _text(params.get('kind'), 'kind')
        transaction = {'slave': slave, 'start': address}
        if operation == 'modbus.read':
            if kind != 'holding':
                invalid('kind')
            count = _integer(params.get('count', 1), 'count', minimum=1)
            try:
                validate_transaction(3, address, quantity=count)
            except ValueError:
                invalid('count')
            transaction.update(fc=3, quantity=count)
        else:
            fc = {'register': 6, 'registers': 16, 'coil': 5, 'coils': 15}.get(kind)
            if fc is None:
                invalid('kind')
            value = params.get('value')
            values = value if fc in (15, 16) else [value]
            if not isinstance(values, list):
                invalid('value')
            if fc in (5, 15):
                if any(type(item) is not bool for item in values):
                    invalid('value')
            else:
                values = [_integer(item, 'value') for item in values]
            try:
                _, _, _, values = validate_transaction(fc, address, values=values)
            except ValueError:
                invalid('value')
            transaction.update(fc=fc, values=values)
    name = f"Agent Modbus {(context.client_id or 'local') if context else 'local'}"
    try:
        with modbus_session(connection, scan=operation == 'modbus.scan',
                            project_root=project_root, probe=probe, kind='sdk', name=name) as client:
            if operation == 'modbus.scan':
                return scan_slaves(lambda slave, register: client.call('modbus_probe',
                    {'slave': slave, 'address': register}), start_addr=start,
                    end_addr=end, probe_register=address)
            result = client.call('modbus_transaction', transaction)
            return result['values'] if operation == 'modbus.read' else {'written': True}
    except RuntimeErrorResponse as exc:
        message = 'Shared Modbus request failed'
        if operation == 'modbus.write':
            message += '; write result may be unknown'
        raise AgentOperationError(message + '; do not retry automatically',
                                  data={'capability': 'modbus', 'status': exc.status_code}) from None


__all__ = ["OperationDispatcher", "dispatch_capability"]
