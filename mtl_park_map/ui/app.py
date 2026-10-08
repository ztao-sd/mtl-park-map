"""Application entry point: ``uv run python -m mtl_park_map``."""

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from mtl_park_map import settings
from mtl_park_map.geolocate import locate_address
from mtl_park_map.slippy.tiles import TileLoader
from mtl_park_map.store import Store
from mtl_park_map.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    """Start the desktop app.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv``).

    Returns:
        Process exit code.
    """
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(settings.APP_NAME)
    app.setApplicationVersion(settings.APP_VERSION)
    app.setOrganizationName("MTLParkMap")

    try:
        store = Store.load()
    except FileNotFoundError as exc:
        QMessageBox.critical(None, settings.APP_NAME, str(exc))
        return 1

    cache_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    tiles = TileLoader(
        settings.TILE_URL_TEMPLATE,
        settings.USER_AGENT,
        cache_dir=Path(cache_root) / "tiles",
        parent=app,
    )
    window = MainWindow(store, locate_address, tiles, QSettings())
    window.show()
    return app.exec()
