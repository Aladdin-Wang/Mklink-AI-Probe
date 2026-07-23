# SuperWatch Stable Y Viewport Design

## Scope

This change addresses two desktop SuperWatch issues:

1. Remove the dynamic statistics footer because changing numeric widths and line wrapping resize the chart rectangle.
2. Let users focus on small signals while a large signal such as `uwTick` remains selected, acquired, and temporarily outside the Y viewport.

No backend acquisition, symbol selection, buffer sizing, export, trigger, or protocol behavior changes are included.

## Layout

- Remove `stats-footer` from the waveform template.
- Stop generating `cur/min/max/avg` footer markup in `updateUI()`.
- Keep current values in the existing variable directory.
- Preserve a stable chart grid so incoming values cannot change the chart rectangle size or position.

## Y Viewport State

SuperWatch has two Y viewport states:

- **Auto**: derive the padded range from all visible channels.
- **Manual**: store an absolute `yMin` and `yMax`. New samples and changing extrema do not move or resize this range.

The initial state is Auto. The first Y zoom or Y pan captures the current rendered range and switches to Manual. Hiding or showing a curve does not alter a Manual range. Reset returns to Auto and refits all visible curves.

## Mouse Interaction

- Mouse wheel over the plot zooms Y around the value under the pointer. The anchored value remains at the same pixel after zoom.
- Left-button drag inside the plot pans Y vertically.
- When the X timeline is zoomed, the same drag may pan X horizontally and Y vertically in one gesture.
- Existing trigger-line and cursor dragging take precedence over viewport panning.
- Existing middle-button, Alt+left, Space+left, and Shift+wheel timeline interactions remain supported.
- Double-click inside the plot resets Y to Auto. Existing axis-specific reset behavior remains available.

Large channels remain selected and acquired while outside the Manual Y viewport. Eye controls continue to affect rendering only.

## Rendering

- Shared SuperWatch numeric Y ticks use the active Auto or Manual range.
- Curves outside the viewport are clipped by the Canvas as they are today.
- Manual viewport calculations must be independent of rolling ring-buffer extrema.
- Zoom and pan request only redraws; they do not reset or reconnect the stream.

## Verification

Automated tests must prove:

- The statistics footer is absent and `updateUI()` no longer rebuilds it.
- The chart rectangle remains unchanged while values gain digits and multiple variables update.
- Pointer-anchored wheel zoom preserves the value under the pointer.
- Left drag changes the absolute Manual Y range.
- A growing outlier channel does not move a Manual viewport focused on smaller signals.
- Double-click restores Auto range across all visible channels.
- Existing X zoom/pan, cursor, trigger, hidden-channel, pause/resume, and binary rendering tests still pass.

Real Edge or installed WebView2 verification should use one large monotonic value and at least two smaller changing signals, then confirm stable chart geometry and smooth Y interaction.
