import { computed, onMounted, onUnmounted, reactive, ref, type Ref } from 'vue'
import { DESKTOP_SETTINGS_STORAGE_KEY } from '../lib/desktopSettings'

type Section = 'signals' | 'pinned' | 'all'
type ResizableSection = 'signals' | 'pinned'
export type SectionFolds = Record<Section, boolean>
const defaults = { signals: 180, pinned: 150 }
const minimum = { signals: 80, pinned: 76, all: 180 }
const keys: Section[] = ['signals', 'pinned', 'all']
const storageKey = DESKTOP_SETTINGS_STORAGE_KEY + '.superwatch-section-sizes'

export function fitWatchSections(height: number, folded: SectionFolds, preferred: Record<ResizableSection, number>) {
  const open = keys.filter(key => !folded[key])
  const last = open.at(-1)
  const resizable = open.filter(key => key !== last) as ResizableSection[]
  const sizes = { signals: folded.signals ? 34 : 80, pinned: folded.pinned ? 34 : 76, all: folded.all ? 34 : 180 }
  const budget = Math.max(0, height - resizable.length * 6 - keys.reduce((sum, key) => sum + sizes[key], 0))
  const extra = (key: ResizableSection) => Math.max(0, preferred[key] - minimum[key])
  const requested = resizable.reduce((sum, key) => sum + extra(key), 0)
  const scale = requested ? Math.min(1, budget / requested) : 1
  for (const key of resizable) sizes[key] += Math.floor(extra(key) * scale)
  if (last) sizes[last] += budget - resizable.reduce((sum, key) => sum + Math.floor(extra(key) * scale), 0)
  return { sizes, resizable }
}

export function useWatchSectionSizes(region: Ref<HTMLElement | null>, folded: SectionFolds) {
  const preferred = reactive({ ...defaults })
  const height = ref(600)
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}')
    for (const key of ['signals', 'pinned'] as const) {
      if (Number.isFinite(saved?.[key])) preferred[key] = Math.max(minimum[key], Math.min(4000, saved[key]))
    }
  } catch { /* Client preferences must not block shared data. */ }
  const layout = computed(() => fitWatchSections(height.value, folded, preferred))
  const style = (key: Section) => ({ flex: `0 0 ${layout.value.sizes[key]}px` })
  const canResize = (key: ResizableSection) => layout.value.resizable.includes(key)
  const maxSize = (key: ResizableSection) => minimum[key] + Math.max(0,
    height.value - layout.value.resizable.length * 6
      - keys.reduce((sum, item) => sum + (item === key ? minimum[item] : folded[item] ? 34
        : layout.value.resizable.includes(item as ResizableSection) ? layout.value.sizes[item] : minimum[item]), 0))
  function save() {
    try { localStorage.setItem(storageKey, JSON.stringify(preferred)) } catch { /* Best effort. */ }
  }
  function setSize(key: ResizableSection, size: number) {
    preferred[key] = Math.round(Math.max(minimum[key], Math.min(maxSize(key), size)))
  }
  function adoptVisibleSizes() {
    const visible = { ...layout.value.sizes }
    for (const item of layout.value.resizable) preferred[item] = visible[item]
  }
  let drag: { key: ResizableSection; y: number; size: number; pointer: number } | undefined
  function move(event: PointerEvent) {
    if (drag && event.pointerId === drag.pointer) setSize(drag.key, drag.size + event.clientY - drag.y)
  }
  function stop() {
    if (drag) save()
    drag = undefined
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
    window.removeEventListener('blur', stop)
  }
  function start(event: PointerEvent, key: ResizableSection) {
    if (event.button !== 0 || !canResize(key)) return
    stop()
    // Start from the visible sizes after a viewport shrink, not hidden old pixels.
    adoptVisibleSizes()
    drag = { key, y: event.clientY, size: layout.value.sizes[key], pointer: event.pointerId }
    ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    window.addEventListener('blur', stop)
  }
  function keyboard(event: KeyboardEvent, key: ResizableSection) {
    if (!canResize(key)) return
    const current = layout.value.sizes[key]
    const next = event.key === 'ArrowUp' ? current - 20 : event.key === 'ArrowDown' ? current + 20
      : event.key === 'Home' ? minimum[key] : event.key === 'End' ? maxSize(key) : null
    if (next === null) return
    event.preventDefault()
    adoptVisibleSizes()
    setSize(key, next)
    save()
  }
  function reset() { Object.assign(preferred, defaults); save() }
  let observer: ResizeObserver | undefined
  onMounted(() => {
    observer = new ResizeObserver(() => { if (region.value?.clientHeight) height.value = region.value.clientHeight })
    if (region.value) {
      if (region.value.clientHeight) height.value = region.value.clientHeight
      observer.observe(region.value)
    }
  })
  onUnmounted(() => { stop(); observer?.disconnect() })
  return { layout, style, canResize, maxSize, minimum, start, keyboard, reset }
}
