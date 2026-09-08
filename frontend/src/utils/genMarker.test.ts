import { beforeEach, describe, expect, it } from 'vitest'

import {
  clearGenMarker,
  loadGenMarker,
  saveGenMarker,
} from './genMarker'

beforeEach(() => localStorage.clear())

describe('genMarker', () => {
  it('save/load 往返', () => {
    saveGenMarker('rid-1')
    expect(loadGenMarker()).toEqual({ id: 'rid-1', ts: expect.any(Number) })
  })

  it('过期（>15 分钟）返回 null 并清除', () => {
    localStorage.setItem(
      'travelmate.gen.active',
      JSON.stringify({ id: 'old', ts: Date.now() - 16 * 60_000 }),
    )
    expect(loadGenMarker()).toBeNull()
    expect(localStorage.getItem('travelmate.gen.active')).toBeNull()
  })

  it('损坏数据返回 null', () => {
    localStorage.setItem('travelmate.gen.active', '{oops')
    expect(loadGenMarker()).toBeNull()
  })

  it('clearGenMarker 清除', () => {
    saveGenMarker('a')
    clearGenMarker()
    expect(loadGenMarker()).toBeNull()
  })
})
