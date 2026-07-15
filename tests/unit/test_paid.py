from mtl_park_map.query.paid import is_spot_free, mask_to_day_ranges

MON_FRI = 0b0011111  # Mon+Tue+Wed+Thu+Fri
SAT_SUN = 0b1100000


def test_mask_to_day_ranges():
    assert mask_to_day_ranges(MON_FRI) == [(1, 5)]
    assert mask_to_day_ranges(SAT_SUN) == [(6, 7)]
    assert mask_to_day_ranges(0b0000101) == [(1, 1), (3, 3)]  # Mon + Wed
    assert mask_to_day_ranges(0) == []


def test_spot_with_no_periods_is_free():
    assert is_spot_free([], (10.0, 11.0), (1.0, 5.0))


def test_paid_during_metered_window():
    periods = [(9.0, 18.0, MON_FRI)]
    # weekday 10–11 inside the Mon–Fri 9–18 meter -> paid
    assert not is_spot_free(periods, (10.0, 11.0), (1.0, 5.0))


def test_free_outside_metered_hours():
    periods = [(9.0, 18.0, MON_FRI)]
    assert is_spot_free(periods, (20.0, 21.0), (1.0, 5.0))


def test_free_outside_metered_days():
    periods = [(9.0, 18.0, MON_FRI)]
    # weekend query, meter only runs Mon–Fri -> free
    assert is_spot_free(periods, (10.0, 11.0), (6.0, 7.0))
