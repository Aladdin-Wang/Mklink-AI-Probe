'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const {
  evaluateOnlineFlashGate,
  firstMismatchAddress,
  runOnlineFlashLifecycle,
  sanitizedFailure,
  scenarioDefinition,
  setActionSelection,
  targetRecordFor,
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

test('online flash failure output exposes only the sanitized stage', () => {
  assert.deepEqual(sanitizedFailure('target-selection'), {
    schemaVersion: 1,
    gate: 'packaged_tauri_online_flash_hil',
    result: 'error',
    stage: 'target-selection',
    error: 'online flash scenario failed; inspect local runtime logs',
  })
})

test('online flash target selection accepts catalog-normalized part-number case', () => {
  const target = targetRecordFor([
    { part_number: 'stm32f103rc', installed: true },
  ], 'STM32F103RC')

  assert.equal(target.part_number, 'stm32f103rc')
  assert.equal(target.installed, true)
})

test('online flash action selection applies checkbox changes sequentially', async () => {
  const order = ['connect', 'erase', 'program', 'verify', 'reset', 'disconnect']
  const checked = new Map(order.map(action => [action, true]))
  const changed = []
  const inputs = {
    async count() { return order.length },
    nth(index) {
      const action = order[index]
      return {
        async isDisabled() { return action === 'connect' || action === 'disconnect' },
        async isChecked() { return checked.get(action) },
        async setChecked(value) {
          changed.push(action)
          checked.set(action, value)
          await Promise.resolve()
        },
      }
    },
  }
  const page = { locator: () => inputs }

  await setActionSelection(page, ['connect', 'verify', 'disconnect'])

  assert.deepEqual(changed, ['erase', 'program', 'reset'])
  assert.deepEqual(order.filter(action => checked.get(action)), ['connect', 'verify', 'disconnect'])
})

test('installed verify scenario is read-only and requires successful verify states', () => {
  const definition = scenarioDefinition('verify', { hex: 'app.hex' })

  assert.equal(definition.file, 'app.hex')
  assert.deepEqual(definition.actions, ['connect', 'verify', 'disconnect'])
  assert.equal(definition.terminal, 'succeeded')
  assert.deepEqual(definition.states, [
    'queued', 'connecting', 'verifying', 'disconnecting', 'succeeded',
  ])
})

test('verify failure evidence extracts and requires the concrete first mismatch address', () => {
  assert.equal(
    firstMismatchAddress('verification mismatch at 0x08001234'),
    '0x08001234',
  )
  assert.equal(firstMismatchAddress('verification failed'), null)

  const metrics = cleanOnlineFlashMetrics()
  metrics.expectedErrorCode = 'VERIFY_FAIL'
  metrics.jobErrorCode = 'VERIFY_FAIL'
  metrics.firstMismatchAddress = null
  assert.equal(evaluateOnlineFlashGate(metrics).pass, false)

  metrics.firstMismatchAddress = '0x08001234'
  assert.equal(evaluateOnlineFlashGate(metrics).pass, true)
})
