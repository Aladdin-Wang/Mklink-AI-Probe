<template>
  <span ref="viewport" class="variable-path" :class="{ overflowing, dragging: drag !== null }"
    :title="path" :aria-label="path" :tabindex="overflowing ? 0 : undefined"
    @pointerdown="startDrag" @pointermove="moveDrag" @pointerup="endDrag"
    @pointercancel="endDrag" @lostpointercapture="drag = null" @keydown="onKey">{{ path }}</span>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
const props = defineProps<{ path: string; alignment?: { edge: 'left' | 'right'; revision: number } }>()
const viewport = ref<HTMLElement | null>(null)
const overflowing = ref(false)
const drag = ref<{ id: number; x: number; left: number } | null>(null)
let observer: ResizeObserver | undefined
function measure() {
  const el = viewport.value
  overflowing.value = !!el && el.scrollWidth > el.clientWidth
  if (el && props.alignment) el.scrollLeft = props.alignment.edge === 'right' ? el.scrollWidth - el.clientWidth : 0
}
function startDrag(event: PointerEvent) {
  const el = viewport.value
  if (!el || event.button !== 0 || el.scrollWidth <= el.clientWidth || event.pointerType === 'touch') return
  drag.value = { id: event.pointerId, x: event.clientX, left: el.scrollLeft }
  el.setPointerCapture(event.pointerId)
  event.preventDefault()
}
function moveDrag(event: PointerEvent) {
  if (viewport.value && drag.value?.id === event.pointerId) {
    viewport.value.scrollLeft = drag.value.left + drag.value.x - event.clientX
  }
}
function endDrag(event: PointerEvent) {
  if (drag.value?.id !== event.pointerId) return
  if (viewport.value?.hasPointerCapture(event.pointerId)) viewport.value.releasePointerCapture(event.pointerId)
  drag.value = null
}
function onKey(event: KeyboardEvent) {
  const el = viewport.value
  if (!el || !overflowing.value) return
  if (event.key === 'ArrowRight') el.scrollLeft += 40
  else if (event.key === 'ArrowLeft') el.scrollLeft -= 40
  else if (event.key === 'Home') el.scrollLeft = 0
  else if (event.key === 'End') el.scrollLeft = el.scrollWidth
  else return
  event.preventDefault()
}
onMounted(() => {
  measure()
  observer = new ResizeObserver(measure)
  if (viewport.value) observer.observe(viewport.value)
})
watch(() => [props.path, props.alignment], async () => {
  if (viewport.value) viewport.value.scrollLeft = 0
  await nextTick()
  measure()
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<style scoped>
.variable-path { display: block; min-width: 0; overflow-x: auto; white-space: nowrap; scrollbar-width: none; font: 12px/1.5 Consolas, monospace; color: var(--fg); }
.variable-path::-webkit-scrollbar { display: none; }
.overflowing { cursor: grab; }
.dragging { cursor: grabbing; user-select: none; }
.variable-path:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
