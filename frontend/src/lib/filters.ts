import { useCallback, useState } from 'react'
import { SignCategory } from '../api/model'
import type { ParkingSignsParams, PaidSpotsParams } from '../api/model'

export type BBox = [number, number, number, number] // min_lon, min_lat, max_lon, max_lat
export type Range = [number, number]

export interface Filters {
  showSigns: boolean
  showSpots: boolean
  categories: SignCategory[]
  reserved: boolean | null // null = all, true = reserved only
  hour: Range | null // null = don't filter this dimension
  day: Range | null
  month: Range | null
  notInRange: boolean
}

export const DEFAULT_FILTERS: Filters = {
  showSigns: false,
  showSpots: false,
  categories: [SignCategory.permitted],
  reserved: null,
  hour: null,
  day: null,
  month: null,
  notInRange: false,
}

export const ALL_CATEGORIES: SignCategory[] = [
  SignCategory.permitted,
  SignCategory.prohibited,
  SignCategory.other,
]
export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
export const MONTH_LABELS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

function encodeRange(r: Range | null): string | null {
  return r ? `${r[0]}-${r[1]}` : null
}

function decodeRange(s: string | null): Range | null {
  if (!s) return null
  const [a, b] = s.split('-').map(Number)
  return Number.isFinite(a) && Number.isFinite(b) ? [a, b] : null
}

export function encodeFilters(f: Filters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.showSigns) p.set('signs', '1')
  if (f.showSpots) p.set('spots', '1')
  if (f.categories.length) p.set('cat', f.categories.join(','))
  if (f.reserved !== null) p.set('reserved', f.reserved ? '1' : '0')
  const h = encodeRange(f.hour)
  if (h) p.set('hour', h)
  const d = encodeRange(f.day)
  if (d) p.set('day', d)
  const m = encodeRange(f.month)
  if (m) p.set('month', m)
  if (f.notInRange) p.set('not', '1')
  return p
}

export function decodeFilters(p: URLSearchParams): Filters {
  const cat = p.get('cat')
  return {
    showSigns: p.get('signs') === '1',
    showSpots: p.get('spots') === '1',
    categories: cat ? (cat.split(',') as SignCategory[]) : DEFAULT_FILTERS.categories,
    reserved: p.has('reserved') ? p.get('reserved') === '1' : null,
    hour: decodeRange(p.get('hour')),
    day: decodeRange(p.get('day')),
    month: decodeRange(p.get('month')),
    notInRange: p.get('not') === '1',
  }
}

export function useFilters(): [Filters, (f: Filters) => void] {
  const [filters, setState] = useState<Filters>(() =>
    decodeFilters(new URLSearchParams(window.location.search)),
  )
  const setFilters = useCallback((f: Filters) => {
    setState(f)
    const qs = encodeFilters(f).toString()
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname)
  }, [])
  return [filters, setFilters]
}

// Optional params are left `undefined` (not null) so the generated client omits
// them from the query string — FastAPI rejects a literal `?hour_start=null`.
export function toSignParams(f: Filters, bbox: BBox): ParkingSignsParams {
  const [min_lon, min_lat, max_lon, max_lat] = bbox
  return {
    min_lon, min_lat, max_lon, max_lat,
    categories: f.categories,
    reserved: f.reserved ?? undefined,
    hour_start: f.hour?.[0],
    hour_end: f.hour?.[1],
    day_start: f.day?.[0],
    day_end: f.day?.[1],
    month_start: f.month?.[0],
    month_end: f.month?.[1],
    not_in_range: f.notInRange,
  }
}

export function toSpotParams(f: Filters, bbox: BBox): PaidSpotsParams {
  const [min_lon, min_lat, max_lon, max_lat] = bbox
  return {
    min_lon, min_lat, max_lon, max_lat,
    hour_start: f.hour?.[0],
    hour_end: f.hour?.[1],
    day_start: f.day?.[0],
    day_end: f.day?.[1],
  }
}
