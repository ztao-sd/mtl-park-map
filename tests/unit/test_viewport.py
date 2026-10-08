import pytest

from mtl_park_map.slippy.projection import lonlat_to_world, world_size
from mtl_park_map.slippy.viewport import TileKey, Viewport

MONTREAL = lonlat_to_world(-73.5673, 45.5017)


def _vp(zoom: int = 12, width: int = 800, height: int = 600) -> Viewport:
    return Viewport(center=MONTREAL, zoom=zoom, width=width, height=height)


def test_centre_maps_to_screen_centre():
    vp = _vp()
    assert vp.world_to_screen(*MONTREAL) == pytest.approx((400.0, 300.0))


def test_screen_world_round_trip():
    vp = _vp()
    assert vp.world_to_screen(*vp.screen_to_world(123.0, 456.0)) == pytest.approx(
        (123.0, 456.0)
    )


def test_one_world_pixel_per_screen_pixel():
    vp = _vp(zoom=12)
    x0, _ = vp.screen_to_world(0.0, 0.0)
    x1, _ = vp.screen_to_world(1.0, 0.0)
    assert (x1 - x0) * world_size(12) == pytest.approx(1.0)


def test_pan_moves_content_with_the_drag():
    vp = _vp()
    world_pt = vp.screen_to_world(100.0, 100.0)
    panned = vp.panned(50.0, -20.0)
    # what was under (100, 100) is now under (150, 80)
    assert panned.world_to_screen(*world_pt) == pytest.approx((150.0, 80.0))


@pytest.mark.parametrize("target", [13, 15, 11])
def test_zoom_keeps_anchor_under_cursor(target: int):
    vp = _vp(zoom=12)
    anchor = vp.screen_to_world(200.0, 450.0)
    zoomed = vp.zoomed_at(200.0, 450.0, target)
    assert zoomed.zoom == target
    assert zoomed.world_to_screen(*anchor) == pytest.approx((200.0, 450.0))


def test_bbox_orders_lon_lat_min_max():
    min_lon, min_lat, max_lon, max_lat = _vp().bbox()
    assert min_lon < -73.5673 < max_lon
    assert min_lat < 45.5017 < max_lat


def test_clamp_zoom():
    bounds = (0.0, 0.0, 1.0, 1.0)
    assert _vp(zoom=25).clamped(bounds, 11, 19).zoom == 19
    assert _vp(zoom=3).clamped(bounds, 11, 19).zoom == 11


def test_clamp_keeps_centre_inside_bounds():
    x, y = MONTREAL
    bounds = (x - 0.01, y - 0.01, x + 0.01, y + 0.01)
    vp = Viewport(center=(x + 0.05, y - 0.05), zoom=14, width=800, height=600)
    assert vp.clamped(bounds, 11, 19).center == pytest.approx((x + 0.01, y - 0.01))


def test_clamp_lets_view_extend_half_a_screen_past_bounds():
    # any point of the bounds can be brought to the screen centre, so up to half a
    # screen of surroundings shows beyond the edge -- even when the bounds are
    # smaller than the screen (zoomed out), the view can still be dragged
    x, y = MONTREAL
    bounds = (x - 1e-4, y - 1e-4, x + 1e-4, y + 1e-4)
    vp = Viewport(center=(x + 1e-4, y), zoom=12, width=800, height=600)
    clamped = vp.clamped(bounds, 11, 19)
    assert clamped.center == pytest.approx((x + 1e-4, y))
    assert clamped.world_rect()[0] == pytest.approx(bounds[2] - 400 / vp.scale)


def test_clamp_leaves_centre_inside_bounds_untouched():
    x, y = MONTREAL
    bounds = (x - 0.01, y - 0.01, x + 0.01, y + 0.01)
    vp = Viewport(center=(x + 0.005, y), zoom=14, width=800, height=600)
    assert vp.clamped(bounds, 11, 19) == vp


def test_visible_tiles_cover_viewport_exactly():
    vp = _vp(zoom=12)
    tiles = vp.visible_tiles()
    assert all(t.z == 12 for t in tiles)
    min_x, min_y, max_x, max_y = vp.world_rect()
    n = 2**12
    xs = {t.x for t in tiles}
    ys = {t.y for t in tiles}
    assert min(xs) / n <= min_x and (max(xs) + 1) / n >= max_x
    assert min(ys) / n <= min_y and (max(ys) + 1) / n >= max_y
    # no superfluous column/row
    assert (min(xs) + 1) / n > min_x and max(xs) / n < max_x
    assert len(tiles) == len(xs) * len(ys)


def test_visible_tiles_start_at_centre():
    vp = _vp(zoom=12)
    first = vp.visible_tiles()[0]
    assert first == TileKey(12, int(MONTREAL[0] * 4096), int(MONTREAL[1] * 4096))


def test_visible_tiles_empty_for_zero_size():
    assert _vp(width=0, height=0).visible_tiles() == []


def test_visible_tiles_stay_inside_world():
    # centred on the world's north-west corner: half the view is off-world
    vp = Viewport(center=(0.0, 0.0), zoom=3, width=800, height=600)
    tiles = vp.visible_tiles()
    assert min(t.x for t in tiles) == 0 and min(t.y for t in tiles) == 0
    assert all(0 <= t.x < 8 and 0 <= t.y < 8 for t in tiles)


# --- rotation ---------------------------------------------------------------------

BEARINGS = [0.0, 30.0, 90.0, 200.0, 315.0]


def _rvp(bearing: float, zoom: int = 12) -> Viewport:
    return Viewport(center=MONTREAL, zoom=zoom, width=800, height=600, bearing=bearing)


def test_bearing_defaults_to_north_up():
    assert _vp().bearing == 0.0


def test_bearing_is_the_direction_at_the_top_of_the_screen():
    vp = _rvp(90.0)  # east up
    d = 50 / vp.scale
    x, y = MONTREAL
    assert vp.world_to_screen(x + d, y) == pytest.approx((400.0, 250.0))  # east: above
    assert vp.world_to_screen(x, y - d) == pytest.approx((350.0, 300.0))  # north: left
    assert _rvp(180.0).world_to_screen(x, y - d) == pytest.approx((400.0, 350.0))  # north: below


@pytest.mark.parametrize("bearing", BEARINGS)
def test_rotated_round_trip(bearing: float):
    vp = _rvp(bearing)
    assert vp.world_to_screen(*vp.screen_to_world(123.0, 456.0)) == pytest.approx((123.0, 456.0))
    assert vp.world_to_screen(*MONTREAL) == pytest.approx((400.0, 300.0))


@pytest.mark.parametrize("bearing", BEARINGS)
def test_rotated_pan_moves_content_with_the_drag(bearing: float):
    vp = _rvp(bearing)
    world_pt = vp.screen_to_world(100.0, 100.0)
    assert vp.panned(50.0, -20.0).world_to_screen(*world_pt) == pytest.approx((150.0, 80.0))


@pytest.mark.parametrize("bearing", BEARINGS)
def test_rotated_zoom_keeps_anchor_under_cursor(bearing: float):
    vp = _rvp(bearing)
    anchor = vp.screen_to_world(200.0, 450.0)
    zoomed = vp.zoomed_at(200.0, 450.0, 14)
    assert zoomed.bearing == bearing
    assert zoomed.world_to_screen(*anchor) == pytest.approx((200.0, 450.0))


@pytest.mark.parametrize(("bearing", "expected"), [(-30.0, 330.0), (370.0, 10.0), (360.0, 0.0)])
def test_with_bearing_normalizes_and_keeps_centre(bearing: float, expected: float):
    vp = _vp().with_bearing(bearing)
    assert vp.bearing == pytest.approx(expected)
    assert vp.center == MONTREAL


def test_clamp_keeps_bearing():
    assert _rvp(45.0).clamped((0.0, 0.0, 1.0, 1.0), 11, 19).bearing == 45.0


@pytest.mark.parametrize("bearing", BEARINGS)
def test_rotated_world_rect_contains_every_screen_corner(bearing: float):
    vp = _rvp(bearing)
    min_x, min_y, max_x, max_y = vp.world_rect()
    for sx, sy in [(0, 0), (800, 0), (0, 600), (800, 600)]:
        x, y = vp.screen_to_world(sx, sy)
        assert min_x - 1e-12 <= x <= max_x + 1e-12 and min_y - 1e-12 <= y <= max_y + 1e-12


@pytest.mark.parametrize("bearing", BEARINGS)
def test_rotated_visible_tiles_cover_every_screen_pixel(bearing: float):
    vp = _rvp(bearing)
    tiles = {(t.x, t.y) for t in vp.visible_tiles()}
    n = 2**vp.zoom
    for sx in range(0, 801, 25):
        for sy in range(0, 601, 25):
            x, y = vp.screen_to_world(sx, sy)
            assert (int(x * n), int(y * n)) in tiles


def test_rotated_visible_tiles_skip_tiles_outside_the_view():
    # the rotated view's bounding box holds more tiles than the view itself touches
    vp = _rvp(45.0)
    n = 2**vp.zoom
    min_x, min_y, max_x, max_y = vp.world_rect()
    bbox_tiles = (int(max_x * n) - int(min_x * n) + 1) * (int(max_y * n) - int(min_y * n) + 1)
    assert len(vp.visible_tiles()) < bbox_tiles
