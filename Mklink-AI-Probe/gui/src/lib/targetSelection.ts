// Online flashing supplies defaults; each consumer can retain its own override.
const KEY = 'mklink.targetSelection'
export const TARGET_SELECTION_CHANGED = 'mklink-target-selection-changed'
export const PACKS_CHANGED = 'mklink-packs-changed'
type Selection = { part: string; revision: string }
export function onlineTarget(): Selection {
  try { return JSON.parse(localStorage.getItem(KEY) || 'null') || { part: '', revision: '' } }
  catch { return { part: '', revision: '' } }
}
export function publishOnlineTarget(part: string): void {
  if (!part) return
  try { localStorage.setItem(KEY, JSON.stringify({ part, revision: crypto.randomUUID() })) }
  catch { return }
  window.dispatchEvent(new Event(TARGET_SELECTION_CHANGED))
}
export function consumerTarget(consumer: string): string {
  const source = onlineTarget()
  try {
    const saved = JSON.parse(localStorage.getItem(`${KEY}.${consumer}`) || 'null')
    if (saved?.revision === source.revision) return saved.part
  } catch { /* Use the online selection when local settings are unavailable. */ }
  return source.part
}
export function saveConsumerTarget(consumer: string, part: string): void {
  try { localStorage.setItem(`${KEY}.${consumer}`, JSON.stringify({ part, revision: onlineTarget().revision })) }
  catch { /* A storage restriction must not block manual chip selection. */ }
}
export function notifyPacksChanged(): void {
  window.dispatchEvent(new Event(PACKS_CHANGED))
}
