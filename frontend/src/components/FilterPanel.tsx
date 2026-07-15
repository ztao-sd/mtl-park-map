import { useState } from 'react'
import type { FormEvent } from 'react'
import { SignCategory } from '../api/model'
import { addressLocation } from '../api/endpoints'
import type { Filters, Range } from '../lib/filters'
import {
  ALL_CATEGORIES,
  DAY_LABELS,
  DEFAULT_FILTERS,
  MONTH_LABELS,
} from '../lib/filters'

interface Props {
  applied: Filters
  onApply: (f: Filters) => void
  onLocate: (loc: { longitude: number; latitude: number }) => void
  loading: boolean
}

export function FilterPanel({ applied, onApply, onLocate, loading }: Props) {
  const [open, setOpen] = useState(true)
  const [draft, setDraft] = useState<Filters>(applied)
  const [address, setAddress] = useState('')
  const [addrError, setAddrError] = useState(false)

  const set = (patch: Partial<Filters>) => setDraft({ ...draft, ...patch })
  const dirty = JSON.stringify(draft) !== JSON.stringify(applied)

  const toggleCategory = (c: SignCategory) => {
    const has = draft.categories.includes(c)
    set({
      categories: has
        ? draft.categories.filter((x) => x !== c)
        : [...draft.categories, c],
    })
  }

  const search = async (e: FormEvent) => {
    e.preventDefault()
    if (!address.trim()) return
    setAddrError(false)
    try {
      const res = await addressLocation({ address })
      if (res.status === 200) {
        onLocate({ longitude: res.data.longitude, latitude: res.data.latitude })
      } else {
        setAddrError(true)
      }
    } catch {
      setAddrError(true)
    }
  }

  return (
    <aside
      style={{
        width: '20rem',
        left: open ? '0rem' : '-20rem',
        transition: 'left 300ms ease-in-out',
      }}
      className="absolute top-0 z-[1100] h-full max-w-full"
    >
      {/* Pull-tab: always visible, sticks out past the panel's right edge. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? 'Hide filters' : 'Show filters'}
        aria-expanded={open}
        className="absolute left-full top-4 flex h-16 w-7 items-center justify-center rounded-r-lg border border-l-0 border-gray-200 bg-white/95 text-lg text-gray-500 shadow-lg backdrop-blur hover:text-gray-800"
      >
        {open ? '‹' : '›'}
      </button>

      <div className="flex h-full flex-col bg-white/95 text-sm text-gray-800 shadow-lg backdrop-blur">
        <header className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <h1 className="text-base font-semibold">MTL Park Map</h1>
          {loading && <span className="text-xs text-gray-400">loading…</span>}
        </header>

        <div className="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-3">
          <div className="flex gap-4">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={draft.showSigns} onChange={(e) => set({ showSigns: e.target.checked })} />
              Signs
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={draft.showSpots} onChange={(e) => set({ showSpots: e.target.checked })} />
              Paid spots
            </label>
          </div>

          {draft.showSigns && (
            <fieldset className="space-y-1">
              <legend className="text-xs uppercase tracking-wide text-gray-500">Sign category</legend>
              {ALL_CATEGORIES.map((c) => (
                <label key={c} className="flex items-center gap-1.5 capitalize">
                  <input type="checkbox" checked={draft.categories.includes(c)} onChange={() => toggleCategory(c)} />
                  {c}
                </label>
              ))}
              <label className="mt-1 flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={draft.reserved === true}
                  onChange={(e) => set({ reserved: e.target.checked ? true : null })}
                />
                Reserved only
              </label>
            </fieldset>
          )}

          <HourFilter value={draft.hour} onChange={(r) => set({ hour: r })} />
          <SelectFilter label="Days" labels={DAY_LABELS} fallback={[1, 5]} value={draft.day} onChange={(r) => set({ day: r })} />
          <SelectFilter label="Months" labels={MONTH_LABELS} fallback={[1, 12]} value={draft.month} onChange={(r) => set({ month: r })} />

          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={draft.notInRange} onChange={(e) => set({ notInRange: e.target.checked })} />
            NOT active in range
          </label>

          <form onSubmit={search} className="space-y-1 pt-1">
            <div className="flex gap-1.5">
              <input
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="Find address…"
                className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1"
              />
              <button type="submit" className="rounded bg-gray-700 px-2.5 py-1 text-white">Go</button>
            </div>
            {addrError && <p className="text-xs text-red-600">Address not found.</p>}
          </form>
        </div>

        <footer className="flex gap-2 border-t border-gray-200 px-4 py-3">
          <button
            type="button"
            onClick={() => onApply(draft)}
            disabled={!dirty}
            className="flex-1 rounded bg-blue-600 py-1.5 font-medium text-white disabled:bg-gray-300"
          >
            Apply{dirty ? ' •' : ''}
          </button>
          <button
            type="button"
            onClick={() => {
              setDraft(DEFAULT_FILTERS)
              onApply(DEFAULT_FILTERS)
            }}
            className="rounded border border-gray-300 px-3 py-1.5"
          >
            Reset
          </button>
        </footer>
      </div>
    </aside>
  )
}

const rowLabel = 'flex items-center gap-1.5 text-xs uppercase tracking-wide text-gray-500'

function HourFilter({
  value,
  onChange,
}: {
  value: Range | null
  onChange: (r: Range | null) => void
}) {
  const [range, setRange] = useState<Range>(value ?? [8, 18])
  const enabled = value !== null
  const clamp = (n: number) => Math.max(0, Math.min(24, Number.isNaN(n) ? 0 : n))
  const update = (r: Range) => {
    setRange(r)
    onChange(r)
  }
  return (
    <div className="space-y-1">
      <label className={rowLabel}>
        <input type="checkbox" checked={enabled} onChange={(e) => onChange(e.target.checked ? range : null)} />
        Hours
      </label>
      <div className="flex items-center gap-1.5 pl-5">
        <input
          type="number"
          min={0}
          max={24}
          value={range[0]}
          disabled={!enabled}
          onChange={(e) => update([clamp(Number(e.target.value)), range[1]])}
          className="w-16 rounded border border-gray-300 px-1 py-0.5 disabled:bg-gray-100 disabled:text-gray-400"
        />
        <span className="text-gray-400">–</span>
        <input
          type="number"
          min={0}
          max={24}
          value={range[1]}
          disabled={!enabled}
          onChange={(e) => update([range[0], clamp(Number(e.target.value))])}
          className="w-16 rounded border border-gray-300 px-1 py-0.5 disabled:bg-gray-100 disabled:text-gray-400"
        />
        <span className="text-gray-500">h</span>
      </div>
    </div>
  )
}

function SelectFilter({
  label,
  labels,
  fallback,
  value,
  onChange,
}: {
  label: string
  labels: string[]
  fallback: Range
  value: Range | null
  onChange: (r: Range | null) => void
}) {
  const [range, setRange] = useState<Range>(value ?? fallback)
  const enabled = value !== null
  const update = (r: Range) => {
    setRange(r)
    onChange(r)
  }
  const options = labels.map((l, i) => (
    <option key={l} value={i + 1}>
      {l}
    </option>
  ))
  return (
    <div className="space-y-1">
      <label className={rowLabel}>
        <input type="checkbox" checked={enabled} onChange={(e) => onChange(e.target.checked ? range : null)} />
        {label}
      </label>
      <div className="flex items-center gap-1.5 pl-5">
        <select
          value={range[0]}
          disabled={!enabled}
          onChange={(e) => update([Number(e.target.value), range[1]])}
          className="min-w-0 flex-1 rounded border border-gray-300 px-1 py-0.5 disabled:bg-gray-100 disabled:text-gray-400"
        >
          {options}
        </select>
        <span className="text-gray-400">–</span>
        <select
          value={range[1]}
          disabled={!enabled}
          onChange={(e) => update([range[0], Number(e.target.value)])}
          className="min-w-0 flex-1 rounded border border-gray-300 px-1 py-0.5 disabled:bg-gray-100 disabled:text-gray-400"
        >
          {options}
        </select>
      </div>
    </div>
  )
}
