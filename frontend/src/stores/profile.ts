import { defineStore } from 'pinia'

const KEY = 'travelmate.profile'
const MAX_ITEMS = 20

function load(): string[] {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

/** 用户长期偏好档案（跨行程），localStorage 持久化。 */
export const useProfileStore = defineStore('profile', {
  state: () => ({ items: load() }),
  actions: {
    persist() {
      localStorage.setItem(KEY, JSON.stringify(this.items))
    },
    /** 并入新偏好：trim/截断 30 字/精确去重，总量上限 20 条 */
    addAll(items: string[]) {
      for (const raw of items) {
        const text = String(raw ?? '')
          .trim()
          .slice(0, 30)
        if (text && !this.items.includes(text)) this.items.push(text)
      }
      this.items = this.items.slice(0, MAX_ITEMS)
      this.persist()
    },
    remove(index: number) {
      this.items.splice(index, 1)
      this.persist()
    },
  },
})
