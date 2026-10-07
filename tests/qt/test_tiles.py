from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mtl_park_map.slippy.tiles import TileLoader
from mtl_park_map.slippy.viewport import TileKey

CHILD = TileKey(12, 1210, 1465)
PARENT = CHILD.parent()  # (11, 605, 732)
OTHER = TileKey(12, 1211, 1465)
MISSING = TileKey(12, 0, 0)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def tile_dir(tmp_path: Path, qapp: QApplication) -> Path:
    for key, color in [(CHILD, "red"), (PARENT, "blue"), (OTHER, "green")]:
        path = tmp_path / str(key.z) / str(key.x) / f"{key.y}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(256, 256, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        assert image.save(str(path))
    return tmp_path


def _loader(tile_dir: Path, clock: FakeClock | None = None, memory_tiles: int = 16) -> TileLoader:
    template = QUrl.fromLocalFile(str(tile_dir)).toString() + "/{z}/{x}/{y}.png"
    return TileLoader(
        template,
        user_agent="test-agent",
        memory_tiles=memory_tiles,
        retry_after_s=60.0,
        clock=clock or FakeClock(),
    )


def test_loads_tile_and_emits(qtbot: QtBot, tile_dir: Path):
    loader = _loader(tile_dir)
    with qtbot.waitSignal(loader.tile_loaded, timeout=5000) as blocker:
        loader.request(CHILD)
    assert blocker.args == [CHILD]
    pixmap = loader.tile(CHILD)
    assert pixmap is not None and pixmap.width() == 256
    assert pixmap.toImage().pixelColor(10, 10) == QColor("red")
    assert not loader.is_pending(CHILD)


def test_cached_tile_is_not_requested_again(qtbot: QtBot, tile_dir: Path):
    loader = _loader(tile_dir)
    with qtbot.waitSignal(loader.tile_loaded, timeout=5000):
        loader.request(CHILD)
    loader.request(CHILD)
    assert not loader.is_pending(CHILD)


def test_concurrent_requests_are_deduplicated(qtbot: QtBot, tile_dir: Path):
    loader = _loader(tile_dir)
    loader.request(CHILD)
    loader.request(CHILD)
    assert loader.pending_count() == 1
    qtbot.waitUntil(lambda: loader.tile(CHILD) is not None, timeout=5000)


def test_missing_tile_backs_off_then_retries(qtbot: QtBot, tile_dir: Path):
    clock = FakeClock()
    loader = _loader(tile_dir, clock)
    with qtbot.waitSignal(loader.tile_failed, timeout=5000) as blocker:
        loader.request(MISSING)
    assert blocker.args == [MISSING]
    assert loader.tile(MISSING) is None

    loader.request(MISSING)
    assert not loader.is_pending(MISSING)  # still backing off

    clock.now += 61.0
    loader.request(MISSING)
    assert loader.is_pending(MISSING)
    qtbot.waitUntil(lambda: not loader.is_pending(MISSING), timeout=5000)


def test_fallback_uses_scaled_ancestor(qtbot: QtBot, tile_dir: Path):
    loader = _loader(tile_dir)
    assert loader.fallback(CHILD) is None
    with qtbot.waitSignal(loader.tile_loaded, timeout=5000):
        loader.request(PARENT)
    fallback = loader.fallback(CHILD)
    assert fallback is not None
    pixmap, source = fallback
    # CHILD is the left (x even) / bottom (y odd) quarter of its parent
    assert source == QRectF(0.0, 128.0, 128.0, 128.0)
    assert pixmap.toImage().pixelColor(10, 10) == QColor("blue")


def test_prune_aborts_unwanted_requests(qtbot: QtBot, tile_dir: Path):
    loader = _loader(tile_dir)
    failed: list[TileKey] = []
    loader.tile_failed.connect(failed.append)
    loader.request(CHILD)
    loader.request(OTHER)
    loader.prune({CHILD})
    assert not loader.is_pending(OTHER)
    qtbot.waitUntil(lambda: loader.tile(CHILD) is not None, timeout=5000)
    assert loader.tile(OTHER) is None
    assert failed == []  # an abort is not a failure: OTHER may be requested again
    loader.request(OTHER)
    assert loader.is_pending(OTHER)


def test_destroying_loader_right_after_a_load_is_safe(qtbot: QtBot, tile_dir: Path):
    # regression: replies deleted via Python deleteLater() aborted the process here
    loader = _loader(tile_dir)
    with qtbot.waitSignal(loader.tile_loaded, timeout=5000):
        loader.request(CHILD)
    del loader
    qtbot.wait(10)  # run the deferred deletes


def test_memory_cache_evicts_least_recently_used(qtbot: QtBot, tile_dir: Path):
    loader = _loader(tile_dir, memory_tiles=1)
    with qtbot.waitSignal(loader.tile_loaded, timeout=5000):
        loader.request(CHILD)
    with qtbot.waitSignal(loader.tile_loaded, timeout=5000):
        loader.request(OTHER)
    assert loader.tile(CHILD) is None
    assert loader.tile(OTHER) is not None
