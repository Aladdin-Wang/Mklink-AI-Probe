# 0.3.5 DWARF bit-field watch verification

Verified 2026-10-15 on repair branch `codex/0.3.5-fixes`, implementation
`62faad0e`, draft PR #43. This extends the earlier
[metadata clock repair](v035-superwatch-clock.md); it is a separate defect.

## Cause and behavior

The symbol catalog deliberately skipped every DWARF bit-field member during
eager expansion, lazy search, browsing and path resolution. The parsers also
conflated legacy `DW_AT_bit_offset` with `DW_AT_data_bit_offset`, and structured
inspection shifted legacy offsets in the wrong direction. Simply exposing the
missing names would therefore have produced incorrect values.

The parsers now retain both location encodings and member storage size. A shared
normalizer converts them to a bounded byte span and LSB shift. Legacy offsets
are measured from the storage unit's MSB; modern offsets include the byte
position in the containing record. This follows the
[DWARF bit-field specification](https://dwarfstd.org/issues/081130.1.html).
The cache schema changes to invalidate previously conflated locations.

Catalog search/browse, scalar reads, structured inspection, shared SuperWatch
and standalone SuperWatch now use the normalized layout. Selected fields share
aligned memory read blocks; each field is masked and signed fields are sign
extended before plotting. Nonstandard byte spans are supported. Bit fields are
read-only, including the write API, to avoid overwriting adjacent fields.
Reparse/rebind retains their metadata and removes fields moved outside RAM.
The variable panel and symbol tab rerun an unchanged search after catalog
generation changes.

## Supplied ELF, offline verification

The private ELF is not committed or downloaded to the F103 board. Fresh parsing
finds 161 variables and 872 scalar leaves, compared with 815 before the repair.
The additional 57 leaves are bit fields.

`gSystemState` is three bytes and now exposes all six members:

| Member | Byte | LSB bit | Width |
|---|---:|---:|---:|
| FocRun | 0 | 0 | 1 |
| Modeloopclosed | 0 | 1 | 1 |
| ModeClose2 | 0 | 2 | 1 |
| bChkMosfetEnable | 0 | 3 | 1 |
| MotorDriverMode | 1 | — | 8 |
| ModeSub | 2 | — | 8 |

All 256 first-byte patterns, with distinct second and third bytes, passed 1,536
field comparisons using the actual ELF and compiled stream decoder. One aligned
four-byte read covers the complete record. `System` exposes 23 members, including
three previously skipped bit fields. The supplied `SystemCoreClock` has address
zero and the function-pointer array is in Flash; neither becomes a RAM scalar
watch. The screenshot's stale-AXF warning is additional context, not proof that
every absent ordinary variable had the same cause.

An additional real-browser comparison isolated the missing ordinary `System`
root. A controlled old catalog exposed only the two ordinary `gSystemState`
leaves; the actual customer ELF was then reparsed through the real HTTP endpoint
while the search text remained `System`. The old production GUI (`db963955`)
continued showing only those two leaves even though the backend now contained
all 23 `System` members. The repaired production GUI immediately showed 23
`System` members and six `gSystemState` members without editing the search text.
Fresh loading also showed all 29 matching leaves using the Device's actual
ELF-derived RAM ranges. This reproduces an independent stale-search defect;
the customer's original in-memory catalog is unavailable, so its exact history
cannot be reconstructed from the screenshot. This browser test used an offline
device-status fixture and real ELF/catalog/API code, with hardware reads/writes
disabled; it is separate from the physical board test below.

## Physical V3 + STM32F103 test

The user's original Keil project was modified in place with two test unions,
built with Arm Compiler 6.24, and downloaded with its existing Keil configuration.
Build: zero errors/warnings. Download: erase/program/verify successful, application
running. Probe firmware and power settings were not changed.

The target updates known patterns at 50 Hz using one aligned 32-bit store per
union. One record covers byte fields and 1/2/3-bit unsigned fields; the other
contains a signed five-bit field, a cross-byte nine-bit field, guards and sequence.
All 15 scalar channels share one contiguous eight-byte read block. Coherence is
checked within each word; no atomicity claim is made across separate words.

Real Edge loaded the rebuilt production GUI through the source shared backend,
at a 30 MHz debug clock. Browser WebSocket rows were compared with independently
calculated expected values:

| Requested interval | Browser rows checked | Incorrect rows | States per word |
|---|---:|---:|---:|
| 1 ms | 12,343 | 0 | 256 |
| 50 us | 245,540 | 0 | 256 |
| 50 us, curve/sequence follow-up | 272,200 | 0 | 256 |

The follow-up had zero sequence gaps when data and metadata frames were counted
together. An initial harness counted only data frames and reported 12 apparent
gaps per run: those were the expected periodic metadata frames. Backend read,
CRC, firmware-drop and queue-drop counters were zero. Browser script errors
were absent. Signed values covered -16 through 15; signed and cross-byte curves
were independently displayed and visually inspected. Hiding a curve retained
its acquisition channel. The bit-field edit control was disabled as intended.

Raw 32-bit curves use Float32 transport: the wide raw-word comparison explicitly
uses Float32 rounding. Small extracted fields are exact. This does not establish
lossless integer precision for arbitrary wide fields, or performance at the
single-channel maximum rate. Status snapshots precede the final drained browser
rows and should not be subtracted from those totals as a loss measurement.

All test captures stopped, browser/SDK clients closed, and runtime status returned
an empty list. The test project and board retain the authorized test firmware.
Local evidence is under the build workspace's `reports/elf-missing`; private ELF,
firmware, screenshots, hardware identifiers and paths are excluded from Git.

## Automated checks and delivery boundary

- 450 Python tests passed across DWARF/catalog, streaming, standalone health,
  alignment, writes, pins, shared watch, runtime memory, peripherals and performance.
- The final bit-field module passed 15 tests, including two added text-parser
  cases (452 distinct covered Python cases in total). Legacy/modern locations,
  bounded spans, signed cross-byte arrays, cache/rebind and write refusal are covered.
- 53 GUI tests passed across the variable panel, symbol tab, catalog and tree,
  including manual reparse adding an ordinary root to an unchanged search.
  Type checking and production GUI build passed.
- Two initial HPM write tests had an inconsistent fixture: HPM addresses with a
  retained Cortex-M RAM map. Correcting the fixture restored the intended coverage.
- Bit-field support is currently little-endian; invalid/unsupported layouts are
  excluded. This is targeted repair verification, not the complete release matrix.
- Source and tracked production Web assets are updated. The installed desktop
  remains the earlier clock-repair candidate and the global Skill remains its
  previously installed version; this bit-field change has not been packaged,
  installed, merged or officially published.
