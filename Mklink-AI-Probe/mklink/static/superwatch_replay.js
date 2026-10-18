// Offline logs use the existing SuperWatch renderer and all of its chart tools.
export function mountReplayButton(host, options = {}) {
  const en = options.language === 'en', tr = (zh, english) => en ? english : zh;
  const viewer = () => window.__waveformViewers?.SuperWatch;
  const open = document.createElement('button');
  open.type = 'button'; open.className = 'panel-btn'; open.dataset.testid = 'open-superwatch-replay';
  open.textContent = tr('加载日志', 'Load log');
  const input = document.createElement('input');
  input.type = 'file'; input.accept = '.csv,.txt,.log,.jsonl,.ndjson'; input.hidden = true; input.dataset.testid = 'replay-file';
  host.append(open, input);
  const bar = document.createElement('div');
  bar.className = 'sw-replay-inline'; bar.hidden = true;
  bar.innerHTML = `<span class="sw-replay-name"></span><label>${tr('速度', 'Speed')} <select data-action="speed">${[.25,.5,1,2,4,8,16].map(v => `<option value="${v}" ${v === 1 ? 'selected' : ''}>${v}×</option>`).join('')}</select></label><input type="range" data-testid="replay-seek" min="0" max="1" step="0.001" value="0" aria-label="${tr('回放进度', 'Replay position')}"><span data-testid="replay-time"></span><button type="button" class="panel-btn" data-action="live">${tr('返回实时', 'Return to live')}</button><span class="sw-replay-message" role="status"></span>`;
  const root = host.closest('.waveform-viewer') || host.closest('header')?.parentElement || host;
  const toolbar = root.querySelector('.watch-toolbar-row') || root.querySelector('#control-toolbar');
  if (toolbar) toolbar.after(bar); else root.append(bar);
  const seek = bar.querySelector('[data-testid=replay-seek]'), speed = bar.querySelector('select');
  const message = bar.querySelector('.sw-replay-message'), name = bar.querySelector('.sw-replay-name');
  let worker = null, metadata = null, position = 0, playing = false, frame = 0, previous = 0;
  let generation = 0, requestId = 0, inFlight = null, pending = false, disposed = false;
  let viewRevision = 0, requestedRevision = 0;
  function announce(channels, values = {}) { root.dispatchEvent(new CustomEvent('mklink:replay', { detail: { channels, values } })); }
  function update() {
    bar.dataset.playbackState = playing ? 'playing' : metadata && position >= metadata.duration ? 'ended' : 'paused';
    seek.value = String(position); seek.disabled = !metadata; speed.disabled = !metadata;
    bar.querySelector('[data-testid=replay-time]').textContent = `${position.toFixed(3)} / ${(metadata?.duration || 0).toFixed(3)} s`;
  }
  function request() {
    if (!worker || !metadata) return;
    if (inFlight !== null) { pending = true; return; }
    const range = viewer()?.getBinaryVisibleRange?.();
    if (!range) return;
    inFlight = ++requestId; pending = false;
    requestedRevision = viewRevision;
    worker.postMessage({ type: 'range', id: inFlight, start: range.start / 1000, end: range.end / 1000,
      position, playing, width: range.pixelWidth, names: metadata.channels.map(c => c.name) });
  }
  function paint(follow = true) { viewer()?.setReplayPosition?.(position, playing, follow); update(); request(); }
  function pause() { playing = false; cancelAnimationFrame(frame); frame = 0; }
  function tick(now) {
    if (!playing || !metadata) return;
    position = Math.min(metadata.duration, position + Math.max(0, now - previous) / 1000 * Number(speed.value));
    previous = now;
    if (position >= metadata.duration) pause();
    paint();
    if (playing) frame = requestAnimationFrame(tick);
  }
  function control(action) {
    if (!metadata) return;
    viewRevision++;
    if (action === 'play' || action === 'toggle' && !playing) {
      if (position >= metadata.duration) position = 0;
      playing = metadata.duration > 0; previous = performance.now();
      cancelAnimationFrame(frame); if (playing) frame = requestAnimationFrame(tick);
    } else {
      pause(); if (action === 'stop') position = 0;
    }
    paint(action !== 'inspect');
  }
  function clear() {
    generation++; pause(); worker?.terminate(); worker = null; metadata = null; position = 0;
    inFlight = null; pending = false; viewer()?.endReplay?.(); announce(null); update();
  }
  function error(text) { clear(); bar.hidden = false; message.textContent = text; }
  open.onclick = () => input.click();
  input.onchange = () => {
    const file = input.files?.[0]; input.value = ''; if (!file) return;
    clear(); bar.hidden = false; name.textContent = file.name; name.title = file.name;
    message.textContent = tr('正在读取…', 'Loading…'); host.closest('details')?.removeAttribute('open');
    const current = generation;
    try {
      worker = new Worker(new URL('./superwatch_replay_worker.js', import.meta.url), { type: 'module' });
      worker.onmessage = ({ data }) => {
        if (disposed || current !== generation) return;
        if (data.type === 'progress') message.textContent = `${tr('正在读取', 'Loading')} ${Math.round(data.fraction * 100)}%`;
        else if (data.type === 'loaded') {
          if (!viewer()?.beginReplay?.(data, control)) { error(tr('波形界面尚未就绪', 'Chart is not ready')); return; }
          metadata = data; seek.max = String(data.duration); message.textContent = ''; announce(data.channels.map(c => c.name)); paint();
        } else if (data.type === 'view' && data.id === inFlight) {
          inFlight = null;
          // A seek/pause during a worker request supersedes its old frame.
          if (requestedRevision === viewRevision) {
            viewer()?.renderReplayView?.(data);
            announce(metadata.channels.map(c => c.name), Object.fromEntries(data.channels.filter(c => c.latest !== null).map(c => [c.name, c.latest])));
          }
          if (pending) request();
        } else if (data.type === 'error') error(data.message);
      };
      worker.onerror = () => { if (current === generation) error(tr('日志读取失败', 'Could not read log')); };
      worker.postMessage({ type: 'load', file });
    } catch (caught) { error(String(caught)); }
  };
  seek.oninput = () => { viewRevision++; pause(); position = Math.max(0, Math.min(metadata?.duration || 0, Number(seek.value))); paint(); };
  speed.onchange = () => { previous = performance.now(); };
  bar.querySelector('[data-action=live]').onclick = () => { clear(); bar.hidden = true; };
  bar.addEventListener('keydown', event => event.stopPropagation());
  const resize = new ResizeObserver(() => { if (metadata) request(); }); resize.observe(root);
  update();
  return () => { disposed = true; clear(); resize.disconnect(); open.remove(); input.remove(); bar.remove(); };
}
