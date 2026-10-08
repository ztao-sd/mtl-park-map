"""Main window: native map in the centre, filter panel docked on the right."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QScrollArea, QWidget

from mtl_park_map import settings
from mtl_park_map.slippy.map_widget import MapConfig, MapWidget
from mtl_park_map.slippy.tiles import TileLoader
from mtl_park_map.store import Store
from mtl_park_map.ui.filter_panel import FilterPanel
from mtl_park_map.ui.filters import (
    FilterState,
    to_sign_query,
    to_spot_query,
    restore_options,
    saved_options,
    to_strip_query,
    window_is_complete,
)
from mtl_park_map.ui.hotspots import (
    Hotspot,
    add_hotspot,
    hotspot_from_json,
    hotspot_to_json,
    hotspots_from_json,
    hotspots_to_json,
    remove_hotspot,
)
from mtl_park_map.ui.legend import Legend
from mtl_park_map.ui.palette import DataLayer, build_layers
from mtl_park_map.slippy.layers import MarkerLayer
from mtl_park_map.ui.popups import (
    SignRow,
    SpotRow,
    StripRow,
    sign_popup_html,
    spot_popup_html,
    strip_popup_html,
)
from mtl_park_map.ui.tasks import BackgroundRunner

type Geocoder = Callable[[str], tuple[float, float] | None]

_FILTERS_KEY = "filters/options"
_HOTSPOTS_KEY = "hotspots/list"
_ADDRESS_KEY = "address/current"
_QUERY_CHANNEL = "query"
_GEOCODE_CHANNEL = "geocode"
_DEFAULT_SIZE = (1280, 820)
_PANEL_MIN_WIDTH = 290


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Everything a finished query hands to the GUI thread.

    Attributes:
        state: The filters the query ran with.
        layers: Map layers, bottom to top.
        sign_count: Signs found, or ``None`` if signs were hidden.
        spot_count: Paid spots found, or ``None`` if spots were hidden.
        free_spot_count: Spots free in the window, or ``None`` if spots were hidden.
        strip_count: Curb strips, or ``None`` if strips were hidden.
        parkable_strip_count: Strips with no rule in force during the window, or
            ``None`` if strips were hidden.
    """

    state: FilterState
    layers: list[DataLayer]
    sign_count: int | None
    spot_count: int | None
    free_spot_count: int | None
    strip_count: int | None
    parkable_strip_count: int | None

    def summary(self) -> str:
        """Human-readable result counts for the status bar."""
        parts: list[str] = []
        if self.sign_count is not None:
            any_time = " (any time)" if self.state.signs_ignore_time else ""
            parts.append(f"{self.sign_count:,} signs{any_time}")
        if self.spot_count is not None:
            text = f"{self.spot_count:,} paid spots"
            if window_is_complete(self.state):
                text += f" ({self.free_spot_count:,} free)"
            parts.append(text)
        if self.strip_count is not None:
            parts.append(
                f"{self.strip_count:,} curb strips ({self.parkable_strip_count:,} parkable)"
            )
        return " · ".join(parts) if parts else "Nothing selected"


def run_query(store: Store, state: FilterState, zoom: int) -> QueryResult:
    """Query the store and prepare map layers. Runs on a worker thread.

    Args:
        store: The data.
        state: Filters to apply.
        zoom: Current map zoom; its clusters are precomputed here so the first
            repaint on the GUI thread is cheap.

    Returns:
        The query result.
    """
    signs = store.query_signs(to_sign_query(state)) if state.show_signs else None
    spots = store.query_spots(to_spot_query(state)) if state.show_spots else None
    strips = store.query_strips(to_strip_query(state)) if state.show_strips else None
    layers = build_layers(signs, spots, strips)
    for data_layer in layers:
        if isinstance(data_layer.layer, MarkerLayer):
            data_layer.layer.clusters(zoom)
    return QueryResult(
        state=state,
        layers=layers,
        sign_count=None if signs is None else signs.height,
        spot_count=None if spots is None else spots.height,
        free_spot_count=None if spots is None else int(spots["is_free"].sum()),
        strip_count=None if strips is None else strips.height,
        parkable_strip_count=None if strips is None else int((~strips["is_restricted"]).sum()),
    )


class MainWindow(QMainWindow):
    """The application window.

    Args:
        store: Parking data.
        geocode: Address → ``(lon, lat)`` lookup (blocking; run off the GUI thread).
        tiles: Map tile source.
        app_settings: Where window/map state is persisted.
        now: Clock for the default time window.
        runner: Background job runner (one is created if omitted).
        parent: Qt parent.
    """

    def __init__(
        self,
        store: Store,
        geocode: Geocoder,
        tiles: TileLoader,
        app_settings: QSettings,
        now: Callable[[], datetime] = datetime.now,
        runner: BackgroundRunner | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._store = store
        self._geocode = geocode
        self._settings = app_settings
        self._runner = runner or BackgroundRunner(parent=self)
        self._layers_by_name: dict[str, DataLayer] = {}
        self._applied: FilterState | None = None
        self._current_address: Hotspot | None = None
        self._hotspots = hotspots_from_json(self._setting_text(_HOTSPOTS_KEY))

        self.setWindowTitle(settings.APP_NAME)
        self.map = MapWidget(tiles, self._map_config())
        self.legend = Legend(
            collapsed=bool(self._settings.value("legend/collapsed", False, type=bool))
        )
        self.map.add_overlay(self.legend, Qt.Corner.BottomLeftCorner)
        self.setCentralWidget(self.map)

        self.panel = FilterPanel(now)
        scroll = QScrollArea()
        scroll.setWidget(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # Scroll vertically on short screens, never horizontally: the dock is at
        # least as wide as the panel's minimum plus a vertical scrollbar.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(
            max(
                _PANEL_MIN_WIDTH,
                self.panel.minimumSizeHint().width()
                + scroll.verticalScrollBar().sizeHint().width(),
            )
        )
        dock = QDockWidget("Filters")
        dock.setObjectName("FiltersDock")  # required by saveState()/restoreState()
        dock.setWidget(scroll)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label, 1)

        self.panel.apply_requested.connect(self.apply_filters)
        self.panel.address_requested.connect(self.find_address)
        self.panel.address_cleared.connect(lambda: self._set_current_address(None))
        self.panel.hotspot_save_requested.connect(self._save_hotspot)
        self.panel.hotspot_selected.connect(self.go_to_hotspot)
        self.panel.hotspot_remove_requested.connect(self._remove_hotspot)
        self.map.feature_clicked.connect(self._on_feature_clicked)
        self.map.hover_changed.connect(self._on_hover_changed)

        self._restore_window()
        self._restore_session()
        self.apply_filters(self.panel.state())

    # ------------------------------------------------------------------ actions

    def apply_filters(self, state: FilterState) -> None:
        """Query in the background and redraw the map with the results.

        Args:
            state: The filters to apply.
        """
        self.panel.mark_applied(state)
        # Remember what was applied (not unapplied edits); time is never saved.
        self._write_setting(_FILTERS_KEY, json.dumps(saved_options(state)))
        self.status_label.setText("Loading…")
        zoom = self.map.view.zoom
        self._runner.submit(
            _QUERY_CHANNEL,
            lambda: run_query(self._store, state, zoom),
            self._on_query_done,
            self._on_query_failed,
        )

    def find_address(self, address: str) -> None:
        """Geocode in the background, then pin and zoom to the result.

        Args:
            address: Free-text address.
        """
        self.panel.set_address_status("Searching…")
        self._runner.submit(
            _GEOCODE_CHANNEL,
            lambda: self._geocode(address),
            lambda lonlat: self._on_geocoded(address, lonlat),
            self._on_geocode_failed,
        )

    def go_to_hotspot(self, hotspot: Hotspot) -> None:
        """Pin a saved place and zoom to it.

        Args:
            hotspot: The place.
        """
        self.panel.set_address_status(None)
        self.panel.address_edit.setText(hotspot.name)
        self._set_current_address(hotspot)
        self.map.center_on(hotspot.lon, hotspot.lat, zoom=settings.ADDRESS_ZOOM)

    # ---------------------------------------------------------------- callbacks

    def _on_query_done(self, result: QueryResult) -> None:
        """Show a finished query on the map."""
        self._applied = result.state
        self._layers_by_name = {dl.spec.name: dl for dl in result.layers}
        self.map.set_layers([dl.layer for dl in result.layers])
        self.status_label.setText(result.summary())

    def _on_query_failed(self, error: Exception) -> None:
        """Report an unexpected query error."""
        self.status_label.setText(f"Query failed: {error}")

    def _on_geocoded(self, address: str, lonlat: tuple[float, float] | None) -> None:
        """Pin and zoom to a found address, which becomes the current address.

        Args:
            address: What was searched (names the place if saved as a hotspot).
            lonlat: Where it is, or ``None`` if not found.
        """
        if lonlat is None:
            self.panel.set_address_status("Address not found.", error=True)
            return
        self.panel.set_address_status(None)
        self._set_current_address(Hotspot(address, *lonlat))
        self.map.center_on(*lonlat, zoom=settings.ADDRESS_ZOOM)

    def _set_current_address(self, address: Hotspot | None) -> None:
        """Pin (or unpin) the current address and remember it for the next launch.

        Args:
            address: The pinned place, or ``None`` to clear the pin.
        """
        if address is None and self._current_address is None:
            return
        self._current_address = address
        self.map.set_pin(None if address is None else (address.lon, address.lat))
        self.panel.set_can_save_hotspot(address is not None)
        self._write_setting(_ADDRESS_KEY, hotspot_to_json(address))

    def _save_hotspot(self) -> None:
        """Add the current address to the saved places."""
        if self._current_address is None:
            return
        self._set_hotspots(add_hotspot(self._hotspots, self._current_address))
        self.panel.set_address_status(f"Saved “{self._current_address.name}”.")

    def _remove_hotspot(self, hotspot: Hotspot) -> None:
        """Delete a saved place.

        Args:
            hotspot: The place to delete.
        """
        self._set_hotspots(remove_hotspot(self._hotspots, hotspot))

    def _set_hotspots(self, hotspots: list[Hotspot]) -> None:
        """Replace the saved places, saving them immediately.

        Args:
            hotspots: The new list.
        """
        self._hotspots = hotspots
        self.panel.set_hotspots(hotspots)
        self._write_setting(_HOTSPOTS_KEY, hotspots_to_json(hotspots))

    def _on_geocode_failed(self, error: Exception) -> None:
        """Report a geocoding service/network error."""
        self.panel.set_address_status(f"Search failed: {error}", error=True)

    def _on_feature_clicked(self, layer_name: str, idx: int, lon: float, lat: float) -> None:
        """Open the popup for a clicked marker or curb strip.

        Args:
            layer_name: The clicked layer.
            idx: Row of the feature in that layer's frame.
            lon: Where to anchor the popup (the marker, or the click on a strip).
            lat: Anchor latitude.
        """
        data_layer = self._layers_by_name.get(layer_name)
        if data_layer is None or self._applied is None:
            return
        row = data_layer.frame.row(idx, named=True)
        match data_layer.spec.kind:
            case "sign":
                html = sign_popup_html(cast(SignRow, row))
            case "spot":
                html = spot_popup_html(cast(SpotRow, row), window_is_complete(self._applied))
            case "strip":
                html = strip_popup_html(cast(StripRow, row))
        self.map.show_popup(html, lon, lat)

    def _on_hover_changed(self, layer_name: str, idx: int) -> None:
        """Highlight the sign poles (and the strip) behind a hovered curb strip.

        Args:
            layer_name: Hovered layer, or ``""`` when nothing is hovered.
            idx: Row of the feature in that layer's frame.
        """
        data_layer = self._layers_by_name.get(layer_name)
        if data_layer is None or data_layer.spec.kind != "strip":
            self.map.clear_highlight()
            return
        row = cast(StripRow, data_layer.frame.row(idx, named=True))
        self.map.set_highlight(
            points=list(zip(row["pole_longitudes"], row["pole_latitudes"], strict=True)),
            line=list(zip(row["longitudes"], row["latitudes"], strict=True)),
        )

    # ------------------------------------------------------------- persistence

    def _map_config(self) -> MapConfig:
        """Map settings, starting where the user left off last time."""
        lon, lat = settings.DEFAULT_CENTER
        return MapConfig(
            center=(
                float(cast(float, self._settings.value("map/lon", lon, type=float))),
                float(cast(float, self._settings.value("map/lat", lat, type=float))),
            ),
            zoom=int(cast(int, self._settings.value("map/zoom", settings.DEFAULT_ZOOM, type=int))),
            min_zoom=settings.MIN_ZOOM,
            max_zoom=settings.MAX_ZOOM,
            bounds=settings.MTL_BOUNDS,
            attribution=settings.TILE_ATTRIBUTION,
            bearing=float(cast(float, self._settings.value("map/bearing", 0.0, type=float))),
        )

    def _setting_text(self, key: str) -> str:
        """A string setting ("" when missing).

        Args:
            key: Settings key.

        Returns:
            The stored text.
        """
        return str(cast(str, self._settings.value(key, "", type=str)))

    def _write_setting(self, key: str, value: object) -> None:
        """Store and flush a setting at once, so it survives a crash.

        Args:
            key: Settings key.
            value: Value to store.
        """
        self._settings.setValue(key, value)
        self._settings.sync()

    def _restore_session(self) -> None:
        """Bring back the saved non-time filters, hotspots and the last pinned address."""
        try:
            saved = json.loads(self._setting_text(_FILTERS_KEY) or "{}")
        except json.JSONDecodeError:
            saved = {}
        if isinstance(saved, dict):
            self.panel.set_state(restore_options(self.panel.state(), saved))
        self.panel.set_hotspots(self._hotspots)
        address = hotspot_from_json(self._setting_text(_ADDRESS_KEY))
        if address is not None:
            # The map view itself is restored separately: don't recentre.
            self.panel.address_edit.setText(address.name)
            self._set_current_address(address)

    def _restore_window(self) -> None:
        """Restore geometry and dock layout, or use a sensible default size."""
        geometry = self._settings.value("window/geometry")
        if isinstance(geometry, QByteArray) and self.restoreGeometry(geometry):
            state = self._settings.value("window/state")
            if isinstance(state, QByteArray):
                self.restoreState(state)
        else:
            self.resize(*_DEFAULT_SIZE)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Persist window and map state."""
        lon, lat = self.map.center_lonlat()
        self._settings.setValue("map/lon", lon)
        self._settings.setValue("map/lat", lat)
        self._settings.setValue("map/zoom", self.map.view.zoom)
        self._settings.setValue("map/bearing", self.map.view.bearing)
        self._settings.setValue("legend/collapsed", self.legend.collapsed)
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        self._settings.sync()
        super().closeEvent(event)
