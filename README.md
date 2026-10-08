# MTL Park Map

Native desktop app to explore Montreal on-street parking on an interactive map:

- **Parking signs** (parking permitted, no parking, no stopping).
- **Paid parking spots**, free or paid at a chosen time.
- **No-parking curb strips**: each side of each block that a no-parking sign covers,
  coloured by whether a rule applies at a chosen time.

You can filter by hour, day-of-week and month window (or its inverse), sign category
and reserved signs, show signs at any time while spots and strips keep following the
window, and jump to an address.

![MTL Park Map](app_screenshot.png)

Built with PySide6. The map is drawn natively with `QPainter` (no web view): OSM
raster tiles are fetched with QtNetwork, and markers are clustered with polars.

## Architecture

```
data/raw/*.csv ────┐
data/raw/geobase.json ─(polars + shapely ETL)→ data/curated/*.parquet ─(Store, in-process)→ PySide6 UI
                                                                                             └ slippy map widget
```

| Package | Responsibility |
|---|---|
| `mtl_park_map/etl/` | Offline ETL. Parses each distinct sign code **once** from its French free text into hour/day/month ranges, a kind (plain `P` parking, struck-through `\P` no parking, `\A` no stopping, other) and a `reserved` flag. Joins the five paid-spot tables into per-spot metered periods. Snaps sign poles to street segments, turns each sign's left/right arrow into a compass direction along its street (shown in the sign's popup, e.g. "← left · points south-east along Rue Berri"), and synthesizes curb strips (below). |
| `mtl_park_map/query/` | Pure interval math on wrapping axes (`22h–07h`, `SEPT À JUIN`): containment for signs, overlap for strips, and the free/paid status of a metered spot. |
| `mtl_park_map/store.py` | Loads the parquet into polars at startup (~0.3 s) and answers whole-city queries in 2–10 ms. Time matching runs once per sign code / distinct meter rule, never per row. |
| `mtl_park_map/slippy/` | Generic native map widget with no parking knowledge. Covers Web-Mercator projection, an immutable `Viewport`, async tile loading (disk cache + memory LRU), clustered marker layers and polyline layers, hit-testing, the popup and overlays. |
| `mtl_park_map/ui/` | The app: filter panel, legend, popups, background tasks (queries and geocoding never block the UI) and the main window. |

Design notes:

- **No database, no server.** The data is ~118k installed signs, ~20k spots and ~51k
  curb strips, read-only, and rebuilt offline. Each Apply queries the whole city on a
  worker thread. Panning and zooming only re-cull and re-cluster in memory, so they
  never re-query.
- **Clustering** buckets points on the *world* pixel grid of each zoom level. Clusters
  stay stable while panning and are computed once per zoom (~5 ms for 100k points). It
  is disabled from zoom 17, where every sign is drawn individually.
- **Integer zoom**: 256 px tiles are drawn 1:1, so they stay crisp and seam-free. While
  a tile loads, a scaled-up ancestor tile stands in for it.
- **Rotation** lives in the `Viewport` transform, so every projection, hit test and
  cull follows it. Rotated tiles are composited north-up offscreen and drawn as one
  rotated image (no seams between tiles). They are raster images, so their labels
  turn with the map. Markers, cluster counts, the pin and popups stay upright. The
  bearing is saved with the rest of the view.

## No-parking curb strips

The ETL turns no-parking (`\P`) signs into curated curb strips
(`data/curated/strips.parquet`): 50,721 strips covering 2,255 km of curb, of which
1,506 km is inferred from signs without arrows. The app then only evaluates time rules:
a whole-city strip query takes about 5 ms.

1. **Snap**: each sign pole is matched to the nearest street segment within 15 m in
   the city's Géobase network (segments run intersection to intersection), and to a
   side of it. 98.7% of arrowed no-parking panels snap; poles at corners that are about
   as close to a cross street are flagged `ambiguous` (2.5%).
2. **Orient**: signs face the roadway, so a right arrow on the segment's left side
   points along the segment, and on its right side against it. Checked on the
   Plateau: under this convention the two signs bounding short zones (delivery,
   disabled parking) point toward each other 92–100% of the time.
3. **Extend**: a sign's rule runs from its pole in the arrow's direction, up to the
   next sign of the same rule pointing back, or else to the end of the block. A double
   arrow extends both ways.
4. **Split**: each curb side is cut into pieces with a constant set of rules, so
   overlapping rules (e.g. street cleaning plus a permit zone) share a piece.

**Signs without an arrow** (65% of no-parking panels) don't say how far their rule
reaches, so the extent is inferred conservatively. When a rule appears on one side of
a block *only* on arrow-less signs (88% of them; mostly street cleaning), it is taken to
cover the stretch from its first to its last sign there, plus 10 m at each end, clipped
to the block. A lone sign covers 20 m. Where the same rule also has arrowed signs on
that side, the arrow-less ones are repeaters and are ignored. This under-claims on
purpose: where arrows do give the extent, street-cleaning rules cover a median 73% of
their block side. Inferred rules are flagged (`inferred_code_ids`, `rules[].inferred`,
and `is_inferred` when a strip exists by inference alone). The map draws them dashed,
and the popup marks them.

Each strip stores its segment (`segment_id`, `street`, `side`, `start_m`, `end_m`,
`length_m`), a curb-offset polyline (`longitudes`, `latitudes`) with its bounding box,
the source panels and their poles (`sign_ids`, `pole_longitudes`, `pole_latitudes`),
and its rules with their parsed hour/day/month ranges (`code_ids`, `rules`).

A strip is shown as **no parking** when any of its rules applies at *some* moment of
the chosen window (overlap), so a ban starting at 10:30 rules out a 10:00–11:00 stay.
Signs, by contrast, show as active only when the whole window falls inside their
hours.

The **Curb strips** box in the filter panel can limit the map to parkable strips or to
no-parking strips for the chosen window, and can leave out inferred extents.

Current limits:

- No-stopping (`\A`) signs are not used yet.
- Permit zones (`… EXCEPTÉ S3R`) count as no parking, even though permit holders may
  park there.
- Strips stop at block ends.

## Run

```bash
uv sync                                   # also installs the app (editable) into .venv
uv run python -m mtl_park_map.etl.build   # first time, and after refreshing data/raw
uv run mtl-park-map                       # or: uv run python -m mtl_park_map
```

IDEs work too, as long as they use the project's `.venv` interpreter.

On first launch the app shows parking-permitted and no-parking signs, paid spots and
curb strips for the next hour, today. Strips appear from street zoom (15) up.

After that it reopens as you left it: the map view (including rotation), the last
searched address pin, the legend state, your saved places, and every filter except
the **When** box, which always restarts at "now + 1 hour". Filters are remembered when
you press **Apply** or **Reset**, not while you are still editing them.

| Action | How |
|---|---|
| Pan | Drag, or the arrow keys |
| Zoom | Mouse wheel / trackpad (anchored at the cursor), double-click, `+` / `-`, or the on-map buttons |
| Rotate | Right-drag or Ctrl+drag around the centre, `Shift` + `←` / `→` (15° steps), or a trackpad twist (macOS). The compass under the zoom buttons, or `N`, resets north-up. |
| Details | Click a dot or a curb strip (popup; `Esc` or click elsewhere to close) |
| See which signs define a strip | Hover over it: the poles of its signs get amber rings (even with sign markers hidden) and the strip glows |
| Expand a cluster | Click it |
| Find an address | Type it in **Find address** and press Enter |
| Save a place | After finding an address, click **★**; pick it later from **Saved places…** to jump there (**✕** removes it). Clearing the address field removes the pin. |
| Collapse the legend | Click its header (remembered between sessions) |
| Show only the address pin | The eye button under the compass, or `H`: hides every sign, spot and strip without re-querying (press again to show them) |
| Change filters | Edit the panel, then **Apply** (enabled only when something changed). **Reset** returns to the defaults. |

## Development

```bash
uv run pytest            # unit + headless Qt tests (QT_QPA_PLATFORM=offscreen)
uv run ruff check
uv run ty check
```

The tests never touch the network: tiles come from `file://` PNGs written to a temp
dir, the geocoder is a fake, and snapping runs on a synthetic street network.

## Data sources

All raw inputs live in `data/raw/` and are git-ignored when large; download them before
running the ETL.

- **Parking signs**: Montreal open data `signalisation_stationnement.csv`, UTF-8. Only
  installed panels (`DESCRIPTION_REP = Réel`) are used; removed, planned and archived
  ones are skipped.
- **Street network**: Montreal open data
  [Géobase](https://donnees.montreal.ca/dataset/geobase) `geobase.json` (GeoJSON,
  ~43 MB). The ETL prints the download command if it is missing.
- **Paid spots**: Agence de mobilité durable open data (`Places`, `Reglementations`,
  `Periodes`, `EmplacementReglementation`, `ReglementationPeriode`), Windows-1252.

The ETL detects each CSV's encoding and writes the curated parquet to `data/curated/`
(git-ignored).

## Third-party services

- **Map tiles**: [OpenStreetMap](https://www.openstreetmap.org/copyright) standard tiles,
  used under the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
  The app sends an identifying `User-Agent`, honours HTTP caching through an on-disk
  cache, fetches only visible tiles and shows the attribution.
- **Geocoding**: [Nominatim](https://nominatim.org/), one request per user search, with
  results biased to Montreal.
