<script setup lang="ts">
import { Cable, FileCode, Radio, Server } from '@lucide/vue'

export type ConfigSection = 'local' | 'files' | 'remote' | 'serve'

defineProps<{ modelValue: ConfigSection }>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: ConfigSection): void
}>()

const sections = [
  { id: 'local' as const, label: '本地设备', icon: Cable },
  { id: 'files' as const, label: '文件来源', icon: FileCode },
  { id: 'remote' as const, label: '远程连接', icon: Radio },
  { id: 'serve' as const, label: '启动服务', icon: Server },
]
</script>

<template>
  <nav class="section-nav" aria-label="配置区域">
    <button
      v-for="section in sections"
      :key="section.id"
      type="button"
      :class="['section-button', { active: modelValue === section.id }]"
      :aria-current="modelValue === section.id ? 'page' : undefined"
      :data-testid="`config-section-${section.id}`"
      @click="emit('update:modelValue', section.id)"
    >
      <component :is="section.icon" :size="17" :stroke-width="1.8" aria-hidden="true" />
      <span data-testid="config-section">{{ section.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.section-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 176px;
  flex: 0 0 176px;
}

.section-button {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.section-button:hover {
  color: var(--fg);
  background: var(--surface);
  border-color: var(--border-subtle);
}

.section-button.active {
  color: var(--accent);
  background: #f3ece6;
  border-color: var(--border);
  font-weight: 600;
}

@media (max-width: 760px) {
  .section-nav {
    width: 100%;
    flex-basis: auto;
    flex-direction: row;
    overflow-x: auto;
  }

  .section-button {
    width: auto;
    min-width: max-content;
  }
}
</style>
