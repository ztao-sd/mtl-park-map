"""Marker layers for query results: which rows go in which colour, in what order."""

from dataclasses import dataclass
from typing import Literal

import polars as pl

from mtl_park_map.enums import SignCategory
from mtl_park_map.slippy.layers import MarkerLayer, MarkerStyle

type LayerKind = Literal["sign", "spot"]


@dataclass(frozen=True, slots=True, eq=False)
class LayerSpec:
    """One visual class of markers.

    Attributes:
        name: Unique layer name (reported by map clicks).
        kind: Whether rows are signs or spots (selects the popup).
        label: Legend text.
        color: Marker colour ``#rrggbb``.
        predicate: Selects this layer's rows from the query result.
    """

    name: str
    kind: LayerKind
    label: str
    color: str
    predicate: pl.Expr


# Bottom to top: spots under signs (as in the web app), the most useful (permitted)
# signs on top.
LAYER_SPECS: tuple[LayerSpec, ...] = (
    LayerSpec("spots-paid", "spot", "Paid spot — paid", "#f59e0b", ~pl.col("is_free")),
    LayerSpec("spots-free", "spot", "Paid spot — free", "#16a34a", pl.col("is_free")),
    LayerSpec(
        "signs-other",
        "sign",
        "Other sign",
        "#9ca3af",
        pl.col("category") == SignCategory.other.value,
    ),
    LayerSpec(
        "signs-prohibited",
        "sign",
        "No-parking sign",
        "#dc2626",
        pl.col("category") == SignCategory.prohibited.value,
    ),
    LayerSpec(
        "signs-permitted",
        "sign",
        "Parking-permitted sign",
        "#2563eb",
        pl.col("category") == SignCategory.permitted.value,
    ),
)


@dataclass(frozen=True, slots=True, eq=False)
class DataLayer:
    """A marker layer together with the rows it was built from.

    Attributes:
        spec: The visual class.
        frame: The layer's rows; ``marker_layer`` hit indices index into it.
        marker_layer: What the map draws.
    """

    spec: LayerSpec
    frame: pl.DataFrame
    marker_layer: MarkerLayer


def build_layers(signs: pl.DataFrame | None, spots: pl.DataFrame | None) -> list[DataLayer]:
    """Split query results into coloured marker layers, bottom to top.

    Pure polars (no Qt), so it can run on a worker thread.

    Args:
        signs: :meth:`~mtl_park_map.store.Store.query_signs` result, or ``None`` when
            signs are hidden.
        spots: :meth:`~mtl_park_map.store.Store.query_spots` result, or ``None``.

    Returns:
        Non-empty layers in drawing order.
    """
    sources: dict[LayerKind, pl.DataFrame | None] = {"sign": signs, "spot": spots}
    layers: list[DataLayer] = []
    for spec in LAYER_SPECS:
        source = sources[spec.kind]
        if source is None:
            continue
        frame = source.filter(spec.predicate)
        if frame.is_empty():
            continue
        marker_layer = MarkerLayer(spec.name, MarkerStyle(spec.color), frame)
        layers.append(DataLayer(spec, frame, marker_layer))
    return layers
