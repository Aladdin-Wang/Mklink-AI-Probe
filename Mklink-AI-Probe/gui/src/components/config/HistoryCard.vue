<template>
  <div class="card" v-if="history.length > 0">
    <div class="card-title">{{ tr('最近项目', 'Recent Projects') }}</div>
    <div class="history-list">
      <div
        v-for="entry in history"
        :key="entry.path"
        class="history-item"
        :class="{ active: entry.path === currentPath }"
        @click="$emit('select', entry.path)"
      >
        <div class="history-info">
          <span class="history-name">{{ entry.name }}</span>
          <span class="history-path" :title="entry.path">{{ truncatePath(entry.path) }}</span>
        </div>
        <span class="history-time">{{ relativeTime(entry.last_used) }}</span>
        <button class="btn-remove" @click.stop="remove(entry.path)" :title="tr('移除', 'Remove')">✕</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useProjectHistory } from '../../composables/useProjectHistory'
import { tr } from '../../composables/useLanguage'

defineProps<{
  currentPath: string
}>()

defineEmits<{
  select: [path: string]
}>()

const { history, removeEntry } = useProjectHistory()

function remove(path: string) {
  removeEntry(path)
}

function truncatePath(path: string): string {
  if (path.length <= 50) return path
  const start = path.substring(0, 20)
  const end = path.substring(path.length - 27)
  return `${start}...${end}`
}

function relativeTime(iso: string): string {
  try {
    const then = new Date(iso).getTime()
    const now = Date.now()
    const diffMs = now - then
    const minutes = Math.floor(diffMs / 60000)
    if (minutes < 1) return tr('刚刚', 'Just now')
    if (minutes < 60) return tr(`${minutes}分钟前`, `${minutes} min ago`)
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return tr(`${hours}小时前`, `${hours} hr ago`)
    const days = Math.floor(hours / 24)
    if (days < 30) return tr(`${days}天前`, `${days} d ago`)
    return new Date(iso).toLocaleDateString()
  } catch {
    return ''
  }
}
</script>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
}
.history-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}
.history-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.1s;
}
.history-item:hover {
  background: var(--bg);
}
.history-item.active {
  background: var(--surface);
  border: 1px solid var(--accent);
}
.history-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.history-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--fg);
}
.history-path {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-time {
  font-size: 11px;
  color: var(--dim);
  flex-shrink: 0;
  white-space: nowrap;
}
.btn-remove {
  background: none;
  border: none;
  color: var(--dim);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 4px;
  border-radius: 3px;
  opacity: 0;
  transition: opacity 0.15s, color 0.15s;
  flex-shrink: 0;
}
.history-item:hover .btn-remove {
  opacity: 1;
}
.btn-remove:hover {
  color: #e74c3c;
  background: var(--bg);
}
</style>
