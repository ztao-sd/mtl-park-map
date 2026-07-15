from dataclasses import dataclass, field
from datetime import time
from enum import IntFlag
from pathlib import Path
import duckdb

from mtl_park_map.app.qt.config import RAW_RESOURCE_DIR
from mtl_park_map.lib.query_utils import is_within_interval

CWD = Path.cwd()
PLACES_CSV = RAW_RESOURCE_DIR / "Places.csv"
EMPLACEMENT_REGLEMENTATION_CSV = RAW_RESOURCE_DIR / "EmplacementReglementation.csv"
REGLEMENTATIONS_CSV = RAW_RESOURCE_DIR / "Reglementations.csv"
REGLEMENTATION_PERIODE_CSV = RAW_RESOURCE_DIR / "ReglementationPeriode.csv"
PERIODES_CSV = RAW_RESOURCE_DIR / "Periodes.csv"
TIME_FORMAT = "%H:%M:%S"


class WeekDay(IntFlag):
    monday = 1
    tuesday = 2
    wednesday = 4
    thursday = 8
    friday = 16
    saturday = 32
    sunday = 64


@dataclass
class PaidPeriod:
    start: time
    end: time
    weekday: WeekDay
    description: str

    @property
    def period_description(self):
        s = self.start.strftime(TIME_FORMAT)
        e = self.end.strftime(TIME_FORMAT)
        d = ",".join(d_.name[:3] for d_ in WeekDay if d_ & self.weekday)
        if d:
            return f"{d}: {s}-{e}"
        return ""

@dataclass
class PaidParkinSpot:
    spot_id: str
    longitude: float
    latitude: float
    paid_periods: list[PaidPeriod] = field(default_factory=list)

    @property
    def description(self):
        return " | ".join(set(period.period_description for period in self.paid_periods if period.period_description))

def _create_tables(conn: duckdb.DuckDBPyConnection):
    conn.sql(f"""
        CREATE TABLE place AS
        SELECT *
        FROM read_csv_auto('{PLACES_CSV}', encoding='CP1252');
            """)
    conn.sql(f"""
        CREATE TABLE regulation AS
        SELECT *
        FROM read_csv_auto('{REGLEMENTATIONS_CSV}', encoding='CP1252');
            """)
    conn.sql(f"""
        CREATE TABLE period AS
        SELECT *
        FROM read_csv_auto('{PERIODES_CSV}', encoding='CP1252');
            """)
    conn.sql(f"""
        CREATE TABLE place_regulation_link AS
        SELECT *
        FROM read_csv_auto('{EMPLACEMENT_REGLEMENTATION_CSV}', encoding='CP1252');
            """)
    conn.sql(f"""
        CREATE TABLE regulation_period_link AS
        SELECT *
        FROM read_csv_auto('{REGLEMENTATION_PERIODE_CSV}', encoding='CP1252');
            """)


def _query_spot_periods(conn: duckdb.DuckDBPyConnection) -> tuple:
    return conn.sql("""
                    SELECT place.sNoPlace,
                           place.nPositionCentreLongitude,
                           place.nPositionCentreLatitude,
                           regulation_period_link.sDescription,
                           period.dtHeureDebut,
                           period.dtHeureFin,
                           period.bLun,
                           period.bMer,
                           period.bJeu,
                           period.bVen,
                           period.bSam,
                           period.bDim
                    FROM (
                             (
                                 (regulation JOIN place_regulation_link ON regulation.Name = place_regulation_link.sCodeAutocollant)
                                     JOIN regulation_period_link ON regulation.Name = regulation_period_link.sCode
                                 )
                                 JOIN period ON regulation_period_link.noPeriode = period.nID
                             )
                             JOIN place ON place.sNoPlace = place_regulation_link.sNoEmplacement
                    """).fetchall()


def _query_spots_by_bounding_box(
    conn: duckdb.DuckDBPyConnection,
    min_lon: float,
    max_lon: float,
    min_lat: float,
    max_lat: float,
) -> tuple:
    return conn.sql(
        """
                    SELECT sNoPlace, nPositionCentreLongitude, nPositionCentreLatitude FROM place 
                    WHERE (nPositionCentreLongitude between ? AND ?) AND (nPositionCentreLatitude between ? AND ?)""",
        params=(min_lon, max_lon, min_lat, max_lat),
    ).fetchall()


def check_paid_periods(
    periods: list[PaidPeriod],
    hour_range: tuple[float, float],
    day_range: tuple[int, int],
) -> bool:
    for period in periods:
        day_ranges = []
        d_range = []
        for i, d in enumerate(WeekDay):
            if d & period.weekday:
                if not d_range:
                    d_range = [i + 1, i + 1]
                else:
                    d_range[1] = i + 1
            else:
                if d_range:
                    day_ranges.append(d_range)
                d_range = []
        in_day = any(
            is_within_interval(day_range, d_range, 7) for d_range in day_ranges
        )
        if in_day:
            start_h = (
                period.start.hour
                + period.start.minute / 60
                + period.start.second / 3600
            )
            end_h = period.end.hour + period.end.minute / 60 + period.end.second / 3600
            is_paid = is_within_interval(hour_range, (start_h, end_h), 24.0)
            if is_paid:
                return True
    return False


class PaidParkingAnalyzer:
    def __init__(self):
        self._conn = duckdb.connect()
        _create_tables(self._conn)

        # Process spots period
        self._paid_parking_spots: dict[str, PaidParkinSpot] = {}
        spot_periods = _query_spot_periods(self._conn)
        for (
            spot,
            lon,
            lat,
            desc,
            start,
            end,
            mon,
            tue,
            wed,
            fr,
            sat,
            sd,
        ) in spot_periods:
            flag = 0
            for i, f in enumerate((mon, tue, wed, fr, sat, sd)):
                flag |= f << i
            if spot not in self._paid_parking_spots:
                self._paid_parking_spots[spot] = PaidParkinSpot(spot, lon, lat)
            p_spot = self._paid_parking_spots[spot]
            p_spot.paid_periods.append(
                PaidPeriod(
                    start=start,
                    end=end,
                    weekday=WeekDay(flag),
                    description=desc,
                )
            )

    def query_spots_by_bounding_box(
        self, min_lon: float, max_lon: float, min_lat: float, max_lat: float
    ) -> list[PaidParkinSpot]:
        return [
            self._paid_parking_spots[spot]
            for spot, _, _ in _query_spots_by_bounding_box(
                self._conn, min_lon, max_lon, min_lat, max_lat
            )
        ]

