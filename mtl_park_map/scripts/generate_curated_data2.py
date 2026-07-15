import re
from enum import IntEnum
from pathlib import Path

import polars as pl

import mtl_park_map as mpm
from mtl_park_map.lib.enums import Day, Month, DayAbbreviation, MonthAbbreviation


def get_int_enum(val: str, type_: type[IntEnum]) -> IntEnum | None:
    try:
        return type_[val]
    except KeyError:
        return None


def conv_time_str_to_hour(time_str: str) -> float:
    vals = time_str.lower().split("h")
    num = 0
    if vals:
        num += float(vals[0])
    if len(vals) > 1:
        if vals[1]:
            num += float(vals[1]) / 60.0
    return num


def extract_hour_ranges_from_str(s: str) -> list[dict[str, float]]:
    hour_ranges = []
    if matches := re.findall(
        r"(\d{1,2}h\d{0,2})-(\d{1,2}h\d{0,2})", s, flags=re.IGNORECASE
    ):
        for start, end in matches:
            hour_ranges.append(
                {
                    "start": conv_time_str_to_hour(start),
                    "end": conv_time_str_to_hour(end),
                }
            )
    return hour_ranges


def extract_day_month_ranges_from_row(s: str, pattern: str) -> pd.Series:
    day_ranges = []
    month_ranges = []
    s = row[RPA_COLUMN]
    if matches := re.findall(pattern, s, flags=re.IGNORECASE):
        day_range = []
        month_range = []
        is_range = False
        for match in matches:
            v = None
            if match == "ET":
                v = match
            elif match in ("A", "AU"):
                v = match
                is_range = True
            if v is None:
                for t_ in (Day, DayAbbreviation):
                    v = get_int_enum(match.lower(), t_)
                    if v is not None:
                        break
                if v is not None:
                    if day_range and not is_range:
                        day_ranges.append(day_range)
                        day_range = []
                    day_range.append(v.value)
                    is_range = False
            if v is None:
                for t_ in (Month, MonthAbbreviation):
                    v = get_int_enum(match.lower(), t_)
                    if v is not None:
                        break
                if v is not None:
                    if month_range and not is_range:
                        month_ranges.append(month_range)
                        month_range = []
                    month_range.append(v.value)
                    is_range = False
        if day_range:
            day_ranges.append(tuple(day_range))
        if month_range:
            month_ranges.append(tuple(month_range))
    return pd.Series([tuple(day_ranges), tuple(month_ranges)])


if __name__ == "__main__":
    RAW_DATA_DIR = Path(mpm.__file__).parent / "resource" / "raw"
    PARKING_SIGN_CSV = RAW_DATA_DIR / "signalisation_stationnement.csv"
    RPA_DESCRIPTION_COLUMN = "DESCRIPTION_RPA"

    any_pattern = "|".join(
        [d.name for d in Day]
        + [m.name for m in Month]
        + [d.name for d in DayAbbreviation]
        + [m.name for m in MonthAbbreviation]
        + ["ET", "A", "AU"]
    )

    parking_sign_df = pl.scan_csv(PARKING_SIGN_CSV)

    step1 = parking_sign_df.with_columns(
        pl.col(RPA_DESCRIPTION_COLUMN)
        .map_elements(
            extract_hour_ranges_from_str,
            return_dtype=pl.List(
                pl.Struct(
                    [
                        pl.Field("start", pl.Float64),
                        pl.Field("end", pl.Float64),
                    ]
                )
            ),
        )
        .alias("generated_hour_ranges")
    ).explode("generated_hour_ranges", empty_as_null=True).unnest("generated_hour_ranges")



    print(parking_sign_df.collect())
    print(step1.collect())
    print(step1.select(["DESCRIPTION_RPA", "start", "end"]).collect())