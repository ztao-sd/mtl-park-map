import pickle
import sys

from PySide6.QtWidgets import QApplication

from mtl_park_map.app.main_win import MainWindowView
from mtl_park_map.config import Config
from mtl_park_map.lib.paid_parking_query import PaidParkingAnalyzer


def main():
    config = Config()

    with open(config.parking_sign_curated_pickle, "rb") as f:
        parking_sign_gdf = pickle.load(f)

    paid_parking_analyzer = PaidParkingAnalyzer()

    qt_app = QApplication(sys.argv)
    main_window_view = MainWindowView(parking_sign_gdf, paid_parking_analyzer)
    main_window_view.initialize()
    main_window_view.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()