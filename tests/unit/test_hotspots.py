import pytest

from mtl_park_map.ui.hotspots import (
    Hotspot,
    add_hotspot,
    hotspot_from_json,
    hotspot_to_json,
    hotspots_from_json,
    hotspots_to_json,
    remove_hotspot,
)

HOME = Hotspot("Home — 4320 Rue Berri", -73.5797, 45.5240)
WORK = Hotspot("845 Rue Sherbrooke Ouest", -73.5787, 45.5069)


def test_list_round_trip():
    assert hotspots_from_json(hotspots_to_json([HOME, WORK])) == [HOME, WORK]


@pytest.mark.parametrize(
    "raw",
    ["", "not json", "{}", '[{"name": "x"}]', '[{"name": 1, "lon": 0, "lat": 0}]', "null"],
)
def test_malformed_lists_are_ignored(raw: str):
    assert hotspots_from_json(raw) == []


def test_valid_entries_survive_next_to_bad_ones():
    raw = '[{"name": "ok", "lon": -73.5, "lat": 45.5}, {"name": "bad"}]'
    assert hotspots_from_json(raw) == [Hotspot("ok", -73.5, 45.5)]


def test_single_round_trip_and_missing():
    assert hotspot_from_json(hotspot_to_json(HOME)) == HOME
    assert hotspot_from_json(hotspot_to_json(None)) is None
    assert hotspot_from_json("garbage") is None


def test_add_appends_and_replaces_same_name_in_place():
    spots = add_hotspot([HOME, WORK], Hotspot("home — 4320 rue berri", -73.0, 45.0))
    assert [h.name for h in spots] == ["home — 4320 rue berri", WORK.name]  # same slot
    assert add_hotspot([HOME], WORK) == [HOME, WORK]


def test_remove():
    assert remove_hotspot([HOME, WORK], HOME) == [WORK]
    assert remove_hotspot([WORK], HOME) == [WORK]
