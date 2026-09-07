import { postJson } from '@/api/client'

/** 抽取长期偏好；网络/GLM 失败会抛错，调用方 fire-and-forget 时自行吞掉 */
export async function extractPreferences(text: string): Promise<string[]> {
  const r = await postJson<{ items: string[] }>('/api/preferences/extract', { text })
  return Array.isArray(r.items) ? r.items.filter((x): x is string => typeof x === 'string') : []
}
