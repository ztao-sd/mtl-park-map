from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QNativeGestureEvent, QPointingDevice, QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel, QToolButton
from pytestqt.qtbot import QtBot

from mtl_park_map.slippy.layers import MarkerLayer, MarkerStyle
from mtl_park_map.slippy.lines import LineLayer, LineStyle
from mtl_park_map.slippy.map_widget import MapConfig, MapWidget
from mtl_park_map.slippy.projection import lonlat_to_world, world_to_lonlat
from mtl_park_map.slippy.tiles import TileLoader
from mtl_park_map.slippy.viewport import TileKey

MONTREAL = (-73.5673, 45.5017)
CONFIG = MapConfig(
    center=MONTREAL,
    zoom=13,
    min_zoom=11,
    max_zoom=19,
    bounds=(-73.97, 45.41, -73.48, 45.70),
    attribution="© test contributors",
)
STYLE = MarkerStyle(color="#2563eb")


@pytest.fixture
def tile_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def tiles(tile_dir: Path, qapp: QApplication) -> TileLoader:
    template = QUrl.fromLocalFile(str(tile_dir)).toString() + "/{z}/{x}/{y}.png"
    return TileLoader(template, user_agent="test")


@pytest.fixture
def map_widget(qtbot: QtBot, tiles: TileLoader) -> MapWidget:
    widget = MapWidget(tiles, CONFIG)
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _layer_at(widget: MapWidget, *screen_pts: tuple[float, float], name: str = "signs") -> MarkerLayer:
    view = widget.view
    lonlat = [world_to_lonlat(*view.screen_to_world(x, y)) for x, y in screen_pts]
    df = pl.DataFrame({"longitude": [p[0] for p in lonlat], "latitude": [p[1] for p in lonlat]})
    return MarkerLayer(name, STYLE, df)


def _wheel(widget: MapWidget, pos: QPointF, delta_y: int) -> None:
    event = QWheelEvent(
        pos,
        widget.mapToGlobal(pos),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_initial_view(map_widget: MapWidget):
    view = map_widget.view
    assert (view.width, view.height, view.zoom) == (800, 600, 13)
    assert view.center == pytest.approx(lonlat_to_world(*MONTREAL))


def test_wheel_zooms_around_cursor(map_widget: MapWidget):
    anchor = map_widget.view.screen_to_world(200.0, 150.0)
    _wheel(map_widget, QPointF(200, 150), 120)
    assert map_widget.view.zoom == 14
    assert map_widget.view.world_to_screen(*anchor) == pytest.approx((200.0, 150.0))


def test_wheel_accumulates_small_trackpad_deltas(map_widget: MapWidget):
    _wheel(map_widget, QPointF(400, 300), 60)
    assert map_widget.view.zoom == 13
    _wheel(map_widget, QPointF(400, 300), 60)
    assert map_widget.view.zoom == 14


def test_wheel_beyond_max_zoom_does_not_drift(map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=19)
    before = map_widget.view
    _wheel(map_widget, QPointF(100, 100), 120)
    assert map_widget.view == before


def test_drag_pans(qtbot: QtBot, map_widget: MapWidget):
    clicked: list[tuple[str, int]] = []
    map_widget.feature_clicked.connect(lambda name, idx, lon, lat: clicked.append((name, idx)))
    map_widget.set_layers([_layer_at(map_widget, (400, 300))])
    world_pt = map_widget.view.screen_to_world(400.0, 300.0)

    qtbot.mousePress(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    qtbot.mouseMove(map_widget, QPoint(430, 310))
    qtbot.mouseMove(map_widget, QPoint(450, 320))
    qtbot.mouseRelease(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(450, 320))

    assert map_widget.view.world_to_screen(*world_pt) == pytest.approx((450.0, 320.0))
    assert clicked == []  # a drag is not a click


def test_pan_is_clamped_to_bounds(map_widget: MapWidget):
    map_widget.center_on(-60.0, 50.0)
    assert map_widget.center_lonlat() == pytest.approx((CONFIG.bounds[2], CONFIG.bounds[3]))


def test_can_drag_past_bounds_when_zoomed_out(qtbot: QtBot, map_widget: MapWidget):
    # at min zoom the whole bounds fit on screen; dragging must still move the map
    map_widget.center_on(*MONTREAL, zoom=CONFIG.min_zoom)
    before = map_widget.view.center
    qtbot.mousePress(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    qtbot.mouseMove(map_widget, QPoint(450, 300))
    qtbot.mouseMove(map_widget, QPoint(500, 300))
    qtbot.mouseRelease(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(500, 300))
    assert map_widget.view.center[0] < before[0]


def test_viewport_changed_signal(qtbot: QtBot, map_widget: MapWidget):
    with qtbot.waitSignal(map_widget.viewport_changed, timeout=1000) as blocker:
        map_widget.center_on(-73.6, 45.52)
    assert blocker.args[0] == map_widget.view


def test_keyboard_zoom_and_pan(qtbot: QtBot, map_widget: MapWidget):
    qtbot.keyClick(map_widget, Qt.Key.Key_Plus)
    assert map_widget.view.zoom == 14
    qtbot.keyClick(map_widget, Qt.Key.Key_Minus)
    assert map_widget.view.zoom == 13
    center = map_widget.view.center
    qtbot.keyClick(map_widget, Qt.Key.Key_Left)
    assert map_widget.view.center[0] < center[0]


def test_zoom_buttons(qtbot: QtBot, map_widget: MapWidget):
    buttons = {b.text(): b for b in map_widget.findChildren(QToolButton)}
    qtbot.mouseClick(buttons["+"], Qt.MouseButton.LeftButton)
    assert map_widget.view.zoom == 14
    qtbot.mouseClick(buttons["−"], Qt.MouseButton.LeftButton)
    assert map_widget.view.zoom == 13


def test_double_click_zooms_in(qtbot: QtBot, map_widget: MapWidget):
    qtbot.mouseDClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    assert map_widget.view.zoom == 14


def test_click_single_marker_emits(qtbot: QtBot, map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=18)
    map_widget.set_layers(
        [_layer_at(map_widget, (100, 100), name="spots"), _layer_at(map_widget, (100, 100), (400, 300))]
    )
    with qtbot.waitSignal(map_widget.feature_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(401, 301))
    assert blocker.args[:2] == ["signs", 1]
    # overlapping markers: the topmost (last) layer wins
    with qtbot.waitSignal(map_widget.feature_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    assert blocker.args[:2] == ["signs", 0]


def test_click_cluster_zooms_in_on_it(qtbot: QtBot, map_widget: MapWidget):
    layer = _layer_at(map_widget, *[(300 + i, 200) for i in range(5)])
    map_widget.set_layers([layer])
    hit = layer.hit_test(map_widget.view, 302.0, 200.0)
    assert hit is not None and hit.count == 5
    qtbot.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(302, 200))
    assert map_widget.view.zoom == 15
    assert map_widget.view.center == pytest.approx((hit.x, hit.y))


def test_popup_follows_anchor_and_closes(qtbot: QtBot, map_widget: MapWidget):
    map_widget.show_popup("<b>Hello</b> &amp; bye", *MONTREAL)
    popup = map_widget.popup
    assert popup.isVisible()
    assert "Hello" in popup.text()
    # bottom-centre of the popup sits just above the anchor (screen centre)
    assert abs(popup.geometry().center().x() - 400) <= 1
    assert popup.geometry().bottom() < 300

    map_widget.center_on(*world_to_lonlat(*map_widget.view.screen_to_world(500.0, 300.0)))
    assert abs(popup.geometry().center().x() - 300) <= 1  # moved with the map

    qtbot.keyClick(map_widget, Qt.Key.Key_Escape)
    assert not popup.isVisible()


def test_click_on_empty_map_closes_popup(qtbot: QtBot, map_widget: MapWidget):
    map_widget.show_popup("x", *MONTREAL)
    qtbot.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(50, 550))
    assert not map_widget.popup.isVisible()


def test_new_layers_close_popup(map_widget: MapWidget):
    map_widget.show_popup("x", *MONTREAL)
    map_widget.set_layers([])
    assert not map_widget.popup.isVisible()


def test_visible_tiles_are_loaded(qtbot: QtBot, tile_dir: Path, tiles: TileLoader):
    x, y = lonlat_to_world(*MONTREAL)
    key = TileKey(13, int(x * 2**13), int(y * 2**13))
    path = tile_dir / "13" / str(key.x) / f"{key.y}.png"
    path.parent.mkdir(parents=True)
    image = QImage(256, 256, QImage.Format.Format_RGB32)
    image.fill(QColor("green"))
    image.save(str(path))

    widget = MapWidget(tiles, CONFIG)
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    qtbot.waitUntil(lambda: tiles.tile(key) is not None, timeout=5000)
    # the loaded tile is painted under the (marker-free) centre
    assert widget.grab().toImage().pixelColor(400, 300) == QColor("green")


def test_paints_layers_clusters_and_pin(map_widget: MapWidget):
    map_widget.set_layers([_layer_at(map_widget, (200, 200), *[(500 + i, 400) for i in range(30)])])
    map_widget.set_pin(MONTREAL)
    image = map_widget.grab().toImage()
    assert not image.isNull()
    assert image.pixelColor(200, 200) == QColor(STYLE.color)  # single marker fill
    # the pin's red head (centred 22 px above its tip at the centre, white dot inside)
    pin = image.pixelColor(400, 271)
    assert pin.red() > 180 and pin.green() < 100


def _line_layer_at(widget: MapWidget, *points: tuple[float, float]) -> LineLayer:
    view = widget.view
    lonlat = [world_to_lonlat(*view.screen_to_world(x, y)) for x, y in points]
    df = pl.DataFrame({"longitudes": [[p[0] for p in lonlat]], "latitudes": [[p[1] for p in lonlat]]})
    return LineLayer("strips", LineStyle(color="#16a34a", width=6.0), df, min_zoom=15)


def test_line_layer_paints_and_is_clickable(qtbot: QtBot, map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=17)
    map_widget.set_layers([_line_layer_at(map_widget, (100, 450), (700, 450))])
    image = map_widget.grab().toImage()
    assert image.pixelColor(400, 450) == QColor("#16a34a")
    with qtbot.waitSignal(map_widget.feature_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(400, 452))
    assert blocker.args[:2] == ["strips", 0]
    # a line popup anchors where the user clicked
    clicked_at = map_widget.view.world_to_screen(*lonlat_to_world(*blocker.args[2:]))
    assert clicked_at == pytest.approx((400.0, 452.0), abs=0.5)


def test_line_layer_hidden_when_zoomed_out(map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=17)
    layer = _line_layer_at(map_widget, (100, 450), (700, 450))
    map_widget.set_layers([layer])
    map_widget.center_on(*MONTREAL, zoom=14)
    x, y = map_widget.view.world_to_screen(*map_widget.view.screen_to_world(400, 450))
    assert map_widget.grab().toImage().pixelColor(round(x), round(y)) != QColor("#16a34a")


# --- rotation -----------------------------------------------------------------------


def _compass(widget: MapWidget) -> QToolButton:
    button = widget.findChild(QToolButton, "Compass")
    assert button is not None
    return button


def test_set_bearing_rotates_about_the_centre(map_widget: MapWidget):
    center = map_widget.view.center
    map_widget.set_bearing(45.0)
    assert map_widget.view.bearing == 45.0
    assert map_widget.view.center == center


def test_right_drag_rotates_around_the_centre(qtbot: QtBot, map_widget: MapWidget):
    # cursor goes from right of the centre to above it: a quarter turn
    # counter-clockwise, so what was east (right) ends up on top: bearing 90
    qtbot.mousePress(map_widget, Qt.MouseButton.RightButton, pos=QPoint(600, 300))
    qtbot.mouseMove(map_widget, QPoint(541, 159))
    qtbot.mouseMove(map_widget, QPoint(400, 100))
    qtbot.mouseRelease(map_widget, Qt.MouseButton.RightButton, pos=QPoint(400, 100))
    assert map_widget.view.bearing == pytest.approx(90.0)


def test_ctrl_drag_rotates(qtbot: QtBot, map_widget: MapWidget):
    center = map_widget.view.center
    qtbot.mousePress(
        map_widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(600, 300)
    )
    qtbot.mouseMove(map_widget, QPoint(400, 500))  # clockwise quarter turn
    qtbot.mouseRelease(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(400, 500))
    assert map_widget.view.bearing == pytest.approx(270.0)
    assert map_widget.view.center == pytest.approx(center)  # rotating does not pan


def test_shift_arrows_rotate_and_n_resets(qtbot: QtBot, map_widget: MapWidget):
    center = map_widget.view.center
    qtbot.keyClick(map_widget, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert map_widget.view.bearing == pytest.approx(15.0)
    qtbot.keyClick(map_widget, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    qtbot.keyClick(map_widget, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    assert map_widget.view.bearing == pytest.approx(345.0)
    assert map_widget.view.center == center
    qtbot.keyClick(map_widget, Qt.Key.Key_N)
    assert map_widget.view.bearing == 0.0


def test_compass_shows_bearing_and_resets_north(qtbot: QtBot, map_widget: MapWidget):
    map_widget.set_bearing(120.0)
    compass = _compass(map_widget)
    assert compass.property("bearing") == pytest.approx(120.0)
    qtbot.mouseClick(compass, Qt.MouseButton.LeftButton)
    assert map_widget.view.bearing == 0.0
    assert compass.property("bearing") == pytest.approx(0.0)


def test_wheel_zoom_anchored_when_rotated(map_widget: MapWidget):
    map_widget.set_bearing(60.0)
    anchor = map_widget.view.screen_to_world(200.0, 150.0)
    _wheel(map_widget, QPointF(200, 150), 120)
    assert map_widget.view.world_to_screen(*anchor) == pytest.approx((200.0, 150.0))


def test_rotated_markers_draw_and_click_where_they_appear(qtbot: QtBot, map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=18)
    map_widget.set_layers([_layer_at(map_widget, (500, 300))])  # 100 px east
    map_widget.set_bearing(90.0)  # east up: the marker moves above the centre
    assert map_widget.grab().toImage().pixelColor(400, 200) == QColor(STYLE.color)
    with qtbot.waitSignal(map_widget.feature_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(400, 201))
    assert blocker.args[:2] == ["signs", 0]


def test_rotated_tiles_are_painted(qtbot: QtBot, tile_dir: Path, tiles: TileLoader):
    x, y = lonlat_to_world(*MONTREAL)
    for dx, dy in [(-1, -1), (0, -1), (1, -1), (-1, 0), (0, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]:
        key = TileKey(13, int(x * 2**13) + dx, int(y * 2**13) + dy)
        path = tile_dir / "13" / str(key.x) / f"{key.y}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(256, 256, QImage.Format.Format_RGB32)
        image.fill(QColor("green"))
        image.save(str(path))
    widget = MapWidget(tiles, CONFIG)
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    widget.show()
    widget.set_bearing(30.0)
    qtbot.waitUntil(lambda: tiles.pending_count() == 0, timeout=5000)
    image = widget.grab().toImage()
    # the rotated composite covers the whole view, corners included, with no seams
    # (sampled away from the zoom controls / attribution overlays on the right)
    for px, py in [(200, 150), (5, 5), (5, 295), (60, 295), (395, 150), (200, 5)]:
        assert image.pixelColor(px, py) == QColor("green"), (px, py)


def test_native_rotate_gesture(map_widget: MapWidget):
    event = QNativeGestureEvent(
        Qt.NativeGestureType.RotateNativeGesture,
        QPointingDevice.primaryPointingDevice(),
        2,
        QPointF(400, 300),
        QPointF(400, 300),
        map_widget.mapToGlobal(QPointF(400, 300)),
        20.0,
        QPointF(0, 0),
    )
    QApplication.sendEvent(map_widget, event)
    assert map_widget.view.bearing == pytest.approx(340.0)  # 20° clockwise twist


def test_initial_bearing_from_config(qtbot: QtBot, tiles: TileLoader):
    widget = MapWidget(tiles, replace(CONFIG, bearing=200.0))
    qtbot.addWidget(widget)
    assert widget.view.bearing == 200.0


# --- hide data layers, keep the address pin -------------------------------------


def _visibility_button(widget: MapWidget) -> QToolButton:
    button = widget.findChild(QToolButton, "HideLayers")
    assert button is not None
    return button


def test_hiding_layers_keeps_only_the_pin(qtbot: QtBot, map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=18)
    map_widget.set_layers(
        [_layer_at(map_widget, (200, 200)), _line_layer_at(map_widget, (100, 450), (700, 450))]
    )
    map_widget.set_pin(MONTREAL)
    with qtbot.waitSignal(map_widget.layers_visibility_changed, timeout=1000) as blocker:
        map_widget.set_layers_visible(False)
    assert blocker.args == [False]
    image = map_widget.grab().toImage()
    assert image.pixelColor(200, 200) != QColor(STYLE.color)  # marker gone
    assert image.pixelColor(400, 450) != QColor("#16a34a")  # strip gone
    pin = image.pixelColor(400, 271)
    assert pin.red() > 180 and pin.green() < 100  # pin still drawn


def test_hidden_layers_are_not_clickable(qtbot: QtBot, map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=18)
    map_widget.set_layers([_layer_at(map_widget, (400, 300))])
    map_widget.show_popup("x", *MONTREAL)
    map_widget.set_layers_visible(False)
    assert not map_widget.popup.isVisible()  # it described a now-hidden feature
    clicked: list[str] = []
    map_widget.feature_clicked.connect(lambda name, idx, lon, lat: clicked.append(name))
    qtbot.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    assert clicked == []


def test_new_layers_stay_hidden_until_shown_again(map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=18)
    map_widget.set_layers_visible(False)
    map_widget.set_layers([_layer_at(map_widget, (200, 200))])
    assert map_widget.grab().toImage().pixelColor(200, 200) != QColor(STYLE.color)
    map_widget.set_layers_visible(True)
    assert map_widget.grab().toImage().pixelColor(200, 200) == QColor(STYLE.color)


def test_visibility_button_and_shortcut(qtbot: QtBot, map_widget: MapWidget):
    button = _visibility_button(map_widget)
    assert not button.isChecked() and map_widget.layers_visible
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert button.isChecked() and not map_widget.layers_visible
    qtbot.keyClick(map_widget, Qt.Key.Key_H)
    assert not button.isChecked() and map_widget.layers_visible


# --- hover + highlight ------------------------------------------------------------


def _record_hovers(widget: MapWidget) -> list[tuple[str, int]]:
    hovers: list[tuple[str, int]] = []
    widget.hover_changed.connect(lambda name, idx: hovers.append((name, idx)))
    return hovers


def _lonlat_at(widget: MapWidget, x: float, y: float) -> tuple[float, float]:
    return world_to_lonlat(*widget.view.screen_to_world(x, y))


def test_hover_reports_a_feature_and_clears(qtbot: QtBot, map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=17)
    map_widget.set_layers([_line_layer_at(map_widget, (100, 450), (700, 450))])
    hovers = _record_hovers(map_widget)
    qtbot.mouseMove(map_widget, QPoint(400, 452))
    qtbot.mouseMove(map_widget, QPoint(410, 451))  # same feature: no repeat
    qtbot.mouseMove(map_widget, QPoint(400, 100))
    assert hovers == [("strips", 0), ("", -1)]


def test_hovering_a_cluster_reports_nothing(qtbot: QtBot, map_widget: MapWidget):
    map_widget.set_layers([_layer_at(map_widget, *[(300 + i, 200) for i in range(5)])])
    hovers = _record_hovers(map_widget)
    qtbot.mouseMove(map_widget, QPoint(302, 200))
    assert hovers == []


def test_leaving_the_map_clears_the_hover(qtbot: QtBot, map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=17)
    map_widget.set_layers([_line_layer_at(map_widget, (100, 450), (700, 450))])
    hovers = _record_hovers(map_widget)
    qtbot.mouseMove(map_widget, QPoint(400, 452))
    QApplication.sendEvent(map_widget, QEvent(QEvent.Type.Leave))
    assert hovers == [("strips", 0), ("", -1)]


def test_highlight_rings_points_and_glows_the_line(map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=17)
    line = [_lonlat_at(map_widget, 100, 450), _lonlat_at(map_widget, 700, 450)]
    map_widget.set_highlight(points=[_lonlat_at(map_widget, 300, 300)], line=line)
    assert len(map_widget.highlight.points) == 1
    assert map_widget.highlight.points[0] == pytest.approx(_lonlat_at(map_widget, 300, 300))
    image = map_widget.grab().toImage()
    ring = image.pixelColor(309, 300)  # on the ring, 9 px from the pole
    assert ring.red() > 200 and ring.green() > 150 and ring.blue() < 100
    glow = image.pixelColor(400, 455)  # beside the line's axis
    assert glow.red() > 200 and glow.blue() < 150
    map_widget.clear_highlight()
    assert map_widget.highlight.points == () and map_widget.highlight.line == ()
    assert map_widget.grab().toImage().pixelColor(309, 300) != ring


def test_highlight_cleared_by_new_or_hidden_layers(map_widget: MapWidget):
    map_widget.set_highlight(points=[MONTREAL])
    map_widget.set_layers([])
    assert map_widget.highlight.points == ()
    map_widget.set_highlight(points=[MONTREAL])
    map_widget.set_layers_visible(False)
    assert map_widget.highlight.points == ()


def test_dashed_lines_have_gaps(map_widget: MapWidget):
    map_widget.center_on(*MONTREAL, zoom=17)
    view = map_widget.view
    lonlat = [world_to_lonlat(*view.screen_to_world(x, 450)) for x in (100, 700)]
    df = pl.DataFrame({"longitudes": [[p[0] for p in lonlat]], "latitudes": [[p[1] for p in lonlat]]})
    map_widget.set_layers([LineLayer("strips", LineStyle("#16a34a", 6.0, dashed=True), df)])
    image = map_widget.grab().toImage()
    on_line = [image.pixelColor(x, 450) == QColor("#16a34a") for x in range(150, 650)]
    assert 0.3 < sum(on_line) / len(on_line) < 0.9  # dashes and gaps


def test_overlays_follow_their_size_changes(qtbot: QtBot, map_widget: MapWidget):
    label = QLabel("one line")
    map_widget.add_overlay(label, Qt.Corner.BottomLeftCorner)
    label.setText("one line\nsecond line\nthird line")
    # it grows to its new size, still anchored to the bottom-left corner
    qtbot.waitUntil(
        lambda: label.height() == label.sizeHint().height()
        and label.geometry().bottom() == map_widget.height() - 10 - 1,
        timeout=1000,
    )


def test_pin_property(map_widget: MapWidget):
    assert map_widget.pin is None
    map_widget.set_pin(MONTREAL)
    assert map_widget.pin == pytest.approx(MONTREAL)
    map_widget.set_pin(None)
    assert map_widget.pin is None
