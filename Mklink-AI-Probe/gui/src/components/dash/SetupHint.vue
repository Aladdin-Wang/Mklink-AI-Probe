<template>
  <div class="setup-hint" :class="`setup-${kind}`" role="status">
    <Usb v-if="kind === 'device'" :size="15" aria-hidden="true" />
    <FileCode2 v-else-if="kind === 'symbols'" :size="15" aria-hidden="true" />
    <CircleAlert v-else-if="kind === 'error'" :size="15" aria-hidden="true" />
    <Info v-else :size="15" aria-hidden="true" />
    <span class="setup-message">{{ message }}</span>
    <button
      v-if="primaryLabel"
      type="button"
      class="btn btn-sm setup-primary"
      :disabled="busy"
      @click="$emit('primary')"
    >
      <LoaderCircle v-if="busy" class="spinning" :size="14" aria-hidden="true" />
      <span>{{ primaryLabel }}</span>
    </button>
    <button
      v-if="secondaryLabel"
      type="button"
      class="setup-secondary"
      :disabled="busy"
      @click="$emit('secondary')"
    >
      {{ secondaryLabel }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { CircleAlert, FileCode2, Info, LoaderCircle, Usb } from '@lucide/vue'

withDefaults(defineProps<{
  kind?: 'device' | 'symbols' | 'error' | 'info'
  message: string
  primaryLabel?: string
  secondaryLabel?: string
  busy?: boolean
}>(), {
  kind: 'info',
  primaryLabel: '',
  secondaryLabel: '',
  busy: false,
})

defineEmits<{
  primary: []
  secondary: []
}>()
</script>

<style scoped>
.setup-hint {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: color-mix(in srgb, var(--surface) 92%, var(--accent));
  color: var(--muted);
  font-size: 12px;
}
.setup-device > svg,
.setup-symbols > svg { color: var(--accent); }
.setup-error > svg { color: var(--danger); }
.setup-message { min-width: 0; flex: 1; }
.setup-primary { display: inline-flex; align-items: center; gap: 5px; flex: 0 0 auto; }
.setup-secondary {
  flex: 0 0 auto;
  padding: 3px 2px;
  border: 0;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font-size: 12px;
}
.setup-secondary:disabled { color: var(--muted); cursor: default; }
.spinning { animation: setup-spin 0.8s linear infinite; }
@keyframes setup-spin { to { transform: rotate(360deg); } }
@media (max-width: 640px) {
  .setup-hint { align-items: flex-start; flex-wrap: wrap; }
  .setup-message { flex-basis: calc(100% - 24px); }
  .setup-primary { margin-left: 22px; }
}
</style>
