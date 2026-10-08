"""Snap sign poles to the street segment and side they regulate.

A pole stands on the sidewalk, typically 5–10 m from the street centreline (city-wide
median 6.8 m, 95th percentile 9.9 m). It is assigned to the nearest street segment
within :data:`MAX_SNAP_M`; ``side`` is which side of the segment's digitized direction
it stands on, ``along_m`` where along the segment it projects.

At corners a pole can be about as close to the cross street as to its own; those are
snapped to the nearest one anyway and flagged ``ambiguous``.
"""

import numpy as np
import polars as pl
import shapely

from mtl_park_map.etl.geometry import FloatArray, to_local
from mtl_park_map.etl.streets import StreetNetwork

MAX_SNAP_M = 15.0  # keeps ~99% of poles; beyond are lots, plazas, missing streets
AMBIGUITY_M = 2.0  # another street this much farther or less => ambiguous
_TANGENT_HALF_M = 0.5  # half-length of the chord used to estimate segment direction

SNAP_SCHEMA = pl.Schema(
    {
        "segment_index": pl.UInt32,
        "segment_id": pl.Int64,
        "along_m": pl.Float64,
        "dist_m": pl.Float64,
        "side": pl.Int8,
        "ambiguous": pl.Boolean,
    }
)


def snap_points(
    network: StreetNetwork, lon: FloatArray, lat: FloatArray, max_dist_m: float = MAX_SNAP_M
) -> pl.DataFrame:
    """Snap points to their nearest street segment and side.

    Args:
        network: The street network.
        lon: Point longitudes.
        lat: Point latitudes.
        max_dist_m: Points farther than this from every segment are left unsnapped.

    Returns:
        One row per input point, in input order, with :data:`SNAP_SCHEMA` columns;
        all null for unsnapped points. ``side`` is +1 left / -1 right of the
        segment's direction.
    """
    n = len(lon)
    x, y = to_local(np.asarray(lon, dtype=np.float64), np.asarray(lat, dtype=np.float64))
    points = shapely.points(x, y)

    point_idx, seg_idx = network.tree.query(points, predicate="dwithin", distance=max_dist_m)
    if point_idx.size == 0:
        return pl.DataFrame({k: [None] * n for k in SNAP_SCHEMA.names()}, schema=SNAP_SCHEMA)
    dist = shapely.distance(points[point_idx], network.lines[seg_idx])
    candidates = (
        pl.DataFrame({"point": point_idx, "segment": seg_idx, "dist": dist})
        .with_columns(
            pl.Series("name", [network.names[i] for i in seg_idx], dtype=pl.Utf8)
        )
        .sort(["point", "dist"])
    )
    nearest = candidates.group_by("point", maintain_order=True).first()
    # Ambiguous: a *different* street (not the next block of the same one) is almost
    # as close as the nearest.
    rival = (
        candidates.join(nearest.select("point", "name", pl.col("dist").alias("best")), on="point")
        .filter(pl.col("name") != pl.col("name_right"))
        .group_by("point")
        .agg((pl.col("dist") - pl.col("best")).min().alias("margin"))
    )
    nearest = nearest.join(rival, on="point", how="left")

    p = nearest["point"].to_numpy()
    s = nearest["segment"].to_numpy()
    lines = network.lines[s]
    along = shapely.line_locate_point(lines, points[p])
    side = _side(lines, network.lengths[s], along, x[p], y[p])

    snapped = pl.DataFrame(
        {
            "point": p,
            "segment_index": s,
            "segment_id": network.segment_ids[s],
            "along_m": along,
            "dist_m": nearest["dist"].to_numpy(),
            "side": side,
            "ambiguous": (nearest["margin"].fill_null(np.inf) < AMBIGUITY_M).to_numpy(),
        }
    ).filter(pl.col("side") != 0)  # exactly on the centreline: side unknown
    return (
        pl.DataFrame({"point": np.arange(n)})
        .join(snapped, on="point", how="left")
        .sort("point")
        .select(SNAP_SCHEMA.names())
        .cast(SNAP_SCHEMA)
    )


def _side(
    lines: np.ndarray,
    lengths: FloatArray,
    along: FloatArray,
    x: FloatArray,
    y: FloatArray,
) -> np.ndarray:
    """Which side of each line its point lies on.

    Args:
        lines: Segment per point.
        lengths: Segment lengths.
        along: Projection distance of each point along its segment.
        x: Point x (metres).
        y: Point y (metres).

    Returns:
        +1 (left of the line's direction), -1 (right) or 0 (on the line).
    """
    # Direction from a short chord around the projection (robust at vertices).
    behind = shapely.get_coordinates(
        shapely.line_interpolate_point(lines, np.clip(along - _TANGENT_HALF_M, 0, lengths))
    )
    ahead = shapely.get_coordinates(
        shapely.line_interpolate_point(lines, np.clip(along + _TANGENT_HALF_M, 0, lengths))
    )
    foot = shapely.get_coordinates(shapely.line_interpolate_point(lines, along))
    tx, ty = (ahead - behind).T
    vx, vy = x - foot[:, 0], y - foot[:, 1]
    return np.sign(tx * vy - ty * vx).astype(np.int8)
