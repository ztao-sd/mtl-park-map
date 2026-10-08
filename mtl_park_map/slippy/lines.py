"""Polyline layers: projected once, culled to the viewport and hit-tested."""

import math
from dataclasses import dataclass

import polars as pl

from mtl_park_map.slippy.layers import Hit
from mtl_park_map.slippy.projection import world_x, world_y
from mtl_park_map.slippy.viewport import Viewport

type ScreenPolyline = tuple[int, list[tuple[float, float]]]

_HIT_SLACK_PX = 3.0  # pick tolerance beyond half the stroke width


@dataclass(frozen=True, slots=True)
class LineStyle:
    """How a layer's lines look.

    Attributes:
        color: Stroke colour ``#rrggbb``.
        width: Stroke width in pixels.
        dashed: Draw the stroke dashed (over a solid white casing).
    """

    color: str
    width: float = 4.0
    dashed: bool = False


def _segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Distance from point ``p`` to segment ``ab`` (all in pixels).

    Returns:
        The Euclidean distance to the closest point of the segment.
    """
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class LineLayer:
    """A named, single-style set of polylines, drawn from ``min_zoom`` up.

    Args:
        name: Identifier reported in hits (unique per map).
        style: Line appearance.
        lines: Frame with ``longitudes`` and ``latitudes`` list columns (degrees),
            one polyline per row. Row numbers identify lines in hits.
        min_zoom: Below this zoom the layer is neither drawn nor hit-tested (dense
            street-level detail would only be noise).
    """

    def __init__(self, name: str, style: LineStyle, lines: pl.DataFrame, min_zoom: int = 15):
        self.name = name
        self.style = style
        self.min_zoom = min_zoom
        # Project once into normalized world coordinates and keep each line's bbox,
        # so culling is a columnar filter.
        self._world = (
            lines.select(
                pl.col("longitudes").list.eval(world_x(pl.element())).alias("xs"),
                pl.col("latitudes").list.eval(world_y(pl.element())).alias("ys"),
            )
            .with_row_index("idx")
            .with_columns(
                pl.col("xs").list.min().alias("min_x"),
                pl.col("xs").list.max().alias("max_x"),
                pl.col("ys").list.min().alias("min_y"),
                pl.col("ys").list.max().alias("max_y"),
            )
        )

    def __len__(self) -> int:
        """Number of lines in the layer."""
        return self._world.height

    def _visible(self, vp: Viewport, margin_px: float) -> pl.DataFrame:
        """Lines whose bbox meets the viewport (grown by ``margin_px``), projected.

        Args:
            vp: The current viewport.
            margin_px: Extra border in pixels.

        Returns:
            Columns ``idx``, ``sxs``, ``sys`` (screen coordinates); empty below
            ``min_zoom``.
        """
        if vp.zoom < self.min_zoom or self._world.is_empty():
            return pl.DataFrame(schema={"idx": pl.UInt32, "sxs": pl.List(pl.Float64), "sys": pl.List(pl.Float64)})
        margin = margin_px / vp.scale
        min_x, min_y, max_x, max_y = vp.world_rect()
        visible = self._world.filter(
            pl.col("max_x") >= min_x - margin,
            pl.col("min_x") <= max_x + margin,
            pl.col("max_y") >= min_y - margin,
            pl.col("min_y") <= max_y + margin,
        )
        if visible.is_empty():
            return pl.DataFrame(schema={"idx": pl.UInt32, "sxs": pl.List(pl.Float64), "sys": pl.List(pl.Float64)})
        # With rotation each screen coordinate mixes x and y, so project vertex rows
        # (the two lists explode in lockstep) and regroup per line, keeping order.
        sx, sy = vp.screen_exprs(pl.col("xs"), pl.col("ys"))
        return (
            visible.select("idx", "xs", "ys")
            .explode("xs", "ys", empty_as_null=False)
            .select("idx", sx.alias("sx"), sy.alias("sy"))
            .group_by("idx", maintain_order=True)
            .agg(pl.col("sx").alias("sxs"), pl.col("sy").alias("sys"))
        )

    def screen_polylines(self, vp: Viewport, margin_px: float = 10.0) -> list[ScreenPolyline]:
        """Visible lines in screen pixels, for painting.

        Args:
            vp: The current viewport.
            margin_px: Extra border so lines crossing the edge are kept.

        Returns:
            ``(idx, [(sx, sy), ...])`` per visible line, in row order.
        """
        visible = self._visible(vp, margin_px)
        return [
            (idx, list(zip(xs, ys, strict=True)))
            for idx, xs, ys in zip(
                visible["idx"].to_list(), visible["sxs"].to_list(), visible["sys"].to_list(), strict=True
            )
        ]

    def hit_test(self, vp: Viewport, sx: float, sy: float) -> Hit | None:
        """The line drawn under a screen point, if any.

        Args:
            vp: The current viewport.
            sx: Screen x of the cursor.
            sy: Screen y of the cursor.

        Returns:
            The nearest line within half its stroke plus a small tolerance, with the
            *cursor* position as the hit location (lines have no single anchor).
        """
        tolerance = self.style.width / 2 + _HIT_SLACK_PX
        best: tuple[float, int] | None = None
        for idx, points in self.screen_polylines(vp, margin_px=tolerance):
            for (ax, ay), (bx, by) in zip(points, points[1:]):
                d = _segment_distance(sx, sy, ax, ay, bx, by)
                if d <= tolerance and (best is None or d < best[0]):
                    best = (d, idx)
        if best is None:
            return None
        x, y = vp.screen_to_world(sx, sy)
        return Hit(self.name, best[1], 1, x, y)
