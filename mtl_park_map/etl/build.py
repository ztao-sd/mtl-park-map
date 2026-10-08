"""Offline ETL: raw Montreal CSVs -> curated parquet consumed by the app.

Run once (and after data refreshes): ``python -m mtl_park_map.etl.build``
"""

import io
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from mtl_park_map import settings
from mtl_park_map.etl.arrows import sign_arrows
from mtl_park_map.etl.dtypes import HOUR_RANGES, INT_RANGES
from mtl_park_map.etl.parse import (
    classify,
    extract_day_month_ranges,
    extract_hour_ranges,
    sign_kind,
)
from mtl_park_map.etl.spots import build_spots
from mtl_park_map.etl.streets import load_streets
from mtl_park_map.etl.strips import build_strips

_INSTALLED_STATUS = "Réel"  # DESCRIPTION_REP of panels physically on the street
_CODES_SCHEMA = {
    "code_id": pl.UInt32,
    "code_rpa": pl.Utf8,
    "description": pl.Utf8,
    "category": pl.Utf8,
    "kind": pl.Utf8,
    "is_reserved": pl.Boolean,
    "hour_ranges": HOUR_RANGES,
    "day_ranges": INT_RANGES,
    "month_ranges": INT_RANGES,
}


def read_raw_csv(path: Path) -> pl.DataFrame:
    """Read a raw source CSV as all-string columns (cast later as needed).

    Sources disagree on encoding: the city's sign CSV is UTF-8 while the AMDS
    paid-spot CSVs are Windows-1252. Strict UTF-8 is tried first: accented
    Windows-1252 text is virtually never valid UTF-8, so a successful decode is
    reliable, whereas decoding UTF-8 as Windows-1252 "succeeds" with mojibake
    (``Côte`` → ``CÃ´te``).

    Args:
        path: The CSV file.

    Returns:
        The table with every column as ``Utf8``.
    """
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")  # also strips a BOM, if any
    except UnicodeDecodeError:
        text = raw.decode(settings.CSV_FALLBACK_ENCODING)
    return pl.read_csv(io.StringIO(text), infer_schema_length=0)


def _struct_list(ranges: Sequence[tuple[float, float]]) -> list[dict[str, float]]:
    """Ranges as parquet ``{start, end}`` structs.

    Args:
        ranges: ``(start, end)`` pairs.

    Returns:
        One dict per range.
    """
    return [{"start": start, "end": end} for start, end in ranges]


def build_signs() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Parse every distinct sign code once and attach it to the sign locations.

    Returns:
        ``(signs, codes)`` frames for ``signs.parquet`` and ``codes.parquet``.
    """
    # The inventory also lists removed ("Enlevé"), planned ("En conception") and
    # archived panels (~18% of rows); only installed ("Réel") ones are on the street.
    raw = read_raw_csv(settings.SIGN_CSV).filter(
        pl.col("DESCRIPTION_REP") == _INSTALLED_STATUS
    )

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
                "kind": sign_kind(description).value,
                "is_reserved": is_reserved,
                "hour_ranges": _struct_list(extract_hour_ranges(description)),
                "day_ranges": _struct_list(days),
                "month_ranges": _struct_list(months),
            }
        )
    codes_df = pl.DataFrame(parsed, schema=_CODES_SCHEMA)

    signs = (
        raw.select(
            "POTEAU_ID_POT", "CODE_RPA", "Longitude", "Latitude", "NOM_ARROND", "FLECHE_PAN"
        )
        .drop_nulls(["CODE_RPA", "Longitude", "Latitude"])
        .with_columns(
            # Panels on the same pole share its id and position.
            pl.col("POTEAU_ID_POT").cast(pl.Int64).alias("pole_id"),
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
            "pole_id",
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
    """Build all curated parquet files and print summary counts."""
    if not settings.GEOBASE_JSON.exists():
        raise SystemExit(
            f"Missing {settings.GEOBASE_JSON}. Download the city's road network first:\n"
            f'  curl -L -o "{settings.GEOBASE_JSON}" "{settings.GEOBASE_URL}"'
        )
    settings.CURATED_DIR.mkdir(parents=True, exist_ok=True)

    signs, codes = build_signs()
    spots = build_spots(read_raw_csv)
    network = load_streets(settings.GEOBASE_JSON)
    strips, strip_report = build_strips(signs, codes, network)
    # Where each arrowed sign points on the map (street + compass bearing).
    signs = signs.join(sign_arrows(signs, network), on="sign_id", how="left")

    signs.write_parquet(settings.SIGNS_PARQUET)
    codes.write_parquet(settings.CODES_PARQUET)
    spots.write_parquet(settings.SPOTS_PARQUET)
    strips.write_parquet(settings.STRIPS_PARQUET)

    print(f"codes:  {codes.height}")
    print(f"signs:  {signs.height}")
    print(signs["category"].value_counts().sort("category"))
    reserved = int(signs["is_reserved"].sum())
    print(f"reserved signs: {reserved}")
    oriented = signs["arrow_bearing"].is_not_null().sum()
    print(f"signs with an arrow oriented on the map: {oriented}")
    print(f"spots:  {spots.height}")
    with_periods = spots.filter(pl.col("periods").is_not_null()).height
    print(f"spots with >=1 paid period: {with_periods}")
    r = strip_report
    print(
        f"no-parking strips: {r.strips} ({r.total_km:.0f} km) from {r.panels_snapped}/"
        f"{r.panels} arrowed no-parking panels ({r.panels_snapped / max(r.panels, 1):.1%} "
        f"snapped); "
        f"{r.poles_ambiguous} of {r.poles} poles at ambiguous corners"
    )
    print(
        f"  of which {r.inferred_km:.0f} km inferred from {r.inferred_panels} "
        f"no-parking panels without arrows"
    )


if __name__ == "__main__":
    main()
