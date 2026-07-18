import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.doUnmock('@tauri-apps/plugin-dialog')
  vi.resetModules()
})

async function loadPickerWithDialog(result: unknown) {
  const open = vi.fn().mockResolvedValue(result)
  vi.doMock('@tauri-apps/plugin-dialog', () => ({ open }))
  return { open, picker: await import('./filePicker') }
}

describe('file picker', () => {
  it('opens an AXF/ELF single-file dialog', async () => {
    const { open, picker } = await loadPickerWithDialog('C:\\firmware\\app.axf')

    await expect(picker.pickSymbolFile()).resolves.toBe('C:\\firmware\\app.axf')
    expect(open).toHaveBeenCalledWith({
      multiple: false,
      filters: [{ name: 'AXF / ELF', extensions: ['axf', 'elf', 'out'] }],
    })
  })

  it('opens a MAP-only single-file dialog', async () => {
    const { open, picker } = await loadPickerWithDialog('C:\\firmware\\app.map')

    await expect(picker.pickMapFile()).resolves.toBe('C:\\firmware\\app.map')
    expect(open).toHaveBeenCalledWith({
      multiple: false,
      filters: [{ name: 'MAP', extensions: ['map'] }],
    })
  })

  it('returns null when the dialog is cancelled', async () => {
    const { picker } = await loadPickerWithDialog(null)

    await expect(picker.pickSymbolFile()).resolves.toBeNull()
  })

  it('returns null when the Tauri dialog plugin is unavailable', async () => {
    vi.doMock('@tauri-apps/plugin-dialog', () => {
      throw new Error('dialog plugin unavailable')
    })
    const picker = await import('./filePicker')

    await expect(picker.pickMapFile()).resolves.toBeNull()
  })
})
