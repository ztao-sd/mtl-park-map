"""Immutable map viewport: what part of the world is shown, at what zoom, how big,
and how it is rotated.

Rotation convention (as in MapLibre / Mapbox): ``bearing`` is the compass direction,
in degrees clockwise from north, that points to the top of the screen. At bearing 90
east is up and north is to the left. With a world-pixel offset ``(dx, dy)`` from the
centre (x east, y south) and ``θ = bearing``, the screen offset is

    sx = dx·cos θ + dy·sin θ
    sy = −dx·sin θ + dy·cos θ

and the inverse rotates back by ``θ``. Every projection in the map goes through
:meth:`Viewport.world_to_screen` / :meth:`Viewport.screen_to_world` or their
vectorized twin :meth:`Viewport.screen_exprs`, so rotation lives here only.
"""

import math
from dataclasses import dataclass, replace

import polars as pl

from mtl_park_map.slippy.projection import world_size, world_to_lonlat

# (min_x, min_y, max_x, max_y) in normalized world coordinates.
type WorldRect = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class TileKey:
    """Address of one slippy-map tile.

    Attributes:
        z: Zoom level.
        x: Column, ``0 … 2**z - 1`` west to east.
        y: Row, ``0 … 2**z - 1`` north to south.
    """

    z: int
    x: int
    y: int

    def parent(self) -> "TileKey":
        """The tile one zoom level up that contains this one.

        Returns:
            The parent tile key.
        """
        return TileKey(self.z - 1, self.x // 2, self.y // 2)


def normalize_bearing(bearing: float) -> float:
    """Wrap a bearing into ``[0, 360)`` degrees.

    Args:
        bearing: Any angle in degrees.

    Returns:
        The equivalent bearing in ``[0, 360)``.
    """
    wrapped = bearing % 360.0
    return 0.0 if math.isclose(wrapped, 360.0) else wrapped


@dataclass(frozen=True, slots=True)
class Viewport:
    """A view of the world.

    Zoom is integral so that 256 px tiles are drawn 1:1 (crisp, seam-free).

    Attributes:
        center: Normalized world coordinate at the centre of the screen.
        zoom: Integer zoom level.
        width: Screen width in logical pixels.
        height: Screen height in logical pixels.
        bearing: Compass direction (degrees clockwise from north) at the top of the
            screen; 0 is north-up.
    """

    center: tuple[float, float]
    zoom: int
    width: int
    height: int
    bearing: float = 0.0

    @property
    def scale(self) -> float:
        """Screen pixels per normalized world unit."""
        return world_size(self.zoom)

    def _cos_sin(self) -> tuple[float, float]:
        """Cosine and sine of the bearing."""
        theta = math.radians(self.bearing)
        return math.cos(theta), math.sin(theta)

    def _offset_to_world(self, ox: float, oy: float, scale: float) -> tuple[float, float]:
        """World offset of a screen offset from the centre (inverse rotation).

        Args:
            ox: Screen offset x in pixels.
            oy: Screen offset y in pixels.
            scale: Pixels per world unit to use.

        Returns:
            ``(dx, dy)`` in normalized world units.
        """
        c, s = self._cos_sin()
        return (ox * c - oy * s) / scale, (ox * s + oy * c) / scale

    def world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        """Project a world coordinate to screen pixels.

        Args:
            x: Normalized world x.
            y: Normalized world y.

        Returns:
            ``(sx, sy)`` relative to the widget's top-left corner.
        """
        cx, cy = self.center
        dx, dy = (x - cx) * self.scale, (y - cy) * self.scale
        c, s = self._cos_sin()
        return dx * c + dy * s + self.width / 2, -dx * s + dy * c + self.height / 2

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        """Inverse of :meth:`world_to_screen`.

        Args:
            sx: Screen x in pixels.
            sy: Screen y in pixels.

        Returns:
            ``(x, y)`` normalized world coordinate.
        """
        cx, cy = self.center
        dx, dy = self._offset_to_world(sx - self.width / 2, sy - self.height / 2, self.scale)
        return cx + dx, cy + dy

    def screen_exprs(self, x: pl.Expr, y: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
        """Vectorized :meth:`world_to_screen` for polars columns.

        Args:
            x: Normalized world x expression.
            y: Normalized world y expression.

        Returns:
            ``(sx, sy)`` expressions.
        """
        cx, cy = self.center
        c, s = self._cos_sin()
        dx, dy = (x - cx) * self.scale, (y - cy) * self.scale
        return dx * c + dy * s + self.width / 2, -dx * s + dy * c + self.height / 2

    def world_rect(self) -> WorldRect:
        """Axis-aligned world bounding box of the visible area.

        When the map is rotated the visible area is a rotated rectangle; this is its
        bounding box (a superset, fine for culling).

        Returns:
            ``(min_x, min_y, max_x, max_y)``.
        """
        corners = [
            self.screen_to_world(sx, sy)
            for sx, sy in ((0.0, 0.0), (self.width, 0.0), (0.0, self.height), (self.width, self.height))
        ]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        return min(xs), min(ys), max(xs), max(ys)

    def bbox(self) -> tuple[float, float, float, float]:
        """The visible area's bounding box in degrees.

        Returns:
            ``(min_lon, min_lat, max_lon, max_lat)``.
        """
        min_x, min_y, max_x, max_y = self.world_rect()
        # World y grows southwards, so the *bottom* edge has the minimum latitude.
        min_lon, min_lat = world_to_lonlat(min_x, max_y)
        max_lon, max_lat = world_to_lonlat(max_x, min_y)
        return min_lon, min_lat, max_lon, max_lat

    def with_size(self, width: int, height: int) -> "Viewport":
        """The same view resized (centre kept).

        Args:
            width: New width in pixels.
            height: New height in pixels.

        Returns:
            The resized viewport.
        """
        return replace(self, width=width, height=height)

    def with_bearing(self, bearing: float) -> "Viewport":
        """The same view rotated about its centre.

        Args:
            bearing: New bearing in degrees (any value; normalized to ``[0, 360)``).

        Returns:
            The rotated viewport.
        """
        return replace(self, bearing=normalize_bearing(bearing))

    def centered_on(self, x: float, y: float, zoom: int | None = None) -> "Viewport":
        """The view moved to a new centre (and optionally zoom).

        Args:
            x: Normalized world x of the new centre.
            y: Normalized world y of the new centre.
            zoom: New zoom, or ``None`` to keep the current one.

        Returns:
            The moved viewport.
        """
        return replace(self, center=(x, y), zoom=self.zoom if zoom is None else zoom)

    def panned(self, dx: float, dy: float) -> "Viewport":
        """The view after dragging the map content by ``(dx, dy)`` screen pixels.

        Args:
            dx: Horizontal drag in pixels (positive = content moves right).
            dy: Vertical drag in pixels (positive = content moves down).

        Returns:
            The panned viewport.
        """
        # What is now at the point opposite the drag comes to the centre.
        return replace(
            self, center=self.screen_to_world(self.width / 2 - dx, self.height / 2 - dy)
        )

    def zoomed_at(self, sx: float, sy: float, zoom: int) -> "Viewport":
        """Change zoom keeping the world point under ``(sx, sy)`` fixed on screen.

        Args:
            sx: Anchor screen x (typically the cursor).
            sy: Anchor screen y.
            zoom: Target zoom level.

        Returns:
            The zoomed viewport.
        """
        ax, ay = self.screen_to_world(sx, sy)
        dx, dy = self._offset_to_world(sx - self.width / 2, sy - self.height / 2, world_size(zoom))
        return replace(self, center=(ax - dx, ay - dy), zoom=zoom)

    def clamped(self, bounds: WorldRect, min_zoom: int, max_zoom: int) -> "Viewport":
        """Constrain zoom to ``[min_zoom, max_zoom]`` and the view centre to ``bounds``.

        Only the *centre* is kept inside ``bounds``, not the whole visible area
        (as Leaflet's ``maxBounds`` does), so any point of the bounds can be dragged
        to the middle of the screen: up to half a screen of surroundings shows past
        the edge at every zoom, and the map stays draggable even when zoomed out far
        enough that the bounds are smaller than the screen. It is also independent
        of the bearing.

        Args:
            bounds: Area ``(min_x, min_y, max_x, max_y)`` in world coords the centre
                must stay in.
            min_zoom: Lowest allowed zoom.
            max_zoom: Highest allowed zoom.

        Returns:
            The constrained viewport (``self`` values unchanged when already valid).
        """
        zoom = max(min_zoom, min(max_zoom, self.zoom))
        min_x, min_y, max_x, max_y = bounds
        cx, cy = self.center
        center = (max(min_x, min(max_x, cx)), max(min_y, min(max_y, cy)))
        return replace(self, center=center, zoom=zoom)

    def visible_tiles(self) -> list[TileKey]:
        """Tiles intersecting the view, nearest to the centre first.

        Returns:
            Tile keys at the current zoom, clipped to the world.
        """
        if self.width <= 0 or self.height <= 0:
            return []
        n = 2**self.zoom
        min_x, min_y, max_x, max_y = self.world_rect()
        # ceil(max) - 1 so an edge landing exactly on a tile boundary does not pull
        # in an extra, fully invisible column/row.
        x0, x1 = max(0, math.floor(min_x * n)), min(n - 1, math.ceil(max_x * n) - 1)
        y0, y1 = max(0, math.floor(min_y * n)), min(n - 1, math.ceil(max_y * n) - 1)
        tiles = [TileKey(self.zoom, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        if self.bearing != 0.0:
            # The bounding box of a rotated view overshoots its corners; keep only
            # tiles whose (rotated) screen footprint meets the screen.
            tiles = [t for t in tiles if self._tile_on_screen(t, n)]
        cx, cy = self.center[0] * n, self.center[1] * n
        tiles.sort(key=lambda t: (t.x + 0.5 - cx) ** 2 + (t.y + 0.5 - cy) ** 2)
        return tiles

    def _tile_on_screen(self, tile: TileKey, n: int) -> bool:
        """Whether a tile's screen footprint intersects the screen.

        Exact for a rotated rectangle vs the screen via the separating-axis test on
        the screen's axes and the tile's (rotated) axes.

        Args:
            tile: The tile.
            n: Tiles per axis at this zoom.

        Returns:
            True if any part of the tile is visible.
        """
        corners = [
            self.world_to_screen((tile.x + i) / n, (tile.y + j) / n)
            for i, j in ((0, 0), (1, 0), (1, 1), (0, 1))
        ]
        screen = [(0.0, 0.0), (self.width, 0.0), (self.width, self.height), (0.0, self.height)]
        (ax, ay), (bx, by), _, (dx, dy) = corners
        axes = [(1.0, 0.0), (0.0, 1.0), (bx - ax, by - ay), (dx - ax, dy - ay)]
        for ux, uy in axes:
            tile_proj = [x * ux + y * uy for x, y in corners]
            screen_proj = [x * ux + y * uy for x, y in screen]
            if max(tile_proj) < min(screen_proj) or max(screen_proj) < min(tile_proj):
                return False
        return True
