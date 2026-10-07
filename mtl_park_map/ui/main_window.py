"""Main window: native map in the centre, filter panel docked on the right."""

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
    window_is_complete,
)
from mtl_park_map.ui.legend import Legend
from mtl_park_map.ui.palette import DataLayer, build_layers
from mtl_park_map.ui.popups import SignRow, SpotRow, sign_popup_html, spot_popup_html
from mtl_park_map.ui.tasks import BackgroundRunner

type Geocoder = Callable[[str], tuple[float, float] | None]

_QUERY_CHANNEL = "query"
_GEOCODE_CHANNEL = "geocode"
_DEFAULT_SIZE = (1280, 820)
_PANEL_MIN_WIDTH = 290


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Everything a finished query hands to the GUI thread.

    Attributes:
        state: The filters the query ran with.
        layers: Marker layers, bottom to top.
        sign_count: Signs found, or ``None`` if signs were hidden.
        spot_count: Paid spots found, or ``None`` if spots were hidden.
        free_spot_count: Spots free in the window, or ``None`` if spots were hidden.
    """

    state: FilterState
    layers: list[DataLayer]
    sign_count: int | None
    spot_count: int | None
    free_spot_count: int | None

    def summary(self) -> str:
        """Human-readable result counts for the status bar."""
        parts: list[str] = []
        if self.sign_count is not None:
            parts.append(f"{self.sign_count:,} signs")
        if self.spot_count is not None:
            text = f"{self.spot_count:,} paid spots"
            if window_is_complete(self.state):
                text += f" ({self.free_spot_count:,} free)"
            parts.append(text)
        return " · ".join(parts) if parts else "Nothing selected"


def run_query(store: Store, state: FilterState, zoom: int) -> QueryResult:
    """Query the store and prepare marker layers. Runs on a worker thread.

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
    layers = build_layers(signs, spots)
    for data_layer in layers:
        data_layer.marker_layer.clusters(zoom)
    return QueryResult(
        state=state,
        layers=layers,
        sign_count=None if signs is None else signs.height,
        spot_count=None if spots is None else spots.height,
        free_spot_count=None if spots is None else int(spots["is_free"].sum()),
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

        self.setWindowTitle(settings.APP_NAME)
        self.map = MapWidget(tiles, self._map_config())
        self.map.add_overlay(Legend(), Qt.Corner.BottomLeftCorner)
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
        self.map.marker_clicked.connect(self._on_marker_clicked)

        self._restore_window()
        self.apply_filters(self.panel.state())

    # ------------------------------------------------------------------ actions

    def apply_filters(self, state: FilterState) -> None:
        """Query in the background and redraw the map with the results.

        Args:
            state: The filters to apply.
        """
        self.panel.mark_applied(state)
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
            self._on_geocoded,
            self._on_geocode_failed,
        )

    # ---------------------------------------------------------------- callbacks

    def _on_query_done(self, result: QueryResult) -> None:
        """Show a finished query on the map."""
        self._applied = result.state
        self._layers_by_name = {dl.spec.name: dl for dl in result.layers}
        self.map.set_layers([dl.marker_layer for dl in result.layers])
        self.status_label.setText(result.summary())

    def _on_query_failed(self, error: Exception) -> None:
        """Report an unexpected query error."""
        self.status_label.setText(f"Query failed: {error}")

    def _on_geocoded(self, lonlat: tuple[float, float] | None) -> None:
        """Pin and zoom to a found address."""
        if lonlat is None:
            self.panel.set_address_status("Address not found.", error=True)
            return
        self.panel.set_address_status(None)
        self.map.set_pin(lonlat)
        self.map.center_on(*lonlat, zoom=settings.ADDRESS_ZOOM)

    def _on_geocode_failed(self, error: Exception) -> None:
        """Report a geocoding service/network error."""
        self.panel.set_address_status(f"Search failed: {error}", error=True)

    def _on_marker_clicked(self, layer_name: str, idx: int) -> None:
        """Open the popup for a clicked marker.

        Args:
            layer_name: The clicked layer.
            idx: Row of the marker in that layer's frame.
        """
        data_layer = self._layers_by_name.get(layer_name)
        if data_layer is None or self._applied is None:
            return
        row = data_layer.frame.row(idx, named=True)
        if data_layer.spec.kind == "sign":
            html = sign_popup_html(cast(SignRow, row))
        else:
            html = spot_popup_html(cast(SpotRow, row), window_is_complete(self._applied))
        self.map.show_popup(html, row["longitude"], row["latitude"])

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
        )

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
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        self._settings.sync()
        super().closeEvent(event)
