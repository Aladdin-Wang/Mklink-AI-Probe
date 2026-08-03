<script setup lang="ts">
import type { ProbeRecord } from '../../types/onlineFlash'
import { tr } from '../../composables/useLanguage'

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
    <div class="panel-title"><span>{{ tr('设备接入', 'Probe Connection') }}</span><button :disabled="busy" @click="$emit('refresh')">{{ tr('刷新', 'Refresh') }}</button></div>
    <label>{{ tr('MKLink 探针', 'MKLink Probe') }}
      <select data-testid="probe-select" :value="selectedId" :disabled="busy" @change="$emit('update:selectedId', ($event.target as HTMLSelectElement).value)">
        <option value="">{{ tr('请选择探针', 'Select a probe') }}</option>
        <option v-for="probe in probes" :key="probe.unique_id" :value="probe.unique_id">
          {{ probe.product_name }} · {{ probe.serial_number || probe.unique_id }}
        </option>
      </select>
    </label>
    <p v-if="!probes.length" class="hint">{{ tr('未发现精确匹配的 MKLink CMSIS-DAP 探针', 'No exact MKLink CMSIS-DAP probe found') }}</p>
    <p v-if="error" class="error">{{ error }}</p>
  </section>
  <section class="panel-block">
    <h3>{{ tr('基本设置', 'Basic Settings') }}</h3>
    <label>{{ tr('SWD 频率', 'SWD Frequency') }}
      <select data-testid="frequency" :value="frequency" @change="$emit('update:frequency', Number(($event.target as HTMLSelectElement).value))">
        <option :value="1000000">1 MHz</option><option :value="2000000">2 MHz</option>
        <option :value="4000000">4 MHz</option><option :value="8000000">8 MHz</option>
        <option :value="10000000">10 MHz</option>
      </select>
    </label>
    <label>{{ tr('连接方式', 'Connection Mode') }}
      <select data-testid="connect-mode" :value="connectMode" @change="$emit('update:connectMode', ($event.target as HTMLSelectElement).value)">
        <option value="halt">{{ tr('连接后暂停', 'Halt after connect') }}</option><option value="attach">{{ tr('保持运行', 'Keep running') }}</option>
        <option value="under-reset">{{ tr('复位下连接', 'Connect under reset') }}</option>
      </select>
    </label>
    <label>{{ tr('复位方式', 'Reset Mode') }}
      <select :value="resetMode" @change="$emit('update:resetMode', ($event.target as HTMLSelectElement).value)">
        <option value="default">{{ tr('默认', 'Default') }}</option><option value="hardware">{{ tr('硬件复位', 'Hardware reset') }}</option><option value="software">{{ tr('软件复位', 'Software reset') }}</option>
      </select>
    </label>
  </section>
</template>

<style scoped>
.panel-block{padding:14px;border-bottom:1px solid var(--of-border)}.panel-title{display:flex;align-items:center;justify-content:space-between}h3,.panel-title{margin:0 0 10px;font-size:13px;color:var(--of-text)}label{display:grid;gap:5px;margin:9px 0;color:var(--of-muted);font-size:11px}select,button{border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text);padding:7px;font:inherit}button{padding:4px 9px}.hint,.error{font-size:11px}.hint{color:var(--of-muted)}.error{color:var(--of-danger)}
</style>
