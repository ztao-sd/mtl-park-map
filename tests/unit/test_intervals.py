from mtl_park_map.query.intervals import (
    is_within_interval,
    sign_active,
    sign_matches,
)


def test_containment_same_axis():
    assert is_within_interval((9.0, 10.0), (8.0, 11.0), 24.0)
    assert not is_within_interval((9.0, 12.0), (8.0, 11.0), 24.0)


def test_overnight_wraparound():
    # 23:00–02:00 sits inside the overnight window 22:00–07:00
    assert is_within_interval((23.0, 2.0), (22.0, 7.0), 24.0)
    # 08:00–09:00 does not
    assert not is_within_interval((8.0, 9.0), (22.0, 7.0), 24.0)


def test_sign_active_or_within_dimension():
    # multi-window sign: query fits the SECOND window -> active (prototype missed this)
    hours = [(7.0, 19.0), (22.0, 7.0)]
    assert sign_active(hours, [], [], (23.0, 2.0), None, None)


def test_sign_active_unconstrained_is_always_on():
    # no parsed ranges (e.g. "EN TOUT TEMPS") matches any query
    assert sign_active([], [], [], (9.0, 10.0), (1.0, 5.0), (1.0, 12.0))


def test_sign_active_and_across_dimensions():
    hours = [(8.0, 18.0)]
    days = [(1.0, 5.0)]
    # hour fits but the queried day range (weekend) is outside Mon–Fri -> not active
    assert not sign_active(hours, days, [], (9.0, 10.0), (6.0, 7.0), None)


def test_not_in_range_inverts():
    hours = [(8.0, 18.0)]
    assert sign_matches(hours, [], [], (9.0, 10.0), None, None, not_in_range=False)
    assert not sign_matches(hours, [], [], (9.0, 10.0), None, None, not_in_range=True)
