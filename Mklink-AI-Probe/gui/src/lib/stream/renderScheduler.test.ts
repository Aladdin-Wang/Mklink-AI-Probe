import { describe, expect, it, vi } from 'vitest'
import { RenderScheduler, type RenderInvalidation } from './renderScheduler'

class FakeAnimationClock {
  now = 0
  hidden = false
  private nextId = 1
  private frames = new Map<number, FrameRequestCallback>()
  private visibilityListeners = new Set<() => void>()

  readonly requestAnimationFrame = (callback: FrameRequestCallback): number => {
    const id = this.nextId++
    this.frames.set(id, callback)
    return id
  }

  readonly cancelAnimationFrame = (id: number): void => {
    this.frames.delete(id)
  }

  readonly addVisibilityListener = (listener: () => void): void => {
    this.visibilityListeners.add(listener)
  }

  readonly removeVisibilityListener = (listener: () => void): void => {
    this.visibilityListeners.delete(listener)
  }

  step(milliseconds: number): void {
    this.now += milliseconds
    const pending = [...this.frames.values()]
    this.frames.clear()
    for (const callback of pending) callback(this.now)
  }

  setHidden(hidden: boolean): void {
    this.hidden = hidden
    for (const listener of this.visibilityListeners) listener()
  }

  dependencies() {
    return {
      now: () => this.now,
      requestAnimationFrame: this.requestAnimationFrame,
      cancelAnimationFrame: this.cancelAnimationFrame,
      isDocumentHidden: () => this.hidden,
      addVisibilityListener: this.addVisibilityListener,
      removeVisibilityListener: this.removeVisibilityListener,
    }
  }

  get pendingFrames(): number {
    return this.frames.size
  }
}

describe('RenderScheduler', () => {
  it('coalesces 100 invalidations inside one 30 FPS frame', () => {
    const clock = new FakeAnimationClock()
    const renders: ReadonlySet<RenderInvalidation>[] = []
    const scheduler = new RenderScheduler(reasons => renders.push(reasons), clock.dependencies())
    scheduler.start()

    const reasons: RenderInvalidation[] = ['data', 'hover', 'zoom', 'resize']
    for (let index = 0; index < 100; index += 1) {
      scheduler.invalidate(reasons[index % reasons.length])
    }

    expect(clock.pendingFrames).toBe(1)
    clock.step(32)
    expect(renders).toHaveLength(1)
    expect([...renders[0]].sort()).toEqual(['data', 'hover', 'resize', 'zoom'])
  })

  it('limits later renders to 30 FPS', () => {
    const clock = new FakeAnimationClock()
    const render = vi.fn()
    const scheduler = new RenderScheduler(render, clock.dependencies())
    scheduler.start()
    scheduler.invalidate('data')
    clock.step(1)
    scheduler.invalidate('data')
    clock.step(32)
    expect(render).toHaveBeenCalledTimes(1)
    clock.step(2)
    expect(render).toHaveBeenCalledTimes(2)
  })

  it('pauses rendering while hidden and renders once after visibility returns', () => {
    const clock = new FakeAnimationClock()
    const render = vi.fn()
    const collect = vi.fn()
    const scheduler = new RenderScheduler(render, clock.dependencies(), collect)
    scheduler.start()
    clock.setHidden(true)
    scheduler.invalidate('data')
    scheduler.invalidate('zoom')
    scheduler.recordCollection(25)
    clock.step(100)

    expect(render).not.toHaveBeenCalled()
    expect(collect).toHaveBeenCalledWith(25)
    expect(clock.pendingFrames).toBe(0)

    clock.setHidden(false)
    expect(clock.pendingFrames).toBe(1)
    clock.step(1)
    expect(render).toHaveBeenCalledTimes(1)
  })

  it('keeps start, stop, and dispose idempotent without stale callbacks', () => {
    const clock = new FakeAnimationClock()
    const render = vi.fn()
    const scheduler = new RenderScheduler(render, clock.dependencies())

    scheduler.start()
    scheduler.start()
    scheduler.invalidate('data')
    expect(clock.pendingFrames).toBe(1)
    scheduler.stop()
    scheduler.stop()
    expect(clock.pendingFrames).toBe(0)
    clock.step(100)
    expect(render).not.toHaveBeenCalled()

    scheduler.start()
    expect(clock.pendingFrames).toBe(1)
    scheduler.dispose()
    scheduler.dispose()
    expect(clock.pendingFrames).toBe(0)
    scheduler.invalidate('zoom')
    scheduler.start()
    clock.step(100)
    expect(render).not.toHaveBeenCalled()
  })
})
