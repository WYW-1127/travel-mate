import { defineStore } from 'pinia'

import type { Activity, Trip } from '@/types/trip'

function newId(): string {
  return crypto.randomUUID()
}

/**
 * 当前编辑中的行程。所有编辑只改这里；地图与预算面板通过 getters 响应式联动。
 */
export const useCurrentTripStore = defineStore('currentTrip', {
  state: () => ({
    trip: null as Trip | null,
  }),
  getters: {
    headcount: (state) =>
      (state.trip?.travelers?.adults ?? 1) + (state.trip?.travelers?.children ?? 0),
    /** 人均费用合计 */
    budgetTotal: (state) =>
      state.trip?.days.reduce(
        (sum, d) => sum + d.activities.reduce((s, a) => s + (a.cost ?? 0), 0),
        0,
      ) ?? 0,
    /** 总费用 = 人均合计 × 出行人数 */
    budgetGrandTotal(): number {
      return this.budgetTotal * this.headcount
    },
    overBudget: (state) =>
      state.trip?.budgetLimit != null && this.budgetGrandTotal > state.trip.budgetLimit,
    budgetByType: (state) => {
      const result: Record<string, number> = {}
      for (const d of state.trip?.days ?? []) {
        for (const a of d.activities) {
          result[a.type] = (result[a.type] ?? 0) + (a.cost ?? 0)
        }
      }
      return result
    },
    /** 某天可上地图的活动（resolved=true 且有坐标） */
    dayRoutePoints(state) {
      return (dayIndex: number) =>
        (state.trip?.days[dayIndex]?.activities ?? []).filter(
          (a) => a.location?.resolved && a.location.longitude != null && a.location.latitude != null,
        )
    },
  },
  actions: {
    set(trip: Trip | null) {
      this.trip = trip
    },
    addActivity(dayIndex: number) {
      const day = this.trip?.days[dayIndex]
      if (!day) return
      day.activities.push({
        id: newId(),
        name: '新活动',
        type: 'attraction',
        startTime: null,
        endTime: null,
        cost: 0,
        notes: '',
        location: null,
      })
    },
    removeActivity(dayIndex: number, activityIndex: number) {
      this.trip?.days[dayIndex]?.activities.splice(activityIndex, 1)
    },
    moveActivity(dayIndex: number, from: number, to: number) {
      const activities = this.trip?.days[dayIndex]?.activities
      if (!activities || to < 0 || to >= activities.length) return
      const [moved] = activities.splice(from, 1)
      activities.splice(to, 0, moved)
    },
    updateActivity(dayIndex: number, activityIndex: number, patch: Partial<Activity>) {
      const activity = this.trip?.days[dayIndex]?.activities[activityIndex]
      if (activity) Object.assign(activity, patch)
    },
    /** 重规划结果落地：整体替换行程对象（调用方先 saveSnapshot） */
    replaceTrip(next: Trip) {
      this.trip = next
    },
  },
})
