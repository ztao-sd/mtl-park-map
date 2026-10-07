"""Typed query models passed from the UI to :class:`mtl_park_map.store.Store`."""

from dataclasses import dataclass

from mtl_park_map.enums import SignCategory
from mtl_park_map.query.intervals import Range


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """The time window a query asks about; ``None`` leaves a dimension unfiltered.

    Ranges are inclusive ``(start, end)`` pairs on a wrapping axis, so ``end < start``
    means wraparound (e.g. hours ``(22, 7)`` or months ``(9, 6)``).

    Attributes:
        hour: Fractional hours in ``[0, 24]``, e.g. ``(8.5, 11.5)`` for 08:30–11:30.
        day: ISO weekdays, 1 = Monday … 7 = Sunday.
        month: Months, 1 = January … 12 = December.
    """

    hour: Range | None = None
    day: Range | None = None
    month: Range | None = None


@dataclass(frozen=True, slots=True)
class SignQuery:
    """Which parking signs to return.

    Attributes:
        categories: Sign categories to include; empty means no signs.
        reserved: ``None`` for all signs, ``True`` for reserved only, ``False`` to
            exclude reserved signs.
        window: Signs must be active for the *whole* window (see
            :func:`mtl_park_map.query.intervals.sign_active`).
        not_in_range: Invert the window test (signs *not* active in the window).
    """

    categories: frozenset[SignCategory] = frozenset({SignCategory.permitted})
    reserved: bool | None = None
    window: TimeWindow = TimeWindow()
    not_in_range: bool = False


@dataclass(frozen=True, slots=True)
class SpotQuery:
    """Which time window to evaluate paid spots' free/paid status for.

    Attributes:
        window: Only ``hour`` and ``day`` matter: meters have no month rules. Unless
            both are set every spot is reported free.
    """

    window: TimeWindow = TimeWindow()
