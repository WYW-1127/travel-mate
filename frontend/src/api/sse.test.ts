import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { postSSE, SSEError } from '@/api/sse'
import type { StreamEvent } from '@/types/trip'

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  let i = 0
  return new Response(
    new ReadableStream({
      pull(controller) {
        if (i < chunks.length) {
          controller.enqueue(encoder.encode(chunks[i++]))
        } else {
          controller.close()
        }
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  )
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => sseResponse([])),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('postSSE', () => {
  it('解析单帧单事件', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse(['data: {"type":"progress","stage":"plan","message":"规划中"}\n\n']),
      ),
    )
    const events: StreamEvent[] = []
    const { done } = postSSE('/api/x', { destination: '重庆', days: 1 }, (e) => events.push(e))
    await done
    expect(events).toHaveLength(1)
    expect(events[0]).toMatchObject({ type: 'progress', stage: 'plan' })
  })

  it('跨 chunk 拆开的事件被缓冲后正确解析', async () => {
    const full = 'data: {"type":"progress","stage":"analyze","message":"分'
    const rest = '析需求"}\n\ndata: {"type":"progress","stage":"plan","message":"b"}\n\n'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([full, rest])),
    )
    const events: StreamEvent[] = []
    const { done } = postSSE('/api/x', { destination: '重庆', days: 1 }, (e) => events.push(e))
    await done
    expect(events.map((e) => e.stage)).toEqual(['analyze', 'plan'])
  })

  it('一帧包含多个事件', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          'data: {"type":"progress","stage":"plan","message":"a"}\n\ndata: {"type":"progress","stage":"enrich","message":"b"}\n\n',
        ]),
      ),
    )
    const events: StreamEvent[] = []
    const { done } = postSSE('/api/x', { destination: '重庆', days: 1 }, (e) => events.push(e))
    await done
    expect(events.map((e) => e.stage)).toEqual(['plan', 'enrich'])
  })

  it('流结束时残留的不完整帧仍被消费', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse(['data: {"type":"progress","stage":"validate","message":"尾帧"}'])),
    )
    const events: StreamEvent[] = []
    const { done } = postSSE('/api/x', { destination: '重庆', days: 1 }, (e) => events.push(e))
    await done
    expect(events).toHaveLength(1)
    expect(events[0]).toMatchObject({ stage: 'validate' })
  })

  it('非 200 抛出 SSEError 并带状态码', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"detail":"JSON decode error"}', { status: 400 })),
    )
    const { done } = postSSE('/api/x', { destination: '重庆', days: 1 }, () => {})
    await expect(done).rejects.toMatchObject({ code: 'NETWORK', message: 'JSON decode error' })
  })
})
