export type RenderInvalidation = 'data' | 'hover' | 'zoom' | 'resize'

export interface RenderSchedulerDependencies {
  readonly now: () => number
  readonly requestAnimationFrame: (callback: FrameRequestCallback) => number
  readonly cancelAnimationFrame: (id: number) => void
  readonly isDocumentHidden: () => boolean
  readonly addVisibilityListener: (listener: () => void) => void
  readonly removeVisibilityListener: (listener: () => void) => void
}

const FRAME_INTERVAL_MS = 1000 / 30

function browserDependencies(): RenderSchedulerDependencies {
  return {
    now: () => performance.now(),
    requestAnimationFrame: callback => requestAnimationFrame(callback),
    cancelAnimationFrame: id => cancelAnimationFrame(id),
    isDocumentHidden: () => document.hidden,
    addVisibilityListener: listener => document.addEventListener('visibilitychange', listener),
    removeVisibilityListener: listener => document.removeEventListener('visibilitychange', listener),
  }
}

/** Coalesces all plot invalidations into at most one 30 FPS render loop. */
export class RenderScheduler {
  private readonly render: (reasons: ReadonlySet<RenderInvalidation>) => void
  private readonly dependencies: RenderSchedulerDependencies
  private readonly collectionTelemetry: (collectedItems: number) => void
  private readonly dirty = new Set<RenderInvalidation>()
  private readonly visibilityListener = () => this.visibilityChanged()
  private frameId: number | null = null
  private lastRender = Number.NEGATIVE_INFINITY
  private generation = 0
  private running = false
  private disposed = false

  constructor(
    render: (reasons: ReadonlySet<RenderInvalidation>) => void,
    dependencies: RenderSchedulerDependencies = browserDependencies(),
    collectionTelemetry: (collectedItems: number) => void = () => {},
  ) {
    this.render = render
    this.dependencies = dependencies
    this.collectionTelemetry = collectionTelemetry
    dependencies.addVisibilityListener(this.visibilityListener)
  }

  start(): void {
    if (this.running || this.disposed) return
    this.running = true
    this.generation += 1
    this.scheduleIfNeeded()
  }

  stop(): void {
    if (!this.running) return
    this.running = false
    this.generation += 1
    if (this.frameId !== null) {
      this.dependencies.cancelAnimationFrame(this.frameId)
      this.frameId = null
    }
  }

  dispose(): void {
    if (this.disposed) return
    this.stop()
    this.disposed = true
    this.dirty.clear()
    this.dependencies.removeVisibilityListener(this.visibilityListener)
  }

  invalidate(reason: RenderInvalidation): void {
    if (this.disposed) return
    this.dirty.add(reason)
    this.scheduleIfNeeded()
  }

  /** Acquisition accounting is immediate and remains active while hidden. */
  recordCollection(collectedItems: number): void {
    if (this.disposed) return
    this.collectionTelemetry(collectedItems)
  }

  private scheduleIfNeeded(): void {
    if (
      !this.running
      || this.disposed
      || this.frameId !== null
      || this.dirty.size === 0
      || this.dependencies.isDocumentHidden()
    ) return
    const generation = this.generation
    this.frameId = this.dependencies.requestAnimationFrame(() => this.onFrame(generation))
  }

  private onFrame(generation: number): void {
    if (generation !== this.generation || !this.running || this.disposed) return
    this.frameId = null
    if (this.dependencies.isDocumentHidden()) return
    const now = this.dependencies.now()
    if (now - this.lastRender >= FRAME_INTERVAL_MS) {
      const reasons = new Set(this.dirty)
      this.dirty.clear()
      this.lastRender = now
      this.render(reasons)
    }
    this.scheduleIfNeeded()
  }

  private visibilityChanged(): void {
    if (!this.dependencies.isDocumentHidden()) this.scheduleIfNeeded()
  }
}
