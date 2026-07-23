import { isTauri } from '@tauri-apps/api/core'

const SYMBOL_FILTER = { name: 'AXF / ELF', extensions: ['axf', 'elf', 'out'] }
const MAP_FILTER = { name: 'MAP', extensions: ['map'] }

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
