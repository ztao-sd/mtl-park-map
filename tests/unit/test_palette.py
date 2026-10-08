import polars as pl
import pytest

from mtl_park_map.enums import SignCategory
from mtl_park_map.models import SignQuery, SpotQuery, StripQuery, TimeWindow
from mtl_park_map.slippy.layers import MarkerLayer
from mtl_park_map.slippy.lines import LineLayer
from mtl_park_map.store import Store
from mtl_park_map.ui.palette import LAYER_SPECS, build_layers

type Results = tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]


@pytest.fixture
def results(store: Store) -> Results:
    wednesday = TimeWindow(hour=(10.0, 11.0), day=(3, 3))
    signs = store.query_signs(SignQuery(categories=frozenset(SignCategory)))
    spots = store.query_spots(SpotQuery(TimeWindow(hour=(10.0, 11.0), day=(1, 1))))
    # Wednesday: only strip 1 restricted; strip 2 exists by inference alone
    strips = store.query_strips(StripQuery(wednesday))
    return signs, spots, strips


def test_layers_in_drawing_order_strips_lowest(results: Results):
    layers = build_layers(*results)
    names = [dl.spec.name for dl in layers]
    # empty layers (no "other" signs, no restricted inferred strip) are skipped;
    # inferred (dashed) strips are drawn under arrow-derived ones
    assert names == [
        "strips-parkable-inferred",
        "strips-parkable",
        "strips-restricted",
        "spots-paid",
        "spots-free",
        "signs-prohibited",
        "signs-permitted",
    ]
    by_name = {dl.spec.name: dl for dl in layers}
    assert by_name["signs-permitted"].frame["sign_id"].to_list() == [0, 1, 3]
    assert by_name["spots-free"].frame["place_id"].to_list() == ["S2", "S3"]
    assert by_name["strips-parkable"].frame["strip_id"].to_list() == [0]
    assert by_name["strips-parkable-inferred"].frame["strip_id"].to_list() == [2]
    assert by_name["strips-restricted"].frame["strip_id"].to_list() == [1]


def test_layer_geometry_types(results: Results):
    for dl in build_layers(*results):
        expected = LineLayer if dl.spec.kind == "strip" else MarkerLayer
        assert isinstance(dl.layer, expected)
        # map hits index into exactly the same rows as the frames
        assert len(dl.layer) == dl.frame.height
        assert dl.layer.name == dl.spec.name


def test_missing_results_produce_no_layers(results: Results):
    signs, _, _ = results
    assert [dl.spec.kind for dl in build_layers(signs, None, None)] == ["sign", "sign"]
    assert build_layers(None, None, None) == []


def test_specs_are_unique_and_colored():
    names = [s.name for s in LAYER_SPECS]
    assert len(names) == len(set(names))
    assert all(s.color.startswith("#") and len(s.color) == 7 for s in LAYER_SPECS)


def test_inferred_strips_are_dashed(results: Results):
    for dl in build_layers(*results):
        if isinstance(dl.layer, LineLayer):
            assert dl.layer.style.dashed == dl.spec.name.endswith("-inferred")
