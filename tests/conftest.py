"""Shared fixtures: a tiny in-memory ``Store`` and headless Qt configuration."""

import os

# Must be set before any QApplication exists (pytest-qt creates it lazily), so Qt
# tests run headless on CI and never steal focus on a developer machine.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import polars as pl  # noqa: E402
import pytest  # noqa: E402

from mtl_park_map.etl.strips import STRIP_SCHEMA  # noqa: E402
from mtl_park_map.store import Store  # noqa: E402

_HOUR = pl.List(pl.Struct({"start": pl.Float64, "end": pl.Float64}))
_INT = pl.List(pl.Struct({"start": pl.Int64, "end": pl.Int64}))
CODES_SCHEMA = {
    "code_id": pl.UInt32,
    "code_rpa": pl.Utf8,
    "description": pl.Utf8,
    "category": pl.Utf8,
    "is_reserved": pl.Boolean,
    "hour_ranges": _HOUR,
    "day_ranges": _INT,
    "month_ranges": _INT,
}
SIGNS_SCHEMA = {
    "sign_id": pl.UInt32,
    "longitude": pl.Float64,
    "latitude": pl.Float64,
    "arrondissement": pl.Utf8,
    "fleche": pl.Utf8,
    "code_id": pl.UInt32,
    "category": pl.Utf8,
    "is_reserved": pl.Boolean,
    "arrow_street": pl.Utf8,
    "arrow_bearing": pl.Float64,
}
_PERIODS = pl.List(
    pl.Struct(
        {
            "start_hour": pl.Float64,
            "end_hour": pl.Float64,
            "weekday_mask": pl.Int64,
            "description": pl.Utf8,
        }
    )
)
SPOTS_SCHEMA = {
    "place_id": pl.Utf8,
    "longitude": pl.Float64,
    "latitude": pl.Float64,
    "tariff_hourly": pl.Float64,
    "spot_type": pl.Utf8,
    "street": pl.Utf8,
    "periods": _PERIODS,
}

MON_FRI = 0b0011111


def make_codes() -> pl.DataFrame:
    """Sign codes: weekday 9–17 parking (0), always-on reserved parking (1), no
    stopping (2), and the no-parking rules used by the strips: Tuesdays 8–11 (3) and
    at all times (4).

    Returns:
        A frame matching the curated ``codes.parquet`` schema.
    """
    return pl.DataFrame(
        [
            {
                "code_id": 0,
                "code_rpa": "P1",
                "description": "P 60 min 9h-17h LUN A VEN",
                "category": "permitted",
                "is_reserved": False,
                "hour_ranges": [{"start": 9.0, "end": 17.0}],
                "day_ranges": [{"start": 1, "end": 5}],
                "month_ranges": [],
            },
            {
                "code_id": 1,
                "code_rpa": "P2",
                "description": "P RESERVE EN TOUT TEMPS",
                "category": "permitted",
                "is_reserved": True,
                "hour_ranges": [],
                "day_ranges": [],
                "month_ranges": [],
            },
            {
                "code_id": 2,
                "code_rpa": "A1",
                "description": r"\A EN TOUT TEMPS",
                "category": "prohibited",
                "is_reserved": False,
                "hour_ranges": [],
                "day_ranges": [],
                "month_ranges": [],
            },
            {
                "code_id": 3,
                "code_rpa": "NP1",
                "description": r"\P 8h-11h MARDI",
                "category": "prohibited",
                "is_reserved": False,
                "hour_ranges": [{"start": 8.0, "end": 11.0}],
                "day_ranges": [{"start": 2, "end": 2}],
                "month_ranges": [],
            },
            {
                "code_id": 4,
                "code_rpa": "NP2",
                "description": r"\P EN TOUT TEMPS",
                "category": "prohibited",
                "is_reserved": False,
                "hour_ranges": [],
                "day_ranges": [],
                "month_ranges": [],
            },
        ],
        schema=CODES_SCHEMA,
    )


def make_signs() -> pl.DataFrame:
    """Four signs; sign 3 is far outside Montreal (it must still be returned).

    Returns:
        A frame matching the curated ``signs.parquet`` schema.
    """
    rows = [
        (0, -73.560, 45.500, "A", 0, "permitted", False),
        (1, -73.561, 45.501, "A", 1, "permitted", True),
        (2, -73.562, 45.502, "A", 2, "prohibited", False),
        (3, -70.000, 40.000, "B", 0, "permitted", False),
    ]
    return pl.DataFrame(
        [
            {
                "sign_id": sign_id,
                "longitude": lon,
                "latitude": lat,
                "arrondissement": arrondissement,
                "fleche": "3" if sign_id == 0 else "0",
                "code_id": code_id,
                "category": category,
                "is_reserved": is_reserved,
                # sign 0 points east along its street; the others have no arrow
                "arrow_street": "Rue X" if sign_id == 0 else None,
                "arrow_bearing": 90.0 if sign_id == 0 else None,
            }
            for sign_id, lon, lat, arrondissement, code_id, category, is_reserved in rows
        ],
        schema=SIGNS_SCHEMA,
    )


def make_spots() -> pl.DataFrame:
    """Three spots: metered Mon–Fri 9–18 (twice, same rule), a never-metered one.

    Returns:
        A frame matching the curated ``spots.parquet`` schema; S3 has a null
        ``periods`` list, which is what the ETL's left join yields for a place with
        no paid periods.
    """
    period = {
        "start_hour": 9.0,
        "end_hour": 18.0,
        "weekday_mask": MON_FRI,
        "description": "LUN-VEN 9-18",
    }
    return pl.DataFrame(
        [
            {
                "place_id": "S1",
                "longitude": -73.560,
                "latitude": 45.500,
                "tariff_hourly": 300.0,
                "spot_type": "Normal",
                "street": "Rue X",
                "periods": [period, period],
            },
            {
                "place_id": "S2",
                "longitude": -73.561,
                "latitude": 45.501,
                "tariff_hourly": None,
                "spot_type": "Normal",
                "street": "Rue Y",
                "periods": [],
            },
            {
                "place_id": "S3",
                "longitude": -73.562,
                "latitude": 45.502,
                "tariff_hourly": 250.0,
                "spot_type": "Normal",
                "street": "Rue Z",
                "periods": None,
            },
        ],
        schema=SPOTS_SCHEMA,
    )


def make_strips() -> pl.DataFrame:
    """Three curb strips near the signs: Tuesday-morning ban (0); permanent ban plus an
    inferred Tuesday-morning ban on the other side (1); and a Tuesday-morning ban on
    Rue Y known only from signs without arrows (2, inferred).

    Returns:
        A frame matching the curated ``strips.parquet`` schema.
    """
    rules = {
        row["code_id"]: row
        for row in make_codes()
        .select("code_id", "description", "hour_ranges", "day_ranges", "month_ranges")
        .iter_rows(named=True)
    }
    rows = [
        # (segment_id, street, side, (lon0, lat0), (lon1, lat1), code_ids, inferred ids)
        (1, "Rue X", 1, (-73.5600, 45.5001), (-73.5594, 45.5001), [3], []),
        (1, "Rue X", -1, (-73.5600, 45.4999), (-73.5594, 45.4999), [3, 4], [3]),
        (2, "Rue Y", 1, (-73.5615, 45.5015), (-73.5615, 45.5020), [3], [3]),
    ]
    return pl.DataFrame(
        [
            {
                "strip_id": i,
                "segment_id": seg,
                "street": street,
                "side": side,
                "start_m": 0.0,
                "end_m": 47.0,
                "length_m": 47.0,
                "longitudes": [a[0], b[0]],
                "latitudes": [a[1], b[1]],
                "min_lon": min(a[0], b[0]),
                "min_lat": min(a[1], b[1]),
                "max_lon": max(a[0], b[0]),
                "max_lat": max(a[1], b[1]),
                "code_ids": codes,
                "inferred_code_ids": inferred,
                "is_inferred": len(inferred) == len(codes),
                # strip 0 is bounded by sign 0's pole; the others have no signs here
                "sign_ids": [0] if i == 0 else [],
                "pole_longitudes": [-73.560] if i == 0 else [],
                "pole_latitudes": [45.500] if i == 0 else [],
                "rules": [{**rules[c], "inferred": c in inferred} for c in codes],
            }
            for i, (seg, street, side, a, b, codes, inferred) in enumerate(rows)
        ],
        schema=STRIP_SCHEMA,
    )


type StoreFrames = tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]


@pytest.fixture
def store_frames() -> StoreFrames:
    """The tiny ``(signs, codes, spots, strips)`` fixture frames above."""
    return make_signs(), make_codes(), make_spots(), make_strips()


@pytest.fixture
def store(store_frames: StoreFrames) -> Store:
    """A ``Store`` over the tiny fixture frames above."""
    return Store(*store_frames)
