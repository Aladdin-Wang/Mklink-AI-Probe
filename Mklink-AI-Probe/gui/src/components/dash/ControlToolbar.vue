<template>
  <div class="control-toolbar">
    <button v-if="state === 'idle'" class="btn btn-primary" @click="$emit('start')" :disabled="!deviceConnected">
      ▶ 开始
    </button>
    <button v-else-if="state === 'starting'" class="btn btn-primary" disabled>
      启动中...
    </button>
    <template v-else-if="state === 'error'">
      <button class="btn btn-primary" @click="$emit('start')" :disabled="!deviceConnected">
        ↻ 重试
      </button>
      <button class="btn btn-danger" @click="$emit('stop')">⏹ 停止</button>
    </template>
    <template v-else-if="state === 'running'">
      <button class="btn" @click="$emit('pause')">⏸ 暂停</button>
      <button class="btn btn-danger" @click="$emit('stop')">⏹ 停止</button>
    </template>
    <template v-else-if="state === 'paused'">
      <button class="btn btn-primary" @click="$emit('resume')">▶ 继续</button>
      <button class="btn btn-danger" @click="$emit('stop')">⏹ 停止</button>
    </template>
    <span v-if="state === 'running'" class="status-dot running"></span>
    <span v-else-if="state === 'paused'" class="status-dot paused"></span>
    <span v-if="error" class="error-text">{{ error }}</span>
    <span v-if="(pointCount ?? 0) > 0" class="point-count">{{ pointCount ?? 0 }} pts</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  state: 'idle' | 'starting' | 'running' | 'paused' | 'error'
  error?: string | null
  deviceConnected: boolean
  pointCount?: number
}>()

defineEmits<{
  start: []
  pause: []
  resume: []
  stop: []
}>()
</script>

<style scoped>
.control-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}
.btn {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--surface);
  color: var(--fg);
  cursor: pointer;
  font-size: 13px;
}
.btn:hover:not(:disabled) { background: var(--bg); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-primary { border-color: var(--accent); color: var(--accent); }
.btn-danger { border-color: var(--danger); color: var(--danger); }
.status-dot {
  width: 8px; height: 8px; border-radius: 50%; display: inline-block;
}
.status-dot.running { background: var(--success); }
.status-dot.paused { background: var(--warn); }
.error-text { color: var(--danger); font-size: 12px; }
.point-count { color: var(--muted); font-size: 12px; margin-left: auto; }
</style>
