# Built-in ELF and DWARF Backend Design

## Scope

MKLink currently shells out to GNU `readelf` for ELF symbols, DWARF types,
function lookup, and section analysis, and to GNU `addr2line` for HardFault
source locations. This makes the packaged desktop application lose AXF/ELF
features on computers without an Arm GNU or system binutils installation.

This change makes a bundled `pyelftools` backend the default for every
symbol-dependent surface:

- CLI and MCP `symbols`, `typeinfo`, `watch`, `superwatch`, and `memmap`.
- Desktop Configuration, Symbols, SuperWatch, and AXF reparse workflows.
- Function search and named hardware-breakpoint resolution.
- HardFault PC/LR address-to-source lookup.
- AI skill guidance and dependency health reporting.

The external GNU tools remain available only as an explicitly selected
compatibility backend. MKLink must never invoke a local `readelf` or
`addr2line` merely because one is present, and it must not silently fall back
to those tools when built-in parsing fails.

## Selected Approach

The implementation will use two backends behind one internal interface:

- `builtin`, the default, parses ELF, symbols, sections, DWARF types, location
  expressions, and line programs through bundled `pyelftools`.
- `external`, selected explicitly, retains the current GNU text-output path and
  existing `MKLINK_READELF`, `MKLINK_ADDR2LINE`, and project tool-path
  resolution.

Bundling GNU executables was rejected because it adds native runtime files,
installer size, and GPL redistribution obligations. Reimplementing the parser
in Rust with `object` and `gimli` was rejected for this iteration because it
would duplicate the established Python `DwarfInfo` model and substantially
increase the migration surface.

## Backend Selection

The effective backend is `builtin` unless the user explicitly selects
`external`. Selection will be accepted from the product's normal configuration
surfaces, with command-specific options taking precedence over environment and
project configuration.

The intended precedence is:

1. A command or API request that explicitly supplies the backend.
2. `MKLINK_ELF_BACKEND` when set to `builtin` or `external`.
3. `.mklink/toolchain.json` key `elf_backend` when set to `builtin` or
   `external`.
4. Default `builtin`.

Configuring `readelf` or `addr2line` paths alone does not activate the external
backend. Once `external` is selected, the existing executable-path resolution
order remains unchanged. An invalid backend value fails with a configuration
error rather than selecting a backend heuristically.

Built-in parsing errors remain built-in errors. They may explain how to opt
into the external compatibility backend, but they must not launch external
programs automatically.

## Internal Interface

A focused ELF service will own backend selection and expose structured
operations instead of command output:

- Load the ELF header and validate that the input is a supported ELF/AXF file.
- Enumerate object and function symbols.
- Resolve an exact function name and search function names.
- Enumerate sections needed by memory-map analysis.
- Build the existing `DwarfInfo` representation.
- Resolve one or more instruction addresses to source file and line.

Consumers will request these operations from the service and will not import
`subprocess`, resolve GNU binaries, or parse GNU text directly. The current
readelf-output parsers remain isolated inside the external adapter for
compatibility and their existing fixture tests.

The public `DwarfInfo`, `DwarfVariable`, `DwarfStruct`, `DwarfArray`,
`DwarfEnum`, and symbol-catalog contracts remain stable. Watch, SuperWatch,
type formatting, symbol-tree generation, and runtime value decoding therefore
continue to consume the same normalized data.

## Built-in Symbol and Section Parsing

The built-in backend reads `.symtab` and returns normalized symbols with name,
address, size, symbol kind, binding, visibility, and section identity. Object
symbols feed variable browsing, while function symbols feed breakpoint and
function-search features. Undefined and unusable symbols are excluded.

Existing consumer-specific address policies remain in place. In particular,
the runtime-readable symbol catalog continues to publish only fixed scalar
leaves in supported RAM ranges. Introducing the new parser must not broaden
the catalog to pointers, dynamic locals, bit-fields, variable-length arrays,
overlapping union aliases, incomplete layouts, or non-RAM addresses.

Memory-map analysis reads section headers directly. It preserves the current
result schema and classification behavior while replacing textual `readelf -S`
parsing. Section size, virtual address, flags, and loadability come from the
ELF records rather than formatted output columns.

## Built-in DWARF Type Parsing

The DWARF adapter walks compilation units and DIEs and converts supported
records into the existing `DwarfInfo` model. It covers base types, typedefs,
qualifiers, pointers, fixed arrays, structures, unions, enumerations, members,
and global variables across DWARF versions 2 through 5 where `pyelftools`
provides the required forms.

Fixed global addresses are resolved from constant DWARF expressions such as
`DW_OP_addr`. When a variable DIE has a usable name and type but no fixed
location, the ELF object symbol table may provide its linked address. Location
lists, register-relative expressions, frame-relative locations, and other
runtime-dependent expressions are not converted into fixed global addresses.

Member offsets and array bounds are normalized from their DWARF attributes.
Unsupported dynamic bounds or expressions leave the record non-readable
instead of guessing a layout. Duplicate named records and anonymous records
remain keyed by DIE offset so the current type-following behavior is preserved.

## Address-to-Source Resolution

The built-in backend builds a searchable index from DWARF line programs. Input
instruction addresses are normalized for Arm Thumb state by clearing bit zero
before lookup. The lookup selects the nearest preceding valid line row within
the applicable sequence and must not cross an end-of-sequence boundary.

HardFault reports keep their current shape. A missing line program, stripped
file, or unmatched address yields an unavailable source location without
preventing fault-register and exception-frame decoding. Function-name lookup
from `.symtab` may decorate results where useful, but it does not substitute a
fabricated source line.

## Cache and Fingerprinting

The DWARF cache records the normalized data schema, selected backend, parser
implementation version, source fingerprint, source size, and modification
time. The schema will be bumped so cached GNU-text results cannot be mistaken
for newly parsed built-in data. Changing backend or parser version invalidates
the cache.

Cache failures remain recoverable: MKLink reparses the source and rewrites the
cache. Cache files continue to live outside the repository and must not contain
firmware payloads.

## Status, Errors, and Compatibility

Health and device status will report the effective ELF backend and whether the
built-in parser is available. External tool availability remains diagnostic
information only and no longer gates AXF loading.

Existing `readelf_available` and `addr2line_available` fields may be retained
temporarily for API compatibility, but they describe only the optional
external backend. New callers must use backend capability fields when deciding
whether AXF features are usable.

Errors distinguish invalid ELF input, missing DWARF data, unsupported DWARF
constructs, malformed sections, and explicitly selected but unavailable
external tools. Connecting to a probe still succeeds when AXF parsing fails;
the AXF status carries the structured parsing error.

The external adapter preserves the current GNU parsing behavior for users who
need compatibility with an unsupported producer. It is an opt-in backend, not
an automatic fallback.

## Packaging, Licensing, and Skill Guidance

`pyelftools` becomes a normal Python dependency and is collected into the
PyInstaller sidecar. The standard NSIS package must contain everything needed
for built-in parsing. MSI and WebView2-offline packages remain out of scope
unless explicitly requested.

Third-party notices and dependency tests will record the bundled parser's
licensing. The AI skill and installation references will stop instructing
agents to require `readelf` before symbol operations. Agents use the built-in
backend by default and mention GNU installation or path configuration only
when the user asks for the external backend or an unsupported file requires an
explicit compatibility choice.

## Testing

Automated tests will cover:

- Backend selection defaults to `builtin` even when GNU tools are discoverable.
- Tool paths alone do not activate `external`.
- Explicit CLI, environment, project, and API selection activates `external`
  with defined precedence.
- Built-in symbol enumeration covers object and function symbols and excludes
  undefined entries.
- Built-in DWARF normalization covers typedef and qualifier chains, duplicate
  and anonymous records, structures, unions, enums, fixed multidimensional
  arrays, member offsets, and fixed global locations.
- Symbol-table address completion works only for eligible named global
  variables.
- Dynamic locations and unsupported array bounds are excluded safely.
- Section parsing preserves memory-map totals and classifications.
- Line-program lookup handles Thumb addresses, exact rows, ranges, sequence
  boundaries, missing lines, and stripped files.
- HardFault decoding remains useful when source lookup is unavailable.
- Existing GNU text-parser tests continue to qualify the explicit external
  adapter.
- MCP, CLI, remote API, GUI status, and AI skill text no longer gate AXF
  features on `readelf_available`.
- PyInstaller includes `pyelftools`, and the installed standard NSIS parses AXF
  files under a restricted PATH with no Python, Keil, GNU Arm, or system
  binutils installation.

Read-only qualification will use representative GCC ELF and Keil AXF files,
including the supplied STM32F103 project, to compare symbol counts, readable
catalogs, structure and array paths, memory maps, and source-line results
between the built-in and explicitly selected external backends. Firmware,
AXF/ELF files, local paths, logs, screenshots, probe identifiers, COM ports,
usernames, credentials, Pack files, and FLM files will not be committed.

## Acceptance Criteria

- A clean Windows installation can use every AXF-dependent desktop, CLI, MCP,
  and HardFault feature without a user-installed compiler or binutils tool.
- No local `readelf` or `addr2line` process is launched unless the effective
  backend is explicitly `external`.
- Explicit external mode remains functional and produces compatible normalized
  results for the currently supported GNU output.
- Existing runtime-readable catalog safety rules and public API result shapes
  remain intact.
- The standard NSIS passes restricted-PATH qualification and the worktree is
  clean after the implementation, memory update, commit, and push.
