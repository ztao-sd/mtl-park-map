import pickle
import re
from enum import IntEnum

import geopandas as gpd
import pandas as pd

from mtl_park_map.app.qt.config import RESOURCE_DIR, RAW_RESOURCE_DIR
from mtl_park_map.lib.enums import Day, DayAbbreviation, Month, MonthAbbreviation
from mtl_park_map.lib.app_type import StrPath

RPA_COLUMN = "DESCRIPTION_RPA"


def get_int_enum(val: str, type_: type[IntEnum]) -> IntEnum | None:
    try:
        return type_[val]
    except KeyError:
        return None


def conv_time_str_to_float(time_str: str) -> float:
    vals = time_str.lower().split("h")
    num = 0
    if vals:
        num += float(vals[0])
    if len(vals) > 1:
        if vals[1]:
            num += float(vals[1]) / 60.0
    return num


def extract_hour_ranges_from_str(s: str) -> tuple[float, ...]:
    hour_ranges = []
    if matches := re.findall(
        r"(\d{1,2}h\d{0,2})-(\d{1,2}h\d{0,2})", s, flags=re.IGNORECASE
    ):
        for start, end in matches:
            hour_ranges.append(
                (
                    conv_time_str_to_float(start),
                    conv_time_str_to_float(end),
                )
            )
    return tuple(hour_ranges)


def extract_day_month_ranges_from_row(row, pattern: str) -> pd.Series:
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


def generate_raw_parking_sign_pickle(parking_sign_geojson: StrPath, parking_sign_pickle: StrPath) -> None:
    gdf = gpd.read_file(parking_sign_geojson)
    with open(parking_sign_pickle, "wb") as f:
        pickle.dump(gdf, f)


def generate_curated_parking_sign_data(
    parking_sign_pickle: StrPath, curated_pickle: StrPath
):
    any_pattern = "|".join(
        [d.name for d in Day]
        + [m.name for m in Month]
        + [d.name for d in DayAbbreviation]
        + [m.name for m in MonthAbbreviation]
        + ["ET", "A", "AU"]
    )

    with open(parking_sign_pickle, "rb") as f:
        gdf: gpd.GeoDataFrame = pickle.load(f)

    # Filter by parking sign
    # gdf = gdf[gdf[RPA_COLUMN].str.contains(r"^\\P", case=False, regex=True)]
    gdf["hour_ranges"] = gdf[RPA_COLUMN].apply(extract_hour_ranges_from_str)
    gdf[["day_ranges", "month_ranges"]] = gdf.apply(
        extract_day_month_ranges_from_row, args=(any_pattern,), axis=1
    )
    with open(curated_pickle, "wb") as f:
        pickle.dump(gdf, f)


if __name__ == "__main__":
    parking_sign_geojson = RAW_RESOURCE_DIR / "signalisation_stationnement.geojson.json"
    parking_sign_pickle = RAW_RESOURCE_DIR / "signalisation-codification-parking.pickle"
    curated_pickle = RESOURCE_DIR / "curated" / "parking_sign_curated.pickle"
    # generate_raw_parking_sign_pickle(parking_sign_geojson, parking_sign_pickle)
    generate_curated_parking_sign_data(parking_sign_pickle, curated_pickle)