'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const {
  evaluateOnlineFlashGate,
  runOnlineFlashLifecycle,
} = require('./packaged_online_flash_probe.cjs')

function cleanOnlineFlashMetrics() {
  return {
    origin: 'http://tauri.localhost',
    route: '#/online-flash',
    probesReturned: 1,
    probesAllMklink: true,
    selectedProbe: true,
    packIndexAvailable: true,
    packTargetInstalled: true,
    targetPart: 'STM32F103RC',
    expectedTargetPart: 'STM32F103RC',
    imageInspected: true,
    imageSha256: 'boot-sha',
    expectedImageSha256: 'boot-sha',
    jobState: 'succeeded',
    expectedTerminalState: 'succeeded',
    uiTerminalObserved: true,
    observedStates: [
      'queued', 'connecting', 'erasing', 'programming', 'verifying',
      'resetting', 'disconnecting', 'succeeded',
    ],
    requiredStates: [
      'queued', 'connecting', 'erasing', 'programming', 'verifying',
      'resetting', 'disconnecting', 'succeeded',
    ],
    jobErrorCode: null,
    expectedErrorCode: null,
    handoffRequired: false,
    handoffSucceeded: null,
    activeJobPresent: false,
    targetDebugOwnerPresent: false,
    restoreRequired: true,
    restoredBootSha256: 'boot-sha',
    expectedRestoreSha256: 'boot-sha',
    restoreVerifySucceeded: true,
    consoleErrors: [],
    browserClosed: true,
  }
}

function onlineFlashFailureMutations() {
  return [
    metrics => { metrics.origin = 'http://127.0.0.1:5173' },
    metrics => { metrics.route = '#/dashboard' },
    metrics => { metrics.probesAllMklink = false },
    metrics => { metrics.selectedProbe = false },
    metrics => { metrics.packIndexAvailable = false },
    metrics => { metrics.packTargetInstalled = false },
    metrics => { metrics.targetPart = 'STM32F103C8' },
    metrics => { metrics.imageInspected = false },
    metrics => { metrics.imageSha256 = 'wrong' },
    metrics => { metrics.jobState = 'programming' },
    metrics => { metrics.uiTerminalObserved = false },
    metrics => { metrics.observedStates.splice(3, 1) },
    metrics => { metrics.expectedErrorCode = 'VERIFY_FAIL'; metrics.jobErrorCode = null },
    metrics => { metrics.handoffRequired = true; metrics.handoffSucceeded = false },
    metrics => { metrics.activeJobPresent = true },
    metrics => { metrics.targetDebugOwnerPresent = true },
    metrics => { metrics.restoredBootSha256 = 'wrong' },
    metrics => { metrics.restoreVerifySucceeded = false },
    metrics => { metrics.consoleErrors.push('page failed') },
    metrics => { metrics.browserClosed = false },
  ]
}

test('online flash gate requires UI, image, job, verify, cleanup, and restoration evidence', () => {
  const evaluation = evaluateOnlineFlashGate(cleanOnlineFlashMetrics())
  assert.equal(evaluation.pass, true)
  for (const mutation of onlineFlashFailureMutations()) {
    const metrics = cleanOnlineFlashMetrics()
    mutation(metrics)
    assert.equal(evaluateOnlineFlashGate(metrics).pass, false)
  }
})

test('online flash lifecycle closes CDP after a failed scenario', async () => {
  let cleaned = false
  let closed = false
  await assert.rejects(
    runOnlineFlashLifecycle(
      async () => { throw new Error('scenario failed') },
      async () => { cleaned = true },
      { close: async () => { closed = true } },
    ),
    /scenario failed/,
  )
  assert.equal(cleaned, true)
  assert.equal(closed, true)
})

test('online flash lifecycle closes CDP after cleanup failure without hiding it', async () => {
  let closed = false
  await assert.rejects(
    runOnlineFlashLifecycle(
      async () => ({ scenario: 'hex' }),
      async () => { throw new Error('cleanup failed') },
      { close: async () => { closed = true } },
    ),
    /cleanup failed/,
  )
  assert.equal(closed, true)
})
