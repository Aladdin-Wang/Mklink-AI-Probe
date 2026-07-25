import { isTauri } from '@tauri-apps/api/core'

const SYMBOL_FILTER = { name: 'AXF / ELF', extensions: ['axf', 'elf', 'out'] }
const MAP_FILTER = { name: 'MAP', extensions: ['map'] }
const FIRMWARE_FILTER = { name: 'BIN / HEX', extensions: ['bin', 'hex'] }

export type PickedFile = string | File | null

function pickBrowserFile(filter: { name: string, extensions: string[] }): Promise<File | null> {
  return new Promise(resolve => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = filter.extensions.map(extension => `.${extension}`).join(',')
    const finish = (file: File | null) => {
      input.remove()
      resolve(file)
    }
    input.addEventListener('change', () => finish(input.files?.[0] ?? null), { once: true })
    input.addEventListener('cancel', () => finish(null), { once: true })
    input.click()
  })
}

async function pickFile(filter: { name: string, extensions: string[] }): Promise<PickedFile> {
  if (!isTauri()) return pickBrowserFile(filter)
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const result = await open({ multiple: false, filters: [filter] })
    return typeof result === 'string' ? result : null
  } catch {
    return null
  }
}

export function pickSymbolFile(): Promise<PickedFile> {
  return pickFile(SYMBOL_FILTER)
}

export function pickMapFile(): Promise<PickedFile> {
  return pickFile(MAP_FILTER)
}

export async function pickFirmwareFiles(multiple = false): Promise<Array<string | File>> {
  if (!isTauri()) {
    const selected = await pickBrowserFile(FIRMWARE_FILTER)
    return selected ? [selected] : []
  }
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const result: unknown = await open({ multiple, filters: [FIRMWARE_FILTER] })
    if (typeof result === 'string') return [result]
    return Array.isArray(result) ? result.filter((item: unknown): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

export async function listenForFirmwarePathDrops(
  onDrop: (paths: string[]) => void,
  onHover?: (active: boolean) => void,
): Promise<() => void> {
  if (!isTauri()) return () => undefined
  const { getCurrentWebview } = await import('@tauri-apps/api/webview')
  return getCurrentWebview().onDragDropEvent(event => {
    if (event.payload.type === 'drop') {
      onHover?.(false)
      onDrop(event.payload.paths)
    } else if (event.payload.type === 'over') {
      onHover?.(true)
    } else {
      onHover?.(false)
    }
  })
}
