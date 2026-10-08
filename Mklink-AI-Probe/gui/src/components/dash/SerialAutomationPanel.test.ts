import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Panel from './SerialAutomationPanel.vue'

const props = () => ({ modelValue: { profile: null, rules: [] }, locked: false, port: 'A' })
async function upload(wrapper: any, id: string, data: unknown, size = 100) {
  const input = wrapper.get(`[data-testid="${id}"]`)
  Object.defineProperty(input.element, 'files', { configurable: true, value: [{ size, text: async () => JSON.stringify(data) }] })
  await input.trigger('change'); await flushPromises()
}
describe('SerialAutomationPanel', () => {
  it('adds one rule draft without sending or opening a port', async () => {
    const wrapper = mount(Panel, { props: props() })
    await wrapper.get('[data-testid="serial-rule-match"]').setValue('Q')
    await wrapper.get('[data-testid="serial-rule-reply"]').setValue('52 0D 0A')
    await wrapper.get('[data-testid="serial-rule-add"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([{ profile: null, rules: [{ match_contains: 'Q', reply_hex: '52 0D 0A', delay: 0 }] }])
    wrapper.unmount()
  })
  it('imports Profile independently of embedded reply suggestions', async () => {
    const wrapper = mount(Panel, { props: props() })
    const profile = { name: 'Frame', version: '1', auto_reply: [{ match_contains: 'Q', reply_hex: '52' }] }
    await upload(wrapper, 'serial-profile-file', profile)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([{ profile, rules: [] }])
    wrapper.unmount()
  })
  it('rejects wrong shapes and oversized imports without changing the draft', async () => {
    const wrapper = mount(Panel, { props: props() })
    await upload(wrapper, 'serial-profile-file', [])
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    await upload(wrapper, 'serial-rules-file', {})
    await upload(wrapper, 'serial-rules-file', [], 16385)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })
  it('keeps running configuration read-only and escapes field and rule text', async () => {
    const wrapper = mount(Panel, { props: { ...props(), locked: true,
      modelValue: { profile: { name: 'P' }, rules: [{ match_contains: '<script>x</script>', reply_hex: '00' }] },
      frame: { seq: 8, timestamp: 1, size: 300, hex_preview: 'AA00', truncated: true, crc_valid: false,
        fields: { temperature: { value: '<script>x</script>', raw: 4, unit: 'C' } } } } })
    expect(wrapper.findAll('input,select,button').every(node => node.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.get('[data-testid="serial-decoded"]').text()).toContain('CRC FAIL')
    expect(wrapper.text()).toContain('<script>x</script>')
    expect(wrapper.find('script').exists()).toBe(false)
    await wrapper.setProps({ port: 'B', frame: undefined })
    expect(wrapper.get('[data-testid="serial-decoded"]').text()).toContain('B')
    expect(wrapper.get('[data-testid="serial-decoded"]').text()).not.toContain('temperature')
    wrapper.unmount()
  })
  it('discards file completion after the backend locks configuration', async () => {
    let resolve!: (text: string) => void
    const wrapper = mount(Panel, { props: props() })
    const input = wrapper.get('[data-testid="serial-profile-file"]')
    Object.defineProperty(input.element, 'files', { value: [{ size: 10, text: () => new Promise<string>(done => { resolve = done }) }] })
    await input.trigger('change'); await wrapper.setProps({ locked: true })
    resolve('{"name":"P"}'); await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.unmount()
  })
  it('rejects a 65th rule without truncating existing rules', async () => {
    const wrapper = mount(Panel, { props: { ...props(), modelValue: { profile: null, rules: Array.from({ length: 64 }, () => ({ match_contains: 'Q', reply_hex: '52' })) } } })
    await wrapper.get('[data-testid="serial-rule-match"]').setValue('Q')
    await wrapper.get('[data-testid="serial-rule-reply"]').setValue('52')
    await wrapper.get('[data-testid="serial-rule-add"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.findAll('.rule-list li')).toHaveLength(64)
    wrapper.unmount()
  })
})
