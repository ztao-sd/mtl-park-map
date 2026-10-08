import pytest

from mtl_park_map.query.overlap import day_ranges_overlap, hour_ranges_overlap, rule_overlaps


@pytest.mark.parametrize(
    ("rule", "query", "expected"),
    [
        ((9.0, 17.0), (10.0, 11.0), True),  # inside
        ((9.0, 17.0), (16.0, 18.0), True),  # partial overlap is enough
        ((9.0, 17.0), (17.0, 18.0), False),  # touching ends do not overlap
        ((9.0, 17.0), (7.0, 9.0), False),
        ((22.0, 7.0), (23.0, 1.0), True),  # both overnight
        ((22.0, 7.0), (6.5, 8.0), True),
        ((22.0, 7.0), (8.0, 9.0), False),
        ((0.0, 2.0), (23.0, 1.0), True),  # overnight query
        ((9.0, 17.0), (10.0, 10.0), True),  # instant inside
        ((9.0, 17.0), (17.0, 17.0), False),  # instant at the (exclusive) end
        ((0.0, 24.0), (3.0, 4.0), True),  # all day
    ],
)
def test_hour_overlap(rule: tuple[float, float], query: tuple[float, float], expected: bool):
    assert hour_ranges_overlap(rule, query) is expected


@pytest.mark.parametrize(
    ("rule", "query", "base", "expected"),
    [
        ((1, 5), (5, 6), 7, True),  # Mon-Fri vs Fri-Sat share Friday
        ((1, 5), (6, 7), 7, False),
        ((6, 1), (1, 1), 7, True),  # Sat-Mon wraps over Sunday
        ((6, 1), (2, 3), 7, False),
        ((3, 3), (3, 3), 7, True),  # single day
        ((12, 3), (1, 1), 12, True),  # Dec-Mar wraps into January
        ((4, 11), (12, 12), 12, False),
        ((4, 12), (11, 2), 12, True),
    ],
)
def test_discrete_overlap(
    rule: tuple[int, int], query: tuple[int, int], base: int, expected: bool
):
    assert day_ranges_overlap(rule, query, base) is expected


def test_rule_overlaps_any_range_within_a_dimension():
    hours = [(7.0, 9.0), (16.0, 18.0)]
    assert rule_overlaps(hours, [], [], (17.0, 17.5), None, None)
    assert not rule_overlaps(hours, [], [], (10.0, 11.0), None, None)


def test_rule_overlaps_requires_every_constrained_dimension():
    hours, days = [(8.0, 11.0)], [(2, 2)]  # Tuesdays 8-11
    assert rule_overlaps(hours, days, [], (10.0, 12.0), (2, 2), None)
    assert not rule_overlaps(hours, days, [], (10.0, 12.0), (3, 3), None)  # Wednesday
    assert not rule_overlaps(hours, days, [], (12.0, 13.0), (2, 2), None)


def test_unconstrained_or_unqueried_dimensions_never_exclude():
    # "EN TOUT TEMPS": no parsed ranges -> applies at every time
    assert rule_overlaps([], [], [], (3.0, 4.0), (7, 7), (1, 1))
    # no month filter in the query -> the rule's months don't restrict
    assert rule_overlaps([(8.0, 9.0)], [], [(4, 11)], (8.0, 8.5), None, None)
    assert not rule_overlaps([(8.0, 9.0)], [], [(4, 11)], (8.0, 8.5), None, (12, 12))
