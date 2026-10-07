from pathlib import Path

import polars as pl
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QWheelEvent
from PySide6.QtWidgets import QApplication, QToolButton
from pytestqt.qtbot import QtBot

from mtl_park_map.slippy.layers import MarkerLayer, MarkerStyle
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
    map_widget.marker_clicked.connect(lambda name, idx: clicked.append((name, idx)))
    map_widget.set_layers([_layer_at(map_widget, (400, 300))])
    world_pt = map_widget.view.screen_to_world(400.0, 300.0)

    qtbot.mousePress(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(400, 300))
    qtbot.mouseMove(map_widget, QPoint(430, 310))
    qtbot.mouseMove(map_widget, QPoint(450, 320))
    qtbot.mouseRelease(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(450, 320))

    assert map_widget.view.world_to_screen(*world_pt) == pytest.approx((450.0, 320.0))
    assert clicked == []  # a drag is not a click


def test_pan_is_clamped_to_bounds(map_widget: MapWidget):
    map_widget.center_on(-60.0, 45.5)
    min_lon, _, max_lon, _ = map_widget.view.bbox()
    assert max_lon == pytest.approx(CONFIG.bounds[2])


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
    with qtbot.waitSignal(map_widget.marker_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(401, 301))
    assert blocker.args == ["signs", 1]
    # overlapping markers: the topmost (last) layer wins
    with qtbot.waitSignal(map_widget.marker_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(map_widget, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    assert blocker.args == ["signs", 0]


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
