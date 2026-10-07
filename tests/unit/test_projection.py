import math

import polars as pl
import pytest

from mtl_park_map.slippy.projection import (
    MAX_LATITUDE,
    TILE_SIZE,
    lonlat_to_world,
    world_size,
    world_to_lonlat,
    world_x,
    world_y,
)

MONTREAL = (-73.5673, 45.5017)


def test_origin_maps_to_world_centre():
    assert lonlat_to_world(0.0, 0.0) == pytest.approx((0.5, 0.5))


def test_world_corners():
    assert lonlat_to_world(-180.0, MAX_LATITUDE) == pytest.approx((0.0, 0.0), abs=1e-9)
    assert lonlat_to_world(180.0, -MAX_LATITUDE) == pytest.approx((1.0, 1.0), abs=1e-9)


def test_latitude_is_clamped_to_mercator_limit():
    assert lonlat_to_world(0.0, 90.0) == pytest.approx(lonlat_to_world(0.0, MAX_LATITUDE))


def test_round_trip():
    x, y = lonlat_to_world(*MONTREAL)
    assert world_to_lonlat(x, y) == pytest.approx(MONTREAL)


@pytest.mark.parametrize(("zoom", "tile"), [(12, (1210, 1465)), (17, (38750, 46890))])
def test_matches_osm_tile_numbering(zoom: int, tile: tuple[int, int]):
    # reference values from the OSM wiki lon2tile/lat2tile formulas
    x, y = lonlat_to_world(*MONTREAL)
    assert (math.floor(x * 2**zoom), math.floor(y * 2**zoom)) == tile


def test_world_size():
    assert world_size(0) == TILE_SIZE
    assert world_size(3) == TILE_SIZE * 8


def test_polars_expressions_match_scalar():
    df = pl.DataFrame({"lon": [MONTREAL[0], 0.0], "lat": [MONTREAL[1], 0.0]})
    out = df.select(x=world_x(pl.col("lon")), y=world_y(pl.col("lat")))
    for (lon, lat), x, y in zip(df.iter_rows(), out["x"], out["y"], strict=True):
        assert (x, y) == pytest.approx(lonlat_to_world(lon, lat))
