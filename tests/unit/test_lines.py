import polars as pl
import pytest

from mtl_park_map.slippy.lines import LineLayer, LineStyle
from mtl_park_map.slippy.projection import lonlat_to_world, world_to_lonlat
from mtl_park_map.slippy.viewport import Viewport

CENTER = lonlat_to_world(-73.5673, 45.5017)
STYLE = LineStyle(color="#dc2626", width=4.0)


def _vp(zoom: int = 17) -> Viewport:
    return Viewport(center=CENTER, zoom=zoom, width=800, height=600)


def _layer(vp: Viewport, *lines_px: list[tuple[float, float]], min_zoom: int = 15) -> LineLayer:
    """A layer whose polylines sit at the given screen pixels of ``vp``."""
    lonlats = [[world_to_lonlat(*vp.screen_to_world(x, y)) for x, y in line] for line in lines_px]
    df = pl.DataFrame(
        {
            "longitudes": [[p[0] for p in line] for line in lonlats],
            "latitudes": [[p[1] for p in line] for line in lonlats],
        }
    )
    return LineLayer("strips", STYLE, df, min_zoom=min_zoom)


def test_len_and_empty():
    empty = pl.DataFrame(schema={"longitudes": pl.List(pl.Float64), "latitudes": pl.List(pl.Float64)})
    layer = LineLayer("strips", STYLE, empty)
    assert len(layer) == 0
    assert layer.screen_polylines(_vp()) == []
    assert layer.hit_test(_vp(), 400.0, 300.0) is None


def test_screen_polylines_project_and_cull():
    vp = _vp()
    layer = _layer(vp, [(100, 100), (300, 100)], [(5000, 100), (5200, 100)], [(780, 300), (900, 300)])
    lines = layer.screen_polylines(vp)
    # off-screen line dropped; one partly visible kept
    assert [idx for idx, _ in lines] == [0, 2]
    _, points = lines[0]
    assert points[0] == pytest.approx((100.0, 100.0))
    assert points[1] == pytest.approx((300.0, 100.0))


def test_hidden_below_min_zoom():
    vp = _vp(zoom=14)
    layer = _layer(vp, [(100, 100), (300, 100)], min_zoom=15)
    assert layer.screen_polylines(vp) == []
    assert layer.hit_test(vp, 200.0, 100.0) is None


def test_hit_test_near_a_segment_anywhere_along_it():
    vp = _vp()
    layer = _layer(vp, [(100, 100), (300, 100), (300, 300)])
    hit = layer.hit_test(vp, 200.0, 103.0)  # 3 px from the first leg
    assert hit is not None and (hit.layer, hit.idx, hit.count) == ("strips", 0, 1)
    # the popup anchors where the user clicked
    assert vp.world_to_screen(hit.x, hit.y) == pytest.approx((200.0, 103.0))
    assert layer.hit_test(vp, 303.0, 250.0) is not None  # second leg


def test_hit_test_miss_and_nearest():
    vp = _vp()
    layer = _layer(vp, [(100, 100), (300, 100)], [(100, 110), (300, 110)])
    assert layer.hit_test(vp, 200.0, 130.0) is None  # 20 px away
    hit = layer.hit_test(vp, 200.0, 107.0)
    assert hit is not None and hit.idx == 1


def test_screen_polylines_follow_the_bearing():
    north_up = _vp()
    layer = _layer(north_up, [(400, 300), (500, 300)])  # from the centre 100 px east
    east_up = Viewport(center=CENTER, zoom=17, width=800, height=600, bearing=90.0)
    (_, points), = layer.screen_polylines(east_up)
    assert points[0] == pytest.approx((400.0, 300.0))
    assert points[1] == pytest.approx((400.0, 200.0))  # east is up
    assert layer.hit_test(east_up, 402.0, 250.0) is not None
