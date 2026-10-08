import polars as pl
import pytest

from mtl_park_map.etl.arrows import (
    ARROW_SCHEMA,
    BACKWARD,
    BOTH,
    FORWARD,
    arrow_direction,
    sign_arrows,
)
from mtl_park_map.etl.streets import StreetNetwork
from tests.geo_helpers import feature, lonlat


@pytest.mark.parametrize(
    ("fleche", "side", "expected"),
    [
        # signs face the roadway: on the left side of the segment a right arrow ("3")
        # points along the segment's direction, on the right side against it
        ("3", 1, FORWARD),
        ("3", -1, BACKWARD),
        ("2", 1, BACKWARD),
        ("2", -1, FORWARD),
        ("8", 1, BOTH),
        ("8", -1, BOTH),
        ("0", 1, None),  # no arrow
        ("22", 1, None),  # undocumented codes
    ],
)
def test_arrow_direction(fleche: str, side: int, expected: int | None):
    assert arrow_direction(fleche, side) == expected


def _signs(*rows: tuple[int, int, float, float, str]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"sign_id": s, "pole_id": p, "longitude": lonlat(x, y)[0], "latitude": lonlat(x, y)[1], "fleche": f}
            for s, p, x, y, f in rows
        ],
        schema={"sign_id": pl.UInt32, "pole_id": pl.Int64, "longitude": pl.Float64,
                "latitude": pl.Float64, "fleche": pl.Utf8},
    )


@pytest.fixture
def network() -> StreetNetwork:
    # west -> east, then a block heading north
    return StreetNetwork.from_features(
        [feature(1, "Rue Test", (0, 0), (200, 0)), feature(2, "Avenue Nord", (300, 0), (300, 200))]
    )


def test_compass_bearing_of_arrows(network: StreetNetwork):
    arrows = sign_arrows(
        _signs(
            (0, 10, 50, 6, "3"),  # north side, right arrow -> forward -> east
            (1, 11, 50, -6, "3"),  # south side, right arrow -> backward -> west
            (2, 12, 120, 6, "2"),  # north side, left arrow -> west
            (3, 13, 150, -6, "8"),  # both ways: reported as the street's axis
            (4, 14, 294, 100, "3"),  # west of a northbound street: left side -> north
        ),
        network,
    )
    assert arrows.schema == ARROW_SCHEMA
    rows = {r["sign_id"]: r for r in arrows.iter_rows(named=True)}
    assert rows[0]["arrow_bearing"] == pytest.approx(90.0, abs=0.5)
    assert rows[1]["arrow_bearing"] == pytest.approx(270.0, abs=0.5)
    assert rows[2]["arrow_bearing"] == pytest.approx(270.0, abs=0.5)
    assert rows[3]["arrow_bearing"] == pytest.approx(90.0, abs=0.5)
    assert rows[4]["arrow_bearing"] == pytest.approx(0.0, abs=0.5)
    assert rows[0]["arrow_street"] == "Rue Test" and rows[4]["arrow_street"] == "Avenue Nord"


def test_signs_without_usable_arrow_or_street_are_left_out(network: StreetNetwork):
    arrows = sign_arrows(
        _signs(
            (0, 10, 50, 6, "0"),  # no arrow
            (1, 11, 50, 60, "3"),  # 60 m from any street
            (2, 12, 50, 6, "22"),  # undocumented arrow code
        ),
        network,
    )
    assert arrows.is_empty()
