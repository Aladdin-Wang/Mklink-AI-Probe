import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RttTerminalPanel from './RttTerminalPanel.vue'

const mocks = vi.hoisted(() => ({
  terminalOptions: [] as Array<Record<string, unknown>>,
}))

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    options: Record<string, unknown>

    constructor(options: Record<string, unknown>) {
      mocks.terminalOptions.push(options)
      this.options = { disableStdin: options.disableStdin }
    }

    loadAddon() {}
    open() {}
    onData() { return { dispose() {} } }
    clear() {}
    write() {}
    focus() {}
    dispose() {}
  },
}))

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit() {}
  },
}))

describe('RttTerminalPanel', () => {
  beforeEach(() => {
    mocks.terminalOptions.length = 0
  })

  it('treats both bare LF and CRLF as terminal newlines', () => {
    const wrapper = mount(RttTerminalPanel, {
      props: { inputEnabled: true },
    })

    expect(mocks.terminalOptions).toHaveLength(1)
    expect(mocks.terminalOptions[0].convertEol).toBe(true)
    wrapper.unmount()
  })
})
