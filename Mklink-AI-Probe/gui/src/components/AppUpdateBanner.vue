<script setup lang="ts">
import { CircleArrowUp, Download, RefreshCw, TriangleAlert } from '@lucide/vue'
import type { AppUpdateState } from '../composables/useAppUpdater'

defineProps<{
  state: AppUpdateState
  version: string
  progress: number | null
  error: string
}>()

defineEmits<{
  install: []
  retry: []
  dismiss: []
}>()
</script>

<template>
  <div
    v-if="['downloading', 'ready', 'installing', 'error'].includes(state)"
    class="update-banner"
    :class="{ 'update-error': state === 'error' }"
    data-testid="update-banner"
    :role="state === 'error' ? 'alert' : 'status'"
  >
    <TriangleAlert v-if="state === 'error'" :size="15" aria-hidden="true" />
    <Download v-else-if="state === 'downloading'" :size="15" aria-hidden="true" />
    <RefreshCw v-else-if="state === 'installing'" :size="15" class="spin" aria-hidden="true" />
    <CircleArrowUp v-else :size="15" aria-hidden="true" />

    <span v-if="state === 'downloading'">正在下载 v{{ version }}</span>
    <span v-else-if="state === 'ready'">v{{ version }} 已下载完成</span>
    <span v-else-if="state === 'installing'">正在安装更新并重新启动</span>
    <span v-else>更新失败：{{ error }}</span>

    <progress
      v-if="state === 'downloading'"
      :value="progress ?? undefined"
      max="1"
      aria-label="软件更新下载进度"
    />
    <div v-if="state === 'ready'" class="update-actions">
      <button
        class="btn btn-sm btn-primary"
        data-testid="install-update"
        type="button"
        @click="$emit('install')"
      >
        <CircleArrowUp :size="13" aria-hidden="true" />
        立即安装
      </button>
      <button
        class="btn btn-sm"
        data-testid="later-update"
        type="button"
        @click="$emit('dismiss')"
      >稍后</button>
    </div>
    <button
      v-else-if="state === 'error'"
      class="btn btn-sm"
      data-testid="retry-update"
      type="button"
      @click="$emit('retry')"
    >
      <RefreshCw :size="13" aria-hidden="true" />
      重试
    </button>
  </div>
</template>

<style scoped>
.update-banner {
  flex: 0 0 34px;
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 20px;
  border-bottom: 1px solid #cbddea;
  background: #edf5fa;
  color: #245b78;
  font-size: 12px;
}
.update-error {
  border-bottom-color: #e6caca;
  background: #f8eeee;
  color: var(--danger);
}
.update-banner span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.update-banner progress {
  width: min(220px, 28vw);
  height: 6px;
  margin-left: auto;
  accent-color: var(--info);
}
.update-actions,
.update-banner > button {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.update-actions { gap: 6px; }
.update-actions button { display: inline-flex; align-items: center; gap: 5px; }
.spin { animation: update-spin 1s linear infinite; }
@keyframes update-spin { to { transform: rotate(360deg); } }
@media (max-width: 640px) {
  .update-banner { padding: 0 12px; }
  .update-banner progress { width: 100px; }
}
</style>
