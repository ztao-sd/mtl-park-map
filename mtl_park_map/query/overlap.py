"""Whether a regulation applies at *any* moment of a query window (overlap semantics).

This complements :mod:`mtl_park_map.query.intervals`, whose *containment* test (the
whole window inside the sign's hours) answers "is this sign showing as active?". To
decide whether a curb is parkable for a whole stay, any overlap matters: a no-parking
rule starting at 10:30 makes a 10:00–11:00 stay illegal.

Ranges are mapped to half-open arcs on a wrapping axis:

- hours are continuous: ``(9, 17)`` → ``[9, 17)``; ``(22, 7)`` wraps past midnight;
- days (1–7) and months (1–12) are discrete and inclusive: ``(1, 5)`` (Mon–Fri) →
  ``[0, 5)`` on a 7-unit axis; ``(6, 1)`` (Sat–Mon) wraps over Sunday.

A zero-length range (e.g. the instant ``(10, 10)``) is a point ``p`` overlapping an
arc ``[a, b)`` when ``a <= p < b``.

Dimensions are treated independently (a cartesian product), as the parsed sign data
does not tie hours to particular days.
"""

from collections.abc import Sequence

from mtl_park_map.query.intervals import Range

type _Arc = tuple[float, float]

_HOURS = 24.0


def _arcs(start: float, end: float, base: float) -> list[_Arc]:
    """Split a possibly wrapping half-open range ``[start, end)`` into plain arcs.

    Args:
        start: Range start on ``[0, base]``.
        end: Range end; ``end < start`` wraps past ``base``.
        base: Axis length.

    Returns:
        One arc, or two when the range wraps.
    """
    if end < start:
        return [(start, base), (0.0, end)]
    return [(start, end)]


def _arc_overlap(a: _Arc, b: _Arc) -> bool:
    """Whether two plain arcs (possibly zero-length points) intersect.

    Args:
        a: First arc ``[lo, hi)``.
        b: Second arc ``[lo, hi)``.

    Returns:
        True on a non-empty intersection, or a point lying inside the other arc.
    """
    (a_lo, a_hi), (b_lo, b_hi) = a, b
    if a_lo == a_hi:
        return b_lo <= a_lo < b_hi or (b_lo == b_hi == a_lo)
    if b_lo == b_hi:
        return a_lo <= b_lo < a_hi
    return max(a_lo, b_lo) < min(a_hi, b_hi)


def _any_overlap(a: list[_Arc], b: list[_Arc]) -> bool:
    """Whether any arc of ``a`` intersects any arc of ``b``."""
    return any(_arc_overlap(x, y) for x in a for y in b)


def hour_ranges_overlap(rule: Range, query: Range) -> bool:
    """Whether two hour ranges (fractional hours, may wrap) share any moment.

    Args:
        rule: The regulation's hours.
        query: The queried hours.

    Returns:
        True if they overlap.
    """
    return _any_overlap(_arcs(*rule, _HOURS), _arcs(*query, _HOURS))


def day_ranges_overlap(rule: Range, query: Range, base: int) -> bool:
    """Whether two inclusive, 1-based discrete ranges (days or months) intersect.

    Args:
        rule: The regulation's range, e.g. ``(1, 5)``.
        query: The queried range.
        base: Axis length: 7 for weekdays, 12 for months.

    Returns:
        True if they share at least one day / month.
    """
    # Inclusive [a, b] over units 1..base → half-open [a - 1, b) over 0..base.
    rule_arcs = _arcs(rule[0] - 1, rule[1], base)
    query_arcs = _arcs(query[0] - 1, query[1], base)
    return _any_overlap(rule_arcs, query_arcs)


def rule_overlaps(
    hour_ranges: Sequence[Range],
    day_ranges: Sequence[Range],
    month_ranges: Sequence[Range],
    q_hour: Range | None,
    q_day: Range | None,
    q_month: Range | None,
) -> bool:
    """Whether a regulation applies at some moment of the query window.

    Within a dimension the rule's ranges are ORed; across dimensions the checks are
    ANDed. A dimension the rule leaves unconstrained, or the query leaves open, never
    excludes it.

    Args:
        hour_ranges: The rule's hour windows.
        day_ranges: The rule's weekday windows.
        month_ranges: The rule's month windows.
        q_hour: Queried hours, or ``None``.
        q_day: Queried weekdays, or ``None``.
        q_month: Queried months, or ``None``.

    Returns:
        True if the rule overlaps the window in every constrained dimension.
    """
    if q_hour is not None and hour_ranges:
        if not any(hour_ranges_overlap(r, q_hour) for r in hour_ranges):
            return False
    if q_day is not None and day_ranges:
        if not any(day_ranges_overlap(r, q_day, 7) for r in day_ranges):
            return False
    if q_month is not None and month_ranges:
        if not any(day_ranges_overlap(r, q_month, 12) for r in month_ranges):
            return False
    return True
