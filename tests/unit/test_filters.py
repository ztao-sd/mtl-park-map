from datetime import datetime, time

import pytest

from mtl_park_map.enums import SignCategory
from mtl_park_map.models import TimeWindow
from mtl_park_map.ui.filters import (
    FilterState,
    default_filters,
    hour_of,
    restore_options,
    saved_options,
    to_sign_query,
    to_spot_query,
    to_strip_query,
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
    # no-parking signs are the most informative ones, so they are on by default
    assert f.categories == frozenset({SignCategory.permitted, SignCategory.prohibited})
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


def test_strips_are_shown_by_default_and_query_all_dimensions():
    f = default_filters(TUESDAY_MORNING)
    assert f.show_strips
    window = to_strip_query(f).window
    assert window == TimeWindow(hour=(10 + 7 / 60, 11 + 7 / 60), day=(2, 2), month=(10, 10))


@pytest.mark.parametrize("restricted", [None, True, False])
def test_strip_status_maps_to_query(restricted: bool | None):
    f = FilterState(strip_restricted=restricted)
    assert to_strip_query(f).restricted is restricted


def test_strip_status_defaults_to_all():
    assert default_filters(TUESDAY_MORNING).strip_restricted is None


def test_signs_can_ignore_the_time_window():
    f = FilterState(
        hours=(time(20, 0), time(21, 0)),
        days=(2, 2),
        months=(10, 10),
        not_in_range=True,
        signs_ignore_time=True,
    )
    q = to_sign_query(f)
    assert q.window == TimeWindow() and not q.not_in_range
    # spots and strips still use the window
    assert to_spot_query(f).window == TimeWindow(hour=(20.0, 21.0), day=(2, 2))
    assert to_strip_query(f).window.hour == (20.0, 21.0)


def test_signs_follow_the_time_window_by_default():
    assert not default_filters(TUESDAY_MORNING).signs_ignore_time


def test_inferred_strips_are_included_by_default_and_can_be_left_out():
    assert to_strip_query(default_filters(TUESDAY_MORNING)).include_inferred
    assert not to_strip_query(FilterState(include_inferred_strips=False)).include_inferred


# --- persistence of the non-time options ---------------------------------------------


def _customised() -> FilterState:
    return FilterState(
        show_signs=False,
        show_spots=True,
        show_strips=False,
        categories=frozenset({SignCategory.other}),
        reserved=True,
        strip_restricted=False,
        include_inferred_strips=False,
        signs_ignore_time=True,
        hours=(time(1, 0), time(2, 0)),
        days=(7, 7),
        months=(1, 1),
        not_in_range=True,
    )


def test_saved_options_exclude_the_time_window():
    saved = saved_options(_customised())
    assert not {"hours", "days", "months", "not_in_range"} & saved.keys()
    assert saved["categories"] == ["other"]


def test_restore_keeps_todays_window_and_the_saved_options():
    today = default_filters(TUESDAY_MORNING)
    restored = restore_options(today, saved_options(_customised()))
    assert (restored.hours, restored.days, restored.months) == (today.hours, today.days, today.months)
    assert not restored.not_in_range
    customised = _customised()
    for field in ("show_signs", "show_spots", "show_strips", "categories", "reserved",
                  "strip_restricted", "include_inferred_strips", "signs_ignore_time"):
        assert getattr(restored, field) == getattr(customised, field), field


def test_restore_ignores_bad_values_field_by_field():
    today = default_filters(TUESDAY_MORNING)
    restored = restore_options(
        today,
        {"show_signs": "yes", "categories": ["permitted", "bogus"], "reserved": 3, "show_spots": False},
    )
    assert restored.show_signs == today.show_signs  # wrong type -> default
    assert restored.categories == today.categories  # unknown category -> default
    assert restored.reserved == today.reserved
    assert restored.show_spots is False  # valid fields still apply


def test_restore_from_nothing_is_the_defaults():
    today = default_filters(TUESDAY_MORNING)
    assert restore_options(today, {}) == today
