/* Packaged Tauri online-flash hardware-in-loop qualification. */
'use strict'

const crypto = require('node:crypto')
const fs = require('node:fs')

const TERMINAL_STATES = new Set(['succeeded', 'failed', 'stopped'])
const SCENARIOS = new Set(['hex', 'bin', 'verify-fail', 'stop', 'probe-busy', 'restore'])
const ACTION_ORDER = ['connect', 'erase', 'program', 'verify', 'reset', 'disconnect']

function orderedSubsequence(observed, required) {
  let cursor = 0
  for (const state of observed || []) {
    if (state === required[cursor]) cursor += 1
    if (cursor === required.length) return true
  }
  return required.length === 0
}

function evaluateOnlineFlashGate(metrics) {
  const restoration = !metrics.restoreRequired
    || (metrics.restoredBootSha256 === metrics.expectedRestoreSha256
      && metrics.restoreVerifySucceeded === true)
  const checks = {
    tauriOrigin: metrics.origin === 'http://tauri.localhost',
    onlineFlashRoute: String(metrics.route || '').startsWith('#/online-flash'),
    mklinkOnlyProbes: Number(metrics.probesReturned || 0) > 0 && metrics.probesAllMklink === true,
    probeSelected: metrics.selectedProbe === true,
    targetSelected: metrics.targetPart === metrics.expectedTargetPart,
    packIndexAvailable: metrics.packIndexAvailable !== false,
    packTargetInstalled: metrics.packTargetInstalled !== false,
    imageInspected: metrics.imageInspected === true,
    imageShaMatches: metrics.imageSha256 === metrics.expectedImageSha256,
    terminalState: TERMINAL_STATES.has(metrics.jobState)
      && metrics.jobState === metrics.expectedTerminalState,
    uiTerminalObserved: metrics.uiTerminalObserved === true,
    orderedStateProgression: orderedSubsequence(metrics.observedStates, metrics.requiredStates || []),
    expectedErrorCode: metrics.expectedErrorCode == null
      ? metrics.jobErrorCode == null
      : metrics.jobErrorCode === metrics.expectedErrorCode,
    handoffSucceeded: metrics.handoffRequired !== true || metrics.handoffSucceeded === true,
    noActiveJob: metrics.activeJobPresent === false,
    targetDebugReleased: metrics.targetDebugOwnerPresent === false,
    bootRestoredAndVerified: restoration,
    noConsoleErrors: (metrics.consoleErrors || []).length === 0,
    browserClosed: metrics.browserClosed === true,
  }
  return { checks, pass: Object.values(checks).every(Boolean) }
}

async function runOnlineFlashLifecycle(operation, cleanupOperation, browser) {
  let value
  let primaryError = null
  let cleanupError = null
  let closeError = null
  try {
    value = await operation()
  } catch (error) {
    primaryError = error
  }
  try {
    const cleanup = await cleanupOperation(value, primaryError)
    if (value && cleanup !== undefined) value.cleanup = cleanup
  } catch (error) {
    cleanupError = error
  }
  try {
    await browser.close()
    if (value) value.browserClosed = true
  } catch (error) {
    closeError = error
  }
  if (primaryError) throw primaryError
  if (cleanupError) throw cleanupError
  if (closeError) throw closeError
  return value
}

async function apiJson(baseUrl, path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, options)
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const code = payload?.detail?.code || `HTTP_${response.status}`
    throw new Error(`${path}: ${code}`)
  }
  return payload
}

function jsonRequest(method, body) {
  const options = { method, headers: { 'content-type': 'application/json' } }
  if (body !== undefined) options.body = JSON.stringify(body)
  return options
}

function fileSha256(path) {
  return crypto.createHash('sha256').update(fs.readFileSync(path)).digest('hex')
}

function scenarioDefinition(scenario, env) {
  const fullStates = [
    'queued', 'connecting', 'erasing', 'programming', 'verifying',
    'resetting', 'disconnecting', 'succeeded',
  ]
  if (scenario === 'bin') {
    return { file: env.bin, actions: ACTION_ORDER, terminal: 'succeeded', states: fullStates }
  }
  if (scenario === 'verify-fail') {
    return {
      file: env.badBin,
      actions: ['connect', 'verify', 'disconnect'],
      terminal: 'failed', errorCode: 'VERIFY_FAIL',
      states: ['queued', 'connecting', 'verifying', 'disconnecting', 'failed'],
    }
  }
  if (scenario === 'stop') {
    return {
      file: env.hex, actions: ACTION_ORDER, terminal: 'stopped',
      states: ['queued', 'stopped'], stop: true,
    }
  }
  if (scenario === 'probe-busy') {
    return {
      file: env.hex, actions: ACTION_ORDER, terminal: 'failed',
      errorCode: 'PROBE_BUSY', states: ['queued', 'connecting', 'failed'],
      holdWithVofa: true, handoffRequired: true,
    }
  }
  return {
    file: env.hex, actions: ACTION_ORDER, terminal: 'succeeded', states: fullStates,
    restoreRequired: scenario === 'restore',
  }
}

async function setActionSelection(page, selectedActions) {
  await page.locator('.action-choices input[type="checkbox"]').evaluateAll((inputs, selected) => {
    const order = ['connect', 'erase', 'program', 'verify', 'reset', 'disconnect']
    inputs.forEach((input, index) => {
      const desired = selected.includes(order[index])
      if (!input.disabled && input.checked !== desired) input.click()
    })
  }, selectedActions)
  await page.waitForTimeout(50)
}

async function waitForTerminal(baseUrl, jobId, timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs
  let snapshot = null
  while (Date.now() < deadline) {
    snapshot = await apiJson(baseUrl, `/api/online-flash/jobs/${encodeURIComponent(jobId)}`)
    if (TERMINAL_STATES.has(snapshot.state)) return snapshot
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error(`online flash job did not reach terminal state from ${snapshot?.state || 'unknown'}`)
}

async function waitForNoActiveJob(baseUrl, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const active = await apiJson(baseUrl, '/api/online-flash/jobs/active')
    if (active == null) return false
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  return true
}

async function waitForTargetDebugRelease(baseUrl, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  let present = true
  while (Date.now() < deadline) {
    const resources = await apiJson(baseUrl, '/api/resources/status')
    present = Object.entries(resources || {}).some(([name, item]) => (
      name === 'target_debug' && item?.owner
    ))
    if (!present) return false
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  return present
}

async function stopVofaAndDisconnect(baseUrl) {
  await apiJson(baseUrl, '/api/dash/vofa/stop', jsonRequest('POST')).catch(() => {})
  await apiJson(baseUrl, '/api/device/disconnect', jsonRequest('POST')).catch(() => {})
}

async function acquireVofaOwner(baseUrl, targetPart) {
  await apiJson(baseUrl, '/api/device/connect', jsonRequest('POST', { mcu: targetPart }))
  await apiJson(baseUrl, '/api/dash/vofa/start', jsonRequest('POST', {
    channels: [{ name: 'resource_hold', addr: '0x20000000', type: 'float', size: 4 }],
    interval: 0.1,
  }))
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    const resources = await apiJson(baseUrl, '/api/resources/status')
    if (Object.values(resources || {}).some(item => item?.owner === 'user:dashboard:vofa')) return
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error('VOFA did not acquire target_debug')
}

async function startUiJob(page) {
  const responsePromise = page.waitForResponse(response => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/online-flash/jobs'
  ))
  await page.getByTestId('start-job').click()
  const response = await responsePromise
  if (!response.ok()) throw new Error(`online flash job create failed: HTTP_${response.status()}`)
  return response.json()
}

async function configureOnlineFlashPage(page, baseUrl, definition, targetPart, baseAddress) {
  await page.evaluate(() => { window.location.hash = '#/online-flash' })
  await page.waitForFunction(() => window.location.hash.startsWith('#/online-flash'))
  await page.locator('.online-flash-grid').waitFor({ state: 'visible' })

  const probes = await apiJson(baseUrl, '/api/online-flash/probes')
  if (!Array.isArray(probes) || probes.length === 0) throw new Error('no MKLink CMSIS-DAP probe found')
  const probeSelect = page.getByTestId('probe-select')
  await probeSelect.waitFor({ state: 'visible' })
  await page.waitForFunction(() => {
    const select = document.querySelector('[data-testid="probe-select"]')
    return select instanceof HTMLSelectElement && select.options.length > 1
  })
  await probeSelect.selectOption({ index: 1 })

  const search = page.getByTestId('target-search')
  await search.fill(targetPart)
  const target = page.getByTestId(`target-${targetPart}`)
  await target.waitFor({ state: 'visible', timeout: 60_000 })
  const targetsBefore = await apiJson(baseUrl, `/api/online-flash/targets?q=${encodeURIComponent(targetPart)}&limit=100`)
  const targetWasInstalled = targetsBefore.some(item => item.part_number === targetPart && item.installed)
  await target.click()
  await page.waitForFunction(part => document.querySelector(`[data-testid="target-${part}"]`)?.classList.contains('active'), targetPart, { timeout: 180_000 })

  const inspectResponsePromise = page.waitForResponse(response => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/online-flash/images/inspect'
  ))
  await page.getByTestId('firmware-input').setInputFiles(definition.file)
  if (definition.file.toLowerCase().endsWith('.bin')) await page.getByTestId('bin-base').fill(baseAddress)
  await page.getByTestId('inspect-image').click()
  const inspectResponse = await inspectResponsePromise
  if (!inspectResponse.ok()) throw new Error(`firmware inspection failed: HTTP_${inspectResponse.status()}`)
  const inspection = await inspectResponse.json()
  await page.locator('.metadata').waitFor({ state: 'visible' })
  await setActionSelection(page, definition.actions)

  const targetsAfter = await apiJson(baseUrl, `/api/online-flash/targets?q=${encodeURIComponent(targetPart)}&installed=true&limit=100`)
  const packStatus = await apiJson(baseUrl, '/api/online-flash/packs/status')
  return {
    probes,
    probeSelected: Boolean(await probeSelect.inputValue()),
    targetWasInstalled,
    targetInstalled: targetsAfter.some(item => item.part_number === targetPart && item.installed),
    packStatus,
    inspection,
  }
}

async function main() {
  const scenario = String(process.env.MKLINK_ONLINE_FLASH_SCENARIO || '').toLowerCase()
  if (!SCENARIOS.has(scenario)) throw new Error('MKLINK_ONLINE_FLASH_SCENARIO is invalid')
  const playwrightPath = process.env.PLAYWRIGHT_CORE_PATH
  if (!playwrightPath || !fs.existsSync(playwrightPath)) throw new Error('PLAYWRIGHT_CORE_PATH is required')
  const env = {
    hex: process.env.MKLINK_ONLINE_FLASH_HEX,
    bin: process.env.MKLINK_ONLINE_FLASH_BIN,
    badBin: process.env.MKLINK_ONLINE_FLASH_BAD_BIN,
  }
  const definition = scenarioDefinition(scenario, env)
  if (!definition.file || !fs.existsSync(definition.file)) throw new Error('required firmware input is unavailable')
  const targetPart = process.env.MKLINK_ONLINE_FLASH_TARGET || 'STM32F103RC'
  const baseAddress = process.env.MKLINK_ONLINE_FLASH_BASE || '0x08000000'
  const expectedSha = process.env.MKLINK_ONLINE_FLASH_EXPECTED_SHA256 || fileSha256(definition.file)
  const baseUrl = process.env.MKLINK_GUI_URL || 'http://127.0.0.1:8765'
  const cdpUrl = process.env.TAURI_CDP_URL || 'http://127.0.0.1:9223'
  const { chromium } = require(playwrightPath)
  const browser = await chromium.connectOverCDP(cdpUrl)
  const context = browser.contexts()[0]
  const page = context?.pages()[0]
  if (!page) throw new Error('no Tauri WebView page exposed by CDP')
  page.setDefaultTimeout(30_000)
  page.on('dialog', dialog => dialog.accept())
  await page.addInitScript(() => {
    window.__mklinkOnlineFlashGate = { states: [] }
    const NativeEventSource = window.EventSource
    window.EventSource = class OnlineFlashGateEventSource extends NativeEventSource {
      constructor(url, options) {
        super(url, options)
        if (!String(url).includes('/api/online-flash/jobs/')) return
        for (const name of ['state', 'error']) {
          this.addEventListener(name, event => {
            try {
              const payload = JSON.parse(event.data)
              if (payload?.state) window.__mklinkOnlineFlashGate.states.push(payload.state)
            } catch { /* the UI reports malformed SSE separately */ }
          })
        }
      }
    }
  })
  const consoleErrors = []
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()) })
  page.on('pageerror', error => consoleErrors.push(String(error)))
  await page.reload({ waitUntil: 'domcontentloaded' })

  let activeJobId = null
  let vofaHeld = false
  const metrics = await runOnlineFlashLifecycle(async () => {
    const configured = await configureOnlineFlashPage(page, baseUrl, definition, targetPart, baseAddress)
    if (definition.holdWithVofa) {
      await acquireVofaOwner(baseUrl, targetPart)
      vofaHeld = true
    }
    const created = await startUiJob(page)
    activeJobId = created.job_id
    if (definition.stop) {
      await page.getByTestId('stop-job').waitFor({ state: 'visible' })
      await page.waitForFunction(() => {
        const button = document.querySelector('[data-testid="stop-job"]')
        return button instanceof HTMLButtonElement && !button.disabled
      })
      await page.getByTestId('stop-job').click()
    }
    const terminal = await waitForTerminal(baseUrl, activeJobId)
    activeJobId = null
    let handoffSucceeded = null
    if (definition.handoffRequired) {
      await stopVofaAndDisconnect(baseUrl)
      vofaHeld = false
      if (await waitForTargetDebugRelease(baseUrl)) throw new Error('target_debug remained owned after VOFA handoff')
      const handoff = await startUiJob(page)
      activeJobId = handoff.job_id
      const handoffTerminal = await waitForTerminal(baseUrl, activeJobId)
      activeJobId = null
      handoffSucceeded = handoffTerminal.state === 'succeeded'
    }
    await page.waitForFunction(() => {
      const start = document.querySelector('[data-testid="start-job"]')
      const stop = document.querySelector('[data-testid="stop-job"]')
      return start instanceof HTMLButtonElement && !start.disabled
        && stop instanceof HTMLButtonElement && stop.disabled
    })
    await page.waitForTimeout(250)
    const observedStates = await page.evaluate(() => [...(window.__mklinkOnlineFlashGate?.states || [])])
    const location = new URL(page.url())
    return {
      scenario,
      origin: location.origin,
      route: location.hash,
      probesReturned: configured.probes.length,
      probesAllMklink: configured.probes.length > 0,
      selectedProbe: configured.probeSelected,
      targetPart,
      expectedTargetPart: targetPart,
      targetWasInstalled: configured.targetWasInstalled,
      packIndexAvailable: configured.packStatus.index_available === true,
      packTargetInstalled: configured.targetInstalled,
      imageInspected: Boolean(configured.inspection.image_id),
      imageSha256: configured.inspection.sha256,
      expectedImageSha256: expectedSha,
      jobState: terminal.state,
      expectedTerminalState: definition.terminal,
      uiTerminalObserved: true,
      observedStates,
      requiredStates: definition.states,
      jobErrorCode: terminal.error_code,
      expectedErrorCode: definition.errorCode || null,
      handoffRequired: definition.handoffRequired === true,
      handoffSucceeded,
      restoreRequired: definition.restoreRequired === true,
      restoredBootSha256: definition.restoreRequired ? terminal.image_sha256 : null,
      expectedRestoreSha256: definition.restoreRequired ? expectedSha : null,
      restoreVerifySucceeded: definition.restoreRequired ? terminal.state === 'succeeded' : null,
      consoleErrors,
    }
  }, async () => {
    if (activeJobId) {
      await apiJson(baseUrl, `/api/online-flash/jobs/${encodeURIComponent(activeJobId)}/stop`, jsonRequest('POST')).catch(() => {})
      await waitForTerminal(baseUrl, activeJobId, 30_000).catch(() => {})
      activeJobId = null
    }
    if (vofaHeld) {
      await stopVofaAndDisconnect(baseUrl)
      vofaHeld = false
    }
    const activeJobPresent = await waitForNoActiveJob(baseUrl)
    let targetDebugOwnerPresent = await waitForTargetDebugRelease(baseUrl)
    if (targetDebugOwnerPresent) {
      await apiJson(baseUrl, '/api/resources/release', jsonRequest('POST', {
        resource: 'target_debug', stop_active: true,
      })).catch(() => {})
      targetDebugOwnerPresent = await waitForTargetDebugRelease(baseUrl, 5_000)
    }
    return { activeJobPresent, targetDebugOwnerPresent }
  }, browser)

  metrics.activeJobPresent = metrics.cleanup.activeJobPresent
  metrics.targetDebugOwnerPresent = metrics.cleanup.targetDebugOwnerPresent
  const evaluation = evaluateOnlineFlashGate(metrics)
  const output = {
    schemaVersion: 1,
    gate: `packaged_tauri_online_flash_${scenario}_hil`,
    result: evaluation.pass ? 'pass' : 'fail',
    scenario,
    target: targetPart,
    image: {
      inspected: metrics.imageInspected,
      sha256: metrics.imageSha256,
      expectedSha256: metrics.expectedImageSha256,
    },
    job: {
      terminalState: metrics.jobState,
      expectedTerminalState: metrics.expectedTerminalState,
      uiTerminalObserved: metrics.uiTerminalObserved,
      observedStates: metrics.observedStates,
      requiredStates: metrics.requiredStates,
      errorCode: metrics.jobErrorCode,
      expectedErrorCode: metrics.expectedErrorCode,
      handoffSucceeded: metrics.handoffSucceeded,
    },
    pack: {
      indexAvailable: metrics.packIndexAvailable,
      targetInstalled: metrics.packTargetInstalled,
      reusedInstalledTarget: metrics.targetWasInstalled,
    },
    cleanup: metrics.cleanup,
    restoration: {
      required: metrics.restoreRequired,
      sha256: metrics.restoredBootSha256,
      expectedSha256: metrics.expectedRestoreSha256,
      verifySucceeded: metrics.restoreVerifySucceeded,
    },
    consoleErrorCount: metrics.consoleErrors.length,
    checks: evaluation.checks,
  }
  console.log(JSON.stringify(output, null, 2))
  process.exitCode = evaluation.pass ? 0 : 1
}

if (require.main === module) {
  main().catch(() => {
    console.error(JSON.stringify({
      schemaVersion: 1,
      gate: 'packaged_tauri_online_flash_hil',
      result: 'error',
      error: 'online flash scenario failed; inspect local runtime logs',
    }, null, 2))
    process.exitCode = 1
  })
}

module.exports = { evaluateOnlineFlashGate, runOnlineFlashLifecycle }
