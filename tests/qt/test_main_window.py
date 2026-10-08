from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from PySide6.QtCore import QPoint, QSettings, Qt, QTime, QUrl
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mtl_park_map.enums import SignCategory
from mtl_park_map.models import SignQuery
from mtl_park_map.slippy.tiles import TileLoader
from mtl_park_map.store import Store
from mtl_park_map.ui.filters import default_filters
from mtl_park_map.ui.legend import Legend
from mtl_park_map.ui.main_window import MainWindow

NOW = datetime(2026, 10, 6, 10, 0)  # Tuesday 10:00
DEFAULT_SUMMARY = "4 signs · 3 paid spots (2 free) · 3 curb strips (0 parkable)"

type Geocoder = Callable[[str], tuple[float, float] | None]
type WindowFactory = Callable[..., MainWindow]


class FakeGeocoder:
    def __init__(
        self, result: tuple[float, float] | None = None, error: Exception | None = None
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def __call__(self, address: str) -> tuple[float, float] | None:
        self.calls.append(address)
        if self.error is not None:
            raise self.error
        return self.result


class BrokenStore(Store):
    def query_signs(self, q: SignQuery) -> pl.DataFrame:
        raise RuntimeError("disk on fire")


@pytest.fixture
def make_window(
    qtbot: QtBot, store: Store, tmp_path: Path, qapp: QApplication
) -> Iterator[WindowFactory]:
    template = QUrl.fromLocalFile(str(tmp_path / "tiles")).toString() + "/{z}/{x}/{y}.png"
    tiles = TileLoader(template, user_agent="test")  # kept alive for the whole test
    settings_path = str(tmp_path / "settings.ini")

    def make(geocode: Geocoder | None = None, data: Store | None = None) -> MainWindow:
        window = MainWindow(
            data or store,
            geocode or FakeGeocoder(),
            tiles,
            QSettings(settings_path, QSettings.Format.IniFormat),
            now=lambda: NOW,
        )
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        qtbot.waitUntil(lambda: window.status_label.text() != "Loading…", timeout=5000)
        return window

    yield make


def _layer_names(window: MainWindow) -> list[str]:
    return [layer.name for layer in window.map.layers]


def _click_map_center(qtbot: QtBot, window: MainWindow) -> None:
    center = QPoint(window.map.width() // 2, window.map.height() // 2)
    qtbot.mouseClick(window.map, Qt.MouseButton.LeftButton, pos=center)


def test_startup_applies_default_filters(make_window: WindowFactory):
    window = make_window()
    assert window.status_label.text() == DEFAULT_SUMMARY
    assert _layer_names(window) == [
        "strips-restricted-inferred",
        "strips-restricted",
        "spots-paid",
        "spots-free",
        "signs-prohibited",
        "signs-permitted",
    ]
    assert not window.panel.apply_button.isEnabled()


def test_apply_new_filters(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.panel.show_spots.setChecked(False)
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    summary = "4 signs · 3 curb strips (0 parkable)"
    qtbot.waitUntil(lambda: window.status_label.text() == summary, timeout=5000)
    assert _layer_names(window) == [
        "strips-restricted-inferred",
        "strips-restricted",
        "signs-prohibited",
        "signs-permitted",
    ]


def test_nothing_selected(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.panel.show_signs.setChecked(False)
    window.panel.show_spots.setChecked(False)
    window.panel.show_strips.setChecked(False)
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.status_label.text() == "Nothing selected", timeout=5000)
    assert window.map.layers == []


def test_sign_marker_click_opens_popup(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.map.center_on(-73.560, 45.500, zoom=18)  # sign 0 (over spot S1)
    _click_map_center(qtbot, window)
    assert window.map.popup.isVisible()
    assert "Permitted sign" in window.map.popup.text()
    assert "9h-17h LUN A VEN" in window.map.popup.text()


def test_spot_marker_click_shows_status(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    # spot S3 shares its location with no-stopping sign 2, so hide signs first
    window.panel.show_signs.setChecked(False)
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    summary = "3 paid spots (2 free) · 3 curb strips (0 parkable)"
    qtbot.waitUntil(lambda: window.status_label.text() == summary, timeout=5000)
    window.map.center_on(-73.562, 45.502, zoom=18)
    _click_map_center(qtbot, window)
    assert "<b>Free</b> at the selected time" in window.map.popup.text()
    assert "Rue Z" in window.map.popup.text()


def test_strip_click_shows_status_and_rules(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    # middle of strip 0 (Rue X, north side, no parking Tuesdays 8-11)
    window.map.center_on(-73.5597, 45.5001, zoom=18)
    _click_map_center(qtbot, window)
    text = window.map.popup.text()
    assert "<b>No parking</b> at the selected time" in text
    assert "Rue X" in text and r"\P 8h-11h MARDI" in text


def test_strips_parkable_on_another_day(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.panel.day_start.setCurrentIndex(2)  # Wednesday
    window.panel.day_end.setCurrentIndex(2)
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "3 curb strips (2 parkable)" in window.status_label.text(), timeout=5000)
    assert "strips-parkable" in _layer_names(window)


def test_find_address_pins_and_zooms(qtbot: QtBot, make_window: WindowFactory):
    geocoder = FakeGeocoder(result=(-73.5772, 45.5048))
    window = make_window(geocode=geocoder)
    window.panel.address_edit.setText("McGill University")
    qtbot.keyClick(window.panel.address_edit, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: window.map.view.zoom == 17, timeout=5000)
    assert geocoder.calls == ["McGill University"]
    assert window.map.center_lonlat() == pytest.approx((-73.5772, 45.5048))
    assert not window.panel.address_status.isVisible()


def test_address_not_found(qtbot: QtBot, make_window: WindowFactory):
    window = make_window(geocode=FakeGeocoder(result=None))
    window.find_address("nowhere")
    qtbot.waitUntil(
        lambda: window.panel.address_status.text() == "Address not found.", timeout=5000
    )


def test_geocoder_error_is_reported(qtbot: QtBot, make_window: WindowFactory):
    window = make_window(geocode=FakeGeocoder(error=TimeoutError("service down")))
    window.find_address("anywhere")
    qtbot.waitUntil(
        lambda: window.panel.address_status.text() == "Search failed: service down",
        timeout=5000,
    )


def test_query_failure_is_reported(
    make_window: WindowFactory,
    store_frames: tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame],
):
    window = make_window(data=BrokenStore(*store_frames))
    assert window.status_label.text() == "Query failed: disk on fire"


def test_map_view_is_restored_next_session(make_window: WindowFactory):
    first = make_window()
    first.map.center_on(-73.60, 45.52, zoom=15)
    first.map.set_bearing(72.5)
    first.close()
    second = make_window()
    assert second.map.view.zoom == 15
    assert second.map.view.bearing == pytest.approx(72.5)
    assert second.map.center_lonlat() == pytest.approx((-73.60, 45.52))


def test_show_only_parkable_strips(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.panel.day_start.setCurrentIndex(2)  # Wednesday: strips 0 and 2 parkable
    window.panel.day_end.setCurrentIndex(2)
    window.panel.strip_status_combo.setCurrentIndex(1)  # parkable only
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "2 curb strips (2 parkable)" in window.status_label.text(), timeout=5000)
    names = _layer_names(window)
    assert "strips-parkable" in names and "strips-restricted" not in names


def test_show_only_no_parking_strips(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.panel.day_start.setCurrentIndex(2)
    window.panel.day_end.setCurrentIndex(2)
    window.panel.strip_status_combo.setCurrentIndex(2)  # no parking only
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "1 curb strips (0 parkable)" in window.status_label.text(), timeout=5000)
    names = _layer_names(window)
    assert "strips-restricted" in names and "strips-parkable" not in names


def test_signs_can_ignore_the_time_window(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    # 20:00-21:00: the weekday 9-17 parking signs (0 and 3) are not in force
    window.panel.hour_start.setTime(QTime(20, 0))
    window.panel.hour_end.setTime(QTime(21, 0))
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.status_label.text().startswith("2 signs ·"), timeout=5000)

    window.panel.signs_ignore_time.setChecked(True)
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window.status_label.text().startswith("4 signs (any time) ·"), timeout=5000
    )


def test_sign_popup_shows_arrow_direction(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.map.center_on(-73.560, 45.500, zoom=18)  # sign 0
    _click_map_center(qtbot, window)
    text = window.map.popup.text()
    assert "Arrow: → right" in text and "points east along Rue X" in text


def test_hovering_a_strip_highlights_its_sign_poles(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.map.center_on(-73.5597, 45.5001, zoom=18)  # middle of strip 0
    center = QPoint(window.map.width() // 2, window.map.height() // 2)
    qtbot.mouseMove(window.map, center)
    highlight = window.map.highlight
    assert len(highlight.points) == 1
    assert highlight.points[0] == pytest.approx((-73.560, 45.500))  # sign 0's pole
    assert [pytest.approx(v) for v in ((-73.5600, 45.5001), (-73.5594, 45.5001))] == list(
        highlight.line
    )
    qtbot.mouseMove(window.map, QPoint(5, 5))
    assert window.map.highlight.points == ()


def test_inferred_strips_can_be_left_out(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.panel.include_inferred_strips.setChecked(False)
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "2 curb strips (0 parkable)" in window.status_label.text(), timeout=5000)
    assert "strips-restricted-inferred" not in _layer_names(window)


def test_legend_collapsed_state_is_restored(qtbot: QtBot, make_window: WindowFactory):
    first = make_window()
    legend = first.findChild(Legend)
    assert legend is not None and not legend.collapsed
    qtbot.mouseClick(legend.header, Qt.MouseButton.LeftButton)
    first.close()
    second = make_window()
    restored = second.findChild(Legend)
    assert restored is not None and restored.collapsed


# --- hotspots, persistent filters, persistent startup -------------------------------

MCGILL = (-73.5772, 45.5048)


def _search(qtbot: QtBot, window: MainWindow, address: str) -> None:
    window.panel.address_edit.setText(address)
    qtbot.keyClick(window.panel.address_edit, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: window.map.pin is not None, timeout=5000)


def _pick_hotspot(window: MainWindow, name: str) -> None:
    combo = window.panel.hotspot_combo
    index = combo.findText(name)
    assert index > 0, f"{name} not in the hotspot list"
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def test_save_and_jump_to_a_hotspot(qtbot: QtBot, make_window: WindowFactory):
    window = make_window(geocode=FakeGeocoder(result=MCGILL))
    assert not window.panel.save_hotspot_button.isEnabled()  # nothing searched yet
    _search(qtbot, window, "McGill")
    qtbot.mouseClick(window.panel.save_hotspot_button, Qt.MouseButton.LeftButton)
    window.map.center_on(-73.62, 45.55, zoom=13)  # wander off
    window.map.set_pin(None)
    _pick_hotspot(window, "McGill")
    assert window.map.view.zoom == 17
    assert window.map.center_lonlat() == pytest.approx(MCGILL)
    assert window.map.pin == pytest.approx(MCGILL)
    assert window.panel.address_edit.text() == "McGill"


def test_hotspots_persist_and_can_be_removed(qtbot: QtBot, make_window: WindowFactory):
    first = make_window(geocode=FakeGeocoder(result=MCGILL))
    _search(qtbot, first, "McGill")
    qtbot.mouseClick(first.panel.save_hotspot_button, Qt.MouseButton.LeftButton)
    first.close()
    second = make_window()
    assert second.panel.hotspot_combo.findText("McGill") > 0
    second.panel.hotspot_combo.setCurrentIndex(second.panel.hotspot_combo.findText("McGill"))
    qtbot.mouseClick(second.panel.remove_hotspot_button, Qt.MouseButton.LeftButton)
    assert second.panel.hotspot_combo.findText("McGill") == -1
    second.close()
    assert make_window().panel.hotspot_combo.findText("McGill") == -1


def test_non_time_filters_persist_but_the_window_restarts_at_now(
    qtbot: QtBot, make_window: WindowFactory
):
    first = make_window()
    panel = first.panel
    panel.show_spots.setChecked(False)
    panel.category_checks[SignCategory.other].setChecked(True)
    panel.strip_status_combo.setCurrentIndex(1)  # parkable only
    panel.include_inferred_strips.setChecked(False)
    panel.signs_ignore_time.setChecked(True)
    panel.hour_start.setTime(QTime(20, 0))  # time: not remembered
    qtbot.mouseClick(panel.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: first.status_label.text() != "Loading…", timeout=5000)
    first.close()

    state = make_window().panel.state()
    assert not state.show_spots
    assert SignCategory.other in state.categories
    assert state.strip_restricted is False and not state.include_inferred_strips
    assert state.signs_ignore_time
    assert state.hours == default_filters(NOW).hours  # back to "now"


def test_unapplied_edits_are_not_remembered(make_window: WindowFactory):
    first = make_window()
    first.panel.show_spots.setChecked(False)  # never applied
    first.close()
    assert make_window().panel.state().show_spots


def test_last_address_pin_is_restored(qtbot: QtBot, make_window: WindowFactory):
    first = make_window(geocode=FakeGeocoder(result=MCGILL))
    _search(qtbot, first, "McGill")
    first.close()
    second = make_window()
    assert second.map.pin == pytest.approx(MCGILL)
    assert second.panel.address_edit.text() == "McGill"
    assert second.panel.save_hotspot_button.isEnabled()


def test_clearing_the_address_removes_the_pin(qtbot: QtBot, make_window: WindowFactory):
    first = make_window(geocode=FakeGeocoder(result=MCGILL))
    _search(qtbot, first, "McGill")
    first.panel.address_edit.clear()
    assert first.map.pin is None
    assert not first.panel.save_hotspot_button.isEnabled()
    first.close()
    assert make_window().map.pin is None
