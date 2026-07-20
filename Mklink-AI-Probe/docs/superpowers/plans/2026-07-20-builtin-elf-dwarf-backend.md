# Built-in ELF and DWARF Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every AXF/ELF-dependent MKLink feature use bundled `pyelftools` by default, while invoking local GNU `readelf` and `addr2line` only after explicit external-backend selection.

**Architecture:** Add a small backend-selection/service layer with separate built-in and external adapters. The built-in adapter normalizes ELF symbols, sections, DWARF records, and line programs into the existing `DwarfInfo` and public result shapes; current GNU text parsers remain isolated in the explicit external adapter. Device, CLI, MCP, remote API, desktop status, packaging, and AI skill documentation consume backend capabilities instead of gating AXF support on `readelf_available`.

**Tech Stack:** Python 3.9+, `pyelftools==0.32`, pytest, FastAPI/MCP, Vue 3/Vitest, PyInstaller, Tauri v2, standard NSIS.

---

## File Structure

- Create `mklink/elf_backend.py`: backend names, configuration precedence, normalized symbol/section records, backend protocol, service entry points, and capability status.
- Create `mklink/elf_builtin.py`: pure-Python ELF/DWARF/line-program implementation using `pyelftools`.
- Create `mklink/elf_external.py`: explicit GNU adapter that owns subprocess execution and feeds the existing GNU text parsers.
- Modify `mklink/dwarf_parser.py`: retain the normalized DWARF model and GNU text parser, delegate loading, and make cache entries backend/version aware.
- Modify `mklink/symbol_parser.py`: retain GNU text parsing and name-filter helpers; consumers stop running subprocesses themselves.
- Modify `mklink/memmap.py`, `mklink/hardfault.py`, `mklink/debug_control.py`, `mklink/superwatch.py`, and `mklink/vofa_viewer.py`: use the ELF service instead of direct GNU discovery or subprocess calls.
- Modify `mklink/device.py`, `mklink/cli.py`, `mklink/mcp_server.py`, and `mklink/remote/api.py`: propagate explicit backend selection and report built-in capabilities.
- Modify `mklink/toolchain.py`, `mklink/project_config.py`, and `mklink/_deps.py`: keep external tool discovery diagnostic-only and add validated backend configuration.
- Modify `pyproject.toml`, `skills/tauri-gui-builder/scripts/build.py`, `gui/src-tauri/resources/THIRD-PARTY-NOTICES.txt`, and builder tests: bundle and disclose `pyelftools`.
- Modify `SKILL.md`, `references/install.md`, and `references/commands-memory.md`: make the AI workflow built-in-first and external-only-on-request.
- Create focused Python tests under `_maintainer/testing/tests/`; modify GUI tests only where status response shapes change.

The user explicitly relaxed mandatory RED and per-small-change commits. The execution should still add meaningful regression tests before or alongside risky parser changes, but may group tightly related tests and implementation into the commits below.

### Task 1: Backend Selection and Capability Contract

**Files:**
- Create: `mklink/elf_backend.py`
- Modify: `mklink/toolchain.py`
- Modify: `mklink/project_config.py`
- Modify: `pyproject.toml`
- Create: `_maintainer/testing/tests/test_elf_backend.py`
- Modify: `_maintainer/testing/tests/test_cli_help.py`

- [ ] **Step 1: Add backend-selection regression tests**

Cover default built-in selection, explicit argument precedence, environment and project configuration, invalid values, and the rule that configured or discoverable GNU paths do not activate external mode.

```python
def test_backend_defaults_to_builtin_even_when_readelf_exists(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mklink.toolchain.resolve_readelf", lambda: r"C:\\tools\\readelf.exe")
    assert resolve_elf_backend(project_root=tmp_path) == "builtin"


def test_backend_requires_explicit_external_selection(monkeypatch, tmp_path):
    write_toolchain_config(tmp_path, {"readelf": "C:/tools/readelf.exe"})
    assert resolve_elf_backend(project_root=tmp_path) == "builtin"
    write_toolchain_config(tmp_path, {"elf_backend": "external"})
    assert resolve_elf_backend(project_root=tmp_path) == "external"
```

- [ ] **Step 2: Add the dependency and backend contract**

Pin the tested pure-Python parser and define stable records and backend operations.

```toml
dependencies = ["pyserial", "pymodbus>=3.0", "pyelftools==0.32"]
```

```python
ELF_BACKENDS = frozenset({"builtin", "external"})


@dataclass(frozen=True)
class ElfSymbol:
    name: str
    address: int
    size: int
    kind: str
    binding: str
    visibility: str
    section: int | str


@dataclass(frozen=True)
class ElfSection:
    name: str
    address: int
    size: int
    flags: int
    section_type: str


class ElfBackend(Protocol):
    name: str
    parser_version: str

    def symbols(self, source: str) -> list[ElfSymbol]: ...
    def sections(self, source: str) -> list[ElfSection]: ...
    def dwarf_info(self, source: str) -> DwarfInfo: ...
    def source_locations(self, source: str, addresses: Iterable[int]) -> dict[int, str]: ...
```

Implement `resolve_elf_backend(explicit=None, project_root=None)`, `get_elf_backend(...)`, and `elf_status(...)`. Use explicit argument, `MKLINK_ELF_BACKEND`, `.mklink/toolchain.json`, then `builtin`. Reject any value outside `builtin|external`.

- [ ] **Step 3: Preserve GNU discovery without allowing implicit activation**

Keep `resolve_readelf`, `resolve_addr2line`, and `toolchain.status()` for external diagnostics. Extend status with fields such as `elf_backend`, `builtin_elf_available`, and `external_elf_available`; do not change backend selection based on PATH probing.

- [ ] **Step 4: Run focused tests and commit**

Run:

```powershell
python -m pytest _maintainer/testing/tests/test_elf_backend.py _maintainer/testing/tests/test_cli_help.py -q
```

Expected: all selected tests pass and CLI help exposes only validated `builtin|external` choices where added later.

Commit:

```powershell
git add pyproject.toml mklink/elf_backend.py mklink/toolchain.py mklink/project_config.py _maintainer/testing/tests/test_elf_backend.py _maintainer/testing/tests/test_cli_help.py
git commit -m "feat: define built-in ELF backend selection"
```

### Task 2: Built-in ELF Symbols and Sections

**Files:**
- Create: `mklink/elf_builtin.py`
- Modify: `mklink/elf_backend.py`
- Create: `_maintainer/testing/tests/test_elf_builtin.py`
- Modify: `_maintainer/testing/tests/test_symbol_catalog.py`

- [ ] **Step 1: Add symbol and section normalization tests**

Use small fake `ELFFile`, symbol-table, symbol, and section objects so automated tests do not commit firmware or require a compiler. Cover object/function kinds, undefined symbols, visibility, non-ASCII names, and section flags.

```python
def test_builtin_symbols_normalize_defined_objects_and_functions(fake_elf):
    backend = BuiltinElfBackend(elf_factory=lambda _stream: fake_elf)
    symbols = backend.symbols("firmware.axf")
    assert [(item.name, item.kind, item.address, item.size) for item in symbols] == [
        ("g_counter", "object", 0x20000010, 4),
        ("HardFault_Handler", "function", 0x08000101, 12),
    ]


def test_builtin_sections_preserve_alloc_write_exec_flags(fake_elf):
    sections = BuiltinElfBackend(elf_factory=lambda _stream: fake_elf).sections("firmware.axf")
    assert sections[0] == ElfSection(".text", 0x08000000, 0x120, 0x6, "SHT_PROGBITS")
```

- [ ] **Step 2: Implement safe ELF opening and normalized enumeration**

Open each source in binary mode, instantiate `ELFFile`, validate ELF class and machine without restricting supported producers unnecessarily, and raise a dedicated `ElfParseError` for invalid input.

```python
class BuiltinElfBackend:
    name = "builtin"
    parser_version = "pyelftools-0.32-v1"

    def symbols(self, source: str) -> list[ElfSymbol]:
        with open(source, "rb") as stream:
            elf = ELFFile(stream)
            symtab = elf.get_section_by_name(".symtab")
            if symtab is None:
                return []
            return [item for symbol in symtab.iter_symbols()
                    if (item := _normalize_symbol(symbol)) is not None]
```

Normalize `STT_OBJECT` to `object`, `STT_FUNC` to `function`, skip `SHN_UNDEF`, and retain Thumb-bit addresses in the symbol record. Section enumeration must use ELF header values, not formatted strings.

- [ ] **Step 3: Expose service helpers**

Add `list_elf_symbols(source, backend=None, project_root=None)` and `list_elf_sections(...)` to `elf_backend.py`. Add exact-name and regex function helpers over normalized symbols so later consumers share one implementation.

- [ ] **Step 4: Run focused tests and commit**

Run:

```powershell
python -m pytest _maintainer/testing/tests/test_elf_builtin.py _maintainer/testing/tests/test_symbol_catalog.py -q
```

Expected: symbol/section tests and existing catalog safety tests pass.

Commit:

```powershell
git add mklink/elf_backend.py mklink/elf_builtin.py _maintainer/testing/tests/test_elf_builtin.py _maintainer/testing/tests/test_symbol_catalog.py
git commit -m "feat: parse ELF symbols and sections internally"
```

### Task 3: Built-in DWARF Normalization and Backend-aware Cache

**Files:**
- Modify: `mklink/elf_builtin.py`
- Modify: `mklink/dwarf_parser.py`
- Modify: `_maintainer/testing/tests/test_dwarf_parser.py`
- Modify: `_maintainer/testing/tests/test_elf_builtin.py`
- Modify: `_maintainer/testing/tests/test_symbol_catalog.py`

- [ ] **Step 1: Add DWARF conversion regression coverage**

Create fake CU/DIE/attribute objects that exercise DWARF reference following and forms without requiring binary fixtures. Cover base types, typedef/qualifier chains, pointer sizes, duplicate and anonymous records, structs/unions, enums, fixed multidimensional arrays, member offsets, fixed `DW_OP_addr`, unique symbol-table address completion, and rejected dynamic locations.

```python
def test_builtin_dwarf_uses_fixed_location_and_symbol_completion(fake_dwarf_elf):
    info = BuiltinElfBackend(elf_factory=lambda _stream: fake_dwarf_elf).dwarf_info("firmware.axf")
    assert info.variables["fixed"].address == 0x20000020
    assert info.variables["linked_only"].address == 0x20000024
    assert info.variables["optimized_local"].address is None


def test_builtin_dwarf_preserves_multidimensional_array(fake_dwarf_elf):
    array = get_array_type(info, info.variables["matrix"].type_offset)
    assert array.dimensions == (2, 3)
    assert array.size == 24
```

- [ ] **Step 2: Convert pyelftools DIEs into the existing model**

Use `die.get_DIE_from_attribute("DW_AT_type")` to follow producer-specific reference forms. Decode byte-valued names safely. Accept constant member locations and simple expression locations only when their operation sequence has an unambiguous fixed meaning.

```python
def _fixed_address(attr, structs) -> int | None:
    if attr.form not in {"DW_FORM_exprloc", "DW_FORM_block", "DW_FORM_block1", "DW_FORM_block2", "DW_FORM_block4"}:
        return None
    operations = DWARFExprParser(structs).parse_expr(attr.value)
    if len(operations) == 1 and operations[0].op_name == "DW_OP_addr":
        return int(operations[0].args[0])
    return None
```

Ignore location lists, frame/register-relative expressions, dynamic bounds, and ambiguous expressions. Complete a missing fixed address only when the exact variable or linkage name maps to one unique defined object symbol.

- [ ] **Step 3: Delegate `load_dwarf_info` and update the cache schema**

Change the public loader signature without breaking current callers:

```python
def load_dwarf_info(
    source: str,
    *,
    use_cache: bool = True,
    backend: str | None = None,
    project_root: str | None = None,
) -> DwarfInfo:
```

Resolve the effective backend first. Cache metadata must include schema version 4, backend name, parser version, resolved source path, source size, and nanosecond mtime. Cache mismatch or corruption triggers a reparse. Keep `parse_dwarf_info_output()` and its tests for the external adapter.

- [ ] **Step 4: Run focused tests and commit**

Run:

```powershell
python -m pytest _maintainer/testing/tests/test_dwarf_parser.py _maintainer/testing/tests/test_elf_builtin.py _maintainer/testing/tests/test_symbol_catalog.py -q
```

Expected: all built-in and legacy GNU-text normalization tests pass.

Commit:

```powershell
git add mklink/elf_builtin.py mklink/dwarf_parser.py _maintainer/testing/tests/test_dwarf_parser.py _maintainer/testing/tests/test_elf_builtin.py _maintainer/testing/tests/test_symbol_catalog.py
git commit -m "feat: parse DWARF types with pyelftools"
```

### Task 4: Built-in Source Lines, HardFault, and Function Lookup

**Files:**
- Modify: `mklink/elf_builtin.py`
- Modify: `mklink/elf_backend.py`
- Modify: `mklink/hardfault.py`
- Modify: `mklink/debug_control.py`
- Create: `_maintainer/testing/tests/test_elf_lineinfo.py`
- Create: `_maintainer/testing/tests/test_hardfault.py`
- Modify: `_maintainer/testing/tests/test_remote_api.py`

- [ ] **Step 1: Add line-sequence and HardFault regression tests**

Cover exact address lookup, nearest preceding row, Thumb bit clearing, end-of-sequence isolation, missing line programs, stripped files, and preservation of register/frame decoding when source lookup is unavailable.

```python
def test_line_lookup_clears_thumb_bit_and_stays_inside_sequence(fake_line_elf):
    locations = BuiltinElfBackend(elf_factory=lambda _stream: fake_line_elf).source_locations(
        "firmware.axf", [0x08000105, 0x08000200]
    )
    assert locations[0x08000105].endswith("fault.c:42")
    assert 0x08000200 not in locations


def test_hardfault_keeps_frame_when_source_lookup_is_empty(monkeypatch):
    monkeypatch.setattr("mklink.elf_backend.lookup_source_locations", lambda *_a, **_k: {})
    frame = parse_exception_stack_frame(bytes.fromhex("00" * 32))
    assert frame["pc"] == 0
```

- [ ] **Step 2: Build and query a line-program index**

For each CU, combine compilation directory, include directories, and file entries. Turn each sequence into non-overlapping `[row.address, next.address)` ranges and close it at `end_sequence.address`. Normalize lookup addresses with `address & ~1` while keeping original addresses as result keys.

- [ ] **Step 3: Route HardFault and function operations through the service**

Make `hardfault.addr2line()` a compatibility wrapper around `lookup_source_locations()`. Replace `debug_control.resolve_function_address()` and `search_functions()` subprocess parsing with normalized service helpers. Keep HardFault source decoration best-effort and never hide CFSR/HFSR or stack-frame data because line lookup failed.

- [ ] **Step 4: Run focused tests and commit**

Run:

```powershell
python -m pytest _maintainer/testing/tests/test_elf_lineinfo.py _maintainer/testing/tests/test_hardfault.py _maintainer/testing/tests/test_remote_api.py -q
```

Expected: source-line, HardFault degradation, and existing API tests pass without invoking GNU tools.

Commit:

```powershell
git add mklink/elf_builtin.py mklink/elf_backend.py mklink/hardfault.py mklink/debug_control.py _maintainer/testing/tests/test_elf_lineinfo.py _maintainer/testing/tests/test_hardfault.py _maintainer/testing/tests/test_remote_api.py
git commit -m "feat: resolve HardFault source lines internally"
```

### Task 5: Explicit GNU Adapter and CLI/Runtime Consumer Migration

**Files:**
- Create: `mklink/elf_external.py`
- Modify: `mklink/elf_backend.py`
- Modify: `mklink/cli.py`
- Modify: `mklink/memmap.py`
- Modify: `mklink/superwatch.py`
- Modify: `mklink/vofa_viewer.py`
- Modify: `mklink/typeinfo.py`
- Modify: `mklink/watch.py`
- Modify: `_maintainer/testing/tests/test_elf_backend.py`
- Modify: `_maintainer/testing/tests/test_watch_map_fallback.py`
- Modify: `_maintainer/testing/tests/test_vofa_streaming.py`
- Modify: `_maintainer/testing/tests/test_rtt_superwatch_streaming.py`
- Modify: `_maintainer/testing/tests/test_cli_help.py`

- [ ] **Step 1: Add explicit-external and no-subprocess-by-default tests**

Patch `subprocess.run` to fail if called in built-in mode. Verify symbols, memmap, SuperWatch symbol sizes, VOFA name resolution, function lookup, and source lookup stay internal. Separately verify `backend="external"` invokes the configured GNU executable and normalizes its output.

```python
def test_builtin_consumers_never_spawn_gnu(monkeypatch, fake_builtin_backend):
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: pytest.fail("unexpected subprocess"))
    monkeypatch.setattr("mklink.elf_backend.get_elf_backend", lambda **_k: fake_builtin_backend)
    assert resolve_variable_names(["g_counter", "uint32_t"], "firmware.axf") == [
        "0x20000010", "uint32_t"
    ]


def test_external_backend_runs_configured_readelf(monkeypatch, tmp_path):
    backend = ExternalElfBackend(readelf="readelf.exe", addr2line="addr2line.exe")
    symbols = backend.symbols("firmware.axf")
    assert symbols[0].name == "g_counter"
```

- [ ] **Step 2: Isolate current GNU behavior in `elf_external.py`**

Use `require_readelf()` only inside external symbol/section/DWARF operations and `require_addr2line()` only inside external source lookup. Feed `parse_readelf_output`, `parse_readelf_functions`, `parse_section_headers`, and `parse_dwarf_info_output`; preserve existing timeouts and actionable missing-tool errors.

- [ ] **Step 3: Migrate all direct consumers**

Replace direct GNU calls in:

- `_cli_symbols` and CLI breakpoint function search.
- `memmap.analyze_memmap`.
- `superwatch._symbol_size_lookup`.
- `vofa_viewer.resolve_variable_names`.
- `typeinfo`, `watch`, and any helper that calls `load_dwarf_info` without propagating backend/project context.

Add a reusable CLI argument:

```python
def _add_elf_backend_arg(parser):
    parser.add_argument(
        "--elf-backend",
        choices=("builtin", "external"),
        help="ELF/DWARF parser backend; default: builtin",
    )
```

Attach it to `symbols`, `typeinfo`, `memmap`, `watch`, `superwatch`, `vofa`, `hardfault`, and named breakpoint commands. Pass the value explicitly; absence retains config/default resolution.

- [ ] **Step 4: Run focused tests and commit**

Run:

```powershell
python -m pytest _maintainer/testing/tests/test_elf_backend.py _maintainer/testing/tests/test_watch_map_fallback.py _maintainer/testing/tests/test_vofa_streaming.py _maintainer/testing/tests/test_rtt_superwatch_streaming.py _maintainer/testing/tests/test_cli_help.py -q
```

Expected: built-in consumer tests show zero GNU subprocess calls; explicit external adapter tests pass.

Commit:

```powershell
git add mklink/elf_external.py mklink/elf_backend.py mklink/cli.py mklink/memmap.py mklink/superwatch.py mklink/vofa_viewer.py mklink/typeinfo.py mklink/watch.py _maintainer/testing/tests/test_elf_backend.py _maintainer/testing/tests/test_watch_map_fallback.py _maintainer/testing/tests/test_vofa_streaming.py _maintainer/testing/tests/test_rtt_superwatch_streaming.py _maintainer/testing/tests/test_cli_help.py
git commit -m "refactor: route ELF consumers through selected backend"
```

### Task 6: Device, MCP, Remote API, and Desktop Status

**Files:**
- Modify: `mklink/device.py`
- Modify: `mklink/mcp_server.py`
- Modify: `mklink/remote/api.py`
- Modify: `mklink/_deps.py`
- Modify: `gui/src/composables/useMklinkApi.ts`
- Modify: `gui/src/composables/useMklinkApi.test.ts`
- Modify: `gui/src/components/dash/SymbolsTab.test.ts`
- Modify: `_maintainer/testing/tests/test_remote_api.py`
- Modify: `_maintainer/testing/tests/test_symbol_catalog.py`

- [ ] **Step 1: Add session propagation and status tests**

Verify SDK `Device`, MCP `connect/load_symbols`, REST `/api/device/connect` and `/api/device/parse-axf`, and desktop status default to built-in, accept explicit external selection, and report backend capabilities independently of external tool availability.

```python
def test_axf_status_reports_builtin_when_readelf_is_missing(monkeypatch, parsed_device):
    monkeypatch.setattr("mklink.toolchain.resolve_readelf", lambda: None)
    status = parsed_device.axf_status
    assert status["loaded"] is True
    assert status["elf_backend"] == "builtin"
    assert status["builtin_elf_available"] is True
    assert status["readelf_available"] is False
```

- [ ] **Step 2: Store backend choice on the device session**

Extend `Device.__init__`, `connect`, `reparse_axf_atomically`, and `parse_axf` with optional `elf_backend`. Resolve once per parse using the device project root and pass the effective backend into DWARF, memory-map, function, and HardFault operations. Update comments and errors that currently assume missing readelf.

- [ ] **Step 3: Extend MCP and REST request surfaces**

Add optional `elf_backend: Literal["builtin", "external"] | None` to MCP `connect` and `load_symbols`, REST connect body, and parse-AXF body. Return `elf_backend`, `builtin_elf_available`, `external_elf_available`, plus deprecated diagnostic `readelf_available`/`addr2line_available` fields. Remove installation guidance from MCP docstrings unless external mode was requested and unavailable.

- [ ] **Step 4: Keep the desktop built-in-first**

The normal desktop connect and reparse requests omit `elf_backend`, thereby selecting built-in. Update TypeScript response types and tests so the Symbols and HardFault surfaces remain enabled when GNU tools are absent. Do not add an everyday UI control for external mode; advanced users opt in through project configuration, environment, CLI, MCP, or REST.

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -m pytest _maintainer/testing/tests/test_remote_api.py _maintainer/testing/tests/test_symbol_catalog.py -q
Set-Location gui
npm test -- --run src/composables/useMklinkApi.test.ts src/components/dash/SymbolsTab.test.ts
Set-Location ..
```

Expected: Python and GUI status tests pass with built-in AXF availability independent of readelf.

Commit:

```powershell
git add mklink/device.py mklink/mcp_server.py mklink/remote/api.py mklink/_deps.py gui/src/composables/useMklinkApi.ts gui/src/composables/useMklinkApi.test.ts gui/src/components/dash/SymbolsTab.test.ts _maintainer/testing/tests/test_remote_api.py _maintainer/testing/tests/test_symbol_catalog.py
git commit -m "feat: expose built-in ELF backend across APIs"
```

### Task 7: Packaging, Licensing, CLI Guidance, and AI Skill

**Files:**
- Modify: `skills/tauri-gui-builder/scripts/build.py`
- Modify: `_maintainer/testing/tests/test_tauri_builder.py`
- Modify: `gui/src-tauri/resources/THIRD-PARTY-NOTICES.txt`
- Modify: `mklink/cli.py`
- Modify: `SKILL.md`
- Modify: `references/install.md`
- Modify: `references/commands-memory.md`

- [ ] **Step 1: Add packaging and documentation guard tests**

Extend the builder test to require `--collect-all elftools` and a complete pyelftools public-domain notice. Add source-text guards that the skill says built-in is default, external GNU is opt-in, and AI agents must not gate symbols or HardFault on `readelf_available`.

```python
def test_sidecar_collects_pyelftools(builder, monkeypatch, tmp_path):
    commands = build_sidecar_command(builder, monkeypatch, tmp_path)
    pairs = [commands[index:index + 2] for index in range(len(commands) - 1)]
    assert ["--collect-all", "elftools"] in pairs


def test_skill_defaults_axf_to_builtin_parser():
    text = (PROJECT_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "默认使用内置 pyelftools" in text
    assert "仅在用户明确指定" in text
```

- [ ] **Step 2: Bundle and disclose pyelftools**

Add `--collect-all elftools` to the sidecar command. Add the pyelftools project name, version policy, source URL, and public-domain dedication to `THIRD-PARTY-NOTICES.txt`. Keep the standard NSIS-only bundle configuration unchanged.

- [ ] **Step 3: Replace install-first guidance**

Update project-init/status output to show `ELF backend: builtin (pyelftools)` by default. Rewrite the GNU section as an optional compatibility backend with explicit examples:

```powershell
$env:MKLINK_ELF_BACKEND = "external"
$env:MKLINK_READELF = "C:\tools\arm-gnu\bin\arm-none-eabi-readelf.exe"
$env:MKLINK_ADDR2LINE = "C:\tools\arm-gnu\bin\arm-none-eabi-addr2line.exe"
```

Document that paths alone do not activate external mode.

- [ ] **Step 4: Update AI skill behavior**

Change `SKILL.md` and `references/commands-memory.md` so AI execution uses built-in symbols, type info, memory map, function lookup, and HardFault lines. `ping` capability fields are informational. Mention GNU installation only after the user explicitly selects external mode or approves it for a file unsupported by the built-in parser.

- [ ] **Step 5: Run focused tests and commit**

Run:

```powershell
python -m pytest _maintainer/testing/tests/test_tauri_builder.py _maintainer/testing/tests/test_cli_help.py -q
python scripts/ai_memory.py validate
```

Expected: builder and documentation guards pass; project memory remains valid.

Commit:

```powershell
git add skills/tauri-gui-builder/scripts/build.py _maintainer/testing/tests/test_tauri_builder.py gui/src-tauri/resources/THIRD-PARTY-NOTICES.txt mklink/cli.py SKILL.md references/install.md references/commands-memory.md
git commit -m "docs: make ELF parsing built-in by default"
```

### Task 8: Real AXF Qualification, Standard NSIS, Memory, and Push

**Files:**
- Modify if verification finds defects: files from Tasks 1-7 and their tests only
- Modify: `docs/ai/project-memory.json`
- Regenerate: `docs/ai/CURRENT_HANDOFF.md`
- Output outside Git: main repository `release/<build-time>/`

- [ ] **Step 1: Compare built-in and explicit external results on real files**

Use the supplied STM32F103 Keil AXF and GCC ELF read-only. Do not copy them into the repository. Compare:

- Defined object and function counts.
- Public readable symbol catalog paths and truncation behavior.
- Structures, unions, enums, arrays, and representative leaf addresses.
- Flash/RAM section summaries.
- Representative function and line lookups, including Thumb addresses.

Run built-in first with a restricted PATH. Run GNU comparison only with explicit `--elf-backend external`.

Expected: built-in handles both representative files without spawning GNU; material result differences are understood and covered by regression tests before proceeding.

- [ ] **Step 2: Run the full automated baseline**

Run:

```powershell
python -m pytest -q
Set-Location gui
npm test -- --run
npm run build
Set-Location src-tauri
cargo test
cargo check
Set-Location ..\..
git diff --check
```

Expected: Python, GUI, production build, Rust tests, cargo check, and whitespace validation all pass.

- [ ] **Step 3: Build only the standard NSIS installer**

Use the repository Tauri builder skill and force a fresh sidecar. Do not build MSI or WebView2-offline packages. Copy the resulting standard installer and compact manifest into the main repository `release/<build-time>/` directory.

Expected: builder output contains the standard NSIS installer, bundled sidecar, build identity, and pyelftools; no MSI or offline WebView2 package exists.

- [ ] **Step 4: Qualify the installed application under restricted PATH**

Install to an isolated location and launch with a PATH that contains no Python, Keil, GNU Arm, or system binutils directories. Verify:

- Health reports `elf_backend=builtin` and built-in availability.
- AXF parse succeeds and Symbols/SuperWatch catalogs load.
- Memory map succeeds.
- HardFault source-line service resolves representative PC/LR addresses offline; if the target has no active fault, do not induce one merely for testing.
- Process shutdown releases the product processes and port 8765.
- Process inspection shows no `readelf`, `addr2line`, or Python child process.

- [ ] **Step 5: Update durable AI memory**

Record factual source commits, installer path/hash, built-in/external compatibility results, restricted-PATH evidence, known unsupported DWARF constructs, and next actions. Do not record local firmware paths, full probe IDs, COM ports, usernames, screenshots, logs, or credentials.

Run:

```powershell
python scripts/ai_memory.py render
python scripts/ai_memory.py validate
git diff --check
```

Expected: memory validates and the handoff accurately reflects the live branch and verification state.

- [ ] **Step 6: Commit memory, push, and confirm clean synchronization**

```powershell
git add docs/ai/project-memory.json docs/ai/CURRENT_HANDOFF.md
git commit -m "docs: hand off built-in ELF backend"
git push origin feature/online-flash-streaming
git status --short --branch
git rev-list --left-right --count HEAD...@{upstream}
```

Expected: push succeeds, worktree is clean, and ahead/behind is `0 0`.

