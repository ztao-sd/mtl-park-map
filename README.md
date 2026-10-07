# MTL Park Map

Native desktop app to explore Montreal on-street parking **signs** and **paid parking
spots** on an interactive map. You can filter by hour, day-of-week and month window
(or its inverse), sign category and reserved signs, and jump to an address.

![MTL Park Map](app_screenshot.png)

Built with PySide6. The map is drawn natively with `QPainter` (no web view): OSM
raster tiles are fetched with QtNetwork, and markers are clustered with polars.

## Architecture

```
data/raw/*.csv ─(polars ETL)→ data/curated/*.parquet ─(Store, in-process)→ PySide6 UI
                                                                            └ slippy map widget (QPainter + OSM tiles)
```

| Package | Responsibility |
|---|---|
| `mtl_park_map/etl/` | Offline ETL. Parses each of the 1,521 distinct sign codes **once** from its French free text into hour/day/month ranges, a category (`permitted` / `prohibited` / `other`) and a `reserved` flag. Joins the five paid-spot tables into per-spot metered periods. |
| `mtl_park_map/query/` | Pure interval math: wraparound ranges (`22h–07h`, `SEPT À JUIN`) and the free/paid status of a metered spot. |
| `mtl_park_map/store.py` | Loads the parquet into polars at startup (~0.3 s) and answers whole-city queries in 5–10 ms. Time matching runs once per sign code / distinct meter rule, never per row. |
| `mtl_park_map/slippy/` | Generic native map widget with no parking knowledge. Covers Web-Mercator projection, an immutable `Viewport`, async tile loading (disk cache + memory LRU), grid clustering, hit-testing, the popup and overlays. |
| `mtl_park_map/ui/` | The app: filter panel, legend, popups, background tasks (queries and geocoding never block the UI) and the main window. |

Design notes:

- **No database, no server.** The data is ~144k signs and ~20k spots, read-only, and
  rebuilt offline. Each Apply queries the whole city on a worker thread. Panning and
  zooming only re-cull and re-cluster in memory, so they never re-query.
- **Clustering** buckets points on the *world* pixel grid of each zoom level. Clusters
  stay stable while panning and are computed once per zoom (~5 ms for 100k points). It
  is disabled from zoom 17, where every sign is drawn individually.
- **Integer zoom**: 256 px tiles are drawn 1:1, so they stay crisp and seam-free. While
  a tile loads, a scaled-up ancestor tile stands in for it.

## Run

```bash
uv sync                                   # also installs the app (editable) into .venv
uv run python -m mtl_park_map.etl.build   # first time, and after refreshing data/raw
uv run mtl-park-map                       # or: uv run python -m mtl_park_map
```

IDEs work too, as long as they use the project's `.venv` interpreter.

On launch the app shows permitted signs and paid spots for the next hour, today. The
map reopens where you left it.

| Action | How |
|---|---|
| Pan | Drag, or the arrow keys |
| Zoom | Mouse wheel / trackpad (anchored at the cursor), double-click, `+` / `-`, or the on-map buttons |
| Marker details | Click a dot (popup; `Esc` or click elsewhere to close) |
| Expand a cluster | Click it |
| Find an address | Type it in **Find address** and press Enter |
| Change filters | Edit the panel, then **Apply** (enabled only when something changed). **Reset** returns to the defaults. |

## Development

```bash
uv run pytest            # unit + headless Qt tests (QT_QPA_PLATFORM=offscreen)
uv run ruff check
uv run ty check
```

The Qt tests never touch the network: tiles come from `file://` PNGs written to a temp
dir, and the geocoder is a fake.

## Data sources

- **Parking signs**: Montreal open data `signalisation_stationnement.csv`, UTF-8. It is
  large and git-ignored, so download it into `data/raw/` before running the ETL.
- **Paid spots**: Agence de mobilité durable open data (`Places`, `Reglementations`,
  `Periodes`, `EmplacementReglementation`, `ReglementationPeriode`), Windows-1252.

Raw CSVs live in `data/raw/`; the ETL detects each file's encoding and writes the
curated parquet to `data/curated/` (git-ignored).

## Third-party services

- **Map tiles**: [OpenStreetMap](https://www.openstreetmap.org/copyright) standard tiles,
  used under the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
  The app sends an identifying `User-Agent`, honours HTTP caching through an on-disk
  cache, fetches only visible tiles and shows the attribution.
- **Geocoding**: [Nominatim](https://nominatim.org/), one request per user search, with
  results biased to Montreal.
