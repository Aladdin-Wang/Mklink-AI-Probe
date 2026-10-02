// Shared by the desktop and standalone viewers. All parsing runs in a Worker.
export const REPLAY_LIMITS = { bytes: 256 * 1024 * 1024, values: 8_000_000, channels: 64, line: 1024 * 1024 };
const CHUNK = 4096;
const BLOCK = 256;

export function csvCells(line, delimiter) {
  const cells = []; let cell = '', quoted = false, closed = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') { quoted = false; closed = true; }
      else cell += c;
    } else if (c === delimiter) { cells.push(cell.trim()); cell = ''; closed = false; }
    else if (c === '"' && !cell && !closed) quoted = true;
    else if (c === '"') throw new Error('Quote inside unquoted CSV field');
    else if (closed && c.trim()) throw new Error('Invalid CSV quoting');
    else cell += c;
  }
  if (quoted) throw new Error('Unclosed CSV quote (multiline fields are not supported)');
  cells.push(cell.trim());
  return cells;
}

function numberValue(raw) {
  if (raw === true || raw === 'true') return 1;
  if (raw === false || raw === 'false') return 0;
  if (typeof raw !== 'number' && (typeof raw !== 'string' || !raw.trim())) throw new Error('Missing numeric value');
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error('Non-finite or invalid numeric value');
  return value;
}

function timestamp(raw, scale = 1) {
  if (raw === '' || raw === null || raw === undefined || typeof raw === 'boolean') throw new Error('Missing or invalid timestamp');
  return numberValue(raw) * scale;
}

class Channel {
  constructor(name) { this.name = name; this.parts = []; this.count = 0; }
  add(t, v) {
    const last = this.count - 1;
    if (last >= 0) {
      const part = this.parts[Math.floor(last / CHUNK)];
      if (part.times[last % CHUNK] === t) { part.values[last % CHUNK] = v; return false; }
    }
    if (this.count % CHUNK === 0) this.parts.push({ times: new Float64Array(CHUNK), values: new Float64Array(CHUNK) });
    const part = this.parts[Math.floor(this.count / CHUNK)];
    part.times[this.count % CHUNK] = t; part.values[this.count % CHUNK] = v; this.count++;
    return true;
  }
  finish(origin) {
    const times = new Float64Array(this.count), values = new Float64Array(this.count);
    this.parts.forEach((part, i) => {
      const size = Math.min(CHUNK, this.count - i * CHUNK);
      times.set(part.times.subarray(0, size), i * CHUNK);
      values.set(part.values.subarray(0, size), i * CHUNK);
    });
    this.parts = [];
    const mins = [], maxs = [];
    for (let i = 0; i < times.length; i++) {
      times[i] -= origin;
      const b = Math.floor(i / BLOCK);
      if (mins[b] === undefined || values[i] < values[mins[b]]) mins[b] = i;
      if (maxs[b] === undefined || values[i] > values[maxs[b]]) maxs[b] = i;
    }
    return { name: this.name, times, values, mins: Uint32Array.from(mins), maxs: Uint32Array.from(maxs) };
  }
}

export class ReplayParser {
  constructor() {
    this.format = ''; this.header = null; this.channels = new Map(); this.lineNumber = 0;
    this.rows = 0; this.values = 0; this.origin = null; this.end = null;
  }
  line(raw) {
    this.lineNumber++;
    const line = raw.replace(/^\uFEFF/, '').trim();
    if (!line) return;
    try {
      if (line.length > REPLAY_LIMITS.line) throw new Error('Line exceeds 1 MiB');
      if (!this.format) this.format = line.startsWith('{') ? 'jsonl' : line.startsWith('[') ? 'raw' : 'csv';
      let time, fields;
      if (this.format === 'csv') {
        if (!this.header) {
          const candidates = [',', ';', '\t'].map(delimiter => {
            try { return { delimiter, count: csvCells(line, delimiter).length }; }
            catch { return { delimiter, count: 0 }; }
          }).sort((a, b) => b.count - a.count);
          this.delimiter = candidates[0].delimiter;
          this.header = csvCells(line, this.delimiter);
          const scales = { timestamp: 1, _t: 1, timestamp_s: 1, time: 1, 'time(s)': 1, timestamp_ms: .001, timestamp_us: .000001 };
          this.timeColumn = this.header.findIndex(name => Object.hasOwn(scales, name.toLowerCase()));
          if (this.timeColumn < 0) throw new Error('CSV requires a timestamp column (seconds, timestamp_ms or timestamp_us)');
          this.scale = scales[this.header[this.timeColumn].toLowerCase()];
          if (this.header.length < 2 || this.header.some(name => !name) || new Set(this.header).size !== this.header.length) throw new Error('Empty or duplicate channel name');
          if (this.header.length - 1 > REPLAY_LIMITS.channels) throw new Error('At most 64 channels are supported');
          return;
        }
        const row = csvCells(line, this.delimiter);
        if (row.length !== this.header.length) throw new Error('CSV column count mismatch');
        time = timestamp(row[this.timeColumn], this.scale);
        fields = this.header.flatMap((name, i) => i === this.timeColumn || row[i] === '' ? [] : [[name, numberValue(row[i])]]);
      } else if (this.format === 'jsonl') {
        const point = JSON.parse(line);
        time = point._t !== undefined ? timestamp(point._t) : timestamp(point.timestamp_us, .000001);
        fields = Object.entries(point).filter(([name]) => !['_t', 'timestamp_us'].includes(name)).map(([name, value]) => [name, numberValue(value)]);
      } else {
        const match = /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]\s+(.+)$/.exec(line);
        if (!match) throw new Error('Expected [YYYY-MM-DD HH:mm:ss.SSS] name=value, ...');
        // Treat display timestamps as a fixed local clock; DST must not reorder rows.
        time = Date.parse(match[1].replace(' ', 'T') + 'Z') / 1000;
        fields = match[2].split(',').map(field => {
          const equals = field.lastIndexOf('=');
          if (equals < 1) throw new Error('Expected name=value');
          return [field.slice(0, equals).trim(), numberValue(field.slice(equals + 1))];
        });
      }
      if (!Number.isFinite(time)) throw new Error('Invalid timestamp');
      if (this.origin !== null && !Number.isFinite(time - this.origin)) throw new Error('Timestamp range overflow');
      if (this.end !== null && time < this.end) throw new Error('Timestamps moved backwards; split restarted sessions into separate logs');
      if (!fields.length) throw new Error('Sample has no variable values');
      if (new Set(fields.map(([name]) => name)).size !== fields.length) throw new Error('Duplicate channel name');
      for (const [name, value] of fields) {
        if (!name || name.length > 512) throw new Error('Invalid channel name');
        if (!this.channels.has(name)) {
          if (this.channels.size >= REPLAY_LIMITS.channels) throw new Error('At most 64 channels are supported');
          this.channels.set(name, new Channel(name));
        }
        if (this.channels.get(name).add(time, value)) this.values++;
        if (this.values > REPLAY_LIMITS.values) throw new Error('Log exceeds 8 million numeric values; split the file');
      }
      if (this.origin === null) this.origin = time;
      this.end = time; this.rows++;
    } catch (error) { throw new Error(`Line ${this.lineNumber}: ${error.message}`); }
  }
  finish() {
    if (!this.rows) throw new Error('No samples in file');
    return { channels: [...this.channels.values()].map(channel => channel.finish(this.origin)),
      duration: this.end - this.origin, origin: this.origin, rows: this.rows, values: this.values, format: this.format };
  }
}

export async function parseReplayFile(file, progress = () => {}) {
  if (!file.size) throw new Error('Empty file');
  if (file.size > REPLAY_LIMITS.bytes) throw new Error('File exceeds 256 MiB; split the file');
  const parser = new ReplayParser(), reader = file.stream().getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let pending = '', bytes = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let offset = 0, newline;
      while ((newline = pending.indexOf('\n', offset)) >= 0) {
        parser.line(pending.slice(offset, newline)); offset = newline + 1;
      }
      pending = pending.slice(offset);
      if (pending.length > REPLAY_LIMITS.line) throw new Error('Line exceeds 1 MiB');
      if (done) break;
      bytes += value.byteLength; progress(bytes / file.size);
    }
    if (pending) parser.line(pending);
    return parser.finish();
  } finally { await reader.cancel(); reader.releaseLock(); }
}

export function lowerBound(times, value, inclusive = false) {
  let lo = 0, hi = times.length;
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (times[mid] < value || (inclusive && times[mid] === value)) lo = mid + 1; else hi = mid; }
  return lo;
}

function extrema(channel, from, to) {
  let min = from, max = from, i = from;
  const take = index => { if (channel.values[index] < channel.values[min]) min = index; if (channel.values[index] > channel.values[max]) max = index; };
  while (i < to) {
    if (i % BLOCK === 0 && i + BLOCK <= to) { take(channel.mins[i / BLOCK]); take(channel.maxs[i / BLOCK]); i += BLOCK; }
    else take(i++);
  }
  return [min, max].sort((a, b) => a - b);
}

export function replayView(data, position, span, width, names) {
  const end = Math.max(0, Math.min(data.duration, position));
  const start = Math.max(0, end - span);
  const displayEnd = Math.max(end, Math.min(data.duration, span), .001);
  const pixels = Math.max(1, Math.min(2048, Math.floor(width)));
  return { start, end: displayEnd, position: end, channels: data.channels.filter(c => names.includes(c.name)).map(c => {
    const from = lowerBound(c.times, start), to = lowerBound(c.times, end, true), points = [];
    if (to - from <= pixels * 2) { for (let i = from; i < to; i++) points.push([c.times[i], c.values[i]]); }
    else {
      let a = from;
      for (let x = 0; x < pixels && a < to; x++) {
        const b = Math.min(to, lowerBound(c.times, start + (displayEnd - start) * (x + 1) / pixels, true));
        if (b > a) { for (const i of extrema(c, a, b)) points.push([c.times[i], c.values[i]]); a = b; }
      }
    }
    const last = lowerBound(c.times, end, true) - 1;
    return { name: c.name, points, latest: last >= 0 ? c.values[last] : null };
  }) };
}
