from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CURATED_DIR = DATA_DIR / "curated"

# Raw CSV sources (shared with legacy/qt_app).
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

# Raw CSVs are Windows-French encoded.
CSV_ENCODING = "cp1252"

# CORS origins for the Vite dev server.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Montreal bounding box (min_lon, min_lat, max_lon, max_lat) — from the prototype.
MTL_BOUNDS = (-73.97, 45.41, -73.48, 45.70)
