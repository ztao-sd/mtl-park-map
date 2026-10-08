"""What a sign's arrow means on the map.

The inventory records the arrow as drawn on the panel (``FLECHE_PAN``: ``"2"`` left,
``"3"`` right, ``"8"`` both ways, ``"0"`` none). Left and right are relative to someone
facing the sign, which says nothing on a map; snapping the pole to its street and side
turns them into a direction along that street.

Convention: signs face the roadway, so for a pole on the segment's left a right arrow
points along the segment's digitized direction, and on the right side against it.
Validated on the Plateau: under this convention the two signs bounding short zones
(delivery, disabled parking) point toward each other 92–100% of the time.
"""

import math

import numpy as np
import polars as pl
import shapely

from mtl_park_map.etl.snapping import MAX_SNAP_M, snap_points
from mtl_park_map.etl.streets import StreetNetwork

FORWARD, BACKWARD, BOTH = 1, -1, 0
ARROW_RIGHT, ARROW_LEFT, ARROW_BOTH = "3", "2", "8"
ARROW_CODES = (ARROW_RIGHT, ARROW_LEFT, ARROW_BOTH)
_TANGENT_HALF_M = 1.0  # half-length of the chord giving the street's local direction

ARROW_SCHEMA = pl.Schema(
    {"sign_id": pl.UInt32, "arrow_street": pl.Utf8, "arrow_bearing": pl.Float64}
)


def arrow_direction(fleche: str, side: int) -> int | None:
    """Direction along the segment that a sign's arrow points to.

    Args:
        fleche: Raw ``FLECHE_PAN`` code: ``"2"`` left, ``"3"`` right, ``"8"`` both.
        side: +1 if the pole is left of the segment's direction, -1 if right.

    Returns:
        :data:`FORWARD`, :data:`BACKWARD`, :data:`BOTH`, or ``None`` for no arrow /
        undocumented codes.
    """
    if fleche == ARROW_BOTH:
        return BOTH
    if fleche == ARROW_RIGHT:
        return FORWARD if side > 0 else BACKWARD
    if fleche == ARROW_LEFT:
        return BACKWARD if side > 0 else FORWARD
    return None


def sign_arrows(
    signs: pl.DataFrame, network: StreetNetwork, max_snap_m: float = MAX_SNAP_M
) -> pl.DataFrame:
    """Street and compass bearing each arrowed sign points along.

    Args:
        signs: Curated signs (``sign_id``, ``pole_id``, ``longitude``, ``latitude``,
            ``fleche``).
        network: Street segments to snap poles to.
        max_snap_m: Maximum pole-to-centreline distance.

    Returns:
        :data:`ARROW_SCHEMA` rows for signs with a usable arrow whose pole snapped:
        ``arrow_bearing`` is the compass direction (degrees clockwise from north) the
        arrow points to; for double arrows, that of the street's digitized direction
        (the opposite way applies too).
    """
    arrowed = signs.filter(pl.col("fleche").is_in(ARROW_CODES))
    poles = arrowed.group_by("pole_id").agg(pl.col("longitude", "latitude").first()).sort("pole_id")
    snaps = snap_points(
        network, poles["longitude"].to_numpy(), poles["latitude"].to_numpy(), max_snap_m
    )
    poles = pl.concat([poles, snaps], how="horizontal").drop_nulls("segment_index")
    if poles.is_empty():
        return pl.DataFrame(schema=ARROW_SCHEMA)

    seg = poles["segment_index"].to_numpy()
    poles = poles.with_columns(
        pl.Series("street", [network.names[i] for i in seg], dtype=pl.Utf8),
        pl.Series(
            "street_bearing",
            _segment_bearings(network, seg, poles["along_m"].to_numpy()),
            dtype=pl.Float64,
        ),
    )
    rows = []
    for row in arrowed.join(poles, on="pole_id").iter_rows(named=True):
        direction = arrow_direction(row["fleche"], row["side"])
        if direction is None:
            continue
        # Pointing against the segment = the street's bearing turned around.
        bearing = row["street_bearing"] + (180.0 if direction == BACKWARD else 0.0)
        rows.append(
            {"sign_id": row["sign_id"], "arrow_street": row["street"], "arrow_bearing": bearing % 360.0}
        )
    return pl.DataFrame(rows, schema=ARROW_SCHEMA).sort("sign_id")


def _segment_bearings(
    network: StreetNetwork, segments: np.ndarray, along: np.ndarray
) -> list[float]:
    """Compass bearing of each segment's digitized direction at a point along it.

    Args:
        network: The street network.
        segments: Segment index per point.
        along: Distance along that segment per point.

    Returns:
        Degrees clockwise from north (local metres: x east, y north).
    """
    lines = network.lines[segments]
    lengths = network.lengths[segments]
    behind = shapely.get_coordinates(
        shapely.line_interpolate_point(lines, np.clip(along - _TANGENT_HALF_M, 0, lengths))
    )
    ahead = shapely.get_coordinates(
        shapely.line_interpolate_point(lines, np.clip(along + _TANGENT_HALF_M, 0, lengths))
    )
    dx, dy = (ahead - behind).T
    return [math.degrees(math.atan2(x, y)) % 360.0 for x, y in zip(dx, dy, strict=True)]
