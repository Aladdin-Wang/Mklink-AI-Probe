<script setup lang="ts">
import type { ImageSegment, SectorRecord } from '../../types/onlineFlash'
import { tr } from '../../composables/useLanguage'
defineProps<{ segments: ImageSegment[]; sectors: SectorRecord[]; selectedAddresses: number[]; inspectionReady: boolean; geometryReliable: boolean; canErase: boolean }>()
defineEmits<{ chipErase: []; selectedErase: []; rangeErase: []; selectAll: []; clearSelection: []; toggleSector: [address: number] }>()
const hex = (value: number) => `0x${value.toString(16).toUpperCase().padStart(8, '0')}`
</script>
<template>
  <div class="map-summary"><h3>{{ tr('闪存映射', 'Flash Map') }}</h3><div v-if="segments.length" v-for="segment in segments" :key="segment.start" class="region"><strong>{{ tr('镜像范围', 'Image Range') }}</strong><span>{{ hex(segment.start) }}</span><span>{{ hex(segment.end) }} · {{ segment.end - segment.start }} B</span></div><p v-else>{{ tr('等待服务端固件检查结果', 'Waiting for firmware inspection') }}</p></div>
  <div class="sector-panel">
    <div class="sector-title">
      <h3>{{ tr('扇区', 'Sectors') }}</h3>
      <span v-if="inspectionReady" class="badge">{{ geometryReliable ? tr('FLM 已验证', 'FLM verified') : tr('几何未验证', 'Geometry unverified') }}</span>
    </div>
    <p v-if="inspectionReady && !geometryReliable" class="warning">{{ tr('扇区几何信息不可验证，已禁用选择与普通烧录擦除。', 'Sector geometry could not be verified. Selection and normal flash erase are disabled.') }}</p>
    <div class="sector-actions"><button data-testid="select-all-sectors" :disabled="!geometryReliable" @click="$emit('selectAll')">{{ tr('全选', 'Select All') }}</button><button :disabled="!geometryReliable" @click="$emit('clearSelection')">{{ tr('清空', 'Clear') }}</button></div>
    <div v-if="geometryReliable" class="sector-list"><label v-for="sector in sectors" :key="sector.address" class="sector-row"><input type="checkbox" :checked="selectedAddresses.includes(sector.address)" @change="$emit('toggleSector', sector.address)"><span>{{ hex(sector.address) }}</span><span>{{ sector.size }} B</span></label></div>
    <div v-else class="sector-empty">{{ inspectionReady ? tr('服务端未提供可靠扇区表', 'No reliable sector table is available') : tr('加载固件后显示扇区表', 'Load firmware to display sectors') }}</div>
    <button :disabled="!geometryReliable || !canErase || !selectedAddresses.length" @click="$emit('selectedErase')">{{ tr('擦除所选', 'Erase Selected') }}</button><button data-testid="range-erase" :disabled="!geometryReliable || !canErase" @click="$emit('rangeErase')">{{ tr('范围擦除', 'Erase Range') }}</button><button data-testid="chip-erase" :disabled="!canErase" class="danger" @click="$emit('chipErase')">{{ tr('全片擦除', 'Chip Erase') }}</button>
  </div>
</template>
<style scoped>
.map-summary,.sector-panel{padding:14px;border-bottom:1px solid var(--of-border)}h3{margin:0;font-size:13px}.region{display:grid;gap:4px;margin-top:10px;padding:10px;border-left:3px solid var(--of-accent);background:var(--of-input);font:10px var(--of-mono)}p{color:var(--of-muted);font-size:11px}.sector-title,.sector-actions{display:flex;justify-content:space-between;gap:6px}.badge{font-size:9px;color:var(--of-warn)}.warning{color:var(--of-warn)}.sector-list{max-height:180px;margin:8px 0;overflow:auto;border:1px solid var(--of-border)}.sector-row{display:grid;grid-template-columns:18px 1fr auto;gap:6px;align-items:center;padding:5px 7px;border-bottom:1px solid var(--of-border);font:10px var(--of-mono)}.sector-row:last-child{border-bottom:0}.sector-empty{height:110px;display:grid;place-items:center;margin:8px 0;border:1px dashed var(--of-border);color:var(--of-muted);font-size:10px}button{margin:3px;padding:6px 8px;border:1px solid var(--of-border);border-radius:4px;background:var(--of-input);color:var(--of-text)}button.danger{color:var(--of-danger)}button:disabled{opacity:.45}
</style>
