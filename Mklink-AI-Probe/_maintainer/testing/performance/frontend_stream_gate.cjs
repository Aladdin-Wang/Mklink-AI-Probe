/* Short real-Edge HIL gate for SystemView, VOFA, and SuperWatch rendering. */
'use strict'

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

const STREAMS = new Set(['systemview', 'vofa', 'superwatch'])

function processWorkingSet(profileMarker) {
  if (process.platform !== 'win32') return null
  const escaped = profileMarker.replaceAll("'", "''")
  const command = [
    `$needle='${escaped}'`,
    "$sum=(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'msedge.exe' -and $_.CommandLine -like \"*$needle*\" } | Measure-Object WorkingSetSize -Sum).Sum",
    'if ($null -eq $sum) { 0 } else { [Int64]$sum }',
  ].join('; ')
  try {
    return Number(execFileSync('powershell.exe', ['-NoProfile', '-Command', command], {
      encoding: 'utf8', windowsHide: true, timeout: 5_000,
    }).trim())
  } catch {
    return null
  }
}

function backendProduced(stream, status) {
  if (stream === 'systemview') return Number(status?.stats?.events || 0)
  if (stream === 'vofa') return Number(status?.completed_samples || 0)
  return Number(status?.stream?.produced_items || status?.read_cycles || 0)
}

function backendDropCounter(stream, status) {
  if (stream === 'systemview') {
    return [
      'dropped_bytes', 'dropped_packets', 'parser_dropped_bytes',
      'parser_dropped_packets', 'target_dropped_packets_since_baseline',
    ].reduce((sum, key) => sum + Number(status?.[key] || 0), 0)
  }
  let sum = Number(status?.read_errors || 0) + Number(status?.read_drops || 0)
  sum += Number(status?.binary_drops?.batches || 0) + Number(status?.binary_drops?.items || 0)
  sum += Number(status?.stream?.dropped_batches || 0) + Number(status?.stream?.dropped_items || 0)
  for (const [key, value] of Object.entries(status?.stream_integrity || {})) {
    if (/(drop|error|crc|overflow|flag)/i.test(key)) sum += Number(value || 0)
  }
  return sum
}

function phaseDelta(after, before, stream) {
  return {
    dataFrames: after.gate.dataFrames - before.gate.dataFrames,
    dataItems: after.gate.dataItems - before.gate.dataItems,
    workerMessages: after.gate.workerMessages - before.gate.workerMessages,
    workerAcceptedFrames: Number(after.gate.lastTelemetry?.acceptedFrames || 0)
      - Number(before.gate.lastTelemetry?.acceptedFrames || 0),
    backendProduced: backendProduced(stream, after.status) - backendProduced(stream, before.status),
    backendDropCounter: backendDropCounter(stream, after.status) - backendDropCounter(stream, before.status),
    targetCanvasClearCalls: after.gate.targetCanvasClearCalls - before.gate.targetCanvasClearCalls,
    targetCanvasStrokeCalls: after.gate.targetCanvasStrokeCalls - before.gate.targetCanvasStrokeCalls,
  }
}

async function apiJson(request, baseUrl, method, endpoint, data) {
  const attempts = method === 'GET' ? 3 : 1
  let lastError
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      const response = await request.fetch(`${baseUrl}${endpoint}`, { method, data })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok()) throw new Error(`${method} ${endpoint}: HTTP ${response.status()} ${JSON.stringify(payload)}`)
      return payload
    } catch (error) {
      lastError = error
      if (attempt + 1 < attempts) await new Promise(resolve => setTimeout(resolve, 250 * (attempt + 1)))
    }
  }
  throw lastError
}

async function stopAll(request, baseUrl) {
  for (const stream of ['systemview', 'vofa', 'superwatch', 'rtt']) {
    await request.post(`${baseUrl}/api/dash/${stream}/stop`).catch(() => {})
  }
}

async function resolveSymbol(request, baseUrl, name) {
  const response = await apiJson(request, baseUrl, 'GET', `/api/symbols/search?q=${encodeURIComponent(name)}`)
  const exact = (response.results || []).find(item => item.name === name)
  if (!exact || !Number.isSafeInteger(Number(exact.address))) throw new Error(`AXF symbol not found: ${name}`)
  return Number(exact.address)
}

async function prepareStream(stream, request, baseUrl, resetDelayMs = 1_000) {
  await stopAll(request, baseUrl)
  await apiJson(request, baseUrl, 'POST', '/api/device/reset')
  await new Promise(resolve => setTimeout(resolve, resetDelayMs))
  if (stream === 'systemview') {
    for (const [name, value] of [
      ['mklink_sv_user_event_pairs_per_tick', 1],
      ['mklink_sv_user_event_counter', 0],
      ['mklink_sv_test_arm', 0],
    ]) {
      await apiJson(request, baseUrl, 'POST', '/api/device/write-variable', { name, value })
    }
    return
  }
  if (stream === 'vofa') {
    const channels = []
    for (const name of ['vofa_test_sin', 'vofa_test_tri']) {
      const address = await resolveSymbol(request, baseUrl, name)
      channels.push({ name, addr: `0x${address.toString(16)}`, type: 'float', size: 4 })
    }
    await apiJson(request, baseUrl, 'POST', '/api/dash/vofa/start', { channels, interval: 0.00001 })
    return
  }
  const current = await apiJson(request, baseUrl, 'GET', '/api/dash/superwatch/items')
  for (const item of current.items || []) {
    await apiJson(request, baseUrl, 'POST', '/api/dash/superwatch/remove', { name: item.name })
  }
  for (const name of ['vofa_test_sin', 'vofa_test_tri']) {
    await resolveSymbol(request, baseUrl, name)
    await apiJson(request, baseUrl, 'POST', '/api/dash/superwatch/add', { name })
  }
  await apiJson(request, baseUrl, 'POST', '/api/dash/superwatch/interval', { interval: 0.00001 })
  await apiJson(request, baseUrl, 'POST', '/api/dash/superwatch/start')
}

async function firstControlStatus(context, baseUrl, stream) {
  const probe = await context.newPage()
  try {
    return await probe.evaluate(({ baseUrl, stream }) => new Promise((resolve, reject) => {
      const url = new URL(baseUrl)
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      url.pathname = `/ws/streams/${stream}`
      url.hash = ''
      url.search = ''
      const socket = new WebSocket(url)
      socket.binaryType = 'arraybuffer'
      const timer = setTimeout(() => { socket.close(); reject(new Error('control status timeout')) }, 5_000)
      socket.onmessage = event => {
        if (!(event.data instanceof ArrayBuffer) || event.data.byteLength < 36) return
        const view = new DataView(event.data)
        if (view.getUint8(5) !== 255) return
        clearTimeout(timer)
        const payload = JSON.parse(new TextDecoder().decode(new Uint8Array(event.data, 36)))
        socket.close()
        resolve(payload)
      }
      socket.onerror = () => { clearTimeout(timer); reject(new Error('control status socket error')) }
    }), { baseUrl, stream })
  } finally {
    await probe.close()
  }
}

async function main() {
  const stream = String(process.argv[2] || process.env.MKLINK_STREAM || '').toLowerCase()
  if (!STREAMS.has(stream)) throw new Error('stream must be systemview, vofa, or superwatch')
  const playwrightPath = process.env.PLAYWRIGHT_CORE_PATH
  const browserExecutable = process.env.BROWSER_EXECUTABLE
  if (!playwrightPath) throw new Error('PLAYWRIGHT_CORE_PATH is required')
  if (!browserExecutable || !fs.existsSync(browserExecutable)) throw new Error('BROWSER_EXECUTABLE is required')
  const { chromium } = require(playwrightPath)
  const baseUrl = process.env.MKLINK_GUI_URL || 'http://127.0.0.1:8765'
  const profileMarker = `mklink-${stream}-gate-${process.pid}-${Date.now()}`
  const profileDir = path.join(os.tmpdir(), profileMarker)
  const context = await chromium.launchPersistentContext(profileDir, {
    executablePath: browserExecutable,
    headless: process.env.BROWSER_HEADLESS !== '0',
    viewport: { width: 1600, height: 1000 },
    args: ['--disable-gpu-sandbox'],
  })
  const page = context.pages()[0] || await context.newPage()
  page.setDefaultTimeout(30_000)
  await page.addInitScript(targetStream => {
    const gate = window.__mklinkGate = {
      workerUrls: [], websocketUrls: [], dataFrames: 0, dataItems: 0,
      dataBytes: 0, lastDataSequence: null, sequenceErrors: 0,
      workerMessages: 0, telemetryMessages: 0, lastTelemetry: null,
      targetCanvasClearCalls: 0, targetCanvasStrokeCalls: 0,
    }
    const safeCopy = value => Object.fromEntries(Object.entries(value || {}).map(([key, item]) => [
      key, typeof item === 'bigint' ? item.toString() : item,
    ]))
    const NativeWorker = window.Worker
    window.Worker = class GateWorker extends NativeWorker {
      constructor(url, options) {
        super(url, options)
        gate.workerUrls.push(String(url))
        this.addEventListener('message', event => {
          gate.workerMessages += 1
          if (event.data?.type === 'telemetry') {
            gate.telemetryMessages += 1
            gate.lastTelemetry = safeCopy(event.data)
          }
        })
      }
    }
    const NativeWebSocket = window.WebSocket
    window.WebSocket = class GateWebSocket extends NativeWebSocket {
      constructor(url, protocols) {
        super(url, protocols)
        const textUrl = String(url)
        gate.websocketUrls.push(textUrl)
        this.addEventListener('message', event => {
          if (!textUrl.includes(`/ws/streams/${targetStream}`) || !(event.data instanceof ArrayBuffer) || event.data.byteLength < 36) return
          const bytes = new Uint8Array(event.data)
          if (bytes[0] !== 0x4d || bytes[1] !== 0x4b || bytes[2] !== 0x53 || bytes[3] !== 0x54) return
          const view = new DataView(event.data)
          if (view.getUint8(5) === 255) return
          const sequence = view.getBigUint64(12, true)
          if (gate.lastDataSequence !== null && sequence !== BigInt(gate.lastDataSequence) + 1n) gate.sequenceErrors += 1
          gate.lastDataSequence = sequence.toString()
          gate.dataFrames += 1
          gate.dataItems += view.getUint32(28, true)
          gate.dataBytes += event.data.byteLength
        })
      }
    }
    const clearRect = CanvasRenderingContext2D.prototype.clearRect
    CanvasRenderingContext2D.prototype.clearRect = function (...args) {
      if (this.canvas?.dataset?.mklinkGate === 'target') gate.targetCanvasClearCalls += 1
      return clearRect.apply(this, args)
    }
    const stroke = CanvasRenderingContext2D.prototype.stroke
    CanvasRenderingContext2D.prototype.stroke = function (...args) {
      if (this.canvas?.dataset?.mklinkGate === 'target') gate.targetCanvasStrokeCalls += 1
      return stroke.apply(this, args)
    }
  }, stream)

  const consoleErrors = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('pageerror', error => consoleErrors.push(String(error)))
  let peakBrowserWorkingSetBytes = 0
  const memoryTimer = setInterval(() => {
    const value = processWorkingSet(profileMarker)
    if (Number.isFinite(value)) peakBrowserWorkingSetBytes = Math.max(peakBrowserWorkingSetBytes, value)
  }, 1_000)
  const statusEndpoint = `/api/dash/${stream}/status`
  const snapshot = async label => {
    const status = await apiJson(page.request, baseUrl, 'GET', statusEndpoint)
    const gate = await page.evaluate(() => ({ ...window.__mklinkGate }))
    return { label, timestampMs: Date.now(), status, gate }
  }

  let result
  let exitCode = 0
  try {
    await prepareStream(stream, page.request, baseUrl)
    await page.goto(`${baseUrl}/#/dashboard?tab=${stream}`, { waitUntil: 'domcontentloaded' })
    if (stream === 'systemview') {
      const toolbar = page.locator('.sv-tab:visible .control-toolbar')
      // The dashboard owns target_debug while running, so arm immediately
      // before Start. The fixture's one-second delay lets host sync first.
      await apiJson(page.request, baseUrl, 'POST', '/api/device/write-variable', {
        name: 'mklink_sv_test_arm', value: 1,
      })
      await toolbar.locator('.btn-primary').click()
      await page.waitForFunction(target => window.__mklinkGate.websocketUrls
        .some(url => url.includes(`/ws/streams/${target}`)), stream, { timeout: 60_000 })
      for (let attempt = 0; attempt < 60; attempt++) {
        const status = await apiJson(page.request, baseUrl, 'GET', statusEndpoint)
        if (status.running && status.synced) break
        if (attempt === 59) throw new Error('SystemView did not reach running+synced before arm')
        await page.waitForTimeout(500)
      }
    }
    const canvas = stream === 'systemview'
      ? page.locator('.sv-tab:visible canvas').first()
      : page.locator('.waveform-viewer:visible #chart')
    await canvas.waitFor({ state: 'visible' })
    await canvas.evaluate(node => { node.dataset.mklinkGate = 'target' })
    const pauseButton = stream === 'systemview'
      ? page.locator('.sv-tab:visible .control-toolbar .btn:not(.btn-danger)')
      : page.locator('.waveform-viewer:visible #btn-pause')
    await page.waitForFunction(target => {
      const gate = window.__mklinkGate
      return gate.websocketUrls.some(url => url.includes(`/ws/streams/${target}`))
        && gate.dataFrames > 5
        && Number(gate.lastTelemetry?.acceptedFrames || 0) > 5
        && Number(gate.lastTelemetry?.bufferedSamples || 0) > 0
    }, stream, { timeout: 60_000 })
    await pauseButton.waitFor({ state: 'visible' })
    await page.waitForFunction(selector => !document.querySelector(selector)?.disabled,
      stream === 'systemview' ? '.sv-tab .control-toolbar .btn:not(.btn-danger)' : '.waveform-viewer #btn-pause')

    // Initial parser synchronization and target FIFO fill are warm-up, not
    // part of the measured gate. Require two stable one-second drop samples.
    let warmup = await snapshot('warmup_start')
    let stableDropSamples = 0
    const minimumWarmupSeconds = stream === 'systemview' ? 10 : 2
    for (let attempt = 0; attempt < 20; attempt++) {
      await page.waitForTimeout(1_000)
      const next = await snapshot('warmup_probe')
      if (backendDropCounter(stream, next.status) === backendDropCounter(stream, warmup.status)) {
        stableDropSamples += 1
      } else {
        stableDropSamples = 0
      }
      warmup = next
      if (attempt + 1 >= minimumWarmupSeconds && stableDropSamples >= 2) break
    }
    if (stableDropSamples < 2) throw new Error('backend drop counters did not stabilize during warm-up')

    const visibleStart = await snapshot('visible_start')
    await page.waitForTimeout(10_000)
    const visibleEnd = await snapshot('visible_end')
    await pauseButton.click()
    await page.waitForTimeout(1_000)
    const pauseStart = await snapshot('pause_start')
    await page.waitForTimeout(5_000)
    const pauseEnd = await snapshot('pause_end')
    const resumeButton = stream === 'systemview'
      ? page.locator('.sv-tab:visible .control-toolbar .btn-primary')
      : page.locator('.waveform-viewer:visible #btn-pause')
    await resumeButton.click()
    await page.waitForTimeout(1_000)
    const resumeStart = await snapshot('resume_start')
    await page.waitForTimeout(5_000)
    const resumeEnd = await snapshot('resume_end')

    const visible = phaseDelta(visibleEnd, visibleStart, stream)
    const pause = phaseDelta(pauseEnd, pauseStart, stream)
    const resume = phaseDelta(resumeEnd, resumeStart, stream)
    const visibleSeconds = (visibleEnd.timestampMs - visibleStart.timestampMs) / 1_000
    const resumeSeconds = (resumeEnd.timestampMs - resumeStart.timestampMs) / 1_000
    const visibleRenderFps = visible.targetCanvasClearCalls / visibleSeconds
    const resumeRenderFps = resume.targetCanvasClearCalls / resumeSeconds
    const telemetry = resumeEnd.gate.lastTelemetry || {}
    const checks = {
      hashedWorker: resumeEnd.gate.workerUrls.some(url => /streamDecoder\.worker-[\w-]+\.js/.test(url)),
      binaryWebSocket: resumeEnd.gate.websocketUrls.some(url => url.includes(`/ws/streams/${stream}`)),
      visibleDataAndWorker: visible.dataFrames > 0 && visible.workerAcceptedFrames > 0 && Number(telemetry.bufferedSamples || 0) > 0,
      visibleCanvas: visible.targetCanvasClearCalls > 0,
      visibleFpsCapped: visibleRenderFps > 0 && visibleRenderFps <= 30.5,
      pauseCollectionContinues: pause.dataFrames > 0 && pause.workerAcceptedFrames > 0 && pause.backendProduced > 0,
      pauseRenderingStops: pause.targetCanvasClearCalls === 0 && pause.targetCanvasStrokeCalls === 0,
      resumeDataAndCanvas: resume.dataFrames > 0 && resume.workerAcceptedFrames > 0 && resume.targetCanvasClearCalls > 0,
      resumeFpsCapped: resumeRenderFps > 0 && resumeRenderFps <= 30.5,
      backendDropIncrement: backendDropCounter(stream, resumeEnd.status) - backendDropCounter(stream, visibleStart.status),
      frontendSequenceErrors: resumeEnd.gate.sequenceErrors,
      frontendTransportDroppedBatches: Number(telemetry.transportDroppedBatches || 0),
      frontendBackendDroppedItems: Number(telemetry.backendDroppedItems || 0),
      targetDropPacketsDuringMeasuredGate: stream === 'systemview'
        ? Number(resumeEnd.status?.target_dropped_packets_since_baseline || 0)
          - Number(visibleStart.status?.target_dropped_packets_since_baseline || 0) : 0,
      targetOverflowEventsDuringMeasuredGate: stream === 'systemview'
        ? Number(resumeEnd.status?.target_overflow_events || 0)
          - Number(visibleStart.status?.target_overflow_events || 0) : 0,
      consoleErrors: consoleErrors.length,
    }
    const checksPass = checks.hashedWorker
      && checks.binaryWebSocket
      && checks.visibleDataAndWorker
      && checks.visibleCanvas
      && checks.visibleFpsCapped
      && checks.pauseCollectionContinues
      && checks.pauseRenderingStops
      && checks.resumeDataAndCanvas
      && checks.resumeFpsCapped
      && checks.backendDropIncrement === 0
      && checks.frontendSequenceErrors === 0
      && checks.frontendTransportDroppedBatches === 0
      && checks.frontendBackendDroppedItems === 0
      && checks.targetDropPacketsDuringMeasuredGate === 0
      && checks.targetOverflowEventsDuringMeasuredGate === 0
      && checks.consoleErrors === 0
    result = {
      schema_version: 1,
      date: new Date().toISOString().slice(0, 10),
      gate: `edge_${stream}_visible_pause_resume_hil`,
      result: checksPass ? 'pass' : 'fail',
      stream,
      browser: 'Microsoft Edge',
      headless: process.env.BROWSER_HEADLESS !== '0',
      peak_browser_working_set_bytes: peakBrowserWorkingSetBytes,
      rendering: { visible_fps: visibleRenderFps, resume_fps: resumeRenderFps },
      checks,
      deltas: { visible, pause, resume },
      final: {
        data_frames: resumeEnd.gate.dataFrames,
        data_items: resumeEnd.gate.dataItems,
        worker_accepted_frames: Number(telemetry.acceptedFrames || 0),
        worker_buffered_samples: Number(telemetry.bufferedSamples || 0),
        last_data_sequence: resumeEnd.gate.lastDataSequence,
        worker_last_sequence: telemetry.lastSequence || null,
      },
      integrity: {
        warmup_seconds_minimum: minimumWarmupSeconds,
        baseline: {
          backend_drop_counter: backendDropCounter(stream, visibleStart.status),
          target_drop_packets: Number(visibleStart.status?.target_dropped_packets_since_baseline || 0),
          target_overflow_events: Number(visibleStart.status?.target_overflow_events || 0),
        },
        final: {
          backend_drop_counter: backendDropCounter(stream, resumeEnd.status),
          target_drop_packets: Number(resumeEnd.status?.target_dropped_packets_since_baseline || 0),
          target_overflow_events: Number(resumeEnd.status?.target_overflow_events || 0),
        },
      },
      hidden_gate: {
        result: 'not-established',
        reason: 'Edge 130 rejects Emulation.setPageVisibilityOverride and a background tab did not set document.hidden=true on this platform.',
      },
      limitations: [
        'This short frontend gate supplements the separate 30-minute authenticated binary WebSocket HIL artifact.',
        ...(stream === 'systemview' ? ['The frontend gate uses one user-event pair per RTOS tick; the 30-minute backend limit gate uses two pairs per tick.'] : []),
        ...(stream === 'systemview' ? ['SystemView startup/SYNC loss is retained in the warm-up baseline; all measured visible, pause, and resume increments must remain zero.'] : []),
        'AXF symbol addresses were resolved at runtime and are intentionally not retained.',
      ],
    }

    let targetDearmed = null
    // Navigating the sole persistent-context page disconnects its Worker/WS
    // without disposing the context's request client (closing it does).
    await page.goto('about:blank', { waitUntil: 'domcontentloaded' })
    let control
    for (let attempt = 0; attempt < 10; attempt++) {
      control = await firstControlStatus(context, baseUrl, stream)
      if (Number(control.active_clients || 0) === 0) break
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    await apiJson(context.request, baseUrl, 'POST', `/api/dash/${stream}/stop`)
    if (stream === 'systemview') {
      await apiJson(context.request, baseUrl, 'POST', '/api/device/write-variable', {
        name: 'mklink_sv_test_arm', value: 0,
      })
      const armAddress = await resolveSymbol(context.request, baseUrl, 'mklink_sv_test_arm')
      const dearm = await apiJson(context.request, baseUrl, 'POST', '/api/device/read-memory', {
        address: `0x${armAddress.toString(16)}`, size: 4,
      })
      targetDearmed = Buffer.from(dearm.data_hex, 'hex').readUInt32LE(0) === 0
    }
    await new Promise(resolve => setTimeout(resolve, 500))
    const cleanupStatus = await apiJson(context.request, baseUrl, 'GET', statusEndpoint)
    const resources = await apiJson(context.request, baseUrl, 'GET', '/api/resources/status')
    result.cleanup = {
      running: cleanupStatus.running ?? cleanupStatus.state,
      binary_active_clients_before_probe: Number(control.active_clients || 0),
      resource_owner_present: Object.values(resources).some(item => item?.owner === `user:dashboard:${stream}`),
      target_dearmed: targetDearmed,
    }
    const cleanupPass = (cleanupStatus.running === false || cleanupStatus.state === 'stopped')
      && result.cleanup.binary_active_clients_before_probe === 0
      && result.cleanup.resource_owner_present === false
      && (stream !== 'systemview' || result.cleanup.target_dearmed === true)
    if (!cleanupPass) result.result = 'fail'
    if (result.result !== 'pass') exitCode = 1
  } catch (error) {
    result = { schema_version: 1, gate: `edge_${stream}_visible_pause_resume_hil`, result: 'error', error: String(error), consoleErrors }
    exitCode = 1
    await page.goto('about:blank', { waitUntil: 'domcontentloaded' }).catch(() => {})
    await context.request.post(`${baseUrl}/api/dash/${stream}/stop`).catch(() => {})
    if (stream === 'systemview') {
      await context.request.post(`${baseUrl}/api/device/write-variable`, { data: { name: 'mklink_sv_test_arm', value: 0 } }).catch(() => {})
    }
  } finally {
    clearInterval(memoryTimer)
    peakBrowserWorkingSetBytes = Math.max(peakBrowserWorkingSetBytes, processWorkingSet(profileMarker) || 0)
    if (result) result.peak_browser_working_set_bytes = peakBrowserWorkingSetBytes
    await context.close()
    fs.rmSync(profileDir, { recursive: true, force: true })
  }
  console.log(JSON.stringify(result, null, 2))
  process.exitCode = exitCode
}

module.exports = { backendDropCounter, backendProduced, phaseDelta, prepareStream }

if (require.main === module) {
  main().catch(error => {
    console.error(error)
    process.exitCode = 1
  })
}
