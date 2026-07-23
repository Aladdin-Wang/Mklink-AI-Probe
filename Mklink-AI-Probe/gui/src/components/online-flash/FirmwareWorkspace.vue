<script setup lang="ts">
import { computed, ref } from 'vue'
import type { FormattedHexRow } from '../../lib/hexPreview'
import type { ImageInspection } from '../../types/onlineFlash'

const props = defineProps<{ file: File | null; baseAddress: string; baseError: string; inspection: ImageInspection | null; rows: FormattedHexRow[]; paddingTop: number; paddingBottom: number; loading: boolean; error: string }>()
const emit = defineEmits<{ file: [file: File | null]; base: [value: string]; scroll: [top: number, height: number] }>()
const isBin = computed(() => props.file?.name.toLowerCase().endsWith('.bin') ?? false)
const fileInput = ref<HTMLInputElement | null>(null)
function openFile() { fileInput.value?.click() }
function fileChanged(event: Event) { emit('file', (event.target as HTMLInputElement).files?.[0] ?? null) }
function scrolled(event: Event) { const el = event.currentTarget as HTMLElement; emit('scroll', el.scrollTop, el.clientHeight) }
function address(value: number) { return `0x${value.toString(16).toUpperCase().padStart(8, '0')}` }
</script>

<template>
  <div class="firmware-toolbar">
    <label data-testid="firmware-trigger" class="file-button" role="button" tabindex="0" @keydown.enter.prevent="openFile" @keydown.space.prevent="openFile">选择 BIN / HEX<input ref="fileInput" class="visually-hidden" data-testid="firmware-input" type="file" accept=".bin,.hex" @change="fileChanged"></label>
    <span class="filename">{{ file?.name || '尚未选择固件' }}</span>
    <label v-if="isBin" class="base-field">基地址<input data-testid="bin-base" :value="baseAddress" placeholder="如 0x08000000" @input="emit('base', ($event.target as HTMLInputElement).value)"></label>
    <span v-if="loading" class="inspection-status">自动检查中…</span>
    <span v-else-if="inspection" class="inspection-status inspection-ok">已自动检查</span>
  </div>
  <p v-if="baseError" data-testid="base-error" class="error">{{ baseError }}</p><p v-if="error" class="error">{{ error }}</p>
  <div v-if="inspection" class="metadata"><span>{{ inspection.format.toUpperCase() }}</span><span>{{ inspection.size }} bytes</span><span>{{ address(inspection.start) }} — {{ address(inspection.end) }}</span><span>SHA-256 {{ inspection.sha256.slice(0, 12) }}…</span></div>
  <div class="hex-head"><span>地址</span><span>00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F</span><span>ASCII</span></div>
  <div class="hex-scroll" @scroll="scrolled">
    <div :style="{ height: `${paddingTop}px` }" />
    <div v-for="row in rows" :key="row.address" class="hex-row"><span>{{ row.address }}</span><span class="cells"><i v-for="(cell, index) in row.hex" :key="index" :class="{ gap: cell === '--' }">{{ cell }}</i></span><span>{{ row.ascii }}</span></div>
    <div :style="{ height: `${paddingBottom}px` }" />
    <div v-if="!inspection" class="empty">选择已安装器件与固件后将自动检查，预览按需加载，不会一次渲染整个文件。</div>
  </div>
</template>

<style scoped>
.firmware-toolbar{display:flex;align-items:center;gap:8px;padding:10px;border-bottom:1px solid var(--of-border)}.file-button{padding:7px 10px;border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text);font-size:11px}.visually-hidden{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.file-button:focus-visible{outline:2px solid var(--of-accent);outline-offset:2px}.filename{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--of-muted);font-size:11px}.inspection-status{margin-left:auto;color:var(--of-warn);font-size:10px;white-space:nowrap}.inspection-ok{color:var(--of-ok)}.base-field{margin-left:auto;display:flex;align-items:center;gap:5px;color:var(--of-muted);font-size:10px}.base-field+.inspection-status{margin-left:0}.base-field input{width:92px;padding:6px;border:1px solid var(--of-border);border-radius:4px;background:var(--of-input);color:var(--of-text);font-family:var(--of-mono)}.error{margin:5px 10px;color:var(--of-danger);font-size:11px}.metadata{display:flex;gap:14px;padding:7px 10px;border-bottom:1px solid var(--of-border);color:var(--of-muted);font-size:10px}.hex-head,.hex-row{display:grid;grid-template-columns:78px minmax(430px,1fr) 136px;align-items:center;white-space:pre}.hex-head{padding:6px 10px;background:#191e24;color:var(--of-muted);font:10px var(--of-mono)}.hex-scroll{min-height:0;height:auto;flex:1;overflow:auto;text-align:left;background:#111419;font:11px/20px var(--of-mono)}.hex-row{height:20px;padding:0 10px;color:#c9d1d9}.cells{display:grid;grid-template-columns:repeat(16,2ch);column-gap:1ch}.cells i{font-style:normal;color:#d8dee9}.cells i.gap{color:#59616c}.empty{padding:50px 20px;text-align:center;color:var(--of-muted)}
</style>
