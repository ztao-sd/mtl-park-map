from pathlib import Path

import polars as pl
import pytest

from mtl_park_map import settings
from mtl_park_map.enums import SignCategory
from mtl_park_map.models import SignQuery, SpotQuery, StripQuery, TimeWindow
from mtl_park_map.store import SIGN_COLUMNS, SPOT_COLUMNS, STRIP_COLUMNS, Store

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
    assert row["description"] == "P 60 min 9h-17h LUN A VEN"
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


# --- no-parking strips ------------------------------------------------------------

TUESDAY_10_11 = TimeWindow(hour=(10.0, 11.0), day=(2, 2))


def _restricted(store: Store, window: TimeWindow) -> dict[int, bool]:
    df = store.query_strips(StripQuery(window=window))
    return dict(zip(df["strip_id"].to_list(), df["is_restricted"].to_list(), strict=True))


def test_strip_result_columns(store: Store):
    assert store.query_strips(StripQuery()).columns == list(STRIP_COLUMNS)


def test_strip_restricted_when_a_rule_overlaps_the_window(store: Store):
    # strips 0 and 2: no parking Tuesdays 8-11; strip 1: no parking at any time
    assert _restricted(store, TUESDAY_10_11) == {0: True, 1: True, 2: True}
    wednesday = TimeWindow(hour=(10.0, 11.0), day=(3, 3))
    assert _restricted(store, wednesday) == {0: False, 1: True, 2: False}


def test_strip_partial_overlap_restricts_but_touching_does_not(store: Store):
    # a stay from 10:30 to noon on Tuesday still hits the 8-11 ban...
    assert _restricted(store, TimeWindow(hour=(10.5, 12.0), day=(2, 2)))[0]
    # ...one starting when it ends does not
    assert not _restricted(store, TimeWindow(hour=(11.0, 12.0), day=(2, 2)))[0]


def test_strip_active_rules_are_listed(store: Store):
    df = store.query_strips(StripQuery(window=TimeWindow(hour=(10.0, 11.0), day=(3, 3))))
    active = dict(zip(df["strip_id"].to_list(), df["active_code_ids"].to_list(), strict=True))
    assert active == {0: [], 1: [4], 2: []}


def test_strip_without_window_counts_any_time(store: Store):
    # with no time filter, every rule applies at *some* time
    assert all(_restricted(store, TimeWindow()).values())


def test_strip_status_filter(store: Store):
    wednesday = TimeWindow(hour=(10.0, 11.0), day=(3, 3))  # only strip 1 restricted
    parkable = store.query_strips(StripQuery(window=wednesday, restricted=False))
    restricted = store.query_strips(StripQuery(window=wednesday, restricted=True))
    assert parkable["strip_id"].to_list() == [0, 2]
    assert restricted["strip_id"].to_list() == [1]
    assert store.query_strips(StripQuery(window=wednesday)).height == 3  # None: all


def test_strips_can_leave_out_inferred_extents(store: Store):
    df = store.query_strips(StripQuery(window=TUESDAY_10_11, include_inferred=False))
    rows = {r["strip_id"]: r for r in df.iter_rows(named=True)}
    assert set(rows) == {0, 1}  # strip 2 existed by inference alone
    # strip 1 keeps only its arrow-derived rule
    assert rows[1]["active_code_ids"] == [4]
    assert [r["code_id"] for r in rows[1]["rules"]] == [4]
    assert not any(r["is_inferred"] for r in rows.values())


def test_strips_include_inferred_by_default(store: Store):
    df = store.query_strips(StripQuery(window=TUESDAY_10_11))
    inferred = dict(zip(df["strip_id"].to_list(), df["is_inferred"].to_list(), strict=True))
    assert inferred == {0: False, 1: False, 2: True}
    rows = {r["strip_id"]: r for r in df.iter_rows(named=True)}
    assert sorted(rows[1]["active_code_ids"]) == [3, 4]
