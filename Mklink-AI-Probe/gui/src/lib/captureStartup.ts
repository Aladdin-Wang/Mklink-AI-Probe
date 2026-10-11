// This bounds the whole backend startup, including metadata and protocol work.
// Transport requests keep their own short deadlines; this does not retry I/O.
export const CAPTURE_START_TIMEOUT_MS = 60_000
