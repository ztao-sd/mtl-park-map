"""Paths and application-wide constants."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CURATED_DIR = DATA_DIR / "curated"

# Raw CSV sources.
SIGN_CSV = RAW_DIR / "signalisation_stationnement.csv"
PLACES_CSV = RAW_DIR / "Places.csv"
REGULATIONS_CSV = RAW_DIR / "Reglementations.csv"
PERIODES_CSV = RAW_DIR / "Periodes.csv"
EMPLACEMENT_CSV = RAW_DIR / "EmplacementReglementation.csv"
REGLEMENTATION_PERIODE_CSV = RAW_DIR / "ReglementationPeriode.csv"

# Curated parquet artifacts produced by `python -m mtl_park_map.etl.build`.
SIGNS_PARQUET = CURATED_DIR / "signs.parquet"
CODES_PARQUET = CURATED_DIR / "codes.parquet"
SPOTS_PARQUET = CURATED_DIR / "spots.parquet"
ETL_COMMAND = "uv run python -m mtl_park_map.etl.build"

# Raw CSVs are UTF-8 or (the AMDS paid-spot files) Windows-1252.
CSV_FALLBACK_ENCODING = "cp1252"

APP_NAME = "MTL Park Map"
APP_VERSION = "0.1.0"
# OSM's tile and Nominatim usage policies require an identifying User-Agent.
USER_AGENT = f"MTLParkMap/{APP_VERSION} (+https://github.com/ztao-sd/mtl-park-map)"

# Montreal bounding box (min_lon, min_lat, max_lon, max_lat): the map's pan limit and
# the geocoder's search bias.
MTL_BOUNDS = (-73.97, 45.41, -73.48, 45.70)
DEFAULT_CENTER = (-73.57, 45.53)  # (lon, lat)
MIN_ZOOM = 11
MAX_ZOOM = 19
DEFAULT_ZOOM = 13
# Zoom used when jumping to a geocoded address (street level).
ADDRESS_ZOOM = 17

# Standard OSM raster tiles. Usage policy: identifying User-Agent, honour HTTP caching,
# no bulk prefetching, visible attribution.
TILE_URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_ATTRIBUTION = (
    '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
)
