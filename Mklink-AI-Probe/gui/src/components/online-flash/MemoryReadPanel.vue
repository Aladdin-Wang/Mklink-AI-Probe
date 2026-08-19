<script setup lang="ts">
import { computed, ref } from 'vue'
import { Download } from '@lucide/vue'
import { useOnlineFlashApi } from '../../composables/useOnlineFlashApi'
import { tr } from '../../composables/useLanguage'
import { downloadBlobFile } from '../../lib/downloadTextFile'

const props = defineProps<{
  probeId: string
  targetPart: string
  hpm: boolean
  frequency: number
  connectMode: string
  resetMode: string
  disabled?: boolean
}>()

const address = ref('0x08000000')
const size = ref(512 * 1024)
const busy = ref(false)
const error = ref('')
const api = useOnlineFlashApi()

const canRead = computed(() => (
  !props.hpm && !!props.probeId && !!props.targetPart
  && Number.isInteger(size.value) && size.value > 0
  && /^0x[0-9a-f]+$/i.test(address.value.trim())
  && !busy.value && !props.disabled
))

async function readMemory(): Promise<void> {
  if (!canRead.value) return
  error.value = ''
  busy.value = true
  const parsedAddress = Number.parseInt(address.value.trim().slice(2), 16)
  try {
    const blob = await api.readMemory({
      address: `0x${parsedAddress.toString(16)}`,
      size: size.value,
      probe_id: props.probeId,
      target_part: props.targetPart,
      frequency: props.frequency,
      connect_mode: props.connectMode,
      reset_mode: props.resetMode,
    })
    const filename = `read-0x${parsedAddress.toString(16).padStart(8, '0').toUpperCase()}-${size.value}.bin`
    downloadBlobFile(filename, blob)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : String(caught)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="memory-read-panel" data-testid="memory-read-panel">
    <header><h3>{{ tr('读取目标数据', 'Read Target Data') }}</h3><span v-if="hpm" class="badge">HPM</span></header>
    <p v-if="hpm" class="memory-read-note">{{ tr('HPM ROM API 当前不支持读取。', 'The HPM ROM API does not support reads yet.') }}</p>
    <template v-else>
      <label><span>{{ tr('起始地址', 'Start Address') }}</span><input v-model.trim="address" data-testid="memory-read-address" inputmode="text" spellcheck="false" placeholder="0x08000000"></label>
      <label><span>{{ tr('读取大小（字节）', 'Size (bytes)') }}</span><input v-model.number="size" data-testid="memory-read-size" type="number" min="1" max="67108864" step="1"></label>
      <p class="memory-read-note">{{ tr('超过 512 KiB 时会自动分块读取。', 'Reads larger than 512 KiB are split into chunks automatically.') }}</p>
      <button class="btn" type="button" data-testid="memory-read-submit" :disabled="!canRead" @click="readMemory"><Download :size="14" aria-hidden="true" />{{ busy ? tr('读取中...', 'Reading...') : tr('读取并保存 BIN', 'Read and Save BIN') }}</button>
      <p v-if="error" class="memory-read-error" role="alert">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.memory-read-panel { display: grid; gap: 8px; padding: 10px; border-top: 1px solid var(--of-border); }
.memory-read-panel header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.memory-read-panel h3 { margin: 0; color: var(--of-text); font-size: 12px; }
.memory-read-panel label { display: grid; gap: 4px; color: var(--of-muted); }
.memory-read-panel input { min-width: 0; width: 100%; height: 30px; box-sizing: border-box; border: 1px solid var(--of-border); border-radius: 5px; background: var(--of-input); color: var(--of-text); padding: 0 8px; font-family: var(--of-mono); }
.memory-read-panel .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
.memory-read-note { margin: 0; color: var(--of-muted); line-height: 1.4; }
.memory-read-error { margin: 0; color: var(--of-danger); overflow-wrap: anywhere; }
</style>
