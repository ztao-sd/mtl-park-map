"""Synthetic street geometry for ETL tests, laid out in metres around ORIGIN."""

import numpy as np

from mtl_park_map.etl.geometry import to_local, to_lonlat
from mtl_park_map.etl.streets import GeobaseFeature

ORIGIN = (-73.60, 45.50)


def lonlat(x_m: float, y_m: float) -> tuple[float, float]:
    """Degrees of the point ``x_m`` east / ``y_m`` north of ORIGIN."""
    ox, oy = to_local(np.array([ORIGIN[0]]), np.array([ORIGIN[1]]))
    lon, lat = to_lonlat(ox + x_m, oy + y_m)
    return float(lon[0]), float(lat[0])


def feature(
    segment_id: int, name: str, *pts_m: tuple[float, float], classe: int = 0, position: int = 5
) -> GeobaseFeature:
    """A Géobase-like feature through points given in metres from ORIGIN."""
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [list(lonlat(*p)) for p in pts_m]},
        "properties": {"ID_TRC": segment_id, "ODONYME": f"{name} ", "CLASSE": classe, "POSITION": position},
    }
