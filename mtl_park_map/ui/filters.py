"""Filter state edited in the side panel, and its mapping to store queries."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta

from mtl_park_map.enums import SignCategory
from mtl_park_map.models import SignQuery, SpotQuery, StripQuery, TimeWindow

type IntRange = tuple[int, int]
type TimeRange = tuple[time, time]

_DEFAULT_SPAN = timedelta(hours=1)
# No-parking signs are the most informative (street cleaning, rush-hour bans…), so
# they are shown alongside the (far fewer) explicit parking-permitted signs.
DEFAULT_CATEGORIES = frozenset({SignCategory.permitted, SignCategory.prohibited})


@dataclass(frozen=True, slots=True)
class FilterState:
    """Everything the user can filter on. ``None`` ranges are not filtered.

    Attributes:
        show_signs: Draw parking signs.
        show_spots: Draw paid spots.
        show_strips: Draw no-parking curb strips.
        strip_restricted: ``None`` all strips, ``True`` no-parking strips only,
            ``False`` parkable strips only.
        include_inferred_strips: Count rules whose extent was inferred from signs
            without arrows.
        categories: Sign categories to draw.
        reserved: ``None`` all signs, ``True`` reserved only, ``False`` no reserved.
        hours: Start/end time of day; ``end < start`` wraps past midnight.
        days: ISO weekday range (1 = Monday), may wrap (``(6, 1)`` = Sat–Mon).
        months: Month range (1 = January), may wrap.
        not_in_range: Show signs *not* active during the window instead.
        signs_ignore_time: Show signs whatever their hours (the window and
            ``not_in_range`` then only apply to paid spots and curb strips).
    """

    show_signs: bool = True
    show_spots: bool = True
    show_strips: bool = True
    strip_restricted: bool | None = None
    include_inferred_strips: bool = True
    categories: frozenset[SignCategory] = DEFAULT_CATEGORIES
    reserved: bool | None = None
    hours: TimeRange | None = None
    days: IntRange | None = None
    months: IntRange | None = None
    not_in_range: bool = False
    signs_ignore_time: bool = False


def default_filters(now: datetime) -> FilterState:
    """"Where can I park right now?": permitted and no-parking signs, and paid spots,
    for the next hour.

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
    if f.signs_ignore_time:
        # An empty window matches every sign; inverting it would match none.
        return SignQuery(categories=f.categories, reserved=f.reserved)
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


def to_strip_query(f: FilterState) -> StripQuery:
    """Map filters to a curb-strip query.

    Args:
        f: The filters.

    Returns:
        The query (hours, days and months all apply to no-parking rules).
    """
    return StripQuery(
        window=_window(f, with_months=True),
        restricted=f.strip_restricted,
        include_inferred=f.include_inferred_strips,
    )


def window_is_complete(f: FilterState) -> bool:
    """Whether spots' free/paid status is meaningful (needs both hours and days).

    Args:
        f: The filters.

    Returns:
        True when both an hour and a day range are set.
    """
    return f.hours is not None and f.days is not None


# --- persistence ---------------------------------------------------------------------
# Everything outside the time window ("When" box) is remembered between sessions;
# the window itself restarts at "now" every launch.

type SavedOptions = dict[str, object]


def saved_options(f: FilterState) -> SavedOptions:
    """The non-time filters, as JSON-friendly values.

    Args:
        f: The filters.

    Returns:
        A dict for :func:`restore_options` (hours, days, months and
        ``not_in_range`` are left out).
    """
    return {
        "show_signs": f.show_signs,
        "show_spots": f.show_spots,
        "show_strips": f.show_strips,
        "categories": sorted(c.value for c in f.categories),
        "reserved": f.reserved,
        "strip_restricted": f.strip_restricted,
        "include_inferred_strips": f.include_inferred_strips,
        "signs_ignore_time": f.signs_ignore_time,
    }


def _bool(value: object, default: bool) -> bool:
    """``value`` if it is a bool, else ``default``."""
    return value if isinstance(value, bool) else default


def _tristate(value: object, default: bool | None) -> bool | None:
    """``value`` if it is a bool or ``None``, else ``default``."""
    return value if value is None or isinstance(value, bool) else default


def _categories(value: object, default: frozenset[SignCategory]) -> frozenset[SignCategory]:
    """Known categories from a list of names, else ``default``."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return default
    known = {c.value for c in SignCategory}
    if not set(value) <= known:
        return default
    return frozenset(SignCategory(v) for v in value)


def restore_options(base: FilterState, saved: Mapping[str, object]) -> FilterState:
    """Apply saved non-time filters onto ``base`` (typically today's defaults).

    Each field falls back to ``base`` on its own when missing or invalid, so a
    corrupt or older settings file never breaks startup.

    Args:
        base: Filters providing the time window and fallbacks.
        saved: Output of :func:`saved_options` (possibly partial or invalid).

    Returns:
        The restored filters.
    """
    return replace(
        base,
        show_signs=_bool(saved.get("show_signs"), base.show_signs),
        show_spots=_bool(saved.get("show_spots"), base.show_spots),
        show_strips=_bool(saved.get("show_strips"), base.show_strips),
        categories=_categories(saved.get("categories"), base.categories),
        reserved=_tristate(saved.get("reserved", base.reserved), base.reserved),
        strip_restricted=_tristate(
            saved.get("strip_restricted", base.strip_restricted), base.strip_restricted
        ),
        include_inferred_strips=_bool(
            saved.get("include_inferred_strips"), base.include_inferred_strips
        ),
        signs_ignore_time=_bool(saved.get("signs_ignore_time"), base.signs_ignore_time),
    )
