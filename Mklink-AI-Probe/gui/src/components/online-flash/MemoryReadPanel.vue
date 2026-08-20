<script setup lang="ts">
import { computed, ref } from 'vue'
import { Download, Save, X } from '@lucide/vue'
import { useOnlineFlashApi } from '../../composables/useOnlineFlashApi'
import { tr } from '../../composables/useLanguage'
import { downloadBlobFile } from '../../lib/downloadTextFile'
import type { SectorRecord } from '../../types/onlineFlash'

const props = defineProps<{
  probeId: string
  targetPart: string
  hpm: boolean
  frequency: number
  connectMode: string
  resetMode: string
  sectors?: SectorRecord[]
  disabled?: boolean
}>()

const address = ref('0x08000000')
const endAddress = ref('0x08080000')
const busy = ref(false)
const error = ref('')
const readDialogOpen = ref(false)
const progress = ref(0)
const progressText = ref('')
const data = ref<Uint8Array | null>(null)
const progressEntries = ref<Array<{ address: number; size: number; state: 'reading' | 'done' | 'failed' }>>([])
const api = useOnlineFlashApi()

const parsedAddress = computed(() => {
  if (!/^0x[0-9a-f]+$/i.test(address.value.trim())) return null
  const value = Number.parseInt(address.value.trim().slice(2), 16)
  return Number.isSafeInteger(value) && value >= 0 && value <= 0xffff_ffff ? value : null
})
const parsedEndAddress = computed(() => {
  if (!/^0x[0-9a-f]+$/i.test(endAddress.value.trim())) return null
  const value = Number.parseInt(endAddress.value.trim().slice(2), 16)
  return Number.isSafeInteger(value) && value >= 0 && value <= 0xffff_ffff ? value : null
})
const readSize = computed(() => parsedAddress.value !== null && parsedEndAddress.value !== null
  ? parsedEndAddress.value - parsedAddress.value : 0)
const canRead = computed(() => (
  !props.hpm && !!props.probeId && !!props.targetPart
  && readSize.value > 0
  && readSize.value <= 64 * 1024 * 1024
  && !busy.value && !props.disabled
))

function chunkSizeAt(address: number, remaining: number): number {
  const sector = (props.sectors || []).find(item => (
    Number.isInteger(item.address) && Number.isInteger(item.size) && item.size > 0
    && address >= item.address && address < item.address + item.size
  ))
  if (!sector) return Math.min(1024, remaining)
  const available = sector.address + sector.size - address
  return Math.min(remaining, available)
}

function openReadDialog(): void {
  error.value = ''
  readDialogOpen.value = true
}

function closeReadDialog(): void {
  if (!busy.value) readDialogOpen.value = false
}

async function readMemory(): Promise<void> {
  if (!canRead.value || parsedAddress.value === null || parsedEndAddress.value === null) return
  error.value = ''
  busy.value = true
  progress.value = 0
  progressText.value = ''
  data.value = null
  progressEntries.value = []
  const start = parsedAddress.value
  const total = readSize.value
  const result = new Uint8Array(total)
  try {
    for (let offset = 0; offset < total;) {
      const chunkSize = chunkSizeAt(start + offset, total - offset)
      const entry: { address: number; size: number; state: 'reading' | 'done' | 'failed' } = {
        address: start + offset,
        size: chunkSize,
        state: 'reading',
      }
      progressEntries.value.push(entry)
      try {
        const blob = await api.readMemory({
          address: `0x${(start + offset).toString(16)}`,
          size: chunkSize,
          probe_id: props.probeId,
          target_part: props.targetPart,
          frequency: props.frequency,
          connect_mode: props.connectMode,
          reset_mode: props.resetMode,
        })
        const chunk = new Uint8Array(await blob.arrayBuffer())
        if (chunk.length !== chunkSize) throw new Error(tr('读取数据长度不匹配', 'Read returned an unexpected length'))
        result.set(chunk, offset)
        entry.state = 'done'
        progress.value = (offset + chunkSize) / total
        progressText.value = `${offset + chunkSize} / ${total} bytes`
        offset += chunkSize
      } catch (caught) {
        entry.state = 'failed'
        throw caught
      }
    }
    data.value = result
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : String(caught)
  } finally {
    busy.value = false
  }
}

async function saveMemory(): Promise<void> {
  if (!data.value || parsedAddress.value === null) return
  const filename = `read-0x${parsedAddress.value.toString(16).padStart(8, '0').toUpperCase()}-${data.value.length}.bin`
  const blob = new Blob([data.value.buffer.slice(data.value.byteOffset, data.value.byteOffset + data.value.byteLength) as ArrayBuffer], { type: 'application/octet-stream' })
  try {
    const picker = (window as Window & { showSaveFilePicker?: (options?: unknown) => Promise<{ createWritable: () => Promise<{ write: (value: Blob) => Promise<void>; close: () => Promise<void> }> }> }).showSaveFilePicker
    if (picker) {
      const handle = await picker({ suggestedName: filename, types: [{ description: 'Binary file', accept: { 'application/octet-stream': ['.bin'] } }] })
      const writable = await handle.createWritable()
      await writable.write(blob)
      await writable.close()
      return
    }
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === 'AbortError') return
    error.value = caught instanceof Error ? caught.message : String(caught)
    return
  }
  downloadBlobFile(filename, blob)
}
</script>

<template>
  <section class="memory-read-panel" data-testid="memory-read-panel">
    <header><h3>{{ tr('读取目标数据', 'Read Target Data') }}</h3><span v-if="hpm" class="badge">HPM</span></header>
    <p v-if="hpm" class="memory-read-note">{{ tr('HPM ROM API 当前不支持读取。', 'The HPM ROM API does not support reads yet.') }}</p>
    <template v-else>
      <div class="memory-read-actions">
        <button class="btn" type="button" data-testid="memory-read-submit" :disabled="!canRead" @click="openReadDialog"><Download :size="14" aria-hidden="true" />{{ tr('读取数据', 'Read Data') }}</button>
        <button class="btn" type="button" data-testid="memory-read-save" :disabled="!data || busy" @click="saveMemory"><Save :size="14" aria-hidden="true" />{{ tr('保存文件', 'Save File') }}</button>
      </div>
      <div v-if="busy || data" class="memory-read-progress" data-testid="memory-read-progress">
        <div class="memory-read-progress-row"><span>{{ busy ? tr('读取进度', 'Read progress') : tr('读取完成', 'Read complete') }}</span><span>{{ Math.round(progress * 100) }}%</span></div>
        <progress :value="progress" max="1"></progress>
        <span class="memory-read-note">{{ progressText || `${data?.length || 0} bytes` }}</span>
        <div class="memory-read-log" data-testid="memory-read-log">
          <div v-for="entry in progressEntries" :key="`${entry.address}-${entry.size}`" class="memory-read-log-entry">
            <span :class="`memory-read-log-state ${entry.state}`">{{ entry.state === 'done' ? tr('读取完成', 'Read complete') : entry.state === 'failed' ? tr('读取失败', 'Read failed') : tr('正在读取...', 'Reading...') }}</span>
            <span class="memory-read-log-range">0x{{ entry.address.toString(16).toUpperCase().padStart(8, '0') }} · {{ entry.size }} Bytes</span>
          </div>
        </div>
      </div>
      <p v-if="error" class="memory-read-error" role="alert">{{ error }}</p>
    </template>

    <div v-if="readDialogOpen" class="memory-read-dialog-backdrop" role="presentation" @click.self="closeReadDialog">
      <section class="memory-read-dialog" role="dialog" aria-modal="true" aria-labelledby="memory-read-dialog-title">
        <header><h4 id="memory-read-dialog-title">{{ tr('填写读取地址', 'Enter Read Range') }}</h4><button class="icon-button" type="button" :title="tr('关闭', 'Close')" @click="closeReadDialog"><X :size="15" aria-hidden="true" /></button></header>
        <label><span>{{ tr('基地址', 'Base Address') }}</span><input v-model.trim="address" data-testid="memory-read-address" inputmode="text" spellcheck="false" placeholder="0x08000000"></label>
        <label><span>{{ tr('结束地址（不含）', 'End Address (exclusive)') }}</span><input v-model.trim="endAddress" data-testid="memory-read-end-address" inputmode="text" spellcheck="false" placeholder="0x08080000"></label>
        <p class="memory-read-note">{{ readSize > 0 ? tr(`将读取 ${readSize} 字节，每次 1024 字节。`, `Reads ${readSize} bytes in 1024-byte chunks.`) : tr('结束地址必须大于基地址。', 'End address must be greater than the base address.') }}</p>
        <div class="memory-read-dialog-actions"><button class="btn" type="button" @click="closeReadDialog">{{ tr('取消', 'Cancel') }}</button><button class="btn btn-primary" type="button" data-testid="memory-read-confirm" :disabled="!canRead" @click="readDialogOpen = false; void readMemory()"><Download :size="14" aria-hidden="true" />{{ tr('开始读取', 'Start Read') }}</button></div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.memory-read-panel { display: grid; gap: 8px; padding: 10px; border-top: 1px solid var(--of-border); }
.memory-read-panel header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.memory-read-panel h3 { margin: 0; color: var(--of-text); font-size: 12px; }
.memory-read-panel label { display: grid; gap: 4px; color: var(--of-muted); }
.memory-read-panel input { min-width: 0; width: 100%; height: 30px; box-sizing: border-box; border: 1px solid var(--of-border); border-radius: 5px; background: var(--of-input); color: var(--of-text); padding: 0 8px; font-family: var(--of-mono); }
.memory-read-panel .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
.memory-read-actions { display: flex; gap: 8px; }
.memory-read-actions .btn { flex: 1 1 0; min-width: 0; }
.memory-read-progress { display: grid; gap: 5px; }
.memory-read-progress-row { display: flex; justify-content: space-between; color: var(--of-text); font-variant-numeric: tabular-nums; }
.memory-read-progress progress { width: 100%; height: 8px; accent-color: var(--of-accent); }
.memory-read-note { margin: 0; color: var(--of-muted); line-height: 1.4; }
.memory-read-log { display: grid; gap: 2px; max-height: 150px; overflow: auto; padding: 5px 7px; border: 1px solid var(--of-border); border-radius: 4px; background: var(--of-input); font-family: var(--of-mono); font-size: 11px; }
.memory-read-log-entry { display: flex; gap: 8px; min-width: 0; line-height: 1.45; }
.memory-read-log-state { flex: 0 0 auto; color: var(--of-muted); }
.memory-read-log-state.done { color: var(--of-ok); }
.memory-read-log-state.failed { color: var(--of-danger); }
.memory-read-log-range { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--of-text); }
.memory-read-error { margin: 0; color: var(--of-danger); overflow-wrap: anywhere; }
.memory-read-dialog-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 16px; background: rgb(0 0 0 / 42%); }
.memory-read-dialog { width: min(420px, 100%); display: grid; gap: 10px; padding: 16px; border: 1px solid var(--of-border); border-radius: 7px; background: var(--of-surface); box-shadow: 0 16px 48px rgb(0 0 0 / 30%); }
.memory-read-dialog header { display: flex; align-items: center; justify-content: space-between; }
.memory-read-dialog h4 { margin: 0; color: var(--of-text); font-size: 14px; }
.memory-read-dialog .icon-button { display: inline-grid; place-items: center; width: 28px; height: 28px; padding: 0; border: 1px solid var(--of-border); border-radius: 4px; background: transparent; color: var(--of-muted); }
.memory-read-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
</style>
