import { useState } from 'react'
import { MapView } from './components/MapView'
import { FilterPanel } from './components/FilterPanel'
import { Legend } from './components/Legend'
import { useFilters, toSignParams, toSpotParams } from './lib/filters'
import type { BBox } from './lib/filters'
import { useParkingSigns, usePaidSpots } from './api/endpoints'

const ZERO: BBox = [0, 0, 0, 0]

export default function App() {
  const [applied, apply] = useFilters()
  const [bbox, setBbox] = useState<BBox | null>(null)
  const [flyTo, setFlyTo] = useState<{ longitude: number; latitude: number } | null>(
    null,
  )

  const signs = useParkingSigns(toSignParams(applied, bbox ?? ZERO), {
    query: { enabled: bbox !== null && applied.showSigns },
  })
  const spots = usePaidSpots(toSpotParams(applied, bbox ?? ZERO), {
    query: { enabled: bbox !== null && applied.showSpots },
  })

  const signData = signs.data?.status === 200 ? signs.data.data : undefined
  const spotData = spots.data?.status === 200 ? spots.data.data : undefined

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <MapView
        signs={applied.showSigns ? signData : undefined}
        spots={applied.showSpots ? spotData : undefined}
        flyTo={flyTo}
        onBoundsChange={setBbox}
      />
      <FilterPanel
        applied={applied}
        onApply={apply}
        onLocate={setFlyTo}
        loading={signs.isFetching || spots.isFetching}
      />
      <Legend />
    </div>
  )
}
