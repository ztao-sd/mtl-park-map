import math

import numpy as np
import pytest

from mtl_park_map.etl.geometry import to_local, to_lonlat
from mtl_park_map.etl.snapping import snap_points
from mtl_park_map.etl.streets import StreetNetwork
from tests.geo_helpers import feature, lonlat


@pytest.fixture
def network() -> StreetNetwork:
    return StreetNetwork.from_features(
        [
            feature(1, "Rue Test", (0, 0), (200, 0)),  # west -> east
            feature(5, "Rue Test", (200, 0), (400, 0)),  # next block, past the corner
            feature(2, "Avenue Cross", (200, 0), (200, 200)),  # south -> north
            feature(3, "Autoroute 99", (0, 40), (200, 40), classe=8),  # highway: dropped
            feature(4, "Rue Haute", (0, -40), (200, -40), position=2),  # viaduct: dropped
        ]
    )


def snap(network: StreetNetwork, *pts_m: tuple[float, float]):
    lons, lats = zip(*(lonlat(*p) for p in pts_m), strict=True)
    return snap_points(network, np.array(lons), np.array(lats))


def test_round_trip_projection():
    x, y = to_local(np.array([-73.57]), np.array([45.53]))
    lon, lat = to_lonlat(x, y)
    assert (lon[0], lat[0]) == pytest.approx((-73.57, 45.53))
    # 1 degree of latitude is ~111 km; local metres are metres
    _, y2 = to_local(np.array([-73.57]), np.array([45.54]))
    assert y2[0] - y[0] == pytest.approx(1113.2, rel=1e-3)


def test_network_drops_highways_and_elevated_segments(network: StreetNetwork):
    assert sorted(network.segment_ids.tolist()) == [1, 2, 5]
    assert network.names[network.index_of(1)] == "Rue Test"
    assert network.lengths[network.index_of(1)] == pytest.approx(200.0, rel=1e-3)


def test_snaps_to_nearest_segment_with_side_and_position(network: StreetNetwork):
    df = snap(network, (100, 6), (60, -7))
    north, south = df.rows(named=True)
    assert north["segment_id"] == 1 and south["segment_id"] == 1
    # heading east, north is on the left (+1) and south on the right (-1)
    assert (north["side"], south["side"]) == (1, -1)
    assert north["along_m"] == pytest.approx(100.0, abs=0.5)
    assert south["along_m"] == pytest.approx(60.0, abs=0.5)
    assert north["dist_m"] == pytest.approx(6.0, abs=0.1)
    assert not north["ambiguous"]


def test_far_points_are_not_snapped(network: StreetNetwork):
    # 30 m from the street (the elevated "Rue Haute" at -40 m was dropped)
    row = snap(network, (100, -30)).row(0, named=True)
    assert row["segment_id"] is None and row["side"] is None


def test_corner_poles_are_flagged_ambiguous(network: StreetNetwork):
    # at the corner: as close to Rue Test (next block) as to Avenue Cross
    row = snap(network, (205, 5)).row(0, named=True)
    assert row["ambiguous"]


def test_block_joints_of_the_same_street_are_not_ambiguous():
    # two consecutive segments of one street: the next block is no rival
    network = StreetNetwork.from_features(
        [feature(1, "Rue Test", (0, 0), (200, 0)), feature(5, "Rue Test", (200, 0), (400, 0))]
    )
    row = snap(network, (201, -6)).row(0, named=True)
    assert row["side"] == -1 and not row["ambiguous"]


def test_side_on_a_northbound_segment(network: StreetNetwork):
    row = snap(network, (194, 100)).row(0, named=True)  # west of Avenue Cross
    assert row["segment_id"] == 2
    assert row["side"] == 1  # heading north, west is on the left
    assert math.isclose(row["along_m"], 100.0, abs_tol=0.5)
