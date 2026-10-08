"""A native slippy-map widget: raster tiles + clustered marker layers, no web view.

Rendering is plain QPainter: tiles are drawn 1:1 at integer zoom, then each layer's
on-screen markers / lines, then the search pin. All geometry lives in the immutable
:class:`~mtl_park_map.slippy.viewport.Viewport`; this class only maps Qt input events
onto viewport transitions and paints the result.

The map can be rotated (right-drag, Ctrl+drag, Shift+←/→, trackpad twist; the compass
resets north). Tiles then rotate with it, labels included (they are raster images),
while markers, cluster counts, the pin and the popup stay upright at their rotated
positions.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QNativeGestureEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
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
from mtl_park_map.slippy.lines import LineLayer
from mtl_park_map.slippy.popup import MapPopup
from mtl_park_map.slippy.projection import TILE_SIZE, lonlat_to_world, world_to_lonlat
from mtl_park_map.slippy.tiles import TileLoader
from mtl_park_map.slippy.viewport import TileKey, Viewport, WorldRect, normalize_bearing

_BACKGROUND = QColor("#e5e3df")  # OSM land colour, shown while tiles load
PIN_COLOR = QColor("#dc2626")
_WHEEL_STEP = 120  # angleDelta units per mouse-wheel notch
_KEY_PAN_PX = 80
_CLUSTER_CLICK_ZOOM_STEPS = 2
_OVERLAY_MARGIN = 10
_POPUP_GAP = 12  # pixels between the popup and its anchor point
_LINE_CASING_PX = 2.0  # white outline around lines, for contrast on the basemap
_KEY_ROTATE_DEG = 15.0
# Highlight: amber glow under a line, amber rings (dark-outlined) over points.
_HIGHLIGHT = QColor("#facc15")
_HIGHLIGHT_DARK = QColor("#78350f")
_HIGHLIGHT_GLOW_ALPHA = 170
_HIGHLIGHT_GLOW_PX = 17.0  # wider than a strip + its casing (9 px), so it shows
_HIGHLIGHT_RING_RADIUS = 9.0
_DASH_PATTERN = [2.5, 2.0]  # dash, gap, in stroke widths

# Anything the map can draw and hit-test.
type MapLayer = MarkerLayer | LineLayer


@dataclass(frozen=True, slots=True)
class MapConfig:
    """Static map settings.

    Attributes:
        center: Initial ``(lon, lat)``.
        zoom: Initial zoom.
        min_zoom: Lowest zoom the user can reach.
        max_zoom: Highest zoom the user can reach (and the tile source serves).
        bounds: ``(min_lon, min_lat, max_lon, max_lat)`` the view centre is kept
            inside, so the map can be dragged up to half a screen past them.
        attribution: Rich-text tile attribution shown bottom-right (required by
            most tile providers' terms).
        bearing: Initial rotation, degrees clockwise from north at the top.
    """

    center: tuple[float, float]
    zoom: int
    min_zoom: int
    max_zoom: int
    bounds: tuple[float, float, float, float]
    attribution: str
    bearing: float = 0.0


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


class _CompassButton(QToolButton):
    """Shows where north is; clicking it resets the map to north-up.

    The current bearing is also exposed as the ``bearing`` Qt property.

    Args:
        parent: The controls frame.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Compass")
        self.setToolTip("Reset to north (rotate: right-drag, Ctrl+drag or Shift+←/→)")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setProperty("bearing", 0.0)

    def set_bearing(self, bearing: float) -> None:
        """Point the needle for a new map bearing.

        Args:
            bearing: Map bearing in degrees.
        """
        self.setProperty("bearing", bearing)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the button, then a needle whose red half points to north."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        # North on screen is "up" rotated counter-clockwise by the bearing.
        painter.rotate(-float(self.property("bearing")))
        half_w, half_h = 4.0, 10.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#dc2626"))
        painter.drawPolygon(QPolygonF([QPointF(0, -half_h), QPointF(half_w, 0), QPointF(-half_w, 0)]))
        painter.setBrush(QColor("#9ca3af"))
        painter.drawPolygon(QPolygonF([QPointF(0, half_h), QPointF(half_w, 0), QPointF(-half_w, 0)]))
        painter.end()


class _VisibilityButton(QToolButton):
    """Checkable eye: checked hides every data layer (the address pin stays).

    Args:
        parent: The controls frame.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("HideLayers")
        self.setCheckable(True)
        self.setToolTip("Hide markers and strips, keep the address pin (H)")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw an eye, struck through while layers are hidden."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        color = QColor("#dc2626") if self.isChecked() else QColor("#374151")
        painter.setPen(QPen(color, 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        eye = QPainterPath(QPointF(-9, 0))
        eye.quadTo(0, -9, 9, 0)
        eye.quadTo(0, 9, -9, 0)
        painter.drawPath(eye)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(0, 0), 2.6, 2.6)
        if self.isChecked():
            painter.drawLine(QPointF(-8, 8), QPointF(8, -8))
        painter.end()


@dataclass(frozen=True, slots=True)
class Highlight:
    """Map features to emphasise, e.g. what a hovered feature relates to.

    Attributes:
        points: ``(lon, lat)`` positions to ring.
        line: ``(lon, lat)`` vertices of a polyline to glow.
    """

    points: tuple[tuple[float, float], ...] = ()
    line: tuple[tuple[float, float], ...] = ()


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
    # A single marker or a line was clicked: layer name, row index in its frame, and
    # the (lon, lat) to anchor a popup at (the marker itself, or the click on a line).
    feature_clicked = Signal(str, int, float, float)
    # Data layers were shown (True) or hidden (False); the address pin always shows.
    layers_visibility_changed = Signal(bool)
    # The single feature under the cursor changed: layer name and row index, or
    # ("", -1) when there is none (clusters don't count).
    hover_changed = Signal(str, int)

    def __init__(self, tiles: TileLoader, config: MapConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self._tiles = tiles
        self._config = config
        min_lon, min_lat, max_lon, max_lat = config.bounds
        # World y grows southwards: the north edge (max_lat) has the smaller y.
        x0, y0 = lonlat_to_world(min_lon, max_lat)
        x1, y1 = lonlat_to_world(max_lon, min_lat)
        self._bounds: WorldRect = (x0, y0, x1, y1)
        self._view = Viewport(
            lonlat_to_world(*config.center), config.zoom, 0, 0, normalize_bearing(config.bearing)
        )

        self._layers: list[MapLayer] = []
        self._layers_visible = True
        self._hovered: tuple[str, int] | None = None
        self._highlight = Highlight()
        self._pin: tuple[float, float] | None = None  # world coords
        self._pin_lonlat: tuple[float, float] | None = None
        self._popup_anchor: tuple[float, float] | None = None  # world coords
        self._press_pos: QPointF | None = None
        self._last_drag_pos = QPointF()
        self._dragging = False
        self._rotating = False
        self._rotate_last_angle = 0.0  # degrees, cursor angle around the centre
        self._wheel_accum = 0
        self._overlays: dict[Qt.Corner, QWidget] = {}

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumSize(200, 150)

        self._popup = MapPopup(self)
        self._compass = _CompassButton(self)
        self._visibility = _VisibilityButton(self)
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
    def layers(self) -> list[MapLayer]:
        """Marker and line layers, bottom to top."""
        return list(self._layers)

    def set_layers(self, layers: Sequence[MapLayer]) -> None:
        """Replace all layers (drawn in order, last on top).

        Closes the popup, since it described a feature of the old layers.

        Args:
            layers: The new layers.
        """
        self._layers = list(layers)
        self.hide_popup()
        # Row indices of the old layers mean nothing in the new ones.
        self._set_hovered(None)
        self.clear_highlight()
        self.update()

    @property
    def layers_visible(self) -> bool:
        """Whether data layers are drawn (the address pin always is)."""
        return self._layers_visible

    def set_layers_visible(self, visible: bool) -> None:
        """Show or hide every data layer, keeping only the address pin.

        Hidden layers are neither drawn nor clickable; layers set while hidden stay
        hidden until shown again. Hiding closes the popup, which described a feature.

        Args:
            visible: ``False`` to hide markers and lines.
        """
        if visible == self._layers_visible:
            return
        self._layers_visible = visible
        if self._visibility.isChecked() == visible:
            self._visibility.setChecked(not visible)
        if not visible:
            self.hide_popup()
            self._set_hovered(None)
            self.clear_highlight()
        self.update()
        self.layers_visibility_changed.emit(visible)

    @property
    def highlight(self) -> Highlight:
        """What is currently highlighted."""
        return self._highlight

    def set_highlight(
        self,
        points: Sequence[tuple[float, float]] = (),
        line: Sequence[tuple[float, float]] = (),
    ) -> None:
        """Emphasise points (rings, drawn over everything) and a line (a glow under
        the layers).

        Args:
            points: ``(lon, lat)`` positions to ring.
            line: ``(lon, lat)`` vertices of a polyline to glow.
        """
        self._highlight = Highlight(tuple(points), tuple(line))
        self.update()

    def clear_highlight(self) -> None:
        """Remove any highlight."""
        if self._highlight != Highlight():
            self._highlight = Highlight()
            self.update()

    @property
    def pin(self) -> tuple[float, float] | None:
        """The search-result pin as ``(lon, lat)``, if shown."""
        return self._pin_lonlat

    def set_pin(self, lonlat: tuple[float, float] | None) -> None:
        """Show (or clear) the search-result pin.

        Args:
            lonlat: Pin position, or ``None`` to remove it.
        """
        self._pin_lonlat = lonlat
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

    def set_bearing(self, bearing: float) -> None:
        """Rotate the map about the screen centre.

        Args:
            bearing: Degrees clockwise from north to show at the top of the screen.
        """
        self._set_view(self._view.with_bearing(bearing))

    def rotate_by(self, degrees: float) -> None:
        """Change the bearing by ``degrees`` (positive turns the view clockwise).

        Args:
            degrees: Bearing change.
        """
        self.set_bearing(self._view.bearing + degrees)

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
        self._paint_highlight_line(painter)
        if self._layers_visible:
            for layer in self._layers:
                self._paint_layer(painter, layer)
        self._paint_highlight_points(painter)
        if self._pin is not None:
            paint_pin(painter, *self._view.world_to_screen(*self._pin))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start a rotation (right / Ctrl+left button), or a potential drag or click."""
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if event.button() == Qt.MouseButton.RightButton or (
            event.button() == Qt.MouseButton.LeftButton and ctrl
        ):
            self._rotating = True
            self._rotate_last_angle = self._angle_around_centre(event.position())
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position()
            self._last_drag_pos = event.position()
            self._dragging = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Rotate or pan while dragging; otherwise update the hover cursor."""
        pos = event.position()
        if self._rotating:
            angle = self._angle_around_centre(pos)
            # Shortest signed turn, so crossing ±180° doesn't spin the map around.
            turn = (angle - self._rotate_last_angle + 180.0) % 360.0 - 180.0
            self._rotate_last_angle = angle
            # The content follows the cursor: a clockwise drag turns it clockwise,
            # which lowers the bearing.
            self.rotate_by(-turn)
            return
        if self._press_pos is None:
            hit = self._hit_test(pos)
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.OpenHandCursor
            )
            self._set_hovered((hit.layer, hit.idx) if hit and hit.count == 1 else None)
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
        """Finish a rotation or drag, or treat a press/release without drag as a click."""
        if self._rotating and event.button() in (
            Qt.MouseButton.RightButton,
            Qt.MouseButton.LeftButton,
        ):
            self._rotating = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
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
        """``+``/``-`` zoom, arrows pan, Shift+←/→ rotate, ``N`` north-up, ``H``
        hide/show data layers, Escape closes the popup."""
        key = event.key()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
        ):
            self.rotate_by(_KEY_ROTATE_DEG if key == Qt.Key.Key_Right else -_KEY_ROTATE_DEG)
            return
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
        elif key == Qt.Key.Key_N:
            self.set_bearing(0.0)
        elif key == Qt.Key.Key_H:
            self.set_layers_visible(not self._layers_visible)
        elif key == Qt.Key.Key_Escape:
            self.hide_popup()
        else:
            super().keyPressEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """The cursor left the map: nothing is hovered any more."""
        self._set_hovered(None)
        super().leaveEvent(event)

    def event(self, event: QEvent) -> bool:
        """Handle trackpad rotation gestures (macOS; most Windows drivers send none)
        and re-anchor overlays whose size changed.

        Qt reports the twist in degrees, clockwise positive; the content follows the
        fingers, so the bearing changes the other way.
        """
        if (
            isinstance(event, QNativeGestureEvent)
            and event.gestureType() == Qt.NativeGestureType.RotateNativeGesture
        ):
            self.rotate_by(-event.value())
            return True
        if event.type() == QEvent.Type.LayoutRequest:
            # A child's size hint changed (Qt notifies the parent): re-anchor the
            # corner overlays, e.g. when the legend collapses.
            self._layout_overlays()
        return super().event(event)

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
        self._compass.set_bearing(view.bearing)
        self._sync_tiles()
        self._layout_popup()
        self.update()
        self.viewport_changed.emit(view)

    def _set_hovered(self, hovered: tuple[str, int] | None) -> None:
        """Track the hovered feature, announcing changes only.

        Args:
            hovered: ``(layer, idx)`` under the cursor, or ``None``.
        """
        if hovered == self._hovered:
            return
        self._hovered = hovered
        self.hover_changed.emit(*(hovered or ("", -1)))

    def _angle_around_centre(self, pos: QPointF) -> float:
        """Screen angle of ``pos`` around the widget centre.

        Args:
            pos: Widget coordinates.

        Returns:
            Degrees, clockwise positive (screen y points down).
        """
        return math.degrees(math.atan2(pos.y() - self.height() / 2, pos.x() - self.width() / 2))

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
            The hit, or ``None`` (always while layers are hidden).
        """
        if not self._layers_visible:
            return None
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
            self.feature_clicked.emit(hit.layer, hit.idx, *world_to_lonlat(hit.x, hit.y))

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
        self._compass.setParent(frame)
        self._compass.clicked.connect(lambda: self.set_bearing(0.0))
        layout.addWidget(self._compass)
        self._visibility.setParent(frame)
        self._visibility.toggled.connect(lambda hidden: self.set_layers_visible(not hidden))
        layout.addWidget(self._visibility)
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
        """Draw visible tiles, rotated with the map.

        North-up, tiles are drawn straight onto the widget. Rotated, they are first
        drawn north-up onto an offscreen square covering the view at any angle, then
        that one image is drawn rotated: rotating tiles one by one would leave
        anti-aliased hairline seams between them.

        Args:
            painter: Active painter on this widget.
        """
        width, height = self.width(), self.height()
        if self._view.bearing == 0.0:
            self._draw_tiles(painter, QPointF(width / 2, height / 2))
            return
        side = math.ceil(math.hypot(width, height)) + 2
        ratio = self.devicePixelRatioF()
        composite = QPixmap(math.ceil(side * ratio), math.ceil(side * ratio))
        composite.setDevicePixelRatio(ratio)
        composite.fill(_BACKGROUND)
        offscreen = QPainter(composite)
        offscreen.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._draw_tiles(offscreen, QPointF(side / 2, side / 2))
        offscreen.end()
        painter.save()
        painter.translate(width / 2, height / 2)
        # Screen = world rotated counter-clockwise by the bearing (see Viewport).
        painter.rotate(-self._view.bearing)
        painter.drawPixmap(QPointF(-side / 2, -side / 2), composite)
        painter.restore()

    def _draw_tiles(self, painter: QPainter, centre: QPointF) -> None:
        """Draw the visible tiles north-up around ``centre``, using a scaled ancestor
        while a tile is loading.

        Args:
            painter: Painter on the widget or on the rotation composite.
            centre: Where the view centre lands on that paint device.
        """
        n = 2**self._view.zoom
        cx, cy = self._view.center
        scale = self._view.scale
        for key in self._view.visible_tiles():
            sx = centre.x() + (key.x / n - cx) * scale
            sy = centre.y() + (key.y / n - cy) * scale
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

    def _paint_highlight_line(self, painter: QPainter) -> None:
        """Glow under the highlighted line, so its own stroke stays visible on top.

        Args:
            painter: Active painter on this widget.
        """
        if len(self._highlight.line) < 2:
            return
        glow = QColor(_HIGHLIGHT)
        glow.setAlpha(_HIGHLIGHT_GLOW_ALPHA)
        pen = QPen(glow, _HIGHLIGHT_GLOW_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        points = [
            QPointF(*self._view.world_to_screen(*lonlat_to_world(lon, lat)))
            for lon, lat in self._highlight.line
        ]
        painter.drawPolyline(QPolygonF(points))

    def _paint_highlight_points(self, painter: QPainter) -> None:
        """Ring each highlighted point (drawn even when data layers are hidden).

        Args:
            painter: Active painter on this widget.
        """
        if not self._highlight.points:
            return
        outline = QPen(_HIGHLIGHT_DARK, 5.0)
        ring = QPen(_HIGHLIGHT, 2.5)
        for lon, lat in self._highlight.points:
            centre = QPointF(*self._view.world_to_screen(*lonlat_to_world(lon, lat)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for pen in (outline, ring):
                painter.setPen(pen)
                painter.drawEllipse(centre, _HIGHLIGHT_RING_RADIUS, _HIGHLIGHT_RING_RADIUS)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_HIGHLIGHT_DARK)
            painter.drawEllipse(centre, 2.5, 2.5)

    def _paint_layer(self, painter: QPainter, layer: MapLayer) -> None:
        """Draw one layer.

        Args:
            painter: Active painter on this widget.
            layer: The layer to draw.
        """
        if isinstance(layer, LineLayer):
            self._paint_lines(painter, layer)
        else:
            self._paint_markers(painter, layer)

    def _paint_lines(self, painter: QPainter, layer: LineLayer) -> None:
        """Draw a line layer's visible polylines, each over a thin white casing.

        Args:
            painter: Active painter on this widget.
            layer: The layer to draw.
        """
        polygons = [
            QPolygonF([QPointF(x, y) for x, y in points])
            for _, points in layer.screen_polylines(self._view)
        ]
        if not polygons:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # All casings first, then all strokes, so neighbouring lines don't cut
        # through each other's colour.
        for color, width, dashed in (
            (QColor("white"), layer.style.width + 2 * _LINE_CASING_PX, False),
            (QColor(layer.style.color), layer.style.width, layer.style.dashed),
        ):
            pen = QPen(color, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            if dashed:
                # Flat caps keep the gaps open (round caps would close them up).
                pen.setDashPattern(_DASH_PATTERN)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            else:
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for polygon in polygons:
                painter.drawPolyline(polygon)

    def _paint_markers(self, painter: QPainter, layer: MarkerLayer) -> None:
        """Draw a marker layer's on-screen markers and clusters.

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
