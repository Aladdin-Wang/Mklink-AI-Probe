<template>
  <div
    ref="host" class="rtt-terminal-panel" role="application" tabindex="-1"
    :aria-label="tr('RTT 终端', 'RTT terminal')" @mousedown="focus"
  />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { tr } from '../../composables/useLanguage'
import { SeggerAnsiNormalizer } from '../../lib/seggerAnsi'

const props = defineProps<{ inputEnabled: boolean }>()
const emit = defineEmits<{ input: [data: string] }>()
const host = ref<HTMLElement | null>(null)
const normalizer = new SeggerAnsiNormalizer()
let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let resizeObserver: ResizeObserver | null = null

function write(text: string): void {
  const normalized = normalizer.push(text)
  if (normalized) terminal?.write(normalized)
}

function clear(): void {
  normalizer.reset()
  terminal?.clear()
  terminal?.write('\x1b[2J\x1b[H')
}

function fit(): void {
  const element = host.value
  if (!element || element.clientWidth <= 0 || element.clientHeight <= 0) return
  try { fitAddon?.fit() } catch { /* hidden or not measured yet */ }
}

function focus(): void {
  terminal?.focus()
}

function activate(): void {
  requestAnimationFrame(() => {
    fit()
    focus()
  })
}

watch(() => props.inputEnabled, enabled => {
  if (terminal) terminal.options.disableStdin = !enabled
})

onMounted(() => {
  const element = host.value
  if (!element) return
  terminal = new Terminal({
    allowTransparency: false,
    convertEol: true,
    cursorBlink: true,
    disableStdin: !props.inputEnabled,
    fontFamily: 'Cascadia Mono, Consolas, SFMono-Regular, monospace',
    fontSize: 13,
    lineHeight: 1.15,
    scrollback: 5000,
    theme: {
      background: '#10151d', foreground: '#d7dde7', cursor: '#f2f5f8',
      selectionBackground: '#315d91aa', black: '#1b2028', red: '#e7646a',
      green: '#4fc47f', yellow: '#e6b657', blue: '#5b97e5', magenta: '#b183d7',
      cyan: '#4bb8c4', white: '#d7dde7', brightBlack: '#697586',
      brightRed: '#ff7b81', brightGreen: '#6bd995', brightYellow: '#f5c96d',
      brightBlue: '#74adf5', brightMagenta: '#c69aeb', brightCyan: '#62cdd8',
      brightWhite: '#ffffff',
    },
  })
  fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  terminal.open(element)
  terminal.onData(data => {
    if (props.inputEnabled) emit('input', data)
  })
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(fit)
    resizeObserver.observe(element)
  }
  fit()
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  terminal?.dispose()
  terminal = null
  fitAddon = null
})

defineExpose({ write, clear, activate, focus })
</script>

<style scoped>
.rtt-terminal-panel {
  flex: 1 1 auto;
  min-height: 220px;
  margin-top: 8px;
  padding: 8px 6px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #10151d;
}
.rtt-terminal-panel :deep(.xterm) { height: 100%; }
.rtt-terminal-panel :deep(.xterm-viewport) { scrollbar-width: thin; }
</style>
