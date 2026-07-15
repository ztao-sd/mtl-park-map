from pydantic import BaseModel


class Point(BaseModel):
    longitude: float
    latitude: float


class ParkingSign(Point):
    description: str


class ParkingSpot(Point):
    description: str
    is_currently_free: bool


class BoundingBox(BaseModel):
    min_lon: float
    max_lon: float
    min_lat: float
    max_lat: float


class ParkingRegulationFilter(BoundingBox):
    include_parking_sign: bool
    include_reserved_parking_sign: bool
    include_parking_spot: bool
    not_in_hour_range: bool
    hour_range: tuple[float, float]
    day_of_week: int
    month: int

