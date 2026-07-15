import { useEffect } from 'react'
import { MapContainer, TileLayer, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet.markercluster'
import type { SignCollection, SignProperties, SpotCollection, SpotProperties } from '../api/model'
import type { BBox } from '../lib/filters'

const MTL_CENTER: [number, number] = [45.53, -73.57]

const escapeHtml = (s: string) =>
  s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c] ?? c)

const signColor = (p: SignProperties): string =>
  p.category === 'permitted' ? '#2563eb' : p.category === 'prohibited' ? '#dc2626' : '#9ca3af'

const spotColor = (p: SpotProperties): string =>
  p.is_currently_free ? '#16a34a' : '#f59e0b'

const signPopup = (p: SignProperties): string =>
  `<b class="capitalize">${p.category}</b><br>${escapeHtml(p.description)}`

const spotPopup = (p: SpotProperties): string => {
  const status = p.is_currently_free ? 'Free now' : 'Paid now'
  const street = p.street ? `<br>${escapeHtml(p.street)}` : ''
  const periods = (p.periods ?? []).map(escapeHtml).join('<br>')
  return `<b>${status}</b>${street}${periods ? `<hr>${periods}` : ''}`
}

interface PointFeature<P> {
  geometry: { coordinates: number[] }
  properties: P
}

function Clusters<P>({
  features,
  color,
  popup,
}: {
  features: PointFeature<P>[] | undefined
  color: (p: P) => string
  popup: (p: P) => string
}) {
  const map = useMap()
  useEffect(() => {
    if (!features) return
    const group = L.markerClusterGroup({
      chunkedLoading: true,
      disableClusteringAtZoom: 17,
      maxClusterRadius: 50,
    })
    for (const f of features) {
      const [lng, lat] = f.geometry.coordinates
      const marker = L.circleMarker([lat, lng], {
        radius: 5,
        weight: 1,
        color: '#ffffff',
        fillColor: color(f.properties),
        fillOpacity: 0.9,
      })
      marker.bindPopup(popup(f.properties))
      group.addLayer(marker)
    }
    map.addLayer(group)
    return () => {
      map.removeLayer(group)
    }
  }, [features, map, color, popup])
  return null
}

function BoundsWatcher({ onBoundsChange }: { onBoundsChange: (bbox: BBox) => void }) {
  const map = useMap()
  const emit = (m: L.Map) => {
    const b = m.getBounds()
    onBoundsChange([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()])
  }
  useEffect(() => {
    emit(map)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map])
  useMapEvents({ moveend: (e) => emit(e.target) })
  return null
}

function FlyTo({ target }: { target: { longitude: number; latitude: number } | null }) {
  const map = useMap()
  useEffect(() => {
    if (target) map.setView([target.latitude, target.longitude], 16)
  }, [target, map])
  return null
}

interface Props {
  signs?: SignCollection
  spots?: SpotCollection
  flyTo: { longitude: number; latitude: number } | null
  onBoundsChange: (bbox: BBox) => void
}

export function MapView({ signs, spots, flyTo, onBoundsChange }: Props) {
  return (
    <MapContainer
      center={MTL_CENTER}
      zoom={12}
      zoomControl={false}
      style={{ position: 'absolute', inset: 0 }}
    >
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
      />
      <ZoomControl position="topright" />
      <BoundsWatcher onBoundsChange={onBoundsChange} />
      <FlyTo target={flyTo} />
      <Clusters features={spots?.features} color={spotColor} popup={spotPopup} />
      <Clusters features={signs?.features} color={signColor} popup={signPopup} />
    </MapContainer>
  )
}
