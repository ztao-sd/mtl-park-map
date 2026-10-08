"""The city's Géobase road network: street centrelines split at intersections.

Source: https://donnees.montreal.ca/dataset/geobase (``geobase.json``). Each feature is
one *tronçon* (block-long segment) with a stable ``ID_TRC``; "left"/"right" in Géobase
(e.g. ``DEB_GCH`` / ``DEB_DRT``) are relative to the segment's digitized direction,
which is also the convention used for ``side`` here.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
import numpy.typing as npt
import shapely

from mtl_park_map.etl.geometry import to_local

# Géobase CLASSE codes that can carry curb signage: 0 local streets, 2 business
# squares, 4 private, 5 collectors, 6 secondary and 7 main arteries. Excluded:
# 1 pedestrian ways, 3 quays, 8 highways, 9 projected (not built) streets.
STREET_CLASSES = frozenset({0, 2, 4, 5, 6, 7})
# Géobase POSITION codes kept: 5 at ground level, 6 underpasses. Bridges/viaducts
# (1-4) and tunnels (7-9) are dropped so poles under an overpass don't snap to it.
STREET_POSITIONS = frozenset({5, 6})


class _Geometry(TypedDict):
    """GeoJSON LineString geometry."""

    type: str
    coordinates: list[list[float]]


class _Properties(TypedDict):
    """The Géobase attributes used here."""

    ID_TRC: int
    ODONYME: str
    CLASSE: int
    POSITION: int


class GeobaseFeature(TypedDict):
    """One Géobase GeoJSON feature."""

    type: str
    geometry: _Geometry
    properties: _Properties


@dataclass(frozen=True, slots=True, eq=False)
class StreetNetwork:
    """Street segments in local metres, with a spatial index.

    Attributes:
        segment_ids: Géobase ``ID_TRC`` per segment.
        names: Street name (``ODONYME``) per segment.
        lines: Shapely ``LineString`` per segment, in local metres.
        lengths: Segment lengths in metres.
        tree: R-tree over ``lines``.
    """

    segment_ids: npt.NDArray[np.int64]
    names: list[str]
    lines: npt.NDArray[np.object_]
    lengths: npt.NDArray[np.float64]
    tree: shapely.STRtree

    @classmethod
    def from_features(cls, features: Sequence[GeobaseFeature]) -> "StreetNetwork":
        """Build the network from Géobase features, keeping street-level roads.

        Args:
            features: Géobase GeoJSON features.

        Returns:
            The network.

        Raises:
            ValueError: If no feature passes the class/position filter.
        """
        kept = [
            f
            for f in features
            if f["properties"]["CLASSE"] in STREET_CLASSES
            and f["properties"]["POSITION"] in STREET_POSITIONS
            and len(f["geometry"]["coordinates"]) >= 2
        ]
        if not kept:
            raise ValueError("no street segment in the Géobase input")
        coords = [np.asarray(f["geometry"]["coordinates"], dtype=np.float64)[:, :2] for f in kept]
        flat = np.concatenate(coords)
        x, y = to_local(flat[:, 0], flat[:, 1])
        # One flat coordinate array + per-vertex line index: shapely's vectorized
        # constructor needs this for lines of different vertex counts.
        indices = np.repeat(np.arange(len(coords)), [len(c) for c in coords])
        lines = shapely.linestrings(np.column_stack([x, y]), indices=indices)
        return cls(
            segment_ids=np.array([f["properties"]["ID_TRC"] for f in kept], dtype=np.int64),
            names=[f["properties"]["ODONYME"].strip() for f in kept],
            lines=lines,
            lengths=shapely.length(lines),
            tree=shapely.STRtree(lines),
        )

    def index_of(self, segment_id: int) -> int:
        """Position of a segment in the arrays.

        Args:
            segment_id: Géobase ``ID_TRC``.

        Returns:
            Its index.

        Raises:
            KeyError: If the segment is not in the network.
        """
        matches = np.flatnonzero(self.segment_ids == segment_id)
        if matches.size == 0:
            raise KeyError(segment_id)
        return int(matches[0])


def load_streets(path: Path) -> StreetNetwork:
    """Load the Géobase GeoJSON file.

    Args:
        path: ``geobase.json``.

    Returns:
        The street network.
    """
    with path.open(encoding="utf-8") as fh:
        features = cast(list[GeobaseFeature], json.load(fh)["features"])
    return StreetNetwork.from_features(features)
