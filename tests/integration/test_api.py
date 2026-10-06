import polars as pl
import pytest
from fastapi.testclient import TestClient

from mtl_park_map.main import create_app
from mtl_park_map.store import Store

_HOUR = pl.List(pl.Struct({"start": pl.Float64, "end": pl.Float64}))
_INT = pl.List(pl.Struct({"start": pl.Int64, "end": pl.Int64}))
_CODES_SCHEMA = {
    "code_id": pl.UInt32,
    "code_rpa": pl.Utf8,
    "description": pl.Utf8,
    "category": pl.Utf8,
    "is_reserved": pl.Boolean,
    "hour_ranges": _HOUR,
    "day_ranges": _INT,
    "month_ranges": _INT,
}
_SIGNS_SCHEMA = {
    "sign_id": pl.UInt32,
    "longitude": pl.Float64,
    "latitude": pl.Float64,
    "arrondissement": pl.Utf8,
    "fleche": pl.Utf8,
    "code_id": pl.UInt32,
    "category": pl.Utf8,
    "is_reserved": pl.Boolean,
}
_PERIODS = pl.List(
    pl.Struct(
        {
            "start_hour": pl.Float64,
            "end_hour": pl.Float64,
            "weekday_mask": pl.Int64,
            "description": pl.Utf8,
        }
    )
)
_SPOTS_SCHEMA = {
    "place_id": pl.Utf8,
    "longitude": pl.Float64,
    "latitude": pl.Float64,
    "tariff_hourly": pl.Float64,
    "spot_type": pl.Utf8,
    "street": pl.Utf8,
    "periods": _PERIODS,
}

BBOX = {"min_lon": -73.57, "min_lat": 45.49, "max_lon": -73.55, "max_lat": 45.51}


@pytest.fixture
def client() -> TestClient:
    codes = pl.DataFrame(
        [
            {
                "code_id": 0,
                "code_rpa": "P1",
                "description": r"\P 9h-17h LUN A VEN",
                "category": "permitted",
                "is_reserved": False,
                "hour_ranges": [{"start": 9.0, "end": 17.0}],
                "day_ranges": [{"start": 1, "end": 5}],
                "month_ranges": [],
            },
            {
                "code_id": 1,
                "code_rpa": "P2",
                "description": r"\P RESERVE EN TOUT TEMPS",
                "category": "permitted",
                "is_reserved": True,
                "hour_ranges": [],
                "day_ranges": [],
                "month_ranges": [],
            },
            {
                "code_id": 2,
                "code_rpa": "A1",
                "description": r"\A EN TOUT TEMPS",
                "category": "prohibited",
                "is_reserved": False,
                "hour_ranges": [],
                "day_ranges": [],
                "month_ranges": [],
            },
        ],
        schema=_CODES_SCHEMA,
    )
    signs = pl.DataFrame(
        [
            {"sign_id": 0, "longitude": -73.560, "latitude": 45.500, "arrondissement": "A", "fleche": "0", "code_id": 0, "category": "permitted", "is_reserved": False},
            {"sign_id": 1, "longitude": -73.561, "latitude": 45.501, "arrondissement": "A", "fleche": "0", "code_id": 1, "category": "permitted", "is_reserved": True},
            {"sign_id": 2, "longitude": -73.562, "latitude": 45.502, "arrondissement": "A", "fleche": "0", "code_id": 2, "category": "prohibited", "is_reserved": False},
            {"sign_id": 3, "longitude": -70.000, "latitude": 40.000, "arrondissement": "B", "fleche": "0", "code_id": 0, "category": "permitted", "is_reserved": False},
        ],
        schema=_SIGNS_SCHEMA,
    )
    spots = pl.DataFrame(
        [
            {"place_id": "S1", "longitude": -73.560, "latitude": 45.500, "tariff_hourly": 300.0, "spot_type": "Normal", "street": "Rue X", "periods": [{"start_hour": 9.0, "end_hour": 18.0, "weekday_mask": 0b0011111, "description": "LUN-VEN 9-18"}]},
            {"place_id": "S2", "longitude": -73.561, "latitude": 45.501, "tariff_hourly": None, "spot_type": "Normal", "street": "Rue Y", "periods": []},
        ],
        schema=_SPOTS_SCHEMA,
    )
    return TestClient(create_app(Store(signs, codes, spots)))


def _ids(payload: dict) -> set[int]:
    return {f["properties"]["sign_id"] for f in payload["features"]}


def test_bbox_excludes_far_signs(client: TestClient):
    r = client.get("/parking-signs", params={**BBOX, "categories": ["permitted", "prohibited"]})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert 3 not in _ids(body)


def test_default_categories_permitted_only(client: TestClient):
    r = client.get("/parking-signs", params=BBOX)
    cats = {f["properties"]["category"] for f in r.json()["features"]}
    assert cats <= {"permitted"}


def test_reserved_filter(client: TestClient):
    r = client.get("/parking-signs", params={**BBOX, "categories": ["permitted"], "reserved": True})
    assert _ids(r.json()) == {1}


def test_time_filter_hits_and_misses(client: TestClient):
    active = client.get("/parking-signs", params={**BBOX, "hour_start": 10, "hour_end": 11, "day_start": 1, "day_end": 5})
    ids = _ids(active.json())
    assert 0 in ids and 1 in ids  # 9-17 sign + always-on sign

    off = client.get("/parking-signs", params={**BBOX, "hour_start": 20, "hour_end": 21, "day_start": 1, "day_end": 5})
    ids_off = _ids(off.json())
    assert 0 not in ids_off and 1 in ids_off  # 9-17 sign inactive; always-on still on


def test_not_in_range_inverts(client: TestClient):
    r = client.get("/parking-signs", params={**BBOX, "hour_start": 20, "hour_end": 21, "day_start": 1, "day_end": 5, "not_in_range": True})
    ids = _ids(r.json())
    assert 0 in ids and 1 not in ids


def test_spots_free_and_paid(client: TestClient):
    r = client.get("/paid-spots", params={**BBOX, "hour_start": 10, "hour_end": 11, "day_start": 1, "day_end": 5})
    free = {f["properties"]["place_id"]: f["properties"]["is_currently_free"] for f in r.json()["features"]}
    assert free["S1"] is False  # metered 9-18 Mon-Fri
    assert free["S2"] is True  # no periods
