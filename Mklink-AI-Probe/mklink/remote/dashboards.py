"""Integrated dashboard SSE endpoints for FastAPI.

Provides real-time data streaming (RTT, VOFA, SuperWatch, Serial, Modbus)
without launching subprocess dashboards. The FastAPI process holds the single
device connection and streams data via SSE.

Architecture::

    Vue Component ──SSE──► FastAPI /api/dash/*/stream
                                  │
                            thread pool executor
                                  │
                            Device (single connection)
                                  │
                            MKLink Probe ──► Target MCU
"""

from __future__ import annotations

import asyncio
import base64
from collections import deque
import json
import logging
import math
import threading
import time
from typing import Any, Generator

from mklink.remote.stream_protocol import encode_systemview_events

logger = logging.getLogger(__name__)


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        parsed = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def _sse_format(data: str, event: str | None = None) -> str:
    """Format a single SSE message."""
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {data}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _sse_json(data: Any, event: str | None = None) -> str:
    return _sse_format(json.dumps(data, default=str), event)


# ---------------------------------------------------------------------------
# AsyncBridge — thread ↔ async queue bridge
# ---------------------------------------------------------------------------

class AsyncBridge:
    """Bridges a synchronous polling thread to an async SSE generator.

    Usage:
        bridge = AsyncBridge()
        # In a background thread:
        bridge.put({"temp": 25.3})
        # In an async SSE generator:
        async for data in bridge:
            yield data
    """

    def __init__(self, maxsize: int = 200):
        self._queue: asyncio.Queue | None = None
        self._maxsize = maxsize
        self._stopped = False
        self._lock = threading.Lock()
        self._clients: list[asyncio.Queue] = []
        self._clients_lock = threading.Lock()

    def _get_queue(self) -> asyncio.Queue:
        """Get or create a queue for the current async context."""
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._maxsize)
        return self._queue

    def put(self, data: Any) -> None:
        """Put data from a sync thread into all client queues."""
        with self._clients_lock:
            for q in self._clients:
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    # Drop oldest to make room
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        q.put_nowait(data)
                    except asyncio.QueueFull:
                        pass

    def add_client(self) -> asyncio.Queue:
        """Register a new SSE client and return its queue."""
        q = asyncio.Queue(maxsize=self._maxsize)
        with self._clients_lock:
            self._clients.append(q)
        return q

    def remove_client(self, q: asyncio.Queue) -> None:
        """Unregister an SSE client."""
        with self._clients_lock:
            try:
                self._clients.remove(q)
            except ValueError:
                pass

    @property
    def client_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)

    def stop(self) -> None:
        self._stopped = True
        with self._clients_lock:
            for q in self._clients:
                try:
                    q.put_nowait(None)  # sentinel
                except asyncio.QueueFull:
                    pass


# ---------------------------------------------------------------------------
# RTT SSE Generator
# ---------------------------------------------------------------------------

class RttStreamManager:
    """Manages RTT streaming sessions with SSE output."""

    def __init__(self):
        self._bridge = AsyncBridge()
        self._thread: threading.Thread | None = None
        self._running = False
        self._paused = threading.Event()
        self._paused.set()  # not paused
        self._stop_event = threading.Event()
        self._history: list[dict] = []
        self._max_history = 500
        self._parser = None
        self._interval = 0.0
        self._stats = {"parsed_lines": 0, "raw_lines": 0}
        self._start_failure_callback = None

    @property
    def running(self) -> bool:
        return self._running and not self._stop_event.is_set()

    @property
    def paused(self) -> bool:
        return not self._paused.is_set()

    def set_start_failure_callback(self, callback) -> None:
        self._start_failure_callback = callback

    def start(self, device, *, addr: str | None = None, channel: int = 0,
              mode: int = 0, search_size: int = 1024,
              duration: float = 86400) -> None:
        """Start RTT polling in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            if self.running:
                return
            raise RuntimeError("RTT worker thread is still active")

        stop_event = threading.Event()
        generation = object()
        self._stop_event = stop_event
        self._generation = generation
        self._paused.set()
        self._running = True
        self._history.clear()
        self._stats = {"parsed_lines": 0, "raw_lines": 0}

        # Auto-detect parser strategy from initial RTT output
        from mklink.rtt_viewer import RttLineParser
        self._parser = RttLineParser("kv")  # will auto-detect on first lines
        failure_callback = self._start_failure_callback

        def _poll():
            initialized = False
            start_failure = None
            try:
                device.rtt_start(addr, channel=channel, mode=mode,
                                 search_size=search_size)
                initialized = True
                start_time = time.time()
                sample_lines = []

                while not stop_event.is_set():
                    if time.time() - start_time > duration:
                        break
                    if not self._paused.is_set():
                        time.sleep(0.05)
                        continue

                    try:
                        text = device.rtt_read(duration=0.5)
                    except Exception:
                        time.sleep(0.1)
                        continue

                    if not text or not text.strip():
                        continue

                    now = time.time()
                    for line in text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        self._stats["raw_lines"] += 1

                        # Collect samples for auto-detection
                        if len(sample_lines) < 20:
                            sample_lines.append(line)
                            if len(sample_lines) == 20:
                                self._parser = RttLineParser.auto_detect(sample_lines)

                        parsed = self._parser.parse(line)
                        if parsed is not None:
                            parsed["_t"] = now
                            self._stats["parsed_lines"] += 1
                            self._bridge.put({"event": "data", **parsed})
                            # History ring buffer
                            self._history.append(parsed)
                            if len(self._history) > self._max_history:
                                self._history = self._history[-self._max_history:]
                        else:
                            # Raw line event
                            self._bridge.put({"event": "raw", "line": line, "_t": now})

            except Exception as e:
                logger.error("RTT stream error: %s", e)
                self._bridge.put({"event": "error", "message": str(e)})
                if not initialized:
                    start_failure = e
            finally:
                try:
                    if getattr(self, "_generation", None) is generation:
                        self._running = False
                        try:
                            self._bridge.put({"event": "stopped"})
                        finally:
                            self._bridge.stop()
                finally:
                    if start_failure is not None and failure_callback is not None:
                        try:
                            failure_callback(start_failure)
                        except Exception:
                            pass

        self._thread = threading.Thread(target=_poll, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        thread = self._thread
        self._stop_event.set()
        if thread:
            thread.join(timeout=timeout)
            if thread.is_alive():
                raise TimeoutError("RTT worker thread is still active")
        self._running = False
        if self._thread is thread:
            self._thread = None
        return True

    def pause(self) -> None:
        self._paused.clear()

    def resume(self) -> None:
        self._paused.set()

    def get_history(self) -> list[dict]:
        return list(self._history)

    def get_status(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "clients": self._bridge.client_count,
            "stats": self._stats,
            "history_size": len(self._history),
        }

    async def sse_generator(self):
        """Async SSE generator for FastAPI StreamingResponse."""
        q = self._bridge.add_client()
        # Send initial state
        yield _sse_json({"event": "status", **self.get_status()})
        # Send history replay
        if self._history:
            yield _sse_json({"event": "history", "points": self._history[-100:]})

        try:
            while self.running or self.paused:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield _sse_format("", event="ping")
                    continue
                if data is None:
                    break
                yield _sse_json(data)
                if data.get("event") == "stopped":
                    break
        finally:
            self._bridge.remove_client(q)


class SystemViewStreamManager:
    """Manages SEGGER SystemView RTOS-trace streaming via RTT channel 1.

    Reads raw bytes from the target's RTT "SysView" up-buffer, decodes them
    with a persistent SystemViewParser (accumulating timestamps + name maps),
    and streams decoded RTOS events (task switches, ISR, CPU%, kernel objects)
    over SSE for the RTOS-Trace dashboard.
    """

    def __init__(self, stream_hub=None):
        self._bridge = AsyncBridge()
        self._thread: threading.Thread | None = None
        self._running = False
        self._paused = threading.Event()
        self._paused.set()  # not paused
        self._stop_event = threading.Event()
        self._history: list[dict] = []
        self._max_history = 100_000
        self._history_buffer_us = 60_000_000
        self._history_replay_limit = 500
        self._live_batch_limit = 500
        self._stream_hub = stream_hub
        self._last_status_publish = 0.0
        self._parser = None
        self._stats = {"events": 0, "bytes": 0}
        self._resolved_task_names: dict[int, str] = {}
        self._name_resolution_attempted: set[int] = set()
        self._last_name_resolution = 0.0
        self._cpu_freq_source = ""
        self._recording = None
        self._recording_path = ""
        self._recording_summary_path = ""
        self._recording_error = ""
        self._start_failure_callback = None

    @property
    def running(self) -> bool:
        return self._running and not self._stop_event.is_set()

    @property
    def paused(self) -> bool:
        return not self._paused.is_set()

    def set_start_failure_callback(self, callback) -> None:
        self._start_failure_callback = callback

    def set_stream_hub(self, stream_hub) -> None:
        self._stream_hub = stream_hub

    def start(self, device, *, addr: str | None = None, channel: int = 1,
              mode: int = 0, search_size: int = 1024,
              duration: float = 86400) -> None:
        """Start SystemView polling in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            if self.running:
                return
            raise RuntimeError("SystemView worker thread is still active")

        stop_event = threading.Event()
        generation = object()
        self._stop_event = stop_event
        self._generation = generation
        self._paused.set()
        self._running = True
        self._history.clear()
        self._stats = {"events": 0, "bytes": 0}
        self._resolved_task_names.clear()
        self._name_resolution_attempted.clear()
        self._last_name_resolution = 0.0
        self._cpu_freq_source = ""
        self._recording = None
        self._recording_path = ""
        self._recording_summary_path = ""
        self._recording_error = ""
        self._parser = self._create_parser(device)
        failure_callback = self._start_failure_callback

        def _poll():
            initialized = False
            start_failure = None
            try:
                start_result = device.systemview_start(
                    addr, channel=channel, mode=mode, search_size=search_size,
                )
                initialized = True
                self._apply_cpu_freq_hint(device, start_result)
                self._start_recording(
                    device,
                    {"addr": addr, "channel": channel, "mode": mode},
                )
                start_time = time.time()
                empty_cycles = 0
                while not stop_event.is_set():
                    if time.time() - start_time > duration:
                        break
                    if not self._paused.is_set():
                        time.sleep(0.05)
                        continue
                    try:
                        raw = device.systemview_read_bytes(
                            duration=0.1, max_bytes=64 * 1024
                        )
                    except Exception:
                        time.sleep(0.1)
                        continue
                    if not raw:
                        empty_cycles += 1
                        if empty_cycles == 4:
                            try:
                                device.systemview_stop()
                                time.sleep(0.5)
                                start_result = device.systemview_start(
                                    addr, channel=channel, mode=mode,
                                    search_size=search_size,
                                )
                                self._apply_cpu_freq_hint(device, start_result)
                            except Exception:
                                pass
                        continue
                    empty_cycles = 0
                    self._stats["bytes"] += len(raw)
                    now = time.time()
                    evs = self._parser.feed(raw)
                    self._note_init_cpu_freq(evs)
                    self._ensure_event_time_fields(evs)
                    self._maybe_resolve_task_names(
                        device, evs, addr=addr, channel=channel,
                        mode=mode, search_size=search_size,
                    )
                    self._apply_task_names(evs)
                    self._process_events(evs, now=now)
            except Exception as e:
                logger.error("SystemView stream error: %s", e)
                self._bridge.put({"event": "error", "message": str(e)})
                if not initialized:
                    start_failure = e
            finally:
                try:
                    device.systemview_stop()
                except Exception:
                    pass
                try:
                    self._close_recording()
                except Exception:
                    pass
                try:
                    if getattr(self, "_generation", None) is generation:
                        self._running = False
                        try:
                            self._bridge.put({"event": "stopped"})
                        finally:
                            self._bridge.stop()
                finally:
                    if start_failure is not None and failure_callback is not None:
                        try:
                            failure_callback(start_failure)
                        except Exception:
                            pass

        self._thread = threading.Thread(target=_poll, daemon=True)
        self._thread.start()

    def _process_events(self, events: list[dict], *, now: float) -> None:
        """Record every event, then publish bounded live binary batches."""
        if not events:
            return
        self._stats["events"] += len(events)
        # Durable recording is deliberately ahead of all bounded live paths.
        self._record_events(events)
        self._history.extend(events)
        self._trim_history()

        if self._stream_hub is not None:
            for offset in range(0, len(events), self._live_batch_limit):
                batch = events[offset:offset + self._live_batch_limit]
                self._stream_hub.publish(
                    encode_systemview_events(batch), item_count=len(batch)
                )

        if now - self._last_status_publish >= 1.0:
            self._last_status_publish = now
            self._bridge.put({
                "event": "status",
                "stats": dict(self._stats),
                "history_size": len(self._history),
                **self._status_meta(),
            })

    def _create_parser(self, device=None):
        from mklink.systemview_parser import SystemViewParser

        parser = SystemViewParser()
        defaults = {}
        getter = getattr(device, "_systemview_defaults", None)
        if callable(getter):
            try:
                defaults = getter()
            except Exception:
                defaults = {}
        parser._ram_base = _positive_int(defaults.get("ram_base")) or 0x20000000
        parser._id_shift = _positive_int(defaults.get("id_shift")) or 2
        freq = _positive_int(defaults.get("cpu_freq"))
        if freq:
            parser._cpu_freq = freq
            self._cpu_freq_source = str(defaults.get("cpu_freq_source") or "systemview_default")
        return parser

    def _apply_cpu_freq_hint(self, device, start_result: dict | None = None) -> int:
        p = self._parser
        if not p or p.cpu_freq:
            if p and p.cpu_freq and not self._cpu_freq_source:
                self._cpu_freq_source = "parser_default"
            return p.cpu_freq if p else 0

        freq = 0
        source = ""
        result = start_result or {}
        for key in ("cpu_freq", "cpu_freq_hint"):
            freq = _positive_int(result.get(key))
            if freq:
                source = str(result.get("cpu_freq_source") or "systemview_start")
                break

        if not freq:
            device_parser = getattr(device, "_systemview_parser", None)
            freq = _positive_int(getattr(device_parser, "cpu_freq", 0))
            if freq:
                source = "device_parser"

        if not freq and getattr(device, "_dwarf_info", None):
            try:
                freq = _positive_int(device.read_variable("SystemCoreClock"))
                if freq:
                    source = "SystemCoreClock"
            except Exception:
                freq = 0

        if not freq:
            freq = self._profile_cpu_freq_default(device)
            if freq:
                source = "mcu_profile_default"

        if freq:
            p._cpu_freq = freq
            self._cpu_freq_source = source
            self._ensure_event_time_fields(self._history)
        return freq

    def _profile_cpu_freq_default(self, device) -> int:
        getter = getattr(device, "_systemview_defaults", None)
        if callable(getter):
            try:
                defaults = getter()
                freq = _positive_int(defaults.get("cpu_freq"))
                if freq:
                    return freq
            except Exception:
                pass
        profile = None
        try:
            getter = getattr(device, "_get_mcu_profile", None)
            if callable(getter):
                profile = getter()
        except Exception:
            profile = None
        if not isinstance(profile, dict):
            return 0
        for key in ("cpu_freq_default", "system_core_clock", "systemview_cpu_freq"):
            freq = _positive_int(profile.get(key))
            if freq:
                return freq
        return 0

    def _note_init_cpu_freq(self, events: list[dict]) -> None:
        for ev in events:
            if ev.get("kind") == "init" and _positive_int(ev.get("cpu_freq")):
                self._cpu_freq_source = "INIT"
                return

    def _ensure_event_time_fields(self, events: list[dict]) -> None:
        p = self._parser
        freq = _positive_int(getattr(p, "cpu_freq", 0))
        if not freq:
            return
        for ev in events:
            ticks = ev.get("t_ticks")
            if "t_us" not in ev and isinstance(ticks, (int, float)):
                ev["t_us"] = ticks * 1_000_000.0 / freq
            delta = ev.get("delta_ticks")
            if "cpu_delta_us" not in ev and isinstance(delta, (int, float)):
                ev["cpu_delta_us"] = delta * 1_000_000.0 / freq

    def _trim_history(self) -> None:
        if self._history_buffer_us > 0:
            latest_us = None
            for ev in reversed(self._history):
                t_us = ev.get("t_us")
                if isinstance(t_us, (int, float)):
                    latest_us = t_us
                    break
            if latest_us is not None:
                cutoff = latest_us - self._history_buffer_us
                self._history = [
                    ev for ev in self._history
                    if not isinstance(ev.get("t_us"), (int, float)) or ev["t_us"] >= cutoff
                ]
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def _start_recording(self, device, extra_meta: dict | None = None) -> None:
        try:
            from mklink.systemview_logger import SystemViewJsonlLogger

            project_root = getattr(device, "_project_root", None) or "."
            meta = {
                **self._status_meta(),
                **(extra_meta or {}),
            }
            self._recording = SystemViewJsonlLogger(project_root, meta)
            self._recording_path = str(self._recording.path)
            self._recording_summary_path = str(self._recording.summary_path)
            self._recording_error = ""
        except Exception as e:
            self._recording = None
            self._recording_error = str(e)

    def _record_events(self, events: list[dict]) -> None:
        if not self._recording or not events:
            return
        try:
            self._recording.write_events(events)
        except Exception as e:
            self._recording_error = str(e)
            try:
                self._recording.close({"events": self._stats.get("events", 0)})
            except Exception:
                pass
            self._recording = None

    def _close_recording(self) -> None:
        if not self._recording:
            return
        try:
            self._recording.close({
                "events": self._stats.get("events", 0),
                "bytes": self._stats.get("bytes", 0),
                "history_size": len(self._history),
                "cpu_freq": _positive_int(getattr(self._parser, "cpu_freq", 0)),
                "cpu_freq_source": self._cpu_freq_source,
                "dropped_bytes": getattr(self._parser, "dropped_bytes", 0),
                "dropped_packets": getattr(self._parser, "dropped_packets", 0),
            })
        except Exception as e:
            self._recording_error = str(e)
        finally:
            self._recording = None

    def _status_meta(self) -> dict:
        p = self._parser
        if not p:
            return {
                "synced": False,
                "abs_time": 0,
                "cpu_freq": 0,
                "cpu_freq_source": "",
                "dropped_bytes": 0,
                "dropped_packets": 0,
                "task_names": {},
                "isr_names": {},
                "recording_path": self._recording_path,
                "recording_summary_path": self._recording_summary_path,
                "recording_error": self._recording_error,
            }
        return {
            "synced": p.synced,
            "abs_time": p.abs_time,
            "cpu_freq": p.cpu_freq,
            "cpu_freq_source": self._cpu_freq_source,
            "dropped_bytes": p.dropped_bytes,
            "dropped_packets": p.dropped_packets,
            "task_names": dict(p._task_names),
            "isr_names": dict(p._isr_names),
            "recording_path": self._recording_path,
            "recording_summary_path": self._recording_summary_path,
            "recording_error": self._recording_error,
        }

    def _unknown_task_ids(self, events: list[dict]) -> set[int]:
        p = self._parser
        if not p:
            return set()
        ram_base = _positive_int(getattr(p, "_ram_base", 0)) or 0x20000000
        ids: set[int] = set()
        for ev in events:
            tid = ev.get("task_id")
            if not isinstance(tid, int):
                continue
            if tid < ram_base:
                continue
            if tid in p._task_names or tid in self._name_resolution_attempted:
                continue
            ids.add(tid)
        return ids

    def _apply_task_names(self, events: list[dict]) -> None:
        p = self._parser
        if not p:
            return
        for ev in events:
            tid = ev.get("task_id")
            if isinstance(tid, int) and not ev.get("task_name"):
                name = p._task_names.get(tid)
                if name:
                    ev["task_name"] = name

    def _resolve_task_names(self, device, task_ids: set[int]) -> dict[int, str]:
        p = self._parser
        ram_base = _positive_int(getattr(p, "_ram_base", 0)) or 0x20000000
        ids = {int(tid) for tid in task_ids if int(tid) >= ram_base}
        if not ids:
            return {}
        names = device.systemview_resolve_task_names(sorted(ids)) or {}
        if p:
            for tid, name in names.items():
                if name:
                    p._task_names[int(tid)] = str(name)
        for ev in self._history:
            tid = ev.get("task_id")
            if isinstance(tid, int) and tid in names and names[tid]:
                ev["task_name"] = names[tid]
        self._resolved_task_names.update({int(k): str(v) for k, v in names.items() if v})
        return names

    def _maybe_resolve_task_names(
        self,
        device,
        events: list[dict],
        *,
        addr: str | None,
        channel: int,
        mode: int,
        search_size: int,
    ) -> None:
        ids = self._unknown_task_ids(events)
        if not ids:
            return
        now = time.time()
        if now - self._last_name_resolution < 3.0:
            return
        self._last_name_resolution = now
        self._name_resolution_attempted.update(ids)

        try:
            device.systemview_stop()
            try:
                self._resolve_task_names(device, ids)
            finally:
                start_result = device.systemview_start(
                    addr, channel=channel, mode=mode, search_size=search_size,
                )
                self._apply_cpu_freq_hint(device, start_result)
        except Exception as e:
            logger.debug("SystemView task-name resolution failed: %s", e)

    def stop(self, timeout: float = 5.0) -> bool:
        thread = self._thread
        self._stop_event.set()
        if thread:
            thread.join(timeout=timeout)
            if thread.is_alive():
                raise TimeoutError("SystemView worker thread is still active")
        self._running = False
        if self._thread is thread:
            self._thread = None
        return True

    def pause(self) -> None:
        self._paused.clear()

    def resume(self) -> None:
        self._paused.set()

    def get_history(self) -> list[dict]:
        return list(self._history)

    def get_status(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "clients": self._bridge.client_count,
            "stats": self._stats,
            "history_size": len(self._history),
            **self._status_meta(),
        }

    async def sse_generator(self):
        """Async SSE generator for FastAPI StreamingResponse."""
        q = self._bridge.add_client()
        yield _sse_json({"event": "status", **self.get_status()})
        try:
            while self.running or self.paused:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield _sse_format("", event="ping")
                    continue
                if data is None:
                    break
                yield _sse_json(data)
                if data.get("event") == "stopped":
                    break
        finally:
            self._bridge.remove_client(q)


# ---------------------------------------------------------------------------
# SuperWatch SSE Generator
# ---------------------------------------------------------------------------

class SuperWatchStreamManager:
    """Manages SuperWatch variable polling with SSE output.

    Uses SuperWatchRuntime for DWARF-based variable resolution and
    efficient block-based memory reads.
    """

    def __init__(self):
        self._bridge = AsyncBridge()
        self._thread: threading.Thread | None = None
        self._running = False
        self._collecting = threading.Event()
        self._stop_event = threading.Event()
        self._interval = 0.1  # 100ms default
        self._device = None
        self._runtime = None
        self._read_lock = threading.Lock()
        self._origin_us: int | None = None

    @property
    def running(self) -> bool:
        return self._running and not self._stop_event.is_set()

    def prepare(self, device) -> None:
        """Build runtime from DWARF info so search/add work before collection starts."""
        if self._runtime is not None:
            return
        self._device = device
        dwarf_info = getattr(device, "_dwarf_info", None)
        svd_registers = {}
        try:
            from mklink.superwatch import find_project_svd, load_svd_registers
            project_root = getattr(device, "_project_root", ".")
            svd_path = find_project_svd(project_root)
            if svd_path:
                svd_registers = load_svd_registers(svd_path)
        except Exception:
            pass
        from mklink.superwatch import SuperWatchRuntime
        self._runtime = SuperWatchRuntime(
            items=[],
            dwarf_info=dwarf_info,
            svd_registers=svd_registers,
            port=getattr(device, "_port", None),
            read_lock=self._read_lock,
        )

    def start(self, device) -> None:
        if self._thread is not None and self._thread.is_alive():
            if self.running:
                return
            raise RuntimeError("SuperWatch worker thread is still active")
        self.prepare(device)
        stop_event = threading.Event()
        generation = object()
        self._stop_event = stop_event
        self._generation = generation
        self._collecting.set()
        self._running = True
        self._origin_us = None

        def _poll():
            try:
                while not stop_event.is_set():
                    if not self._collecting.is_set() or not self._runtime.items:
                        time.sleep(0.5)
                        continue
                    t0 = time.monotonic()
                    try:
                        from mklink.superwatch import sample_blocks
                        with self._read_lock:
                            result = sample_blocks(
                                self._runtime.blocks,
                                origin_us=self._origin_us,
                                bridge=device._bridge,
                            )
                        self._origin_us = result.origin_us
                        for point in result.points:
                            self._bridge.put({"event": "data", **point})
                    except Exception as e:
                        logger.debug("SuperWatch poll error: %s", e)
                        self._bridge.put({"event": "error", "message": str(e)})
                    elapsed = time.monotonic() - t0
                    remaining = max(0.0, self._interval - elapsed)
                    stop_event.wait(timeout=remaining)
            except Exception as e:
                logger.error("SuperWatch stream error: %s", e)
                self._bridge.put({"event": "error", "message": str(e)})
            finally:
                if getattr(self, "_generation", None) is generation:
                    self._running = False
                    self._bridge.put({"event": "stopped"})
                    self._bridge.stop()

        self._thread = threading.Thread(target=_poll, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        thread = self._thread
        self._stop_event.set()
        self._collecting.clear()
        if thread:
            thread.join(timeout=timeout)
            if thread.is_alive():
                raise TimeoutError("SuperWatch worker thread is still active")
        self._running = False
        if self._thread is thread:
            self._thread = None
        return True

    def add_watch(self, name: str) -> dict:
        if self._runtime is None:
            return {"error": "SuperWatch not started"}
        result = self._runtime.add(name)
        return {"item": result}

    def remove_watch(self, name: str) -> dict:
        if self._runtime is None:
            return {"error": "SuperWatch not started"}
        result = self._runtime.remove(name)
        return {"item": result}

    def search(self, query: str) -> list[dict]:
        if self._runtime is None:
            return []
        return self._runtime.search(query)

    def pause(self) -> None:
        self._collecting.clear()

    def resume(self) -> None:
        self._collecting.set()

    def start_collecting(self) -> None:
        self._collecting.set()

    def set_interval(self, interval: float) -> float:
        self._interval = max(0.0, min(60.0, interval))
        return self._interval

    def get_status(self) -> dict:
        if self._collecting.is_set():
            state = "running"
        elif self._running:
            state = "paused"
        else:
            state = "stopped"
        return {
            "state": state,
            "interval": self._interval,
            "items": self.list_watches(),
        }

    def list_watches(self) -> list[dict]:
        if self._runtime is None:
            return []
        from mklink.superwatch import make_channel_metadata
        meta = make_channel_metadata(self._runtime.items)
        return [{"name": item.name, **meta.get(item.name, {})} for item in self._runtime.items]

    def inspect(self, name: str) -> dict | None:
        if self._runtime is None or not self._device:
            return None
        try:
            return self._runtime.inspect(name)
        except Exception as e:
            logger.warning("SuperWatch inspect error for %s: %s", name, e)
            return None

    async def sse_generator(self):
        q = self._bridge.add_client()
        # Send initial channel metadata for already-added variables
        if self._runtime and self._runtime.items:
            from mklink.superwatch import make_channel_metadata
            meta = make_channel_metadata(self._runtime.items)
            yield _sse_json({"event": "channel_metadata", "channels": meta})
        state = "running" if self._collecting.is_set() else ("paused" if self._running else "stopped")
        yield _sse_json({"event": "state_change", "state": state, "items": self.list_watches()})
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield _sse_format("", event="ping")
                    continue
                if data is None:
                    break
                yield _sse_json(data)
                if data.get("event") == "stopped":
                    break
        finally:
            self._bridge.remove_client(q)


# ---------------------------------------------------------------------------
# Serial SSE Generator
# ---------------------------------------------------------------------------

class SerialStreamManager:
    """Manages serial port monitoring with SSE output."""

    def __init__(self):
        self._bridge = AsyncBridge()
        self._monitor = None
        self._running = False
        self._port_config: dict = {}
        self._profile: dict | None = None
        self._auto_reply_rules: list[dict] | None = None
        self._rx_count = 0
        self._tx_count = 0
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._start_time = 0.0

    @property
    def running(self) -> bool:
        return self._running

    def start(self, ports: list[dict], profile: dict | None = None,
              auto_reply_rules: list[dict] | None = None) -> None:
        if self._running:
            return

        from mklink.serial._monitor import SerialMonitor

        self._port_config = ports
        self._profile = profile
        self._auto_reply_rules = auto_reply_rules
        self._rx_count = 0
        self._tx_count = 0
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._start_time = time.time()

        def _event_callback(event):
            ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
            ms = int((event.timestamp % 1) * 1000)
            raw_hex = event.raw.hex().upper()
            try:
                ascii_repr = event.raw.decode("ascii", errors="replace")
            except Exception:
                ascii_repr = ""

            fields = {}
            crc_valid = None
            if event.parsed:
                crc_valid = event.parsed.crc_valid
                if event.parsed.fields:
                    for k, v in event.parsed.fields.items():
                        if isinstance(v, dict):
                            fields[k] = {"value": v.get("value", ""), "unit": v.get("unit", "")}
                        else:
                            fields[k] = {"value": str(v), "unit": ""}

            if event.direction == "RX":
                self._rx_count += 1
                self._rx_bytes += len(event.raw)
            else:
                self._tx_count += 1
                self._tx_bytes += len(event.raw)

            self._bridge.put({
                "event": "data",
                "timestamp": f"{ts}.{ms:03d}",
                "port": event.port,
                "direction": event.direction,
                "raw_hex": raw_hex,
                "ascii": ascii_repr,
                "fields": fields,
                "crc_valid": crc_valid,
            })

        self._monitor = SerialMonitor(
            ports=ports,
            profile=profile,
            auto_reply_rules=auto_reply_rules,
            event_callback=_event_callback,
        )
        self._monitor.start()
        self._running = True
        self._bridge.put({"event": "status", "ports": {cfg["port"]: "open" for cfg in ports}})

    def stop(self) -> None:
        if self._monitor:
            self._monitor.stop()
            self._monitor = None
        self._running = False
        self._bridge.put({"event": "stopped"})
        self._bridge.stop()

    def send(self, port: str, data: bytes) -> bool:
        if not self._monitor:
            return False
        return self._monitor.send(port, data)

    def send_all(self, data: bytes) -> None:
        if self._monitor:
            self._monitor.send_all(data)

    def get_status(self) -> dict:
        elapsed = max(time.time() - self._start_time, 1.0)
        ports = {}
        if self._monitor:
            ports = self._monitor.port_status
        return {
            "running": self._running,
            "ports": ports,
            "stats": {
                "rx_count": self._rx_count,
                "tx_count": self._tx_count,
                "rx_bytes": self._rx_bytes,
                "tx_bytes": self._tx_bytes,
                "bytes_per_sec": round((self._rx_bytes + self._tx_bytes) / elapsed, 1),
            },
        }

    async def sse_generator(self):
        q = self._bridge.add_client()
        yield _sse_json({"event": "status", **self.get_status()})
        try:
            while self.running:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield _sse_format("", event="ping")
                    continue
                if data is None:
                    break
                yield _sse_json(data)
                if data.get("event") == "stopped":
                    break
        finally:
            self._bridge.remove_client(q)


# ---------------------------------------------------------------------------
# Modbus SSE Generator
# ---------------------------------------------------------------------------

class ModbusStreamManager:
    """Manages Modbus register polling with SSE output."""

    def __init__(self):
        self._bridge = AsyncBridge()
        self._thread: threading.Thread | None = None
        self._running = False
        self._client = None
        self._slave: int = 1
        self._specs: list = []
        self._interval: float = 1.0
        self._stop_event = threading.Event()
        self._history: list[dict] = []
        self._max_history = 500
        self._latest: dict = {}

    @property
    def running(self) -> bool:
        return self._running

    def start(self, client, slave: int, registers: list[dict] | None = None,
              interval: float = 1.0) -> None:
        """Start Modbus register polling.

        Args:
            client: ModbusClient instance
            slave: Slave address
            registers: List of {addr, type?, name?} dicts. If None, reads 0-9.
            interval: Polling interval in seconds
        """
        if self._running:
            return

        self._client = client
        self._slave = slave
        self._interval = interval
        self._stop_event.clear()
        self._latest = {}

        if registers:
            from mklink.modbus._format import RegisterSpec
            self._specs = [
                RegisterSpec(
                    addr=r["addr"],
                    type=r.get("type", "uint16"),
                    name=r.get("name", ""),
                ) for r in registers
            ]
        else:
            from mklink.modbus._format import RegisterSpec
            self._specs = [RegisterSpec(addr=i, type="uint16", name=f"R{i}")
                           for i in range(10)]

        self._running = True

        def _poll():
            from mklink.modbus._format import registers_to_values
            from mklink.modbus._poller import _group_consecutive
            try:
                while not self._stop_event.is_set():
                    now = time.time()
                    try:
                        result: dict[str, Any] = {"_t": now, "registers": {}}
                        groups = _group_consecutive(self._specs)
                        for group in groups:
                            start_addr = group[0].addr
                            count = sum(s.reg_count for s in group)
                            n = min(count, 125)
                            regs = self._client.read_holding_registers(
                                start_addr, n, self._slave
                            )
                            for spec in group:
                                offset = spec.addr - start_addr
                                if 0 <= offset + spec.reg_count <= len(regs):
                                    raw = regs[offset:offset + spec.reg_count]
                                    vals = registers_to_values(raw, spec.type)
                                    if vals:
                                        result["registers"][spec.addr] = {
                                            "value": vals[0],
                                            "name": spec.name,
                                            "type": spec.type,
                                        }
                        self._latest = result
                        self._bridge.put({"event": "data", **result})
                        self._history.append(result)
                        if len(self._history) > self._max_history:
                            self._history = self._history[-self._max_history:]
                    except Exception as e:
                        logger.debug("Modbus poll error: %s", e)
                        self._bridge.put({"event": "error", "message": str(e)})
                    self._stop_event.wait(self._interval)
            except Exception as e:
                logger.error("Modbus stream error: %s", e)
                self._bridge.put({"event": "error", "message": str(e)})
            finally:
                self._running = False
                self._bridge.put({"event": "stopped"})
                self._bridge.stop()

        self._thread = threading.Thread(target=_poll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._running = False
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

    def write_register(self, addr: int, value: int) -> dict:
        if not self._client:
            raise RuntimeError("Modbus not connected")
        self._client.write_register(addr, value, self._slave)
        return {"addr": addr, "value": value, "ok": True}

    def read_debug(self, fc: int, start: int, quantity: int) -> list:
        if not self._client:
            raise RuntimeError("Modbus not connected")
        if fc == 3:
            return self._client.read_holding_registers(start, quantity, self._slave)
        elif fc == 4:
            return self._client.read_input_registers(start, quantity, self._slave)
        elif fc == 1:
            return self._client.read_coils(start, quantity, self._slave)
        elif fc == 2:
            return self._client.read_discrete_inputs(start, quantity, self._slave)
        raise ValueError(f"Unsupported FC: {fc}")

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "slave": self._slave,
            "interval": self._interval,
            "register_count": len(self._specs),
            "clients": self._bridge.client_count,
            "latest": self._latest,
        }

    async def sse_generator(self):
        q = self._bridge.add_client()
        yield _sse_json({"event": "status", **self.get_status()})
        if self._history:
            yield _sse_json({"event": "history", "points": self._history[-100:]})
        try:
            while self.running:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield _sse_format("", event="ping")
                    continue
                if data is None:
                    break
                yield _sse_json(data)
                if data.get("event") == "stopped":
                    break
        finally:
            self._bridge.remove_client(q)


# ---------------------------------------------------------------------------
# VOFA+ JustFloat SSE Generator
# ---------------------------------------------------------------------------

def normalize_vofa_interval(interval: float) -> float:
    """Return a finite supported VOFA interval without silently accepting invalid input."""
    try:
        value = float(interval)
    except (TypeError, ValueError):
        raise ValueError("VOFA interval must be a finite number") from None
    if not math.isfinite(value) or value <= 0 or value > 60.0:
        raise ValueError("VOFA interval must be finite and in the range (0, 60]")
    return max(0.000001, value)


class VofaStreamManager:
    """Manages VOFA+ JustFloat variable streaming via memory reads.

    Reads device RAM at specified addresses, interprets as floats,
    and streams the data via SSE for the VofaTab chart.
    """

    def __init__(
        self,
        stream_hub=None,
        *,
        batch_samples: int = 32,
        clock=time.perf_counter,
    ):
        self._bridge = AsyncBridge()
        self._thread: threading.Thread | None = None
        self._running = False
        self._paused = threading.Event()
        self._paused.set()
        self._stop_event = threading.Event()
        self._channels: list[dict] = []  # [{name, addr, type, size}]
        self._interval: float = 0.1  # seconds
        self._history: list[dict] = []
        self._max_history = 500
        self._stream_hub = stream_hub
        self._batch_samples = max(1, int(batch_samples))
        self._clock = clock
        self._read_groups = []
        self._pending_samples: list[tuple[float, ...]] = []
        self._completed_samples = 0
        self._completed_reads = 0
        self._read_errors = 0
        self._rate_timestamps = deque()
        self._actual_rate = 0.0

    @property
    def running(self) -> bool:
        return self._running and not self._stop_event.is_set()

    @property
    def paused(self) -> bool:
        return not self._paused.is_set()

    def set_stream_hub(self, stream_hub) -> None:
        self._stream_hub = stream_hub

    def detach_stream_hub(self, stream_hub) -> None:
        if self._stream_hub is stream_hub:
            self._stream_hub = None

    def configure(self, channels: list[dict], interval: float | None = None) -> None:
        from mklink.vofa_viewer import build_vofa_read_groups, normalize_vofa_channels

        normalized_interval = (
            self._interval if interval is None else normalize_vofa_interval(interval)
        )
        normalized = normalize_vofa_channels(channels)
        read_groups = build_vofa_read_groups(normalized)
        self._channels = normalized
        self._interval = normalized_interval
        self._read_groups = read_groups
        self._pending_samples.clear()
        self._completed_samples = 0
        self._completed_reads = 0
        self._read_errors = 0
        self._rate_timestamps.clear()
        self._actual_rate = 0.0

    def collect_cycle(self, device) -> bool:
        import struct as _struct

        unpack = {
            "float": ("<f", 4), "fp32": ("<f", 4),
            "int32_t": ("<i", 4), "int32": ("<i", 4),
            "uint32_t": ("<I", 4), "uint32": ("<I", 4),
            "int16_t": ("<h", 2), "int16": ("<h", 2),
            "uint16_t": ("<H", 2), "uint16": ("<H", 2),
            "int8_t": ("<b", 1), "int8": ("<b", 1),
            "uint8_t": ("<B", 1), "uint8": ("<B", 1),
            "bool": ("<?", 1), "boolean": ("<?", 1),
        }
        values = [None] * len(self._channels)
        try:
            for group in self._read_groups:
                raw = device.read_memory(group.address, group.size)
                self._completed_reads += 1
                if len(raw) != group.size:
                    raise ValueError("non-exact VOFA memory read")
                for channel in group.channels:
                    fmt, width = unpack.get(channel.type_name, ("<f", 4))
                    start = channel.offset
                    values[channel.channel_index] = _struct.unpack(
                        fmt, raw[start:start + width],
                    )[0]
        except Exception:
            self._read_errors += 1
            return False
        if any(value is None for value in values):
            self._read_errors += 1
            return False
        sample = tuple(
            number if math.isfinite(number) else 0.0
            for number in (float(value) for value in values)
        )
        self._completed_samples += 1
        completed_at = self._clock()
        self._rate_timestamps.append(completed_at)
        cutoff = completed_at - 1.0
        while self._rate_timestamps and self._rate_timestamps[0] < cutoff:
            self._rate_timestamps.popleft()
        if len(self._rate_timestamps) >= 2:
            elapsed = self._rate_timestamps[-1] - self._rate_timestamps[0]
            self._actual_rate = (
                (len(self._rate_timestamps) - 1) / elapsed if elapsed > 0 else 0.0
            )
        else:
            self._actual_rate = 0.0
        point = {"_t": time.time()}
        point.update({
            channel["name"]: sample[index]
            for index, channel in enumerate(self._channels)
        })
        self._bridge.put({"event": "data", **point})
        self._history.append(point)
        if len(self._history) > self._max_history:
            del self._history[:-self._max_history]
        self._pending_samples.append(sample)
        if len(self._pending_samples) >= self._batch_samples:
            self._flush_binary_batch()
        return True

    def publish_samples(self, samples) -> None:
        from mklink.vofa_viewer import (
            VOFA_SAMPLE_MAJOR_FLOAT32,
            encode_vofa_samples,
        )

        rows = [tuple(row) for row in samples]
        if not rows or self._stream_hub is None:
            return
        self._stream_hub.publish(
            encode_vofa_samples(rows), item_count=len(rows),
            flags=VOFA_SAMPLE_MAJOR_FLOAT32,
        )

    def _flush_binary_batch(self) -> None:
        if not self._pending_samples:
            return
        pending = self._pending_samples
        self._pending_samples = []
        self.publish_samples(pending)

    def start(self, device, channels: list[dict], interval: float = 0.1) -> None:
        """Start VOFA polling.

        Args:
            device: Device instance with read_memory()
            channels: List of {name, addr (int or hex str), type?, size?}
            interval: Polling interval in seconds
        """
        if self._thread is not None and self._thread.is_alive():
            if self.running:
                return
            raise RuntimeError("VOFA worker thread is still active")

        self.configure(channels, interval)
        stop_event = threading.Event()
        generation = object()
        self._stop_event = stop_event
        self._generation = generation
        self._paused.set()
        self._running = True
        self._history.clear()

        def _poll():
            try:
                while not stop_event.is_set():
                    if not self._paused.is_set():
                        stop_event.wait(self._interval)
                        continue

                    self.collect_cycle(device)
                    stop_event.wait(self._interval)

            except Exception as e:
                logger.error("VOFA stream error: %s", e)
                self._bridge.put({"event": "error", "message": str(e)})
            finally:
                if getattr(self, "_generation", None) is generation:
                    self._running = False
                    self._bridge.put({"event": "stopped"})
                    self._bridge.stop()

        self._thread = threading.Thread(target=_poll, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        thread = self._thread
        self._stop_event.set()
        if thread:
            thread.join(timeout=timeout)
            if thread.is_alive():
                raise TimeoutError("VOFA worker thread is still active")
        self._running = False
        self._flush_binary_batch()
        if self._thread is thread:
            self._thread = None
        return True

    def pause(self) -> None:
        self._paused.clear()
        self._rate_timestamps.clear()
        self._actual_rate = 0.0

    def resume(self) -> None:
        self._rate_timestamps.clear()
        self._actual_rate = 0.0
        self._paused.set()

    def set_interval(self, interval: float) -> float:
        self._interval = normalize_vofa_interval(interval)
        return self._interval

    def get_status(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "channels": self._channels,
            "interval": self._interval,
            "clients": self._bridge.client_count,
            "history_size": len(self._history),
            "completed_samples": self._completed_samples,
            "completed_reads": self._completed_reads,
            "read_errors": self._read_errors,
            "actual_rate": round(self._actual_rate, 6),
            "layout": "sample-major-float32",
        }

    async def sse_generator(self):
        q = self._bridge.add_client()
        yield _sse_json({"event": "status", **self.get_status()})
        if self._history:
            yield _sse_json({"event": "history", "points": self._history[-100:]})
        try:
            while self.running or self.paused:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield _sse_format("", event="ping")
                    continue
                if data is None:
                    break
                yield _sse_json(data)
                if data.get("event") == "stopped":
                    break
        finally:
            self._bridge.remove_client(q)


# ---------------------------------------------------------------------------
# Global stream managers (keyed by state in api.py)
# ---------------------------------------------------------------------------

_managers: dict[str, Any] = {}

BRIDGE_DASHBOARD_TYPES = ("rtt", "superwatch", "vofa", "systemview")


def get_managers() -> dict[str, Any]:
    """Get or create stream manager singletons."""
    if "rtt" not in _managers:
        _managers["rtt"] = RttStreamManager()
    if "superwatch" not in _managers:
        _managers["superwatch"] = SuperWatchStreamManager()
    if "serial" not in _managers:
        _managers["serial"] = SerialStreamManager()
    if "modbus" not in _managers:
        _managers["modbus"] = ModbusStreamManager()
    if "vofa" not in _managers:
        _managers["vofa"] = VofaStreamManager()
    if "systemview" not in _managers:
        _managers["systemview"] = SystemViewStreamManager()
    return _managers


def stop_bridge_dashboards(
    exclude: str | None = None,
    resource_manager=None,
) -> list[str]:
    """停止所有使用 MKLink Bridge 的 Dashboard（RTT/SuperWatch/VOFA）。
    返回被停止的 Dashboard 名称列表。"""
    stopped = []
    managers = get_managers()
    for name in BRIDGE_DASHBOARD_TYPES:
        if name == exclude:
            continue
        mgr = managers.get(name)
        if mgr and mgr.running:
            error = None
            try:
                mgr.stop()
            except Exception as exc:
                error = exc
            thread = getattr(mgr, "_thread", None)
            alive = thread.is_alive() if thread is not None else bool(mgr.running)
            if alive:
                raise TimeoutError(
                    f"{name} worker thread is still active"
                ) from error
            if resource_manager is not None:
                resource_manager.release(f"user:dashboard:{name}")
            if error is not None:
                raise error
            stopped.append(name)
    return stopped
