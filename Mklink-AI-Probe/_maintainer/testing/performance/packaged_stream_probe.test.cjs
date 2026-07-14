'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const {
  cleanupAndDisconnect,
  evaluatePackagedGate,
  runWithCleanup,
  streamProfile,
} = require('./packaged_stream_probe.cjs')

function cleanMetrics() {
  return {
    streamName: 'rtt',
    requiredDurationSeconds: 300,
    elapsedSeconds: 300,
    workerAssetUrls: ['http://tauri.localhost/assets/streamDecoder.worker-abc.js'],
    websocketUrls: ['ws://127.0.0.1:8765/ws/streams/rtt'],
    dataFrames: 10,
    dataItems: 100,
    lastDataSequence: '42',
    workerAcceptedFrames: 10,
    workerBufferedSamples: 100,
    workerLastSequence: '42',
    canvasFrames: 30,
    sequenceErrors: 0,
    workerTelemetry: {
      transportDroppedBatches: 0,
      backendDroppedBatches: 0,
      backendDroppedItems: 0,
      backendDroppedBytes: 0,
    },
    backendDrops: { batches: 0, items: 0, bytes: 0 },
    cleanup: {
      running: false,
      activeClients: 0,
      resourceStatusAvailable: true,
      resourceOwnerPresent: false,
      targetDearmed: true,
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

test('rejects unknown packaged stream profiles', () => {
  assert.throws(() => streamProfile('serial'), /unsupported packaged stream/)
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

test('packaged gate passes only with complete transport and cleanup evidence', () => {
  const evaluation = evaluatePackagedGate(cleanMetrics())
  assert.equal(evaluation.pass, true)
  assert.equal(Object.values(evaluation.checks).every(Boolean), true)
})

test('packaged gate rejects sequence, transport, backend, or cleanup loss', () => {
  const mutations = [
    metrics => { metrics.workerAcceptedFrames = 9 },
    metrics => { metrics.workerLastSequence = '41' },
    metrics => { metrics.sequenceErrors = 1 },
    metrics => { metrics.workerTelemetry.transportDroppedBatches = 1 },
    metrics => { metrics.workerTelemetry.backendDroppedItems = 1 },
    metrics => { metrics.backendDrops.bytes = 1 },
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
