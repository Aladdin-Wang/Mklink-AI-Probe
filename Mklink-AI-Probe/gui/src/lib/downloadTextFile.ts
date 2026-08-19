import { isTauri } from '@tauri-apps/api/core'

export function timestampedLogName(prefix: string, now = new Date()): string {
  return `${prefix}-${now.toISOString().replace(/[:.]/g, '-')}.log`
}

export function downloadTextFile(filename: string, text: string): void {
  if (isTauri()) {
    void saveTextFile(filename, text)
    return
  }
  downloadBlobFile(filename, new Blob([text], { type: 'text/plain;charset=utf-8' }))
}

export function downloadBlobFile(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  try {
    link.click()
  } finally {
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

export async function saveBlobFile(filename: string, blob: Blob): Promise<boolean> {
  if (!isTauri()) {
    downloadBlobFile(filename, blob)
    return true
  }
  const { save } = await import('@tauri-apps/plugin-dialog')
  const path = await save({
    defaultPath: filename,
    filters: [{ name: 'Log / Binary', extensions: ['log', 'txt', 'bin'] }],
  })
  if (!path) return false
  const { invoke } = await import('@tauri-apps/api/core')
  const contents = Array.from(new Uint8Array(await blob.arrayBuffer()))
  await invoke('write_file', { path, contents })
  return true
}

export function saveTextFile(filename: string, text: string): Promise<boolean> {
  return saveBlobFile(filename, new Blob([text], { type: 'text/plain;charset=utf-8' }))
}
