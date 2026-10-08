import numpy as np
import polars as pl
import pytest

from mtl_park_map.etl.arrows import BACKWARD, BOTH, FORWARD
from mtl_park_map.etl.streets import StreetNetwork
from mtl_park_map.etl.strips import (
    STRIP_SCHEMA,
    Piece,
    StripReport,
    SignEvent,
    build_strips,
    inferred_extents,
    rule_extents,
    split_pieces,
)
from tests.geo_helpers import feature, lonlat


def test_signs_pointing_toward_each_other_bound_a_zone():
    events = [SignEvent(20.0, FORWARD, 1), SignEvent(80.0, BACKWARD, 2)]
    assert rule_extents(events, 100.0) == [(20.0, 80.0, 1), (20.0, 80.0, 2)]


def test_signs_pointing_away_run_to_the_block_ends():
    events = [SignEvent(20.0, BACKWARD, 1), SignEvent(80.0, FORWARD, 2)]
    assert rule_extents(events, 100.0) == [(0.0, 20.0, 1), (80.0, 100.0, 2)]


def test_double_arrow_extends_both_ways_until_a_closing_sign():
    events = [SignEvent(10.0, FORWARD, 1), SignEvent(50.0, BOTH, 2), SignEvent(90.0, BACKWARD, 3)]
    assert rule_extents(events, 100.0) == [
        (10.0, 90.0, 1),
        (10.0, 50.0, 2),
        (50.0, 90.0, 2),
        (10.0, 90.0, 3),
    ]


def test_same_direction_chain_runs_to_the_end():
    events = [SignEvent(10.0, FORWARD, 1), SignEvent(40.0, FORWARD, 2)]
    assert rule_extents(events, 100.0) == [(10.0, 100.0, 1), (40.0, 100.0, 2)]


def test_split_pieces_by_overlapping_rules():
    pieces = split_pieces({7: [(0.0, 60.0, 1)], 9: [(40.0, 100.0, 2)]})
    assert pieces == [
        Piece(0.0, 40.0, (7,), (1,)),
        Piece(40.0, 60.0, (7, 9), (1, 2)),
        Piece(60.0, 100.0, (9,), (2,)),
    ]


def test_split_pieces_merges_contiguous_same_rule_and_drops_slivers():
    pieces = split_pieces(
        {7: [(0.0, 30.0, 1), (30.0, 60.0, 2), (80.0, 80.4, 3)]}, min_length_m=1.0
    )
    assert pieces == [Piece(0.0, 60.0, (7,), (1, 2))]


def test_split_pieces_keeps_gaps():
    pieces = split_pieces({7: [(0.0, 20.0, 1), (50.0, 70.0, 2)]})
    assert [(p.start_m, p.end_m) for p in pieces] == [(0.0, 20.0), (50.0, 70.0)]


# --- end to end on a synthetic street -------------------------------------------

_HOURS = pl.List(pl.Struct({"start": pl.Float64, "end": pl.Float64}))
_INTS = pl.List(pl.Struct({"start": pl.Int64, "end": pl.Int64}))


def _codes() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"code_id": 0, "description": r"\P 8h-11h MARDI", "kind": "no_parking",
             "hour_ranges": [{"start": 8.0, "end": 11.0}], "day_ranges": [{"start": 2, "end": 2}],
             "month_ranges": []},
            {"code_id": 1, "description": r"\A EN TOUT TEMPS", "kind": "no_stopping",
             "hour_ranges": [], "day_ranges": [], "month_ranges": []},
        ],
        schema={"code_id": pl.UInt32, "description": pl.Utf8, "kind": pl.Utf8,
                "hour_ranges": _HOURS, "day_ranges": _INTS, "month_ranges": _INTS},
    )


def _signs() -> pl.DataFrame:
    rows = [
        # (sign_id, pole_id, x, y, fleche, code_id)
        (0, 10, 20.0, 6.0, "3", 0),  # north side: right arrow -> eastwards
        (1, 11, 80.0, 6.0, "2", 0),  # north side: left arrow -> westwards (closes zone)
        (2, 12, 50.0, -6.0, "3", 0),  # south side: right arrow -> westwards to the corner
        (3, 13, 120.0, 6.0, "3", 1),  # \A no stopping: ignored for now
        (4, 14, 150.0, 6.0, "0", 0),  # no arrow, but its rule has arrows here: ignored
        (5, 15, 100.0, 40.0, "3", 0),  # 34 m off the street: not snapped
    ]
    return pl.DataFrame(
        [
            {"sign_id": s, "pole_id": p, "longitude": lonlat(x, y)[0], "latitude": lonlat(x, y)[1],
             "fleche": f, "code_id": c}
            for s, p, x, y, f, c in rows
        ],
        schema={"sign_id": pl.UInt32, "pole_id": pl.Int64, "longitude": pl.Float64,
                "latitude": pl.Float64, "fleche": pl.Utf8, "code_id": pl.UInt32},
    )


@pytest.fixture
def built() -> tuple[pl.DataFrame, StripReport]:
    network = StreetNetwork.from_features([feature(1, "Rue Test", (0, 0), (200, 0))])
    return build_strips(_signs(), _codes(), network)


def test_build_strips_schema_and_extents(built: tuple[pl.DataFrame, StripReport]):
    strips, _ = built
    assert strips.schema == STRIP_SCHEMA
    rows = {(r["side"], round(r["start_m"]), round(r["end_m"])): r for r in strips.iter_rows(named=True)}
    assert set(rows) == {(1, 20, 80), (-1, 0, 50)}
    north = rows[(1, 20, 80)]
    assert north["segment_id"] == 1 and north["street"] == "Rue Test"
    assert north["length_m"] == pytest.approx(60.0, abs=0.5)
    assert north["code_ids"] == [0] and sorted(north["sign_ids"]) == [0, 1]


def test_build_strips_geometry_is_on_the_curb_side(built: tuple[pl.DataFrame, StripReport]):
    strips, _ = built
    street_lat = lonlat(0, 0)[1]
    for row in strips.iter_rows(named=True):
        lats = np.array(row["latitudes"])
        # north-side strips lie north of the centreline, south-side ones south of it
        assert (np.sign(lats - street_lat) == row["side"]).all()
        assert row["min_lat"] == pytest.approx(lats.min())
        assert row["max_lon"] == pytest.approx(max(row["longitudes"]))


def test_build_strips_carries_temporal_rules(built: tuple[pl.DataFrame, StripReport]):
    strips, _ = built
    rule = strips.row(0, named=True)["rules"][0]
    assert rule["description"] == r"\P 8h-11h MARDI"
    assert rule["hour_ranges"] == [{"start": 8.0, "end": 11.0}]
    assert rule["day_ranges"] == [{"start": 2, "end": 2}]


def test_build_strips_report(built: tuple[pl.DataFrame, StripReport]):
    _, report = built
    assert report.panels == 4  # \P with an arrow: signs 0, 1, 2, 5
    assert report.panels_snapped == 3
    assert report.strips == 2


def test_build_strips_records_the_poles_of_their_signs(built: tuple[pl.DataFrame, StripReport]):
    strips, _ = built
    north = strips.filter(pl.col("side") == 1).row(0, named=True)
    # signs 0 and 1 (poles at 20 m and 80 m, 6 m north of the centreline)
    expected = sorted([lonlat(20.0, 6.0), lonlat(80.0, 6.0)])
    poles = sorted(zip(north["pole_longitudes"], north["pole_latitudes"], strict=True))
    assert poles == pytest.approx(expected)



# --- option B: extents inferred from signs without arrows ------------------------

MONDAY_CLEANING = 2  # code of the arrow-less rule below


def _codes_with_cleaning() -> pl.DataFrame:
    cleaning = pl.DataFrame(
        [{"code_id": MONDAY_CLEANING, "description": r"\P 8h30-11h30 LUNDI", "kind": "no_parking",
          "hour_ranges": [{"start": 8.5, "end": 11.5}], "day_ranges": [{"start": 1, "end": 1}],
          "month_ranges": []}],
        schema=_codes().schema,
    )
    return pl.concat([_codes(), cleaning])


def _signs_with_cleaning() -> pl.DataFrame:
    extra = [
        # (sign_id, pole_id, x, y, fleche, code_id) -- all without a usable arrow
        (6, 16, 120.0, -6.0, "0", MONDAY_CLEANING),  # south side ...
        (7, 17, 160.0, -6.0, "0", MONDAY_CLEANING),  # ... spans 40 m to 160 m with sign 9
        (9, 19, 40.0, -6.0, "0", MONDAY_CLEANING),  # overlaps the arrowed rule's [0, 50]
        (8, 18, 195.0, 6.0, "0", MONDAY_CLEANING),  # north side, alone, near the block end
        (10, 20, 100.0, 6.0, "22", MONDAY_CLEANING),  # undocumented arrow code: ignored
    ]
    rows = pl.DataFrame(
        [
            {"sign_id": s, "pole_id": p, "longitude": lonlat(x, y)[0], "latitude": lonlat(x, y)[1],
             "fleche": f, "code_id": c}
            for s, p, x, y, f, c in extra
        ],
        schema=_signs().schema,
    )
    return pl.concat([_signs(), rows])


@pytest.fixture
def built_inferred() -> tuple[pl.DataFrame, StripReport]:
    network = StreetNetwork.from_features([feature(1, "Rue Test", (0, 0), (200, 0))])
    return build_strips(_signs_with_cleaning(), _codes_with_cleaning(), network)


def _by_extent(strips: pl.DataFrame) -> dict[tuple[int, int, int], dict]:
    return {
        (r["side"], round(r["start_m"]), round(r["end_m"])): r for r in strips.iter_rows(named=True)
    }


def test_inferred_extent_spans_the_signs_plus_padding(built_inferred: tuple[pl.DataFrame, StripReport]):
    strips, _ = built_inferred
    rows = _by_extent(strips)
    # south: arrowed rule 0 covers [0, 50]; arrow-less rule 2 spans 40..160 m +/-10 m
    assert set(k for k in rows if k[0] == -1) == {(-1, 0, 30), (-1, 30, 50), (-1, 50, 170)}
    inferred_only = rows[(-1, 50, 170)]
    assert inferred_only["code_ids"] == [MONDAY_CLEANING]
    assert inferred_only["inferred_code_ids"] == [MONDAY_CLEANING]
    assert inferred_only["is_inferred"]
    assert sorted(inferred_only["sign_ids"]) == [6, 7, 9]


def test_inferred_single_sign_is_clipped_to_the_block(built_inferred: tuple[pl.DataFrame, StripReport]):
    strips, _ = built_inferred
    rows = _by_extent(strips)
    alone = rows[(1, 185, 200)]  # 195 m +/-10 m, block ends at 200 m
    assert alone["is_inferred"] and alone["sign_ids"] == [8]


def test_mixed_piece_keeps_per_rule_sources(built_inferred: tuple[pl.DataFrame, StripReport]):
    strips, _ = built_inferred
    mixed = _by_extent(strips)[(-1, 30, 50)]
    assert mixed["code_ids"] == [0, MONDAY_CLEANING]
    assert mixed["inferred_code_ids"] == [MONDAY_CLEANING]
    assert not mixed["is_inferred"]  # it exists on arrow evidence alone too
    flags = {r["code_id"]: r["inferred"] for r in mixed["rules"]}
    assert flags == {0: False, MONDAY_CLEANING: True}


def test_arrowed_strips_unchanged_and_ignored_signs_unused(
    built_inferred: tuple[pl.DataFrame, StripReport],
):
    strips, _ = built_inferred
    north = _by_extent(strips)[(1, 20, 80)]
    assert north["code_ids"] == [0] and north["inferred_code_ids"] == [] and not north["is_inferred"]
    used = {s for ids in strips["sign_ids"].to_list() for s in ids}
    assert 4 not in used  # repeater of an arrowed rule
    assert 10 not in used  # undocumented arrow code


def test_report_counts_inferred_panels(built_inferred: tuple[pl.DataFrame, StripReport]):
    _, report = built_inferred
    assert report.inferred_panels == 4  # signs 6, 7, 8, 9
    assert report.inferred_km == pytest.approx((120 + 15) / 1000, abs=0.002)


def test_inferred_extents_function():
    assert inferred_extents([(40.0, 9), (120.0, 6)], 200.0) == [(30.0, 130.0, 9), (30.0, 130.0, 6)]
    assert inferred_extents([(5.0, 1)], 100.0) == [(0.0, 15.0, 1)]  # clipped at the start
    assert inferred_extents([(50.0, 1)], 100.0, pad_m=0.0) == [(50.0, 50.0, 1)]
