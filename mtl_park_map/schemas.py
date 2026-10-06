from typing import Literal

from pydantic import BaseModel

from mtl_park_map.enums import SignCategory
from mtl_park_map.query.intervals import Range

BBox = tuple[float, float, float, float]


class _BBoxParams(BaseModel):
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def bbox(self) -> BBox:
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)


class _TimeParams(BaseModel):
    hour_start: float | None = None
    hour_end: float | None = None
    day_start: int | None = None
    day_end: int | None = None
    month_start: int | None = None
    month_end: int | None = None

    def hour_range(self) -> Range | None:
        if self.hour_start is not None and self.hour_end is not None:
            return (self.hour_start, self.hour_end)
        return None

    def day_range(self) -> Range | None:
        if self.day_start is not None and self.day_end is not None:
            return (self.day_start, self.day_end)
        return None

    def month_range(self) -> Range | None:
        if self.month_start is not None and self.month_end is not None:
            return (self.month_start, self.month_end)
        return None


class SignQuery(_BBoxParams, _TimeParams):
    categories: list[SignCategory] = [SignCategory.permitted]
    reserved: bool | None = None  # None = all, True = only reserved, False = exclude
    not_in_range: bool = False


class SpotQuery(_BBoxParams, _TimeParams):
    pass


# --- GeoJSON response models (used for the OpenAPI schema orval consumes) ---


class PointGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: list[float]


class SignProperties(BaseModel):
    sign_id: int
    category: SignCategory
    is_reserved: bool
    arrondissement: str | None = None
    description: str


class SignFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: SignProperties


class SignCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SignFeature]


class SpotProperties(BaseModel):
    place_id: str
    is_currently_free: bool
    tariff_hourly: float | None = None
    spot_type: str | None = None
    street: str | None = None
    periods: list[str] = []


class SpotFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: SpotProperties


class SpotCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SpotFeature]


class AddressLocation(BaseModel):
    latitude: float
    longitude: float
