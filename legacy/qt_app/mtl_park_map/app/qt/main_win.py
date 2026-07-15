import geopandas as gpd
from PySide6.QtCore import QObject, Slot, QSize
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QMessageBox

from mtl_park_map.lib.geolocate import locate_address
from mtl_park_map.lib.mtl_map import mtl_map, add_marker, add_marker_cluster
from mtl_park_map.app.qt.sidebar_control import SideBarView
from mtl_park_map.app.parking_spot_analyzer import PaidParkingAnalyzer, check_paid_periods
from mtl_park_map.lib.parking_sign_query import (
    query_by_rpa_regex,
    RPA_COLUMN,
    query_by_time_range,
    query_by_bounding_box,
)

MARKER_COUNT_LIMIT = 10_000


class Bridge(QObject):
    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._min_lat = 0.0
        self._min_lon = 0.0
        self._max_lat = 0.0
        self._max_lon = 0.0
        self._zoom = 0

    @property
    def zoom(self) -> int:
        return self._zoom

    @property
    def bounding_box(self) -> tuple[float, float, float, float]:
        return self._min_lon, self._max_lon, self._min_lat, self._max_lat

    @Slot(float, float, float, float, int)
    def update_data(self, north, south, east, west, zoom):
        self._max_lon = east
        self._min_lon = west
        self._max_lat = north
        self._min_lat = south
        self._zoom = zoom


class DebugPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, msg, line, sourceID):
        print(f"[JS Console] {msg} (Line {line})")


class MainWindowView(QMainWindow):
    def __init__(
        self,
        parking_sign_gdf: gpd.GeoDataFrame,
        paid_parking_analyzer: PaidParkingAnalyzer,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._gdf = parking_sign_gdf
        self._paid_parking_analyzer = paid_parking_analyzer

        # Ui
        self.setWindowTitle("MTL Parking Map")
        self._central_widget = QWidget()
        self._web_view = QWebEngineView(parent=self._central_widget)
        self._web_view.setPage(DebugPage(self._web_view))
        self._side_bar_view = SideBarView(parent=self._central_widget)

        # Layout
        self.setCentralWidget(self._central_widget)
        self._layout = QHBoxLayout(self._central_widget)
        self._central_widget.setLayout(self._layout)
        self._layout.addWidget(self._web_view, stretch=1)
        self._layout.addWidget(self._side_bar_view, stretch=0)

        # Web channel
        self._channel = QWebChannel()
        self._bridge = Bridge()
        self._channel.registerObject("bridge", self._bridge)
        self._web_view.page().setWebChannel(self._channel)

        # Connect signals
        self._side_bar_view.apply_button.clicked.connect(self._apply_filter)
        self._side_bar_view.clear_button.clicked.connect(self._clear_filter)

        # Size
        self.resize(QSize(1200, 800))

    def _apply_filter(self):
        hour_range = self._side_bar_view.get_hour_range()
        day = self._side_bar_view.get_day()
        month = self._side_bar_view.get_month()

        # Create map object
        min_x, max_x, min_y, max_y = self._bridge.bounding_box
        zoom = self._bridge.zoom
        m = mtl_map(
            min_lon=min_x,
            max_lon=max_x,
            min_lat=min_y,
            max_lat=max_y,
            zoom=zoom,
        )

        # Add free parking
        parking_signs = []
        if self._side_bar_view.include_free_parking:
            expr = r"^\\P"
            if not self._side_bar_view.reserved:
                expr = r"^\\P(?!.*RESERVE).+"
            gdf = query_by_rpa_regex(self._gdf, expr)
            gdf = query_by_bounding_box(
                gdf,
                min_x,
                max_x,
                min_y,
                max_y,
            )
            gdf = query_by_time_range(
                gdf,
                hour_range,
                (day, day),
                (month, month),
                self._side_bar_view.not_in_range,
            )
            parking_signs = [
                (row["Latitude"], row["Longitude"], row[RPA_COLUMN])
                for _, row in gdf.iterrows()
            ]

        # Add free parking
        paid_spots = []
        free_paid_spots = []
        if self._side_bar_view.include_paid_parking:
            spots = self._paid_parking_analyzer.query_spots_by_bounding_box(
                min_lon=min_x,
                max_lon=max_x,
                min_lat=min_y,
                max_lat=max_y,
            )
            for spot in spots:
                if check_paid_periods(spot.paid_periods, hour_range, (day, day)):
                    paid_spots.append(
                        (
                            spot.latitude,
                            spot.longitude,
                            spot.description,
                        )
                    )
                else:
                    free_paid_spots.append(
                        (
                            spot.latitude,
                            spot.longitude,
                            spot.description,
                        )
                    )

        # Add clusters
        total_marker_count = len(parking_signs) + len(paid_spots) + len(free_paid_spots)
        print("Total_marker_count:", total_marker_count)
        if total_marker_count <= MARKER_COUNT_LIMIT:
            add_marker_cluster(m, parking_signs)
            add_marker_cluster(m, paid_spots, "circleMarker", color="orange")
            add_marker_cluster(m, free_paid_spots, "circleMarker", color="green")
        else:
            self._on_marker_count_limit_reached(total_marker_count)
            return

        # Add address marker
        if self._side_bar_view.address:
            if loc := locate_address(self._side_bar_view.address):
                add_marker(m, loc[0], loc[1], self._side_bar_view.address, color="red")

        # Render HTML
        html = m.get_root().render()
        self._web_view.page().setHtml(html)

    def _on_marker_count_limit_reached(self, count: int):
        QMessageBox.information(
            self,
            "Marker count limit reached",
            f"The maximum number of markers that can be drawn is {MARKER_COUNT_LIMIT}, while {count} markers are found. Please narrow your search.",
        )

    def _clear_filter(self):
        min_x, max_x, min_y, max_y = self._bridge.bounding_box
        zoom = self._bridge.zoom
        html = mtl_map(min_x, max_x, min_y, max_y, zoom).get_root().render()
        self._web_view.page().setHtml(html)

    def initialize(self):
        html = mtl_map().get_root().render()
        self._web_view.page().setHtml(html)






