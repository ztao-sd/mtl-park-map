"""Popup content for clicked map features (Qt rich text; all data is HTML-escaped)."""

from html import escape
from typing import TypedDict

_MUTED = "color:#6b7280"

# FLECHE_PAN code → how the arrow is drawn on the panel.
_ARROWS = {"2": "← left", "3": "→ right", "8": "↔ both ways"}
_NO_ARROW = "0"
_COMPASS = (
    "north",
    "north-east",
    "east",
    "south-east",
    "south",
    "south-west",
    "west",
    "north-west",
)


def compass_name(bearing: float) -> str:
    """The nearest of the 8 compass points.

    Args:
        bearing: Degrees clockwise from north.

    Returns:
        E.g. ``"north-west"``.
    """
    return _COMPASS[round((bearing % 360.0) / 45.0) % 8]


class SignRow(TypedDict):
    """One row of :meth:`mtl_park_map.store.Store.query_signs`."""

    sign_id: int
    longitude: float
    latitude: float
    category: str
    is_reserved: bool
    arrondissement: str | None
    description: str
    fleche: str | None
    arrow_street: str | None
    arrow_bearing: float | None


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
        Rich text: category (and reserved flag), raw sign text, its arrow, borough.
    """
    title = f"<b>{escape(row['category'].capitalize())} sign</b>"
    if row["is_reserved"]:
        title += " · Reserved"
    parts = [title, escape(row["description"]), _arrow_html(row)]
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


class _Range(TypedDict):
    """One ``{start, end}`` range of a parsed rule."""

    start: float
    end: float


class RuleRow(TypedDict):
    """One no-parking rule of a strip (see ``strips.parquet``)."""

    code_id: int
    description: str
    hour_ranges: list[_Range]
    day_ranges: list[_Range]
    month_ranges: list[_Range]
    inferred: bool


class StripRow(TypedDict):
    """One row of :meth:`mtl_park_map.store.Store.query_strips`."""

    strip_id: int
    street: str
    side: int
    length_m: float
    longitudes: list[float]
    latitudes: list[float]
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    pole_longitudes: list[float]
    pole_latitudes: list[float]
    rules: list[RuleRow]
    active_code_ids: list[int]
    is_restricted: bool
    is_inferred: bool


def strip_popup_html(row: StripRow) -> str:
    """Popup for a no-parking curb strip.

    Args:
        row: The strip, evaluated for the selected time window.

    Returns:
        Rich text: status, street and length, the strip's rules (those in force
        during the window in bold), and what the status is based on.
    """
    status = "No parking" if row["is_restricted"] else "Parking OK"
    active = set(row["active_code_ids"])
    rules = "<br>".join(_rule_html(r, r["code_id"] in active) for r in row["rules"])
    parts = [
        f"<b>{status}</b> at the selected time",
        f"{escape(row['street'])} · ~{row['length_m']:.0f} m of curb",
        f"<span style='{_MUTED}'>Rules:</span><br>{rules}",
    ]
    if row["is_inferred"]:
        parts.append(
            f"<span style='{_MUTED}'>Extent inferred from no-parking signs without "
            "arrows: the stretch their signs span, plus 10 m.</span>"
        )
    parts.append(
        f"<span style='{_MUTED}'>From no-parking signs only; other restrictions "
        "(no stopping, hydrants, permits) may also apply.</span>"
    )
    return "<br>".join(parts)


def _rule_html(rule: RuleRow, active: bool) -> str:
    """One rule line: bold when in force during the window, flagged when inferred.

    Args:
        rule: The rule.
        active: Whether it applies during the selected window.

    Returns:
        Rich text.
    """
    text = escape(rule["description"])
    if active:
        text = f"<b>{text}</b>"
    if rule["inferred"]:
        text += " <i>(extent inferred)</i>"
    return text


def _arrow_html(row: SignRow) -> str:
    """The sign's arrow as drawn, and where it points on the map when known.

    Args:
        row: The sign.

    Returns:
        One rich-text line.
    """
    fleche = row["fleche"]
    if fleche is None or fleche == _NO_ARROW:
        return f"<span style='{_MUTED}'>No arrow</span>"
    drawn = _ARROWS.get(fleche)
    if drawn is None:
        return f"<span style='{_MUTED}'>Unrecognised arrow code {escape(fleche)}</span>"
    text = f"Arrow: {drawn}"
    bearing, street = row["arrow_bearing"], row["arrow_street"]
    if bearing is not None and street:
        if fleche == "8":
            where = f"{compass_name(bearing)} and {compass_name(bearing + 180.0)}"
        else:
            where = f"points {compass_name(bearing)}"
        text += f" · {where} along {escape(street)}"
    return text
