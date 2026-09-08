import type { ChatRequest, GenerateRequest, ReplayRequest, ReplanRequest, StreamEvent } from '@/types/trip'

export class SSEError extends Error {
  code: string

  constructor(message: string, code = 'NETWORK') {
    super(message)
    this.code = code
  }
}

/**
 * POST + fetch 流式消费 SSE（浏览器 EventSource 只支持 GET，带不下请求体）。
 * 跨 chunk 缓冲、按空行分帧、每帧取 `data:` 行解析 JSON。
 * 返回 stop 函数：中断连接（AbortController）。
 */
export function postSSE(
  url: string,
  body: GenerateRequest | ReplanRequest | ChatRequest | ReplayRequest,
  onEvent: (event: StreamEvent) => void,
): { stop: () => void; done: Promise<void> } {
  const controller = new AbortController()

  const done = (async () => {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (!resp.ok || !resp.body) {
      let detail = `HTTP ${resp.status}`
      try {
        const data = await resp.json()
        if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
      } catch {
        /* 非 JSON 错误体，保留状态码信息 */
      }
      throw new SSEError(detail)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const consumeFrame = (frame: string) => {
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data: ')) continue
        try {
          onEvent(JSON.parse(line.slice(6)) as StreamEvent)
        } catch {
          /* 忽略无法解析的帧 */
        }
      }
    }

    for (;;) {
      const { done: finished, value } = await reader.read()
      if (finished) break
      buffer += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        consumeFrame(buffer.slice(0, idx))
        buffer = buffer.slice(idx + 2)
      }
    }
    if (buffer.trim()) consumeFrame(buffer)
  })()

  return { stop: () => controller.abort(), done }
}
