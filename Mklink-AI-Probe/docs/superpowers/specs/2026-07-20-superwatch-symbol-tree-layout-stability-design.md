# SuperWatch Symbol Tree and Layout Stability Design

## Scope

This change addresses two remaining desktop SuperWatch problems:

1. The waveform rectangle moves vertically when live status text changes width and causes the header or toolbars to wrap.
2. Showing the complete symbol catalog renders thousands of leaf rows and makes the live waveform UI noticeably less responsive.

The change also improves structured-symbol navigation by presenting structure and array leaves as a collapsed tree. It does not change symbol discovery, the public runtime-readable catalog, acquisition addresses, read-block merging, binary streaming, firmware protocols, or the 256-leaf-per-root safety cap.

## Stable Waveform Layout

The desktop SuperWatch header will separate identity/status content from command actions. Live badges remain in a single stable row and use bounded dimensions for changing numeric text. Command buttons remain visible and do not move when status values change.

The collection and trigger toolbars will use stable single-row geometry on desktop. Their dynamic badges receive fixed or bounded widths, and their controls must not wrap in response to changing sample rate, buffer count, timestamps, or drop counters. Narrow layouts may use a deterministic responsive arrangement, but runtime text changes must not alter the chart rectangle.

This extends the earlier stable-Y-viewport work: removing the statistics footer prevented value rows from resizing the chart, while this change prevents the remaining header and toolbar wrap points from doing so.

## Symbol Tree Model

The frontend will derive a tree from the existing flat `SymbolDescriptor[]` catalog. The tree builder will parse member and array notation into stable path nodes while retaining the original descriptor only on readable scalar leaves.

Node types are:

- Root scalar leaf, displayed directly under the global-variable section.
- Structure or array branch, displayed with an expand control and descendant selection count.
- Runtime-readable scalar leaf, retaining the existing selection, visibility, value, type, and write controls.

All structure and array branches are collapsed by default. Expansion state is keyed by the full node path so catalog refreshes can preserve still-valid expanded branches. A reparse removes expansion keys that no longer exist.

Only descendants of expanded branches are rendered. Collapsed branches do not create leaf-row DOM nodes. Expanding a capped large root may render at most its existing 256 published leaves, which is acceptable without adding a second virtualization system.

## Filtering Behavior

With no search and `仅已选` disabled, the tree shows all root scalars and collapsed structured roots.

With `仅已选` enabled, the tree is pruned to selected leaves and their ancestors. Branches containing selected leaves expand automatically so the selected variables remain immediately visible. This filtering does not add, remove, start, stop, hide, or show acquisition channels.

During search, matching is case-insensitive against full symbol path and type name. The result contains matching leaves and all of their ancestors, and every matching path expands automatically. The component snapshots the user's expansion state when search begins. Clearing the search restores that snapshot instead of leaving search-expanded branches open.

Search and `仅已选` may be combined. A leaf must satisfy both filters, and only ancestors of surviving leaves remain visible.

## Live Value Updates

Waveform acquisition continues to publish the latest selected-channel values. Tree structure and filter results depend only on the catalog, selection set, query, and expansion state; they must not be rebuilt from every incoming value batch.

Only mounted leaf rows consume `latestValues`. Because collapsed branches do not mount their descendants, high-rate value updates cannot trigger thousands of off-screen row patches. Selection, visibility, and verified writes keep their existing API behavior.

## Error and State Handling

- A failed add or remove request restores the originating checkbox and leaves tree state unchanged.
- Stale catalogs continue to disable writes.
- Catalog reparse preserves valid selections and expansion keys, removes invalid ones, and keeps the current filtering mode.
- Empty filtered branches are omitted.
- Truncated-root warnings remain visible and continue to identify roots capped at 256 readable leaves.

## Testing

Automated tests will cover:

- Nested structure and array paths build the expected branch hierarchy.
- Structured roots are collapsed by default and do not render leaf rows.
- Expanding a branch reveals its readable leaves without changing selection.
- Search expands matching paths and clearing search restores the prior expansion state.
- `仅已选` prunes empty branches and exposes selected leaves.
- Search and `仅已选` compose correctly.
- Selection, visibility, editing, verified writes, stale-catalog behavior, and reparse behavior remain intact.
- A large synthetic catalog does not mount all leaf rows while its branches are collapsed.
- Changing live badge contents does not change desktop header, toolbar, or chart geometry.
- Existing SuperWatch binary streaming, hidden-channel, Y viewport, trigger, cursor, pause/resume, and responsive tests continue to pass.

## Qualification

After automated tests and the production frontend build, qualification will use the supplied STM32F103 target project with the real desktop application when available. The check will compare chart geometry over time while live counters change, confirm smooth rendering with `仅已选` both enabled and disabled, exercise nested structure and array expansion/search, and verify normal shutdown releases product processes and ports.

No firmware, Pack, FLM, logs, screenshots, probe identifiers, COM ports, usernames, credentials, or local hardware paths will be committed.
