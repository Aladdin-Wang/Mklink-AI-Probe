/* Five-minute physical stream smoke for an already-running packaged Tauri WebView. */
'use strict'

const fs = require('node:fs')
const { execFileSync } = require('node:child_process')

const STREAM_PROFILES = Object.freeze({
  rtt: Object.freeze({
    tab: 'RTT View', websocketName: 'rtt', apiName: 'rtt',
    owner: 'user:dashboard:rtt', root: '.rtt-view-tab:visible',
    canvas: '.rtt-view-tab canvas.rtt-numeric-chart',
    minimumStableWarmupSeconds: 0,
    start: '.control-toolbar .btn-primary', pause: '.control-toolbar .btn:not(.btn-danger)',
    resume: '.control-toolbar .btn-primary', stop: '.control-toolbar .btn-danger',
  }),
  systemview: Object.freeze({
    tab: 'RTOS Trace', websocketName: 'systemview', apiName: 'systemview',
    owner: 'user:dashboard:systemview', root: '.sv-tab:visible',
    canvas: '.sv-tab .sv-canvas-wrap canvas',
    minimumStableWarmupSeconds: 10,
    start: '.control-toolbar .btn-primary', pause: '.control-toolbar .btn:not(.btn-danger)',
    resume: '.control-toolbar .btn-primary', stop: '.control-toolbar .btn-danger',
  }),
  vofa: Object.freeze({
    tab: 'VOFA+', websocketName: 'vofa', apiName: 'vofa',
    owner: 'user:dashboard:vofa', root: '.waveform-viewer:visible',
    canvas: '.waveform-viewer #chart',
    minimumStableWarmupSeconds: 0,
    start: '#btn-start', pause: '#btn-pause', resume: '#btn-pause', stop: '#btn-stop',
  }),
  superwatch: Object.freeze({
    tab: 'SuperWatch', websocketName: 'superwatch', apiName: 'superwatch',
    owner: 'user:dashboard:superwatch', root: '.waveform-viewer:visible',
    canvas: '.waveform-viewer #chart',
    minimumStableWarmupSeconds: 0,
    start: '#btn-start', pause: '#btn-pause', resume: '#btn-pause', stop: '#btn-stop',
  }),
})

function streamProfile(name) {
  const profile = STREAM_PROFILES[name]
  if (!profile) throw new Error(`unsupported packaged stream: ${name}`)
  return profile
}

function streamRunningState(status) {
  if (typeof status?.running === 'boolean') return status.running
  if (typeof status?.state === 'string') return status.state !== 'stopped'
  return null
}

function processTreeWorkingSet(rootPid) {
  const pid = Number(rootPid)
  if (process.platform !== 'win32' || !Number.isInteger(pid) || pid <= 0) return null
  const command = [
    '$all=Get-CimInstance Win32_Process',
    `$root=${pid}`,
    '$ids=New-Object System.Collections.Generic.HashSet[int]',
    '$null=$ids.Add($root)',
    'do{$added=$false;foreach($p in $all){if($ids.Contains([int]$p.ParentProcessId)-and $ids.Add([int]$p.ProcessId)){$added=$true}}}while($added)',
    '$sum=($all|Where-Object{$ids.Contains([int]$_.ProcessId)}|Measure-Object WorkingSetSize -Sum).Sum',
    'if($null -eq $sum){0}else{[Int64]$sum}',
  ].join(';')
  try {
    return Number(execFileSync('powershell.exe', ['-NoProfile', '-Command', command], {
      encoding: 'utf8', windowsHide: true, timeout: 10_000,
    }).trim())
  } catch {
    return null
  }
}

async function streamSnapshot(page, baseUrl, profile) {
  const gate = await page.evaluate(() => ({ ...window.__mklinkPackagedGate }))
  const status = await apiJson(baseUrl, `/api/dash/${profile.apiName}/status`)
  return { timestampMs: Date.now(), gate, status }
}

function streamDelta(after, before) {
  return {
    dataFrames: Number(after.gate.dataFrames || 0) - Number(before.gate.dataFrames || 0),
    dataItems: Number(after.gate.dataItems || 0) - Number(before.gate.dataItems || 0),
    dataBytes: Number(after.gate.dataBytes || 0) - Number(before.gate.dataBytes || 0),
    workerAcceptedFrames: Number(after.gate.lastTelemetry?.acceptedFrames || 0)
      - Number(before.gate.lastTelemetry?.acceptedFrames || 0),
    backendProducedItems: Number(after.status?.stream?.produced_items || 0)
      - Number(before.status?.stream?.produced_items || 0),
    canvasFrames: Number(after.gate.canvasClearCalls || 0) - Number(before.gate.canvasClearCalls || 0),
    canvasStrokes: Number(after.gate.canvasStrokeCalls || 0) - Number(before.gate.canvasStrokeCalls || 0),
  }
}

async function apiJson(baseUrl, path, options = {}) {
  let lastError
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(`${baseUrl}${path}`, options)
      if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`)
      return await response.json()
    } catch (error) {
      lastError = error
      await new Promise(resolve => setTimeout(resolve, 250 * (attempt + 1)))
    }
  }
  throw lastError
}

function memoryWriteBody(write) {
  return { address: write.address, data_hex: write.data_hex }
}

async function applyMemoryWrites(baseUrl, writes) {
  for (const write of writes) {
    await apiJson(baseUrl, '/api/device/write-memory', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(memoryWriteBody(write)),
    })
  }
}

async function startPackagedStream(apiStart, uiStart, startBodyText) {
  if (startBodyText !== undefined) await apiStart(JSON.parse(startBodyText))
  await uiStart()
}

async function waitForStreamStartControl(streamRoot, selector) {
  const control = streamRoot.locator(selector)
  await control.waitFor({ state: 'visible', timeout: 60_000 })
  return control
}

async function waitForStreamUiReady(page, streamRoot, profile) {
  if (profile.apiName !== 'vofa') return
  const intervalInput = streamRoot.locator('#interval-input')
  await intervalInput.waitFor({ state: 'visible', timeout: 60_000 })
  const inputHandle = await intervalInput.elementHandle()
  if (!inputHandle) throw new Error('VOFA interval input is unavailable')
  await page.waitForFunction(input => {
    const value = Number(input.value)
    return Number.isFinite(value) && value > 0
  }, inputHandle, { timeout: 60_000 })
}

async function waitForFrontendDeviceConnection(page) {
  await page.locator('.status-bar .badge-ok').waitFor({ state: 'visible', timeout: 60_000 })
}

async function waitForWarmStream(page) {
  try {
    await page.waitForFunction(() => {
      const gate = window.__mklinkPackagedGate
      return gate?.dataFrames > 5
        && Number(gate.lastTelemetry?.acceptedFrames || 0) > 5
        && Number(gate.lastTelemetry?.bufferedSamples || 0) > 0
    }, null, { timeout: 60_000 })
  } catch {
    throw new Error('stream WebSocket/Worker did not warm within 60 seconds')
  }
  const canvasBaseline = await page.evaluate(() => ({
    clears: window.__mklinkPackagedGate.canvasClearCalls,
    strokes: window.__mklinkPackagedGate.canvasStrokeCalls,
  }))
  try {
    await page.waitForFunction(baseline => (
      window.__mklinkPackagedGate?.canvasClearCalls > baseline.clears
        && window.__mklinkPackagedGate?.canvasStrokeCalls > baseline.strokes
    ), canvasBaseline, { timeout: 60_000 })
  } catch {
    throw new Error('primary canvas did not clear and stroke within 60 seconds')
  }
}

function lossCounterKey(status) {
  return JSON.stringify([
    Number(status?.stream?.dropped_batches || 0),
    Number(status?.stream?.dropped_items || 0),
    Number(status?.stream?.dropped_bytes || 0),
    Number(status?.parser_dropped_bytes || 0),
    Number(status?.parser_dropped_packets || 0),
    Number(status?.target_dropped_packets_since_baseline || 0),
    Number(status?.target_overflow_events || 0),
  ])
}

async function waitForStableLossCounters(page, baseUrl, profile) {
  const minimumSeconds = Number(profile.minimumStableWarmupSeconds || 0)
  if (minimumSeconds <= 0) return
  let previous = null
  let stableSamples = 0
  for (let elapsedSeconds = 1; elapsedSeconds <= minimumSeconds + 20; elapsedSeconds++) {
    await page.waitForTimeout(1_000)
    const status = await apiJson(baseUrl, `/api/dash/${profile.apiName}/status`)
    const current = lossCounterKey(status)
    stableSamples = current === previous ? stableSamples + 1 : 0
    previous = current
    if (elapsedSeconds >= minimumSeconds && stableSamples >= 2) return
  }
  throw new Error(`${profile.apiName} loss counters did not stabilize during warmup`)
}

async function selectDashboardStreamTab(page, label) {
  await page.locator('.tabs-bar .tab-btn').filter({ hasText: label }).click()
}

function acceptPageDialogs(page) {
  page.on('dialog', dialog => { void dialog.accept() })
}

async function leaveDashboard(page, streamRoot) {
  await page.evaluate(() => { window.location.hash = '#/config' })
  if (streamRoot) await streamRoot.waitFor({ state: 'detached', timeout: 10_000 })
}

async function verifyMemoryWrites(baseUrl, writes) {
  if (writes.length === 0) return false
  for (const write of writes) {
    const expected = String(write.data_hex || '').toLowerCase()
    if (!expected || expected.length % 2 !== 0) return false
    const readback = await apiJson(baseUrl, '/api/device/read-memory', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ address: write.address, size: expected.length / 2 }),
    })
    if (String(readback.data_hex || '').toLowerCase() !== expected) return false
  }
  return true
}

async function verifyTargetArmWrites(writes, verifier) {
  return writes.length === 0 ? true : await verifier()
}

function sameNumber(left, right) {
  return Number.isFinite(Number(left))
    && Number.isFinite(Number(right))
    && Math.abs(Number(left) - Number(right)) <= 1e-12
}

function sameStringArray(left, right) {
  return Array.isArray(left) && Array.isArray(right)
    && left.length === right.length
    && left.every((value, index) => value === right[index])
}

function littleEndianHexValue(value) {
  const hex = String(value || '').toLowerCase()
  if (!hex || hex.length % 2 !== 0 || !/^[0-9a-f]+$/.test(hex) || hex.length > 12) return null
  const bytes = Buffer.from(hex, 'hex')
  let decoded = 0
  for (let index = bytes.length - 1; index >= 0; index--) decoded = decoded * 256 + bytes[index]
  return Number.isSafeInteger(decoded) ? decoded : null
}

function sanitizedControls(controls) {
  if (!Array.isArray(controls)) return []
  return controls.map(control => ({
    symbol: String(control?.symbol || ''),
    maskedAddress: String(control?.maskedAddress || ''),
    value: Number(control?.value),
  }))
}

function buildFixtureEvidence({
  streamName, fixture, targetWrites, targetArmed, prepareRequests, startBodyText, endStatus,
}) {
  const expected = fixture && typeof fixture === 'object' ? fixture : {}
  const evidence = { stream: streamName, validated: false }
  if (expected.stream !== streamName || targetArmed !== true) return evidence

  if (streamName === 'rtt' || streamName === 'systemview') {
    const controls = sanitizedControls(expected.controls)
    const writes = Array.isArray(targetWrites) ? targetWrites : []
    const controlsValid = controls.length > 0 && controls.length === writes.length
      && controls.every(control => {
        const write = writes.find(item => item?.symbol === control.symbol)
        return write
          && write.maskedAddress === control.maskedAddress
          && Number(write.value) === control.value
          && littleEndianHexValue(write.data_hex) === control.value
          && /^0x[0-9a-f*]+$/i.test(control.maskedAddress)
          && control.maskedAddress.includes('*')
      })
    return { ...evidence, controls, validated: controlsValid }
  }

  const channels = Array.isArray(expected.channels)
    ? expected.channels.map(value => String(value))
    : []
  const status = endStatus || {}
  const statusChannels = (streamName === 'superwatch' ? status.items : status.channels) || []
  const statusNames = statusChannels.map(item => String(item?.name || ''))
  const statusValid = channels.length === 2
    && sameStringArray(statusNames, channels)
    && sameNumber(status.interval, expected.intervalSeconds)
    && status.acquisition_mode === expected.acquisitionMode

  if (streamName === 'vofa') {
    let startBody = null
    try { startBody = JSON.parse(startBodyText || '') } catch { startBody = null }
    const startNames = Array.isArray(startBody?.channels)
      ? startBody.channels.map(item => String(item?.name || ''))
      : []
    const startValid = sameStringArray(startNames, channels)
      && sameNumber(startBody?.interval, expected.intervalSeconds)
    return {
      ...evidence, channels, intervalSeconds: Number(expected.intervalSeconds),
      acquisitionMode: String(expected.acquisitionMode || ''),
      validated: startValid && statusValid,
    }
  }

  if (streamName === 'superwatch') {
    const requests = Array.isArray(prepareRequests) ? prepareRequests : []
    const addedNames = requests
      .filter(request => request?.path === '/api/dash/superwatch/add')
      .map(request => String(request?.body?.name || ''))
    const intervalRequest = requests.find(
      request => request?.path === '/api/dash/superwatch/interval',
    )
    const prepareValid = sameStringArray(addedNames, channels)
      && sameNumber(intervalRequest?.body?.interval, expected.intervalSeconds)
    return {
      ...evidence, channels, intervalSeconds: Number(expected.intervalSeconds),
      acquisitionMode: String(expected.acquisitionMode || ''),
      validated: prepareValid && statusValid,
    }
  }

  return evidence
}

async function cleanupPackagedGate(baseUrl, page, streamRoot, profile, targetDearmWrites) {
  try { await streamRoot?.locator(profile.stop).click({ timeout: 5_000 }) } catch { /* REST fallback below */ }
  try { await apiJson(baseUrl, `/api/dash/${profile.apiName}/stop`, { method: 'POST' }) } catch { /* status check reports failure */ }
  let targetDearmed = false
  try {
    await applyMemoryWrites(baseUrl, targetDearmWrites)
    targetDearmed = await verifyMemoryWrites(baseUrl, targetDearmWrites)
  } catch { /* reported by targetDearmed=false */ }
  try { await leaveDashboard(page, streamRoot) } catch { /* active client check reports failure */ }

  let status = {}
  let resources = null
  let resourceStatusAvailable = false
  for (let attempt = 0; attempt < 10; attempt++) {
    try { status = await apiJson(baseUrl, `/api/dash/${profile.apiName}/status`) } catch { status = {} }
    try {
      resources = await apiJson(baseUrl, '/api/resources/status')
      resourceStatusAvailable = true
    } catch {
      resources = null
      resourceStatusAvailable = false
    }
    const ownerPresent = resourceStatusAvailable
      ? Object.values(resources).some(item => item?.owner === profile.owner)
      : null
    if (streamRunningState(status) === false
      && Number(status.stream?.active_clients || 0) === 0
      && resourceStatusAvailable
      && ownerPresent === false) break
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  return {
    running: streamRunningState(status),
    activeClients: Number(status.stream?.active_clients || 0),
    resourceStatusAvailable,
    resourceOwnerPresent: resourceStatusAvailable
      ? Object.values(resources).some(item => item?.owner === profile.owner)
      : null,
    targetDearmed,
  }
}

async function runWithCleanup(operation, cleanupOperation) {
  let value = null
  let primaryError = null
  let cleanup = null
  let cleanupError = null
  try {
    value = await operation()
  } catch (error) {
    primaryError = error
  } finally {
    try {
      cleanup = await cleanupOperation()
    } catch (error) {
      cleanupError = error
    }
  }
  return { value, primaryError, cleanup, cleanupError }
}

async function cleanupAndDisconnect(cleanupOperation, browser) {
  try {
    return await cleanupOperation()
  } finally {
    await browser.close()
  }
}

async function runBrowserLifecycle(
  connectBrowser, operation, stopSampling = () => {}, onBrowserClosed = () => {},
) {
  let browser = null
  try {
    browser = await connectBrowser()
    return await operation(browser)
  } finally {
    stopSampling()
    if (browser) {
      await browser.close()
      onBrowserClosed()
    }
  }
}

function systemViewTaskNameEvidence(streamName, taskNames) {
  if (streamName !== 'systemview') {
    return { required: false, taskNameCount: 0, invalidTaskNameCount: 0, valid: true }
  }
  const names = Object.values(taskNames || {})
  const invalidTaskNameCount = names.filter(name => (
    typeof name !== 'string'
      || name.trim().length === 0
      || [...name.trim()].length > 32
      || /[\p{Cc}\p{Cf}\p{Cs}\ufffd]/u.test(name)
  )).length
  return {
    required: true,
    taskNameCount: names.length,
    invalidTaskNameCount,
    valid: names.length > 0 && invalidTaskNameCount === 0,
  }
}

function evaluatePackagedGate(metrics) {
  const telemetry = metrics.workerTelemetry || {}
  const backendDrops = metrics.backendDrops || {}
  const parserDrops = metrics.parserDrops || {}
  const targetDrops = metrics.targetDrops || {}
  const cleanup = metrics.cleanup || {}
  const workerAssetUrls = metrics.workerAssetUrls || []
  const websocketUrls = metrics.websocketUrls || []
  const renderFps = metrics.elapsedSeconds > 0 ? metrics.canvasFrames / metrics.elapsedSeconds : 0
  const pause = metrics.pause || {}
  const resume = metrics.resume || {}
  const taskNameEvidence = systemViewTaskNameEvidence(metrics.streamName, metrics.taskNames)
  const checks = {
    requiredWallClockDuration: metrics.elapsedSeconds >= metrics.requiredDurationSeconds,
    tauriAssetOrigin: workerAssetUrls.some(url => url.startsWith('http://tauri.localhost/')),
    hashedWorker: workerAssetUrls.some(url => /streamDecoder\.worker-[\w-]+\.js/.test(url)),
    binaryWebSocket: websocketUrls.some(url => url.includes(`/ws/streams/${metrics.streamName}`)),
    dataFrames: metrics.dataFrames > 0 && metrics.dataItems > 0,
    workerDecodedData: metrics.workerAcceptedFrames > 0 && metrics.workerBufferedSamples > 0,
    workerFrameParity: Number(metrics.workerAcceptedFrames) === Number(metrics.wireFrames),
    workerSequenceParity: metrics.lastDataSequence != null
      && metrics.workerLastSequence != null
      && String(metrics.workerLastSequence) === String(metrics.lastDataSequence),
    canvasDrawn: metrics.canvasFrames > 0,
    canvasStroked: metrics.canvasStrokes > 0,
    renderFpsCapped: renderFps > 0 && renderFps <= 30.5,
    pauseCollectionContinues: Number(pause.dataFrames || 0) > 0
      && Number(pause.workerAcceptedFrames || 0) > 0
      && Number(pause.backendProducedItems || 0) > 0,
    pauseRenderingStops: Number(pause.canvasFrames || 0) === 0
      && Number(pause.canvasStrokes || 0) === 0,
    resumeCollectionContinues: Number(resume.dataFrames || 0) > 0
      && Number(resume.workerAcceptedFrames || 0) > 0
      && Number(resume.backendProducedItems || 0) > 0,
    resumeRenderingAdvances: Number(resume.canvasFrames || 0) > 0,
    processTreePeakWorkingSetRecorded: Number(metrics.processTreePeakWorkingSetBytes || 0) > 0,
    fixtureValidated: metrics.fixture?.validated === true,
    noFrontendSequenceErrors: Number(metrics.sequenceErrors || 0) === 0,
    noFrontendTransportDrops: Number(telemetry.transportDroppedBatches || 0) === 0,
    noFrontendBackendDrops: Number(telemetry.backendDroppedBatches || 0) === 0
      && Number(telemetry.backendDroppedItems || 0) === 0
      && Number(telemetry.backendDroppedBytes || 0) === 0,
    noBackendDrops: Number(backendDrops.batches || 0) === 0
      && Number(backendDrops.items || 0) === 0
      && Number(backendDrops.bytes || 0) === 0,
    noParserDrops: Number(parserDrops.bytes || 0) === 0
      && Number(parserDrops.packets || 0) === 0,
    noTargetDrops: Number(targetDrops.packets || 0) === 0
      && Number(targetDrops.overflowEvents || 0) === 0,
    validSystemViewTaskNames: taskNameEvidence.valid,
    cleanupStopped: cleanup.running === false,
    cleanupActiveClientsZero: cleanup.activeClients === 0,
    cleanupResourceStatusAvailable: cleanup.resourceStatusAvailable === true,
    cleanupResourceOwnerReleased: cleanup.resourceOwnerPresent === false,
    targetDearmed: cleanup.targetDearmed === true,
    browserClosed: cleanup.browserClosed === true,
    noConsoleErrors: (metrics.consoleErrors || []).length === 0,
  }
  return { checks, pass: Object.values(checks).every(Boolean), renderFps }
}

async function main() {
  const playwrightPath = process.env.PLAYWRIGHT_CORE_PATH
  if (!playwrightPath || !fs.existsSync(playwrightPath)) throw new Error('PLAYWRIGHT_CORE_PATH is required')
  const { chromium } = require(playwrightPath)
  const cdpUrl = process.env.TAURI_CDP_URL || 'http://127.0.0.1:9223'
  const baseUrl = process.env.MKLINK_GUI_URL || 'http://127.0.0.1:8765'
  const streamName = String(process.env.MKLINK_STREAM || 'rtt').toLowerCase()
  const profile = streamProfile(streamName)
  const durationMs = Number(process.env.MKLINK_PACKAGED_DURATION_MS || 600_000)
  const prepareRequests = JSON.parse(process.env.MKLINK_STREAM_PREPARE_REQUESTS || '[]')
  const startBodyText = process.env.MKLINK_STREAM_START_BODY
  const targetWrites = JSON.parse(process.env.MKLINK_TARGET_ARM_WRITES || '[]')
  const targetDearmWrites = JSON.parse(process.env.MKLINK_TARGET_DEARM_WRITES || '[]')
  const fixture = JSON.parse(process.env.MKLINK_STREAM_FIXTURE || 'null')
  const tauriPid = Number(process.env.MKLINK_TAURI_PID || 0)
  let processTreePeakWorkingSetBytes = 0
  const sampleWorkingSet = () => {
    const value = processTreeWorkingSet(tauriPid)
    if (Number.isFinite(value)) processTreePeakWorkingSetBytes = Math.max(processTreePeakWorkingSetBytes, value)
  }
  let memoryTimer = null
  let browserClosed = false
  const session = await runBrowserLifecycle(
    () => chromium.connectOverCDP(cdpUrl),
    async browser => {
  const context = browser.contexts()[0]
  const page = context?.pages()[0]
  if (!page) throw new Error('no Tauri WebView page exposed by CDP')
  page.setDefaultTimeout(30_000)
  acceptPageDialogs(page)
  await page.addInitScript(canvasSelector => {
    const gate = window.__mklinkPackagedGate = {
      workerUrls: [], websocketUrls: [], wireFrames: 0, dataFrames: 0, dataItems: 0, dataBytes: 0,
      lastDataSequence: null, sequenceErrors: 0, workerMessages: 0, lastTelemetry: null,
      canvasClearCalls: 0, canvasStrokeCalls: 0,
    }
    const safeCopy = value => Object.fromEntries(Object.entries(value || {}).map(([key, item]) => [
      key, typeof item === 'bigint' ? item.toString() : item,
    ]))
    const NativeWorker = window.Worker
    window.Worker = class PackagedGateWorker extends NativeWorker {
      constructor(url, options) {
        super(url, options)
        gate.workerUrls.push(String(url))
        this.addEventListener('message', event => {
          gate.workerMessages += 1
          if (event.data?.type === 'telemetry') gate.lastTelemetry = safeCopy(event.data)
        })
      }
    }
    const NativeWebSocket = window.WebSocket
    window.WebSocket = class PackagedGateWebSocket extends NativeWebSocket {
      constructor(url, protocols) {
        super(url, protocols)
        gate.websocketUrls.push(String(url))
        this.addEventListener('message', event => {
          if (!(event.data instanceof ArrayBuffer) || event.data.byteLength < 36) return
          const bytes = new Uint8Array(event.data)
          if (bytes[0] !== 0x4d || bytes[1] !== 0x4b || bytes[2] !== 0x53 || bytes[3] !== 0x54) return
          const view = new DataView(event.data)
          gate.wireFrames += 1
          if (view.getUint8(5) === 255) return
          const sequence = view.getBigUint64(12, true)
          if (gate.lastDataSequence !== null && sequence !== BigInt(gate.lastDataSequence) + 1n) gate.sequenceErrors += 1
          gate.dataFrames += 1
          gate.dataItems += view.getUint32(28, true)
          gate.dataBytes += event.data.byteLength
          gate.lastDataSequence = sequence.toString()
        })
      }
    }
    const clearRect = CanvasRenderingContext2D.prototype.clearRect
    CanvasRenderingContext2D.prototype.clearRect = function (...args) {
      if (this.canvas?.matches?.(canvasSelector)) gate.canvasClearCalls += 1
      return clearRect.apply(this, args)
    }
    const stroke = CanvasRenderingContext2D.prototype.stroke
    CanvasRenderingContext2D.prototype.stroke = function (...args) {
      if (this.canvas?.matches?.(canvasSelector)) gate.canvasStrokeCalls += 1
      return stroke.apply(this, args)
    }
  }, profile.canvas)

  const consoleErrors = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('pageerror', error => consoleErrors.push(String(error)))
  sampleWorkingSet()
  memoryTimer = setInterval(sampleWorkingSet, 5_000)
  let streamRoot = null
  const lifecycle = await runWithCleanup(async () => {
    for (const request of prepareRequests) {
      const method = String(request.method || 'POST').toUpperCase()
      const options = { method }
      if (request.body !== undefined) {
        options.headers = { 'content-type': 'application/json' }
        options.body = JSON.stringify(request.body)
      }
      await apiJson(baseUrl, request.path, options)
    }
    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForFrontendDeviceConnection(page)
    const dashboardTab = page.locator('.app-nav .nav-tab').nth(1)
    await dashboardTab.click()
    await page.waitForFunction(() => window.location.hash.startsWith('#/dashboard'))
    await selectDashboardStreamTab(page, profile.tab)
    streamRoot = page.locator(profile.root)
    await waitForStreamStartControl(streamRoot, profile.start)
    await waitForStreamUiReady(page, streamRoot, profile)
    await applyMemoryWrites(baseUrl, targetWrites)
    const targetArmed = await verifyTargetArmWrites(
      targetWrites, () => verifyMemoryWrites(baseUrl, targetWrites),
    )
    if (!targetArmed) throw new Error('target fixture writes did not verify')
    await startPackagedStream(
      body => apiJson(baseUrl, `/api/dash/${profile.apiName}/start`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      }),
      () => streamRoot.locator(profile.start).click(),
      startBodyText,
    )
    await waitForWarmStream(page)
    await waitForStableLossCounters(page, baseUrl, profile)
    const startedAt = Date.now()
    const startSnapshot = await streamSnapshot(page, baseUrl, profile)
    const pauseDurationMs = 5_000
    const resumeDurationMs = 5_000
    await page.waitForTimeout(Math.max(0, durationMs - pauseDurationMs - resumeDurationMs))
    await streamRoot.locator(profile.pause).click()
    await page.waitForTimeout(250)
    const pauseStart = await streamSnapshot(page, baseUrl, profile)
    await page.waitForTimeout(pauseDurationMs)
    const pauseEnd = await streamSnapshot(page, baseUrl, profile)
    await streamRoot.locator(profile.resume).click()
    await page.waitForTimeout(250)
    const resumeStart = await streamSnapshot(page, baseUrl, profile)
    await page.waitForTimeout(resumeDurationMs)
    const resumeEnd = await streamSnapshot(page, baseUrl, profile)
    const endedAt = Date.now()
    const startGate = startSnapshot.gate
    const startStatus = startSnapshot.status
    const endGate = resumeEnd.gate
    const endStatus = resumeEnd.status
    return {
      streamName,
      requiredDurationSeconds: durationMs / 1_000,
      elapsedSeconds: (endedAt - startedAt) / 1_000,
      workerAssetUrls: endGate.workerUrls,
      websocketUrls: endGate.websocketUrls,
      dataFrames: endGate.dataFrames - startGate.dataFrames,
      wireFrames: endGate.wireFrames - startGate.wireFrames,
      dataItems: endGate.dataItems - startGate.dataItems,
      dataBytes: endGate.dataBytes - startGate.dataBytes,
      lastDataSequence: endGate.lastDataSequence,
      sequenceErrors: endGate.sequenceErrors,
      workerAcceptedFrames: Number(endGate.lastTelemetry?.acceptedFrames || 0) - Number(startGate.lastTelemetry?.acceptedFrames || 0),
      workerBufferedSamples: Number(endGate.lastTelemetry?.bufferedSamples || 0),
      workerLastSequence: endGate.lastTelemetry?.lastSequence || null,
      workerTelemetry: endGate.lastTelemetry || {},
      canvasFrames: endGate.canvasClearCalls - startGate.canvasClearCalls,
      canvasStrokes: endGate.canvasStrokeCalls - startGate.canvasStrokeCalls,
      backendDrops: {
        batches: Number(endStatus.stream?.dropped_batches || 0) - Number(startStatus.stream?.dropped_batches || 0),
        items: Number(endStatus.stream?.dropped_items || 0) - Number(startStatus.stream?.dropped_items || 0),
        bytes: Number(endStatus.stream?.dropped_bytes || 0) - Number(startStatus.stream?.dropped_bytes || 0),
      },
      parserDrops: {
        bytes: Number(endStatus.parser_dropped_bytes || 0) - Number(startStatus.parser_dropped_bytes || 0),
        packets: Number(endStatus.parser_dropped_packets || 0) - Number(startStatus.parser_dropped_packets || 0),
      },
      targetDrops: {
        packets: Number(endStatus.target_dropped_packets_since_baseline || 0)
          - Number(startStatus.target_dropped_packets_since_baseline || 0),
        overflowEvents: Number(endStatus.target_overflow_events || 0)
          - Number(startStatus.target_overflow_events || 0),
      },
      targetBaseline: {
        parserDroppedBytes: Number(startStatus.parser_dropped_bytes || 0),
        parserDroppedPackets: Number(startStatus.parser_dropped_packets || 0),
        droppedPacketsSinceBaseline: Number(startStatus.target_dropped_packets_since_baseline || 0),
        overflowEvents: Number(startStatus.target_overflow_events || 0),
      },
      taskNames: endStatus.task_names || {},
      fixture: buildFixtureEvidence({
        streamName, fixture, targetWrites, targetArmed, prepareRequests, startBodyText, endStatus,
      }),
      pause: streamDelta(pauseEnd, pauseStart),
      resume: streamDelta(resumeEnd, resumeStart),
      consoleErrors,
    }
  }, () => cleanupPackagedGate(baseUrl, page, streamRoot, profile, targetDearmWrites))
  return { lifecycle, consoleErrors }
    },
    () => {
      if (memoryTimer) clearInterval(memoryTimer)
      sampleWorkingSet()
    },
    () => { browserClosed = true },
  )
  const { lifecycle, consoleErrors } = session
  const measured = lifecycle.value
  const primaryError = lifecycle.primaryError
  const cleanupError = lifecycle.cleanupError
  const cleanup = lifecycle.cleanup || {
    running: null,
    activeClients: null,
    resourceStatusAvailable: false,
    resourceOwnerPresent: null,
    targetDearmed: false,
    browserClosed,
  }
  cleanup.browserClosed = browserClosed
  let result
  if (measured) {
    measured.processTreePeakWorkingSetBytes = processTreePeakWorkingSetBytes
    measured.cleanup = cleanup
    const evaluation = evaluatePackagedGate(measured)
    const taskNameEvidence = systemViewTaskNameEvidence(streamName, measured.taskNames)
    result = {
      schemaVersion: 1,
      gate: `packaged_tauri_${streamName}_hil`,
      result: evaluation.pass ? 'pass' : 'fail',
      elapsedSeconds: measured.elapsedSeconds,
      checks: evaluation.checks,
      transport: {
        wireFrames: measured.wireFrames,
        dataFrames: measured.dataFrames, dataItems: measured.dataItems, dataBytes: measured.dataBytes,
        lastDataSequence: measured.lastDataSequence, frontendSequenceErrors: measured.sequenceErrors,
        workerAcceptedFrames: measured.workerAcceptedFrames,
        workerBufferedSamples: measured.workerBufferedSamples, workerLastSequence: measured.workerLastSequence,
        frontendTransportDroppedBatches: Number(measured.workerTelemetry.transportDroppedBatches || 0),
        frontendBackendDroppedBatches: Number(measured.workerTelemetry.backendDroppedBatches || 0),
        frontendBackendDroppedItems: Number(measured.workerTelemetry.backendDroppedItems || 0),
        frontendBackendDroppedBytes: Number(measured.workerTelemetry.backendDroppedBytes || 0),
        backendDroppedBatches: measured.backendDrops.batches,
        backendDroppedItems: measured.backendDrops.items,
        backendDroppedBytes: measured.backendDrops.bytes,
        parserDroppedBytes: measured.parserDrops.bytes,
        parserDroppedPackets: measured.parserDrops.packets,
        targetDroppedPackets: measured.targetDrops.packets,
        targetOverflowEvents: measured.targetDrops.overflowEvents,
      },
      rendering: {
        canvasFrames: measured.canvasFrames,
        canvasStrokes: measured.canvasStrokes,
        renderFps: evaluation.renderFps,
      },
      pause: measured.pause,
      resume: measured.resume,
      performance: {
        processTreePeakWorkingSetBytes: measured.processTreePeakWorkingSetBytes,
        itemRatePerSecond: measured.dataItems / measured.elapsedSeconds,
        byteRatePerSecond: measured.dataBytes / measured.elapsedSeconds,
      },
      integrityBaseline: measured.targetBaseline,
      systemViewTaskNames: taskNameEvidence.required ? {
        taskNameCount: taskNameEvidence.taskNameCount,
        invalidTaskNameCount: taskNameEvidence.invalidTaskNameCount,
      } : undefined,
      fixture: measured.fixture,
      cleanup,
      assets: {
        workerAssetPaths: measured.workerAssetUrls.map(url => new URL(url).pathname),
        websocketPaths: measured.websocketUrls.map(url => new URL(url).pathname),
      },
      consoleErrors,
    }
    if (cleanupError) result.cleanupError = String(cleanupError)
  } else {
    result = {
      schemaVersion: 1, gate: `packaged_tauri_${streamName}_hil`, result: 'error',
      error: String(primaryError || cleanupError || 'measurement unavailable'), cleanup, consoleErrors,
    }
    if (cleanupError) result.cleanupError = String(cleanupError)
  }
  console.log(JSON.stringify(result, null, 2))
  process.exitCode = result.result === 'pass' ? 0 : 1
}

if (require.main === module) {
  main().catch(error => {
    console.error(JSON.stringify({ schemaVersion: 1, gate: 'packaged_tauri_stream_hil', result: 'error', error: String(error) }, null, 2))
    process.exitCode = 1
  })
}

module.exports = {
  acceptPageDialogs,
  buildFixtureEvidence,
  cleanupAndDisconnect,
  evaluatePackagedGate,
  leaveDashboard,
  memoryWriteBody,
  processTreeWorkingSet,
  runBrowserLifecycle,
  runWithCleanup,
  selectDashboardStreamTab,
  startPackagedStream,
  streamDelta,
  streamProfile,
  streamRunningState,
  waitForFrontendDeviceConnection,
  waitForWarmStream,
  waitForStreamUiReady,
  waitForStreamStartControl,
  verifyTargetArmWrites,
}
