const KEY = 'travelmate.gen.active'
const MAX_AGE = 15 * 60_000

export interface GenMarker {
  id: string
  ts: number
}

/** 提交生成时记录请求标记：页面刷新后凭它重放事件流领回行程。 */
export function saveGenMarker(id: string): void {
  localStorage.setItem(KEY, JSON.stringify({ id, ts: Date.now() } satisfies GenMarker))
}

export function loadGenMarker(): GenMarker | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const m = JSON.parse(raw)
    if (typeof m?.id !== 'string' || typeof m?.ts !== 'number') return null
    if (Date.now() - m.ts > MAX_AGE) {
      localStorage.removeItem(KEY)
      return null
    }
    return { id: m.id, ts: m.ts }
  } catch {
    return null
  }
}

export function clearGenMarker(): void {
  localStorage.removeItem(KEY)
}
