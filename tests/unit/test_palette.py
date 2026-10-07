import polars as pl
import pytest

from mtl_park_map.enums import SignCategory
from mtl_park_map.models import SignQuery, SpotQuery, TimeWindow
from mtl_park_map.store import Store
from mtl_park_map.ui.palette import LAYER_SPECS, build_layers


@pytest.fixture
def results(store: Store) -> tuple[pl.DataFrame, pl.DataFrame]:
    signs = store.query_signs(SignQuery(categories=frozenset(SignCategory)))
    spots = store.query_spots(SpotQuery(TimeWindow(hour=(10.0, 11.0), day=(1, 1))))
    return signs, spots


def test_layers_split_by_category_and_status_spots_below_signs(
    results: tuple[pl.DataFrame, pl.DataFrame],
):
    layers = build_layers(*results)
    names = [dl.spec.name for dl in layers]
    # empty layers (no "other" signs in the fixture) are skipped
    assert names == ["spots-paid", "spots-free", "signs-prohibited", "signs-permitted"]
    by_name = {dl.spec.name: dl for dl in layers}
    assert by_name["signs-permitted"].frame["sign_id"].to_list() == [0, 1, 3]
    assert by_name["spots-free"].frame["place_id"].to_list() == ["S2", "S3"]
    # marker layers index into exactly the same rows as the frames
    assert all(len(dl.marker_layer) == dl.frame.height for dl in layers)
    assert all(dl.marker_layer.name == dl.spec.name for dl in layers)


def test_missing_results_produce_no_layers(results: tuple[pl.DataFrame, pl.DataFrame]):
    signs, _ = results
    assert [dl.spec.kind for dl in build_layers(signs, None)] == ["sign", "sign"]
    assert build_layers(None, None) == []


def test_specs_are_unique_and_colored():
    names = [s.name for s in LAYER_SPECS]
    assert len(names) == len(set(names))
    assert all(s.color.startswith("#") and len(s.color) == 7 for s in LAYER_SPECS)
