import polars as pl
import pytest

from mtl_park_map.slippy.clustering import cluster_points
from mtl_park_map.slippy.projection import world_size

ZOOM = 12
PX = 1.0 / world_size(ZOOM)  # one screen pixel in world units at ZOOM
# Inside one 60 px grid cell at ZOOM (cell origin aligned to the world grid).
BASE = 1000 * 60 * PX + 10 * PX


def _points(*offsets_px: tuple[float, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "x": [BASE + dx * PX for dx, _ in offsets_px],
            "y": [BASE + dy * PX for _, dy in offsets_px],
        }
    )


def test_near_points_merge_into_one_cluster():
    out = cluster_points(_points((0, 0), (5, 5), (10, 0)), ZOOM, cell_px=60)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["count"] == 3
    assert row["idx"] == 0
    assert row["x"] == pytest.approx(BASE + 5 * PX)  # mean position


def test_far_points_stay_separate():
    out = cluster_points(_points((0, 0), (200, 0), (0, 200)), ZOOM, cell_px=60)
    assert out["count"].to_list() == [1, 1, 1]
    assert out["idx"].to_list() == [0, 1, 2]


def test_clustering_disabled_at_high_zoom():
    pts = _points((0, 0), (0.1, 0.1))
    out = cluster_points(pts, 17, cell_px=60, disable_at_zoom=17)
    assert out["count"].to_list() == [1, 1]
    assert out["x"].to_list() == pts["x"].to_list()


def test_empty_input():
    out = cluster_points(pl.DataFrame({"x": [], "y": []}, schema={"x": pl.Float64, "y": pl.Float64}), ZOOM)
    assert out.is_empty()
    assert out.columns == ["x", "y", "count", "idx"]


def test_output_is_deterministic_and_sorted_by_first_member():
    pts = _points(*[((i * 37) % 400, (i * 91) % 400) for i in range(200)])
    a = cluster_points(pts, ZOOM, cell_px=60)
    b = cluster_points(pts, ZOOM, cell_px=60)
    assert a.equals(b)
    assert a["idx"].is_sorted()
    assert a["count"].sum() == 200
