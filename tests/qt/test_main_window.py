from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from PySide6.QtCore import QPoint, QSettings, Qt, QUrl
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mtl_park_map.models import SignQuery
from mtl_park_map.slippy.tiles import TileLoader
from mtl_park_map.store import Store
from mtl_park_map.ui.main_window import MainWindow

NOW = datetime(2026, 10, 6, 10, 0)  # Tuesday 10:00
DEFAULT_SUMMARY = "3 signs · 3 paid spots (2 free)"

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
    assert _layer_names(window) == ["spots-paid", "spots-free", "signs-permitted"]
    assert not window.panel.apply_button.isEnabled()


def test_apply_new_filters(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.panel.show_spots.setChecked(False)
    qtbot.mouseClick(window.panel.apply_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.status_label.text() == "3 signs", timeout=5000)
    assert _layer_names(window) == ["signs-permitted"]


def test_nothing_selected(qtbot: QtBot, make_window: WindowFactory):
    window = make_window()
    window.panel.show_signs.setChecked(False)
    window.panel.show_spots.setChecked(False)
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
    window.map.center_on(-73.562, 45.502, zoom=18)  # spot S3 (sign 2 is hidden)
    _click_map_center(qtbot, window)
    assert "<b>Free</b> at the selected time" in window.map.popup.text()
    assert "Rue Z" in window.map.popup.text()


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
    make_window: WindowFactory, store_frames: tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]
):
    window = make_window(data=BrokenStore(*store_frames))
    assert window.status_label.text() == "Query failed: disk on fire"


def test_map_view_is_restored_next_session(make_window: WindowFactory):
    first = make_window()
    first.map.center_on(-73.60, 45.52, zoom=15)
    first.close()
    second = make_window()
    assert second.map.view.zoom == 15
    assert second.map.center_lonlat() == pytest.approx((-73.60, 45.52))
