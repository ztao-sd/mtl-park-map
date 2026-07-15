from typing import Annotated

import orjson
from fastapi import APIRouter, HTTPException, Query, Response

from mtl_park_map.api.deps import StoreDep
from mtl_park_map.geolocate import locate_address
from mtl_park_map.schemas import (
    AddressLocation,
    SignCollection,
    SignQuery,
    SpotCollection,
    SpotQuery,
)

router = APIRouter()


def _geojson(data: dict) -> Response:
    # Serialize directly; the feature collection is already validated by construction,
    # so we skip per-feature response_model validation on potentially large payloads.
    return Response(content=orjson.dumps(data), media_type="application/json")


@router.get("/parking-signs", response_model=SignCollection, operation_id="parkingSigns")
def parking_signs(query: Annotated[SignQuery, Query()], store: StoreDep) -> Response:
    return _geojson(
        store.query_signs(
            query.bbox(),
            query.categories,
            query.reserved,
            query.hour_range(),
            query.day_range(),
            query.month_range(),
            query.not_in_range,
        )
    )


@router.get("/paid-spots", response_model=SpotCollection, operation_id="paidSpots")
def paid_spots(query: Annotated[SpotQuery, Query()], store: StoreDep) -> Response:
    return _geojson(
        store.query_spots(query.bbox(), query.hour_range(), query.day_range())
    )


@router.get(
    "/address-location", response_model=AddressLocation, operation_id="addressLocation"
)
def address_location(address: str) -> AddressLocation:
    location = locate_address(address)
    if location is None:
        raise HTTPException(status_code=404, detail="Address not found")
    latitude, longitude = location
    return AddressLocation(latitude=latitude, longitude=longitude)
