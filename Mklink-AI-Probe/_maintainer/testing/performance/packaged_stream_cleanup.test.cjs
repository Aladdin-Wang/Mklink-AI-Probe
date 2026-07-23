'use strict'

const assert = require('node:assert/strict')
const test = require('node:test')

const { finalizePackagedCleanup, parseJsonBytes } = require('./packaged_stream_cleanup.cjs')

test('cleanup reads PowerShell UTF-16LE artifacts as structured JSON', () => {
  const document = '{"result":"pass"}'
  const bytes = Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(document, 'utf16le')])

  assert.deepEqual(parseJsonBytes(bytes), { result: 'pass' })
})

test('final cleanup reflashes, resets, verifies controls, and releases the runtime', async () => {
  const calls = []
  const result = await finalizePackagedCleanup({
    streamName: 'systemview',
    measurement: { cleanup: { browserClosed: true, targetDearmed: true } },
    firmware: 'runtime-only.hex',
    tauriPid: 123,
    dearmWrites: [{
      address: '0x20000010', data_hex: '00000000',
      symbol: 'mklink_sv_test_arm', maskedAddress: '0x2000****', value: 0,
    }],
  }, {
    flash: async () => { calls.push('flash'); return { verified: true } },
    reset: async () => { calls.push('reset') },
    verifyWrites: async () => { calls.push('verify'); return true },
    terminateTauri: async () => { calls.push('terminate') },
    waitForTauriExit: async () => { calls.push('process'); return true },
    waitForApiRelease: async () => { calls.push('api'); return true },
    waitForCdpRelease: async () => { calls.push('cdp'); return true },
  })

  assert.deepEqual(calls, ['flash', 'reset', 'verify', 'terminate', 'process', 'api', 'cdp'])
  assert.equal(result.result, 'pass')
  assert.deepEqual(result.controls, [{
    symbol: 'mklink_sv_test_arm', maskedAddress: '0x2000****', value: 0,
  }])
  assert.equal(result.checks.targetVerified, true)
  assert.equal(JSON.stringify(result).includes('runtime-only.hex'), false)
  assert.equal(JSON.stringify(result).includes('0x20000010'), false)
})

test('final cleanup fails when the measurement or a release step is incomplete', async () => {
  const result = await finalizePackagedCleanup({
    streamName: 'rtt',
    measurement: { cleanup: { browserClosed: false, targetDearmed: true } },
    firmware: 'runtime-only.hex',
    tauriPid: 123,
    dearmWrites: [],
  }, {
    flash: async () => ({ success: true, verified: false }),
    reset: async () => {},
    verifyWrites: async () => false,
    terminateTauri: async () => {},
    waitForTauriExit: async () => true,
    waitForApiRelease: async () => false,
    waitForCdpRelease: async () => true,
  })

  assert.equal(result.result, 'fail')
  assert.equal(result.checks.browserClosed, false)
  assert.equal(result.checks.targetVerified, false)
  assert.equal(result.checks.finalControlsZero, false)
  assert.equal(result.checks.apiPortReleased, false)
})
