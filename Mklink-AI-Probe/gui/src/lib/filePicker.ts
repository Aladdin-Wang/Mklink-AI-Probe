const SYMBOL_FILTER = { name: 'AXF / ELF', extensions: ['axf', 'elf'] }
const MAP_FILTER = { name: 'MAP', extensions: ['map'] }

async function pickFile(filter: { name: string, extensions: string[] }): Promise<string | null> {
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const result = await open({ multiple: false, filters: [filter] })
    return typeof result === 'string' ? result : null
  } catch {
    return null
  }
}

export function pickSymbolFile(): Promise<string | null> {
  return pickFile(SYMBOL_FILTER)
}

export function pickMapFile(): Promise<string | null> {
  return pickFile(MAP_FILTER)
}
