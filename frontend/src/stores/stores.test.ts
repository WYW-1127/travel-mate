import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useCurrentTripStore } from '@/stores/currentTrip'
import type { Trip } from '@/types/trip'
import { useTripsStore } from '@/stores/trips'

function makeTrip(overrides: Partial<Trip> = {}): Trip {
  return {
    destination: '重庆',
    days: [
      {
        title: 'D1',
        activities: [
          { id: 'a1', name: '洪崖洞', type: 'attraction', cost: 30, location: { name: '洪崖洞', resolved: true, longitude: 106.579, latitude: 29.562 } },
          { id: 'a2', name: '火锅', type: 'meal', cost: 110 },
        ],
      },
      {
        title: 'D2',
        activities: [{ id: 'a3', name: '磁器口', type: 'attraction', cost: 0 }],
      },
    ],
    travelers: { adults: 2, children: 1 },
    budgetLimit: 1000,
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

describe('trips store', () => {
  it('upsert 新增并持久化到 localStorage', () => {
    const store = useTripsStore()
    const saved = store.upsert(makeTrip())
    expect(store.list).toHaveLength(1)
    expect(saved.id).toBeTruthy()
    expect(JSON.parse(localStorage.getItem('travelmate.trips')!)).toHaveLength(1)
  })

  it('upsert 按 id 更新已有行程', () => {
    const store = useTripsStore()
    const saved = store.upsert(makeTrip({ title: '旧标题' }))
    store.upsert({ ...saved, title: '新标题' })
    expect(store.list).toHaveLength(1)
    expect(store.list[0].title).toBe('新标题')
  })

  it('duplicate 生成独立副本且 version 归 1', () => {
    const store = useTripsStore()
    const saved = store.upsert(makeTrip({ version: 3 }))
    const copy = store.duplicate(saved.id!)
    expect(copy!.version).toBe(1)
    expect(copy!.id).not.toBe(saved.id)
    expect(store.list).toHaveLength(2)
  })

  it('saveSnapshot/undo 恢复上一版本，栈深 ≤5', () => {
    const store = useTripsStore()
    let trip = store.upsert(makeTrip({ version: 1 }))
    for (let v = 2; v <= 8; v++) {
      store.saveSnapshot(trip)
      trip = store.upsert({ ...trip, version: v })
    }
    expect(store.snapshotCount(trip.id!)).toBe(5)
    const restored = store.undo(trip)
    expect(restored!.version).toBe(7)
    expect(store.undo(restored!)!.version).toBe(6)
  })

  it('undo 无快照返回 null', () => {
    const store = useTripsStore()
    const trip = store.upsert(makeTrip())
    expect(store.undo(trip)).toBeNull()
  })
})

describe('currentTrip store', () => {
  it('预算派生：人均合计 / 总价 / 分类 / 超预算', () => {
    const store = useCurrentTripStore()
    store.set(makeTrip())
    expect(store.budgetTotal).toBe(140) // 30 + 110 + 0
    expect(store.headcount).toBe(3)
    expect(store.budgetGrandTotal).toBe(420)
    expect(store.overBudget).toBe(false)
    expect(store.budgetByType).toEqual({ attraction: 30, meal: 110 })

    store.updateActivity(0, 1, { cost: 400 })
    expect(store.budgetGrandTotal).toBe(1290) // (30+400+0)×3，响应式重算
    expect(store.overBudget).toBe(true)
  })

  it('dayRoutePoints 只含 resolved 且有坐标的活动', () => {
    const store = useCurrentTripStore()
    store.set(makeTrip())
    expect(store.dayRoutePoints(0)).toHaveLength(1)
    expect(store.dayRoutePoints(1)).toHaveLength(0)
  })

  it('moveActivity 支持拖拽重排', () => {
    const store = useCurrentTripStore()
    store.set(makeTrip())
    store.moveActivity(0, 1, 0)
    expect(store.trip!.days[0].activities[0].name).toBe('火锅')
  })
})
