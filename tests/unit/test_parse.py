from mtl_park_map.enums import SignCategory
from mtl_park_map.etl.parse import (
    classify,
    fold_accents,
    extract_day_month_ranges,
    extract_hour_ranges,
)


def test_hour_ranges_with_minutes_and_wraparound():
    assert extract_hour_ranges(r"\P 8h30-11h30 MERCREDI") == [(8.5, 11.5)]
    assert extract_hour_ranges(r"\P 9h30-18h EXCEPTE") == [(9.5, 18.0)]
    # multiple windows incl. an overnight wraparound (end < start)
    assert extract_hour_ranges(r"\P 07h-19h CLIGNOTANT 22h-07h FIXE") == [
        (7.0, 19.0),
        (22.0, 7.0),
    ]


def test_no_hours():
    assert extract_hour_ranges(r"\A EN TOUT TEMPS") == []


def test_day_range_with_connector():
    days, months = extract_day_month_ranges(r"\A RESERVE AUTOBUS 07h-09h30 LUN. AU VEN.")
    assert days == [(1, 5)]
    assert months == []


def test_separate_days_without_connector():
    days, _ = extract_day_month_ranges(r"\P 13h-15h30 MARDI VENDREDI")
    assert days == [(2, 2), (5, 5)]


def test_month_range_and_single_day():
    days, months = extract_day_month_ranges(r"\P 8h30-11h30 MERCREDI 1 AVRIL AU 1 DEC")
    assert days == [(3, 3)]
    assert months == [(4, 12)]


def test_sept_and_avr_abbreviations():
    # "SEPT" (September) and the AU connector -> wraparound month range (9, 6)
    _, months = extract_day_month_ranges(r"\A 7h-18h LUN A VEN SEPT A JUIN")
    assert months == [(9, 6)]
    _, months2 = extract_day_month_ranges(r"\P 1 AVR AU 1 DEC")
    assert months2 == [(4, 12)]


def test_autobus_does_not_match_au_connector():
    # word boundaries stop AUTOBUS from being read as the "AU" range connector
    days, _ = extract_day_month_ranges(r"\A RESERVE AUTOBUS SCOLAIRE MARDI")
    assert days == [(2, 2)]


def test_classify():
    assert classify(r"\P EN TOUT TEMPS") == (SignCategory.permitted, False)
    assert classify(r"\A EN TOUT TEMPS") == (SignCategory.prohibited, False)
    assert classify(r"\A RESERVE AUTOBUS") == (SignCategory.prohibited, True)
    assert classify("INTERDICTION DE STAT. S3R") == (SignCategory.other, False)


def test_accented_a_is_a_range_connector():
    # "À" is the most common connector in the raw data (136 codes)
    days, _ = extract_day_month_ranges(r"\P 09h-17h LUN À VEN")
    assert days == [(1, 5)]


def test_accented_month_tokens():
    _, months = extract_day_month_ranges(r"\A 1 AVRIL AU 1 DÉC")
    assert months == [(4, 12)]
    _, months = extract_day_month_ranges(r"\A 15 JUIN À 15 AOÛT")
    assert months == [(6, 8)]
    _, months = extract_day_month_ranges(r"\A 1 FÉV AU 31 DÉCEMBRE")
    assert months == [(2, 12)]


def test_classify_accented_reserved():
    assert classify(r"\P RÉSERVÉ S3R 09h-23h") == (SignCategory.permitted, True)


def test_fold_accents():
    assert fold_accents("RÉSERVÉ À AOÛT Côte") == "RESERVE A AOUT Cote"
