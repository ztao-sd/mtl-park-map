import pytest

from mtl_park_map.enums import SignCategory, SignKind
from mtl_park_map.etl.parse import (
    classify,
    fold_accents,
    sign_kind,
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


def test_classify_slashed_p_is_no_parking():
    # "\P" is the struck-through P: parking prohibited during the stated times
    assert classify(r"\P EN TOUT TEMPS") == (SignCategory.prohibited, False)
    assert classify(r"\P 12h-16h LUNDI 15 MARS AU 15 NOVEMBRE") == (
        SignCategory.prohibited,
        False,
    )


def test_classify_slashed_a_is_no_stopping():
    assert classify(r"\A EN TOUT TEMPS") == (SignCategory.prohibited, False)
    assert classify(r"\A RESERVE AUTOBUS") == (SignCategory.prohibited, True)


def test_classify_plain_p_is_parking_permitted():
    assert classify("P 60 min 9h-17h LUNDI JEUDI") == (SignCategory.permitted, False)
    assert classify("P TARIFÉ EXCEPTÉ SECTEUR 527") == (SignCategory.permitted, False)
    assert classify("P15 min LUN À VEN") == (SignCategory.permitted, False)


@pytest.mark.parametrize(
    "description",
    [r"\p 08h - 12h lundi 1er mars", r"\\P 12h30-15h30 MERCREDI", r"\P13H - 17H MERCREDI"],
)
def test_classify_tolerates_raw_data_typos(description: str):
    # lowercase, doubled backslash and missing space all occur in the raw data
    assert classify(description)[0] == SignCategory.prohibited


@pytest.mark.parametrize(
    "description",
    ["PANONCEAU 15 AOUT - 28 JUIN", "PARCOMETRE", "INTERDICTION DE STAT. S3R", "8H À 12H MAR JEU"],
)
def test_classify_other(description: str):
    assert classify(description)[0] == SignCategory.other


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
    assert classify("P RÉSERVÉ S3R 09h-23h") == (SignCategory.permitted, True)


def test_fold_accents():
    assert fold_accents("RÉSERVÉ À AOÛT Côte") == "RESERVE A AOUT Cote"


@pytest.mark.parametrize(
    ("description", "kind"),
    [
        (r"\P 9h-17h LUN A VEN", SignKind.no_parking),
        (r"\p 08h - 12h lundi", SignKind.no_parking),
        (r"\A EN TOUT TEMPS", SignKind.no_stopping),
        ("P 60 min 9h-17h", SignKind.parking),
        ("PANONCEAU 15 AOUT - 28 JUIN", SignKind.other),
    ],
)
def test_sign_kind(description: str, kind: SignKind):
    assert sign_kind(description) is kind
