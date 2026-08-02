import { beforeEach, describe, expect, it } from 'vitest'
import { loadSerialAssistantSettings, saveSerialAssistantSettings } from './serialAssistantSettings'

class MemoryStorage {
  private readonly values = new Map<string, string>()
  getItem(key: string): string | null { return this.values.get(key) ?? null }
  setItem(key: string, value: string): void { this.values.set(key, value) }
}

describe('serialAssistantSettings', () => {
  let storage: MemoryStorage

  beforeEach(() => { storage = new MemoryStorage() })

  it('keeps serial send history separate and normalizes persisted values', () => {
    expect(loadSerialAssistantSettings(storage)).toEqual({
      transmitMode: 'text', lineEnding: '', sendHistory: [],
    })

    saveSerialAssistantSettings(storage, {
      transmitMode: 'hex',
      lineEnding: '\r\n',
      sendHistory: [{ text: 'AA 55', mode: 'hex', lineEnding: '', timestamp: 10 }],
    })

    expect(loadSerialAssistantSettings(storage)).toEqual({
      transmitMode: 'hex',
      lineEnding: '\r\n',
      sendHistory: [{ text: 'AA 55', mode: 'hex', lineEnding: '', timestamp: 10 }],
    })
    expect(storage.getItem('mklink.desktop.settings.v1')).toBeNull()
  })
})
