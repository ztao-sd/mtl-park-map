"""Polars dtypes shared by the curated parquet schemas."""

import polars as pl

# Lists of (start, end) ranges: fractional hours, or 1-based weekdays / months.
HOUR_RANGES = pl.List(pl.Struct({"start": pl.Float64, "end": pl.Float64}))
INT_RANGES = pl.List(pl.Struct({"start": pl.Int64, "end": pl.Int64}))
