import { describe, expect, it } from 'vitest'
// The same ES module is used by the packaged standalone page and Vite Worker.
// @ts-ignore JavaScript runtime module with test-only exports.
import { ReplayParser, parseReplayFile, replayView, csvCells } from '../../../mklink/static/superwatch_replay_data.js'

function parse(text: string) {
  const parser = new ReplayParser()
  for (const line of text.split('\n')) parser.line(line)
  return parser.finish()
}

describe('SuperWatch file replay', () => {
  it.each([
    ['[2026-10-02 00:00:00.000] gain=1', '[2026-10-02 00:00:00.100] gain=2'],
    ['{"_t":0,"gain":1}', '{"_t":0.1,"gain":2}'],
  ])('imports live-write metadata before and between samples without changing their clock', (first, last) => {
    const event = JSON.stringify({ event: 'write', path: 'gain', value: 2, verified: true, mode: 'live', timestamp_us: 123456789 })
    const data = parse([event, first, event, last].join('\n'))
    expect(data.rows).toBe(2)
    expect(data.writeEvents).toBe(2)
    expect(data.duration).toBeCloseTo(.1)
    expect(data.channels.map((c: any) => c.name)).toEqual(['gain'])
    expect([...data.channels[0].values]).toEqual([1, 2])
  })
  it('rejects malformed write metadata and event-only logs', () => {
    expect(() => parse('{"event":"write"}')).toThrow('Invalid write event')
    expect(() => parse('{"event":"write","path":"gain","value":2,"verified":true,"mode":"live"}')).toThrow('No samples')
  })
  it('round trips exported CSV, BOM/CRLF, sparse values and microsecond timestamps', () => {
    const data = parse('\uFEFFtimestamp_us,a,b\r\n1000000,2,\r\n1050000,,false\r\n1100000,4,true\r\n')
    expect(data.rows).toBe(3)
    expect(data.duration).toBeCloseTo(.1)
    expect([...data.channels[0].values]).toEqual([2, 4])
    expect([...data.channels[1].values]).toEqual([0, 1])
  })
  it.each([',', ';', '\t'])('supports delimiter %j and quoted channel names', delimiter => {
    const data = parse(`timestamp${delimiter}"motor, reference"\n0${delimiter}1\n.05${delimiter}2`)
    expect(data.channels[0].name).toBe('motor, reference')
    expect([...data.channels[0].values]).toEqual([1, 2])
    expect(csvCells('"a""b",c', ',')).toEqual(['a"b', 'c'])
  })
  it('reads standalone sparse JSONL regions at duplicate timestamps without inventing values', () => {
    const data = parse('{"_t":0,"timestamp_us":500,"a":1}\n{"_t":0,"b":2}\n{"_t":0,"a":3}\n{"_t":1,"b":4}')
    expect(data.values).toBe(3)
    expect([...data.channels[0].values]).toEqual([3])
    const view = replayView(data, .5, 10, 100, ['a', 'b'])
    expect(view.channels[1].latest).toBe(2)
    expect(view.channels[1].points).toEqual([[0, 2]])
  })
  it('reads timestamped TXT exports using a fixed clock through a date boundary', () => {
    const data = parse('[2026-10-02 23:59:59.950] app.x[0]=1.2, flag=true\n[2026-10-03 00:00:00.000] app.x[0]=2.4, flag=false')
    expect(data.duration).toBeCloseTo(.05)
    expect(data.channels.map((c: any) => c.name)).toEqual(['app.x[0]', 'flag'])
  })
  it.each([
    ['a,b\n1,2', 'timestamp'],
    ['timestamp,a,a\n0,1,2', 'duplicate'],
    ['timestamp,a\n0,NaN', 'Line 2'],
    ['timestamp,a\n0,1\n-1,2', 'backwards'],
    ['timestamp,a\n,1', 'timestamp'],
    ['timestamp,a\n0,', 'no variable'],
    ['timestamp,a\n0,1,2', 'column count'],
    ['{"_t":0,"timestamp_us":1}', 'no variable'],
    ['{"_t":0,"a":null}', 'Missing numeric'],
    ['{"_t":true,"a":1}', 'invalid timestamp'],
    ['timestamp,a\n-1e308,1\n1e308,2', 'overflow'],
    ['[invalid] a=1', 'Expected'],
    ['timestamp,a\n', 'No samples'],
    ['timestamp,a\n0,"1', 'Unclosed'],
  ])('rejects malformed logs (%s)', (text, expected) => {
    expect(() => parse(text)).toThrow(expected)
  })
  it('keeps an isolated spike in a pixel-bounded overview and can seek backwards', () => {
    const parser = new ReplayParser(); parser.line('timestamp,value')
    for (let i = 0; i < 100000; i++) parser.line(`${i / 1000},${i === 55555 ? 999 : 0}`)
    const data = parser.finish()
    const all = replayView(data, data.duration, data.duration, 200, ['value'])
    expect(all.channels[0].points.length).toBeLessThanOrEqual(400)
    expect(all.channels[0].points.some((p: number[]) => p[1] === 999)).toBe(true)
    const early = replayView(data, 1, .1, 200, ['value'])
    expect(early.channels[0].latest).toBe(0)
    expect(early.channels[0].points.every((p: number[]) => p[0]! >= .9 && p[0]! <= 1)).toBe(true)
    expect(replayView(data, 50, 10, 200, []).channels).toEqual([])
  })
  it('parses UTF-8 text split across streaming chunk boundaries', async () => {
    const bytes = new TextEncoder().encode('timestamp,温度\r\n0,2\r\n1,3')
    const file = { size: bytes.length, stream: () => new ReadableStream({ start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
      controller.close()
    } }) }
    const data = await parseReplayFile(file)
    expect(data.channels[0].name).toBe('温度')
    expect(data.rows).toBe(2)
  })
  it('rejects oversized files before reading and excessive channel counts', async () => {
    await expect(parseReplayFile({ size: 257 * 1024 * 1024 })).rejects.toThrow('256 MiB')
    expect(() => parse('timestamp,' + Array.from({ length: 65 }, (_, i) => 'v' + i).join(','))).toThrow('64 channels')
  })
})
