import {
  MAX_SEND_HISTORY,
  type RttLineEnding,
  type RttSendHistoryEntry,
  type RttTransmitMode,
} from './desktopSettings'

const STORAGE_KEY = 'mklink.serial-assistant.settings.v1'

export interface SerialAssistantStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export interface SerialAssistantSettings {
  transmitMode: RttTransmitMode
  lineEnding: RttLineEnding
  sendHistory: RttSendHistoryEntry[]
}

function defaults(): SerialAssistantSettings {
  return { transmitMode: 'text', lineEnding: '', sendHistory: [] }
}

function isLineEnding(value: unknown): value is RttLineEnding {
  return value === '' || value === '\r' || value === '\n' || value === '\r\n'
}

function historyEntry(value: unknown): RttSendHistoryEntry | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const entry = value as Record<string, unknown>
  if (
    typeof entry.text !== 'string'
    || (entry.mode !== 'text' && entry.mode !== 'hex')
    || !isLineEnding(entry.lineEnding)
    || typeof entry.timestamp !== 'number'
    || !Number.isFinite(entry.timestamp)
  ) return null
  return {
    text: entry.text,
    mode: entry.mode,
    lineEnding: entry.lineEnding,
    timestamp: entry.timestamp,
  }
}

export function loadSerialAssistantSettings(storage: SerialAssistantStorage): SerialAssistantSettings {
  try {
    const value = JSON.parse(storage.getItem(STORAGE_KEY) || 'null') as Record<string, unknown> | null
    if (!value) return defaults()
    return {
      transmitMode: value.transmitMode === 'hex' ? 'hex' : 'text',
      lineEnding: isLineEnding(value.lineEnding) ? value.lineEnding : '',
      sendHistory: Array.isArray(value.sendHistory)
        ? value.sendHistory.map(historyEntry).filter((entry): entry is RttSendHistoryEntry => entry !== null).slice(0, MAX_SEND_HISTORY)
        : [],
    }
  } catch {
    return defaults()
  }
}

export function saveSerialAssistantSettings(
  storage: SerialAssistantStorage,
  settings: SerialAssistantSettings,
): SerialAssistantSettings {
  const saved = {
    transmitMode: settings.transmitMode === 'hex' ? 'hex' as const : 'text' as const,
    lineEnding: isLineEnding(settings.lineEnding) ? settings.lineEnding : '' as const,
    sendHistory: settings.sendHistory.map(historyEntry)
      .filter((entry): entry is RttSendHistoryEntry => entry !== null)
      .slice(0, MAX_SEND_HISTORY),
  }
  storage.setItem(STORAGE_KEY, JSON.stringify(saved))
  return saved
}
