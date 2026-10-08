"""Local metric projection for Montreal-scale geometry work in the ETL.

A plain equirectangular projection around Montreal's latitude: x = metres east, y =
metres north. Across the island (45.41°–45.70° N) its scale error stays under 0.3%,
far below the sign inventory's positional accuracy, and it needs no projection
library. Distances, offsets and lengths computed in it are in metres.
"""

import math

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]

_LAT0 = 45.55  # reference latitude: middle of the island
_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = _M_PER_DEG_LAT * math.cos(math.radians(_LAT0))


def to_local(lon: FloatArray, lat: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Degrees → local metres.

    Args:
        lon: Longitudes in degrees.
        lat: Latitudes in degrees.

    Returns:
        ``(x, y)`` in metres.
    """
    return np.asarray(lon) * _M_PER_DEG_LON, np.asarray(lat) * _M_PER_DEG_LAT


def to_lonlat(x: FloatArray, y: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Local metres → degrees (inverse of :func:`to_local`).

    Args:
        x: Metres east.
        y: Metres north.

    Returns:
        ``(lon, lat)`` in degrees.
    """
    return np.asarray(x) / _M_PER_DEG_LON, np.asarray(y) / _M_PER_DEG_LAT
