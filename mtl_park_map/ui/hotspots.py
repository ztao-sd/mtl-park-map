"""Saved places ("hotspots") to jump back to, and their JSON form for QSettings."""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Hotspot:
    """A named map location.

    Attributes:
        name: What the user searched for (shown in the list); unique, ignoring case.
        lon: Longitude.
        lat: Latitude.
    """

    name: str
    lon: float
    lat: float


def _number(value: object) -> float | None:
    """A finite JSON number as float (bools, which are ints in Python, excluded).

    Args:
        value: A decoded JSON value.

    Returns:
        The number, or ``None``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _parse(item: object) -> Hotspot | None:
    """A hotspot from a decoded JSON object, or ``None`` if it is malformed.

    Args:
        item: A decoded JSON value.

    Returns:
        The hotspot, or ``None``.
    """
    if not isinstance(item, dict):
        return None
    name, lon, lat = item.get("name"), _number(item.get("lon")), _number(item.get("lat"))
    if not isinstance(name, str) or not name or lon is None or lat is None:
        return None
    return Hotspot(name, lon, lat)


def _loads(raw: str) -> object:
    """Decode JSON, treating anything undecodable as ``None``."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def hotspot_to_json(hotspot: Hotspot | None) -> str:
    """Encode one (optional) hotspot.

    Args:
        hotspot: The hotspot, or ``None``.

    Returns:
        JSON text.
    """
    if hotspot is None:
        return "null"
    return json.dumps({"name": hotspot.name, "lon": hotspot.lon, "lat": hotspot.lat})


def hotspot_from_json(raw: str) -> Hotspot | None:
    """Decode :func:`hotspot_to_json` output (``None`` when missing or malformed).

    Args:
        raw: JSON text.

    Returns:
        The hotspot, or ``None``.
    """
    return _parse(_loads(raw))


def hotspots_to_json(hotspots: Sequence[Hotspot]) -> str:
    """Encode a list of hotspots.

    Args:
        hotspots: The hotspots, in display order.

    Returns:
        JSON text.
    """
    return json.dumps([{"name": h.name, "lon": h.lon, "lat": h.lat} for h in hotspots])


def hotspots_from_json(raw: str) -> list[Hotspot]:
    """Decode :func:`hotspots_to_json` output, skipping malformed entries.

    Args:
        raw: JSON text (possibly empty or corrupt).

    Returns:
        The valid hotspots, in order.
    """
    decoded = _loads(raw)
    if not isinstance(decoded, list):
        return []
    return [h for h in (_parse(item) for item in decoded) if h is not None]


def add_hotspot(hotspots: Sequence[Hotspot], hotspot: Hotspot) -> list[Hotspot]:
    """Add a hotspot, replacing one with the same name (ignoring case) in place.

    Args:
        hotspots: Current list.
        hotspot: The one to add.

    Returns:
        The new list.
    """
    key = hotspot.name.casefold()
    if any(h.name.casefold() == key for h in hotspots):
        return [hotspot if h.name.casefold() == key else h for h in hotspots]
    return [*hotspots, hotspot]


def remove_hotspot(hotspots: Sequence[Hotspot], hotspot: Hotspot) -> list[Hotspot]:
    """Remove a hotspot.

    Args:
        hotspots: Current list.
        hotspot: The one to remove.

    Returns:
        The new list.
    """
    return [h for h in hotspots if h != hotspot]
