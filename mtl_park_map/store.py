"""In-memory query store: curated parquet loaded into polars once at startup.

Queries cover the whole city (~144k signs, ~20k spots); spatial culling and clustering
are the map widget's job, so panning never re-queries.

Time matching cannot be expressed as a columnar ``BETWEEN`` (ranges wrap around
midnight / year end), so it runs in Python — but only once per distinct *rule*, never
per row:

- signs: once per sign *code* (~1.5k), then signs are filtered by ``code_id``;
- spots: once per distinct set of metered periods (spots share regulations), then
  the per-set verdicts are gathered back onto the spots;
- strips: once per code, then each strip's ``code_ids`` list is filtered columnar-style.

Strip geometry is precomputed by the ETL (:mod:`mtl_park_map.etl.strips`), so a strip
query only evaluates time rules.
"""

from collections.abc import Iterable, Mapping, Sequence

import polars as pl

from mtl_park_map import settings
from mtl_park_map.models import SignQuery, SpotQuery, StripQuery
from mtl_park_map.query.intervals import Range, sign_matches
from mtl_park_map.query.overlap import rule_overlaps
from mtl_park_map.query.paid import Period, is_spot_free

# Result-frame contracts shared with the UI.
SIGN_COLUMNS = (
    "sign_id",
    "longitude",
    "latitude",
    "category",
    "is_reserved",
    "arrondissement",
    "description",
    "fleche",
    "arrow_street",
    "arrow_bearing",
)
SPOT_COLUMNS = (
    "place_id",
    "longitude",
    "latitude",
    "is_free",
    "tariff_hourly",
    "spot_type",
    "street",
    "periods",
)
STRIP_COLUMNS = (
    "strip_id",
    "street",
    "side",
    "length_m",
    "longitudes",
    "latitudes",
    "min_lon",
    "min_lat",
    "max_lon",
    "max_lat",
    "pole_longitudes",
    "pole_latitudes",
    "rules",
    "active_code_ids",
    "is_restricted",
    "is_inferred",
)

type _CodeRanges = tuple[list[Range], list[Range], list[Range]]
type _PeriodSet = tuple[Period, ...]


def _to_ranges(structs: Iterable[Mapping[str, float]]) -> list[Range]:
    """Convert parquet ``{start, end}`` structs to ``(start, end)`` tuples.

    Args:
        structs: Range structs as read from ``codes.parquet``.

    Returns:
        The ranges as tuples.
    """
    return [(s["start"], s["end"]) for s in structs]


def _index_period_sets(
    periods_column: Sequence[Sequence[Mapping[str, float | int | str]] | None],
) -> tuple[list[_PeriodSet], list[int], list[list[str]]]:
    """Deduplicate each spot's metered periods into shared, canonical period sets.

    Args:
        periods_column: Per spot, its list of period structs, or ``None`` when the
            place has no paid period (the ETL's left join yields null).

    Returns:
        ``(sets, set_ids, descriptions)``: the distinct period sets, each spot's index
        into ``sets``, and each spot's period descriptions (deduplicated, in order).
    """
    set_index: dict[_PeriodSet, int] = {}
    set_ids: list[int] = []
    descriptions: list[list[str]] = []
    for periods in periods_column:
        periods = periods or []
        # Sorted + deduplicated so equal rules in a different order share one set;
        # `is_spot_free` is an `any(...)`, so order and multiplicity are irrelevant.
        key: _PeriodSet = tuple(
            sorted(
                {
                    (float(p["start_hour"]), float(p["end_hour"]), int(p["weekday_mask"]))
                    for p in periods
                }
            )
        )
        set_ids.append(set_index.setdefault(key, len(set_index)))
        descriptions.append(list(dict.fromkeys(str(p["description"]) for p in periods)))
    return list(set_index), set_ids, descriptions


class Store:
    """Read-only parking data with sign and spot queries.

    Args:
        signs: Curated ``signs.parquet`` frame.
        codes: Curated ``codes.parquet`` frame (one row per sign code).
        spots: Curated ``spots.parquet`` frame.
        strips: Curated ``strips.parquet`` frame (no-parking curb strips).
    """

    def __init__(
        self,
        signs: pl.DataFrame,
        codes: pl.DataFrame,
        spots: pl.DataFrame,
        strips: pl.DataFrame,
    ):
        self._strips = strips
        self._code_ranges: dict[int, _CodeRanges] = {
            row["code_id"]: (
                _to_ranges(row["hour_ranges"]),
                _to_ranges(row["day_ranges"]),
                _to_ranges(row["month_ranges"]),
            )
            for row in codes.iter_rows(named=True)
        }
        # Join descriptions once here so a query is a pure filter + select.
        self._signs = signs.join(
            codes.select("code_id", "description"), on="code_id", how="left"
        )

        sets, set_ids, descriptions = _index_period_sets(spots["periods"].to_list())
        self._period_sets = sets
        self._spot_set_ids = pl.Series("set_id", set_ids, dtype=pl.UInt32)
        self._spots = spots.with_columns(
            pl.Series("periods", descriptions, dtype=pl.List(pl.Utf8))
        )

    @classmethod
    def load(cls) -> "Store":
        """Load the curated parquet artifacts.

        Returns:
            A ready-to-query store.

        Raises:
            FileNotFoundError: If the ETL has not been run yet.
        """
        paths = (
            settings.SIGNS_PARQUET,
            settings.CODES_PARQUET,
            settings.SPOTS_PARQUET,
            settings.STRIPS_PARQUET,
        )
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            raise FileNotFoundError(
                f"Curated data not found ({', '.join(missing)}). "
                f"Build it first with: {settings.ETL_COMMAND}"
            )
        signs, codes, spots, strips = (pl.read_parquet(p) for p in paths)
        return cls(signs, codes, spots, strips)

    def query_signs(self, q: SignQuery) -> pl.DataFrame:
        """Signs matching the query, anywhere in the city.

        Args:
            q: Category, reserved and time-window filters.

        Returns:
            A frame with columns :data:`SIGN_COLUMNS`.
        """
        window = q.window
        matching = [
            code_id
            for code_id, (hours, days, months) in self._code_ranges.items()
            if sign_matches(
                hours, days, months, window.hour, window.day, window.month, q.not_in_range
            )
        ]
        df = self._signs.filter(
            pl.col("category").is_in([c.value for c in q.categories]),
            pl.col("code_id").is_in(matching),
        )
        if q.reserved is not None:
            df = df.filter(pl.col("is_reserved") == q.reserved)
        return df.select(SIGN_COLUMNS)

    def query_spots(self, q: SpotQuery) -> pl.DataFrame:
        """All paid spots with their free/paid status for the query window.

        Args:
            q: The time window; spots are all free unless it has an hour and a day.

        Returns:
            A frame with columns :data:`SPOT_COLUMNS`.
        """
        q_hour, q_day = q.window.hour, q.window.day
        if q_hour is None or q_day is None:
            is_free = pl.repeat(True, self._spots.height, eager=True, dtype=pl.Boolean)
        else:
            free_per_set = pl.Series(
                [is_spot_free(s, q_hour, q_day) for s in self._period_sets],
                dtype=pl.Boolean,
            )
            is_free = free_per_set.gather(self._spot_set_ids)
        return self._spots.with_columns(is_free.alias("is_free")).select(SPOT_COLUMNS)

    def query_strips(self, q: StripQuery) -> pl.DataFrame:
        """All no-parking curb strips with their status for the query window.

        Args:
            q: The time window (a strip is restricted when any of its rules applies
                at some moment of it) and an optional status filter.

        Returns:
            A frame with columns :data:`STRIP_COLUMNS`; ``active_code_ids`` lists the
            rules applying during the window, ``is_restricted`` whether there is any.
        """
        w = q.window
        active = [
            code_id
            for code_id, (hours, days, months) in self._code_ranges.items()
            if rule_overlaps(hours, days, months, w.hour, w.day, w.month)
        ]
        df = self._strips
        if not q.include_inferred:
            df = df.with_columns(
                pl.col("code_ids").list.set_difference("inferred_code_ids"),
                pl.col("rules").list.eval(
                    pl.element().filter(~pl.element().struct.field("inferred"))
                ),
                pl.lit(False).alias("is_inferred"),
            ).filter(pl.col("code_ids").list.len() > 0)
        df = df.with_columns(
            pl.col("code_ids")
            .list.eval(pl.element().filter(pl.element().is_in(active)))
            .alias("active_code_ids")
        ).with_columns((pl.col("active_code_ids").list.len() > 0).alias("is_restricted"))
        if q.restricted is not None:
            df = df.filter(pl.col("is_restricted") == q.restricted)
        return df.select(STRIP_COLUMNS)
