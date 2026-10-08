"""Address geocoding via OpenStreetMap Nominatim, biased towards Montreal."""

from geopy.geocoders import Nominatim

from mtl_park_map import settings

_TIMEOUT_S = 10.0

_geolocator = Nominatim(user_agent=settings.USER_AGENT, timeout=_TIMEOUT_S)


def locate_address(address: str) -> tuple[float, float] | None:
    """Geocode a free-text address.

    Results are biased to (not restricted to) Montreal so short queries such as a
    street name resolve locally. Blocking network call: run it off the UI thread.
    Nominatim's usage policy allows at most one request per second, which is fine for
    user-initiated searches.

    Args:
        address: Free-text address, e.g. ``"845 Sherbrooke St W"``.

    Returns:
        ``(longitude, latitude)``, or ``None`` when nothing matches.

    Raises:
        geopy.exc.GeopyError: On network failure, timeout or service error.
    """
    min_lon, min_lat, max_lon, max_lat = settings.MTL_BOUNDS
    location = _geolocator.geocode(
        address,
        country_codes="ca",
        viewbox=((min_lat, min_lon), (max_lat, max_lon)),
    )
    if location is None:
        return None
    return location.longitude, location.latitude
