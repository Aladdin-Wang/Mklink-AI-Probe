export interface SvTimelineRoots {
  canvas: HTMLCanvasElement
  tooltip?: HTMLElement
  legend?: HTMLElement
  vcpu?: HTMLElement
  resetBtn?: HTMLElement
  hint?: HTMLElement
}
export interface SvTimelineData {
  intervals: { tid: number; name: string; start: number; end: number; startTk?: number | bigint; endTk?: number | bigint }[]
  unit?: 'us' | 'tk'
  tickHz?: number
  follow?: boolean
  windowSize?: number
  tickOrigin?: bigint
  renderPaused?: boolean
}
export class SvTimeline {
  viewStart: number | null
  viewEnd: number | null
  constructor(roots: SvTimelineRoots, data: SvTimelineData)
  setData(intervals: SvTimelineData['intervals']): void
  setPrefilteredIntervals(intervals: SvTimelineData['intervals']): void
  setWindowSize(windowSize: number): void
  setTickOrigin(tickOrigin: bigint): void
  setFollowMode(enabled: boolean): void
  pauseRendering(): void
  resumeRendering(): void
  reset(): void
  toggleTask(tid: number): void
  destroy(): void
}

export function exactTickFromOffset(origin: bigint, offset: number): string
