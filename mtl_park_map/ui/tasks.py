"""Run blocking work (queries, geocoding) off the GUI thread.

Results come back on the GUI thread through a queued signal. Each job belongs to a
*channel*; submitting a new job on a channel supersedes older ones, whose results are
silently dropped — so a slow, outdated query can never overwrite a newer one.
"""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from typing import cast

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _JobSignals(QObject):
    """Signals a worker emits; delivered queued to the runner on the GUI thread."""

    succeeded = Signal(int, object)  # job id, result
    failed = Signal(int, object)  # job id, exception


class _Job(QRunnable):
    """A callable executed on the thread pool.

    Args:
        job_id: Identifier echoed back in the signals.
        fn: The work.
        signals: Where to report the outcome.
    """

    def __init__(self, job_id: int, fn: Callable[[], object], signals: _JobSignals):
        super().__init__()
        self._job_id = job_id
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        """Execute the work and report its result or exception."""
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 — any failure is reported to the caller
            self._signals.failed.emit(self._job_id, exc)
        else:
            self._signals.succeeded.emit(self._job_id, result)


@dataclass(frozen=True, slots=True)
class _Pending:
    """Bookkeeping for a submitted job."""

    channel: str
    on_done: Callable[[object], None]
    on_error: Callable[[Exception], None]


class BackgroundRunner(QObject):
    """Thread-pool job runner with per-channel "latest wins" semantics.

    Args:
        pool: Thread pool to use; defaults to the global one.
        parent: Qt parent.
    """

    def __init__(self, pool: QThreadPool | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._pool = pool or QThreadPool.globalInstance()
        # Created on the GUI thread and connected to bound methods of this GUI-thread
        # object, so emissions from workers are queued onto the GUI thread.
        # Deliberately *not* parented to the runner: every job holds a reference, so
        # a job outliving the runner (window closed mid-geocode) emits on a live
        # object whose connections Qt already dropped, instead of a deleted one.
        self._signals = _JobSignals()
        self._signals.succeeded.connect(self._on_succeeded)
        self._signals.failed.connect(self._on_failed)
        self._ids = count(1)
        self._pending: dict[int, _Pending] = {}
        self._latest: dict[str, int] = {}

    def submit[T](
        self,
        channel: str,
        fn: Callable[[], T],
        on_done: Callable[[T], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """Run ``fn`` on the pool; deliver its outcome unless superseded.

        Args:
            channel: Jobs on the same channel supersede each other.
            fn: Blocking work; must not touch widgets.
            on_done: Called on the GUI thread with the result.
            on_error: Called on the GUI thread with the raised exception.
        """
        job_id = next(self._ids)
        self._latest[channel] = job_id
        # T is erased once stored; the signal round-trip hands back the same object.
        self._pending[job_id] = _Pending(
            channel, lambda result: on_done(cast(T, result)), on_error
        )
        self._pool.start(_Job(job_id, fn, self._signals))

    def is_busy(self, channel: str) -> bool:
        """Whether the latest job on ``channel`` has not finished yet.

        Args:
            channel: The channel.

        Returns:
            True while its newest job is running or queued.
        """
        latest = self._latest.get(channel)
        return latest is not None and latest in self._pending

    def pending_count(self) -> int:
        """Jobs submitted but not yet finished (including superseded ones)."""
        return len(self._pending)

    def _take(self, job_id: int) -> _Pending | None:
        """Forget a finished job; return it only if it is its channel's latest.

        Args:
            job_id: The finished job.

        Returns:
            The job's callbacks, or ``None`` if it was superseded.
        """
        pending = self._pending.pop(job_id)
        return pending if self._latest.get(pending.channel) == job_id else None

    def _on_succeeded(self, job_id: int, result: object) -> None:
        """Deliver a result on the GUI thread."""
        pending = self._take(job_id)
        if pending is not None:
            pending.on_done(result)

    def _on_failed(self, job_id: int, error: Exception) -> None:
        """Deliver an exception on the GUI thread."""
        pending = self._take(job_id)
        if pending is not None:
            pending.on_error(error)
