<template>
  <div
    ref="root"
    class="version-history"
    @mouseenter="showFromHover"
    @mouseleave="hideFromHover"
    @focusout="onFocusOut"
  >
    <button
      ref="trigger"
      type="button"
      class="version-trigger"
      data-testid="app-version"
      aria-haspopup="dialog"
      aria-controls="version-history-panel"
      :aria-expanded="open"
      title="查看版本更新记录"
      @click="togglePinned"
      @focus="showFromFocus"
    >
      <History :size="12" aria-hidden="true" />
      <span>v{{ version }} · {{ buildCommit }}</span>
    </button>

    <section
      v-if="open"
      id="version-history-panel"
      class="version-panel"
      data-testid="version-history-panel"
      role="dialog"
      aria-label="版本更新记录"
    >
      <header class="version-panel-header">
        <div>
          <h2>版本更新</h2>
          <p>当前构建 {{ buildCommit }}</p>
        </div>
        <span class="current-version">v{{ version }}</span>
      </header>

      <div class="release-heading">稳定版记录</div>
      <ol class="release-list">
        <li
          v-for="entry in releaseHistory"
          :key="entry.version"
          class="release-entry"
          :class="{ current: entry.version === version }"
          data-testid="release-entry"
        >
          <div class="release-meta">
            <strong>v{{ entry.version }}</strong>
            <span v-if="entry.version === version" class="current-badge">当前版本</span>
            <time :datetime="entry.date">{{ entry.date }}</time>
          </div>
          <div class="release-summary">{{ entry.summary }}</div>
          <ul>
            <li v-for="change in entry.changes" :key="change">{{ change }}</li>
          </ul>
        </li>
      </ol>
    </section>
  </div>
</template>

<script setup lang="ts">
import { History } from '@lucide/vue'
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { releaseHistory } from '../data/releaseHistory'

defineProps<{
  version: string
  buildCommit: string
}>()

const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
const pinned = ref(false)
const hovered = ref(false)

function showFromHover(): void {
  hovered.value = true
  open.value = true
}

function hideFromHover(): void {
  hovered.value = false
  if (!pinned.value) open.value = false
}

function showFromFocus(): void {
  open.value = true
}

function togglePinned(): void {
  if (pinned.value) {
    pinned.value = false
    hovered.value = false
    open.value = false
    return
  }
  pinned.value = true
  open.value = true
}

function close(): void {
  pinned.value = false
  hovered.value = false
  open.value = false
}

function onFocusOut(event: FocusEvent): void {
  const next = event.relatedTarget
  if (next instanceof Node && root.value?.contains(next)) return
  if (!pinned.value && !hovered.value) open.value = false
}

function onPointerDown(event: PointerEvent): void {
  const target = event.target
  if (target instanceof Node && root.value?.contains(target)) return
  close()
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || !open.value) return
  event.preventDefault()
  close()
  void nextTick(() => trigger.value?.focus())
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeyDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeyDown)
})
</script>

<style scoped>
.version-history {
  position: relative;
  height: 100%;
  display: flex;
  align-items: center;
}
.version-trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 20px;
  padding: 0 2px;
  border: 0;
  background: transparent;
  color: var(--dim);
  font: inherit;
  cursor: pointer;
}
.version-trigger:hover,
.version-trigger:focus-visible,
.version-trigger[aria-expanded="true"] {
  color: var(--accent);
}
.version-trigger:focus-visible {
  outline: 1px solid var(--accent);
  outline-offset: 2px;
}
.version-panel {
  position: absolute;
  right: 0;
  bottom: calc(100% + 8px);
  z-index: 1200;
  width: min(390px, calc(100vw - 24px));
  max-height: min(520px, calc(100vh - 88px));
  overflow: auto;
  padding: 14px 16px 16px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--fg);
  box-shadow: 0 12px 32px rgba(20, 20, 19, 0.18);
  font-family: var(--font-body);
  font-size: 12px;
  text-align: left;
}
.version-panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 11px;
  border-bottom: 1px solid var(--border);
}
.version-panel-header h2 {
  font-size: 14px;
  font-weight: 650;
  letter-spacing: 0;
}
.version-panel-header p {
  margin-top: 2px;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 10px;
}
.current-version {
  flex: 0 0 auto;
  color: var(--accent);
  font-family: var(--font-mono);
  font-weight: 600;
}
.release-heading {
  margin: 11px 0 8px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
}
.release-list {
  list-style: none;
}
.release-entry {
  position: relative;
  margin-left: 5px;
  padding: 0 0 16px 17px;
  border-left: 1px solid var(--border);
}
.release-entry:last-child {
  padding-bottom: 0;
}
.release-entry::before {
  content: '';
  position: absolute;
  top: 5px;
  left: -4px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--dim);
}
.release-entry.current::before {
  background: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
}
.release-meta {
  display: flex;
  align-items: center;
  gap: 7px;
}
.release-meta strong {
  font-family: var(--font-mono);
  font-size: 12px;
}
.release-meta time {
  margin-left: auto;
  color: var(--dim);
  font-family: var(--font-mono);
  font-size: 10px;
}
.current-badge {
  color: var(--accent);
  font-size: 10px;
}
.release-summary {
  margin-top: 3px;
  color: var(--fg);
  font-weight: 600;
}
.release-entry ul {
  margin: 5px 0 0 15px;
  color: var(--muted);
  line-height: 1.55;
}
.release-entry li + li {
  margin-top: 2px;
}
</style>
