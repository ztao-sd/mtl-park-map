from datetime import datetime, time

import pytest

from mtl_park_map.enums import SignCategory
from mtl_park_map.models import TimeWindow
from mtl_park_map.ui.filters import (
    FilterState,
    default_filters,
    hour_of,
    to_sign_query,
    to_spot_query,
    window_is_complete,
)

TUESDAY_MORNING = datetime(2026, 10, 6, 10, 7, 42)


def test_hour_of():
    assert hour_of(time(8, 30)) == 8.5
    assert hour_of(time(0, 0)) == 0.0
    assert hour_of(time(23, 45)) == 23.75


def test_default_filters_are_now_for_one_hour():
    f = default_filters(TUESDAY_MORNING)
    assert f.show_signs and f.show_spots
    assert f.categories == frozenset({SignCategory.permitted})
    assert f.reserved is None
    assert f.hours == (time(10, 7), time(11, 7))
    assert f.days == (2, 2)
    assert f.months == (10, 10)
    assert not f.not_in_range


def test_default_hours_wrap_past_midnight():
    f = default_filters(datetime(2026, 10, 6, 23, 30))
    assert f.hours == (time(23, 30), time(0, 30))
    assert to_sign_query(f).window.hour == (23.5, 0.5)


def test_sign_query_mapping():
    f = FilterState(
        categories=frozenset({SignCategory.prohibited}),
        reserved=False,
        hours=(time(8, 30), time(9, 0)),
        days=(1, 5),
        months=None,
        not_in_range=True,
    )
    q = to_sign_query(f)
    assert q.categories == frozenset({SignCategory.prohibited})
    assert q.reserved is False
    assert q.window == TimeWindow(hour=(8.5, 9.0), day=(1, 5), month=None)
    assert q.not_in_range


def test_spot_query_ignores_months():
    f = FilterState(hours=(time(9, 0), time(10, 0)), days=(6, 7), months=(1, 3))
    assert to_spot_query(f).window == TimeWindow(hour=(9.0, 10.0), day=(6, 7))


@pytest.mark.parametrize(
    ("hours", "days", "complete"),
    [
        ((time(9), time(10)), (1, 1), True),
        (None, (1, 1), False),
        ((time(9), time(10)), None, False),
    ],
)
def test_window_is_complete(
    hours: tuple[time, time] | None, days: tuple[int, int] | None, complete: bool
):
    assert window_is_complete(FilterState(hours=hours, days=days)) is complete
