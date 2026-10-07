"""A native slippy-map widget: raster tiles + clustered marker layers, no web view.

Rendering is plain QPainter: tiles are drawn 1:1 at integer zoom, then each marker
layer's on-screen clusters, then the search pin. All geometry lives in the immutable
:class:`~mtl_park_map.slippy.viewport.Viewport`; this class only maps Qt input events
onto viewport transitions and paints the result.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mtl_park_map.slippy.layers import Hit, MarkerLayer, cluster_radius
from mtl_park_map.slippy.popup import MapPopup
from mtl_park_map.slippy.projection import TILE_SIZE, lonlat_to_world, world_to_lonlat
from mtl_park_map.slippy.tiles import TileLoader
from mtl_park_map.slippy.viewport import TileKey, Viewport, WorldRect

_BACKGROUND = QColor("#e5e3df")  # OSM land colour, shown while tiles load
PIN_COLOR = QColor("#dc2626")
_WHEEL_STEP = 120  # angleDelta units per mouse-wheel notch
_KEY_PAN_PX = 80
_CLUSTER_CLICK_ZOOM_STEPS = 2
_OVERLAY_MARGIN = 10
_POPUP_GAP = 12  # pixels between the popup and its anchor point


@dataclass(frozen=True, slots=True)
class MapConfig:
    """Static map settings.

    Attributes:
        center: Initial ``(lon, lat)``.
        zoom: Initial zoom.
        min_zoom: Lowest zoom the user can reach.
        max_zoom: Highest zoom the user can reach (and the tile source serves).
        bounds: ``(min_lon, min_lat, max_lon, max_lat)`` the view is kept inside.
        attribution: Rich-text tile attribution shown bottom-right (required by
            most tile providers' terms).
    """

    center: tuple[float, float]
    zoom: int
    min_zoom: int
    max_zoom: int
    bounds: tuple[float, float, float, float]
    attribution: str


def paint_pin(painter: QPainter, x: float, y: float, scale: float = 1.0) -> None:
    """Draw the red teardrop "searched address" pin with its tip at ``(x, y)``.

    Args:
        painter: Active painter.
        x: Tip x.
        y: Tip y.
        scale: Size factor (1.0 = 32 px tall); the legend draws a small one.
    """
    radius, head_y = 10.0 * scale, y - 22.0 * scale
    path = QPainterPath(QPointF(x, y))
    path.cubicTo(x - 3 * scale, y - 8 * scale, x - radius, head_y + 7 * scale, x - radius, head_y)
    # Over the top of the head, from its west point (180°) clockwise to east (0°).
    path.arcTo(QRectF(x - radius, head_y - radius, 2 * radius, 2 * radius), 180, -180)
    path.cubicTo(x + radius, head_y + 7 * scale, x + 3 * scale, y - 8 * scale, x, y)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#7f1d1d"), 1))
    painter.setBrush(PIN_COLOR)
    painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("white"))
    painter.drawEllipse(QPointF(x, head_y), 3.5 * scale, 3.5 * scale)
    painter.restore()


def _format_count(count: int) -> str:
    """Compact cluster label, e.g. ``"842"``, ``"1.2k"``, ``"14k"``.

    Args:
        count: Cluster member count.

    Returns:
        The label text.
    """
    if count < 1000:
        return str(count)
    if count < 10_000:
        return f"{count / 1000:.1f}k"
    return f"{count // 1000}k"


class MapWidget(QWidget):
    """Interactive map: drag to pan, wheel/double-click/keys/buttons to zoom.

    Args:
        tiles: Tile source (shared so its caches outlive the widget if needed).
        config: Initial view and limits.
        parent: Qt parent.
    """

    viewport_changed = Signal(object)  # Viewport
    marker_clicked = Signal(str, int)  # layer name, row index in the layer's frame

    def __init__(self, tiles: TileLoader, config: MapConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self._tiles = tiles
        self._config = config
        min_lon, min_lat, max_lon, max_lat = config.bounds
        # World y grows southwards: the north edge (max_lat) has the smaller y.
        x0, y0 = lonlat_to_world(min_lon, max_lat)
        x1, y1 = lonlat_to_world(max_lon, min_lat)
        self._bounds: WorldRect = (x0, y0, x1, y1)
        self._view = Viewport(lonlat_to_world(*config.center), config.zoom, 0, 0)

        self._layers: list[MarkerLayer] = []
        self._pin: tuple[float, float] | None = None  # world coords
        self._popup_anchor: tuple[float, float] | None = None  # world coords
        self._press_pos: QPointF | None = None
        self._last_drag_pos = QPointF()
        self._dragging = False
        self._wheel_accum = 0
        self._overlays: dict[Qt.Corner, QWidget] = {}

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumSize(200, 150)

        self._popup = MapPopup(self)
        self.add_overlay(self._make_zoom_controls(), Qt.Corner.TopRightCorner)
        self.add_overlay(self._make_attribution(config.attribution), Qt.Corner.BottomRightCorner)
        tiles.tile_loaded.connect(self._on_tile_loaded)

    # ------------------------------------------------------------------ public API

    @property
    def view(self) -> Viewport:
        """The current viewport."""
        return self._view

    @property
    def popup(self) -> MapPopup:
        """The info popup (exposed for inspection)."""
        return self._popup

    @property
    def layers(self) -> list[MarkerLayer]:
        """Marker layers, bottom to top."""
        return list(self._layers)

    def set_layers(self, layers: Sequence[MarkerLayer]) -> None:
        """Replace all marker layers (drawn in order, last on top).

        Closes the popup, since it described a marker of the old layers.

        Args:
            layers: The new layers.
        """
        self._layers = list(layers)
        self.hide_popup()
        self.update()

    def set_pin(self, lonlat: tuple[float, float] | None) -> None:
        """Show (or clear) the search-result pin.

        Args:
            lonlat: Pin position, or ``None`` to remove it.
        """
        self._pin = None if lonlat is None else lonlat_to_world(*lonlat)
        self.update()

    def center_on(self, lon: float, lat: float, zoom: int | None = None) -> None:
        """Move the view.

        Args:
            lon: Longitude of the new centre.
            lat: Latitude of the new centre.
            zoom: New zoom, or ``None`` to keep the current one.
        """
        self._set_view(self._view.centered_on(*lonlat_to_world(lon, lat), zoom))

    def center_lonlat(self) -> tuple[float, float]:
        """The current centre as ``(lon, lat)``."""
        return world_to_lonlat(*self._view.center)

    def zoom_in(self) -> None:
        """Zoom in one level around the centre."""
        self._zoom_at(QPointF(self.width() / 2, self.height() / 2), self._view.zoom + 1)

    def zoom_out(self) -> None:
        """Zoom out one level around the centre."""
        self._zoom_at(QPointF(self.width() / 2, self.height() / 2), self._view.zoom - 1)

    def show_popup(self, html: str, lon: float, lat: float) -> None:
        """Open the popup above a map point; it then follows the map.

        Args:
            html: Rich-text content (escape untrusted text first).
            lon: Anchor longitude.
            lat: Anchor latitude.
        """
        self._popup.set_html(html)
        self._popup_anchor = lonlat_to_world(lon, lat)
        self._layout_popup()

    def hide_popup(self) -> None:
        """Close the popup."""
        self._popup_anchor = None
        self._popup.hide()

    def add_overlay(self, widget: QWidget, corner: Qt.Corner) -> None:
        """Pin a child widget (legend, controls…) to a corner of the map.

        Args:
            widget: The overlay; it is reparented to the map.
            corner: Where to keep it; one overlay per corner.

        Raises:
            ValueError: If the corner is already taken.
        """
        if corner in self._overlays:
            raise ValueError(f"corner {corner} already has an overlay")
        widget.setParent(self)
        widget.adjustSize()
        widget.show()
        self._overlays[corner] = widget
        self._layout_overlays()

    # ------------------------------------------------------------- Qt event hooks

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Track the widget size in the viewport and re-anchor overlays."""
        self._set_view(self._view.with_size(self.width(), self.height()))
        self._layout_overlays()
        super().resizeEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw tiles, then marker layers bottom-up, then the pin."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), _BACKGROUND)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._paint_tiles(painter)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for layer in self._layers:
            self._paint_layer(painter, layer)
        if self._pin is not None:
            paint_pin(painter, *self._view.world_to_screen(*self._pin))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start a potential drag or click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position()
            self._last_drag_pos = event.position()
            self._dragging = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Pan while dragging; otherwise update the hover cursor."""
        pos = event.position()
        if self._press_pos is None:
            hovering = self._hit_test(pos) is not None
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if hovering else Qt.CursorShape.OpenHandCursor
            )
            return
        # Small jitters during a click must not pan, or clicks would be swallowed.
        if not self._dragging:
            moved = (pos - self._press_pos).manhattanLength()
            if moved < QApplication.startDragDistance():
                return
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        delta = pos - self._last_drag_pos
        self._last_drag_pos = pos
        self._set_view(self._view.panned(delta.x(), delta.y()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a drag, or treat a press/release without drag as a click."""
        if event.button() != Qt.MouseButton.LeftButton or self._press_pos is None:
            super().mouseReleaseEvent(event)
            return
        was_drag = self._dragging
        self._press_pos = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if not was_drag:
            self._click(event.position())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Zoom in one level around the cursor."""
        if event.button() == Qt.MouseButton.LeftButton:
            # The double-click replaces the second press; there is no drag to track.
            self._press_pos = None
            self._zoom_at(event.position(), self._view.zoom + 1)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom around the cursor, one level per wheel notch.

        Trackpads deliver many small deltas; they are accumulated so a full notch's
        worth of scrolling zooms exactly one level.
        """
        self._wheel_accum += event.angleDelta().y()
        steps = int(self._wheel_accum / _WHEEL_STEP)  # truncates towards zero
        if steps:
            self._wheel_accum -= steps * _WHEEL_STEP
            self._zoom_at(event.position(), self._view.zoom + steps)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """``+``/``-`` zoom, arrows pan, Escape closes the popup."""
        key = event.key()
        pans = {
            Qt.Key.Key_Left: (_KEY_PAN_PX, 0),
            Qt.Key.Key_Right: (-_KEY_PAN_PX, 0),
            Qt.Key.Key_Up: (0, _KEY_PAN_PX),
            Qt.Key.Key_Down: (0, -_KEY_PAN_PX),
        }
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.zoom_out()
        elif key in pans:
            self._set_view(self._view.panned(*pans[Qt.Key(key)]))
        elif key == Qt.Key.Key_Escape:
            self.hide_popup()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------- internals

    def _set_view(self, view: Viewport) -> None:
        """Apply a (clamped) viewport and refresh everything that depends on it.

        Args:
            view: The desired viewport.
        """
        view = view.clamped(self._bounds, self._config.min_zoom, self._config.max_zoom)
        if view == self._view:
            return
        self._view = view
        self._sync_tiles()
        self._layout_popup()
        self.update()
        self.viewport_changed.emit(view)

    def _zoom_at(self, pos: QPointF, zoom: int) -> None:
        """Zoom keeping the point under ``pos`` fixed, if ``zoom`` is reachable.

        Args:
            pos: Anchor in widget coordinates.
            zoom: Target zoom (clamped to the configured limits).
        """
        zoom = max(self._config.min_zoom, min(self._config.max_zoom, zoom))
        if zoom != self._view.zoom:
            self._set_view(self._view.zoomed_at(pos.x(), pos.y(), zoom))

    def _sync_tiles(self) -> None:
        """Request missing visible tiles and abort requests for hidden ones."""
        visible = self._view.visible_tiles()
        for key in visible:
            if self._tiles.tile(key) is None:
                self._tiles.request(key)
        self._tiles.prune(set(visible))

    def _on_tile_loaded(self, key: TileKey) -> None:
        """Repaint when a tile of the current zoom arrives.

        Args:
            key: The loaded tile.
        """
        if key.z == self._view.zoom:
            self.update()

    def _hit_test(self, pos: QPointF) -> Hit | None:
        """The topmost marker or cluster under ``pos``.

        Args:
            pos: Widget coordinates.

        Returns:
            The hit, or ``None``.
        """
        for layer in reversed(self._layers):
            hit = layer.hit_test(self._view, pos.x(), pos.y())
            if hit is not None:
                return hit
        return None

    def _click(self, pos: QPointF) -> None:
        """Open a marker, expand a cluster, or dismiss the popup.

        Args:
            pos: Click position in widget coordinates.
        """
        hit = self._hit_test(pos)
        if hit is None:
            self.hide_popup()
        elif hit.count > 1:
            zoom = min(self._config.max_zoom, self._view.zoom + _CLUSTER_CLICK_ZOOM_STEPS)
            self._set_view(self._view.centered_on(hit.x, hit.y, zoom))
        else:
            self.marker_clicked.emit(hit.layer, hit.idx)

    def _layout_popup(self) -> None:
        """Keep the popup above its anchor (hidden while the anchor is off-screen)."""
        if self._popup_anchor is None:
            return
        sx, sy = self._view.world_to_screen(*self._popup_anchor)
        if not self.rect().contains(round(sx), round(sy)):
            self._popup.hide()
            return
        width, height = self._popup.width(), self._popup.height()
        x = round(sx - width / 2)
        y = round(sy - height - _POPUP_GAP)
        if y < 0:  # no room above: flip below the anchor
            y = round(sy + _POPUP_GAP)
        self._popup.move(x, y)
        self._popup.show()
        self._popup.raise_()

    def _layout_overlays(self) -> None:
        """Re-anchor corner overlays after a resize."""
        for corner, widget in self._overlays.items():
            # The attribution hugs its corner, like on most web maps.
            margin = 0 if corner == Qt.Corner.BottomRightCorner else _OVERLAY_MARGIN
            size = widget.sizeHint().expandedTo(widget.minimumSizeHint())
            widget.resize(size)
            right = corner in (Qt.Corner.TopRightCorner, Qt.Corner.BottomRightCorner)
            bottom = corner in (Qt.Corner.BottomLeftCorner, Qt.Corner.BottomRightCorner)
            x = self.width() - size.width() - margin if right else margin
            y = self.height() - size.height() - margin if bottom else margin
            widget.move(x, y)

    def _make_zoom_controls(self) -> QWidget:
        """Build the ``+`` / ``−`` button pair.

        Returns:
            The control frame.
        """
        frame = QFrame()
        frame.setObjectName("ZoomControls")
        frame.setStyleSheet(
            "#ZoomControls { background: white; border: 1px solid #d1d5db; border-radius: 6px; }"
            "#ZoomControls QToolButton { border: none; font-size: 16px; color: #374151;"
            " min-width: 30px; min-height: 30px; }"
            "#ZoomControls QToolButton:hover { background: #f3f4f6; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        for text, tip, slot in (("+", "Zoom in", self.zoom_in), ("−", "Zoom out", self.zoom_out)):
            button = QToolButton(frame)
            button.setText(text)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.ArrowCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(slot)
            layout.addWidget(button)
        return frame

    def _make_attribution(self, html: str) -> QLabel:
        """Build the tile attribution label.

        Args:
            html: Rich-text attribution.

        Returns:
            The label.
        """
        label = QLabel(html)
        label.setObjectName("Attribution")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(True)
        label.setCursor(Qt.CursorShape.ArrowCursor)
        label.setStyleSheet(
            "#Attribution { background: rgba(255, 255, 255, 200); color: #374151;"
            " padding: 1px 5px; font-size: 11px; }"
        )
        return label

    def _paint_tiles(self, painter: QPainter) -> None:
        """Draw visible tiles, using a scaled ancestor while a tile is loading.

        Args:
            painter: Active painter on this widget.
        """
        n = 2**self._view.zoom
        for key in self._view.visible_tiles():
            sx, sy = self._view.world_to_screen(key.x / n, key.y / n)
            # All tiles share the same fractional offset, so rounding each origin
            # keeps them exactly TILE_SIZE apart: no hairline seams.
            target = QRectF(round(sx), round(sy), TILE_SIZE, TILE_SIZE)
            pixmap = self._tiles.tile(key)
            if pixmap is not None:
                painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
                continue
            fallback = self._tiles.fallback(key)
            if fallback is not None:
                painter.drawPixmap(target, *fallback)

    def _paint_layer(self, painter: QPainter, layer: MarkerLayer) -> None:
        """Draw one layer's on-screen markers and clusters.

        Args:
            painter: Active painter on this widget.
            layer: The layer to draw.
        """
        clusters = layer.screen_clusters(self._view)
        if clusters.is_empty():
            return
        color = QColor(layer.style.color)
        halo = QColor(color)
        halo.setAlpha(90)
        white_pen = QPen(QColor("white"), 1.5)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(11)
        painter.setFont(font)

        for sx, sy, count in zip(
            clusters["sx"].to_list(), clusters["sy"].to_list(), clusters["count"].to_list(), strict=True
        ):
            center = QPointF(sx, sy)
            radius = cluster_radius(count, layer.style.radius)
            if count == 1:
                painter.setPen(white_pen)
                painter.setBrush(color)
                painter.drawEllipse(center, radius, radius)
                continue
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(center, radius, radius)
            painter.setPen(white_pen)
            painter.setBrush(color)
            painter.drawEllipse(center, radius - 4, radius - 4)
            painter.drawText(
                QRectF(sx - radius, sy - radius, 2 * radius, 2 * radius),
                Qt.AlignmentFlag.AlignCenter,
                _format_count(count),
            )
