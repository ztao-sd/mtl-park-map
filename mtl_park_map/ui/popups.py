"""Popup content for clicked markers (Qt rich text; all data is HTML-escaped)."""

from html import escape
from typing import TypedDict

_MUTED = "color:#6b7280"


class SignRow(TypedDict):
    """One row of :meth:`mtl_park_map.store.Store.query_signs`."""

    sign_id: int
    longitude: float
    latitude: float
    category: str
    is_reserved: bool
    arrondissement: str | None
    description: str


class SpotRow(TypedDict):
    """One row of :meth:`mtl_park_map.store.Store.query_spots`."""

    place_id: str
    longitude: float
    latitude: float
    is_free: bool
    tariff_hourly: float | None
    spot_type: str | None
    street: str | None
    periods: list[str]


def sign_popup_html(row: SignRow) -> str:
    """Popup for a parking sign.

    Args:
        row: The sign.

    Returns:
        Rich text: category (and reserved flag), raw sign text, borough.
    """
    title = f"<b>{escape(row['category'].capitalize())} sign</b>"
    if row["is_reserved"]:
        title += " · Reserved"
    parts = [title, escape(row["description"])]
    if row["arrondissement"]:
        parts.append(f"<span style='{_MUTED}'>{escape(row['arrondissement'])}</span>")
    return "<br>".join(parts)


def spot_popup_html(row: SpotRow, evaluated: bool) -> str:
    """Popup for a paid spot.

    Args:
        row: The spot.
        evaluated: Whether ``is_free`` reflects a complete hour + day window; if not,
            no free/paid status is claimed.

    Returns:
        Rich text: status, street, tariff, metered periods, spot id.
    """
    if evaluated:
        status = "Free" if row["is_free"] else "Paid"
        title = f"<b>{status}</b> at the selected time"
    else:
        title = "<b>Paid spot</b>"
    details = [escape(v) for v in (row["street"], row["spot_type"]) if v]
    if row["tariff_hourly"] is not None:
        # The source data gives the hourly rate in cents.
        details.append(f"${row['tariff_hourly'] / 100:.2f}/h")
    parts = [title]
    if details:
        parts.append(" · ".join(details))
    if row["periods"]:
        periods = "<br>".join(escape(p) for p in row["periods"])
        parts.append(f"<span style='{_MUTED}'>Metered:</span><br>{periods}")
    parts.append(f"<span style='{_MUTED}'>Spot {escape(row['place_id'])}</span>")
    return "<br>".join(parts)
