"""Bounded flush writes shared by Device, the runtime API and MCP.

The caller owns the existing hardware lease. This module never opens ports,
retries writes, changes clocks or stops another client's stream.
"""
from mklink.remote.stream_protocol import canonical_memory_address

MAX_REGIONS = 8
MAX_BYTES = 12 * 1024


def validate_writes(writes):
    if not isinstance(writes, list) or not 1 <= len(writes) <= MAX_REGIONS:
        raise ValueError('writes must be non-empty and contain at most 8 regions')
    parsed = []
    total = 0
    for item in writes:
        if not isinstance(item, dict) or set(item) != {'address', 'data_hex'}:
            raise ValueError('Each write must contain only address and data_hex')
        address, data_hex = item['address'], item['data_hex']
        if type(address) is not int or not 0 <= address <= 0xffffffff:
            raise ValueError('address must be a 32-bit integer')
        if not isinstance(data_hex, str) or len(data_hex) > MAX_BYTES * 3:
            raise ValueError('data_hex must be a bounded hex string')
        try:
            data = bytes.fromhex(data_hex)
        except ValueError as error:
            raise ValueError('data_hex must be valid hex') from error
        if not 1 <= len(data) <= MAX_BYTES:
            raise ValueError('size must be between 1 and 12288 bytes')
        if address + len(data) > 0x100000000:
            raise ValueError('Write exceeds the 32-bit address space')
        total += len(data)
        if total > MAX_BYTES:
            raise ValueError('total write data must not exceed 12288 bytes')
        if any(address < prior + len(payload) and prior < address + len(data)
               for prior, payload in parsed):
            raise ValueError('Write regions must not overlap')
        parsed.append((address, data))
    return parsed


def parse_flush_response(response):
    # Silent completion and command echoes are the firmware success contract.
    # An ambiguous diagnostic is not proof of success, including bare flush fail.
    if not isinstance(response, str):
        return False, 'Invalid flush response'
    lines = [line.strip() for line in response.splitlines()
             if line.strip() and not line.strip().startswith(('cmd.', '->'))]
    return (False, '\n'.join(lines)[:256]) if lines else (True, '')


def flush_command(batch):
    items = [f'({canonical_memory_address(address)}, {_flush_data_expr(data)[0]})'
             for address, data in batch]
    return "cmd.flush_memory([" + ', '.join(items) + "])"


_FLUSH_CMD_MAX = 230          # PIKA_LINE_BUFF safe bound
_FLUSH_NONREPEAT_CHUNK = 30   # ~180 chars expanded, headroom under 230


def _flush_data_expr(data: bytes) -> tuple[str, bool]:
    """Build the PikaScript data expression for one flush tuple.

    All-same-byte payloads use the short ``bytes([0xVV])*N`` form (carries up
    to 12 KiB in one command); anything else expands to a literal (caller
    pre-splits these into ≤30B chunks). Returns (expression, is_short_form).
    """
    if data and all(b == data[0] for b in data):
        return f"bytes([0x{data[0]:02X}])*{len(data)}", True
    literal = ", ".join(f"0x{b:02X}" for b in data)
    return f"bytes([{literal}])", False


def plan_flush_batches(
    writes: list[tuple[int, bytes]],
) -> list[list[tuple[int, bytes]]]:
    """Split (addr, data) writes into batches whose command string stays
    under _FLUSH_CMD_MAX. Non-repeat payloads >30B are pre-split into 30B
    chunks; batches then greedily packed (≤8 items, ≤230 chars). Encodes the
    chunking strategy from references/flush-memory.md §5.
    """
    items: list[tuple[int, bytes]] = []
    for addr, data in writes:
        if not data:
            continue
        _, is_short = _flush_data_expr(data)
        if is_short:
            items.append((addr, data))
        else:
            for off in range(0, len(data), _FLUSH_NONREPEAT_CHUNK):
                items.append((addr + off, data[off:off + _FLUSH_NONREPEAT_CHUNK]))

    batches: list[list[tuple[int, bytes]]] = []
    cur: list[tuple[int, bytes]] = []
    cur_len = len("cmd.flush_memory([])")
    for addr, data in items:
        tup = f"({canonical_memory_address(addr)}, {_flush_data_expr(data)[0]})"
        add = len(tup) + (2 if cur else 0)
        if cur and (cur_len + add > _FLUSH_CMD_MAX or len(cur) >= 8):
            batches.append(cur)
            cur = []
            cur_len = len("cmd.flush_memory([])")
            add = len(tup)
        cur.append((addr, data))
        cur_len += add
    if cur:
        batches.append(cur)
    return batches


def execute_flush(device, parsed, *, verify=False):
    from mklink.observe_bridge import memory_flush_facts, observe_operation
    if type(verify) is not bool:
        raise ValueError('verify must be boolean')
    with observe_operation(
        "memory.flush",
        capability="target.memory",
        action_class="emit",
    ) as observation:
        total = sum(len(data) for _, data in parsed)
        batches = plan_flush_batches(parsed)
        results = []
        try:
            for bi, batch in enumerate(batches):
                resp = device._bridge.send_command(flush_command(batch), timeout=10.0)
                ok, msg = parse_flush_response(resp)
                if ok and verify:
                    for address, data in batch:
                        for offset in range(0, len(data), 4096):
                            expected = data[offset:offset + 4096]
                            if device.read_memory(address + offset, len(expected)) != expected:
                                ok, msg = False, 'Readback mismatch; write was not retried'
                                break
                        if not ok:
                            break
                results.append({
                    "batch": bi + 1, "items": len(batch),
                    "bytes": sum(len(d) for _, d in batch),
                    "ok": ok, "message": msg,
                })
                if not ok:
                    break
        except Exception:
            successful_batches = sum(result["ok"] for result in results)
            facts = memory_flush_facts(
                canonical_memory_address(parsed[0][0]) if parsed else None,
                total_bytes=total,
                region_count=len(parsed),
                batch_count=len(batches),
                successful_batches=successful_batches,
                failed_batches=1,
            )
            observation.fail("memory_flush_transport_failed", facts=facts)
            raise
        response = {
            "ok": len(results) == len(batches) and all(r["ok"] for r in results),
            "batches": len(batches),
            "total_bytes": total,
            "results": results,
        }
        failed_batches = sum(not result["ok"] for result in results)
        facts = memory_flush_facts(
            canonical_memory_address(parsed[0][0]) if parsed else None,
            total_bytes=total,
            region_count=len(parsed),
            batch_count=len(batches),
            successful_batches=sum(result["ok"] for result in results),
            failed_batches=failed_batches,
        )
        if response["ok"]:
            observation.complete(facts=facts)
        else:
            observation.fail("memory_flush_failed", facts=facts)
        if verify:
            response["verified"] = response["ok"]
        return response
