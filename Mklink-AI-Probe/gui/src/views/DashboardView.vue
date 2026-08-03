<template>
  <div class="dash-root">
    <div
      class="card"
      :class="{
        'card-full': tab === 'rtt' || tab === 'superwatch' || tab === 'serial',
        'card-rtt': tab === 'rtt',
        'card-systemview': tab === 'systemview',
      }"
    >
      <div class="dashboard-nav-row">
        <div class="tabs-bar">
          <button :class="['tab-btn', { active: tab === 'rtt' }]" @click="tab = 'rtt'">RTT View</button>
          <button :class="['tab-btn', { active: tab === 'superwatch' }]" @click="tab = 'superwatch'">SuperWatch</button>
          <button :class="['tab-btn', { active: tab === 'hardfault' }]" @click="tab = 'hardfault'">HardFault</button>
          <button :class="['tab-btn', { active: tab === 'memory' }]" @click="tab = 'memory'">Memory</button>
          <button :class="['tab-btn', { active: tab === 'debug' }]" @click="tab = 'debug'">{{ tr('调试控制', 'Debug Control') }}</button>
          <button :class="['tab-btn', { active: tab === 'serial' }]" @click="tab = 'serial'">{{ tr('串口助手', 'Serial Assistant') }}</button>
          <button :class="['tab-btn', { active: tab === 'modbus' }]" @click="tab = 'modbus'">Modbus</button>
          <button :class="['tab-btn', { active: tab === 'systemview' }]" @click="tab = 'systemview'">RTOS Trace</button>
          <button :class="['tab-btn', { active: tab === 'symbols' }]" @click="tab = 'symbols'">{{ tr('符号表', 'Symbols') }}</button>
        </div>
        <div class="title-right">
          <span v-if="bridgeOwner" class="resource-status-inline">
            <span class="status-dot" :class="bridgeOwner.startsWith('ai:') ? 'dot-ai' : 'dot-user'"></span>
            <span v-if="bridgeOwner.startsWith('ai:')">{{ tr('AI 正在使用设备', 'AI is using the device') }}</span>
            <span v-else>{{ bridgeOwnerLabel }}</span>
          </span>
          <span v-if="deviceStatus.connected" class="device-summary" :title="deviceStatus.port || ''">
            {{ deviceStatus.mcu || tr('已连接', 'Connected') }}
          </span>
          <button
            type="button"
            class="device-quick-action"
            :class="{ connected: deviceStatus.connected }"
            :disabled="connecting || disconnecting"
            :title="deviceStatus.connected ? tr('断开 MKLink 设备', 'Disconnect MKLink device') : tr('使用上次成功配置连接', 'Connect with the last successful settings')"
            data-testid="device-quick-action"
            @click="deviceStatus.connected ? quickDisconnect() : quickConnect()"
          >
            <LoaderCircle v-if="connecting || disconnecting" class="spinning" :size="14" aria-hidden="true" />
            <Unplug v-else-if="deviceStatus.connected" :size="14" aria-hidden="true" />
            <Usb v-else :size="14" aria-hidden="true" />
            <span>{{ connecting ? tr('连接中', 'Connecting') : disconnecting ? tr('断开中', 'Disconnecting') : deviceStatus.connected ? tr('断开', 'Disconnect') : tr('连接设备', 'Connect Device') }}</span>
          </button>
          <div v-if="connectionError" class="device-quick-error" role="alert">
            <span>{{ connectionError }}</span>
            <button type="button" @click="goConnect">{{ tr('打开配置', 'Open Config') }}</button>
          </div>
        </div>
      </div>

      <RttViewTab v-show="tab === 'rtt'" :device-connected="deviceStatus.connected" />

      <!-- 调试控制 -->
      <div v-if="tab === 'debug'">
        <SetupHint
          v-if="!deviceStatus.connected"
          kind="device"
          :message="tr('调试控制需要 MKLink 设备连接。', 'Debug Control requires an MKLink device connection.')"
          :primary-label="tr('连接设备', 'Connect Device')"
          :busy="connecting"
          @primary="quickConnect"
        />
        <template v-else>
          <div class="btn-group">
            <button class="btn" @click="doHalt">{{ tr('暂停 CPU', 'Halt CPU') }}</button>
            <button class="btn" @click="doResume">{{ tr('恢复 CPU', 'Resume CPU') }}</button>
            <button class="btn" @click="doReset">{{ tr('复位', 'Reset') }}</button>
            <button class="btn btn-danger" @click="doErase">{{ tr('整片擦除', 'Chip Erase') }}</button>
          </div>
        </template>
      </div>

      <HardFaultTab v-if="tab === 'hardfault'" :device-connected="deviceStatus.connected" :symbol-loaded="deviceStatus.axf?.loaded === true" />
      <MemoryTab v-if="tab === 'memory'" :device-connected="deviceStatus.connected" />
      <SuperWatchTab v-if="tab === 'superwatch'" :device-connected="deviceStatus.connected" :symbol-loaded="deviceStatus.axf?.loaded === true" :symbol-error="deviceStatus.axf?.error" />
      <SerialMonitorTab v-show="tab === 'serial'" />
      <ModbusTab v-show="tab === 'modbus'" />
      <SystemViewTab v-show="tab === 'systemview'" :device-connected="deviceStatus.connected" />
      <SymbolsTab v-if="tab === 'symbols'" :device-connected="deviceStatus.connected" :symbol-loaded="deviceStatus.axf?.loaded === true" :symbol-error="deviceStatus.axf?.error" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { LoaderCircle, Unplug, Usb } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { useMklinkApi } from '../composables/useMklinkApi'
import { useToast } from '../composables/useToast'
import { useResourceStatus } from '../composables/useResourceStatus'
import { useDashboardSetup } from '../composables/useDashboardSetup'
import RttViewTab from '../components/dash/RttViewTab.vue'
import HardFaultTab from '../components/dash/HardFaultTab.vue'
import SymbolsTab from '../components/dash/SymbolsTab.vue'
import MemoryTab from '../components/dash/MemoryTab.vue'
import SuperWatchTab from '../components/dash/SuperWatchTab.vue'
import SerialMonitorTab from '../components/dash/SerialMonitorTab.vue'
import ModbusTab from '../components/dash/ModbusTab.vue'
import SystemViewTab from '../components/dash/SystemViewTab.vue'
import SetupHint from '../components/dash/SetupHint.vue'
import { tr } from '../composables/useLanguage'

const route = useRoute()
const router = useRouter()
const {
  deviceStatus,
  resetDevice,
  eraseDevice,
  haltDevice,
  resumeDevice,
} = useMklinkApi()
const toast = useToast()
const {
  connecting,
  disconnecting,
  connectionError,
  quickConnect,
  quickDisconnect,
} = useDashboardSetup()
const { refresh: refreshResource, getBridgeOwner } = useResourceStatus()
const dashboardTabs = new Set(['rtt', 'superwatch', 'memory', 'symbols', 'hardfault', 'serial', 'modbus', 'systemview'])
const routeTab = Array.isArray(route.query.tab) ? route.query.tab[0] : route.query.tab
const tab = ref(typeof routeTab === 'string' && dashboardTabs.has(routeTab) ? routeTab : 'rtt')

const bridgeOwner = computed(() => getBridgeOwner())
const bridgeOwnerLabel = computed(() => {
  const owner = bridgeOwner.value
  if (!owner) return ''
  const dashNames: Record<string, string> = {
    'user:dashboard:rtt': 'RTT View',
    'user:dashboard:superwatch': 'SuperWatch',
    'user:dashboard:vofa': 'VOFA+',
    'user:dashboard:systemview': 'RTOS Trace',
  }
  return dashNames[owner] || owner
})

// 周期性刷新资源状态
refreshResource()
setInterval(refreshResource, 3000)

function goConnect() {
  router.push({ name: 'config' })
}

async function doReset() {
  if (!confirm(tr('确定要复位 CPU？', 'Reset the CPU?'))) return
  try { await resetDevice(); toast.success(tr('已复位', 'CPU reset')) } catch (e: any) { toast.error(e.message) }
}
async function doErase() {
  if (!confirm(tr('确定要整片擦除？此操作不可撤销。', 'Erase the entire chip? This cannot be undone.'))) return
  try { await eraseDevice(); toast.success(tr('整片擦除完成', 'Chip erase complete')) } catch (e: any) { toast.error(e.message) }
}
async function doHalt() {
  if (!confirm(tr('确定要暂停 CPU？', 'Halt the CPU?'))) return
  try { await haltDevice(); toast.info(tr('CPU 已暂停', 'CPU halted')) } catch (e: any) { toast.error(e.message) }
}
async function doResume() { try { await resumeDevice(); toast.success(tr('CPU 已恢复', 'CPU resumed')) } catch (e: any) { toast.error(e.message) } }
</script>

<style scoped>
.dash-root {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.card-full {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding-bottom: 0;
  overflow: hidden;
  min-height: 0;
}
.card-full :deep(.waveform-viewer) {
  flex: 1;
  min-height: 0;
}
.card-full :deep(.rtt-view-tab) {
  flex: 1;
  min-height: 0;
  min-width: 0;
}
.card-rtt {
  padding-bottom: 16px;
}
.card-systemview {
  flex: 1 1 auto;
  min-height: 0;
  max-height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-gutter: stable;
  padding-bottom: 16px;
}
.card-systemview :deep(.sv-tab) {
  height: auto;
  min-height: 0;
}
.dashboard-nav-row {
  display: flex;
  align-items: stretch;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.card-full :deep(.serial-assistant) {
  flex: 1;
  min-height: 0;
  min-width: 0;
}
.dashboard-nav-row .tabs-bar {
  flex: 1;
  min-width: 0;
  margin-bottom: 0;
  border-bottom: 0;
}
.title-right {
  position: relative;
  flex: 0 0 auto;
  display: flex; align-items: center; gap: 8px;
  padding: 0 8px;
}
.resource-status-inline {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--muted);
}
.device-summary {
  max-width: 120px;
  overflow: hidden;
  color: var(--muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.device-quick-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 30px;
  padding: 4px 8px;
  border: 1px solid var(--accent-border);
  border-radius: 4px;
  background: var(--accent-bg);
  color: var(--accent);
  cursor: pointer;
  font-size: 12px;
  white-space: nowrap;
}
.device-quick-action.connected { border-color: var(--border); background: transparent; color: var(--muted); }
.device-quick-action:disabled { cursor: wait; opacity: 0.65; }
.device-quick-error {
  position: absolute;
  z-index: 20;
  top: calc(100% + 6px);
  right: 8px;
  display: grid;
  gap: 6px;
  width: min(300px, calc(100vw - 24px));
  padding: 9px;
  border: 1px solid var(--danger);
  border-radius: 4px;
  background: var(--surface);
  color: var(--danger);
  font-size: 12px;
}
.device-quick-error button { justify-self: end; border: 0; background: transparent; color: var(--accent); cursor: pointer; }
.spinning { animation: device-spin 0.8s linear infinite; }
@keyframes device-spin { to { transform: rotate(360deg); } }
.status-dot {
  width: 8px; height: 8px; border-radius: 50%; display: inline-block;
}
.dot-user { background: var(--success); }
.dot-ai { background: var(--warn); }
.alert-warn { color: var(--warn); padding: 8px; border: 1px solid var(--border); border-radius: var(--radius); background: #f5f0e1; }
@media (max-width: 900px) {
  .dashboard-nav-row { flex-wrap: wrap; }
  .dashboard-nav-row .tabs-bar { flex-basis: 100%; }
  .title-right { width: 100%; justify-content: flex-end; padding: 6px 4px; border-top: 1px solid var(--border-subtle); }
}
@media (max-width: 520px) {
  .resource-status-inline { display: none; }
  .device-summary { max-width: 92px; }
}
</style>
