"""Synthesize curb strips from no-parking (``\\P``) signs.

A strip is a stretch of one side of one street segment (block) together with every
no-parking rule that applies along it, so the app can tell for any time window which
curbs are restricted and which are parkable, without rebuilding geometry at runtime.

How a sign's extent is derived:

1. **Snap** its pole to a segment and side (:mod:`mtl_park_map.etl.snapping`).
2. **Orient** its arrow along the segment
   (:func:`mtl_park_map.etl.arrows.arrow_direction`).
3. **Extend** it (:func:`rule_extents`): from the pole in the arrow's direction up
   to the next sign of the same rule pointing back, or else to the end of the block.
   A double arrow (``"8"``) extends both ways.
4. **Split** each curb side into pieces with a constant set of rules
   (:func:`split_pieces`); overlapping rules (e.g. street cleaning and a permit zone)
   end up on the same piece.

Signs **without an arrow** (65% of no-parking panels) say nothing about extent, so it
is inferred conservatively (:func:`inferred_extents`): when a rule appears on a curb
side *only* on arrow-less signs, it is taken to cover the stretch from its first to its
last sign there, padded by :data:`INFERRED_PAD_M` and clipped to the block (a lone sign
covers 20 m). Where the rule also has arrowed signs on that side, the arrow-less ones
are repeaters (or contradict them) and are ignored. Inferred rules are flagged per strip
(``inferred_code_ids``, ``rules[].inferred``; ``is_inferred`` when a strip exists by
inference alone) so the app can draw them differently or leave them out.

Other arrow codes and unsnapped poles are not used. Extents stop at segment ends:
Géobase segments are blocks, and a curb rule does not continue past an intersection.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl
import shapely
from shapely.ops import substring

from mtl_park_map.enums import SignKind
from mtl_park_map.etl.arrows import ARROW_CODES, BACKWARD, BOTH, FORWARD, arrow_direction
from mtl_park_map.etl.dtypes import HOUR_RANGES, INT_RANGES
from mtl_park_map.etl.geometry import to_lonlat
from mtl_park_map.etl.snapping import MAX_SNAP_M, snap_points
from mtl_park_map.etl.streets import StreetNetwork

MIN_STRIP_M = 1.0  # shorter pieces are rounding slivers
# Strips are drawn on the parking lane: this far inside the side's median pole line,
# clamped to a sane distance from the centreline.
_PARKING_LANE_INSET_M = 2.5
_MIN_CURB_OFFSET_M = 1.5
_MAX_CURB_OFFSET_M = 10.0
_COORD_DECIMALS = 7  # ~1 cm
_NO_ARROW = "0"
# Padding beyond the first/last arrow-less sign of a rule. Conservative: arrowed
# street-cleaning zones cover a median 73% of their block side, so spanning only the
# signs (+10 m) under-claims rather than over-claims.
INFERRED_PAD_M = 10.0

type Extent = tuple[float, float, int]  # (start_m, end_m, sign_id)

RULE_DTYPE = pl.Struct(
    {
        "code_id": pl.UInt32,
        "description": pl.Utf8,
        "hour_ranges": HOUR_RANGES,
        "day_ranges": INT_RANGES,
        "month_ranges": INT_RANGES,
        "inferred": pl.Boolean,  # extent inferred from signs without arrows
    }
)
STRIP_SCHEMA = pl.Schema(
    {
        "strip_id": pl.UInt32,
        "segment_id": pl.Int64,
        "street": pl.Utf8,
        "side": pl.Int8,
        "start_m": pl.Float64,
        "end_m": pl.Float64,
        "length_m": pl.Float64,
        "longitudes": pl.List(pl.Float64),
        "latitudes": pl.List(pl.Float64),
        "min_lon": pl.Float64,
        "min_lat": pl.Float64,
        "max_lon": pl.Float64,
        "max_lat": pl.Float64,
        "code_ids": pl.List(pl.UInt32),
        # Rules whose extent here was inferred (signs without arrows), and whether
        # the strip exists by inference alone.
        "inferred_code_ids": pl.List(pl.UInt32),
        "is_inferred": pl.Boolean,
        "sign_ids": pl.List(pl.UInt32),
        # Distinct poles carrying those signs, for highlighting them on the map.
        "pole_longitudes": pl.List(pl.Float64),
        "pole_latitudes": pl.List(pl.Float64),
        "rules": pl.List(RULE_DTYPE),
    }
)


@dataclass(frozen=True, slots=True)
class SignEvent:
    """One sign panel positioned on a curb side.

    Attributes:
        along_m: Position along the segment.
        direction: :data:`FORWARD`, :data:`BACKWARD` or :data:`BOTH`.
        sign_id: The panel's ``sign_id``.
    """

    along_m: float
    direction: int
    sign_id: int


@dataclass(frozen=True, slots=True)
class Piece:
    """A stretch of curb with a constant set of rules.

    Attributes:
        start_m: Start along the segment.
        end_m: End along the segment.
        code_ids: Rules applying along it (sorted).
        sign_ids: Panels whose extents cover it (sorted).
    """

    start_m: float
    end_m: float
    code_ids: tuple[int, ...]
    sign_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class StripReport:
    """Coverage statistics of a strip build.

    Attributes:
        panels: No-parking panels with a usable arrow.
        panels_snapped: Of those, panels whose pole snapped to a street side.
        inferred_panels: Arrow-less no-parking panels whose rule's extent was inferred.
        poles: Distinct poles carrying the no-parking panels considered.
        poles_ambiguous: Snapped poles that could belong to a cross street.
        strips: Strips produced.
        total_km: Their total length.
        inferred_km: Length of strips that exist by inference alone.
    """

    panels: int
    panels_snapped: int
    inferred_panels: int
    poles: int
    poles_ambiguous: int
    strips: int
    total_km: float
    inferred_km: float


def rule_extents(events: Sequence[SignEvent], length_m: float) -> list[Extent]:
    """Stretches covered by each sign of one rule on one curb side.

    A ray stops at the next sign of the rule pointing back toward it, or at the end
    of the segment. Signs pointing the same way, or double arrows, do not stop it:
    they repeat the rule within the same zone.

    Args:
        events: The rule's signs on this curb side.
        length_m: Segment length.

    Returns:
        ``(start_m, end_m, sign_id)`` per ray, in sign order (backward ray first for
        double arrows).
    """
    extents: list[Extent] = []
    for event in sorted(events, key=lambda e: (e.along_m, e.sign_id)):
        if event.direction in (BACKWARD, BOTH):
            start = max(
                (o.along_m for o in events if o.along_m < event.along_m and o.direction == FORWARD),
                default=0.0,
            )
            extents.append((start, event.along_m, event.sign_id))
        if event.direction in (FORWARD, BOTH):
            end = min(
                (o.along_m for o in events if o.along_m > event.along_m and o.direction == BACKWARD),
                default=length_m,
            )
            extents.append((event.along_m, end, event.sign_id))
    return extents


def inferred_extents(
    signs: Sequence[tuple[float, int]], length_m: float, pad_m: float = INFERRED_PAD_M
) -> list[Extent]:
    """Extent of a rule known only from arrow-less signs on one curb side.

    Conservative: the stretch the signs themselves span, padded by ``pad_m`` and
    clipped to the block. Every sign is credited with the whole stretch.

    Args:
        signs: ``(along_m, sign_id)`` of the rule's arrow-less signs on this side.
        length_m: Segment length.
        pad_m: Padding beyond the first and last sign.

    Returns:
        One ``(start_m, end_m, sign_id)`` per sign, all with the same stretch.
    """
    start = max(0.0, min(a for a, _ in signs) - pad_m)
    end = min(length_m, max(a for a, _ in signs) + pad_m)
    return [(start, end, sign_id) for _, sign_id in sorted(signs)]


def split_pieces(
    extents_by_code: Mapping[int, Sequence[Extent]], min_length_m: float = MIN_STRIP_M
) -> list[Piece]:
    """Cut a curb side into pieces with a constant set of covering rules.

    Args:
        extents_by_code: Each rule's extents on this curb side.
        min_length_m: Pieces shorter than this (after merging) are dropped.

    Returns:
        Covered pieces in order; adjacent pieces with the same rules are merged.
    """
    bounds = sorted({p for extents in extents_by_code.values() for s, e, _ in extents for p in (s, e)})
    pieces: list[Piece] = []
    for start, end in zip(bounds, bounds[1:]):
        mid = (start + end) / 2
        codes: set[int] = set()
        signs: set[int] = set()
        for code_id, extents in extents_by_code.items():
            for s, e, sign_id in extents:
                if s <= mid <= e:
                    codes.add(code_id)
                    signs.add(sign_id)
        if not codes:
            continue
        piece = Piece(start, end, tuple(sorted(codes)), tuple(sorted(signs)))
        previous = pieces[-1] if pieces else None
        if previous and previous.end_m == start and previous.code_ids == piece.code_ids:
            merged_signs = tuple(sorted({*previous.sign_ids, *piece.sign_ids}))
            pieces[-1] = Piece(previous.start_m, end, piece.code_ids, merged_signs)
        else:
            pieces.append(piece)
    return [p for p in pieces if p.end_m - p.start_m >= min_length_m]


def build_strips(
    signs: pl.DataFrame,
    codes: pl.DataFrame,
    network: StreetNetwork,
    max_snap_m: float = MAX_SNAP_M,
) -> tuple[pl.DataFrame, StripReport]:
    """Synthesize no-parking curb strips.

    Args:
        signs: Curated signs (``sign_id``, ``pole_id``, ``longitude``, ``latitude``,
            ``fleche``, ``code_id``).
        codes: Curated codes (``code_id``, ``kind``, ``description`` and the parsed
            ``hour_ranges`` / ``day_ranges`` / ``month_ranges``).
        network: Street segments to snap to.
        max_snap_m: Maximum pole-to-centreline distance.

    Returns:
        Strips with :data:`STRIP_SCHEMA` (sorted by segment, side, start) and a
        coverage report.
    """
    no_parking = codes.filter(pl.col("kind") == SignKind.no_parking.value)
    candidates = signs.join(no_parking.select("code_id"), on="code_id").filter(
        pl.col("fleche").is_in([*ARROW_CODES, _NO_ARROW])
    )
    arrowed_panels = candidates.filter(pl.col("fleche") != _NO_ARROW).height
    # One snapping pass for arrowed and arrow-less panels alike.
    poles = candidates.group_by("pole_id").agg(pl.col("longitude", "latitude").first()).sort("pole_id")
    snaps = snap_points(
        network, poles["longitude"].to_numpy(), poles["latitude"].to_numpy(), max_snap_m
    )
    pole_count = poles.height
    poles = pl.concat([poles, snaps], how="horizontal").drop_nulls("segment_index")
    events = candidates.join(poles.drop("longitude", "latitude"), on="pole_id")

    curb_offsets = {
        (seg, side): float(
            np.clip(dist - _PARKING_LANE_INSET_M, _MIN_CURB_OFFSET_M, _MAX_CURB_OFFSET_M)
        )
        for seg, side, dist in poles.group_by("segment_index", "side")
        .agg(pl.col("dist_m").median())
        .iter_rows()
    }
    rule_columns = [f.name for f in RULE_DTYPE.fields if f.name != "inferred"]
    rules = {r["code_id"]: r for r in no_parking.select(rule_columns).iter_rows(named=True)}

    # (segment_index, side) -> code_id -> arrowed events / arrow-less (along, sign_id)
    arrowed: dict[tuple[int, int], dict[int, list[SignEvent]]] = defaultdict(lambda: defaultdict(list))
    bare: dict[tuple[int, int], dict[int, list[tuple[float, int]]]] = defaultdict(lambda: defaultdict(list))
    sign_poles: dict[int, tuple[float, float]] = {}
    arrowed_snapped = 0
    for row in events.iter_rows(named=True):
        sign_poles[row["sign_id"]] = (row["longitude"], row["latitude"])
        seg, side = row["segment_index"], row["side"]
        along = min(max(row["along_m"], 0.0), float(network.lengths[seg]))
        if row["fleche"] == _NO_ARROW:
            bare[(seg, side)][row["code_id"]].append((along, row["sign_id"]))
            continue
        arrowed_snapped += 1
        direction = arrow_direction(row["fleche"], side)
        if direction is not None:
            arrowed[(seg, side)][row["code_id"]].append(SignEvent(along, direction, row["sign_id"]))

    rows: list[dict[str, object]] = []
    inferred_panels = 0
    for seg, side in sorted(arrowed.keys() | bare.keys()):
        length = float(network.lengths[seg])
        extents = {code: rule_extents(evs, length) for code, evs in arrowed[(seg, side)].items()}
        # Arrow-less signs only count for rules with no arrowed sign on this side.
        inferred = {
            code: inferred_extents(signs_here, length)
            for code, signs_here in bare[(seg, side)].items()
            if code not in extents
        }
        inferred_panels += sum(len(v) for v in inferred.values())
        extents.update(inferred)
        for piece in split_pieces(extents):
            inferred_codes = [c for c in piece.code_ids if c in inferred]
            lons, lats = _curb_line(network.lines[seg], piece, side, curb_offsets[(seg, side)])
            # Panels on one pole share its position: keep each pole once, in order.
            piece_poles = list(dict.fromkeys(sign_poles[s] for s in piece.sign_ids))
            rows.append(
                {
                    "segment_id": int(network.segment_ids[seg]),
                    "street": network.names[seg],
                    "side": side,
                    "start_m": piece.start_m,
                    "end_m": piece.end_m,
                    "length_m": piece.end_m - piece.start_m,
                    "longitudes": lons,
                    "latitudes": lats,
                    "min_lon": min(lons),
                    "min_lat": min(lats),
                    "max_lon": max(lons),
                    "max_lat": max(lats),
                    "code_ids": list(piece.code_ids),
                    "inferred_code_ids": inferred_codes,
                    "is_inferred": len(inferred_codes) == len(piece.code_ids),
                    "sign_ids": list(piece.sign_ids),
                    "pole_longitudes": [lon for lon, _ in piece_poles],
                    "pole_latitudes": [lat for _, lat in piece_poles],
                    "rules": [{**rules[c], "inferred": c in inferred} for c in piece.code_ids],
                }
            )

    strips = (
        pl.DataFrame(rows, schema={k: v for k, v in STRIP_SCHEMA.items() if k != "strip_id"})
        .sort("segment_id", "side", "start_m")
        .with_row_index("strip_id")
        .cast(STRIP_SCHEMA)
    )
    report = StripReport(
        panels=arrowed_panels,
        panels_snapped=arrowed_snapped,
        inferred_panels=inferred_panels,
        poles=pole_count,
        poles_ambiguous=int(poles["ambiguous"].sum()),
        strips=strips.height,
        total_km=float(strips["length_m"].sum()) / 1000.0,
        inferred_km=float(strips.filter(pl.col("is_inferred"))["length_m"].sum()) / 1000.0,
    )
    return strips, report


def _curb_line(
    line: shapely.LineString, piece: Piece, side: int, offset_m: float
) -> tuple[list[float], list[float]]:
    """The piece's stretch of centreline, shifted onto the parking lane.

    Args:
        line: Segment centreline (local metres).
        piece: Stretch along it.
        side: +1 left, -1 right of the segment's direction.
        offset_m: Distance from the centreline.

    Returns:
        ``(longitudes, latitudes)`` of the curb polyline, in the segment's direction.
    """
    centre = substring(line, piece.start_m, piece.end_m)
    # Positive offsets go left; shapely >= 2 keeps the input direction on both sides.
    curb = shapely.offset_curve(centre, side * offset_m)
    if curb.geom_type == "MultiLineString":
        # Tight bends can split the offset; keep the main part.
        curb = max(curb.geoms, key=lambda g: g.length)
    if curb.is_empty or curb.geom_type != "LineString":
        curb = centre
    xy = shapely.get_coordinates(curb)
    lon, lat = to_lonlat(xy[:, 0], xy[:, 1])
    return (
        np.round(lon, _COORD_DECIMALS).tolist(),
        np.round(lat, _COORD_DECIMALS).tolist(),
    )
