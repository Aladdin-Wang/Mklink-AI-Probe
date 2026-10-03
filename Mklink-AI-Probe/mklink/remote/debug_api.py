"""Shared, serialized register/fault snapshots and FPB breakpoint operations."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool


def _fields(body, allowed):
    if body.keys() - allowed:
        raise ValueError("Unknown arguments: " + ", ".join(sorted(body.keys() - allowed)))


def _address(value, size=4):
    if type(value) not in (int, str):
        raise ValueError("Address must be an integer or numeric string")
    address = int(value, 0) if isinstance(value, str) else value
    if address % 4 or not 0 <= address <= 0x100000000 - size:
        raise ValueError("Address must be aligned and within the 32-bit address space")
    return address


def register_snapshot(device, body):
    from mklink.peripheral_watch import load_catalog, read_item
    from mklink.registers import resolve_register
    _fields(body, {'register', 'address', 'width', 'count', 'raw'})
    name, address = body.get('register'), body.get('address')
    count, width, raw = body.get('count', 1), body.get('width', 32), body.get('raw', False)
    if type(width) is not int or width != 32 or type(count) is not int or not 1 <= count <= 1024 or type(raw) is not bool:
        raise ValueError("Register reads require width=32 and count=1..1024")
    if bool(name) == (address is not None) or (name is not None and not isinstance(name, str)):
        raise ValueError("Specify exactly one register name or address")
    catalog = load_catalog(device._project_root)
    if catalog:
        if count != 1 or raw or address is not None:
            raise ValueError("Catalog reads take one named register/field; use read-ram for explicit raw memory")
        item = catalog.resolve(name)
        value = read_item(device, item)
        return {'name': item.name, 'address': item.address, 'values': [value], 'data_hex': value.to_bytes(4, 'little').hex()}
    reg = resolve_register(name if name else hex(_address(address, count * 4)))
    _address(reg.address, count * 4)
    if name and not name.strip().lower().startswith('0x'):
        # Preserve Device's architecture guard and authoritative catalog rules.
        data = device.read_register(name).to_bytes(4, 'little')
        if count > 1:
            data += device.read_memory(reg.address + 4, (count - 1) * 4)
    else:
        data = device.read_memory(reg.address, count * 4)
    if len(data) != count * 4:
        raise RuntimeError("Incomplete register snapshot")
    return {'name': reg.name, 'address': reg.address,
            'values': [int.from_bytes(data[i:i+4], 'little') for i in range(0, len(data), 4)],
            'data_hex': data.hex()}


def fault_snapshot(device, body):
    from mklink.hardfault import FAULT_REGISTERS, addr2line, format_hardfault_report, parse_exception_stack_frame
    from mklink.registers import resolve_register
    _fields(body, {'sp'})
    sp = _address(body['sp'], 32) if body.get('sp') is not None else None
    device._require_cortex_m_debug()
    values = {}
    for name in FAULT_REGISTERS:
        # Architectural registers must not depend on vendor SVD contents.
        data = device.read_memory(resolve_register(name).address, 4)
        if len(data) != 4:
            raise RuntimeError("Incomplete fault register snapshot: " + name)
        values[name] = int.from_bytes(data, 'little')
    frame, locations = None, {}
    if sp is not None:
        data = device.read_memory(sp, 32)
        if len(data) != 32:
            raise RuntimeError("Incomplete exception stack frame")
        frame = parse_exception_stack_frame(data)
        if device._axf:
            locations = addr2line(device._axf, frame['pc'], frame['lr'],
                                 backend=device._elf_backend, project_root=device._project_root)
    return {'registers': values, 'frame': frame, 'locations': locations,
            'report': format_hardfault_report(values, frame=frame, locations=locations),
            'halt_requested': False}


def breakpoints(device, body):
    from mklink import debug_control as debug
    _fields(body, {'action', 'target', 'slot'})
    action, target, slot = body.get('action'), body.get('target'), body.get('slot')
    if action not in {'status', 'list', 'set', 'clear', 'clear_all'}:
        raise ValueError("Unknown breakpoint action")
    if (action == 'set') != (isinstance(target, str) and bool(target.strip())):
        raise ValueError("Only set requires a target address or function")
    if action != 'set' and target is not None:
        raise ValueError("Only set accepts a target")
    if slot is not None and (type(slot) is not int or slot < 0):
        raise ValueError("Slot must be a nonnegative integer")
    if (action == 'clear' and slot is None) or (action not in {'set', 'clear'} and slot is not None):
        raise ValueError("Only set/clear accepts a slot; clear requires one")
    address = None
    if action == 'set':
        if target.lower().startswith('0x'):
            address = int(target, 16)
        else:
            if not device._axf:
                raise ValueError("Load an AXF in the shared backend to resolve a function")
            address = debug.resolve_function_address(device._axf, target, backend=device._elf_backend,
                                                     project_root=device._project_root)
            if address is None:
                raise ValueError("Function not found: " + target)
            address &= ~1  # ELF Thumb function symbols may carry bit zero.
        if address % 2 or not 0 <= address < 0x20000000:
            raise ValueError("FPBv1 requires an even code address below 0x20000000")
    device._require_cortex_m_debug()
    if debug._read_u32(device._bridge, debug.FP_CTRL) >> 28:
        raise ValueError("Shared breakpoints currently support FPBv1 only")
    state = debug.read_debug_state(device._bridge)
    if slot is not None and slot >= state.num_breakpoints:
        raise ValueError("Breakpoint slot is out of range")
    if action in {'list', 'status'}:
        return asdict(state)
    if action == 'set':
        occupied = {bp.index for bp in state.breakpoints}
        if slot is None:
            slot = next((i for i in range(state.num_breakpoints) if i not in occupied), None)
        if slot is None or slot in occupied:
            raise ValueError("No free selected breakpoint slot; clear it explicitly before replacing")
        slot = device.set_breakpoint(address, slot)
        # Readback detects silent bridge failures, without replaying writes.
        actual = debug._read_u32(device._bridge, debug.FP_COMP_BASE + slot * 4)
        expected = (address & 0x1ffffffc) | (0x80000000 if address & 2 else 0x40000000) | 1
        if actual != expected or not debug._read_u32(device._bridge, debug.FP_CTRL) & debug.FP_CTRL_ENABLE:
            raise RuntimeError("Breakpoint verification failed; inspect status before another operation")
        return {'action': action, 'slot': slot, 'address': address, 'verified': True}
    slots = [slot] if action == 'clear' else [bp.index for bp in state.breakpoints]
    for index in slots:
        device.clear_breakpoint(index)
        if debug._read_u32(device._bridge, debug.FP_COMP_BASE + index * 4) != 0:
            raise RuntimeError("Breakpoint clear verification failed; inspect status before another operation")
    return {'action': action, 'cleared': slots, 'verified': True}


def memory_dump_stream(device, body):
    from mklink.dump_memory import capture_dump_stream
    _fields(body, {'regions', 'period', 'frames', 'duration', 'speed_profile'})
    return capture_dump_stream(device, body.get('regions'), period=body.get('period', 0.0),
                               frames=body.get('frames', 1), duration=body.get('duration', 2.0),
                               speed_profile=body.get('speed_profile'))


def memory_dump(device, body):
    from mklink.dump_memory import capture_memory
    _fields(body, {'regions', 'sample_count', 'timeout', 'speed_profile'})
    return capture_memory(device, body.get('regions'), sample_count=body.get('sample_count', 1),
                          timeout=body.get('timeout', 10.0), speed_profile=body.get('speed_profile'))


def memory_regions(device, body):
    from mklink.memory_access import read_memory_regions
    _fields(body, {'regions'})
    return read_memory_regions(device, body.get('regions'))


def peripheral_read(device, body):
    from mklink.peripheral_watch import load_catalog, read_item
    names = _peripheral_names(body, {'names'})
    catalog = load_catalog(device._project_root)
    if catalog is None:
        raise ValueError('Select a peripheral catalog first')
    items = [catalog.resolve(name) for name in names]
    return {'values': {item.name: read_item(device, item) for item in items}}


def _peripheral_names(body, allowed):
    _fields(body, allowed)
    names = body.get('names')
    if (not isinstance(names, list) or not 1 <= len(names) <= 64
            or any(not isinstance(name, str) or not name.strip() or len(name) > 256 for name in names)):
        raise ValueError('Select 1..64 peripheral register or field names')
    if len({name.strip().replace('->', '.').casefold() for name in names}) != len(names):
        raise ValueError('Peripheral channel names must be unique')
    return names


def peripheral_capture(device, body):
    import math
    names = _peripheral_names(body, {'names', 'duration', 'period'})
    duration, period = body.get('duration', 1.0), body.get('period', .01)
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in (duration, period)):
        raise ValueError('Capture duration and period must be finite numbers')
    if not 0 < duration <= 30 or period <= 0:
        raise ValueError('Capture requires 0 < duration <= 30 and period > 0')
    return device.capture_peripherals(names, duration=duration, period=period)


def create_debug_router(state, lease):
    router = APIRouter(prefix='/api/device')

    def add(path, operation):
        async def endpoint(body: dict):
            device = state.get('device')
            if not device or not device.connected:
                raise HTTPException(400, 'Device not connected')
            async with lease(state, path):
                try:
                    return await run_in_threadpool(operation, device, body)
                except (ValueError, KeyError) as error:
                    raise HTTPException(422, str(error)) from error
                except Exception as error:
                    raise HTTPException(500, str(error)) from error
        router.add_api_route('/' + path, endpoint, methods=['POST'], name=path)

    add('dump-memory', memory_dump)
    add('dump-memory/capture', memory_dump_stream)
    add('read-memory-regions', memory_regions)
    add('register-snapshot', register_snapshot)
    add('fault-snapshot', fault_snapshot)
    add('breakpoints', breakpoints)
    add('peripherals/read', peripheral_read)
    add('peripherals/capture', peripheral_capture)
    return router
