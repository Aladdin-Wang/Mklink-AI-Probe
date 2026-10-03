"""Passive probe identity and host-local aliases; never opens a serial port."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os


def inventory() -> list[dict]:
    from mklink.discovery import discover_mklink_command_ports
    ports = discover_mklink_command_ports()
    identities = [(p.vid, p.pid, (p.serial_number or "").strip().casefold()) for p in ports]
    counts = Counter(identities)
    aliases = load_aliases()
    probes = []
    for port, identity in zip(ports, identities):
        stable = bool(identity[2]) and counts[identity] == 1
        # Missing/duplicate serials must not silently merge two physical devices.
        material = repr(identity) if stable else repr((identity, port.location, port.device))
        probe_id = ("usb-" if stable else "local-") + hashlib.sha256(material.encode()).hexdigest()[:24]
        probes.append({"probe_id": probe_id, "port": port.device, "vid": port.vid, "pid": port.pid, "serial_number": port.serial_number or "",
                       "description": port.description, "location": port.location or "", "identity_stable": stable,
                       "alias": aliases.get(probe_id, "") if stable else ""})
    return sorted(probes, key=lambda p: (p["alias"].casefold(), p["probe_id"]))


def select_probe(selector=None, *, allow_lobby=False) -> dict:
    from mklink.runtime import RuntimeErrorResponse
    probes = inventory()
    if selector:
        key = str(selector).strip().casefold()
        matching = [p for p in probes if key in {p["probe_id"].casefold(), p["port"].casefold(), p["alias"].casefold()}]
        if len(matching) != 1:
            raise RuntimeErrorResponse("Probe selector is missing or ambiguous; run mklink probes list")
        return matching[0]
    if len(probes) == 1:
        return probes[0]
    if allow_lobby:
        return {"probe_id": "lobby", "port": None, "identity_stable": False, "alias": ""}
    raise RuntimeErrorResponse("Multiple probes attached; specify --probe ID/alias or --device-port COM port" if probes
                               else "No supported probe found; connect a probe or select a command interface explicitly")


def load_aliases() -> dict:
    from mklink.runtime import runtime_dir
    try:
        data = json.loads((runtime_dir() / "aliases.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_alias(selector: str, alias: str) -> dict:
    from mklink.runtime import RuntimeErrorResponse, runtime_dir, runtime_lock
    probe = select_probe(selector)
    if not probe["identity_stable"]:
        raise RuntimeErrorResponse("A persistent alias requires a unique USB serial number; this probe has none or a duplicate")
    alias = alias.strip()
    if len(alias) > 64 or any(ord(char) < 32 for char in alias):
        raise RuntimeErrorResponse("Alias must contain at most 64 printable characters")
    if alias and any(p["probe_id"] != probe["probe_id"] and alias.casefold() in {p["port"].casefold(), p["probe_id"].casefold()}
                     for p in inventory()):
        raise RuntimeErrorResponse("Alias conflicts with another probe's ID or port")
    with runtime_lock("aliases.lock"):
        aliases = load_aliases()
        if alias and any(name.casefold() == alias.casefold() and key != probe["probe_id"] for key, name in aliases.items()):
            raise RuntimeErrorResponse("This alias is already assigned to another probe")
        if alias:
            aliases[probe["probe_id"]] = alias
        else:
            aliases.pop(probe["probe_id"], None)
        target = runtime_dir() / "aliases.json"
        temporary = target.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(aliases, output, ensure_ascii=False, indent=2)
        temporary.replace(target)
    return {**probe, "alias": alias, "scope": "this-computer", "firmware_changed": False}
