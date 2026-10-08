"""Grid-based point clustering, vectorized with polars.

Points are bucketed into ``cell_px``-sized squares of the *world* pixel grid at the
given zoom (not the screen grid), so clusters are stable while panning and only change
on zoom. A cluster sits at the mean position of its members. ~5 ms for 150k points.
"""

import polars as pl

from mtl_park_map.slippy.projection import world_size

CLUSTER_SCHEMA = pl.Schema(
    {"x": pl.Float64, "y": pl.Float64, "count": pl.UInt32, "idx": pl.UInt32}
)


def cluster_points(
    points: pl.DataFrame,
    zoom: int,
    cell_px: float = 80.0,
    disable_at_zoom: int = 17,
) -> pl.DataFrame:
    """Cluster points for display at ``zoom``.

    Args:
        points: Columns ``x`` and ``y`` in normalized world coordinates; a point's
            row number is its identity (``idx``).
        zoom: Zoom level the clusters are drawn at.
        cell_px: Grid cell size in screen pixels.
        disable_at_zoom: At or above this zoom every point is its own cluster.

    Returns:
        Columns ``x``, ``y`` (cluster position), ``count`` (members) and ``idx``
        (lowest member row number — *the* point when ``count == 1``), sorted by
        ``idx``.
    """
    indexed = points.select(
        pl.col("x").cast(pl.Float64), pl.col("y").cast(pl.Float64)
    ).with_row_index("idx")
    if zoom >= disable_at_zoom:
        return indexed.select("x", "y", pl.lit(1, pl.UInt32).alias("count"), "idx")

    cells_per_unit = world_size(zoom) / cell_px
    return (
        indexed.group_by(
            (pl.col("x") * cells_per_unit).floor().alias("cell_x"),
            (pl.col("y") * cells_per_unit).floor().alias("cell_y"),
        )
        .agg(
            pl.col("x").mean(),
            pl.col("y").mean(),
            pl.len().cast(pl.UInt32).alias("count"),
            pl.col("idx").min(),
        )
        # group_by order is unspecified; sorting makes rendering deterministic.
        .sort("idx")
        .select(CLUSTER_SCHEMA.names())
        .cast(CLUSTER_SCHEMA)
    )
