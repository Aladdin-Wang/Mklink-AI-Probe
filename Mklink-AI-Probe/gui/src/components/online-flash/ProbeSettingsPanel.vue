<script setup lang="ts">
import type { ProbeRecord } from '../../types/onlineFlash'

defineProps<{
  probes: ProbeRecord[]
  selectedId: string
  frequency: number
  connectMode: string
  resetMode: string
  busy: boolean
  error: string
}>()

defineEmits<{
  refresh: []
  'update:selectedId': [value: string]
  'update:frequency': [value: number]
  'update:connectMode': [value: string]
  'update:resetMode': [value: string]
}>()
</script>

<template>
  <section class="panel-block">
    <div class="panel-title"><span>设备接入</span><button :disabled="busy" @click="$emit('refresh')">刷新</button></div>
    <label>MKLink 探针
      <select :value="selectedId" :disabled="busy" @change="$emit('update:selectedId', ($event.target as HTMLSelectElement).value)">
        <option value="">请选择探针</option>
        <option v-for="probe in probes" :key="probe.unique_id" :value="probe.unique_id">
          {{ probe.product_name }} · {{ probe.serial_number || probe.unique_id }}
        </option>
      </select>
    </label>
    <p v-if="!probes.length" class="hint">未发现精确匹配的 MKLink CMSIS-DAP 探针</p>
    <p v-if="error" class="error">{{ error }}</p>
  </section>
  <section class="panel-block">
    <h3>基本设置</h3>
    <label>SWD 频率
      <select data-testid="frequency" :value="frequency" @change="$emit('update:frequency', Number(($event.target as HTMLSelectElement).value))">
        <option :value="1000000">1 MHz</option><option :value="2000000">2 MHz</option>
        <option :value="4000000">4 MHz</option><option :value="8000000">8 MHz</option>
      </select>
    </label>
    <label>连接方式
      <select :value="connectMode" @change="$emit('update:connectMode', ($event.target as HTMLSelectElement).value)">
        <option value="halt">连接后暂停</option><option value="attach">保持运行</option>
        <option value="under-reset">复位下连接</option>
      </select>
    </label>
    <label>复位方式
      <select :value="resetMode" @change="$emit('update:resetMode', ($event.target as HTMLSelectElement).value)">
        <option value="default">默认</option><option value="hardware">硬件复位</option><option value="software">软件复位</option>
      </select>
    </label>
  </section>
</template>

<style scoped>
.panel-block{padding:14px;border-bottom:1px solid var(--of-border)}.panel-title{display:flex;align-items:center;justify-content:space-between}h3,.panel-title{margin:0 0 10px;font-size:13px;color:var(--of-text)}label{display:grid;gap:5px;margin:9px 0;color:var(--of-muted);font-size:11px}select,button{border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text);padding:7px;font:inherit}button{padding:4px 9px}.hint,.error{font-size:11px}.hint{color:var(--of-muted)}.error{color:var(--of-danger)}
</style>
