import { describe, expect, it } from 'vitest'
import { SignCategory } from '../api/model'
import type { BBox, Filters } from './filters'
import {
  DEFAULT_FILTERS,
  decodeFilters,
  encodeFilters,
  toSignParams,
  toSpotParams,
} from './filters'

describe('filter URL sync', () => {
  it('round-trips a fully populated filter set', () => {
    const f: Filters = {
      showSigns: true,
      showSpots: false,
      categories: [SignCategory.permitted, SignCategory.prohibited],
      reserved: true,
      hour: [8, 18],
      day: [1, 5],
      month: [4, 12],
      notInRange: true,
    }
    expect(decodeFilters(encodeFilters(f))).toEqual(f)
  })

  it('falls back to defaults for an empty query string', () => {
    const f = decodeFilters(new URLSearchParams(''))
    expect(f.categories).toEqual([SignCategory.permitted])
    expect(f.hour).toBeNull()
    expect(f.reserved).toBeNull()
    expect(f.showSigns).toBe(false)
    expect(f.showSpots).toBe(false)
  })

  it('omits null/inactive values from the query string', () => {
    const qs = encodeFilters(DEFAULT_FILTERS).toString()
    expect(qs).not.toContain('hour')
    expect(qs).not.toContain('day')
    expect(qs).not.toContain('not')
  })
})

describe('query param mapping', () => {
  const bbox: BBox = [-73.6, 45.4, -73.5, 45.6]

  it('maps enabled ranges and NOT into sign params', () => {
    const f: Filters = { ...DEFAULT_FILTERS, hour: [9, 17], day: [1, 5], notInRange: true }
    const p = toSignParams(f, bbox)
    expect(p).toMatchObject({
      min_lon: -73.6,
      max_lat: 45.6,
      hour_start: 9,
      hour_end: 17,
      day_start: 1,
      day_end: 5,
      not_in_range: true,
      categories: [SignCategory.permitted],
    })
    expect(p.month_start).toBeUndefined()
    expect(p.month_end).toBeUndefined()
  })

  it('omits disabled time dimensions (undefined, not null)', () => {
    const p = toSignParams(DEFAULT_FILTERS, bbox)
    expect(p.hour_start).toBeUndefined()
    expect(p.day_start).toBeUndefined()
    expect(p.month_start).toBeUndefined()
    expect(p.reserved).toBeUndefined()
  })

  it('spot params carry bbox + hour + day only', () => {
    const f: Filters = { ...DEFAULT_FILTERS, hour: [10, 11], day: [6, 7] }
    expect(toSpotParams(f, bbox)).toEqual({
      min_lon: -73.6,
      min_lat: 45.4,
      max_lon: -73.5,
      max_lat: 45.6,
      hour_start: 10,
      hour_end: 11,
      day_start: 6,
      day_end: 7,
    })
  })
})
