/* Real-browser diagnostic for the MKLink binary stream data plane. */
'use strict'

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

function decodeStreamHeader(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 36) return null
  const bytes = new Uint8Array(buffer)
  if (bytes[0] !== 0x4d || bytes[1] !== 0x4b || bytes[2] !== 0x53 || bytes[3] !== 0x54) return null
  const view = new DataView(buffer)
  const streamType = view.getUint8(5)
  return {
    streamType,
    sequence: view.getBigUint64(12, true),
    itemCount: view.getUint32(28, true),
    isControl: streamType === 255,
  }
}

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

function delta(after, before) {
  const result = {}
  for (const key of ['dataFrames', 'dataItems', 'dataBytes', 'workerMessages', 'canvasClearCalls', 'canvasStrokeCalls']) {
    result[key] = Number(after.gate[key] || 0) - Number(before.gate[key] || 0)
  }
  result.backendProducedItems = Number(after.status?.stream?.produced_items || 0) - Number(before.status?.stream?.produced_items || 0)
  result.backendDroppedBatches = Number(after.status?.stream?.dropped_batches || 0) - Number(before.status?.stream?.dropped_batches || 0)
  result.backendDroppedItems = Number(after.status?.stream?.dropped_items || 0) - Number(before.status?.stream?.dropped_items || 0)
  result.backendDroppedBytes = Number(after.status?.stream?.dropped_bytes || 0) - Number(before.status?.stream?.dropped_bytes || 0)
  result.workerAcceptedFrames = Number(after.gate.lastTelemetry?.acceptedFrames || 0) - Number(before.gate.lastTelemetry?.acceptedFrames || 0)
  result.retainedLines = Number(after.retainedLines || 0) - Number(before.retainedLines || 0)
  return result
}

function evaluateTransportIntegrity(gate, beforeStream = {}, afterStream = {}) {
  const telemetry = gate?.lastTelemetry || {}
  const result = {
    frontendSequenceErrors: Number(gate?.sequenceErrors || 0),
    frontendTransportDroppedBatches: Number(telemetry.transportDroppedBatches || 0),
    frontendBackendDroppedBatches: Number(telemetry.backendDroppedBatches || 0),
    frontendBackendDroppedItems: Number(telemetry.backendDroppedItems || 0),
    frontendBackendDroppedBytes: Number(telemetry.backendDroppedBytes || 0),
    backendDroppedBatches: Number(afterStream?.dropped_batches || 0) - Number(beforeStream?.dropped_batches || 0),
    backendDroppedItems: Number(afterStream?.dropped_items || 0) - Number(beforeStream?.dropped_items || 0),
    backendDroppedBytes: Number(afterStream?.dropped_bytes || 0) - Number(beforeStream?.dropped_bytes || 0),
  }
  result.noNewDrops = Object.values(result).every(value => value === 0)
  return result
}

function evaluateCleanup(cleanup) {
  const checks = {
    backendStopped: cleanup?.running === false,
    activeClientsZero: Number(cleanup?.activeClients) === 0,
    resourceOwnerReleased: cleanup?.resourceOwnerPresent === false,
    targetDearmed: cleanup?.targetDearmed === true,
  }
  return { checks, pass: Object.values(checks).every(Boolean) }
}

async function requestJson(request, baseUrl, method, endpoint, data) {
  const response = await request.fetch(`${baseUrl}${endpoint}`, { method, data })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok()) throw new Error(`${method} ${endpoint}: HTTP ${response.status()}`)
  return payload
}

async function cleanupBrowserGate(page, toolbar, baseUrl, targetDearmWrites) {
  try { await toolbar?.locator('.btn-danger').click({ timeout: 5_000 }) } catch { /* REST fallback below */ }
  try { await requestJson(page.request, baseUrl, 'POST', '/api/dash/rtt/stop') } catch { /* final status reports failure */ }

  let targetDearmed = false
  try {
    for (const write of targetDearmWrites) {
      await requestJson(page.request, baseUrl, 'POST', '/api/device/write-memory', write)
    }
    targetDearmed = targetDearmWrites.length > 0
    for (const write of targetDearmWrites) {
      const expected = String(write.data_hex || '').toLowerCase()
      const readback = await requestJson(page.request, baseUrl, 'POST', '/api/device/read-memory', {
        address: write.address, size: expected.length / 2,
      })
      if (!expected || expected.length % 2 !== 0 || String(readback.data_hex || '').toLowerCase() !== expected) {
        targetDearmed = false
      }
    }
  } catch { targetDearmed = false }

  try { await page.goto('about:blank', { waitUntil: 'domcontentloaded' }) } catch { /* context close follows */ }
  let status = {}
  let resources = {}
  for (let attempt = 0; attempt < 10; attempt++) {
    try { status = await requestJson(page.request, baseUrl, 'GET', '/api/dash/rtt/status') } catch { status = {} }
    try { resources = await requestJson(page.request, baseUrl, 'GET', '/api/resources/status') } catch { resources = {} }
    const ownerPresent = Object.values(resources).some(item => item?.owner === 'user:dashboard:rtt')
    if (status.running === false && Number(status.stream?.active_clients || 0) === 0 && !ownerPresent) break
    await page.waitForTimeout(250)
  }
  return {
    running: status.running,
    activeClients: Number(status.stream?.active_clients || 0),
    resourceOwnerPresent: Object.values(resources).some(item => item?.owner === 'user:dashboard:rtt'),
    targetDearmed,
  }
}

async function main() {
  const playwrightPath = process.env.PLAYWRIGHT_CORE_PATH
  if (!playwrightPath) throw new Error('PLAYWRIGHT_CORE_PATH is required')
  const { chromium } = require(playwrightPath)
  const browserExecutable = process.env.BROWSER_EXECUTABLE
  if (!browserExecutable || !fs.existsSync(browserExecutable)) {
    throw new Error('BROWSER_EXECUTABLE must point to an installed Chromium browser')
  }
  const baseUrl = process.env.MKLINK_GUI_URL || 'http://127.0.0.1:8765'
  const targetWrites = JSON.parse(process.env.MKLINK_TARGET_ARM_WRITES || '[]')
  const targetDearmWrites = JSON.parse(process.env.MKLINK_TARGET_DEARM_WRITES || '[]')
  const profileMarker = `mklink-browser-gate-${process.pid}-${Date.now()}`
  const profileDir = path.join(os.tmpdir(), profileMarker)
  const context = await chromium.launchPersistentContext(profileDir, {
    executablePath: browserExecutable,
    headless: process.env.BROWSER_HEADLESS !== '0',
    viewport: { width: 1600, height: 1000 },
    ignoreDefaultArgs: [
      '--disable-background-timer-throttling',
      '--disable-backgrounding-occluded-windows',
      '--disable-renderer-backgrounding',
    ],
    args: ['--disable-gpu-sandbox'],
  })
  const page = context.pages()[0] || await context.newPage()
  page.setDefaultTimeout(30_000)
  await page.addInitScript(() => {
    const gate = window.__mklinkGate = {
      workerUrls: [], websocketUrls: [], binaryMessages: 0, binaryBytes: 0,
      dataFrames: 0, dataItems: 0, dataBytes: 0, lastDataSequence: null,
      sequenceErrors: 0,
      workerMessages: 0, telemetryMessages: 0, lastTelemetry: null,
      canvasClearCalls: 0, canvasStrokeCalls: 0,
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
        gate.websocketUrls.push(String(url))
        this.addEventListener('message', event => {
          if (!(event.data instanceof ArrayBuffer)) return
          gate.binaryMessages += 1
          gate.binaryBytes += event.data.byteLength
          if (event.data.byteLength < 36) return
          const bytes = new Uint8Array(event.data)
          if (bytes[0] !== 0x4d || bytes[1] !== 0x4b || bytes[2] !== 0x53 || bytes[3] !== 0x54) return
          const view = new DataView(event.data)
          if (view.getUint8(5) === 255) return
          gate.dataFrames += 1
          gate.dataItems += view.getUint32(28, true)
          gate.dataBytes += event.data.byteLength
          const sequence = view.getBigUint64(12, true)
          if (gate.lastDataSequence !== null && sequence !== BigInt(gate.lastDataSequence) + 1n) gate.sequenceErrors += 1
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
  let peakBrowserWorkingSetBytes = 0
  const memoryTimer = setInterval(() => {
    const value = processWorkingSet(profileMarker)
    if (Number.isFinite(value)) peakBrowserWorkingSetBytes = Math.max(peakBrowserWorkingSetBytes, value)
  }, 1_000)

  const snapshot = async label => {
    let statusResponse
    let lastStatusError
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        statusResponse = await page.request.get(`${baseUrl}/api/dash/rtt/status`)
        break
      } catch (error) {
        lastStatusError = error
        await page.waitForTimeout(250 * (attempt + 1))
      }
    }
    if (!statusResponse) throw lastStatusError
    const status = statusResponse.ok() ? await statusResponse.json() : { http_status: statusResponse.status() }
    const browserState = await page.evaluate(() => ({
      gate: { ...window.__mklinkGate },
      visibility: document.visibilityState,
      hidden: document.hidden,
      health: document.querySelector('.stream-health')?.textContent?.trim() || '',
      retainedLines: Number((document.querySelector('.line-count')?.textContent || '').match(/\d+/)?.[0] || 0),
      toolbar: Array.from(document.querySelectorAll('.control-toolbar button')).map(button => button.textContent?.trim()),
      canvasCount: document.querySelectorAll('canvas').length,
    }))
    return { label, timestampMs: Date.now(), status, ...browserState }
  }

  let result
  let exitCode = 0
  let toolbar = null
  try {
    await page.goto(`${baseUrl}/#/dashboard?tab=rtt`, { waitUntil: 'domcontentloaded' })
    toolbar = page.locator('.rtt-view-tab:visible .control-toolbar')
    await toolbar.locator('button').first().waitFor({ state: 'visible' })
    for (const write of targetWrites) {
      const response = await page.request.post(`${baseUrl}/api/device/write-memory`, { data: write })
      if (!response.ok()) throw new Error(`target arm write failed: HTTP ${response.status()}`)
    }
    const start = toolbar.locator('.btn-primary')
    await start.click()
    await page.waitForFunction(() => window.__mklinkGate.workerUrls.length > 0 && window.__mklinkGate.websocketUrls.length > 0)
    await page.waitForFunction(() => {
      const gate = window.__mklinkGate
      return gate.dataFrames > 5
        && Number(gate.lastTelemetry?.acceptedFrames || 0) > 5
        && Number(gate.lastTelemetry?.bufferedSamples || 0) > 0
        && gate.canvasClearCalls > 0 && gate.canvasStrokeCalls > 0
    }, null, { timeout: 60_000 })

    const visibleStart = await snapshot('visible_start')
    await page.waitForTimeout(10_000)
    const visibleEnd = await snapshot('visible_end')

    await toolbar.locator('.btn:not(.btn-danger)').click()
    await page.waitForTimeout(1_000)
    const pauseStart = await snapshot('pause_start')
    await page.waitForTimeout(5_000)
    const pauseEnd = await snapshot('pause_end')

    await toolbar.locator('.btn-primary').click()
    await page.waitForTimeout(1_000)
    const resumeStart = await snapshot('resume_start')
    await page.waitForTimeout(5_000)
    const resumeEnd = await snapshot('resume_end')

    const cdp = await context.newCDPSession(page)
    let visibilityMethod = 'unavailable'
    let coverPage = null
    try {
      await cdp.send('Emulation.setPageVisibilityOverride', { visibilityState: 'hidden' })
      visibilityMethod = 'CDP Emulation.setPageVisibilityOverride(hidden)'
    } catch {
      coverPage = await context.newPage()
      await coverPage.goto('about:blank')
      await coverPage.bringToFront()
      visibilityMethod = 'real background tab via Page.bringToFront'
    }
    await page.waitForTimeout(1_000)
    const hiddenStart = await snapshot('hidden_start')
    await page.waitForTimeout(5_000)
    const hiddenEnd = await snapshot('hidden_end')
    if (visibilityMethod.startsWith('CDP')) {
      await cdp.send('Emulation.setPageVisibilityOverride', { visibilityState: 'visible' })
    } else {
      await page.bringToFront()
      await coverPage?.close()
    }
    await page.waitForTimeout(1_000)
    const restoreStart = await snapshot('restore_start')
    await page.waitForTimeout(5_000)
    const restoreEnd = await snapshot('restore_end')

    const visibleDelta = delta(visibleEnd, visibleStart)
    const pauseDelta = delta(pauseEnd, pauseStart)
    const resumeDelta = delta(resumeEnd, resumeStart)
    const hiddenDelta = delta(hiddenEnd, hiddenStart)
    const restoreDelta = delta(restoreEnd, restoreStart)
    const visibleSeconds = (visibleEnd.timestampMs - visibleStart.timestampMs) / 1_000
    const visibleRenderFps = visibleDelta.canvasClearCalls / visibleSeconds
    const restoreSeconds = (restoreEnd.timestampMs - restoreStart.timestampMs) / 1_000
    const restoreRenderFps = restoreDelta.canvasClearCalls / restoreSeconds
    const workerAssetIsHashed = visibleEnd.gate.workerUrls.some(url => /streamDecoder\.worker-[\w-]+\.js/.test(url))
    const transportIntegrity = evaluateTransportIntegrity(
      restoreEnd.gate,
      visibleStart.status?.stream,
      restoreEnd.status?.stream,
    )
    const checks = {
      hashedWorker: workerAssetIsHashed,
      binaryDataFrames: visibleDelta.dataFrames > 0,
      workerDecodedData: visibleDelta.workerAcceptedFrames > 0 && Number(visibleEnd.gate.lastTelemetry?.bufferedSamples || 0) > 0,
      canvasDrawn: visibleDelta.canvasClearCalls > 0 && visibleDelta.canvasStrokeCalls > 0,
      visibleFpsCapped: visibleRenderFps > 0 && visibleRenderFps <= 30.5,
      pauseCollectionContinues: pauseDelta.dataFrames > 0 && pauseDelta.workerAcceptedFrames > 0 && pauseDelta.backendProducedItems > 0,
      pauseRenderingStops: pauseDelta.canvasClearCalls === 0 && pauseDelta.canvasStrokeCalls === 0 && pauseDelta.retainedLines === 0,
      actualHiddenState: hiddenStart.hidden === true && hiddenStart.visibility === 'hidden',
      hiddenCollectionContinues: hiddenDelta.dataFrames > 0 && hiddenDelta.workerAcceptedFrames > 0 && hiddenDelta.backendProducedItems > 0,
      hiddenRenderingStops: hiddenDelta.canvasClearCalls === 0 && hiddenDelta.canvasStrokeCalls === 0,
      restoreWithoutBacklog: restoreDelta.dataFrames > 0 && restoreDelta.workerAcceptedFrames > 0 && restoreRenderFps > 0 && restoreRenderFps <= 30.5,
      noNewDrops: transportIntegrity.noNewDrops,
      noConsoleErrors: consoleErrors.length === 0,
    }
    result = {
      schemaVersion: 1,
      gate: 'edge_rtt_worker_canvas_pause_visibility',
      result: Object.values(checks).every(Boolean) ? 'pass' : 'fail',
      browser: 'Microsoft Edge',
      headless: process.env.BROWSER_HEADLESS !== '0',
      visibilityMethod,
      peakBrowserWorkingSetBytes,
      visibleRenderFps,
      restoreRenderFps,
      checks,
      transportIntegrity,
      deltas: { visible: visibleDelta, pause: pauseDelta, resume: resumeDelta, hidden: hiddenDelta, restore: restoreDelta },
      final: {
        dataFrames: restoreEnd.gate.dataFrames,
        dataItems: restoreEnd.gate.dataItems,
        lastDataSequence: restoreEnd.gate.lastDataSequence,
        frontendSequenceErrors: transportIntegrity.frontendSequenceErrors,
        frontendTransportDroppedBatches: transportIntegrity.frontendTransportDroppedBatches,
        frontendBackendDroppedBatches: transportIntegrity.frontendBackendDroppedBatches,
        frontendBackendDroppedItems: transportIntegrity.frontendBackendDroppedItems,
        frontendBackendDroppedBytes: transportIntegrity.frontendBackendDroppedBytes,
        workerAcceptedFrames: restoreEnd.gate.lastTelemetry?.acceptedFrames || 0,
        workerBufferedSamples: restoreEnd.gate.lastTelemetry?.bufferedSamples || 0,
        workerLastSequence: restoreEnd.gate.lastTelemetry?.lastSequence || null,
        backendStream: restoreEnd.status?.stream || null,
        workerAssetIsHashed,
        canvasCount: restoreEnd.canvasCount,
      },
      consoleErrors,
      limitations: [
        'This gate covers real Edge, WebSocket, Web Worker, Canvas, and physical RTT HIL for a short window; the committed 30-minute backend artifact remains the duration evidence.',
        'Target-arm RAM writes are supplied out-of-band through MKLINK_TARGET_ARM_WRITES and are not committed.',
      ],
    }
    if (result.result !== 'pass') exitCode = 1
  } catch (error) {
    result = { schemaVersion: 1, gate: 'edge_rtt_worker_canvas_pause_visibility', result: 'error', error: String(error), consoleErrors }
    exitCode = 1
  } finally {
    clearInterval(memoryTimer)
    peakBrowserWorkingSetBytes = Math.max(peakBrowserWorkingSetBytes, processWorkingSet(profileMarker) || 0)
    const cleanup = await cleanupBrowserGate(page, toolbar, baseUrl, targetDearmWrites)
    const cleanupEvaluation = evaluateCleanup(cleanup)
    if (result) {
      result.peakBrowserWorkingSetBytes = peakBrowserWorkingSetBytes
      result.cleanup = cleanup
      result.cleanupChecks = cleanupEvaluation.checks
      if (!cleanupEvaluation.pass) {
        result.result = 'fail'
        exitCode = 1
      }
    }
    await context.close()
    fs.rmSync(profileDir, { recursive: true, force: true })
  }
  console.log(JSON.stringify(result, null, 2))
  process.exitCode = exitCode
}

module.exports = { decodeStreamHeader, delta, evaluateCleanup, evaluateTransportIntegrity }

if (require.main === module) {
  main().catch(error => {
    console.error(error)
    process.exitCode = 1
  })
}
