<template>
  <details class="serial-automation" data-testid="serial-automation">
    <summary>{{ tr('协议与自动应答', 'Protocol and auto-reply') }} · {{ profileName }} · {{ modelValue.rules.length }} {{ tr('条规则', 'rules') }}</summary>
    <p class="hint">{{ locked ? tr('当前为后台共享配置；关闭连接后才能修改。', 'Shared backend configuration; close the connection before editing.') : tr('配置在打开串口时生效。应答只按下方规则执行一次。', 'Applied when opening the port. Replies run once using the rules below.') }}</p>
    <div class="automation-actions">
      <label>{{ tr('导入 Profile', 'Import Profile') }} <input data-testid="serial-profile-file" type="file" accept=".json" :disabled="locked" @change="importFile($event, 'profile')"></label>
      <button type="button" :disabled="locked || !modelValue.profile" @click="update(null, modelValue.rules)">{{ tr('清除 Profile', 'Clear Profile') }}</button>
      <label>{{ tr('导入应答规则', 'Import reply rules') }} <input data-testid="serial-rules-file" type="file" accept=".json" :disabled="locked" @change="importFile($event, 'rules')"></label>
    </div>
    <div class="rule-editor">
      <select v-model="matchType" :disabled="locked" :aria-label="tr('匹配类型', 'Match type')">
        <option value="match_hex">HEX</option><option value="match_contains">{{ tr('包含文本', 'Contains text') }}</option><option value="match_regex">{{ tr('正则', 'Regex') }}</option>
      </select>
      <input v-model="match" data-testid="serial-rule-match" :disabled="locked" :placeholder="tr('匹配内容', 'Match content')" maxlength="4096">
      <select v-model="replyType" :disabled="locked" :aria-label="tr('回复类型', 'Reply type')"><option value="reply_hex">HEX</option><option value="reply_ascii">UTF-8</option></select>
      <input v-model="reply" data-testid="serial-rule-reply" :disabled="locked" :placeholder="tr('回复内容', 'Reply content')" maxlength="16384">
      <label>{{ tr('延时（秒）', 'Delay (s)') }} <input v-model.number="delay" type="number" min="0" max="3600" step="0.01" :disabled="locked"></label>
      <button type="button" data-testid="serial-rule-add" :disabled="locked" @click="addRule">{{ tr('添加规则', 'Add rule') }}</button>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <ul class="rule-list">
      <li v-for="(rule, index) in modelValue.rules" :key="index">
        <code>{{ describeRule(rule) }}</code>
        <button type="button" :disabled="locked" :aria-label="tr(`删除规则 ${index + 1}`, `Remove rule ${index + 1}`)" @click="removeRule(index)">{{ tr('删除', 'Remove') }}</button>
      </li>
    </ul>
    <div v-if="modelValue.profile" class="decoded" data-testid="serial-decoded">
      <strong>{{ tr('最新解析帧', 'Latest parsed frame') }} · {{ port || '--' }}</strong>
      <p class="hint">{{ tr('约每秒刷新，只显示最新帧，可能跳过中间帧。', 'Refreshes about once per second; intermediate frames may be skipped.') }}</p>
      <template v-if="frame">
        <p>#{{ frame.seq }} · {{ new Date(frame.timestamp * 1000).toLocaleTimeString() }} · {{ frame.size }} B · CRC {{ frame.crc_valid === null ? '--' : frame.crc_valid ? 'OK' : 'FAIL' }}</p>
        <table><thead><tr><th>{{ tr('字段', 'Field') }}</th><th>{{ tr('值', 'Value') }}</th><th>{{ tr('原始值', 'Raw value') }}</th><th>{{ tr('单位', 'Unit') }}</th></tr></thead>
          <tbody><tr v-for="(field, name) in frame.fields" :key="name"><td>{{ name }}</td><td>{{ field.value }}</td><td>{{ field.raw }}</td><td>{{ field.unit || '' }}</td></tr></tbody>
        </table>
        <code class="frame-preview">{{ frame.hex_preview }}{{ frame.truncated ? '…' : '' }}</code>
      </template>
      <p v-else>{{ tr('此端口尚无解析帧', 'No parsed frame for this port yet') }}</p>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { tr } from '../../composables/useLanguage'
export interface SerialAutomation { profile: Record<string, unknown> | null; rules: Array<Record<string, unknown>> }
export interface SerialParsedFrame {
  timestamp: number; seq: number; size: number; hex_preview: string; truncated: boolean; crc_valid: boolean | null
  fields: Record<string, { value: unknown; raw: unknown; unit?: string }>
}
const props = defineProps<{ modelValue: SerialAutomation; locked: boolean; port: string; frame?: SerialParsedFrame }>()
const emit = defineEmits<{ 'update:modelValue': [value: SerialAutomation] }>()
const error = ref('')
const matchType = ref('match_contains'), replyType = ref('reply_hex')
const match = ref(''), reply = ref(''), delay = ref(0)
const profileName = computed(() => String(props.modelValue.profile?.name || tr('无 Profile', 'No Profile')))
function update(profile: SerialAutomation['profile'], rules: SerialAutomation['rules']) {
  if (props.locked) return
  const next = { profile, rules }
  // Backend validation is authoritative; reject oversized local drafts early.
  if (new TextEncoder().encode(JSON.stringify(next)).length > 16384 || rules.length > 64) {
    error.value = tr('配置最多 16 KiB、64 条规则。', 'Configuration allows at most 16 KiB and 64 rules.')
    return
  }
  error.value = ''
  emit('update:modelValue', next)
}
async function importFile(event: Event, kind: 'profile' | 'rules') {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || props.locked) return
  try {
    if (file.size > 16384) throw new Error(tr('文件超过 16 KiB。', 'File exceeds 16 KiB.'))
    const data: unknown = JSON.parse(await file.text())
    if (props.locked) return // backend may have started while the file was read
    if (kind === 'profile') {
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error(tr('Profile 必须是 JSON 对象。', 'Profile must be a JSON object.'))
      update(data as Record<string, unknown>, props.modelValue.rules)
    } else {
      if (!Array.isArray(data) || data.some(item => !item || typeof item !== 'object' || Array.isArray(item))) throw new Error(tr('规则必须是 JSON 对象数组。', 'Rules must be a JSON object array.'))
      update(props.modelValue.profile, data)
    }
  } catch (caught) { error.value = caught instanceof Error ? caught.message : String(caught) }
}
function addRule() {
  if (!match.value || !reply.value || !Number.isFinite(delay.value) || delay.value < 0 || delay.value > 3600) {
    error.value = tr('填写匹配和回复内容，延时须为 0–3600 秒。', 'Enter match and reply content; delay must be 0–3600 seconds.')
    return
  }
  update(props.modelValue.profile, [...props.modelValue.rules, { [matchType.value]: match.value, [replyType.value]: reply.value, delay: delay.value }])
}
function removeRule(index: number) { update(props.modelValue.profile, props.modelValue.rules.filter((_, i) => i !== index)) }
function describeRule(rule: Record<string, unknown>) {
  const match = ['match_hex', 'match_contains', 'match_regex'].filter(key => rule[key] != null).map(key => `${key.replace('match_', '')}: ${rule[key]}`).join(' / ')
  return `${match} → ${rule.reply_hex != null ? 'HEX: ' + rule.reply_hex : 'UTF-8: ' + rule.reply_ascii} (${rule.delay || 0}s)`
}
</script>

<style scoped>
.serial-automation { margin-top: 8px; border: 1px solid var(--border); border-radius: 5px; padding: 7px 10px; font-size: 12px; max-height: 42vh; overflow: auto; flex-shrink: 0; }
summary { cursor: pointer; }
.hint { color: var(--muted); margin: 8px 0; }
.automation-actions, .rule-editor, .rule-list li { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
input, select, button { background: var(--surface); color: inherit; border: 1px solid var(--border); border-radius: 4px; padding: 4px 6px; }
input[type=number] { width: 75px; } input[type=file] { max-width: 210px; } button:disabled { opacity: .45; }
.rule-list { margin: 8px 0; padding: 0; list-style: none; } .rule-list code { flex: 1; overflow-wrap: anywhere; }
.error { color: #f87171; } table { width: 100%; border-collapse: collapse; } th, td { text-align: left; border-bottom: 1px solid var(--border); padding: 4px 8px; }
.frame-preview { display: block; margin: 6px 0; overflow-wrap: anywhere; }
</style>
