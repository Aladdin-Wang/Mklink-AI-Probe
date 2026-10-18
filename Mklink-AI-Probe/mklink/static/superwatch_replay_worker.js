import { parseReplayFile, replayView, replayRange } from './superwatch_replay_data.js';
let data = null;
self.onmessage = async ({ data: message }) => {
  try {
    if (message.type === 'load') {
      data = null;
      let last = 0;
      data = await parseReplayFile(message.file, fraction => {
        if (performance.now() - last > 100) { last = performance.now(); self.postMessage({ type: 'progress', fraction }); }
      });
      self.postMessage({ type: 'loaded', duration: data.duration, rows: data.rows, values: data.values,
        origin: data.origin, format: data.format, writeEvents: data.writeEvents,
        overview: replayRange(data, 0, data.duration, data.duration, 512, data.channels.map(c => c.name), false).channels,
        channels: data.channels.map(c => ({ name: c.name, count: c.times.length })) });
    } else if (message.type === 'view' && data) {
      self.postMessage({ type: 'view', id: message.id, ...replayView(data, message.position, message.span, message.width, message.names) });
    } else if (message.type === 'range' && data) {
      self.postMessage({ type: 'view', id: message.id, ...replayRange(data, message.start, message.end, message.position, message.width, message.names, message.playing) });
    }
  } catch (error) { data = null; self.postMessage({ type: 'error', message: error.message }); }
};
