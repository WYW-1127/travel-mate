import { defineStore } from 'pinia'

import type { Trip } from '@/types/trip'

const STORAGE_KEY = 'travelmate.trips'
const SNAPSHOT_KEY = 'travelmate.snapshots'
const MAX_SNAPSHOTS = 5

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function newId(): string {
  return crypto.randomUUID()
}

/** Trip 是纯 JSON 数据（要进 localStorage），JSON 往返即可深拷贝，且能穿透响应式 Proxy */
function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}

/**
 * 行程列表：localStorage 持久化 + 重规划快照栈（每行程 ≤5 版，支持撤销）。
 */
export const useTripsStore = defineStore('trips', {
  state: () => ({
    list: load<Trip[]>(STORAGE_KEY, []),
    snapshots: load<Record<string, Trip[]>>(SNAPSHOT_KEY, {}),
  }),
  getters: {
    sorted: (state) =>
      [...state.list].sort((a, b) => (b.id ?? '').localeCompare(a.id ?? '')),
  },
  actions: {
    persist() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.list))
      localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(this.snapshots))
    },
    upsert(trip: Trip): Trip {
      const stored = { ...trip, id: trip.id || newId() }
      const idx = this.list.findIndex((t) => t.id === stored.id)
      if (idx === -1) this.list.unshift(stored)
      else this.list[idx] = stored
      this.persist()
      return stored
    },
    get(id: string): Trip | undefined {
      return this.list.find((t) => t.id === id)
    },
    remove(id: string) {
      this.list = this.list.filter((t) => t.id !== id)
      delete this.snapshots[id]
      this.persist()
    },
    duplicate(id: string): Trip | undefined {
      const src = this.get(id)
      if (!src) return undefined
      return this.upsert({
        ...deepClone(src),
        id: undefined,
        title: `${src.title ?? src.destination}（副本）`,
        version: 1,
      })
    },
    /** 重规划前调用：保存当前版本快照 */
    saveSnapshot(trip: Trip) {
      if (!trip.id) return
      const stack = (this.snapshots[trip.id] ??= [])
      stack.push(deepClone(trip))
      if (stack.length > MAX_SNAPSHOTS) stack.shift()
      this.persist()
    },
    /** 撤销：恢复最近一次快照，返回恢复的行程（无快照返回 null） */
    undo(trip: Trip): Trip | null {
      if (!trip.id) return null
      const stack = this.snapshots[trip.id] ?? []
      const prev = stack.pop()
      if (!prev) return null
      this.persist()
      return this.upsert(prev)
    },
    snapshotCount(id: string): number {
      return (this.snapshots[id] ?? []).length
    },
  },
})
