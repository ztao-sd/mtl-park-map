"""Offline ETL: raw Montreal CSVs -> curated parquet consumed by the API.

Run once (and after data refreshes): ``python -m mtl_park_map.etl.build``
"""

import io
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from mtl_park_map import settings
from mtl_park_map.etl.parse import (
    classify,
    extract_day_month_ranges,
    extract_hour_ranges,
)
from mtl_park_map.etl.spots import build_spots

_HOUR_RANGE = pl.List(pl.Struct({"start": pl.Float64, "end": pl.Float64}))
_INT_RANGE = pl.List(pl.Struct({"start": pl.Int64, "end": pl.Int64}))
_CODES_SCHEMA = {
    "code_id": pl.UInt32,
    "code_rpa": pl.Utf8,
    "description": pl.Utf8,
    "category": pl.Utf8,
    "is_reserved": pl.Boolean,
    "hour_ranges": _HOUR_RANGE,
    "day_ranges": _INT_RANGE,
    "month_ranges": _INT_RANGE,
}


def read_cp1252_csv(path: Path) -> pl.DataFrame:
    """Read a Windows-French CSV as all-string columns (cast later as needed)."""
    utf8 = path.read_bytes().decode(settings.CSV_ENCODING).encode("utf-8")
    return pl.read_csv(io.BytesIO(utf8), infer_schema_length=0)


def _struct_list(ranges: Sequence[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"start": start, "end": end} for start, end in ranges]


def build_signs() -> tuple[pl.DataFrame, pl.DataFrame]:
    raw = read_cp1252_csv(settings.SIGN_CSV)

    codes = (
        raw.select("CODE_RPA", "DESCRIPTION_RPA")
        .drop_nulls("CODE_RPA")
        .unique()
        .sort("CODE_RPA")
        .with_row_index("code_id")
    )

    parsed: list[dict] = []
    for row in codes.iter_rows(named=True):
        description = row["DESCRIPTION_RPA"] or ""
        category, is_reserved = classify(description)
        days, months = extract_day_month_ranges(description)
        parsed.append(
            {
                "code_id": row["code_id"],
                "code_rpa": row["CODE_RPA"],
                "description": description,
                "category": category.value,
                "is_reserved": is_reserved,
                "hour_ranges": _struct_list(extract_hour_ranges(description)),
                "day_ranges": _struct_list(days),
                "month_ranges": _struct_list(months),
            }
        )
    codes_df = pl.DataFrame(parsed, schema=_CODES_SCHEMA)

    signs = (
        raw.select("CODE_RPA", "Longitude", "Latitude", "NOM_ARROND", "FLECHE_PAN")
        .drop_nulls(["CODE_RPA", "Longitude", "Latitude"])
        .with_columns(
            pl.col("Longitude").cast(pl.Float64).alias("longitude"),
            pl.col("Latitude").cast(pl.Float64).alias("latitude"),
        )
        .join(
            codes_df.select("code_id", "code_rpa", "category", "is_reserved"),
            left_on="CODE_RPA",
            right_on="code_rpa",
            how="inner",
        )
        .rename({"NOM_ARROND": "arrondissement", "FLECHE_PAN": "fleche"})
        .with_row_index("sign_id")
        .select(
            "sign_id",
            "longitude",
            "latitude",
            "arrondissement",
            "fleche",
            "code_id",
            "category",
            "is_reserved",
        )
    )
    return signs, codes_df


def main() -> None:
    settings.CURATED_DIR.mkdir(parents=True, exist_ok=True)

    signs, codes = build_signs()
    spots = build_spots(read_cp1252_csv)

    signs.write_parquet(settings.SIGNS_PARQUET)
    codes.write_parquet(settings.CODES_PARQUET)
    spots.write_parquet(settings.SPOTS_PARQUET)

    print(f"codes:  {codes.height}")
    print(f"signs:  {signs.height}")
    print(signs["category"].value_counts().sort("category"))
    reserved = int(signs["is_reserved"].sum())
    print(f"reserved signs: {reserved}")
    print(f"spots:  {spots.height}")
    with_periods = spots.filter(pl.col("periods").is_not_null()).height
    print(f"spots with >=1 paid period: {with_periods}")


if __name__ == "__main__":
    main()
