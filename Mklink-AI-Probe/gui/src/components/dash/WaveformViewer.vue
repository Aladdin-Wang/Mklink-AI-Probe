<template>
  <div ref="container" class="waveform-viewer"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useBinaryStream } from '../../composables/useBinaryStream'
import { RenderScheduler } from '../../lib/stream/renderScheduler'
import type { WorkerOutput } from '../../workers/streamDecoder.worker'
import '../../assets/rtt_viewer.css'
import i18nUrl from '../../assets/rtt_i18n.js?url'
import viewerUrl from '../../assets/rtt_viewer.js?url'

const props = defineProps<{
  mode: 'SuperWatch' | 'VOFA'
  deviceConnected: boolean
}>()

const container = ref<HTMLDivElement>()
const binary = props.mode === 'VOFA'
  ? useBinaryStream('vofa', { capacity: 200000, channelCount: 1 })
  : null
let vofaChannels: Array<Record<string, unknown>> = []
let pendingBatch: Extract<WorkerOutput, { type: 'waveform-batch' }> | null = null
let disposed = false
const vofaScheduler = binary
  ? new RenderScheduler(() => {
      const viewer = (window as any).__waveformViewers?.VOFA
      viewer?.renderBinaryFrame?.()
    })
  : null

function onVofaChannels(event: Event): void {
  if (!binary || disposed) return
  const channels = (event as CustomEvent<unknown>).detail
  if (!Array.isArray(channels)) return
  vofaChannels = channels
  binary.configure(Math.max(1, channels.length))
  ;(window as any).__waveformViewers?.VOFA?.configureBinaryChannels?.(channels)
}

watch(() => binary?.waveformBatch.value ?? null, batch => {
  if (!batch || props.mode !== 'VOFA') return
  pendingBatch = batch
  const viewer = (window as any).__waveformViewers?.VOFA
  if (viewer?.acceptBinaryBatch) {
    viewer.acceptBinaryBatch(batch, vofaChannels)
    pendingBatch = null
  }
  vofaScheduler?.recordCollection(batch.itemCount)
  vofaScheduler?.invalidate('data')
})

onMounted(() => {
  if (!container.value) return
  const el = container.value

  // 1. Inject HTML template
  el.innerHTML = buildTemplate(props.mode)

  // 2. Inject CONFIG + load scripts
  injectScripts(el, props.mode)
  if (binary) {
    window.addEventListener('mklink:vofa-channels', onVofaChannels)
    vofaScheduler?.start()
    void fetch('/api/dash/vofa/status')
      .then(response => response.ok ? response.json() : null)
      .then(status => {
        if (!status || disposed) return
        vofaChannels = Array.isArray(status.channels) ? status.channels : []
        binary.configure(Math.max(1, vofaChannels.length))
        binary.start()
      })
      .catch(() => {
        if (!disposed) binary.start()
      })
  }
})

watch(() => props.deviceConnected, (val) => {
  const viewers = (window as any).__waveformViewers
  if (viewers?.[props.mode]?.setDeviceConnected) viewers[props.mode].setDeviceConnected(val)
})

onUnmounted(() => {
  disposed = true
  binary?.stop()
  vofaScheduler?.dispose()
  window.removeEventListener('mklink:vofa-channels', onVofaChannels)
  // Close EventSource if running
  try {
    const viewers = (window as any).__waveformViewers
    if (viewers?.[props.mode]?.es) viewers[props.mode].es.close()
    if (viewers) delete viewers[props.mode]
  } catch { /* ignore */ }
  // Clear DOM
  if (container.value) container.value.innerHTML = ''
})

function buildTemplate(mode: string): string {
  const maxPoints = 10000
  return `
<header>
  <h1>MKLink ${mode}</h1>
  <span id="mode-badge" class="badge badge-mode">${mode}</span>
  <span id="conn-status" class="badge badge-ok" data-i18n="live">live</span>
  <span id="pts-count" class="badge badge-info">0 pts</span>
  <span id="sample-rate-badge" class="badge badge-info">rate -- Hz</span>
  <div class="header-actions">
    <button id="btn-lang-toggle" class="panel-btn" title="中文/English">中/En</button>
    <button id="btn-cursor-toggle" class="panel-btn" data-i18n-title="cursors_tip" data-i18n="cursors">Cursors</button>
    <button id="btn-cursor-mode" class="panel-btn" style="display:none;" data-i18n-title="cursor_mode_tip">Time</button>
    <button id="btn-save-project" class="panel-btn" data-i18n-title="save_project_tip" data-i18n="save">Save</button>
    <button id="btn-load-project" class="panel-btn" data-i18n-title="load_project_tip" data-i18n="load">Load</button>
    <button id="btn-thresholds" class="panel-btn" data-i18n-title="thresholds_tip" data-i18n="thresholds">Thresholds</button>
    <button id="btn-export-csv" class="panel-btn" data-i18n-title="export_csv_tip">CSV</button>
    <button id="btn-export-png" class="panel-btn" data-i18n-title="export_png_tip">PNG</button>
    <button id="btn-help" class="panel-btn" data-i18n-title="help_tip">?</button>
    <input id="project-load-input" class="hidden-file-input" type="file" accept="application/json,.json">
  </div>
</header>

<div id="control-toolbar">
  <button id="btn-start" class="ctrl-btn active" data-i18n="start">Start</button>
  <button id="btn-pause" class="ctrl-btn" data-i18n="pause">Pause</button>
  <button id="btn-stop" class="ctrl-btn danger" data-i18n="stop">Stop</button>
  <span id="collection-status-badge" class="status-running" data-i18n="running">Running</span>
  <div class="ctrl-sep"></div>
  <label data-i18n="buffer">Buffer</label>
  <input type="number" id="buffer-input" value="${maxPoints}" min="2" max="200000" step="10">
  <span class="buffer-unit">pts</span>
  <button id="btn-apply-buffer" class="ctrl-btn" data-i18n="apply">Apply</button>
  <div class="ctrl-sep"></div>
  <div id="interval-group">
    <label data-i18n="interval">Interval</label>
    <input type="number" id="interval-input" value="0" step="0.001" min="0" max="60">
    <span class="interval-unit">s</span>
    <button id="btn-apply-interval" class="ctrl-btn" data-i18n="apply">Apply</button>
  </div>
</div>

<div id="trigger-toolbar">
  <button id="trigger-enable-btn" data-i18n="trigger">Trigger</button>
  <span id="trigger-state-badge" class="trigger-state-idle" data-i18n="idle">Idle</span>
  <div class="trigger-sep"></div>
  <label data-i18n="source">Source</label>
  <select id="trigger-source"><option value="">--</option></select>
  <div class="trigger-sep"></div>
  <label data-i18n="edge">Edge</label>
  <select id="trigger-edge">
    <option value="rising" data-i18n="rising">Rising</option>
    <option value="falling" data-i18n="falling">Falling</option>
    <option value="both" data-i18n="both">Both</option>
  </select>
  <div class="trigger-sep"></div>
  <label data-i18n="level">Level</label>
  <input type="number" id="trigger-level" value="0" step="0.1">
  <div class="trigger-sep"></div>
  <label data-i18n="mode">Mode</label>
  <select id="trigger-mode">
    <option value="auto" data-i18n="auto">Auto</option>
    <option value="normal" data-i18n="normal">Normal</option>
    <option value="single" data-i18n="single">Single</option>
  </select>
  <div class="trigger-sep"></div>
  <label data-i18n="pretrig">Pre-trig</label>
  <input type="number" id="trigger-pretrig" value="1000" min="10" max="50000" step="100">
  <div class="trigger-sep"></div>
  <button id="trigger-force-btn" data-i18n="force_trigger">Force Trigger</button>
</div>

<div id="var-selector"></div>

<div id="superwatch-panel" aria-hidden="true">
  <div id="sw-search-wrap" style="position:relative">
    <input id="superwatch-search-input" data-i18n-placeholder="sw_search_placeholder" placeholder="搜索或输入变量名...">
    <ul id="sw-search-dropdown"></ul>
  </div>
  <button id="superwatch-add-btn" class="panel-btn" data-i18n="add">添加</button>
  <label data-i18n="time">时间</label>
  <select id="time-unit-select">
    <option value="us">us</option>
    <option value="ms" selected>ms</option>
    <option value="s">s</option>
  </select>
  <button id="superwatch-inspect-btn" class="panel-btn" data-i18n="inspect">检查</button>
</div>

<main id="debug-main">
  <section id="chart-watch-wrap">
    <div id="enum-tooltip"></div>
    <div id="chart-wrap">
      <canvas id="chart"></canvas>
      <div id="tooltip"></div>
      <div id="cursor-a" class="cursor-line" style="display:none;"></div>
      <div id="cursor-b" class="cursor-line" style="display:none;"></div>
      <div id="cursor-measure-panel" style="display:none;"></div>
    </div>
    <div id="watch-resizer"></div>
    <div id="watch-panel">
      <div class="panel-header">
        <div class="panel-title">
          <span class="panel-dot"></span>
          <span data-i18n="watch">监视</span>
        </div>
        <div class="panel-actions">
          <span id="watch-count" class="panel-count">0 ch</span>
          <button id="watch-columns-btn" class="panel-btn" data-i18n-title="columns_tip" data-i18n="columns">列</button>
          <button id="watch-collapse" class="panel-btn panel-btn-close" data-i18n-title="collapse_watch" title="折叠监视面板">&#x2715;</button>
        </div>
      </div>
      <div id="watch-columns-menu" class="columns-menu" aria-hidden="true"></div>
      <div id="watch-table-wrap">
        <table id="watch-table">
          <thead>
            <tr id="watch-table-head-row"></tr>
          </thead>
          <tbody id="watch-tbody"></tbody>
        </table>
      </div>
    </div>
  </section>

  <div id="minimap-wrap">
    <canvas id="minimap-canvas"></canvas>
    <div id="minimap-viewport"></div>
    <div id="cursor-readout"></div>
  </div>

  <section id="raw-log-panel" data-open="false">
    <div class="panel-resizer" title="Drag to resize"></div>
    <div class="panel-header">
      <div class="panel-title">
        <span class="panel-dot"></span>
        <span data-i18n="raw_log">原始日志</span>
      </div>
      <div class="panel-actions">
        <span id="raw-log-count" class="panel-count">0 lines</span>
        <button id="raw-log-clear" class="panel-btn" data-i18n-title="clear_log" data-i18n="clear">清除</button>
        <button id="raw-log-close" class="panel-btn panel-btn-close" data-i18n-title="close_panel" title="关闭面板">&#x2715;</button>
      </div>
    </div>
    <pre id="raw-log"></pre>
  </section>
  <section id="inspector-panel" aria-hidden="true"></section>
</main>

<footer id="stats-footer"></footer>
<div id="threshold-overlay" class="config-overlay" aria-hidden="true">
  <div class="config-dialog" role="dialog" aria-modal="true" aria-labelledby="threshold-title">
    <h2 id="threshold-title" data-i18n="thresholds">阈值</h2>
    <div class="config-grid">
      <div class="config-field full">
        <label for="threshold-channel" data-i18n="channel">通道</label>
        <select id="threshold-channel"></select>
      </div>
      <div class="config-field">
        <label for="threshold-warn-low" data-i18n="warn_low">警告下限</label>
        <input id="threshold-warn-low" type="number" step="0.1">
      </div>
      <div class="config-field">
        <label for="threshold-warn-high" data-i18n="warn_high">警告上限</label>
        <input id="threshold-warn-high" type="number" step="0.1">
      </div>
      <div class="config-field">
        <label for="threshold-alarm-low" data-i18n="alarm_low">报警下限</label>
        <input id="threshold-alarm-low" type="number" step="0.1">
      </div>
      <div class="config-field">
        <label for="threshold-alarm-high" data-i18n="alarm_high">报警上限</label>
        <input id="threshold-alarm-high" type="number" step="0.1">
      </div>
    </div>
    <div class="config-actions">
      <button id="threshold-clear" class="panel-btn" data-i18n="clear">清除</button>
      <button id="threshold-cancel" class="panel-btn" data-i18n="cancel">取消</button>
      <button id="threshold-apply" class="panel-btn" data-i18n="apply">应用</button>
    </div>
  </div>
</div>
<div id="shutdown-overlay">
  <h2 data-i18n="server_shutdown">服务器已关闭</h2>
  <p data-i18n="server_stopped_msg">可视化服务器已停止。</p>
  <p data-i18n="close_tab_msg">可以关闭此标签页。</p>
</div>

<div id="help-overlay" aria-hidden="true">
  <div id="help-modal" role="dialog" aria-modal="true" aria-labelledby="help-modal-title">
    <div id="help-modal-header">
      <h2 id="help-modal-title" data-i18n="help_title">使用说明</h2>
      <button id="help-close-btn" data-i18n-title="close_esc" title="关闭 (Esc)">&times;</button>
    </div>
    <div id="help-modal-body">
      <div class="help-section"><h3 data-i18n="help_chart">图表交互</h3><ul id="help-chart-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_var_selector">变量选择器</h3><ul id="help-var-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_trigger_sys">触发系统</h3><ul id="help-trigger-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_watch_panel">Watch 面板</h3><ul id="help-watch-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_minimap">缩略图</h3><ul id="help-minimap-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_cursors">测量光标</h3><ul id="help-cursors-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_export">数据导出</h3><ul id="help-export-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_shortcuts">键盘快捷键</h3><table class="help-kbd-table" id="help-kbd-table"></table></div>
      <div class="help-section"><h3 data-i18n="help_rawlog">Raw Log 面板</h3><ul id="help-rawlog-list"></ul></div>
      <div class="help-section"><h3 data-i18n="help_pause_resume">暂停/恢复</h3><ul id="help-pause-list"></ul></div>
    </div>
  </div>
</div>`
}

function injectScripts(el: HTMLDivElement, mode: string) {
  // 1. Set CONFIG globally
  const configScript = document.createElement('script')
  configScript.textContent = `
    var CONFIG = {
      maxPoints: 10000,
      title: "MKLink ${mode}",
      mode: "${mode}",
      lang: "zh",
      deviceConnected: ${props.deviceConnected}
    };
  `
  el.appendChild(configScript)

  // 2. Load i18n script
  const i18nScript = document.createElement('script')
  i18nScript.src = i18nUrl
  i18nScript.onload = () => {
    // DOMContentLoaded already fired, call applyI18n manually
    if (typeof (window as any).applyI18n === 'function') {
      ;(window as any).applyI18n()
    }
    // 3. Load main viewer script after i18n
    loadViewerScript(el)
  }
  el.appendChild(i18nScript)
}

function loadViewerScript(el: HTMLDivElement) {
  const viewerScript = document.createElement('script')
  viewerScript.src = viewerUrl
  viewerScript.onload = () => {
    // Store es reference for cleanup (var es leaks to window in classic scripts)
    const viewers = (window as any).__waveformViewers
    if (viewers && !viewers[props.mode]) {
      viewers[props.mode] = { es: (window as any).es }
    } else if (viewers?.[props.mode]) {
      viewers[props.mode].es = (window as any).es
    }
    if (props.mode === 'VOFA' && viewers?.VOFA) {
      viewers.VOFA.configureBinaryChannels?.(vofaChannels)
      if (pendingBatch) {
        viewers.VOFA.acceptBinaryBatch?.(pendingBatch, vofaChannels)
        pendingBatch = null
      }
    }
  }
  el.appendChild(viewerScript)
}
</script>

<style scoped>
.waveform-viewer {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
