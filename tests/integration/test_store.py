from pathlib import Path

import polars as pl
import pytest

from mtl_park_map import settings
from mtl_park_map.enums import SignCategory
from mtl_park_map.models import SignQuery, SpotQuery, TimeWindow
from mtl_park_map.store import SIGN_COLUMNS, SPOT_COLUMNS, Store

WEEKDAY_MORNING = TimeWindow(hour=(10.0, 11.0), day=(1, 5))
WEEKDAY_EVENING = TimeWindow(hour=(20.0, 21.0), day=(1, 5))


def _ids(df: pl.DataFrame) -> set[int]:
    return set(df["sign_id"].to_list())


def test_sign_result_columns(store: Store):
    assert store.query_signs(SignQuery()).columns == list(SIGN_COLUMNS)


def test_whole_dataset_is_queried_no_bbox(store: Store):
    # sign 3 lies outside Montreal; culling is the map's job, not the store's
    assert 3 in _ids(store.query_signs(SignQuery()))


def test_default_categories_permitted_only(store: Store):
    df = store.query_signs(SignQuery())
    assert set(df["category"].to_list()) == {"permitted"}
    assert _ids(df) == {0, 1, 3}


def test_multiple_categories(store: Store):
    q = SignQuery(categories=frozenset({SignCategory.permitted, SignCategory.prohibited}))
    assert _ids(store.query_signs(q)) == {0, 1, 2, 3}


def test_no_categories_returns_nothing(store: Store):
    assert store.query_signs(SignQuery(categories=frozenset())).is_empty()


def test_reserved_filter(store: Store):
    assert _ids(store.query_signs(SignQuery(reserved=True))) == {1}
    assert _ids(store.query_signs(SignQuery(reserved=False))) == {0, 3}


def test_description_and_arrondissement_are_joined(store: Store):
    row = store.query_signs(SignQuery()).filter(pl.col("sign_id") == 0).row(0, named=True)
    assert row["description"] == r"\P 9h-17h LUN A VEN"
    assert row["arrondissement"] == "A"


def test_time_filter_hits_and_misses(store: Store):
    assert {0, 1} <= _ids(store.query_signs(SignQuery(window=WEEKDAY_MORNING)))
    off = _ids(store.query_signs(SignQuery(window=WEEKDAY_EVENING)))
    assert 0 not in off and 1 in off  # 9-17 sign inactive; always-on still on


def test_not_in_range_inverts(store: Store):
    ids = _ids(store.query_signs(SignQuery(window=WEEKDAY_EVENING, not_in_range=True)))
    assert 0 in ids and 1 not in ids


def test_spot_result_columns(store: Store):
    assert store.query_spots(SpotQuery()).columns == list(SPOT_COLUMNS)


def test_spots_free_and_paid(store: Store):
    df = store.query_spots(SpotQuery(window=WEEKDAY_MORNING))
    free = dict(zip(df["place_id"].to_list(), df["is_free"].to_list(), strict=True))
    assert free == {"S1": False, "S2": True, "S3": True}


def test_spots_free_outside_metered_hours(store: Store):
    df = store.query_spots(SpotQuery(window=WEEKDAY_EVENING))
    assert df["is_free"].to_list() == [True, True, True]


def test_spots_all_free_without_hour_and_day(store: Store):
    # free/paid is only meaningful with both an hour and a day window
    df = store.query_spots(SpotQuery(window=TimeWindow(hour=(10.0, 11.0))))
    assert df["is_free"].all()


def test_spot_periods_are_deduplicated_descriptions(store: Store):
    df = store.query_spots(SpotQuery())
    periods = dict(zip(df["place_id"].to_list(), df["periods"].to_list(), strict=True))
    assert periods == {"S1": ["LUN-VEN 9-18"], "S2": [], "S3": []}


def test_load_missing_parquet_names_etl_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "SIGNS_PARQUET", tmp_path / "missing.parquet")
    with pytest.raises(FileNotFoundError, match="mtl_park_map.etl.build"):
        Store.load()
