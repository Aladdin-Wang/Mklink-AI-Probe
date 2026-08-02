// @vitest-environment node

import { describe, expect, it } from 'vitest'
import type { UserConfig } from 'vite'

import viteConfig from './vite.config'

describe('Vite development proxy', () => {
  it('forwards REST and binary WebSocket traffic to the local backend', () => {
    const proxy = (viteConfig as UserConfig).server?.proxy

    expect(proxy?.['/api']).toBe('http://127.0.0.1:8765')
    expect(proxy?.['/ws']).toMatchObject({
      target: 'ws://127.0.0.1:8765',
      ws: true,
    })
  })
})
