'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const {
  acceptPageDialogs,
  buildFixtureEvidence,
  cleanupAndDisconnect,
  evaluatePackagedGate,
  leaveDashboard,
  memoryWriteBody,
  parserDropCounters,
  runBrowserLifecycle,
  runWithCleanup,
  selectDashboardStreamTab,
  startPackagedStream,
  streamRunningState,
  streamProfile,
  waitForFrontendDeviceConnection,
  waitForWarmStream,
  waitForStreamUiReady,
  waitForStreamStartControl,
  verifyTargetArmWrites,
} = require('./packaged_stream_probe.cjs')

test('parser drop counters support nested SuperWatch stream integrity', () => {
  assert.deepEqual(parserDropCounters({
    parser_dropped_bytes: 99,
    parser_dropped_packets: 88,
    stream_integrity: {
      parser_dropped_bytes: 7,
      parser_dropped_frames: 3,
    },
  }), { bytes: 7, packets: 3 })

  assert.deepEqual(parserDropCounters({
    parser_dropped_bytes: 5,
    parser_dropped_packets: 2,
  }), { bytes: 5, packets: 2 })
})

function cleanMetrics() {
  return {
    streamName: 'rtt',
    requiredDurationSeconds: 300,
    elapsedSeconds: 300,
    workerAssetUrls: ['http://tauri.localhost/assets/streamDecoder.worker-abc.js'],
    websocketUrls: ['ws://127.0.0.1:8765/ws/streams/rtt'],
    dataFrames: 10,
    wireFrames: 10,
    dataItems: 100,
    lastDataSequence: '42',
    workerAcceptedFrames: 10,
    workerBufferedSamples: 100,
    workerLastSequence: '42',
    canvasFrames: 30,
    canvasStrokes: 60,
    sequenceErrors: 0,
    workerTelemetry: {
      transportDroppedBatches: 0,
      backendDroppedBatches: 0,
      backendDroppedItems: 0,
      backendDroppedBytes: 0,
    },
    backendDrops: { batches: 0, items: 0, bytes: 0 },
    parserDrops: { bytes: 0, packets: 0 },
    targetDrops: { packets: 0, overflowEvents: 0 },
    pause: {
      dataFrames: 5,
      workerAcceptedFrames: 5,
      backendProducedItems: 50,
      canvasFrames: 0,
      canvasStrokes: 0,
    },
    resume: {
      dataFrames: 5,
      workerAcceptedFrames: 5,
      backendProducedItems: 50,
      canvasFrames: 5,
    },
    processTreePeakWorkingSetBytes: 128 * 1024 * 1024,
    fixture: { stream: 'rtt', validated: true, controls: [] },
    cleanup: {
      running: false,
      activeClients: 0,
      resourceStatusAvailable: true,
      resourceOwnerPresent: false,
      targetDearmed: true,
      browserClosed: true,
    },
    consoleErrors: [],
  }
}

test('defines packaged profiles for all high-rate streams', () => {
  assert.deepEqual(
    ['rtt', 'systemview', 'vofa', 'superwatch']
      .map(name => streamProfile(name).websocketName),
    ['rtt', 'systemview', 'vofa', 'superwatch'],
  )
})

test('defines one primary render canvas for each packaged stream', () => {
  assert.deepEqual(
    ['rtt', 'systemview', 'vofa', 'superwatch']
      .map(name => streamProfile(name).canvas),
    [
      '.rtt-view-tab canvas.rtt-numeric-chart',
      '.sv-tab .sv-canvas-wrap canvas',
      '.waveform-viewer #chart',
      '.waveform-viewer #chart',
    ],
  )
})

test('rejects unknown packaged stream profiles', () => {
  assert.throws(() => streamProfile('serial'), /unsupported packaged stream/)
})

test('normalizes boolean and state-string backend running contracts', () => {
  assert.equal(streamRunningState({ running: false, state: 'running' }), false)
  assert.equal(streamRunningState({ running: true }), true)
  assert.equal(streamRunningState({ state: 'stopped' }), false)
  assert.equal(streamRunningState({ state: 'running' }), true)
  assert.equal(streamRunningState({ state: 'paused' }), true)
  assert.equal(streamRunningState({}), null)
})

test('requires a ten-second stable-loss warmup only for SystemView', () => {
  assert.equal(streamProfile('systemview').minimumStableWarmupSeconds, 10)
  assert.equal(streamProfile('rtt').minimumStableWarmupSeconds, 0)
  assert.equal(streamProfile('vofa').minimumStableWarmupSeconds, 0)
  assert.equal(streamProfile('superwatch').minimumStableWarmupSeconds, 0)
})

test('uses the requested wall-clock duration', () => {
  const metrics = cleanMetrics()
  metrics.requiredDurationSeconds = 600
  metrics.elapsedSeconds = 599.9
  assert.equal(evaluatePackagedGate(metrics).pass, false)
  metrics.elapsedSeconds = 600
  assert.equal(evaluatePackagedGate(metrics).pass, true)
})

test('module import does not start the packaged HIL run', () => {
  const script = path.resolve(__dirname, 'packaged_stream_probe.cjs')
  const result = spawnSync(process.execPath, ['-e', `require(${JSON.stringify(script)})`], {
    encoding: 'utf8',
  })
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, '')
})

test('the executable path leaves stdout flushing to process exitCode', () => {
  const source = fs.readFileSync(path.resolve(__dirname, 'packaged_stream_probe.cjs'), 'utf8')
  assert.equal(source.includes('process.exit('), false)
  assert.equal(source.includes('process.exitCode ='), true)
})

test('runWithCleanup executes cleanup after a measurement failure', async () => {
  const cleanup = { stopped: true }
  const result = await runWithCleanup(
    async () => { throw new Error('measurement failed') },
    async () => cleanup,
  )

  assert.match(String(result.primaryError), /measurement failed/)
  assert.equal(result.cleanup, cleanup)
  assert.equal(result.cleanupError, null)
})

test('runWithCleanup reports cleanup failure without hiding the measurement', async () => {
  const result = await runWithCleanup(
    async () => ({ measured: true }),
    async () => { throw new Error('cleanup failed') },
  )

  assert.deepEqual(result.value, { measured: true })
  assert.match(String(result.cleanupError), /cleanup failed/)
})

test('cleanupAndDisconnect releases the CDP browser after cleanup succeeds', async () => {
  let closed = false
  const cleanup = { stopped: true }
  const result = await cleanupAndDisconnect(
    async () => cleanup,
    { close: async () => { closed = true } },
  )

  assert.equal(result, cleanup)
  assert.equal(closed, true)
})

test('cleanupAndDisconnect releases the CDP browser after cleanup fails', async () => {
  let closed = false
  await assert.rejects(
    cleanupAndDisconnect(
      async () => { throw new Error('cleanup failed') },
      { close: async () => { closed = true } },
    ),
    /cleanup failed/,
  )
  assert.equal(closed, true)
})

test('browser lifecycle closes CDP and stops sampling after setup failure', async () => {
  let closed = false
  let samplingStopped = false
  const browser = { close: async () => { closed = true } }

  await assert.rejects(
    runBrowserLifecycle(
      async () => browser,
      async () => { throw new Error('no WebView page') },
      () => { samplingStopped = true },
    ),
    /no WebView page/,
  )

  assert.equal(closed, true)
  assert.equal(samplingStopped, true)
})

test('browser lifecycle stops sampling when CDP connection fails', async () => {
  let samplingStopped = false

  await assert.rejects(
    runBrowserLifecycle(
      async () => { throw new Error('CDP unavailable') },
      async () => {},
      () => { samplingStopped = true },
    ),
    /CDP unavailable/,
  )

  assert.equal(samplingStopped, true)
})

test('packaged gate accepts confirmation dialogs used by waveform stop', async () => {
  let eventName = null
  let handler = null
  const page = {
    on(name, callback) {
      eventName = name
      handler = callback
    },
  }
  let accepted = false

  acceptPageDialogs(page)
  await handler({ accept: async () => { accepted = true } })

  assert.equal(eventName, 'dialog')
  assert.equal(accepted, true)
})

test('packaged cleanup leaves the dashboard so stream clients unmount', async () => {
  const calls = []
  const page = {
    evaluate: async callback => {
      const previousWindow = global.window
      global.window = { location: { hash: '#/dashboard' } }
      try { callback() } finally { global.window = previousWindow }
      calls.push(['navigate'])
    },
  }
  const streamRoot = {
    waitFor: async options => { calls.push(['waitFor', options]) },
  }

  await leaveDashboard(page, streamRoot)

  assert.deepEqual(calls, [
    ['navigate'],
    ['waitFor', { state: 'detached', timeout: 10_000 }],
  ])
})

test('packaged gate passes only with complete transport and cleanup evidence', () => {
  const evaluation = evaluatePackagedGate(cleanMetrics())
  assert.equal(evaluation.pass, true)
  assert.equal(Object.values(evaluation.checks).every(Boolean), true)
})

test('packaged gate rejects sequence, transport, backend, or cleanup loss', () => {
  const mutations = [
    metrics => { metrics.workerAcceptedFrames = 9 },
    metrics => { metrics.wireFrames = 9 },
    metrics => { metrics.workerLastSequence = '41' },
    metrics => { metrics.sequenceErrors = 1 },
    metrics => { metrics.workerTelemetry.transportDroppedBatches = 1 },
    metrics => { metrics.workerTelemetry.backendDroppedItems = 1 },
    metrics => { metrics.backendDrops.bytes = 1 },
    metrics => { metrics.parserDrops.bytes = 1 },
    metrics => { metrics.parserDrops.packets = 1 },
    metrics => { metrics.targetDrops.packets = 1 },
    metrics => { metrics.targetDrops.overflowEvents = 1 },
    metrics => { metrics.cleanup.running = true },
    metrics => { metrics.cleanup.activeClients = 1 },
    metrics => { metrics.cleanup.resourceStatusAvailable = false },
    metrics => { metrics.cleanup.resourceOwnerPresent = true },
    metrics => { metrics.cleanup.targetDearmed = false },
  ]
  for (const mutate of mutations) {
    const metrics = cleanMetrics()
    mutate(metrics)
    assert.equal(evaluatePackagedGate(metrics).pass, false)
  }
})

test('packaged gate requires pause, resume, and process-tree memory evidence', () => {
  const mutations = [
    metrics => { metrics.pause.dataFrames = 0 },
    metrics => { metrics.pause.workerAcceptedFrames = 0 },
    metrics => { metrics.pause.backendProducedItems = 0 },
    metrics => { metrics.pause.canvasFrames = 1 },
    metrics => { metrics.pause.canvasStrokes = 1 },
    metrics => { metrics.resume.dataFrames = 0 },
    metrics => { metrics.resume.workerAcceptedFrames = 0 },
    metrics => { metrics.resume.backendProducedItems = 0 },
    metrics => { metrics.resume.canvasFrames = 0 },
    metrics => { metrics.processTreePeakWorkingSetBytes = 0 },
  ]
  for (const mutate of mutations) {
    const metrics = cleanMetrics()
    mutate(metrics)
    assert.equal(evaluatePackagedGate(metrics).pass, false)
  }
})

test('packaged gate requires validated fixture and browser-close evidence', () => {
  const fixtureMissing = cleanMetrics()
  fixtureMissing.fixture.validated = false
  assert.equal(evaluatePackagedGate(fixtureMissing).pass, false)

  const browserOpen = cleanMetrics()
  browserOpen.cleanup.browserClosed = false
  assert.equal(evaluatePackagedGate(browserOpen).pass, false)
})

test('RTT fixture evidence verifies symbolic control writes without raw addresses', () => {
  const evidence = buildFixtureEvidence({
    streamName: 'rtt',
    fixture: {
      stream: 'rtt',
      controls: [
        { symbol: 'mklink_rtt_burst_rows', maskedAddress: '0x2000****', value: 13 },
        { symbol: 'mklink_rtt_test_arm', maskedAddress: '0x2000****', value: 1 },
      ],
    },
    targetWrites: [
      {
        address: '0x20000010', data_hex: '0d000000',
        symbol: 'mklink_rtt_burst_rows', maskedAddress: '0x2000****', value: 13,
      },
      {
        address: '0x20000014', data_hex: '01000000',
        symbol: 'mklink_rtt_test_arm', maskedAddress: '0x2000****', value: 1,
      },
    ],
    targetArmed: true,
    prepareRequests: [],
    startBodyText: undefined,
    endStatus: {},
  })

  assert.equal(evidence.validated, true)
  assert.deepEqual(evidence.controls, [
    { symbol: 'mklink_rtt_burst_rows', maskedAddress: '0x2000****', value: 13 },
    { symbol: 'mklink_rtt_test_arm', maskedAddress: '0x2000****', value: 1 },
  ])
  assert.equal(JSON.stringify(evidence).includes('0x20000010'), false)
})

test('memory write requests exclude fixture evidence metadata', () => {
  assert.deepEqual(memoryWriteBody({
    address: '0x20000010', data_hex: '0d000000',
    symbol: 'mklink_rtt_burst_rows', maskedAddress: '0x2000****', value: 13,
  }), {
    address: '0x20000010', data_hex: '0d000000',
  })
})

test('streams without arm controls satisfy the target-arm boundary', async () => {
  let called = false
  const verified = await verifyTargetArmWrites([], async () => { called = true; return false })

  assert.equal(verified, true)
  assert.equal(called, false)
})

test('VOFA fixture evidence requires the two symbols and 10 us status', () => {
  const base = {
    streamName: 'vofa',
    fixture: {
      stream: 'vofa', channels: ['vofa_test_sin', 'vofa_test_tri'],
      intervalSeconds: 0.00001, acquisitionMode: 'dump-memory',
    },
    targetWrites: [], targetArmed: true, prepareRequests: [],
    startBodyText: JSON.stringify({
      channels: [
        { name: 'vofa_test_sin', addr: '0x20000010', type: 'float', size: 4 },
        { name: 'vofa_test_tri', addr: '0x20000014', type: 'float', size: 4 },
      ],
      interval: 0.00001,
    }),
    endStatus: {
      interval: 0.00001, acquisition_mode: 'dump-memory',
      channels: [{ name: 'vofa_test_sin' }, { name: 'vofa_test_tri' }],
    },
  }

  assert.equal(buildFixtureEvidence(base).validated, true)
  assert.equal(buildFixtureEvidence({
    ...base,
    endStatus: { ...base.endStatus, interval: 0.001 },
  }).validated, false)
})

test('SuperWatch fixture evidence validates prepare requests and dump-memory status', () => {
  const evidence = buildFixtureEvidence({
    streamName: 'superwatch',
    fixture: {
      stream: 'superwatch', channels: ['vofa_test_sin', 'vofa_test_tri'],
      intervalSeconds: 0.00001, acquisitionMode: 'dump-memory',
    },
    targetWrites: [], targetArmed: true,
    prepareRequests: [
      { path: '/api/dash/superwatch/add', body: { name: 'vofa_test_sin' } },
      { path: '/api/dash/superwatch/add', body: { name: 'vofa_test_tri' } },
      { path: '/api/dash/superwatch/interval', body: { interval: 0.00001 } },
    ],
    startBodyText: undefined,
    endStatus: {
      interval: 0.00001, acquisition_mode: 'dump-memory',
      items: [{ name: 'vofa_test_sin' }, { name: 'vofa_test_tri' }],
    },
  })

  assert.equal(evidence.validated, true)
  assert.deepEqual(evidence.channels, ['vofa_test_sin', 'vofa_test_tri'])
})

test('packaged gate rejects a canvas that clears but never draws a curve', () => {
  const metrics = cleanMetrics()
  metrics.canvasStrokes = 0

  const evaluation = evaluatePackagedGate(metrics)

  assert.equal(evaluation.checks.canvasStroked, false)
  assert.equal(evaluation.pass, false)
})

test('SystemView gate requires printable task names without replacement characters', () => {
  const clean = cleanMetrics()
  clean.streamName = 'systemview'
  clean.websocketUrls = ['ws://127.0.0.1:8765/ws/streams/systemview']
  clean.taskNames = { 1: 'svuser', 2: 'tidle0' }

  const evaluation = evaluatePackagedGate(clean)

  assert.equal(evaluation.checks.validSystemViewTaskNames, true)
  assert.equal(evaluation.pass, true)

  for (const taskNames of [
    {},
    { 1: '\u0006svuser' },
    { 1: 'svuser\ufffd' },
    { 1: '   ' },
    { 1: 123 },
    { 1: 'x'.repeat(33) },
  ]) {
    const metrics = { ...clean, taskNames }
    assert.equal(evaluatePackagedGate(metrics).checks.validSystemViewTaskNames, false)
  }
})

test('configured packaged start also clicks the GUI start control', async () => {
  const calls = []
  await startPackagedStream(
    async body => { calls.push(['api', body]) },
    async () => { calls.push(['ui']) },
    '{"channel":0}',
  )

  assert.deepEqual(calls, [['api', { channel: 0 }], ['ui']])
})

test('packaged gate includes control frames in WebSocket and Worker parity', () => {
  const metrics = cleanMetrics()
  metrics.dataFrames = 10
  metrics.wireFrames = 12
  metrics.workerAcceptedFrames = 12

  assert.equal(evaluatePackagedGate(metrics).pass, true)
})

test('packaged gate allows the connected-state poll to reveal the start control', async () => {
  let options = null
  const control = { waitFor: async value => { options = value } }
  const streamRoot = { locator: () => control }

  assert.equal(await waitForStreamStartControl(streamRoot, '.start'), control)
  assert.deepEqual(options, { state: 'visible', timeout: 60_000 })
})

test('VOFA gate waits for the configured interval to reach the UI before start', async () => {
  const inputHandle = { kind: 'interval-input' }
  const calls = []
  const streamRoot = {
    locator(selector) {
      calls.push(['locator', selector])
      return {
        waitFor: async options => { calls.push(['waitFor', options]) },
        elementHandle: async () => inputHandle,
      }
    },
  }
  const page = {
    waitForFunction: async (callback, argument, options) => {
      calls.push(['waitForFunction', callback.toString(), argument, options])
    },
  }

  await waitForStreamUiReady(page, streamRoot, streamProfile('vofa'))

  assert.deepEqual(calls[0], ['locator', '#interval-input'])
  assert.deepEqual(calls[1], ['waitFor', { state: 'visible', timeout: 60_000 }])
  assert.equal(calls[2][0], 'waitForFunction')
  assert.match(calls[2][1], /Number\(input\.value\)/)
  assert.equal(calls[2][2], inputHandle)
  assert.deepEqual(calls[2][3], { timeout: 60_000 })
})

test('non-VOFA packaged streams do not wait for waveform configuration', async () => {
  const page = { waitForFunction: async () => { throw new Error('unexpected wait') } }
  const streamRoot = { locator: () => { throw new Error('unexpected locator') } }

  await waitForStreamUiReady(page, streamRoot, streamProfile('superwatch'))
})

test('packaged gate waits for the frontend device-connected badge before navigation', async () => {
  let selector = null
  let options = null
  const page = {
    locator(value) {
      selector = value
      return { waitFor: async waitOptions => { options = waitOptions } }
    },
  }

  await waitForFrontendDeviceConnection(page)
  assert.equal(selector, '.status-bar .badge-ok')
  assert.deepEqual(options, { state: 'visible', timeout: 60_000 })
})

test('packaged gate selects the stream through the visible dashboard tab', async () => {
  const calls = []
  const filtered = { click: async () => { calls.push(['click']) } }
  const tabs = {
    filter(options) {
      calls.push(['filter', options])
      return filtered
    },
  }
  const page = { locator: selector => { calls.push(['locator', selector]); return tabs } }

  await selectDashboardStreamTab(page, 'RTOS Trace')
  assert.deepEqual(calls, [
    ['locator', '.tabs-bar .tab-btn'],
    ['filter', { hasText: 'RTOS Trace' }],
    ['click'],
  ])
})

test('packaged warmup proves a primary-canvas frame after data and Worker readiness', async () => {
  const waits = []
  const page = {
    waitForFunction: async (callback, argument, options) => {
      waits.push({ source: callback.toString(), argument, options })
    },
    evaluate: async () => ({ clears: 17, strokes: 3 }),
  }

  await waitForWarmStream(page)

  assert.equal(waits.length, 2)
  assert.match(waits[0].source, /acceptedFrames/)
  assert.equal(waits[0].options.timeout, 60_000)
  assert.deepEqual(waits[1].argument, { clears: 17, strokes: 3 })
  assert.match(waits[1].source, /canvasClearCalls/)
  assert.match(waits[1].source, /canvasStrokeCalls/)
  assert.equal(waits[1].options.timeout, 60_000)
})
