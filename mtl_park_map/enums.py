from enum import IntEnum, StrEnum


class Day(IntEnum):
    lundi = 1
    mardi = 2
    mercredi = 3
    jeudi = 4
    vendredi = 5
    samedi = 6
    dimanche = 7


class DayAbbreviation(IntEnum):
    lun = 1
    mar = 2
    mer = 3
    jeu = 4
    ven = 5
    sam = 6
    dim = 7


class Month(IntEnum):
    janvier = 1
    fevrier = 2
    mars = 3
    avril = 4
    mai = 5
    juin = 6
    juillet = 7
    aout = 8
    septembre = 9
    octobre = 10
    novembre = 11
    decembre = 12


class MonthAbbreviation(IntEnum):
    jan = 1
    fev = 2
    mar = 3
    avril = 4
    avr = 4  # alias — "AVR" appears in the raw descriptions
    mai = 5
    juin = 6
    juil = 7
    aout = 8
    sep = 9
    sept = 9  # alias — "SEPT" appears in the raw descriptions
    oct = 10
    nov = 11
    dec = 12


class SignCategory(StrEnum):
    permitted = "permitted"
    prohibited = "prohibited"
    other = "other"
