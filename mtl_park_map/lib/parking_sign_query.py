
import geopandas as gpd

from mtl_park_map.lib.query_utils import is_within_interval

RPA_COLUMN = "DESCRIPTION_RPA"


def _filter_by_time_ranges(
    row,
    hour_range: tuple[float, float] | None,
    day_range: tuple[int, int] | None,
    month_range: tuple[int, int] | None,
    not_in_range: bool = False,
) -> bool:
    hour_ranges, day_ranges, month_ranges = (
        row["hour_ranges"],
        row["day_ranges"],
        row["month_ranges"],
    )
    passed = True
    if not any((hour_ranges, day_ranges, month_ranges)):
        passed = False

    if hour_ranges and hour_range and passed:
        for range_ in hour_ranges:
            passed = is_within_interval(hour_range, range_, 24.0) ^ not_in_range
            if not passed:
                break

    if day_ranges and day_range and passed:
        for range_ in day_ranges:
            if len(range_) == 1:
                range_ = (range_[0], range_[0])
            if len(range_) <= 2:
                # print(day_ranges, hour_ranges, row[RPA_COLUMN])
                passed = is_within_interval(day_range, range_, 7) ^ not_in_range
            else:
                passed = False
            if not passed:
                break

    if month_ranges and month_range and passed:
        for range_ in month_ranges:
            if len(range_) == 1:
                range_ = (range_[0], range_[0])
            passed = is_within_interval(month_range, range_, 12) ^ not_in_range
            if not passed:
                break

    return passed


def query_by_rpa_regex(gdf: gpd.GeoDataFrame, expr: str) -> gpd.GeoDataFrame:
    return gdf[gdf[RPA_COLUMN].str.contains(expr, case=False, regex=True)]


def query_by_time_range(
    gdf: gpd.GeoDataFrame,
    hour_range: tuple[float, float] | None,
    day_range: tuple[int, int] | None,
    month_range: tuple[int, int] | None,
    not_in_range: bool = False,
) -> gpd.GeoDataFrame:
    return gdf[
        gdf.apply(
            _filter_by_time_ranges,
            args=(hour_range, day_range, month_range, not_in_range),
            axis=1,
        )
    ]


def query_by_bounding_box(
    gdf: gpd.GeoDataFrame, min_x: float, max_x: float, min_y: float, max_y: float
) -> gpd.GeoDataFrame:
    return gdf.cx[min_x:max_x, min_y:max_y]
