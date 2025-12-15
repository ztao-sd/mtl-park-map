from geopy.geocoders import Nominatim

def locate_address(address: str) -> tuple[float, float] | None:
    geolocator = Nominatim(user_agent="MTLParkMap")
    location = geolocator.geocode(address)
    if location:
        return location.latitude, location.longitude
    return None

