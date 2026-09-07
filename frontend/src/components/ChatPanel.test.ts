import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { StreamEvent } from '@/types/trip'

const postSSE = vi.fn()
vi.mock('@/api/sse', () => ({ postSSE: (...args: unknown[]) => postSSE(...args) }))

import ChatPanel from './ChatPanel.vue'
import { useCurrentTripStore } from '@/stores/currentTrip'
import { useTripsStore } from '@/stores/trips'

function makeTrip() {
  return {
    id: 't1',
    destination: '杭州',
    version: 1,
    preferences: '带娃',
    days: [{ title: 'D1', activities: [{ id: 'a1', name: '西湖', type: 'attraction', cost: 0 }] }],
    chat: [{ role: 'assistant', content: '行程已生成，随时告诉我要改什么', ts: '2026-09-07T10:00:00' }],
  }
}

function sseMock(events: StreamEvent[]) {
  postSSE.mockImplementation((_url: string, _body: unknown, onEvent: (e: StreamEvent) => void) => {
    for (const e of events) onEvent(e)
    return { stop: vi.fn(), done: Promise.resolve() }
  })
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  postSSE.mockReset()
})

describe('ChatPanel', () => {
  it('渲染已有对话历史', () => {
    const store = useCurrentTripStore()
    store.set(makeTrip() as never)
    const wrapper = mount(ChatPanel)
    expect(wrapper.text()).toContain('行程已生成，随时告诉我要改什么')
  })

  it('发送后 complete 落地：version 变化才存快照，trip 整体替换', async () => {
    const current = useCurrentTripStore()
    const trips = useTripsStore()
    const trip = trips.upsert(makeTrip() as never)
    current.set(trip)

    const next = {
      ...trip,
      version: 2,
      chat: [...(trip.chat ?? []), { role: 'user', content: '别太赶' }, { role: 'assistant', content: '已放慢节奏' }],
    }
    sseMock([{ type: 'complete', trip: next as never }])

    const wrapper = mount(ChatPanel)
    await wrapper.find('input[type="text"]').setValue('第二天别太赶')
    await wrapper.find('form').trigger('submit')
    await vi.waitFor(() => expect(current.trip!.version).toBe(2))
    expect(current.trip!.chat).toHaveLength(3)
    expect(trips.snapshotCount('t1')).toBe(1)
    // 请求体带 chat 端点与消息
    expect(postSSE).toHaveBeenCalledWith(
      '/api/trips/chat',
      expect.objectContaining({ trip: expect.objectContaining({ id: 't1' }), message: '第二天别太赶' }),
      expect.any(Function),
    )
  })
})
