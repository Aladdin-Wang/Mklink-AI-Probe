<template>
  <div class="hardfault-tab">
    <SetupHint
      v-if="!deviceConnected"
      kind="device"
      :message="tr('HardFault 现场采集需要连接 MKLink 设备。', 'HardFault capture requires an MKLink device connection.')"
      :primary-label="tr('连接设备', 'Connect Device')"
      :busy="connecting"
      @primary="quickConnect"
    />
    <template v-else>
      <SetupHint
        v-if="!symbolLoaded"
        kind="info"
        :message="tr('不加载符号也可检查；加载 AXF / ELF 后可解析函数和源码位置。', 'Capture works without symbols; load AXF / ELF to resolve functions and source locations.')"
        :primary-label="hasSymbolSource ? tr('解析已选文件', 'Parse Selected File') : tr('加载符号', 'Load Symbols')"
        :busy="loadingSymbols"
        @primary="hasSymbolSource ? parseSelectedSymbols() : loadSymbolFile()"
      />
      <button class="btn btn-primary" @click="check" :disabled="loading">
        {{ loading ? tr('检查中...', 'Checking...') : tr('检查 HardFault', 'Check HardFault') }}
      </button>
      <div v-if="report" class="fault-report">
        <div v-if="!report.fault" class="alert alert-ok">{{ tr('无 HardFault', 'No HardFault') }}</div>
        <template v-else>
          <div v-if="report.fault_function || report.fault_location" class="fault-focus" data-testid="fault-focus">
            <span>{{ tr('故障位置', 'Fault Location') }}</span>
            <strong>{{ report.fault_function || tr('未知函数', 'Unknown function') }}</strong>
            <code v-if="report.fault_location">{{ report.fault_location }}</code>
          </div>
          <div class="fault-section">
            <h4>{{ tr('概要', 'Summary') }}</h4>
            <p class="fault-summary">{{ report.summary }}</p>
          </div>
          <div class="fault-section" v-if="report.cfsr_flags?.length">
            <h4>{{ tr('CFSR 标志', 'CFSR Flags') }}</h4>
            <div class="flag-list">
              <span v-for="f in report.cfsr_flags" :key="f" class="flag-badge">{{ f }}</span>
            </div>
          </div>
          <div class="fault-section" v-if="report.hfsr_flags?.length">
            <h4>{{ tr('HFSR 标志', 'HFSR Flags') }}</h4>
            <div class="flag-list">
              <span v-for="f in report.hfsr_flags" :key="f" class="flag-badge">{{ f }}</span>
            </div>
          </div>
          <div class="fault-section" v-if="report.stack_frame">
            <h4>{{ tr('栈帧', 'Stack Frame') }}</h4>
            <table class="desc-table">
              <tr v-for="(val, reg) in report.stack_frame" :key="reg">
                <th>{{ reg }}</th>
                <td>{{ typeof val === 'number' ? '0x' + val.toString(16).toUpperCase().padStart(8, '0') : val }}</td>
              </tr>
            </table>
          </div>
          <div class="fault-section" v-if="report.source_locations">
            <h4>{{ tr('源码位置', 'Source Locations') }}</h4>
            <div v-for="(loc, addr) in report.source_locations" :key="addr" class="source-loc">
              <span class="loc-addr">{{ addr }}</span>
              <span class="loc-file">{{ loc }}</span>
            </div>
          </div>
          <div class="fault-section" v-if="report.exception_stack">
            <h4>{{ tr('异常栈', 'Exception Stack') }}</h4>
            <p class="stack-evidence">
              {{ report.exception_stack.pointer.toUpperCase() }}
              {{ formatAddress(report.exception_stack.pointer_address) }}
              → {{ tr('栈帧', 'frame') }} {{ formatAddress(report.exception_stack.frame_address) }}
              <template v-if="report.exception_stack.exc_return !== null && report.exception_stack.exc_return !== undefined">
                · EXC_RETURN {{ formatAddress(report.exception_stack.exc_return) }}
              </template>
            </p>
          </div>
          <div class="fault-section" v-if="report.call_stack?.length">
            <h4>{{ tr('调用栈', 'Call Stack') }}</h4>
            <div class="call-stack-wrap">
              <table class="call-stack" data-testid="hardfault-call-stack">
                <thead><tr><th>#</th><th>{{ tr('地址', 'Address') }}</th><th>{{ tr('函数', 'Function') }}</th><th>{{ tr('位置', 'Location') }}</th><th>{{ tr('依据', 'Evidence') }}</th></tr></thead>
                <tbody>
                  <tr v-for="frame in report.call_stack" :key="`${frame.index}-${frame.address}`">
                    <td>{{ frame.index }}</td>
                    <td><code>{{ formatAddress(frame.address) }}</code></td>
                    <td>{{ frame.function || tr('未知函数', 'Unknown function') }}</td>
                    <td>{{ frame.location || '—' }}</td>
                    <td>{{ frameSource(frame.source) }} · {{ confidenceLabel(frame.confidence) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <button class="btn" @click="copyReport">{{ tr('复制报告', 'Copy Report') }}</button>
        </template>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useDeviceApi } from '../../composables/useDashboard'
import { useToast } from '../../composables/useToast'
import { useDashboardSetup } from '../../composables/useDashboardSetup'
import type { HardFaultDetail } from '../../types/mklink'
import { tr } from '../../composables/useLanguage'
import SetupHint from './SetupHint.vue'

const props = withDefaults(defineProps<{
  deviceConnected: boolean
  symbolLoaded?: boolean
}>(), {
  symbolLoaded: true,
})

const device = useDeviceApi()
const toast = useToast()
const {
  connecting,
  loadingSymbols,
  hasSymbolSource,
  quickConnect,
  loadSymbolFile,
  parseSelectedSymbols,
} = useDashboardSetup()
const loading = ref(false)
const report = ref<HardFaultDetail | null>(null)

function formatAddress(value: number): string {
  return `0x${value.toString(16).toUpperCase().padStart(8, '0')}`
}

function frameSource(source: string): string {
  if (source === 'exception_pc') return tr('异常 PC', 'Exception PC')
  if (source === 'exception_lr') return tr('异常 LR', 'Exception LR')
  return tr('栈扫描', 'Stack scan')
}

function confidenceLabel(confidence: string): string {
  if (confidence === 'exact') return tr('精确', 'Exact')
  if (confidence === 'high') return tr('高', 'High')
  return tr('推测', 'Inferred')
}

async function check() {
  loading.value = true
  try {
    report.value = await device.getHardfaultDetail()
  } catch (e: unknown) {
    toast.error(e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

function copyReport() {
  if (report.value) {
    navigator.clipboard.writeText(JSON.stringify(report.value, null, 2))
    toast.success(tr('已复制到剪贴板', 'Copied to clipboard'))
  }
}
</script>

<style scoped>
.hardfault-tab { display: flex; flex-direction: column; gap: 12px; }
.fault-report { margin-top: 8px; }
.fault-focus { display: grid; gap: 4px; margin-bottom: 14px; padding: 12px; border-left: 3px solid var(--danger); background: #f5e6e6; }
.fault-focus span { color: var(--dim); font-size: 11px; }
.fault-focus strong { color: var(--danger); font-size: 16px; }
.fault-focus code { overflow-wrap: anywhere; color: var(--fg); }
.fault-section { margin-bottom: 12px; }
.fault-section h4 { margin: 0 0 4px; font-size: 13px; color: var(--fg); }
.fault-summary { font-family: var(--font-mono); font-size: 13px; color: var(--warn); margin: 0; }
.flag-list { display: flex; flex-wrap: wrap; gap: 4px; }
.flag-badge {
  padding: 2px 8px; border-radius: 3px; font-size: 11px;
  background: #f5e6e6; color: var(--danger); border: 1px solid rgba(181, 51, 51, 0.3);
}
.source-loc {
  display: flex; gap: 8px; font-family: var(--font-mono); font-size: 12px;
  padding: 2px 0;
}
.loc-addr { color: var(--info); min-width: 80px; }
.loc-file { color: var(--dim); }
.stack-evidence { margin: 0; font-family: var(--font-mono); font-size: 12px; color: var(--dim); }
.call-stack-wrap { max-width: 100%; overflow-x: auto; }
.call-stack { width: 100%; border-collapse: collapse; font-size: 12px; }
.call-stack th, .call-stack td { padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
.call-stack th { color: var(--dim); font-weight: 600; }
.call-stack td:nth-child(4) { white-space: normal; overflow-wrap: anywhere; }
.alert-ok { color: var(--success); padding: 8px; border: 1px solid var(--success); border-radius: 4px; background: #e6f2ea; }
.alert-warn { color: var(--warn); padding: 8px; border: 1px solid var(--warn); border-radius: 4px; }
</style>
