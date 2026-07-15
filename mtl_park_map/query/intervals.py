"""Pure interval math for time filtering.

``is_within_interval`` is moved verbatim from the prototype (``lib/query_utils.py``):
it tests whether a ``child`` interval sits inside a ``parent`` interval on a *wrapping*
axis (24 h, 7 days, 12 months), so overnight ranges like ``22h–07h`` work.

``sign_active`` intentionally differs from the prototype's ``_filter_by_time_ranges``:
a sign is active when the query fits *any* of a dimension's ranges (OR), not *all* of
them. The prototype broke on the first failing range, which hid multi-window signs
such as ``\\P 07h-19h CLIGNOTANT 22h-07h FIXE``.

Semantics: a sign matches when the *entire* query window is contained in the sign's
active window (containment, as in the prototype), ANDed across the hour/day/month
dimensions the sign constrains. Dimensions the sign leaves unconstrained (no parsed
ranges) never exclude it, so an always-on ``EN TOUT TEMPS`` sign matches every query.
"""

from collections.abc import Sequence

Range = tuple[float, float]


def is_within_interval(child: Range, parent: Range, base: float) -> bool:
    start_, end_ = child
    start, end = parent
    if end < start:
        end += base
        if end_ < start_:
            end_ += base
        else:
            if start_ < start:
                start_ += base
            if end_ < start:
                end_ += base
    else:
        if end_ < start_:
            end_ += base
    return start_ >= start and end_ <= end


def _any_within(query: Range, ranges: Sequence[Range], base: float) -> bool:
    return any(is_within_interval(query, r, base) for r in ranges)


def sign_active(
    hour_ranges: Sequence[Range],
    day_ranges: Sequence[Range],
    month_ranges: Sequence[Range],
    q_hour: Range | None,
    q_day: Range | None,
    q_month: Range | None,
) -> bool:
    checks: list[bool] = []
    if q_hour is not None and hour_ranges:
        checks.append(_any_within(q_hour, hour_ranges, 24.0))
    if q_day is not None and day_ranges:
        checks.append(_any_within(q_day, day_ranges, 7.0))
    if q_month is not None and month_ranges:
        checks.append(_any_within(q_month, month_ranges, 12.0))
    return all(checks) if checks else True


def sign_matches(
    hour_ranges: Sequence[Range],
    day_ranges: Sequence[Range],
    month_ranges: Sequence[Range],
    q_hour: Range | None,
    q_day: Range | None,
    q_month: Range | None,
    not_in_range: bool,
) -> bool:
    active = sign_active(
        hour_ranges, day_ranges, month_ranges, q_hour, q_day, q_month
    )
    return active ^ not_in_range
