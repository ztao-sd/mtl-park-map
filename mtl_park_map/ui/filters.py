"""Filter state edited in the side panel, and its mapping to store queries."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from mtl_park_map.enums import SignCategory
from mtl_park_map.models import SignQuery, SpotQuery, TimeWindow

type IntRange = tuple[int, int]
type TimeRange = tuple[time, time]

_DEFAULT_SPAN = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class FilterState:
    """Everything the user can filter on. ``None`` ranges are not filtered.

    Attributes:
        show_signs: Draw parking signs.
        show_spots: Draw paid spots.
        categories: Sign categories to draw.
        reserved: ``None`` all signs, ``True`` reserved only, ``False`` no reserved.
        hours: Start/end time of day; ``end < start`` wraps past midnight.
        days: ISO weekday range (1 = Monday), may wrap (``(6, 1)`` = Sat–Mon).
        months: Month range (1 = January), may wrap.
        not_in_range: Show signs *not* active during the window instead.
    """

    show_signs: bool = True
    show_spots: bool = True
    categories: frozenset[SignCategory] = frozenset({SignCategory.permitted})
    reserved: bool | None = None
    hours: TimeRange | None = None
    days: IntRange | None = None
    months: IntRange | None = None
    not_in_range: bool = False


def default_filters(now: datetime) -> FilterState:
    """"Where can I park right now?": permitted signs and spots for the next hour.

    Args:
        now: Current local time.

    Returns:
        Filters for ``now`` (to the minute) → one hour later, today, this month.
    """
    start = now.replace(second=0, microsecond=0)
    weekday = now.isoweekday()
    return FilterState(
        hours=(start.time(), (start + _DEFAULT_SPAN).time()),
        days=(weekday, weekday),
        months=(now.month, now.month),
    )


def hour_of(t: time) -> float:
    """Fractional hour of a time of day, e.g. 08:30 → 8.5.

    Args:
        t: Time of day.

    Returns:
        Hours since midnight.
    """
    return t.hour + t.minute / 60.0


def _window(f: FilterState, with_months: bool) -> TimeWindow:
    """The query time window for the filter's enabled dimensions.

    Args:
        f: The filters.
        with_months: Whether to include the month range.

    Returns:
        The time window.
    """
    hours = None if f.hours is None else (hour_of(f.hours[0]), hour_of(f.hours[1]))
    return TimeWindow(hour=hours, day=f.days, month=f.months if with_months else None)


def to_sign_query(f: FilterState) -> SignQuery:
    """Map filters to a sign query.

    Args:
        f: The filters.

    Returns:
        The query.
    """
    return SignQuery(
        categories=f.categories,
        reserved=f.reserved,
        window=_window(f, with_months=True),
        not_in_range=f.not_in_range,
    )


def to_spot_query(f: FilterState) -> SpotQuery:
    """Map filters to a paid-spot query (meters have no month rules).

    Args:
        f: The filters.

    Returns:
        The query.
    """
    return SpotQuery(window=_window(f, with_months=False))


def window_is_complete(f: FilterState) -> bool:
    """Whether spots' free/paid status is meaningful (needs both hours and days).

    Args:
        f: The filters.

    Returns:
        True when both an hour and a day range are set.
    """
    return f.hours is not None and f.days is not None
