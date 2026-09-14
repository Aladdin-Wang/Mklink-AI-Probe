"""Bounded CMSIS-SVD inheritance/array expansion shared by all entry points."""

from __future__ import annotations
import copy
import re
import xml.etree.ElementTree as ET

PROPERTIES = ("size", "access", "resetValue", "resetMask", "readAction")
COLLECTIONS = {"peripherals", "registers", "fields"}
MAX_EXPANDED = 250000


def integer(text):
    text = text.strip()
    return int(text[1:], 2) if text.startswith("#") else int(text, 0)


def dimensions(node):
    count = integer(node.findtext("dim", "1"))
    if not 1 <= count <= 4096:
        raise ValueError("SVD dimension exceeds supported limit")
    index = node.findtext("dimIndex")
    if index is None:
        indices = list(map(str, range(count)))
    elif "," in index:
        indices = [x.strip() for x in index.split(",")]
    elif re.fullmatch(r"\d+-\d+", index):
        first, last = map(int, index.split("-"))
        if last - first + 1 != count:
            raise ValueError("SVD dimension/index mismatch")
        indices = list(map(str, range(first, last + 1)))
    elif re.fullmatch(r"[A-Za-z]-[A-Za-z]", index):
        indices = list(map(chr, range(ord(index[0]), ord(index[2]) + 1)))
    else:
        indices = [index]
    if len(indices) != count:
        raise ValueError("SVD dimension/index mismatch")
    name = node.findtext("name", "")
    if count > 1 and "%s" not in name:
        raise ValueError("SVD array name needs %s")
    step = integer(node.findtext("dimIncrement", "0"))
    if count > 1 and step <= 0:
        raise ValueError("SVD array increment must be positive")
    return [(name.replace("%s", index), i * step) for i, index in enumerate(indices)]


def normalize(root):
    """Resolve references before flattening; preserve register-level read actions."""
    pending = [(root, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > 64:
            raise ValueError("SVD nesting limit exceeded")
        pending.extend((child, depth + 1) for child in node)
    root = copy.deepcopy(root)
    lookup, paths = {}, {}

    def index(node, prefix=""):
        name = node.findtext("name")
        path = (
            f"{prefix}.{name}".strip(".") if name and node.tag != "device" else prefix
        )
        if node.tag in {"peripheral", "register", "cluster", "field"}:
            if path in lookup:
                raise ValueError(f"Duplicate SVD declaration: {path}")
            lookup[path], paths[id(node)] = node, path
        for child in node:
            if child.tag in COLLECTIONS or child.tag in {
                "peripheral",
                "register",
                "cluster",
                "field",
            }:
                index(child, path)

    index(root)
    cache, active = {}, set()

    def resolve(node):
        key = id(node)
        if key in cache:
            return copy.deepcopy(cache[key])
        if key in active:
            raise ValueError("Cyclic SVD derivedFrom")
        if len(active) >= 64:
            raise ValueError("SVD inheritance limit exceeded")
        active.add(key)
        ref = node.get("derivedFrom")
        if ref:
            scope = paths[key].rsplit(".", 1)[0] if "." in paths[key] else ""
            target = lookup.get(f"{scope}.{ref}".strip("."))
            if target is None:
                target = lookup.get(ref)
            if target is None or target.tag != node.tag:
                raise ValueError(f"Unknown SVD derivedFrom: {ref}")
            result = resolve(target)
            for child in node:
                replacement = (
                    resolve(child) if id(child) in paths else expand_children(child)
                )
                old_collection = (
                    result.find(child.tag) if child.tag in COLLECTIONS else None
                )
                if old_collection is not None:
                    for entry in replacement:
                        for old in list(old_collection):
                            if old.tag == entry.tag and old.findtext(
                                "name"
                            ) == entry.findtext("name"):
                                old_collection.remove(old)
                        old_collection.append(entry)
                    continue
                for old in result.findall(child.tag):
                    if child.tag in {"register", "cluster", "field"} and old.findtext(
                        "name"
                    ) != child.findtext("name"):
                        continue
                    result.remove(old)
                result.append(replacement)
        else:
            result = expand_children(node)
        result.attrib.pop("derivedFrom", None)
        active.remove(key)
        cache[key] = result
        return copy.deepcopy(result)

    def expand_children(node):
        new = copy.copy(node)
        new[:] = [
            resolve(c)
            if c.tag in {"peripheral", "register", "cluster", "field"}
            else expand_children(c)
            for c in node
        ]
        return new

    root = expand_children(root)
    defaults = {k: root.findtext(k) for k in PROPERTIES if root.findtext(k) is not None}
    expanded = 0

    def props(node, parent):
        return {
            **parent,
            **{k: node.findtext(k) for k in PROPERTIES if node.findtext(k) is not None},
        }

    def set_text(node, tag, value):
        child = node.find(tag)
        if child is None:
            child = ET.SubElement(node, tag)
        child.text = str(value)

    def strip_dim(node):
        for child in list(node):
            if child.tag.startswith("dim"):
                node.remove(child)

    def flatten(container, inherited, prefix="", base=0):
        nonlocal expanded
        for node in container:
            if node.tag not in {"cluster", "register"}:
                continue
            current = props(node, inherited)
            for name, step in dimensions(node):
                expanded += 1
                if expanded > MAX_EXPANDED:
                    raise ValueError("SVD expansion limit exceeded")
                offset = base + integer(node.findtext("addressOffset", "0")) + step
                if node.tag == "cluster":
                    yield from flatten(node, current, prefix + name + ".", offset)
                else:
                    r = copy.deepcopy(node)
                    strip_dim(r)
                    set_text(r, "name", prefix + name)
                    set_text(r, "addressOffset", offset)
                    for k, v in current.items():
                        set_text(r, k, v)
                    fields = r.find("fields")
                    if fields is not None:
                        result = []
                        for f in fields:
                            for fname, bitstep in dimensions(f):
                                expanded += 1
                                if expanded > MAX_EXPANDED:
                                    raise ValueError("SVD expansion limit exceeded")
                                new = copy.deepcopy(f)
                                strip_dim(new)
                                set_text(new, "name", fname)
                                if new.find("bitRange") is not None:
                                    hi, lo = map(
                                        int,
                                        re.findall(r"\d+", new.findtext("bitRange")),
                                    )
                                elif new.find("lsb") is not None:
                                    lo = integer(new.findtext("lsb"))
                                    hi = integer(new.findtext("msb"))
                                else:
                                    lo = integer(new.findtext("bitOffset", "0"))
                                    hi = lo + integer(new.findtext("bitWidth", "0")) - 1
                                for tag in ("bitRange", "lsb", "msb"):
                                    for c in new.findall(tag):
                                        new.remove(c)
                                set_text(new, "bitOffset", lo + bitstep)
                                set_text(new, "bitWidth", hi - lo + 1)
                                result.append(new)
                        fields[:] = result
                    yield r

    peripherals = root.find("peripherals")
    if peripherals is None:
        raise ValueError("SVD has no peripherals")
    output = []
    for p in peripherals:
        for name, step in dimensions(p):
            current = copy.deepcopy(p)
            strip_dim(current)
            set_text(current, "name", name)
            set_text(
                current, "baseAddress", integer(p.findtext("baseAddress", "0")) + step
            )
            regs = current.find("registers")
            if regs is not None:
                regs[:] = list(flatten(regs, props(current, defaults)))
            output.append(current)
    peripherals[:] = output
    return root
