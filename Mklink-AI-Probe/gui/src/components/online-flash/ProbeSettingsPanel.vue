<script setup lang="ts">
import { RefreshCw } from '@lucide/vue'
import type { ProbeRecord } from '../../types/onlineFlash'
import { tr } from '../../composables/useLanguage'
import { useConfirmation } from '../../composables/useConfirmation'
const confirm = useConfirmation()

const voltageChoices = [1800, 3300, 5000] as const

const props = defineProps<{
  probes: ProbeRecord[]
  selectedId: string
  frequency: number
  connectMode: string
  resetMode: string
  resetVoltageMv: 1800 | 3300 | 5000
  busy: boolean
  error: string
}>()

const emit = defineEmits<{
  refresh: []
  'update:selectedId': [value: string]
  'update:frequency': [value: number]
  'update:connectMode': [value: string]
  'update:resetMode': [value: string]
  'update:resetVoltageMv': [value: 1800 | 3300 | 5000]
}>()

async function updateResetVoltage(value: 1800 | 3300 | 5000, input: HTMLInputElement): Promise<void> {
  if (value === 5000) {
    input.checked = false
    const previous = input.closest('.voltage-options')?.querySelector<HTMLInputElement>(`input[value="${props.resetVoltageMv}"]`)
    if (previous) previous.checked = true
    if (!await confirm(tr(
    '5V 可能永久损坏不耐受 5V 的目标板。仅在确认当前目标硬件支持 5V 时选择。确定选择 5V？',
    '5 V may permanently damage a target that is not 5 V tolerant. Select it only after verifying the connected hardware. Select 5 V?',
    ))) return
  }
  if (props.busy) return
  emit('update:resetVoltageMv', value)
}
</script>

<template>
  <section class="panel-block">
    <div class="panel-title"><span>{{ tr('设备接入', 'Probe Connection') }}</span><button class="refresh-probes" :disabled="busy" @click="$emit('refresh')"><RefreshCw :size="13"/>{{ tr('刷新', 'Refresh') }}</button></div>
    <label><span class="probe-label">{{ tr('MKLink 探针', 'MKLink Probe') }}</span>
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
  <details class="connection-details">
    <summary><strong>{{ tr('连接设置', 'Connection settings') }}</strong><span>{{ frequency / 1000000 }} MHz · {{ connectMode === 'attach' ? tr('保持运行', 'Attach') : connectMode === 'halt' ? tr('连接后暂停', 'Halt') : tr('复位下连接', 'Under reset') }}<template v-if="resetMode !== 'default'"> · {{ resetMode === 'power-cycle' ? tr('断电复位', 'Power cycle') + ` ${resetVoltageMv / 1000}V` : resetMode === 'hardware' ? tr('硬件复位', 'Hardware reset') : tr('软件复位', 'Software reset') }}</template></span></summary>
  <section class="panel-block basic-settings">
    <label>{{ tr('SWD 频率', 'SWD Frequency') }}
      <select data-testid="frequency" :disabled="busy" :value="frequency" @change="$emit('update:frequency', Number(($event.target as HTMLSelectElement).value))">
        <option :value="1000000">1 MHz</option><option :value="2000000">2 MHz</option>
        <option :value="4000000">4 MHz</option><option :value="8000000">8 MHz</option>
        <option :value="10000000">10 MHz</option>
        <option :value="20000000">20 MHz</option>
        <option :value="30000000">30 MHz</option>
      </select>
    </label>
    <label>{{ tr('连接方式', 'Connection Mode') }}
      <select data-testid="connect-mode" :disabled="busy" :value="connectMode" @change="$emit('update:connectMode', ($event.target as HTMLSelectElement).value)">
        <option value="halt">{{ tr('连接后暂停', 'Halt after connect') }}</option><option value="attach">{{ tr('保持运行', 'Keep running') }}</option>
        <option value="under-reset">{{ tr('复位下连接', 'Connect under reset') }}</option>
      </select>
    </label>
    <label>{{ tr('复位方式', 'Reset Mode') }}
      <select data-testid="reset-mode" :disabled="busy" :value="resetMode" @change="$emit('update:resetMode', ($event.target as HTMLSelectElement).value)">
        <option value="default">{{ tr('默认', 'Default') }}</option><option value="hardware">{{ tr('硬件复位', 'Hardware reset') }}</option><option value="software">{{ tr('软件复位', 'Software reset') }}</option><option value="power-cycle">{{ tr('断电复位', 'Power-cycle reset') }}</option>
      </select>
    </label>
    <div v-if="resetMode === 'power-cycle'" class="voltage-setting" data-testid="reset-voltage-setting">
      <span>{{ tr('VCC 恢复电压（默认 3.3V）', 'VCC restore voltage (3.3 V default)') }}</span>
      <div class="voltage-options">
        <label v-for="choice in voltageChoices" :key="choice">
          <input :data-testid="`reset-voltage-${choice}`" type="radio" name="reset-voltage" :value="choice" :checked="resetVoltageMv === choice" @change="updateResetVoltage(choice, $event.target as HTMLInputElement)">
          {{ (choice / 1000).toFixed(choice === 5000 ? 0 : 1) }}V
        </label>
      </div>
      <p class="power-warning">{{ tr('执行断电复位时会关闭 VCC，等待 3 秒后按所选电压重新输出。', 'Power-cycle reset disables VCC, waits 3 seconds, then restores the selected voltage.') }}</p>
    </div>
  </section>
  </details>
</template>

<style scoped>
.panel-block{padding:14px;border-bottom:1px solid var(--of-border)}.panel-title{display:flex;align-items:center;justify-content:space-between}h3,.panel-title{margin:0 0 10px;font-size:13px;color:var(--of-text)}label{display:grid;gap:5px;margin:9px 0;color:var(--of-muted);font-size:11px}select,button{border:1px solid var(--of-border);border-radius:5px;background:var(--of-input);color:var(--of-text);padding:7px;font:inherit}button{padding:4px 9px}.hint,.error{font-size:11px}.hint{color:var(--of-muted)}.error{color:var(--of-danger)}.voltage-setting{display:grid;gap:7px;margin:10px 0;color:var(--of-muted);font-size:11px}.voltage-options{display:flex;gap:14px}.voltage-options label{display:flex;align-items:center;gap:5px;margin:0}.power-warning{margin:0;color:var(--of-warn);line-height:1.45}

.panel-block{padding:10px 12px}.panel-title{margin-bottom:6px}.panel-block>label{margin:5px 0}.refresh-probes{display:inline-flex;align-items:center;gap:5px;font-size:11px;cursor:pointer}.refresh-probes:hover:not(:disabled){border-color:var(--of-accent);color:var(--of-accent)}.basic-settings{display:grid;grid-template-columns:1fr 1fr;gap:6px 10px}.basic-settings h3{grid-column:1/-1;margin:0;font-size:12px}.basic-settings>label{min-width:0;margin:0;gap:4px}.basic-settings>label:last-of-type{grid-column:1/-1;display:grid;grid-template-columns:70px minmax(0,1fr);align-items:center}.basic-settings select{min-width:0;width:100%;height:30px;padding:4px 6px}.voltage-setting{grid-column:1/-1;margin:0}select:disabled,button:disabled{opacity:.5}

.probe-label{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.connection-details{border-bottom:1px solid var(--of-border)}.connection-details>summary{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 12px;cursor:pointer;list-style:none}.connection-details>summary strong{font-size:12px}.connection-details>summary strong:before{content:'▸';margin-right:6px;color:var(--of-muted)}.connection-details[open]>summary strong:before{content:'▾'}.connection-details>summary span{font-size:10px;color:var(--of-muted)}.connection-details .panel-block{border:0;padding-top:0}
</style>
