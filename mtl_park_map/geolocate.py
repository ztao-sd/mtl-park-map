"""Address geocoding via Nominatim (ported from the prototype's lib/geolocate.py)."""

from geopy.geocoders import Nominatim

_geolocator = Nominatim(user_agent="MTLParkMap")


def locate_address(address: str) -> tuple[float, float] | None:
    location = _geolocator.geocode(address)
    if location is None:
        return None
    return location.latitude, location.longitude
