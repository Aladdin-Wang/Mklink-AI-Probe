/**
 * SystemView 任务切换时间轴 —— 框架无关的 canvas 交互式渲染器。
 *
 * 被 HTML 报告（systemview-report，内联）与 Vue Dashboard（SystemViewTab，import）共用。
 *
 * 能力：
 *   - 滚轮缩放（以光标为中心）
 *   - 拖拽平移
 *   - 时间游标与 hover 提示（任务名 / 时长 / 起止时间）
 *   - 固定微秒单位的自适应主/次标尺
 *   - 运行区间内时长标签
 *   - 图例点击隐藏/显示任务泳道
 *   - 缩放全览 / 重置
 *
 * 用法：
 *   const tl = new SvTimeline(
 *     { canvas, tooltip, legend, resetBtn, hint },
 *     { intervals: [{tid,name,start,end}], unit: 'us'|'tk' }
 *   );
 *   tl.setData(newIntervals);   // Vue 实时更新
 *   tl.destroy();
 *
 * 区间 start/end 用同一时间单位（µs 或 ticks），与 unit 一致。
 */
export function exactTickFromOffset(origin, offset) {
  if (typeof origin !== 'bigint' || !Number.isSafeInteger(Math.round(offset))) {
    throw new RangeError('tick origin must be BigInt and offset must be a safe integer');
  }
  return (origin + BigInt(Math.round(offset))).toString();
}

const FOLLOW_FRAME_INTERVAL_MS = 1000 / 30;

export class SvTimeline {
  constructor(roots, data) {
    this.roots = roots;
    this.canvas = roots.canvas;
    this.ctx = this.canvas.getContext('2d');
    this.unit = (data && data.unit) || 'us';
    this.tickHz = Number((data && data.tickHz) || 0);
    this.tickOrigin = typeof (data && data.tickOrigin) === 'bigint' ? data.tickOrigin : 0n;
    this.PALETTE = ['#4f7fc7','#2e9f86','#be7d28','#8b67b4','#bf5b63','#9a8a2f',
      '#278e9a','#6b75bd','#4f996d','#b27052','#517cae','#a75f86'];
    this.nameColW = 132;
    this.rulerH = 42;
    this.laneH = 28;
    // Keep a compact, stable viewport for small traces. The capacity only
    // grows when new tasks appear, so live discovery does not make the page
    // jump up and down while avoiding a large empty 20-lane canvas.
    this.laneCapacity = 2;
    this.padR = 6;
    this.hidden = new Set();
    this.hover = null;
    this.markerTime = null;
    this.markerPinned = false;
    this.dragging = false;
    this.dragMoved = false;
    this.dragX0 = 0;
    this.dragView0 = null;
    this.viewStart = null;
    this.viewEnd = null;
    this._hadIntervals = false;
    this._taskOrder = [];
    this._taskMeta = new Map();
    this._explicitContexts = [];
    this.follow = (data && data.follow) !== false;
    this.windowSize = Number((data && data.windowSize) || 0);
    this.followEase = 0.22;
    this._followRaf = 0;
    this._lastLiveRender = Number.NEGATIVE_INFINITY;
    this._renderPaused = (data && data.renderPaused) === true;
    this.emptyText = (data && data.emptyText) || '窗口内无任务';
    this.setData((data && data.intervals) || []);
    this._bind();
    this._resize();
    window.addEventListener('resize', this._resize);
  }

  setData(intervals) {
    // 缓冲溢出丢包会在时间轴上留下巨大假缺口（abs_time 跳变），把真实活动压到
    // 一小撮。先剔到最密连续段再渲染。
    this._acceptData(this._filterContinuous(intervals || []));
  }

  setContexts(contexts) {
    this._explicitContexts = Array.isArray(contexts) ? contexts : [];
    this._acceptData(this.intervals || []);
  }

  setLabels(labels) {
    if (labels && labels.emptyText) this.emptyText = labels.emptyText;
    this._draw();
    this._updateStatus();
  }

  _acceptData(intervals) {
    // 按任务汇总，确定泳道顺序（总运行时间降序，最多 12 条）
    const hadIntervalsBefore = this._hadIntervals;
    this._hadIntervals = intervals.length > 0;
    this.intervals = intervals;
    const run = new Map(), names = new Map(), types = new Map();
    for (const it of this.intervals) {
      run.set(it.tid, (run.get(it.tid) || 0) + (it.end - it.start));
      names.set(it.tid, it.name);
      if (it.type) types.set(it.tid, it.type);
    }
    for (const context of (this._explicitContexts || [])) {
      if (!context || !Number.isFinite(context.tid)) continue;
      if (!run.has(context.tid)) run.set(context.tid, 0);
      if (context.name) names.set(context.tid, context.name);
      if (context.type) types.set(context.tid, context.type);
    }
    this.tasks = this._mergeTasks(run, names, types);
    this.taskOf = new Map(this.tasks.map(t => [t.tid, t]));
    // 时间范围
    if (this.intervals.length) {
      this.tMin = Math.min(...this.intervals.map(i => i.start));
      this.tMax = Math.max(...this.intervals.map(i => i.end));
    } else { this.tMin = 0; this.tMax = 1; }
    if (this.tMax <= this.tMin) this.tMax = this.tMin + 1;
    const viewInvalid = this.viewStart == null || this.viewEnd == null || this.viewEnd <= this.viewStart;
    const shouldFollow = this.follow && this.windowSize > 0 && this.intervals.length;
    if (shouldFollow && (viewInvalid || !hadIntervalsBefore)) {
      this._snapFollowRange();
    } else if (shouldFollow) {
      const span = this.windowSize;
      if (Math.abs((this.viewEnd - this.viewStart) - span) > 0.001) {
        this.viewStart = this.viewEnd - span;
      }
    } else {
      const viewOutsideData = this.viewEnd < this.tMin || this.viewStart > this.tMax;
      if (viewInvalid || viewOutsideData || (!hadIntervalsBefore && this.intervals.length)) {
      this.viewStart = this.tMin;
      this.viewEnd = this.tMax;
      } else {
      this.viewStart = Math.max(this.tMin, this.viewStart);
      this.viewEnd = Math.min(this.tMax, this.viewEnd);
      if (this.viewEnd <= this.viewStart) {
        this.viewStart = this.tMin;
        this.viewEnd = this.tMax;
      }
      }
    }
    this._layout();
    const drew = shouldFollow ? this._drawLive() : (this._draw(), true);
    if (drew) this._updateStatus();
    if (shouldFollow && !viewInvalid && hadIntervalsBefore) this._scheduleFollow();
  }

  // Live workers already filter the requested visible range. This entrypoint
  // deliberately avoids slicing/sorting the retained 50k interval history.
  setPrefilteredIntervals(intervals) {
    // User interaction leaves follow mode so the inspected frame stays stable
    // while acquisition and the Runtime/Context tables continue updating.
    if (!this.follow && this._hadIntervals) return;
    this._acceptData(intervals || []);
  }

  _mergeTasks(run, names, types = new Map()) {
    if (!this._taskOrder) this._taskOrder = [];
    if (!this._taskMeta) this._taskMeta = new Map();

    const rankedByRuntime = [...run.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([tid]) => tid);
    const explicitOrder = (this._explicitContexts || [])
      .map(context => context && context.tid)
      .filter(tid => Number.isFinite(tid) && run.has(tid));
    const stableRemainder = this._taskOrder.filter(tid => run.has(tid) && !explicitOrder.includes(tid));
    const ranked = [...new Set([...explicitOrder, ...stableRemainder, ...rankedByRuntime])].slice(0, 20);
    const active = new Set(ranked);

    for (const tid of ranked) {
      const name = names.get(tid) || ('0x' + (tid >>> 0).toString(16).toUpperCase());
      if (!this._taskMeta.has(tid)) {
        this._taskMeta.set(tid, {
          tid,
          name,
          type: types.get(tid) || 'Task',
          color: this._contextColor(types.get(tid), this._taskMeta.size),
        });
      } else if (name) {
        this._taskMeta.get(tid).name = name;
        if (types.get(tid)) this._taskMeta.get(tid).type = types.get(tid);
      }
      if (!this._taskOrder.includes(tid)) this._taskOrder.push(tid);
    }

    this._taskOrder = ranked.filter(tid => active.has(tid));

    return this._taskOrder
      .map(tid => this._taskMeta.get(tid))
      .filter(Boolean)
      .slice(0, 20);
  }

  _contextColor(type, paletteIndex) {
    if (type === 'ISR') return '#c52832';
    if (type === 'Scheduler') return '#727983';
    if (type === 'Idle') return '#8b929a';
    return this.PALETTE[paletteIndex % this.PALETTE.length];
  }

  setWindowSize(windowSize) {
    this.windowSize = Math.max(0, Number(windowSize) || 0);
    if (this.follow && this.windowSize > 0) this._snapFollowRange();
  }

  setTickOrigin(tickOrigin) {
    if (typeof tickOrigin !== 'bigint') throw new TypeError('tick origin must be BigInt');
    this.tickOrigin = tickOrigin;
  }

  setFollowMode(enabled) {
    this.follow = !!enabled;
    if (this.follow && this.windowSize > 0) this._snapFollowRange();
  }

  _targetFollowRange() {
    if (!this.windowSize || this.windowSize <= 0) {
      return { start: this.tMin, end: this.tMax };
    }
    const end = this.tMax;
    return { start: end - this.windowSize, end };
  }

  _snapFollowRange() {
    const target = this._targetFollowRange();
    this.viewStart = target.start;
    this.viewEnd = target.end;
    if (this.W && this.H) {
      this._draw();
      this._updateStatus();
    }
  }

  _drawLive(timestamp = performance.now()) {
    if (this._renderPaused) return false;
    const lastRender = Number.isFinite(this._lastLiveRender)
      ? this._lastLiveRender
      : Number.NEGATIVE_INFINITY;
    if (timestamp - lastRender < FOLLOW_FRAME_INTERVAL_MS) return false;
    this._lastLiveRender = timestamp;
    this._draw();
    return true;
  }

  _scheduleFollow() {
    if (this._renderPaused || !this.follow || this.windowSize <= 0 || this._followRaf) return;
    const step = (timestamp) => {
      this._followRaf = 0;
      if (this._renderPaused || !this.follow || this.windowSize <= 0) return;
      const now = Number.isFinite(timestamp) ? timestamp : performance.now();
      const target = this._targetFollowRange();
      const currentEnd = Number.isFinite(this.viewEnd) ? this.viewEnd : target.end;
      const delta = target.end - currentEnd;
      if (Math.abs(delta) < 0.5) {
        this.viewEnd = target.end;
        this.viewStart = target.start;
      } else {
        this.viewEnd = currentEnd + delta * this.followEase;
        this.viewStart = this.viewEnd - this.windowSize;
      }
      if (this._drawLive(now)) this._updateStatus();
      if (Math.abs(target.end - this.viewEnd) >= 0.5) {
        this._followRaf = requestAnimationFrame(step);
      }
    };
    this._followRaf = requestAnimationFrame(step);
  }

  pauseRendering() {
    this._renderPaused = true;
    if (this._followRaf) {
      cancelAnimationFrame(this._followRaf);
      this._followRaf = 0;
    }
  }

  resumeRendering() {
    if (!this._renderPaused) return;
    this._renderPaused = false;
    this._lastLiveRender = Number.NEGATIVE_INFINITY;
    this._layout();
    if (this._drawLive()) this._updateStatus();
    this._scheduleFollow();
  }

  _layout() {
    this.lanes = this.tasks.filter(t => !this.hidden.has(t.tid));
    const dpr = window.devicePixelRatio || 1;
    const cssW = this.canvas.clientWidth || 800;
    if (this.lanes.length > this.laneCapacity) this.laneCapacity = this.lanes.length;
    const cssH = this.rulerH + Math.max(1, this.laneCapacity) * this.laneH + 4;
    if (!this._renderPaused) {
      const width = cssW * dpr;
      const height = cssH * dpr;
      if (this.canvas.width !== width) this.canvas.width = width;
      if (this.canvas.height !== height) this.canvas.height = height;
      this.canvas.style.height = cssH + 'px';
    }
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.W = cssW; this.H = cssH;
    this.plotX0 = this.nameColW;
    this.plotX1 = this.W - this.padR;
    this.plotW = this.plotX1 - this.plotX0;
  }

  _resize = () => {
    this._layout();
    if (!this._renderPaused) this._draw();
  }

  _filterContinuous(intervals) {
    if (intervals.length < 8) return intervals;
    let maxGap = 0, maxIdx = 0;
    let tMin = Infinity, tMax = -Infinity;
    for (let i = 0; i < intervals.length - 1; i++) {
      const g = intervals[i + 1].start - intervals[i].end;
      if (g > maxGap) { maxGap = g; maxIdx = i; }
      if (intervals[i].start < tMin) tMin = intervals[i].start;
      if (intervals[i].end > tMax) tMax = intervals[i].end;
    }
    const last = intervals[intervals.length - 1];
    if (last.start < tMin) tMin = last.start;
    if (last.end > tMax) tMax = last.end;
    const durs = intervals.map(it => it.end - it.start).sort((a, b) => a - b);
    const med = durs[Math.floor(durs.length / 2)] || 1;
    if (maxGap <= this._largeGapThreshold(Math.max(0, tMax - tMin), med)) return intervals;
    if (maxGap <= med * 200) return intervals; // 无离群缺口
    const left = intervals.slice(0, maxIdx + 1), right = intervals.slice(maxIdx + 1);
    return this._filterContinuous(left.length >= right.length ? left : right);
  }

  _largeGapThreshold(span, medianDuration) {
    const oneSecond = this.unit === 'us'
      ? 1_000_000
      : (this.tickHz > 0 ? this.tickHz : 1_000_000);
    const windowThreshold = this.windowSize > 0 ? this.windowSize * 2 : span * 0.2;
    return Math.max(medianDuration * 200, oneSecond * 2, windowThreshold);
  }

  _t2x(t) { return this.plotX0 + (t - this.viewStart) / (this.viewEnd - this.viewStart) * this.plotW; }
  _x2t(x) { return this.viewStart + (x - this.plotX0) / this.plotW * (this.viewEnd - this.viewStart); }

  _fmtLegacy(t) {
    if (this.unit === 'us') {
      if (t >= 1e6) return (t / 1e6).toFixed(3) + ' s';
      if (t >= 1e3) return (t / 1e3).toFixed(2) + ' ms';
      return t.toFixed(0) + ' µs';
    }
    return Math.round(t).toLocaleString() + ' tk';
  }

  _fmtTime(us) {
    return this._fmtMicroseconds(us, 3);
  }

  _fmtMicroseconds(value, maxDecimals = 3) {
    if (!Number.isFinite(value)) return '';
    const rounded = Number(value.toFixed(maxDecimals));
    const text = rounded.toLocaleString('en-US', { maximumFractionDigits: maxDecimals });
    return `${text} us`;
  }

  _fmtAxisValue(value, step) {
    if (this.unit !== 'us') return this._fmtTicks(BigInt(exactTickFromOffset(this.tickOrigin, value)));
    const decimals = step < 0.01 ? 3 : step < 0.1 ? 2 : step < 1 ? 1 : 0;
    const rounded = Number(value.toFixed(decimals));
    const text = rounded.toLocaleString('en-US', { maximumFractionDigits: decimals });
    return `${text} us`;
  }

  _fmtIntervalLabel(it) {
    const duration = it.end - it.start;
    if (this.unit !== 'us') return this._fmtTicks(Math.round(duration), true);
    return this._fmtMicroseconds(duration, 3);
  }

  _ticksFromUs(us) {
    return this.tickHz > 0 ? us * this.tickHz / 1_000_000 : null;
  }

  _fmtTicks(ticks, compact = false) {
    if (typeof ticks === 'bigint') {
      const sign = ticks < 0n ? '-' : '';
      const abs = ticks < 0n ? -ticks : ticks;
      if (compact && abs >= 1_000_000n) return sign + (Number(abs / 10_000n) / 100).toFixed(2).replace(/\.?0+$/, '') + 'M tk';
      if (compact && abs >= 1_000n) return sign + (Number(abs / 100n) / 10).toFixed(1).replace(/\.?0+$/, '') + 'k tk';
      return ticks.toLocaleString() + ' tk';
    }
    if (!Number.isFinite(ticks)) return '';
    const rounded = Math.round(ticks);
    const abs = Math.abs(rounded);
    if (compact && abs >= 1_000_000) return (rounded / 1_000_000).toFixed(2).replace(/\.?0+$/, '') + 'M tk';
    if (compact && abs >= 1_000) return (rounded / 1_000).toFixed(1).replace(/\.?0+$/, '') + 'k tk';
    return rounded.toLocaleString() + ' tk';
  }

  _fmt(t, withTicks = false) {
    if (this.unit === 'us') {
      const time = this._fmtTime(t);
      if (withTicks && this.tickHz > 0) return time + ' / ' + this._fmtTicks(this._ticksFromUs(t), true);
      return time;
    }
    return this._fmtTicks(BigInt(exactTickFromOffset(this.tickOrigin, t)));
  }

  _fmtPoint(time, ticks) {
    if (this.unit !== 'us') {
      return this._fmtTicks(typeof ticks === 'bigint'
        ? ticks
        : BigInt(exactTickFromOffset(this.tickOrigin, time)));
    }
    const tickValue = typeof ticks === 'bigint' || Number.isFinite(ticks)
      ? ticks
      : this._ticksFromUs(time);
    const tickText = this._fmtTicks(tickValue);
    return tickText ? `${this._fmtTime(time)} (${tickText})` : this._fmtTime(time);
  }

  _fmtDuration(it) {
    const duration = it.end - it.start;
    if (this.unit !== 'us') {
      if (typeof it.startTk === 'bigint' && typeof it.endTk === 'bigint') {
        return this._fmtTicks(it.endTk - it.startTk);
      }
      return this._fmtTicks(BigInt(Math.round(duration)));
    }
    const hasExactTicks = (
      (typeof it.startTk === 'bigint' && typeof it.endTk === 'bigint')
      || (Number.isFinite(it.startTk) && Number.isFinite(it.endTk))
    );
    const durationTicks = hasExactTicks ? it.endTk - it.startTk : this._ticksFromUs(duration);
    const tickText = this._fmtTicks(durationTicks);
    return tickText ? `${this._fmtTime(duration)} (${tickText})` : this._fmtTime(duration);
  }

  _niceStep(rawStep) {
    if (!Number.isFinite(rawStep) || rawStep <= 0) return 1;
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const normalized = rawStep / magnitude;
    const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return multiplier * magnitude;
  }

  _labelWidth(text) {
    if (this.ctx && typeof this.ctx.measureText === 'function') {
      return this.ctx.measureText(text).width;
    }
    return String(text).length * 7;
  }

  _draw() {
    if (this._renderPaused) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.W, this.H);
    ctx.font = '11px -apple-system,Segoe UI,Roboto,sans-serif';
    this._drawLaneBackgrounds();
    this._drawRuler();
    this.lanes.forEach((task, i) => {
      const y = this.rulerH + i * this.laneH;
      ctx.fillStyle = '#343a43'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
      ctx.font = task.type === 'ISR'
        ? '600 11px -apple-system,Segoe UI,Roboto,sans-serif'
        : '11px -apple-system,Segoe UI,Roboto,sans-serif';
      ctx.fillText(task.name.slice(0, 16), 17, y + this.laneH / 2);
      ctx.fillStyle = task.color;
      ctx.fillRect(5, y + 4, 4, this.laneH - 8);
    });
    ctx.font = '11px -apple-system,Segoe UI,Roboto,sans-serif';
    for (const it of this.intervals) {
      const task = this.taskOf.get(it.tid);
      if (!task || this.hidden.has(it.tid)) continue;
      const laneIdx = this.lanes.indexOf(task);
      if (laneIdx < 0) continue;
      if (it.end < this.viewStart || it.start > this.viewEnd) continue;
      const x0 = Math.max(this._t2x(it.start), this.plotX0);
      const x1 = Math.min(this._t2x(it.end), this.plotX1);
      if (x1 - x0 < 0.4) continue; // 太细跳过
      const y = this.rulerH + laneIdx * this.laneH + 3;
      const w = Math.max(x1 - x0, 0.8);
      const h = this.laneH - 6;
      ctx.fillStyle = task.type === 'Scheduler' ? '#eef0f3'
        : task.type === 'Idle' ? '#f7f8fa' : task.color;
      ctx.fillRect(x0, y, w, h);
      ctx.strokeStyle = task.type === 'Scheduler' || task.type === 'Idle'
        ? '#969da6' : 'rgba(31, 41, 55, 0.32)';
      ctx.lineWidth = 1;
      ctx.strokeRect(x0 + 0.5, y + 0.5, Math.max(w - 1, 0.8), Math.max(h - 1, 1));
      const durationLabel = this._fmtIntervalLabel(it);
      ctx.font = '10px ui-monospace,SFMono-Regular,Consolas,monospace';
      const labelWidth = this._labelWidth(durationLabel);
      if (w >= labelWidth + 10) {
        ctx.fillStyle = task.type === 'Scheduler' || task.type === 'Idle' ? '#4b535d' : '#ffffff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(durationLabel, x0 + w / 2, y + h / 2 + 0.5);
      }
    }
    if (this.hover) {
      const task = this.taskOf.get(this.hover.tid);
      const laneIdx = this.lanes.indexOf(task);
      if (laneIdx >= 0) {
        const x0 = Math.max(this._t2x(this.hover.start), this.plotX0);
        const x1 = Math.min(this._t2x(this.hover.end), this.plotX1);
        const y = this.rulerH + laneIdx * this.laneH + 2;
        ctx.strokeStyle = '#111827'; ctx.lineWidth = 1.25;
        ctx.strokeRect(x0 - 0.5, y - 0.5, Math.max(x1 - x0, 1.5) + 1, this.laneH - 4);
        ctx.setLineDash([3, 2]);
        ctx.strokeStyle = 'rgba(17, 24, 39, .55)';
        for (const x of [x0, x1]) {
          ctx.beginPath(); ctx.moveTo(x, this.rulerH); ctx.lineTo(x, this.H); ctx.stroke();
        }
        ctx.setLineDash([]);
      }
    }
    this._drawMarker();
  }

  _drawLaneBackgrounds() {
    const ctx = this.ctx;
    ctx.fillStyle = '#f1f3f5';
    ctx.fillRect(0, this.rulerH, this.nameColW, this.H - this.rulerH);
    this.lanes.forEach((_task, index) => {
      const y = this.rulerH + index * this.laneH;
      ctx.fillStyle = index % 2 ? '#f4f7f4' : '#f8faf8';
      ctx.fillRect(this.plotX0, y, this.plotW, this.laneH);
      ctx.fillStyle = '#d9dde2';
      ctx.fillRect(0, y + this.laneH - 1, this.W, 1);
    });
    ctx.fillStyle = '#bfc5cc';
    ctx.fillRect(this.nameColW - 1, this.rulerH, 1, this.H - this.rulerH);
  }

  _drawRuler() {
    const ctx = this.ctx;
    ctx.fillStyle = '#eceff2'; ctx.fillRect(0, 0, this.W, this.rulerH);
    ctx.fillStyle = '#d2d7dd'; ctx.fillRect(0, this.rulerH - 1, this.W, 1);
    ctx.fillStyle = '#343a43';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    ctx.font = '600 11px -apple-system,Segoe UI,Roboto,sans-serif';
    ctx.fillText('Core 0', 17, this.rulerH / 2 + 1);
    ctx.fillStyle = '#bfc5cc';
    ctx.fillRect(this.nameColW - 1, 0, 1, this.rulerH);

    const span = this.viewEnd - this.viewStart;
    const targetLabels = Math.max(2, Math.floor(this.plotW / 110));
    const step = this._niceStep(span / targetLabels);
    const minorStep = step / 5;
    const minorStart = Math.ceil(this.viewStart / minorStep) * minorStep;
    ctx.lineWidth = 1;
    for (let t = minorStart; t <= this.viewEnd + minorStep * 0.1; t += minorStep) {
      const x = this._t2x(t);
      if (x < this.plotX0 || x > this.plotX1) continue;
      const major = Math.abs(t / step - Math.round(t / step)) < 1e-6;
      ctx.strokeStyle = major ? '#cbd1d7' : '#e5e8eb';
      ctx.beginPath();
      ctx.moveTo(x, major ? 24 : 32);
      ctx.lineTo(x, this.H);
      ctx.stroke();
    }
    ctx.fillStyle = '#636b75'; ctx.textBaseline = 'middle'; ctx.textAlign = 'center';
    ctx.font = '10px ui-monospace,SFMono-Regular,Consolas,monospace';
    const t0 = Math.ceil(this.viewStart / step) * step;
    let lastLabelRight = -Infinity;
    for (let t = t0; t <= this.viewEnd; t += step) {
      const x = this._t2x(t);
      if (x < this.plotX0 || x > this.plotX1) continue;
      const label = this._fmtAxisValue(t, step);
      const half = this._labelWidth(label) / 2;
      const labelX = Math.min(Math.max(x, this.plotX0 + half + 2), this.plotX1 - half - 2);
      const labelLeft = labelX - half;
      const labelRight = labelX + half;
      if (labelLeft <= lastLabelRight + 10) continue;
      ctx.fillText(label, labelX, 12);
      lastLabelRight = labelRight;
    }
  }

  _drawMarker() {
    if (!Number.isFinite(this.markerTime)) return;
    const x = this._t2x(this.markerTime);
    if (x < this.plotX0 || x > this.plotX1) return;
    const ctx = this.ctx;
    ctx.strokeStyle = '#2563c9';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, 19); ctx.lineTo(x, this.H); ctx.stroke();
    ctx.fillStyle = '#2563c9';
    ctx.beginPath(); ctx.moveTo(x - 4, 19); ctx.lineTo(x + 4, 19); ctx.lineTo(x, 24); ctx.closePath(); ctx.fill();

    const label = this.unit === 'us'
      ? this._fmtMicroseconds(this.markerTime, 3)
      : this._fmt(this.markerTime);
    ctx.font = '600 10px ui-monospace,SFMono-Regular,Consolas,monospace';
    const width = this._labelWidth(label) + 8;
    const labelX = Math.min(Math.max(x, this.plotX0 + width / 2), this.plotX1 - width / 2);
    ctx.fillStyle = '#eceff2';
    ctx.fillRect(labelX - width / 2, 22, width, 17);
    ctx.fillStyle = '#174ea6';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(label, labelX, 30.5);
  }

  _hitTest(mx, my) {
    if (mx < this.plotX0 || mx > this.plotX1) return null;
    const laneIdx = Math.floor((my - this.rulerH) / this.laneH);
    if (laneIdx < 0 || laneIdx >= this.lanes.length) return null;
    const t = this._x2t(mx);
    // 该泳道里找命中的区间（取最后一个，即最上层）
    let hit = null;
    for (const it of this.intervals) {
      if (it.tid !== this.lanes[laneIdx].tid) continue;
      if (it.start <= t && it.end >= t) hit = it;
    }
    return hit;
  }

  _bind() {
    if (this._listenersBound) return;

    this._onWheel = (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      if (!this._shouldZoomWheel(mx) || e.deltaY === 0) return;
      e.preventDefault();
      this.setFollowMode(false);
      const t = this._x2t(mx);
      const factor = e.deltaY < 0 ? 0.8 : 1.25; // 缩放因子
      const fullSpan = Math.max(this.tMax - this.tMin, Number.EPSILON);
      const currentSpan = Math.max(this.viewEnd - this.viewStart, Number.EPSILON);
      const minSpan = Math.max(fullSpan * 1e-5, this.unit === 'us' ? 0.001 : 1);
      const nextSpan = Math.min(fullSpan, Math.max(minSpan, currentSpan * factor));
      const anchor = Math.min(1, Math.max(0, (mx - this.plotX0) / this.plotW));
      let ns = t - nextSpan * anchor;
      let ne = ns + nextSpan;
      if (ns < this.tMin) { ne += this.tMin - ns; ns = this.tMin; }
      if (ne > this.tMax) { ns -= ne - this.tMax; ne = this.tMax; }
      this.viewStart = Math.max(this.tMin, ns);
      this.viewEnd = Math.min(this.tMax, ne);
      this._draw(); this._updateStatus();
    };

    this._onMouseDown = (e) => {
      if (e.button !== 0) return;
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      if (mx < this.plotX0 || mx > this.plotX1) return;
      e.preventDefault();
      this.setFollowMode(false);
      this.dragging = true;
      this.dragMoved = false;
      this.dragX0 = e.clientX;
      this.dragView0 = [this.viewStart, this.viewEnd];
      this.canvas.style.cursor = 'grabbing';
    };

    this._onMouseMove = (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      if (this.dragging) {
        const dx = e.clientX - this.dragX0;
        if (Math.abs(dx) >= 3) this.dragMoved = true;
        const dt = -dx / this.plotW * (this.dragView0[1] - this.dragView0[0]);
        let ns = this.dragView0[0] + dt, ne = this.dragView0[1] + dt;
        if (ns < this.tMin) { ne += this.tMin - ns; ns = this.tMin; }
        if (ne > this.tMax) { ns -= ne - this.tMax; ne = this.tMax; }
        this.viewStart = ns; this.viewEnd = ne;
        this._draw(); this._updateStatus();
      } else if (mx >= 0 && mx <= this.W && my >= 0 && my <= this.H) {
        const hit = this._hitTest(mx, my);
        this.hover = hit;
        if (!this.markerPinned && mx >= this.plotX0 && mx <= this.plotX1) {
          this.markerTime = this._x2t(mx);
        }
        this.canvas.style.cursor = hit ? 'pointer' : 'grab';
        if (hit) this._showTip(e.clientX, e.clientY, hit); else this._hideTip();
        this._draw();
      }
    };

    this._onMouseUp = (e) => {
      if (this.dragging && !this.dragMoved) {
        const rect = this.canvas.getBoundingClientRect();
        const mx = Math.min(this.plotX1, Math.max(this.plotX0, e.clientX - rect.left));
        this.markerTime = this._x2t(mx);
        this.markerPinned = true;
      }
      this.dragging = false;
      this.canvas.style.cursor = 'grab';
      this._draw();
    };
    this._onMouseLeave = () => {
      this.hover = null;
      if (!this.markerPinned) this.markerTime = null;
      this._hideTip();
      this._draw();
    };
    this._onDoubleClick = () => {
      this.markerPinned = false;
      this.markerTime = null;
      this.reset();
    };

    this.canvas.addEventListener('wheel', this._onWheel, { passive: false });
    this.canvas.addEventListener('mousedown', this._onMouseDown);
    window.addEventListener('mousemove', this._onMouseMove);
    window.addEventListener('mouseup', this._onMouseUp);
    this.canvas.addEventListener('mouseleave', this._onMouseLeave);
    this.canvas.addEventListener('dblclick', this._onDoubleClick);
    if (this.roots.resetBtn) this.roots.resetBtn.onclick = () => this.reset();
    this._listenersBound = true;
  }

  _shouldZoomWheel(mx) {
    return Number.isFinite(mx) && mx >= this.plotX0 && mx <= this.plotX1;
  }

  _escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  _showTip(cx, cy, it) {
    const tip = this.roots.tooltip; if (!tip) return;
    tip.style.display = 'block';
    tip.innerHTML = `<b>${this._escapeHtml(it.name)}</b><br>duration ${this._fmtDuration(it)}<br>`
      + `start ${this._fmtPoint(it.start, it.startTk)}<br>end ${this._fmtPoint(it.end, it.endTk)}`;
    const w = tip.offsetWidth;
    const h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(cx + 14, window.innerWidth - w - 8)) + 'px';
    tip.style.top = Math.max(8, Math.min(cy + 14, window.innerHeight - h - 8)) + 'px';
  }
  _hideTip() { if (this.roots.tooltip) this.roots.tooltip.style.display = 'none'; }

  _updateStatus() {
    if (this.roots.legend) {
      this.roots.legend.innerHTML = this.tasks.map(t =>
        `<span class="sv-lg${this.hidden.has(t.tid) ? ' sv-lg-off' : ''}" data-tid="${t.tid}">`
        + `<i style="background:${t.color}"></i>${this._escapeHtml(t.name.slice(0, 16))}</span>`
      ).join('');
      this.roots.legend.querySelectorAll('.sv-lg').forEach(el => {
        el.onclick = () => { const tid = +el.dataset.tid; this.toggleTask(tid); };
      });
    }
  }

  toggleTask(tid) {
    if (this.hidden.has(tid)) this.hidden.delete(tid); else this.hidden.add(tid);
    this._layout(); this._draw(); this._updateStatus();
  }

  reset() {
    this.markerPinned = false;
    this.markerTime = null;
    if (this.windowSize > 0) {
      this.setFollowMode(true);
      return;
    }
    this.viewStart = this.tMin; this.viewEnd = this.tMax; this._draw(); this._updateStatus();
  }

  destroy() {
    if (this._followRaf) {
      cancelAnimationFrame(this._followRaf);
      this._followRaf = 0;
    }
    window.removeEventListener('resize', this._resize);
    if (this._listenersBound) {
      this.canvas.removeEventListener('wheel', this._onWheel);
      this.canvas.removeEventListener('mousedown', this._onMouseDown);
      window.removeEventListener('mousemove', this._onMouseMove);
      window.removeEventListener('mouseup', this._onMouseUp);
      this.canvas.removeEventListener('mouseleave', this._onMouseLeave);
      this.canvas.removeEventListener('dblclick', this._onDoubleClick);
      if (this.roots.resetBtn) this.roots.resetBtn.onclick = null;
      this._listenersBound = false;
    }
    this._hideTip();
    // （其它监听挂在 window/canvas，组件卸载时随 DOM 释放；简单场景可接受）
  }
}

// 供 HTML 报告（非 module）使用：挂到 window
if (typeof window !== 'undefined') window.SvTimeline = SvTimeline;
