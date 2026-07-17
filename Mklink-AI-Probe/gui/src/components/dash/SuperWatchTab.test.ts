import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import SuperWatchTab from './SuperWatchTab.vue'
import SymbolVariablePanel from './SymbolVariablePanel.vue'
import WaveformViewer from './WaveformViewer.vue'

describe('SuperWatchTab', () => {
  it('uses a two-column workspace and passes waveform values to the variable directory', async () => {
    const wrapper = mount(SuperWatchTab, {
      props: { deviceConnected: true },
      global: {
        stubs: {
          SymbolVariablePanel: {
            name: 'SymbolVariablePanel',
            props: ['deviceConnected', 'latestValues'],
            template: '<aside class="variable-panel-stub" />',
          },
          WaveformViewer: {
            name: 'WaveformViewer',
            emits: ['latest-values'],
            props: ['mode', 'deviceConnected'],
            template: '<main class="waveform-stub" />',
          },
        },
      },
    })

    expect(wrapper.get('.superwatch-workspace').exists()).toBe(true)
    wrapper.findComponent(WaveformViewer).vm.$emit('latest-values', { gain: 1.25 })
    await nextTick()

    expect(wrapper.findComponent(SymbolVariablePanel).props('latestValues')).toEqual({ gain: 1.25 })
  })
})
