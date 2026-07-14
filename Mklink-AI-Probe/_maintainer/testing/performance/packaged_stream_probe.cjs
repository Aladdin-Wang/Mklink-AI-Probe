/* Five-minute physical stream smoke for an already-running packaged Tauri WebView. */
'use strict'

const fs = require('node:fs')

const STREAM_PROFILES = Object.freeze({
  rtt: Object.freeze({
    tab: 'RTT View', websocketName: 'rtt', apiName: 'rtt',
    owner: 'user:dashboard:rtt', root: '.rtt-view-tab:visible',
    start: '.control-toolbar .btn-primary', stop: '.control-toolbar .btn-danger',
  }),
  systemview: Object.freeze({
    tab: 'RTOS Trace', websocketName: 'systemview', apiName: 'systemview',
    owner: 'user:dashboard:systemview', root: '.sv-tab:visible',
    start: '.control-toolbar .btn-primary', stop: '.control-toolbar .btn-danger',
  }),
  vofa: Object.freeze({
    tab: 'VOFA+', websocketName: 'vofa', apiName: 'vofa',
    owner: 'user:dashboard:vofa', root: '.waveform-viewer:visible',
    start: '#btn-start', stop: '#btn-stop',
  }),
  superwatch: Object.freeze({
    tab: 'SuperWatch', websocketName: 'superwatch', apiName: 'superwatch',
    owner: 'user:dashboard:superwatch', root: '.waveform-viewer:visible',
    start: '#btn-start', stop: '#btn-stop',
  }),
})

function streamProfile(name) {
  const profile = STREAM_PROFILES[name]
  if (!profile) throw new Error(`unsupported packaged stream: ${name}`)
  return profile
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

async function applyMemoryWrites(baseUrl, writes) {
  for (const write of writes) {
    await apiJson(baseUrl, '/api/device/write-memory', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(write),
    })
  }
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

async function cleanupPackagedGate(baseUrl, streamRoot, profile, targetDearmWrites) {
  try { await streamRoot?.locator(profile.stop).click({ timeout: 5_000 }) } catch { /* REST fallback below */ }
  try { await apiJson(baseUrl, `/api/dash/${profile.apiName}/stop`, { method: 'POST' }) } catch { /* status check reports failure */ }
  let targetDearmed = false
  try {
    await applyMemoryWrites(baseUrl, targetDearmWrites)
    targetDearmed = await verifyMemoryWrites(baseUrl, targetDearmWrites)
  } catch { /* reported by targetDearmed=false */ }

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
    if (status.running === false
      && Number(status.stream?.active_clients || 0) === 0
      && resourceStatusAvailable
      && ownerPresent === false) break
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  return {
    running: status.running,
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

function evaluatePackagedGate(metrics) {
  const telemetry = metrics.workerTelemetry || {}
  const backendDrops = metrics.backendDrops || {}
  const cleanup = metrics.cleanup || {}
  const workerAssetUrls = metrics.workerAssetUrls || []
  const websocketUrls = metrics.websocketUrls || []
  const renderFps = metrics.elapsedSeconds > 0 ? metrics.canvasFrames / metrics.elapsedSeconds : 0
  const checks = {
    requiredWallClockDuration: metrics.elapsedSeconds >= metrics.requiredDurationSeconds,
    tauriAssetOrigin: workerAssetUrls.some(url => url.startsWith('http://tauri.localhost/')),
    hashedWorker: workerAssetUrls.some(url => /streamDecoder\.worker-[\w-]+\.js/.test(url)),
    binaryWebSocket: websocketUrls.some(url => url.includes(`/ws/streams/${metrics.streamName}`)),
    dataFrames: metrics.dataFrames > 0 && metrics.dataItems > 0,
    workerDecodedData: metrics.workerAcceptedFrames > 0 && metrics.workerBufferedSamples > 0,
    workerFrameParity: Number(metrics.workerAcceptedFrames) === Number(metrics.dataFrames),
    workerSequenceParity: metrics.lastDataSequence != null
      && metrics.workerLastSequence != null
      && String(metrics.workerLastSequence) === String(metrics.lastDataSequence),
    canvasDrawn: metrics.canvasFrames > 0,
    renderFpsCapped: renderFps > 0 && renderFps <= 30.5,
    noFrontendSequenceErrors: Number(metrics.sequenceErrors || 0) === 0,
    noFrontendTransportDrops: Number(telemetry.transportDroppedBatches || 0) === 0,
    noFrontendBackendDrops: Number(telemetry.backendDroppedBatches || 0) === 0
      && Number(telemetry.backendDroppedItems || 0) === 0
      && Number(telemetry.backendDroppedBytes || 0) === 0,
    noBackendDrops: Number(backendDrops.batches || 0) === 0
      && Number(backendDrops.items || 0) === 0
      && Number(backendDrops.bytes || 0) === 0,
    cleanupStopped: cleanup.running === false,
    cleanupActiveClientsZero: cleanup.activeClients === 0,
    cleanupResourceStatusAvailable: cleanup.resourceStatusAvailable === true,
    cleanupResourceOwnerReleased: cleanup.resourceOwnerPresent === false,
    targetDearmed: cleanup.targetDearmed === true,
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
  const browser = await chromium.connectOverCDP(cdpUrl)
  const context = browser.contexts()[0]
  const page = context?.pages()[0]
  if (!page) throw new Error('no Tauri WebView page exposed by CDP')
  page.setDefaultTimeout(30_000)
  await page.addInitScript(() => {
    const gate = window.__mklinkPackagedGate = {
      workerUrls: [], websocketUrls: [], dataFrames: 0, dataItems: 0, dataBytes: 0,
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
      gate.canvasClearCalls += 1
      return clearRect.apply(this, args)
    }
    const stroke = CanvasRenderingContext2D.prototype.stroke
    CanvasRenderingContext2D.prototype.stroke = function (...args) {
      gate.canvasStrokeCalls += 1
      return stroke.apply(this, args)
    }
  })

  const consoleErrors = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('pageerror', error => consoleErrors.push(String(error)))
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
    const dashboardTab = page.locator('.app-nav .nav-tab').nth(1)
    await dashboardTab.click()
    await page.waitForFunction(() => window.location.hash.startsWith('#/dashboard'))
    await page.evaluate(name => { window.location.hash = `#/dashboard?tab=${name}` }, streamName)
    await page.waitForFunction(name => window.location.hash.includes(`tab=${name}`), streamName)
    streamRoot = page.locator(profile.root)
    await streamRoot.locator(profile.start).waitFor({ state: 'visible' })
    await applyMemoryWrites(baseUrl, targetWrites)
    if (startBodyText !== undefined) {
      await apiJson(baseUrl, `/api/dash/${profile.apiName}/start`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(JSON.parse(startBodyText)),
      })
    } else {
      await streamRoot.locator(profile.start).click()
    }
    await page.waitForFunction(() => {
      const gate = window.__mklinkPackagedGate
      return gate?.dataFrames > 5
        && Number(gate.lastTelemetry?.acceptedFrames || 0) > 5
        && Number(gate.lastTelemetry?.bufferedSamples || 0) > 0
        && gate.canvasClearCalls > 0 && gate.canvasStrokeCalls > 0
    }, null, { timeout: 60_000 })
    const startedAt = Date.now()
    const startGate = await page.evaluate(() => ({ ...window.__mklinkPackagedGate }))
    const startStatus = await apiJson(baseUrl, `/api/dash/${profile.apiName}/status`)
    await page.waitForTimeout(durationMs)
    const endedAt = Date.now()
    const endGate = await page.evaluate(() => ({ ...window.__mklinkPackagedGate }))
    const endStatus = await apiJson(baseUrl, `/api/dash/${profile.apiName}/status`)
    return {
      streamName,
      requiredDurationSeconds: durationMs / 1_000,
      elapsedSeconds: (endedAt - startedAt) / 1_000,
      workerAssetUrls: endGate.workerUrls,
      websocketUrls: endGate.websocketUrls,
      dataFrames: endGate.dataFrames - startGate.dataFrames,
      dataItems: endGate.dataItems - startGate.dataItems,
      dataBytes: endGate.dataBytes - startGate.dataBytes,
      lastDataSequence: endGate.lastDataSequence,
      sequenceErrors: endGate.sequenceErrors,
      workerAcceptedFrames: Number(endGate.lastTelemetry?.acceptedFrames || 0) - Number(startGate.lastTelemetry?.acceptedFrames || 0),
      workerBufferedSamples: Number(endGate.lastTelemetry?.bufferedSamples || 0),
      workerLastSequence: endGate.lastTelemetry?.lastSequence || null,
      workerTelemetry: endGate.lastTelemetry || {},
      canvasFrames: endGate.canvasClearCalls - startGate.canvasClearCalls,
      backendDrops: {
        batches: Number(endStatus.stream?.dropped_batches || 0) - Number(startStatus.stream?.dropped_batches || 0),
        items: Number(endStatus.stream?.dropped_items || 0) - Number(startStatus.stream?.dropped_items || 0),
        bytes: Number(endStatus.stream?.dropped_bytes || 0) - Number(startStatus.stream?.dropped_bytes || 0),
      },
      consoleErrors,
    }
  }, () => cleanupAndDisconnect(
    () => cleanupPackagedGate(baseUrl, streamRoot, profile, targetDearmWrites),
    browser,
  ))
  const measured = lifecycle.value
  const primaryError = lifecycle.primaryError
  const cleanupError = lifecycle.cleanupError
  const cleanup = lifecycle.cleanup || {
    running: null,
    activeClients: null,
    resourceStatusAvailable: false,
    resourceOwnerPresent: null,
    targetDearmed: false,
  }
  let result
  if (measured) {
    measured.cleanup = cleanup
    const evaluation = evaluatePackagedGate(measured)
    result = {
      schemaVersion: 1,
      gate: `packaged_tauri_${streamName}_hil`,
      result: evaluation.pass ? 'pass' : 'fail',
      elapsedSeconds: measured.elapsedSeconds,
      checks: evaluation.checks,
      transport: {
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
      },
      rendering: { canvasFrames: measured.canvasFrames, renderFps: evaluation.renderFps },
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

module.exports = { cleanupAndDisconnect, evaluatePackagedGate, runWithCleanup, streamProfile }
