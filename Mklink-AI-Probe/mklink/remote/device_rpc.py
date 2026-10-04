"""Device RPC adapter used inside the admitted FastAPI backend."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RPC protocol helpers
# ---------------------------------------------------------------------------

def make_response(result: Any, req_id: int | None = None) -> str:
    return json.dumps({"jsonrpc": "2.0", "result": result, "id": req_id})


def make_error(code: int, message: str, req_id: int | None = None) -> str:
    return json.dumps({
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": req_id,
    })


# ---------------------------------------------------------------------------
# RPC method dispatcher
# ---------------------------------------------------------------------------

class DeviceDispatcher:
    """Bridges JSON-RPC calls to a local Device instance."""

    def __init__(self, device):
        self._device = device
        self._handlers: dict[str, Callable] = {
            "idcode": self._idcode,
            "mcu_name": self._mcu_name,
            "flash": self._flash,
            "erase_chip": self._erase_chip,
            "reset": self._reset,
            "rtt_start": self._rtt_start,
            "rtt_read": self._rtt_read,
            "rtt_write": self._rtt_write,
            "rtt_stop": self._rtt_stop,
            "read_memory": self._read_memory,
            "write_memory": self._write_memory,
            "read_variable": self._read_variable,
            "write_variable": self._write_variable,
            "read_register": self._read_register,
            "halt": self._halt,
            "resume": self._resume,
            "step": self._step,
            "set_breakpoint": self._set_breakpoint,
            "clear_breakpoint": self._clear_breakpoint,
            "read_core_registers": self._read_core_registers,
            "check_hardfault": self._check_hardfault,
            "decode_hardfault": self._decode_hardfault,
        }

    def dispatch(self, method: str, params: dict, req_id: int | None = None) -> str:
        handler = self._handlers.get(method)
        if not handler:
            return make_error(-32601, f"Method not found: {method}", req_id)
        try:
            result = handler(**params)
            if isinstance(result, bytes):
                import base64
                result = {"__bytes__": base64.b64encode(result).decode()}
            return make_response(result, req_id)
        except Exception as e:
            logger.exception("RPC error in %s", method)
            return make_error(-32603, str(e), req_id)

    # -- individual method implementations --

    def _idcode(self) -> int:
        return self._device.idcode

    def _mcu_name(self) -> str:
        return self._device.mcu_name

    def _flash(self, firmware: str, **kw) -> dict:
        return self._device.flash(firmware, **kw)

    def _erase_chip(self) -> bool:
        return self._device.erase_chip()

    def _reset(self) -> None:
        self._device.reset()

    def _rtt_start(self, addr: str | None = None, **kw) -> dict:
        return self._device.rtt_start(addr, **kw)

    def _rtt_read(self, duration: float = 10.0) -> str:
        return self._device.rtt_read(duration)

    def _rtt_write(self, data: str) -> bool:
        return self._device.rtt_write(data)

    def _rtt_stop(self) -> str:
        return self._device.rtt_stop()

    def _read_memory(self, address, size: int) -> bytes:
        return self._device.read_memory(int(address, 0) if isinstance(address, str) else address, size)

    def _write_memory(self, address, data_b64: str) -> None:
        import base64
        addr = int(address, 0) if isinstance(address, str) else address
        data = base64.b64decode(data_b64)
        self._device.write_memory(addr, data)

    def _read_variable(self, name: str) -> Any:
        return self._device.read_variable(name)

    def _write_variable(self, name: str, value: int) -> None:
        self._device.write_variable(name, value)

    def _read_register(self, name: str) -> int:
        return self._device.read_register(name)

    def _halt(self) -> dict:
        s = self._device.halt()
        return {"halted": s.halted}

    def _resume(self) -> dict:
        s = self._device.resume()
        return {"halted": s.halted}

    def _step(self) -> dict:
        s = self._device.step()
        return {"halted": s.halted}

    def _set_breakpoint(self, address: int, slot: int | None = None) -> int:
        return self._device.set_breakpoint(address, slot)

    def _clear_breakpoint(self, slot: int) -> None:
        self._device.clear_breakpoint(slot)

    def _read_core_registers(self) -> dict:
        return self._device.read_core_registers()

    def _check_hardfault(self) -> dict | None:
        return self._device.check_hardfault()

    def _decode_hardfault(self, fault_regs: dict | None = None) -> dict | None:
        report = self._device.decode_hardfault(fault_regs)
        if report is None:
            return None
        return {
            "cfsr": report.cfsr,
            "hfsr": report.hfsr,
            "cfsr_flags": report.cfsr_flags,
            "hfsr_flags": report.hfsr_flags,
            "summary": report.summary,
            "stack_frame": report.stack_frame,
            "source_locations": report.source_locations,
        }
