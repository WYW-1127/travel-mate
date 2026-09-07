import { defineStore } from 'pinia'

import { postSSE, SSEError } from '@/api/sse'
import type { ChatRequest, GenerateRequest, ReplanRequest, StreamEvent, Trip } from '@/types/trip'

export type GenerationPhase = 'idle' | 'running' | 'done' | 'error'

/**
 * 生成/对话修改行程的 SSE 连接状态。GeneratingView 与 ChatPanel 共用。
 */
export const useGenerationStore = defineStore('generation', {
  state: () => ({
    phase: 'idle' as GenerationPhase,
    messages: [] as string[],
    thinking: '',
    error: null as { code: string; message: string } | null,
    result: null as Trip | null,
    stop: null as (() => void) | null,
  }),
  actions: {
    reset() {
      this.phase = 'idle'
      this.messages = []
      this.thinking = ''
      this.error = null
      this.result = null
      this.stop = null
    },
    /** 发起流式请求；onEvent 可选，用于调用方旁路监听 */
    run(url: string, body: GenerateRequest | ReplanRequest | ChatRequest, onEvent?: (e: StreamEvent) => void) {
      this.reset()
      this.phase = 'running'
      const { stop, done } = postSSE(url, body, (event) => {
        onEvent?.(event)
        if (event.type === 'progress') {
          this.messages.push(event.message)
        } else if (event.type === 'thinking') {
          this.thinking += event.content
        } else if (event.type === 'complete') {
          this.result = event.trip
          this.phase = 'done'
        } else {
          this.error = { code: event.code, message: event.message }
          this.phase = 'error'
        }
      })
      this.stop = stop
      // 网络失败 / HTTP 错误（如后端 500）也要终结 running 态，否则 UI 永久卡住
      done.catch((e: unknown) => {
        if (this.phase === 'running') {
          this.error = {
            code: e instanceof SSEError ? e.code : 'NETWORK',
            message: e instanceof Error ? e.message : '网络错误，请重试',
          }
          this.phase = 'error'
        }
      })
      return done
    },
  },
})
