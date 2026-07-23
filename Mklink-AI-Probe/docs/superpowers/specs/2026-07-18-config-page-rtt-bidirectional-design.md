# Configuration Page and RTT Bidirectional Communication Design

## Objective

Simplify the desktop configuration experience for users who operate MKLink without AI-assisted project discovery. Replace the duplicated Configuration/Connection tabs with one configuration page, let users provide artifact paths directly, move RTT address controls into RTT View, and add RTT DownBuffer transmission.

The existing AI and CLI project-initialization workflow remains available. This change removes project discovery from the desktop page; it does not remove or redefine the backend project-init endpoints or CLI behavior.

## Confirmed Requirements

- Remove the Configuration/Connection top-level tabs inside `ConfigView`.
- Remove Project Overview, Project Directory, Project Status, Recent Projects, and the duplicate configuration/MICROKEEN status strip.
- Remove MCU selection and the local connection MCU hint.
- Preserve local device connection, remote server connection, and service launch functionality.
- Use the selected left-side section navigation:
  - Local Device
  - File Sources
  - Remote Connection
  - Start Service
- Provide one AXF/ELF path and one independent MAP path.
- AXF/ELF is the primary source for symbols and RTT address detection. MAP is the fallback source.
- Paths are desktop-global settings and are restored on the next application launch.
- Remove RTT Advanced Configuration from the configuration page.
- Move RTT address entry and automatic address search into Dashboard RTT View.
- RTT automatic search fills the editable RTT address input. There is no Auto/Manual mode selector.
- Add a compact RTT transmit bar below the received-data display, based on the supplied reference image.
- Support string and hexadecimal transmission, Enter-to-send, line-ending selection, clear, and send history.

## Scope Boundary

Most work is in the desktop frontend. Two small backend API extensions are required to make the confirmed UI functional:

1. RTT address detection must accept an optional source path instead of always scanning the backend project root.
2. The integrated RTT dashboard must expose binary-safe DownBuffer transmission.

Both extensions are additive. Calls without the new arguments retain the current project-root behavior used by AI project initialization and CLI workflows.

## Configuration Page Structure

`ConfigView` becomes a single workspace with a narrow left navigation and one right content area. The page does not introduce another set of tabs.

### Local Device

The default section contains:

- Serial port selector with automatic detection and refresh.
- SWD clock setting.
- Save, Connect Device, and Disconnect commands.
- Compact device status: connection, runtime state, and symbol-load state.

Connection uses the saved AXF/ELF path when present. The request no longer sends an MCU hint. Existing connection and disconnection behavior, resource coordination, firmware warning, and device polling remain unchanged.

### File Sources

The section contains:

- Editable AXF/ELF path with a Browse button.
- Editable MAP fallback path with a Browse button.
- Save File Paths command.
- Symbol parsing status and Parse Symbols command.

The desktop shell uses the Tauri dialog plugin to obtain absolute file paths. AXF/ELF selection accepts `.axf`, `.elf`, and `.out`; MAP selection accepts `.map`. Manual path editing remains available, including in browser-based development where the native dialog is unavailable.

The frontend stores these values in a versioned local-storage object. It does not write them into a user project directory. Saving a path does not invoke project initialization.

Parse Symbols is enabled only while a device is connected and an AXF/ELF path is present. MAP is not offered as an application-variable symbol source.

### Remote Connection

Preserve the current server URL, optional token, connect, and disconnect behavior. The section is isolated for future expansion but does not gain new behavior in this task.

### Start Service

Preserve host, port, optional token, and service-launch behavior. The section is isolated for future expansion but does not gain new behavior in this task.

## Removed Frontend Dependencies

`ConfigView` stops loading or presenting:

- Project root.
- Project information.
- Configuration status.
- Project history.
- MCU profiles.
- RTT configuration.
- RTT project-root discovery controls.

The related backend endpoints and project configuration modules remain intact for AI, CLI, and other consumers. Frontend components that become unused may be removed only when no other view imports them.

## RTT Address Controls

RTT View adds an editable `RTT Address` input and an `Auto Search` button to its toolbar.

Automatic search uses this source priority:

1. Saved AXF/ELF path.
2. Saved MAP path when AXF/ELF is empty.
3. Existing backend project-derived discovery when both desktop paths are empty.

The detection endpoint accepts an optional `source_path`. When supplied, it calls the existing MAP/ELF/AXF resolver directly and returns the detected address, source, details, and warnings. When omitted, the endpoint follows its existing project-root discovery path.

Successful detection writes the address into the same editable input and displays its source. Failure leaves the previous address untouched and shows actionable details.

The address input accepts `0x` followed by hexadecimal digits. RTT Start validates the input and passes its current value to the existing RTT start API. A detected or manually entered address is treated as an exact control-block address; the UI does not expose storage mode, search size, or channel controls.

The most recently valid RTT address is retained with the desktop-global settings so removing the old RTT configuration section does not lose persistence.

## RTT Transmit Bar

The transmit bar is placed below the waveform and receive log. It is a single compact row:

`Abc/Hex toggle | transmit direction | input | clear | history | line ending | send`

Use the existing icon library for direction, clear, history, and dropdown affordances. The format toggle displays only the active label:

- `Abc`: UTF-8 string input.
- `Hex`: hexadecimal byte input.

Clicking the format control toggles the mode. It does not rewrite the current input text.

### Line Ending

The mutually exclusive choices use literal escape notation:

- `无`
- `\r`
- `\n`
- `\r\n`

The selected ending is appended after the main payload is encoded.

### Sending

- Clicking Send or pressing Enter sends the current value.
- IME composition Enter events do not send prematurely.
- Empty input is not sent.
- Send is enabled only when RTT is running and an active DownBuffer is reported.
- String mode encodes the exact input as UTF-8.
- Hex mode ignores ASCII whitespace and requires an even number of hexadecimal digits.
- The frontend converts both modes to bytes, appends the selected ending bytes, and sends one hexadecimal payload to the backend.
- No implicit newline, terminator, escaping, or command interpretation occurs beyond the selected line ending.
- Successful send clears only the current input.
- Failed send retains the input and displays the error.
- Format mode and line-ending selection persist after sending.

### Clear and History

Clear empties only the transmit input and does not clear received RTT data.

History stores the 20 most recent successful sends in desktop local storage. Each entry contains input text, format mode, line ending, and timestamp. Consecutive duplicate entries are collapsed. Choosing a history entry restores its text, format, and line ending without sending it.

## Binary-Safe Backend Contract

Add `POST /api/dash/rtt/write` with a JSON body containing `data_hex`.

The endpoint:

- Rejects malformed or odd-length hexadecimal data.
- Rejects empty payloads and payloads over 64 KiB.
- Requires an active RTT dashboard session.
- Requires an active RTT DownBuffer.
- Converts hex to bytes and writes those exact bytes through the running RTT session.
- Returns the number of transmitted bytes.

`RttStreamManager` retains the active device and RTT start metadata for its current generation, exposes DownBuffer availability in status, and provides a manager-owned write operation. Stop and failed-start cleanup clear the retained device and metadata so stale sessions cannot accept writes.

## State and Error Handling

- Native file-dialog cancellation makes no state change.
- Invalid or missing saved paths remain editable and show inline validation; they do not block device connection unless the user explicitly requests symbol parsing.
- Device connection remains valid if AXF/ELF parsing fails; the existing symbol error is displayed separately.
- RTT address search cannot overwrite a user-edited address after a newer search or component disposal.
- RTT start is blocked when the address is invalid.
- Transmit controls disable immediately on stop, runtime error, missing DownBuffer, disconnect, or component unmount.
- DownBuffer writes do not create a second device or bridge connection.

## Testing Strategy

### Frontend

- Config page has no Configuration/Connection tabs or removed project/MCU/RTT sections.
- Left navigation exposes all four retained sections.
- Local connection omits MCU and uses the saved AXF/ELF path.
- File paths save and restore from versioned desktop settings.
- Native Browse success and cancellation are covered through an adapter mock; manual editing remains usable without Tauri.
- RTT address search observes AXF/ELF, MAP, then backend fallback priority.
- Stale address-search results cannot overwrite newer edits.
- RTT Start passes the validated address.
- Abc/Hex toggle, literal line endings, Enter send, IME guard, clear, and history restore behave as specified.
- UTF-8 and hexadecimal inputs produce exact expected bytes.
- Invalid HEX and failed sends retain the input.
- Send is gated by runtime and DownBuffer state.

### Backend

- Optional RTT detection path supports AXF/ELF/MAP and preserves no-argument project discovery.
- RTT write rejects invalid, empty, oversized, stopped-session, and missing-DownBuffer requests.
- RTT write preserves arbitrary byte values exactly.
- Manager lifecycle prevents writes through stale or stopped generations.

### Verification

- Focused GUI and Python tests.
- Full GUI and Python suites because ConfigView, shared device connection, and RTT manager/API contracts are touched.
- Vite production build, Rust tests, and `cargo check` because the Tauri dialog plugin and capabilities change.
- Real Edge/Playwright validation against the production frontend and installed bundled sidecar.
- Physical RTT HIL for address detection, manual address override, UTF-8 transmit, HEX transmit, each line ending, history restore, failure behavior, stop cleanup, and resource release.

## Out of Scope

- Removing or changing AI/CLI project initialization.
- Changing online or offline flash workflows.
- Adding new remote-server or service-launch capabilities.
- Multi-line RTT command editing, macros, scripted send sequences, or automatic resend.
- MSI or WebView2-offline packaging unless explicitly requested.
