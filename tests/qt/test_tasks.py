import threading

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mtl_park_map.ui.tasks import BackgroundRunner


def _fail() -> int:
    raise ValueError("boom")


def test_result_is_delivered_on_gui_thread(qtbot: QtBot, qapp: QApplication):
    runner = BackgroundRunner()
    results: list[tuple[int, bool]] = []
    worker_threads: list[QThread] = []

    def work() -> int:
        worker_threads.append(QThread.currentThread())
        return 42

    runner.submit(
        "q",
        work,
        lambda r: results.append((r, QThread.currentThread() is qapp.thread())),
        lambda e: None,
    )
    qtbot.waitUntil(lambda: results != [], timeout=5000)
    assert results == [(42, True)]
    assert worker_threads[0] is not qapp.thread()
    qtbot.waitUntil(lambda: runner.pending_count() == 0, timeout=5000)


def test_exception_goes_to_error_callback(qtbot: QtBot):
    runner = BackgroundRunner()
    errors: list[Exception] = []
    runner.submit("q", _fail, lambda r: None, errors.append)
    qtbot.waitUntil(lambda: errors != [], timeout=5000)
    assert isinstance(errors[0], ValueError) and str(errors[0]) == "boom"


def test_stale_result_on_same_channel_is_dropped(qtbot: QtBot):
    runner = BackgroundRunner()
    release_slow = threading.Event()
    results: list[str] = []

    def slow() -> str:
        release_slow.wait(5)
        return "slow"

    runner.submit("q", slow, results.append, lambda e: None)
    runner.submit("q", lambda: "fast", results.append, lambda e: None)
    qtbot.waitUntil(lambda: results == ["fast"], timeout=5000)
    release_slow.set()
    qtbot.waitUntil(lambda: runner.pending_count() == 0, timeout=5000)
    assert results == ["fast"]


def test_channels_are_independent(qtbot: QtBot):
    runner = BackgroundRunner()
    results: list[str] = []
    runner.submit("a", lambda: "a", results.append, lambda e: None)
    runner.submit("b", lambda: "b", results.append, lambda e: None)
    qtbot.waitUntil(lambda: sorted(results) == ["a", "b"], timeout=5000)


def test_job_outliving_its_runner_is_harmless(qtbot: QtBot):
    runner = BackgroundRunner()
    release = threading.Event()
    finished = threading.Event()

    def work() -> int:
        release.wait(5)
        finished.set()
        return 1

    runner.submit("q", work, lambda r: None, lambda e: None)
    runner.deleteLater()
    del runner
    qtbot.wait(10)  # runner's C++ object is gone now
    release.set()
    qtbot.waitUntil(finished.is_set, timeout=5000)
    qtbot.wait(20)  # deliver (and drop) the queued result without crashing


def test_busy_reflects_latest_job_per_channel(qtbot: QtBot):
    runner = BackgroundRunner()
    release = threading.Event()
    runner.submit("q", lambda: release.wait(5), lambda r: None, lambda e: None)
    assert runner.is_busy("q") and not runner.is_busy("other")
    release.set()
    qtbot.waitUntil(lambda: not runner.is_busy("q"), timeout=5000)
