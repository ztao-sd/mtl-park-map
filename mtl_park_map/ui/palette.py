"""Map layers for query results: which rows go in which colour, in what order."""

from dataclasses import dataclass
from typing import Literal

import polars as pl

from mtl_park_map.enums import SignCategory
from mtl_park_map.slippy.layers import MarkerLayer, MarkerStyle
from mtl_park_map.slippy.lines import LineLayer, LineStyle
from mtl_park_map.slippy.map_widget import MapLayer

type LayerKind = Literal["sign", "spot", "strip"]

_STRIP_WIDTH_PX = 5.0
# Curb strips are street-level detail; zoomed further out they would be a smear.
STRIP_MIN_ZOOM = 15


@dataclass(frozen=True, slots=True, eq=False)
class LayerSpec:
    """One visual class of map features.

    Attributes:
        name: Unique layer name (reported by map clicks).
        kind: Whether rows are signs, spots or curb strips (selects geometry and
            popup).
        label: Legend text.
        color: Fill / stroke colour ``#rrggbb``.
        predicate: Selects this layer's rows from the query result.
        dashed: Draw lines dashed (curb strips whose extent was inferred).
    """

    name: str
    kind: LayerKind
    label: str
    color: str
    predicate: pl.Expr
    dashed: bool = False


_PARKABLE, _RESTRICTED = "#16a34a", "#dc2626"

# Bottom to top: curb strips under everything (inferred, dashed ones under those
# derived from arrows), then spots, then signs; the sparse permitted signs (~7k)
# above the dense no-parking ones (~110k) so they are never buried.
LAYER_SPECS: tuple[LayerSpec, ...] = (
    LayerSpec(
        "strips-parkable-inferred",
        "strip",
        "Curb — parking OK (extent inferred)",
        _PARKABLE,
        ~pl.col("is_restricted") & pl.col("is_inferred"),
        dashed=True,
    ),
    LayerSpec(
        "strips-restricted-inferred",
        "strip",
        "Curb — no parking (extent inferred)",
        _RESTRICTED,
        pl.col("is_restricted") & pl.col("is_inferred"),
        dashed=True,
    ),
    LayerSpec(
        "strips-parkable",
        "strip",
        "Curb — parking OK at the selected time",
        _PARKABLE,
        ~pl.col("is_restricted") & ~pl.col("is_inferred"),
    ),
    LayerSpec(
        "strips-restricted",
        "strip",
        "Curb — no parking at the selected time",
        _RESTRICTED,
        pl.col("is_restricted") & ~pl.col("is_inferred"),
    ),
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
        "No-parking / no-stopping sign",
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
    """A map layer together with the rows it was built from.

    Attributes:
        spec: The visual class.
        frame: The layer's rows; ``layer`` hit indices index into it.
        layer: What the map draws.
    """

    spec: LayerSpec
    frame: pl.DataFrame
    layer: MapLayer


def _make_layer(spec: LayerSpec, frame: pl.DataFrame) -> MapLayer:
    """The map layer drawing ``frame`` in ``spec``'s style.

    Args:
        spec: The visual class.
        frame: Its rows.

    Returns:
        A line layer for curb strips, a marker layer otherwise.
    """
    if spec.kind == "strip":
        style = LineStyle(spec.color, _STRIP_WIDTH_PX, dashed=spec.dashed)
        return LineLayer(spec.name, style, frame, STRIP_MIN_ZOOM)
    return MarkerLayer(spec.name, MarkerStyle(spec.color), frame)


def build_layers(
    signs: pl.DataFrame | None,
    spots: pl.DataFrame | None,
    strips: pl.DataFrame | None,
) -> list[DataLayer]:
    """Split query results into coloured map layers, bottom to top.

    Pure polars (no Qt), so it can run on a worker thread.

    Args:
        signs: :meth:`~mtl_park_map.store.Store.query_signs` result, or ``None`` when
            signs are hidden.
        spots: :meth:`~mtl_park_map.store.Store.query_spots` result, or ``None``.
        strips: :meth:`~mtl_park_map.store.Store.query_strips` result, or ``None``.

    Returns:
        Non-empty layers in drawing order.
    """
    sources: dict[LayerKind, pl.DataFrame | None] = {
        "sign": signs,
        "spot": spots,
        "strip": strips,
    }
    layers: list[DataLayer] = []
    for spec in LAYER_SPECS:
        source = sources[spec.kind]
        if source is None:
            continue
        frame = source.filter(spec.predicate)
        if frame.is_empty():
            continue
        layers.append(DataLayer(spec, frame, _make_layer(spec, frame)))
    return layers
