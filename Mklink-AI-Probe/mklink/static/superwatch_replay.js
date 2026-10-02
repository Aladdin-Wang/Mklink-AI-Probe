// File contents never leave the browser. The dialog owns its Worker and clock.
export function mountReplayButton(host, options = {}) {
  const en = options.language === 'en';
  const t = (zh, english) => en ? english : zh;
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'panel-btn'; button.dataset.testid = 'open-superwatch-replay';
  button.textContent = t('日志回放', 'Log replay');
  host.append(button);
  let closeDialog = null;
  button.onclick = () => {
    if (closeDialog) return;
    const dialog = document.createElement('dialog');
    dialog.className = 'sw-replay'; dialog.setAttribute('aria-label', t('SuperWatch 离线日志回放', 'SuperWatch offline log replay'));
    // Keep the live viewer's document shortcuts from handling replay controls.
    dialog.addEventListener('keydown', event => event.stopPropagation());
    dialog.innerHTML = `
      <div class="sw-replay-heading"><div><h2>SuperWatch · ${t('日志回放', 'Log replay')}</h2>
        <p>${t('本地离线查看 · 不修改设备或实时采样', 'Local offline viewer · Device and live acquisition remain unchanged')}</p></div>
        <button type="button" data-action="close">${t('返回实时页面', 'Return to live view')}</button></div>
      <div class="sw-replay-import"><label>${t('导入日志', 'Import log')}
        <input data-testid="replay-file" type="file" accept=".csv,.txt,.log,.jsonl,.ndjson"></label>
        <button type="button" data-action="cancel" hidden>${t('取消加载', 'Cancel loading')}</button>
        <span>${t('CSV / TXT / JSONL · 最大 256 MiB、64 通道、800 万数值', 'CSV / TXT / JSONL · Up to 256 MiB, 64 channels, 8M values')}</span></div>
      <div class="sw-replay-message" role="status" aria-live="polite">${t('请选择 SuperWatch 导出的带时间戳日志。无需连接设备。', 'Select a timestamped SuperWatch log. No device connection is required.')}</div>
      <progress class="sw-replay-progress" max="1" value="0" hidden></progress>
      <div class="sw-replay-controls">
        <button type="button" data-action="play" disabled>${t('播放', 'Play')}</button>
        <button type="button" data-action="restart" disabled>${t('重新播放', 'Restart')}</button>
        <label>${t('速度', 'Speed')} <select data-action="speed" disabled><option>0.25</option><option>0.5</option><option selected>1</option><option>2</option><option>4</option><option>8</option><option>16</option></select> ×</label>
        <label>${t('时间窗口', 'Window')} <select data-action="span" disabled><option value="2">2 s</option><option value="10" selected>10 s</option><option value="60">60 s</option><option value="all">${t('全部', 'All')}</option></select></label>
        <button type="button" data-action="overview" disabled>${t('查看全部', 'Show all')}</button>
        <output data-testid="replay-time">0.000 / 0.000 s</output>
        <span data-testid="replay-state">${t('未加载', 'No file')}</span>
      </div>
      <input class="sw-replay-seek" data-testid="replay-seek" type="range" min="0" max="1" step="any" value="0" disabled aria-label="${t('回放时间轴（秒）', 'Replay timeline (seconds)')}">
      <div class="sw-replay-content"><aside><div class="sw-replay-channel-heading">${t('通道（同时显示最多 16 路）', 'Channels (up to 16 visible)')}</div><div class="sw-replay-channels"></div></aside>
        <div class="sw-replay-chart-wrap"><canvas aria-label="${t('日志回放波形', 'Log replay waveforms')}" role="img"></canvas><p class="sw-replay-chart-hint">${t('拖动时间轴定位；滚轮缩放时间窗口。各通道纵轴独立。', 'Seek with the timeline; scroll to zoom time. Each channel has its own Y scale.')}</p></div></div>`;
    document.body.append(dialog);
    const $ = selector => dialog.querySelector(selector);
    const action = name => $(`[data-action="${name}"]`);
    const message = $('.sw-replay-message'), progress = $('.sw-replay-progress'), fileInput = $('[data-testid=replay-file]');
    const seek = $('[data-testid=replay-seek]'), time = $('[data-testid=replay-time]'), state = $('[data-testid=replay-state]');
    const canvas = $('canvas'), wrap = $('.sw-replay-chart-wrap'), context = canvas.getContext('2d');
    let worker = null, metadata = null, frame = null, disposed = false, playing = false, position = 0, speed = 1, span = 10;
    let request = 0, inFlight = false, pending = false, raf = 0, anchorClock = 0, anchorTime = 0, lastPaint = 0;
    const selected = new Set(), rows = new Map();
    const colors = ['#68b7ff', '#ffaf67', '#73d6a1', '#dc9bfa', '#e6d779', '#f58fa6', '#79d7d7', '#c9b9ff'];

    function status(text, error = false) { message.textContent = text; message.classList.toggle('error', error); }
    function controls(enabled) {
      for (const name of ['play', 'restart', 'speed', 'span', 'overview']) action(name).disabled = !enabled;
      seek.disabled = !enabled;
    }
    function renderClock() {
      time.textContent = `${position.toFixed(3)} / ${(metadata?.duration || 0).toFixed(3)} s`;
      seek.value = String(position);
      state.textContent = !metadata ? t('未加载', 'No file') : playing ? t('播放中', 'Playing') : position >= metadata.duration ? t('回放结束', 'Ended') : t('已暂停', 'Paused');
      dialog.dataset.playbackState = !metadata ? 'empty' : playing ? 'playing' : position >= metadata.duration ? 'ended' : 'paused';
      action('play').textContent = playing ? t('暂停', 'Pause') : t('播放', 'Play');
    }
    function requestView() {
      if (!worker || !metadata || disposed) return;
      if (inFlight) { pending = true; return; }
      inFlight = true; pending = false;
      worker.postMessage({ type: 'view', id: ++request, position, span,
        width: Math.max(1, wrap.clientWidth - 32), names: [...selected] });
    }
    function draw() {
      const width = Math.max(240, wrap.clientWidth - 24), height = Math.max(240, (frame?.channels.length || 1) * 110 + 30);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.floor(width * dpr); canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.fillStyle = '#0e151d'; context.fillRect(0, 0, width, height);
      context.font = '12px monospace';
      if (!frame?.channels.length) { context.fillStyle = '#aebccc'; context.fillText(t('导入日志并选择通道', 'Import a log and select channels'), 16, 36); return; }
      frame.channels.forEach((channel, index) => {
        const top = index * 110, left = 75, plotWidth = width - left - 12, color = colors[index % colors.length];
        let low = Infinity, high = -Infinity;
        for (const [, value] of channel.points) { low = Math.min(low, value); high = Math.max(high, value); }
        if (!Number.isFinite(low)) { low = 0; high = 1; }
        if (low === high) { low -= Math.max(1, Math.abs(low) * .05); high += Math.max(1, Math.abs(high) * .05); }
        context.save(); context.beginPath(); context.rect(0, top, width, 110); context.clip();
        context.fillStyle = color; context.fillText(channel.name, 10, top + 15, width - 20);
        context.fillStyle = '#96a8bb'; context.fillText(high.toPrecision(4), 6, top + 36); context.fillText(low.toPrecision(4), 6, top + 92);
        context.strokeStyle = '#2a3948'; context.beginPath(); context.moveTo(left, top + 26); context.lineTo(left, top + 94); context.lineTo(width - 10, top + 94); context.stroke();
        context.strokeStyle = color; context.beginPath();
        channel.points.forEach(([x, value], i) => {
          const px = left + (x - frame.start) / (frame.end - frame.start) * plotWidth;
          const py = top + 90 - (value - low) / (high - low) * 60;
          if (i) context.lineTo(px, py); else context.moveTo(px, py);
          if (channel.points.length === 1) context.fillRect(px - 2, py - 2, 4, 4);
        });
        context.stroke(); context.restore();
        const value = rows.get(channel.name)?.querySelector('output');
        if (value) value.textContent = channel.latest === null ? '—' : String(Number(channel.latest.toPrecision(9)));
      });
      context.fillStyle = '#aebccc'; context.fillText(frame.start.toFixed(3) + ' s', 75, height - 8);
      context.textAlign = 'right'; context.fillText(frame.end.toFixed(3) + ' s', width - 12, height - 8); context.textAlign = 'left';
      canvas.dataset.points = String(frame.channels.reduce((count, channel) => count + channel.points.length, 0));
      canvas.dataset.position = String(frame.position);
    }
    function tick(now) {
      if (!playing || disposed) return;
      position = Math.min(metadata.duration, anchorTime + (now - anchorClock) / 1000 * speed);
      if (now - lastPaint >= 33 || position >= metadata.duration) { lastPaint = now; renderClock(); requestView(); }
      if (position >= metadata.duration) { playing = false; renderClock(); return; }
      raf = requestAnimationFrame(tick);
    }
    function pause() {
      if (playing) position = Math.min(metadata.duration, anchorTime + (performance.now() - anchorClock) / 1000 * speed);
      playing = false; cancelAnimationFrame(raf); renderClock(); requestView();
    }
    function play() {
      if (!metadata) return;
      if (position >= metadata.duration) position = 0;
      if (!metadata.duration) { renderClock(); requestView(); return; }
      playing = true; anchorTime = position; anchorClock = performance.now(); renderClock();
      cancelAnimationFrame(raf); raf = requestAnimationFrame(tick);
    }
    function stopWorker() { worker?.terminate(); worker = null; inFlight = false; pending = false; }
    function empty() {
      pause(); stopWorker(); metadata = null; frame = null; position = 0;
      rows.clear(); selected.clear(); $('.sw-replay-channels').replaceChildren();
      progress.hidden = true; action('cancel').hidden = true; controls(false); renderClock(); draw();
    }
    function load(file) {
      empty(); if (!file) return;
      progress.hidden = false; progress.value = 0; action('cancel').hidden = false;
      status(t('正在加载：', 'Loading: ') + file.name);
      try { worker = new Worker(new URL('./superwatch_replay_worker.js', import.meta.url), { type: 'module' }); }
      catch (error) { empty(); status(t('无法启动日志解析：', 'Cannot start log parser: ') + error.message, true); return; }
      const current = worker;
      current.onerror = () => { if (worker === current) { empty(); status(t('日志解析线程失败，请重新导入。', 'Log worker failed. Please import again.'), true); } };
      current.onmessage = ({ data }) => {
        if (disposed || worker !== current) return;
        if (data.type === 'progress') progress.value = data.fraction;
        else if (data.type === 'error') { empty(); status(t('导入失败：', 'Import failed: ') + data.message, true); }
        else if (data.type === 'loaded') {
          metadata = data; progress.hidden = true; action('cancel').hidden = true;
          dialog.dataset.logRows = String(data.rows); dialog.dataset.logValues = String(data.values);
          seek.max = String(data.duration || 1); position = 0; span = 10; action('span').value = '10'; controls(true);
          status(`${file.name} · ${data.rows.toLocaleString()} ${t('行', 'rows')} · ${data.channels.length} ${t('通道', 'channels')} · ${data.duration.toFixed(3)} s`);
          data.channels.forEach((channel, index) => {
            const row = document.createElement('label'), checkbox = document.createElement('input'), name = document.createElement('span'), value = document.createElement('output');
            checkbox.type = 'checkbox'; checkbox.checked = index < 8; if (checkbox.checked) selected.add(channel.name);
            name.textContent = channel.name; name.title = channel.name; value.textContent = '—';
            checkbox.onchange = () => {
              if (checkbox.checked && selected.size >= 16) { checkbox.checked = false; status(t('最多同时显示 16 路；请先取消一个通道。', 'Select at most 16 visible channels; uncheck one first.'), true); return; }
              if (checkbox.checked) selected.add(channel.name); else selected.delete(channel.name);
              requestView();
            };
            row.append(checkbox, name, value); rows.set(channel.name, row); $('.sw-replay-channels').append(row);
          });
          renderClock(); requestView();
        } else if (data.type === 'view' && data.id === request) {
          inFlight = false; frame = data; draw(); if (pending) requestView();
        }
      };
      current.postMessage({ type: 'load', file });
    }
    fileInput.onchange = () => { const file = fileInput.files?.[0]; if (file) load(file); fileInput.value = ''; };
    action('cancel').onclick = () => { empty(); status(t('已取消加载', 'Loading cancelled')); };
    action('play').onclick = () => playing ? pause() : play();
    action('restart').onclick = () => { pause(); position = 0; play(); };
    action('speed').onchange = () => { const resume = playing; pause(); speed = Number(action('speed').value); if (resume) play(); };
    action('span').onchange = () => { span = action('span').value === 'all' ? Math.max(.001, metadata.duration) : Number(action('span').value); requestView(); };
    action('overview').onclick = () => { pause(); position = metadata.duration; span = Math.max(.001, metadata.duration); action('span').value = 'all'; renderClock(); requestView(); };
    seek.oninput = () => { const requested = Number(seek.value); pause(); position = requested; renderClock(); requestView(); };
    canvas.addEventListener('wheel', event => {
      if (!metadata || event.ctrlKey) return;
      event.preventDefault(); span = Math.max(.001, Math.min(Math.max(.001, metadata.duration), span * (event.deltaY > 0 ? 1.25 : .8)));
      action('span').value = ''; requestView();
    }, { passive: false });
    const observer = new ResizeObserver(() => { draw(); requestView(); }); observer.observe(wrap);
    closeDialog = () => {
      disposed = true; cancelAnimationFrame(raf); stopWorker(); observer.disconnect();
      dialog.close(); dialog.remove(); closeDialog = null; button.focus();
    };
    action('close').onclick = closeDialog;
    dialog.addEventListener('cancel', event => { event.preventDefault(); closeDialog?.(); });
    dialog.showModal(); draw();
  };
  return () => { closeDialog?.(); button.remove(); };
}
