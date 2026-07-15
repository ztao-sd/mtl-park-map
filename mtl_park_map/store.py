"""In-memory query store: curated parquet loaded into polars at startup.

The spatial bounding-box cut is a columnar polars filter. Time matching is done in
Python (wraparound ranges are not expressible as a SQL/columnar BETWEEN), but only
once per *code* (~1.5k) rather than per sign: the set of codes matching the time
filter is computed first, then signs are filtered by ``code_id`` columnar-style, so
cost is independent of how many signs the viewport contains.
"""

from collections.abc import Iterable, Sequence

import polars as pl

from mtl_park_map import settings
from mtl_park_map.enums import SignCategory
from mtl_park_map.query.intervals import Range, sign_matches
from mtl_park_map.query.paid import Period, is_spot_free
from mtl_park_map.schemas import BBox


def _to_ranges(structs: Iterable[dict]) -> list[Range]:
    return [(s["start"], s["end"]) for s in structs]


class Store:
    def __init__(self, signs: pl.DataFrame, codes: pl.DataFrame, spots: pl.DataFrame):
        self._signs = signs
        self._spots = spots
        self._code_ranges: dict[int, tuple[list[Range], list[Range], list[Range]]] = {}
        self._code_desc: dict[int, str] = {}
        for row in codes.iter_rows(named=True):
            self._code_ranges[row["code_id"]] = (
                _to_ranges(row["hour_ranges"]),
                _to_ranges(row["day_ranges"]),
                _to_ranges(row["month_ranges"]),
            )
            self._code_desc[row["code_id"]] = row["description"]

    @classmethod
    def load(cls) -> "Store":
        return cls(
            pl.read_parquet(settings.SIGNS_PARQUET),
            pl.read_parquet(settings.CODES_PARQUET),
            pl.read_parquet(settings.SPOTS_PARQUET),
        )

    def query_signs(
        self,
        bbox: BBox,
        categories: Sequence[SignCategory],
        reserved: bool | None,
        q_hour: Range | None,
        q_day: Range | None,
        q_month: Range | None,
        not_in_range: bool,
    ) -> dict:
        matching = [
            code_id
            for code_id, (hours, days, months) in self._code_ranges.items()
            if sign_matches(hours, days, months, q_hour, q_day, q_month, not_in_range)
        ]
        min_lon, min_lat, max_lon, max_lat = bbox
        df = self._signs.filter(
            pl.col("longitude").is_between(min_lon, max_lon),
            pl.col("latitude").is_between(min_lat, max_lat),
            pl.col("category").is_in([c.value for c in categories]),
            pl.col("code_id").is_in(matching),
        )
        if reserved is not None:
            df = df.filter(pl.col("is_reserved") == reserved)
        return self._signs_geojson(df)

    def _signs_geojson(self, df: pl.DataFrame) -> dict:
        features = [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [row["longitude"], row["latitude"]],
                },
                "properties": {
                    "sign_id": row["sign_id"],
                    "category": row["category"],
                    "is_reserved": row["is_reserved"],
                    "arrondissement": row["arrondissement"],
                    "description": self._code_desc.get(row["code_id"], ""),
                },
            }
            for row in df.iter_rows(named=True)
        ]
        return {"type": "FeatureCollection", "features": features}

    def query_spots(
        self, bbox: BBox, q_hour: Range | None, q_day: Range | None
    ) -> dict:
        min_lon, min_lat, max_lon, max_lat = bbox
        df = self._spots.filter(
            pl.col("longitude").is_between(min_lon, max_lon),
            pl.col("latitude").is_between(min_lat, max_lat),
        )
        compute_free = q_hour is not None and q_day is not None
        features = []
        for row in df.iter_rows(named=True):
            periods = row["periods"] or []
            if compute_free:
                tuples: list[Period] = [
                    (p["start_hour"], p["end_hour"], p["weekday_mask"]) for p in periods
                ]
                free = is_spot_free(tuples, q_hour, q_day)  # type: ignore[arg-type]
            else:
                free = True
            descriptions = list(dict.fromkeys(p["description"] for p in periods))
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [row["longitude"], row["latitude"]],
                    },
                    "properties": {
                        "place_id": row["place_id"],
                        "is_currently_free": free,
                        "tariff_hourly": row["tariff_hourly"],
                        "spot_type": row["spot_type"],
                        "street": row["street"],
                        "periods": descriptions,
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}
