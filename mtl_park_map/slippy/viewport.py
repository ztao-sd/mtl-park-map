"""Immutable map viewport: what part of the world is shown, at what zoom, how big."""

import math
from dataclasses import dataclass, replace

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


@dataclass(frozen=True, slots=True)
class Viewport:
    """A view of the world.

    Zoom is integral so that 256 px tiles are drawn 1:1 (crisp, seam-free).

    Attributes:
        center: Normalized world coordinate at the centre of the screen.
        zoom: Integer zoom level.
        width: Screen width in logical pixels.
        height: Screen height in logical pixels.
    """

    center: tuple[float, float]
    zoom: int
    width: int
    height: int

    @property
    def scale(self) -> float:
        """Screen pixels per normalized world unit."""
        return world_size(self.zoom)

    def world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        """Project a world coordinate to screen pixels.

        Args:
            x: Normalized world x.
            y: Normalized world y.

        Returns:
            ``(sx, sy)`` relative to the widget's top-left corner.
        """
        cx, cy = self.center
        return (x - cx) * self.scale + self.width / 2, (y - cy) * self.scale + self.height / 2

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        """Inverse of :meth:`world_to_screen`.

        Args:
            sx: Screen x in pixels.
            sy: Screen y in pixels.

        Returns:
            ``(x, y)`` normalized world coordinate.
        """
        cx, cy = self.center
        return cx + (sx - self.width / 2) / self.scale, cy + (sy - self.height / 2) / self.scale

    def world_rect(self) -> WorldRect:
        """The visible area in world coordinates.

        Returns:
            ``(min_x, min_y, max_x, max_y)``.
        """
        min_x, min_y = self.screen_to_world(0.0, 0.0)
        max_x, max_y = self.screen_to_world(float(self.width), float(self.height))
        return min_x, min_y, max_x, max_y

    def bbox(self) -> tuple[float, float, float, float]:
        """The visible area in degrees.

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
        cx, cy = self.center
        return replace(self, center=(cx - dx / self.scale, cy - dy / self.scale))

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
        scale = world_size(zoom)
        center = (ax - (sx - self.width / 2) / scale, ay - (sy - self.height / 2) / scale)
        return replace(self, center=center, zoom=zoom)

    def clamped(self, bounds: WorldRect, min_zoom: int, max_zoom: int) -> "Viewport":
        """Constrain zoom to ``[min_zoom, max_zoom]`` and the view to ``bounds``.

        Like Leaflet's ``maxBounds``: the visible area is kept inside ``bounds``; along
        an axis where the view is larger than the bounds, the bounds are centred.

        Args:
            bounds: Allowed area ``(min_x, min_y, max_x, max_y)`` in world coords.
            min_zoom: Lowest allowed zoom.
            max_zoom: Highest allowed zoom.

        Returns:
            The constrained viewport.
        """
        zoom = max(min_zoom, min(max_zoom, self.zoom))
        scale = world_size(zoom)
        min_x, min_y, max_x, max_y = bounds

        def clamp_axis(c: float, half: float, lo: float, hi: float) -> float:
            """Clamp centre ``c`` so ``[c - half, c + half]`` stays in ``[lo, hi]``."""
            if hi - lo <= 2 * half:
                return (lo + hi) / 2
            return max(lo + half, min(hi - half, c))

        cx, cy = self.center
        center = (
            clamp_axis(cx, self.width / 2 / scale, min_x, max_x),
            clamp_axis(cy, self.height / 2 / scale, min_y, max_y),
        )
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
        cx, cy = self.center[0] * n, self.center[1] * n
        tiles = [TileKey(self.zoom, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        tiles.sort(key=lambda t: (t.x + 0.5 - cx) ** 2 + (t.y + 0.5 - cy) ** 2)
        return tiles
