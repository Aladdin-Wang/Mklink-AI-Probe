<template>
  <div class="raw-log-panel" :class="{ collapsed }">
    <div class="log-header" @click="collapsed = !collapsed">
      <span>{{ tr('原始日志', 'Raw Log') }} ({{ lines.length }})</span>
      <button class="toggle-btn" @click.stop="collapsed = !collapsed">
        {{ collapsed ? '▸' : '▾' }}
      </button>
      <button class="clear-btn" @click.stop="$emit('clear')">{{ tr('清除', 'Clear') }}</button>
    </div>
    <div v-if="!collapsed" class="log-body" ref="logBody">
      <div v-for="(line, i) in visibleLines" :key="i" class="log-line">{{ line }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { tr } from '../../composables/useLanguage'

const props = defineProps<{
  lines: string[]
  maxHeight?: string
}>()

defineEmits<{ clear: [] }>()

const collapsed = ref(true)
const logBody = ref<HTMLElement | null>(null)

const visibleLines = computed(() => {
  const max = 500
  if (props.lines.length <= max) return props.lines
  return props.lines.slice(-max)
})

watch(() => props.lines.length, async () => {
  if (!collapsed.value) {
    await nextTick()
    if (logBody.value) {
      logBody.value.scrollTop = logBody.value.scrollHeight
    }
  }
})
</script>

<style scoped>
.raw-log-panel {
  border-top: 1px solid var(--border);
  margin-top: 4px;
}
.log-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  cursor: pointer;
  font-size: 12px;
  color: var(--muted);
  user-select: none;
}
.toggle-btn, .clear-btn {
  background: none; border: none; color: var(--muted);
  cursor: pointer; font-size: 12px; padding: 0 4px;
}
.clear-btn { margin-left: auto; }
.clear-btn:hover { color: var(--fg); }
.log-body {
  max-height: v-bind(maxHeight || '150px');
  overflow-y: auto;
  padding: 4px 8px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
  font-size: 11px;
  color: #ccc;
  line-height: 1.4;
  background: #1e1e1e;
}
.log-line {
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
