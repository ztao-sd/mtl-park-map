const ITEMS: ReadonlyArray<[string, string]> = [
  ['#2563eb', 'Permitted sign'],
  ['#dc2626', 'Prohibited sign'],
  ['#9ca3af', 'Other sign'],
  ['#16a34a', 'Spot — free now'],
  ['#f59e0b', 'Spot — paid now'],
]

export function Legend() {
  return (
    <div className="absolute bottom-3 right-3 z-10 space-y-1 rounded-lg bg-white/95 px-3 py-2 text-xs text-gray-700 shadow">
      {ITEMS.map(([color, label]) => (
        <div key={label} className="flex items-center gap-2">
          <span
            className="inline-block h-3 w-3 rounded-full border border-white"
            style={{ backgroundColor: color }}
          />
          {label}
        </div>
      ))}
    </div>
  )
}
