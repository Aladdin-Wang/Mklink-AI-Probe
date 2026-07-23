'use strict'

const assert = require('node:assert/strict')
const test = require('node:test')
const { prepareStream } = require('./frontend_stream_gate.cjs')

test('SystemView preparation leaves high-rate fixture dearmed', async () => {
  const writes = []
  const response = payload => ({
    ok: () => true,
    status: () => 200,
    json: async () => payload,
  })
  const request = {
    post: async () => response({}),
    fetch: async (_url, options) => {
      if (options.data?.name) writes.push(options.data)
      return response({})
    },
  }

  await prepareStream('systemview', request, 'http://test.invalid', 0)

  assert.deepEqual(writes.find(write => write.name === 'mklink_sv_user_event_pairs_per_tick'), {
    name: 'mklink_sv_user_event_pairs_per_tick', value: 1,
  })
  assert.deepEqual(writes.at(-1), { name: 'mklink_sv_test_arm', value: 0 })
  assert.equal(writes.some(write => write.name === 'mklink_sv_test_arm' && write.value === 1), false)
})
