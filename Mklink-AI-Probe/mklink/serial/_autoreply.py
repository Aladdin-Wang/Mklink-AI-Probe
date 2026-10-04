"""串口自动应答引擎。"""

from __future__ import annotations

import json
import math
import threading
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AutoReplyRule:
    match_hex: str | None = None
    match_regex: str | None = None
    match_contains: str | None = None
    reply_hex: str | None = None
    reply_ascii: str | None = None
    delay: float = 0.0
    description: str = ""


    def __post_init__(self):
        if (isinstance(self.delay, bool) or not isinstance(self.delay, (int, float))
                or not math.isfinite(self.delay) or not 0 <= self.delay <= 3600):
            raise ValueError('Auto-reply delay must be finite and in 0..3600 seconds')
        matchers = (self.match_hex, self.match_regex, self.match_contains)
        if not any(value is not None for value in matchers):
            raise ValueError('Auto-reply requires a match condition')
        for value in matchers:
            if value is not None and (not isinstance(value, str) or not 1 <= len(value.encode('utf-8')) <= 4096):
                raise ValueError('Auto-reply match must contain 1..4096 UTF-8 bytes')
        if self.match_hex is not None:
            object.__setattr__(self, 'match_hex', bytes.fromhex(self.match_hex).hex().upper())
            if not self.match_hex:
                raise ValueError('Auto-reply HEX match is empty')
        if self.match_regex is not None:
            try:
                re.compile(self.match_regex)
            except re.error as error:
                raise ValueError(f'Invalid auto-reply regex: {error}') from error
        if (self.reply_hex is None) == (self.reply_ascii is None):
            raise ValueError('Auto-reply requires exactly one reply_hex or reply_ascii')
        source = self.reply_hex if self.reply_hex is not None else self.reply_ascii
        if not isinstance(source, str) or len(source) > 16384:
            raise ValueError('Auto-reply encoded text exceeds 16384 characters')
        if not 1 <= len(_build_reply(self)) <= 4096:
            raise ValueError('Auto-reply payload must contain 1..4096 bytes')
        if not isinstance(self.description, str) or len(self.description) > 1024:
            raise ValueError('Auto-reply description exceeds 1024 characters')


def _bytes_to_ascii_safe(data: bytes) -> str:
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)


def _process_escape_sequences(s: str) -> bytes:
    result = bytearray()
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                result.append(0x0A)
                i += 2
            elif nxt == "r":
                result.append(0x0D)
                i += 2
            elif nxt == "t":
                result.append(0x09)
                i += 2
            elif nxt == "x" and i + 3 < len(s):
                result.append(int(s[i + 2 : i + 4], 16))
                i += 4
            elif nxt == "\\":
                result.append(0x5C)
                i += 2
            else:
                result.extend(s[i].encode("utf-8"))
                i += 1
        else:
            result.extend(s[i].encode("utf-8"))
            i += 1
    return bytes(result)


def _build_reply(rule: AutoReplyRule) -> bytes | None:
    if rule.reply_hex is not None:
        return bytes.fromhex(rule.reply_hex)
    if rule.reply_ascii is not None:
        return _process_escape_sequences(rule.reply_ascii)
    return None


def _matches(rule: AutoReplyRule, data: bytes) -> bool:
    if rule.match_hex is not None:
        hex_str = data.hex().upper()
        if rule.match_hex.upper() in hex_str:
            return True

    ascii_repr = _bytes_to_ascii_safe(data)

    if rule.match_regex is not None:
        if re.search(rule.match_regex, ascii_repr):
            return True

    if rule.match_contains is not None:
        if rule.match_contains in ascii_repr:
            return True

    return False


def _parse_rules(data) -> list[AutoReplyRule]:
    if not isinstance(data, list) or len(data) > 64:
        raise ValueError('Select at most 64 auto-reply rules')
    rules = []
    for item in data:
        if not isinstance(item, dict) or item.keys() - AutoReplyRule.__dataclass_fields__.keys():
            raise ValueError('Invalid or unknown auto-reply rule fields')
        rules.append(AutoReplyRule(**item))
    return rules


class AutoReplyEngine:
    def __init__(self, rules: list[AutoReplyRule] | None = None):
        self._lock = threading.Lock()
        self._rules = []
        for rule in rules or []:
            self.add_rule(rule)

    def add_rule(self, rule: AutoReplyRule) -> None:
        if not isinstance(rule, AutoReplyRule):
            raise ValueError('Expected a validated auto-reply rule')
        with self._lock:
            if len(self._rules) >= 64:
                raise ValueError('Select at most 64 auto-reply rules')
            self._rules.append(rule)

    def remove_rule(self, index: int) -> None:
        with self._lock:
            del self._rules[index]

    def load_rules(self, rules_data: list[dict]) -> None:
        rules = _parse_rules(rules_data)
        with self._lock:
            if len(self._rules) + len(rules) > 64:
                raise ValueError('Select at most 64 auto-reply rules')
            self._rules.extend(rules)

    def check(self, data: bytes) -> list[tuple[bytes, float]]:
        with self._lock:
            rules = tuple(self._rules)
        return [(_build_reply(rule), rule.delay) for rule in rules if _matches(rule, data)]

    @property
    def rules(self) -> list[AutoReplyRule]:
        with self._lock:
            return list(self._rules)


def load_rules_from_file(path: str) -> list[AutoReplyRule]:
    return _parse_rules(json.loads(Path(path).read_text(encoding='utf-8')))
