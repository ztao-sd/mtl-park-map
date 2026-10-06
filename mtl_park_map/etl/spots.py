"""Paid-spot ETL: join the five relational source CSVs into per-spot period lists.

Ports the DuckDB join from the prototype's ``parking_spot_analyzer.py`` to polars.
Unlike the prototype it (a) keeps *all* places via a left join — a place with no
paid periods is simply always-free rather than dropped — and (b) includes every
weekday column (the prototype's SQL omitted Tuesday).
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl

from mtl_park_map import settings

_WEEKDAY_BITS = [
    ("bLun", 1),
    ("bMar", 2),
    ("bMer", 4),
    ("bJeu", 8),
    ("bVen", 16),
    ("bSam", 32),
    ("bDim", 64),
]


def _hhmmss_to_hour(col: str) -> pl.Expr:
    return pl.col(col).str.slice(0, 2).cast(pl.Float64) + pl.col(col).str.slice(
        3, 2
    ).cast(pl.Float64) / 60.0


def _weekday_mask() -> pl.Expr:
    expr = pl.lit(0)
    for col, weight in _WEEKDAY_BITS:
        expr = expr + pl.col(col).cast(pl.Int64) * weight
    return expr.alias("weekday_mask")


def build_spots(read_csv: Callable[[Path], pl.DataFrame]) -> pl.DataFrame:
    places = read_csv(settings.PLACES_CSV)
    place_link = read_csv(settings.EMPLACEMENT_CSV)
    period_link = read_csv(settings.REGLEMENTATION_PERIODE_CSV)
    periods = read_csv(settings.PERIODES_CSV)

    periods = periods.with_columns(
        _hhmmss_to_hour("dtHeureDebut").alias("start_hour"),
        _hhmmss_to_hour("dtHeureFin").alias("end_hour"),
        _weekday_mask(),
    )

    per_place = (
        place_link.join(
            period_link, left_on="sCodeAutocollant", right_on="sCode", how="inner"
        )
        .join(periods, left_on="noPeriode", right_on="nID", how="inner")
        .group_by("sNoEmplacement")
        .agg(
            pl.struct(
                start_hour="start_hour",
                end_hour="end_hour",
                weekday_mask="weekday_mask",
                description="sDescription",
            ).alias("periods")
        )
    )

    return (
        places.with_columns(
            pl.col("nPositionCentreLongitude").cast(pl.Float64).alias("longitude"),
            pl.col("nPositionCentreLatitude").cast(pl.Float64).alias("latitude"),
            pl.col("nTarifHoraire").cast(pl.Float64, strict=False).alias("tariff_hourly"),
        )
        .select("sNoPlace", "longitude", "latitude", "tariff_hourly", "sType", "sNomRue")
        .drop_nulls(["longitude", "latitude"])
        .join(per_place, left_on="sNoPlace", right_on="sNoEmplacement", how="left")
        .rename({"sNoPlace": "place_id", "sType": "spot_type", "sNomRue": "street"})
    )
