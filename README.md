# MTL Park Map

Web app to explore Montreal on-street parking **signs** and **paid parking spots** on an
interactive map, filterable by map viewport, hour / day-of-week / month range, sign
category, and a NOT toggle on the time filter.

A FastAPI backend serves GeoJSON from curated parquet (built offline with polars); a
React + Leaflet single-page app renders it.

> The original PySide6 desktop prototype is preserved under [`legacy/qt_app/`](legacy/qt_app/).

## Architecture

```
data/raw/*.csv ─(polars ETL)→ data/curated/*.parquet ─(load at startup)→ FastAPI (GeoJSON) ─(orval)→ React + MapLibre SPA
```

- **Storage:** curated parquet loaded into in-memory polars DataFrames at startup — no
  database. The data is ~144k signs + ~20k spots, read-only, and rebuilt offline, so a DB
  buys nothing (measured viewport filter: 5–8 ms). The spatial bounding-box cut is a
  columnar polars filter; wraparound time filtering (e.g. `22h–07h`) runs in pure Python on
  the small viewport subset.
- **Sign parsing:** each of the 1,521 distinct sign codes is parsed *once* from its French
  free-text description into hour/day/month ranges, a category
  (`permitted` / `prohibited` / `other`), and a `reserved` flag.
- **Frontend:** Vite + React + TypeScript, Leaflet + leaflet.markercluster (raster
  basemap, no WebGL), TanStack Query via an orval-generated typed client, Tailwind.
  Filter state lives in the URL; layers are off by default (nothing shown until you
  pick a layer and press Apply).

## Run both servers (one command)

```bash
uv sync && uv run python -m mtl_park_map.etl.build   # first time only: build parquet
uv run python dev.py                                 # backend :8000 + frontend :5173
```

Then open <http://localhost:5173> (Ctrl+C stops both). To run them individually, see below.

## Backend

```bash
uv sync
uv run python -m mtl_park_map.etl.build          # raw CSVs -> data/curated/*.parquet
uv run uvicorn mtl_park_map.main:app --port 8000 # API + docs at /docs
uv run pytest                                    # tests
uv run ruff check ; uv run ty check
```

## Frontend

Requires the backend running on `:8000` (the dev server proxies `/api/*` to it).

```bash
cd frontend
npm install
npm run codegen     # regenerate the typed API client from ../openapi.json
npm run dev         # http://localhost:5173
npm run test        # vitest
npm run build
```

Regenerate `openapi.json` after backend schema changes:

```bash
uv run python -c "import json; from mtl_park_map.main import create_app; open('openapi.json','w',encoding='utf-8').write(json.dumps(create_app().openapi(), indent=2))"
```

## Data sources

- **Parking signs** — Montreal open data: `signalisation_stationnement.csv` plus the RPA/RTP
  codification tables.
- **Paid spots** — Agence de mobilité durable open data: `Places`, `Reglementations`,
  `Periodes`, `EmplacementReglementation`, `ReglementationPeriode`.

Raw CSVs live in `data/raw/` (shared with the legacy app); curated parquet is generated into
`data/curated/`.

## Legacy prototype

The PySide6 + Folium + DuckDB desktop prototype is archived under `legacy/qt_app/` and reads
the same shared `data/raw/`. It requires the optional `legacy` dependency group:

```bash
cd legacy/qt_app && uv run --group legacy python -m mtl_park_map.app.qt.main
```
