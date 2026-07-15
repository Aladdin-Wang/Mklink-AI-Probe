'use strict'

const fs = require('node:fs')
const { execFileSync } = require('node:child_process')
let fatalStage = 'startup'

function parseJsonBytes(bytes) {
  let text
  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    text = bytes.subarray(2).toString('utf16le')
  } else {
    text = bytes.toString('utf8').replace(/^\ufeff/, '')
  }
  return JSON.parse(text)
}

async function apiJson(baseUrl, path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, options)
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`)
  return await response.json()
}

async function verifyMemoryWrites(baseUrl, writes) {
  if (!Array.isArray(writes) || writes.length === 0) return false
  for (const write of writes) {
    const expected = String(write.data_hex || '').toLowerCase()
    if (!expected || expected.length % 2 !== 0) return false
    const readback = await apiJson(baseUrl, '/api/device/read-memory', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ address: write.address, size: expected.length / 2 }),
    })
    if (String(readback.data_hex || '').toLowerCase() !== expected) return false
  }
  return true
}

async function waitForEndpointRelease(url, attempts = 40) {
  let releasedSamples = 0
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      await fetch(url, { signal: AbortSignal.timeout(500) })
      releasedSamples = 0
    } catch {
      releasedSamples += 1
      if (releasedSamples >= 2) return true
    }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  return false
}

function processExists(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

async function waitForProcessExit(pid, attempts = 40) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (!processExists(pid)) return true
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  return false
}

function terminateProcessTree(pid) {
  if (!Number.isInteger(pid) || pid <= 0) throw new Error('invalid Tauri process')
  if (!processExists(pid)) return
  if (process.platform === 'win32') {
    execFileSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
      stdio: 'ignore', windowsHide: true, timeout: 15_000,
    })
    return
  }
  process.kill(pid, 'SIGTERM')
}

function sanitizedControls(writes) {
  if (!Array.isArray(writes)) return []
  return writes.map(write => ({
    symbol: String(write?.symbol || ''),
    maskedAddress: String(write?.maskedAddress || ''),
    value: Number(write?.value),
  }))
}

async function step(operation) {
  try {
    const value = await operation()
    return value === false ? false : (value ?? true)
  } catch {
    return false
  }
}

async function finalizePackagedCleanup(options, dependencies) {
  const controls = sanitizedControls(options.dearmWrites)
  const controlsDescribeZero = controls.length > 0 && controls.every(control => (
    control.symbol
      && control.maskedAddress.includes('*')
      && /^0x[0-9a-f*]+$/i.test(control.maskedAddress)
      && control.value === 0
  ))
  const flashResult = await step(() => dependencies.flash(options.firmware))
  const checks = {
    browserClosed: options.measurement?.cleanup?.browserClosed === true,
    measurementTargetDearmed: options.measurement?.cleanup?.targetDearmed === true,
    targetReflashed: Boolean(flashResult),
    targetVerified: flashResult?.verified === true,
    targetReset: false,
    finalControlsZero: false,
    tauriExited: false,
    apiPortReleased: false,
    cdpPortReleased: false,
  }
  checks.targetReset = Boolean(await step(() => dependencies.reset()))
  const writesVerified = Boolean(await step(() => dependencies.verifyWrites(options.dearmWrites)))
  checks.finalControlsZero = controlsDescribeZero && writesVerified
  await step(() => dependencies.terminateTauri(options.tauriPid))
  checks.tauriExited = Boolean(await step(() => dependencies.waitForTauriExit(options.tauriPid)))
  checks.apiPortReleased = Boolean(await step(() => dependencies.waitForApiRelease()))
  checks.cdpPortReleased = Boolean(await step(() => dependencies.waitForCdpRelease()))
  return {
    schemaVersion: 1,
    gate: `packaged_tauri_${options.streamName}_cleanup`,
    result: Object.values(checks).every(Boolean) ? 'pass' : 'fail',
    checks,
    controls,
  }
}

async function main() {
  fatalStage = 'read-environment'
  const streamName = String(process.env.MKLINK_STREAM || '').toLowerCase()
  const artifactPath = process.env.MKLINK_STREAM_ARTIFACT
  const firmware = process.env.MKLINK_FINAL_FIRMWARE
  const tauriPid = Number(process.env.MKLINK_TAURI_PID || 0)
  const baseUrl = process.env.MKLINK_GUI_URL || 'http://127.0.0.1:8765'
  const cdpUrl = process.env.TAURI_CDP_URL || 'http://127.0.0.1:9223'
  fatalStage = 'parse-dearm'
  const dearmWrites = JSON.parse(process.env.MKLINK_TARGET_DEARM_WRITES || '[]')
  if (!streamName || !artifactPath || !firmware || !Number.isInteger(tauriPid) || tauriPid <= 0) {
    throw new Error('cleanup runtime inputs are incomplete')
  }
  fatalStage = 'read-artifact'
  const measurement = parseJsonBytes(fs.readFileSync(artifactPath))
  fatalStage = 'finalize'
  const result = await finalizePackagedCleanup({
    streamName, measurement, firmware, tauriPid, dearmWrites,
  }, {
    flash: value => apiJson(baseUrl, '/api/device/flash', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ firmware: value, verify: true, reset_after: true }),
    }),
    reset: () => apiJson(baseUrl, '/api/device/reset', { method: 'POST' }),
    verifyWrites: writes => verifyMemoryWrites(baseUrl, writes),
    terminateTauri: pid => terminateProcessTree(pid),
    waitForTauriExit: pid => waitForProcessExit(pid),
    waitForApiRelease: () => waitForEndpointRelease(`${baseUrl}/api/health`),
    waitForCdpRelease: () => waitForEndpointRelease(`${cdpUrl}/json/version`),
  })
  console.log(JSON.stringify(result, null, 2))
  process.exitCode = result.result === 'pass' ? 0 : 1
}

if (require.main === module) {
  main().catch(() => {
    console.error(JSON.stringify({
      schemaVersion: 1, gate: 'packaged_tauri_stream_cleanup', result: 'error',
      stage: fatalStage,
    }, null, 2))
    process.exitCode = 1
  })
}

module.exports = { finalizePackagedCleanup, parseJsonBytes, waitForEndpointRelease }
