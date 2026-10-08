"""Pure parsing of Montreal parking-sign descriptions (``DESCRIPTION_RPA``).

Ported and cleaned from the QT prototype (``scripts/generate_curated_data.py`` and
``lib/parking_sign_query.py``). Each distinct sign *code* carries exactly one
description (verified: 1521 codes ↔ 1521 descriptions, 0 collisions), so these
functions run once per code at ETL time, never per request.
"""

import re
import unicodedata
from enum import IntEnum

from mtl_park_map.enums import (
    Day,
    DayAbbreviation,
    Month,
    MonthAbbreviation,
    SignCategory,
    SignKind,
)

_DAY_ENUMS: tuple[type[IntEnum], ...] = (Day, DayAbbreviation)
_MONTH_ENUMS: tuple[type[IntEnum], ...] = (Month, MonthAbbreviation)

# "8h30-11h30", "9h30-18h", "22h-07h" -> (hours, minutes, hours, minutes)
_HOUR_RANGE_RE = re.compile(r"(\d{1,2})h(\d{0,2})-(\d{1,2})h(\d{0,2})")

# Full names before abbreviations so the alternation prefers the longer token;
# "AU" before "A". Word boundaries stop tokens matching inside words such as
# AUTOBUS, MARCHE or AVRILAU (a latent bug in the prototype's boundary-less
# pattern). `__members__` is used so enum aliases (avr, sept) are included.
_TOKENS = (
    list(Day.__members__)
    + list(Month.__members__)
    + list(DayAbbreviation.__members__)
    + list(MonthAbbreviation.__members__)
    + ["ET", "AU", "A"]
)
_TOKEN_RE = re.compile(r"\b(" + "|".join(_TOKENS) + r")\b", flags=re.IGNORECASE)

# Struck-through P / A pictograms. The raw data also writes them lowercase, with a
# doubled backslash, or without the following space ("\p 8h", "\\P 9h", "\P13H").
_NO_PARKING_RE = re.compile(r"\\+P", flags=re.IGNORECASE)
_NO_STOPPING_RE = re.compile(r"\\+A", flags=re.IGNORECASE)
# Plain P pictogram: a P on its own ("P 60 min", "P15 min"), not a word starting
# with P such as PANONCEAU or PARCOMETRE.
_PERMITTED_RE = re.compile(r"P(?![A-Z])", flags=re.IGNORECASE)


def fold_accents(text: str) -> str:
    """Strip diacritics so French tokens match their unaccented enum names.

    The raw descriptions write the range connector as ``À`` as often as ``A``
    (``LUN À VEN``) and months as ``DÉC`` / ``AOÛT``; reserved signs say ``RÉSERVÉ``.

    Args:
        text: Raw description.

    Returns:
        The text with combining marks removed (``"RÉSERVÉ À"`` → ``"RESERVE A"``).
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def hour_to_float(hours: str, minutes: str) -> float:
    """Convert matched ``HHhMM`` parts to fractional hours.

    Args:
        hours: Hour digits.
        minutes: Minute digits, possibly empty (``"9h"``).

    Returns:
        E.g. ``("8", "30")`` → 8.5.
    """
    return int(hours) + (int(minutes) / 60.0 if minutes else 0.0)


def extract_hour_ranges(description: str) -> list[tuple[float, float]]:
    """All ``HHhMM-HHhMM`` spans; end < start means an overnight wraparound."""
    return [
        (hour_to_float(h1, m1), hour_to_float(h2, m2))
        for h1, m1, h2, m2 in _HOUR_RANGE_RE.findall(description)
    ]


def _lookup(token: str, enums: tuple[type[IntEnum], ...]) -> int | None:
    """Value of the first enum having a member named ``token``.

    Args:
        token: Lower-case, unaccented token.
        enums: Enums to search, in order.

    Returns:
        The member's value, or ``None``.
    """
    for enum_type in enums:
        try:
            return enum_type[token].value
        except KeyError:
            continue
    return None


def extract_day_month_ranges(
    description: str,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Group day/month tokens into ``(start, end)`` ranges.

    A bare token starts a new single-value range; ``A``/``AU`` extends the current
    one into a span (``LUN AU VEN`` -> ``(1, 5)``). ``ET`` is a no-op separator.
    """
    day_ranges: list[tuple[int, int]] = []
    month_ranges: list[tuple[int, int]] = []
    day_acc: list[int] = []
    month_acc: list[int] = []
    is_range = False

    for match in _TOKEN_RE.findall(fold_accents(description)):
        upper = match.upper()
        if upper == "ET":
            continue
        if upper in ("A", "AU"):
            is_range = True
            continue

        token = match.lower()
        day = _lookup(token, _DAY_ENUMS)
        if day is not None:
            if day_acc and not is_range:
                day_ranges.append((day_acc[0], day_acc[-1]))
                day_acc = []
            day_acc.append(day)
            is_range = False
            continue

        month = _lookup(token, _MONTH_ENUMS)
        if month is not None:
            if month_acc and not is_range:
                month_ranges.append((month_acc[0], month_acc[-1]))
                month_acc = []
            month_acc.append(month)
            is_range = False

    if day_acc:
        day_ranges.append((day_acc[0], day_acc[-1]))
    if month_acc:
        month_ranges.append((month_acc[0], month_acc[-1]))
    return day_ranges, month_ranges


def classify(description: str) -> tuple[SignCategory, bool]:
    """``(category, is_reserved)`` from the sign's leading pictogram code.

    - ``\\P …`` (struck-through P, no parking) and ``\\A …`` (struck-through A,
      no stopping) → prohibited during the stated times;
    - ``P …`` (plain P, e.g. ``P 60 min 9h-17h``, ``P TARIFÉ``) → permitted;
    - anything else (sub-panels, meters, bare schedules…) → other.

    Args:
        description: Raw ``DESCRIPTION_RPA`` text.

    Returns:
        The category and whether the sign is reserved (``RÉSERVÉ``).
    """
    folded = fold_accents(description).strip()
    return _KIND_CATEGORY[sign_kind(description)], "RESERVE" in folded.upper()


_KIND_CATEGORY = {
    SignKind.no_parking: SignCategory.prohibited,
    SignKind.no_stopping: SignCategory.prohibited,
    SignKind.parking: SignCategory.permitted,
    SignKind.other: SignCategory.other,
}


def sign_kind(description: str) -> SignKind:
    """The pictogram a sign shows, from its leading code.

    Args:
        description: Raw ``DESCRIPTION_RPA`` text.

    Returns:
        ``no_parking`` (``\\P``), ``no_stopping`` (``\\A``), ``parking`` (plain ``P``)
        or ``other``.
    """
    folded = fold_accents(description).strip()
    if _NO_PARKING_RE.match(folded):
        return SignKind.no_parking
    if _NO_STOPPING_RE.match(folded):
        return SignKind.no_stopping
    if _PERMITTED_RE.match(folded):
        return SignKind.parking
    return SignKind.other
