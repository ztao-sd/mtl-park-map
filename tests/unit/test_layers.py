import polars as pl
import pytest

from mtl_park_map.slippy.layers import MarkerLayer, MarkerStyle, cluster_radius
from mtl_park_map.slippy.projection import lonlat_to_world, world_to_lonlat
from mtl_park_map.slippy.viewport import Viewport

CENTER = lonlat_to_world(-73.5673, 45.5017)
STYLE = MarkerStyle(color="#2563eb", radius=5.0)


def _vp(zoom: int = 18) -> Viewport:
    return Viewport(center=CENTER, zoom=zoom, width=800, height=600)


def _layer_at_screen(vp: Viewport, *screen_pts: tuple[float, float]) -> MarkerLayer:
    lonlat = [world_to_lonlat(*vp.screen_to_world(sx, sy)) for sx, sy in screen_pts]
    df = pl.DataFrame(
        {"longitude": [p[0] for p in lonlat], "latitude": [p[1] for p in lonlat]}
    )
    return MarkerLayer("signs", STYLE, df)


def test_len_and_empty():
    empty = pl.DataFrame(schema={"longitude": pl.Float64, "latitude": pl.Float64})
    layer = MarkerLayer("x", STYLE, empty)
    assert len(layer) == 0
    assert layer.screen_clusters(_vp()).is_empty()
    assert layer.hit_test(_vp(), 400.0, 300.0) is None


def test_clusters_are_cached_per_zoom():
    layer = _layer_at_screen(_vp(), (400, 300))
    assert layer.clusters(12) is layer.clusters(12)


def test_screen_clusters_cull_off_screen_points():
    vp = _vp()
    layer = _layer_at_screen(vp, (400, 300), (5000, 300), (810, 300))
    out = layer.screen_clusters(vp, margin_px=30)
    assert out["idx"].to_list() == [0, 2]  # 810 is within the 30 px margin
    assert out.row(0, named=True)["sx"] == pytest.approx(400.0)
    assert out.row(0, named=True)["sy"] == pytest.approx(300.0)


def test_hit_test_singleton():
    vp = _vp()
    layer = _layer_at_screen(vp, (100, 100), (400, 300))
    hit = layer.hit_test(vp, 403.0, 302.0)
    assert hit is not None
    assert (hit.layer, hit.idx, hit.count) == ("signs", 1, 1)


def test_hit_test_miss():
    vp = _vp()
    layer = _layer_at_screen(vp, (400, 300))
    assert layer.hit_test(vp, 420.0, 300.0) is None


def test_hit_test_prefers_nearest():
    vp = _vp()
    layer = _layer_at_screen(vp, (400, 300), (406, 300))
    hit = layer.hit_test(vp, 405.0, 300.0)
    assert hit is not None and hit.idx == 1


def test_cluster_has_bigger_hit_area():
    vp = _vp(zoom=12)
    layer = _layer_at_screen(vp, *[(400 + i, 300) for i in range(10)])
    hit = layer.hit_test(vp, 404.5 + 14, 300.0)
    assert hit is not None and hit.count == 10


def test_cluster_radius_grows_and_caps():
    assert cluster_radius(1, 5.0) == 5.0
    assert 5.0 < cluster_radius(2, 5.0) < cluster_radius(50, 5.0)
    assert cluster_radius(10**6, 5.0) == cluster_radius(10**7, 5.0)


def test_screen_clusters_follow_the_bearing():
    north_up = _vp()
    layer = _layer_at_screen(north_up, (500, 300))  # 100 px east of the centre
    east_up = Viewport(center=CENTER, zoom=18, width=800, height=600, bearing=90.0)
    row = layer.screen_clusters(east_up).row(0, named=True)
    assert (row["sx"], row["sy"]) == pytest.approx((400.0, 200.0))  # now above
    hit = layer.hit_test(east_up, 401.0, 201.0)
    assert hit is not None and hit.idx == 0
