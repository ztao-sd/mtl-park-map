"""Whether a paid parking spot is free at a queried time.

Ported from the prototype's ``check_paid_periods``: a spot is *paid* when any of its
metered periods covers the queried time (query day-range within the period's active
weekdays and query hour-range within the period's hours). ``is_currently_free`` is the
negation. A spot with no metered periods is always free.
"""

from collections.abc import Sequence

from mtl_park_map.query.intervals import Range, is_within_interval

# One metered period: (start_hour, end_hour, weekday_mask) where bit i (0=Mon..6=Sun).
Period = tuple[float, float, int]


def mask_to_day_ranges(mask: int) -> list[Range]:
    """Contiguous weekday spans from a bitmask, e.g. Mon–Fri (0b0011111) -> [(1, 5)]."""
    ranges: list[list[int]] = []
    for i in range(7):
        if mask & (1 << i):
            day = i + 1
            if ranges and day == ranges[-1][1] + 1:
                ranges[-1][1] = day
            else:
                ranges.append([day, day])
    return [(start, end) for start, end in ranges]


def _period_covers(period: Period, q_hour: Range, q_day: Range) -> bool:
    start_hour, end_hour, mask = period
    day_ranges = mask_to_day_ranges(mask)
    if not any(is_within_interval(q_day, dr, 7.0) for dr in day_ranges):
        return False
    return is_within_interval(q_hour, (start_hour, end_hour), 24.0)


def is_spot_free(periods: Sequence[Period], q_hour: Range, q_day: Range) -> bool:
    return not any(_period_covers(p, q_hour, q_day) for p in periods)
