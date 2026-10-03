"""Offline MCP analysis tools shared by both entry points; no device or runtime."""


def register_systemview_offline_tools(mcp):
    @mcp.tool()
    def systemview_analyze_events(events: list) -> dict:
        """Analyze an already-decoded SystemView event list (offline, no device).

        Args:
            events: list of decoded event dicts (as returned by systemview_read or
                systemview_decode ``events``). Useful for the AI to analyze a
                previously captured trace without re-capturing.
        """
        from mklink.systemview_analyzer import analyze_events
        return analyze_events(events)

    @mcp.tool()
    def systemview_decode(hex_bytes: str) -> dict:
        """Decode raw SystemView bytes (hex string) offline — no device needed.

        Useful for validating the decoder or replaying a captured RTT channel-1
        dump without hardware. Feed the hex of the raw bytes captured from the
        "SysView" up-buffer.

        Args:
            hex_bytes: Hex-encoded raw SystemView byte stream
                (e.g. "00000000000000000000180b..." ).
        """
        from mklink.systemview_parser import SystemViewParser
        try:
            raw = bytes.fromhex(hex_bytes)
        except ValueError as e:
            raise ValueError(f"invalid hex string: {e}") from e
        p = SystemViewParser()
        events = p.feed(raw)
        return {
            "events": events,
            "event_count": len(events),
            "bytes_read": len(raw),
            "synced": p.synced,
            "abs_time": p.abs_time,
            "cpu_freq": p.cpu_freq,
            "dropped_bytes": p.dropped_bytes,
            "dropped_packets": p.dropped_packets,
        }
