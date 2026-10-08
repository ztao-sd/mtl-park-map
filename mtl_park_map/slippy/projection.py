"""Spherical Web-Mercator (EPSG:3857) math, as used by OSM slippy-map tiles.

"World" coordinates are normalized to ``[0, 1]`` on both axes: ``(0, 0)`` is the
north-west corner of the world, ``(1, 1)`` the south-east. At integer zoom ``z`` the
world is ``TILE_SIZE * 2**z`` pixels wide, and tile ``(x, y)`` covers world
``[x / 2**z, (x + 1) / 2**z)`` horizontally (likewise vertically).
"""

import math

import polars as pl

TILE_SIZE = 256
# Latitude at which Web-Mercator's square world ends (atan(sinh(pi))).
MAX_LATITUDE = 85.0511287798066

_FOUR_PI = 4.0 * math.pi


def world_size(zoom: int) -> float:
    """Width (and height) of the whole world in pixels at ``zoom``.

    Args:
        zoom: Integer zoom level.

    Returns:
        ``TILE_SIZE * 2**zoom``.
    """
    return float(TILE_SIZE * 2**zoom)


def lonlat_to_world(lon: float, lat: float) -> tuple[float, float]:
    """Project a WGS84 coordinate to normalized world coordinates.

    Args:
        lon: Longitude in degrees.
        lat: Latitude in degrees; clamped to ``±MAX_LATITUDE``.

    Returns:
        ``(x, y)`` in ``[0, 1]``.
    """
    lat = max(-MAX_LATITUDE, min(MAX_LATITUDE, lat))
    s = math.sin(math.radians(lat))
    return (lon + 180.0) / 360.0, 0.5 - math.log((1.0 + s) / (1.0 - s)) / _FOUR_PI


def world_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Inverse of :func:`lonlat_to_world`.

    Args:
        x: Normalized world x.
        y: Normalized world y.

    Returns:
        ``(lon, lat)`` in degrees.
    """
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y))))
    return x * 360.0 - 180.0, lat


def world_x(lon: pl.Expr) -> pl.Expr:
    """Vectorized longitude → normalized world x.

    Args:
        lon: Longitude expression in degrees.

    Returns:
        The world-x expression.
    """
    return (lon + 180.0) / 360.0


def world_y(lat: pl.Expr) -> pl.Expr:
    """Vectorized latitude → normalized world y.

    Args:
        lat: Latitude expression in degrees.

    Returns:
        The world-y expression.
    """
    s = lat.clip(-MAX_LATITUDE, MAX_LATITUDE).radians().sin()
    return 0.5 - ((1.0 + s) / (1.0 - s)).log() / _FOUR_PI
