import { describe, expect, it, vi } from 'vitest'
import { SvTimeline } from './svTimeline'

describe('SvTimeline continuous filtering', () => {
  it('keeps normal periodic RTOS task gaps inside a live window', () => {
    const timeline = Object.create(SvTimeline.prototype)
    timeline.unit = 'us'
    timeline.tickHz = 72_000_000
    timeline.windowSize = 2_000_000

    const intervals = []
    for (let i = 0; i < 40; i++) {
      const start = i * 50_000
      intervals.push({ tid: 1, name: 'svfast', start, end: start + 180 })
      intervals.push({ tid: 2, name: 'afe', start: start + 700, end: start + 920 })
      if (i % 5 === 0) {
        intervals.push({ tid: 3, name: 'svmid', start: start + 1_400, end: start + 1_900 })
      }
    }

    expect(timeline._filterContinuous(intervals)).toHaveLength(intervals.length)
  })

  it('keeps task lane order stable when runtime percentages cross', () => {
    const timeline = Object.create(SvTimeline.prototype)
    timeline.PALETTE = ['#1', '#2', '#3']
    timeline.hidden = new Set()
    timeline.follow = false
    timeline.windowSize = 0
    timeline.viewStart = null
    timeline.viewEnd = null
    timeline._hadIntervals = false
    timeline._filterContinuous = intervals => intervals
    timeline._layout = () => {}
    timeline._draw = () => {}
    timeline._updateStatus = () => {}

    timeline.setData([
      { tid: 1, name: 'afe', start: 0, end: 60 },
      { tid: 2, name: 'svfast', start: 0, end: 40 },
    ])
    expect(timeline.tasks.map(task => task.name)).toEqual(['afe', 'svfast'])

    timeline.setData([
      { tid: 1, name: 'afe', start: 100, end: 130 },
      { tid: 2, name: 'svfast', start: 100, end: 190 },
    ])
    expect(timeline.tasks.map(task => task.name)).toEqual(['afe', 'svfast'])
  })

  it('keeps visible CPU status order stable when percentages cross', () => {
    const timeline = Object.create(SvTimeline.prototype)
    timeline.hidden = new Set()
    timeline.tasks = [
      { tid: 1, name: 'afe', color: '#1' },
      { tid: 2, name: 'svfast', color: '#2' },
    ]
    timeline.intervals = [
      { tid: 1, name: 'afe', start: 0, end: 30 },
      { tid: 2, name: 'svfast', start: 0, end: 70 },
    ]
    timeline.viewStart = 0
    timeline.viewEnd = 100
    timeline.roots = {
      legend: document.createElement('div'),
      vcpu: document.createElement('div'),
    }
    timeline.toggleTask = vi.fn()

    timeline._updateStatus()

    const labels = [...timeline.roots.legend.querySelectorAll('.sv-lg')]
      .map(el => el.textContent.trim().replace(/\s+\d+(\.\d+)?%$/, ''))
    expect(labels).toEqual(['afe', 'svfast'])
  })

  it('lets ordinary wheel events scroll the surrounding dashboard', () => {
    const timeline = Object.create(SvTimeline.prototype)

    expect(timeline._shouldZoomWheel({ ctrlKey: false, shiftKey: false })).toBe(false)
    expect(timeline._shouldZoomWheel({ ctrlKey: true, shiftKey: false })).toBe(true)
    expect(timeline._shouldZoomWheel({ ctrlKey: false, shiftKey: true })).toBe(true)
  })

  it('removes window listeners after destroy', () => {
    const timeline = Object.create(SvTimeline.prototype)
    const canvas = document.createElement('canvas')
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 240, height: 80, right: 240, bottom: 80, x: 0, y: 0, toJSON: () => ({}) })
    timeline.roots = { canvas }
    timeline.canvas = canvas
    timeline.W = 240
    timeline.H = 80
    timeline.dragging = false
    timeline._resize = vi.fn()
    timeline._draw = vi.fn()
    timeline._updateStatus = vi.fn()
    timeline._hitTest = vi.fn(() => null)
    timeline._showTip = vi.fn()
    timeline._hideTip = vi.fn()
    timeline.setFollowMode = vi.fn()

    timeline._bind()
    timeline.destroy()
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 20, clientY: 20 }))
    window.dispatchEvent(new MouseEvent('mouseup'))

    expect(timeline._draw).not.toHaveBeenCalled()
  })

  it('caps live follow animation draws at 30 FPS', () => {
    const callbacks = []
    vi.stubGlobal('requestAnimationFrame', vi.fn(callback => {
      callbacks.push(callback)
      return callbacks.length
    }))
    const timeline = Object.create(SvTimeline.prototype)
    Object.assign(timeline, {
      follow: true,
      windowSize: 100,
      followEase: 0.22,
      _followRaf: 0,
      _lastFollowRender: Number.NEGATIVE_INFINITY,
      tMin: 0,
      tMax: 1_000,
      viewStart: 0,
      viewEnd: 100,
      _draw: vi.fn(),
      _updateStatus: vi.fn(),
    })

    timeline._scheduleFollow()
    callbacks.shift()(0)
    callbacks.shift()(8)
    callbacks.shift()(34)

    expect(timeline._draw).toHaveBeenCalledTimes(2)
    vi.unstubAllGlobals()
  })

  it('shares one 30 FPS budget between live data and follow animation', () => {
    const callbacks = []
    vi.stubGlobal('requestAnimationFrame', vi.fn(callback => {
      callbacks.push(callback)
      return callbacks.length
    }))
    const timeline = Object.create(SvTimeline.prototype)
    Object.assign(timeline, {
      follow: true,
      windowSize: 100,
      followEase: 0.22,
      _followRaf: 0,
      _lastLiveRender: Number.NEGATIVE_INFINITY,
      tMin: 0,
      tMax: 1_000,
      viewStart: 0,
      viewEnd: 100,
      _draw: vi.fn(),
      _updateStatus: vi.fn(),
    })

    timeline._drawLive(0)
    timeline._scheduleFollow()
    callbacks.shift()(8)

    expect(timeline._draw).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
  })

  it('cancels follow rendering while paused and resumes without changing follow mode', () => {
    const timeline = Object.create(SvTimeline.prototype)
    Object.assign(timeline, {
      follow: true,
      windowSize: 100,
      _followRaf: 7,
      _lastLiveRender: 0,
      _draw: vi.fn(),
      _updateStatus: vi.fn(),
      _scheduleFollow: vi.fn(),
      _layout: vi.fn(),
    })
    const cancel = vi.fn()
    vi.stubGlobal('cancelAnimationFrame', cancel)

    timeline.pauseRendering()
    expect(cancel).toHaveBeenCalledWith(7)
    expect(timeline._drawLive(100)).toBe(false)
    expect(timeline.follow).toBe(true)

    timeline.resumeRendering()
    expect(timeline._layout).toHaveBeenCalledOnce()
    expect(timeline._draw).toHaveBeenCalledOnce()
    expect(timeline._scheduleFollow).toHaveBeenCalledOnce()
    expect(timeline.follow).toBe(true)
    vi.unstubAllGlobals()
  })

  it('does not draw while an initially paused timeline is constructed or resized', () => {
    const canvas = document.createElement('canvas')
    canvas.width = 321
    canvas.height = 123
    const context = new Proxy({
      setTransform: vi.fn(),
      clearRect: vi.fn(),
      measureText: vi.fn(() => ({ width: 0 })),
    }, {
      get(target, property) {
        if (!(property in target)) target[property] = vi.fn()
        return target[property]
      },
    })
    canvas.getContext = vi.fn(() => context)
    const timeline = new SvTimeline(
      { canvas },
      {
        intervals: [],
        follow: true,
        windowSize: 100,
        renderPaused: true,
      },
    )

    window.dispatchEvent(new Event('resize'))
    timeline.setData([{ tid: 1, name: 'main', start: 0, end: 10 }])

    expect(context.clearRect).not.toHaveBeenCalled()
    expect(canvas.width).toBe(321)
    expect(canvas.height).toBe(123)
    timeline.destroy()
  })
})
