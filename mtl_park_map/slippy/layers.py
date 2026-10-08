"""Marker layers: points projected once, clustered per zoom, culled and hit-tested."""

import math
from dataclasses import dataclass

import polars as pl

from mtl_park_map.slippy.clustering import cluster_points
from mtl_park_map.slippy.projection import world_x, world_y
from mtl_park_map.slippy.viewport import Viewport

# Cluster circles stay well under half a grid cell (80 px) so dense areas keep the
# basemap visible between them.
_CLUSTER_MIN_RADIUS = 10.0
_CLUSTER_MAX_RADIUS = 20.0
_CLUSTER_GROWTH = 2.0  # extra pixels per doubling of the member count

SCREEN_SCHEMA = pl.Schema(
    {"sx": pl.Float64, "sy": pl.Float64, "count": pl.UInt32, "idx": pl.UInt32}
)


@dataclass(frozen=True, slots=True)
class MarkerStyle:
    """How a layer's markers look.

    Attributes:
        color: Fill colour as ``#rrggbb``.
        radius: Radius of a single (unclustered) marker in pixels.
    """

    color: str
    radius: float = 5.0


@dataclass(frozen=True, slots=True)
class Hit:
    """A marker or cluster under the cursor.

    Attributes:
        layer: Name of the layer hit.
        idx: Row of the hit point in the layer's source frame (lowest member row for
            a cluster).
        count: Number of points in the cluster (1 for a single marker).
        x: Normalized world x of the marker/cluster centre.
        y: Normalized world y of the marker/cluster centre.
    """

    layer: str
    idx: int
    count: int
    x: float
    y: float


def cluster_radius(count: int, base: float) -> float:
    """On-screen radius of a marker representing ``count`` points.

    Args:
        count: Cluster member count.
        base: Single-marker radius.

    Returns:
        ``base`` for a single point, otherwise a log-scaled, capped radius.
    """
    if count <= 1:
        return base
    return min(_CLUSTER_MIN_RADIUS + _CLUSTER_GROWTH * math.log2(count), _CLUSTER_MAX_RADIUS)


def _radius_expr(base: float) -> pl.Expr:
    """Vectorized :func:`cluster_radius` over a ``count`` column."""
    grown = (_CLUSTER_MIN_RADIUS + _CLUSTER_GROWTH * pl.col("count").cast(pl.Float64).log(2)).clip(
        upper_bound=_CLUSTER_MAX_RADIUS
    )
    return pl.when(pl.col("count") <= 1).then(pl.lit(base)).otherwise(grown)


class MarkerLayer:
    """A named, single-style set of points drawn on the map.

    Args:
        name: Identifier reported in hits (unique per map).
        style: Marker appearance.
        points: Frame with ``longitude`` and ``latitude`` columns (degrees). Row
            numbers identify points in hits, so callers can look up their payload in
            the same frame.
        cell_px: Clustering grid cell size in pixels.
        disable_clustering_at: Zoom from which points are never clustered.
    """

    def __init__(
        self,
        name: str,
        style: MarkerStyle,
        points: pl.DataFrame,
        cell_px: float = 80.0,
        disable_clustering_at: int = 17,
    ):
        self.name = name
        self.style = style
        # Project once; every zoom level reuses the normalized world coordinates.
        self._world = points.select(
            world_x(pl.col("longitude")).alias("x"), world_y(pl.col("latitude")).alias("y")
        )
        self._cell_px = cell_px
        self._disable_at = disable_clustering_at
        self._clusters: dict[int, pl.DataFrame] = {}

    def __len__(self) -> int:
        """Number of points in the layer."""
        return self._world.height

    def clusters(self, zoom: int) -> pl.DataFrame:
        """Clusters at ``zoom`` (computed once per zoom, then cached).

        Args:
            zoom: Integer zoom level.

        Returns:
            See :func:`mtl_park_map.slippy.clustering.cluster_points`.
        """
        if zoom not in self._clusters:
            self._clusters[zoom] = cluster_points(
                self._world, zoom, self._cell_px, self._disable_at
            )
        return self._clusters[zoom]

    def screen_clusters(self, vp: Viewport, margin_px: float = 30.0) -> pl.DataFrame:
        """Clusters within (or ``margin_px`` around) the viewport, in screen pixels.

        Args:
            vp: The current viewport.
            margin_px: Extra border so markers straddling the edge are still drawn.

        Returns:
            Columns ``sx``, ``sy``, ``count``, ``idx``.
        """
        sx, sy = vp.screen_exprs(pl.col("x"), pl.col("y"))
        return (
            self.clusters(vp.zoom)
            .select(sx.alias("sx"), sy.alias("sy"), "count", "idx")
            .filter(
                pl.col("sx").is_between(-margin_px, vp.width + margin_px),
                pl.col("sy").is_between(-margin_px, vp.height + margin_px),
            )
            .cast(SCREEN_SCHEMA)
        )

    def hit_test(
        self, vp: Viewport, sx: float, sy: float, tolerance_px: float = 3.0
    ) -> Hit | None:
        """The marker or cluster drawn under a screen point, if any.

        Args:
            vp: The current viewport.
            sx: Screen x of the cursor.
            sy: Screen y of the cursor.
            tolerance_px: Extra pick radius beyond the drawn circle.

        Returns:
            The nearest hit whose circle (plus tolerance) contains the point, or None.
        """
        hits = (
            self.screen_clusters(vp)
            .with_columns(
                ((pl.col("sx") - sx) ** 2 + (pl.col("sy") - sy) ** 2).alias("d2"),
                (_radius_expr(self.style.radius) + tolerance_px).alias("r"),
            )
            .filter(pl.col("d2") <= pl.col("r") ** 2)
            .sort("d2")
        )
        if hits.is_empty():
            return None
        row = hits.row(0, named=True)
        x, y = vp.screen_to_world(row["sx"], row["sy"])
        return Hit(self.name, int(row["idx"]), int(row["count"]), x, y)
