'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { decodeStreamHeader, evaluateCleanup, evaluateTransportIntegrity } = require('./browser_stream_probe.cjs')

test('decodeStreamHeader distinguishes data from CONTROL frames', () => {
  const buffer = new ArrayBuffer(36)
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  bytes.set([0x4d, 0x4b, 0x53, 0x54])
  view.setUint8(4, 1)
  view.setUint8(5, 3)
  view.setUint8(7, 36)
  view.setBigUint64(12, 42n, true)
  view.setUint32(28, 13, true)
  assert.deepEqual(decodeStreamHeader(buffer), {
    streamType: 3, sequence: 42n, itemCount: 13, isControl: false,
  })
  view.setUint8(5, 255)
  assert.equal(decodeStreamHeader(buffer).isControl, true)
})

test('decodeStreamHeader rejects short and non-MKST messages', () => {
  assert.equal(decodeStreamHeader(new ArrayBuffer(4)), null)
  assert.equal(decodeStreamHeader(new ArrayBuffer(36)), null)
})

test('transport integrity fails on frontend sequence, Worker, or backend loss', () => {
  const clean = evaluateTransportIntegrity({
    sequenceErrors: 0,
    lastTelemetry: {
      transportDroppedBatches: 0, backendDroppedBatches: 0,
      backendDroppedItems: 0, backendDroppedBytes: 0,
    },
  }, { dropped_batches: 4, dropped_items: 8, dropped_bytes: 16 },
  { dropped_batches: 4, dropped_items: 8, dropped_bytes: 16 })
  assert.equal(clean.noNewDrops, true)

  for (const mutation of [
    gate => { gate.sequenceErrors = 1 },
    gate => { gate.lastTelemetry.transportDroppedBatches = 1 },
    gate => { gate.lastTelemetry.backendDroppedItems = 1 },
  ]) {
    const gate = JSON.parse(JSON.stringify({
      sequenceErrors: 0,
      lastTelemetry: {
        transportDroppedBatches: 0, backendDroppedBatches: 0,
        backendDroppedItems: 0, backendDroppedBytes: 0,
      },
    }))
    mutation(gate)
    assert.equal(evaluateTransportIntegrity(gate, {}, {}).noNewDrops, false)
  }
})

test('cleanup requires stopped backend, no clients or owner, and target dearm readback', () => {
  const clean = { running: false, activeClients: 0, resourceOwnerPresent: false, targetDearmed: true }
  assert.equal(evaluateCleanup(clean).pass, true)
  for (const mutation of [
    value => { value.running = true },
    value => { value.activeClients = 1 },
    value => { value.resourceOwnerPresent = true },
    value => { value.targetDearmed = false },
  ]) {
    const value = { ...clean }
    mutation(value)
    assert.equal(evaluateCleanup(value).pass, false)
  }
})
