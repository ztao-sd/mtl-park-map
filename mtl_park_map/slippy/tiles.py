"""Asynchronous raster-tile loading with a disk cache and an in-memory LRU.

Respects the OSM tile usage policy: identifying ``User-Agent``, HTTP caching honoured
via :class:`QNetworkDiskCache`, and only tiles that are actually visible are fetched
(:meth:`TileLoader.prune` aborts requests for tiles scrolled out of view).
"""

import time
from collections import OrderedDict
from collections.abc import Callable, Collection
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QUrl, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkDiskCache,
    QNetworkReply,
    QNetworkRequest,
)

from mtl_park_map.slippy.projection import TILE_SIZE
from mtl_park_map.slippy.viewport import TileKey

_DISK_CACHE_BYTES = 256 * 1024 * 1024


class TileLoader(QObject):
    """Fetches tiles by :class:`TileKey` and keeps recently used ones in memory.

    Args:
        url_template: URL with ``{z}``, ``{x}``, ``{y}`` placeholders (any scheme
            QtNetwork supports, including ``file://`` for tests/offline tiles).
        user_agent: ``User-Agent`` header sent with every request.
        cache_dir: Directory for the HTTP disk cache, or ``None`` for no disk cache.
        memory_tiles: Max decoded tiles kept in memory.
        retry_after_s: How long a failed tile is not re-requested.
        clock: Monotonic time source (injectable for tests).
        parent: Qt parent.
    """

    tile_loaded = Signal(object)  # TileKey
    tile_failed = Signal(object)  # TileKey

    def __init__(
        self,
        url_template: str,
        user_agent: str,
        cache_dir: Path | None = None,
        memory_tiles: int = 512,
        retry_after_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._url_template = url_template
        self._user_agent = user_agent.encode()
        self._memory_tiles = memory_tiles
        self._retry_after_s = retry_after_s
        self._clock = clock
        self._nam = QNetworkAccessManager(self)
        # PySide6 6.10 pitfalls, both of which abort the process when the loader is
        # destroyed: (1) calling reply.deleteLater() from Python, and (2) slots that
        # capture a reply in a closure (lambda / functools.partial on
        # `reply.finished`). So Qt deletes finished replies itself, and the reply
        # reaches us as an argument of the manager's `finished` signal.
        self._nam.setAutoDeleteReplies(True)
        self._nam.finished.connect(self._on_finished)
        if cache_dir is not None:
            disk_cache = QNetworkDiskCache(self)
            disk_cache.setCacheDirectory(str(cache_dir))
            disk_cache.setMaximumCacheSize(_DISK_CACHE_BYTES)
            self._nam.setCache(disk_cache)
        self._pixmaps: OrderedDict[TileKey, QPixmap] = OrderedDict()
        self._pending: dict[TileKey, QNetworkReply] = {}
        self._failed_at: dict[TileKey, float] = {}

    def tile(self, key: TileKey) -> QPixmap | None:
        """A loaded tile from memory (marking it recently used).

        Args:
            key: The tile.

        Returns:
            The decoded tile, or ``None`` if it is not in memory.
        """
        pixmap = self._pixmaps.get(key)
        if pixmap is not None:
            self._pixmaps.move_to_end(key)
        return pixmap

    def fallback(self, key: TileKey, max_levels: int = 4) -> tuple[QPixmap, QRectF] | None:
        """The closest in-memory ancestor tile region covering ``key``.

        Drawn scaled up while ``key`` itself is loading, so zooming shows a blurry
        preview instead of an empty grid.

        Args:
            key: The tile that is missing.
            max_levels: How many zoom levels up to search.

        Returns:
            ``(ancestor_pixmap, source_rect)`` where ``source_rect`` is the part of the
            ancestor covering ``key``, or ``None``.
        """
        ancestor = key
        for level in range(1, max_levels + 1):
            if ancestor.z == 0:
                return None
            ancestor = ancestor.parent()
            pixmap = self._pixmaps.get(ancestor)
            if pixmap is not None:
                n = 2**level
                size = TILE_SIZE / n
                source = QRectF((key.x % n) * size, (key.y % n) * size, size, size)
                return pixmap, source
        return None

    def is_pending(self, key: TileKey) -> bool:
        """Whether a request for ``key`` is in flight.

        Args:
            key: The tile.

        Returns:
            True while the tile is being fetched.
        """
        return key in self._pending

    def pending_count(self) -> int:
        """Number of requests in flight."""
        return len(self._pending)

    def request(self, key: TileKey) -> None:
        """Fetch ``key`` unless it is in memory, in flight, or recently failed.

        Completion is reported via :attr:`tile_loaded` / :attr:`tile_failed`.

        Args:
            key: The tile to fetch.
        """
        if key in self._pixmaps or key in self._pending:
            return
        failed_at = self._failed_at.get(key)
        if failed_at is not None:
            if self._clock() - failed_at < self._retry_after_s:
                return
            del self._failed_at[key]

        url = self._url_template.format(z=key.z, x=key.x, y=key.y)
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", self._user_agent)
        # Serve fresh cached tiles without revalidating (HTTP expiry still honoured).
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.PreferCache,
        )
        self._pending[key] = self._nam.get(request)

    def prune(self, keep: Collection[TileKey]) -> None:
        """Abort in-flight requests for tiles no longer needed.

        Args:
            keep: Tiles still wanted (typically the visible ones).
        """
        for key in [k for k in self._pending if k not in keep]:
            # abort() emits `finished` synchronously; _on_finished ignores it because
            # the key is no longer pending.
            self._pending.pop(key).abort()

    def _on_finished(self, reply: QNetworkReply) -> None:
        """Decode a finished reply into the memory cache.

        Args:
            reply: The finished network reply.
        """
        # Linear scan is fine: only the visible tiles (a few dozen) are ever pending.
        key = next((k for k, r in self._pending.items() if r is reply), None)
        if key is None:
            return  # aborted by prune(): neither loaded nor failed
        del self._pending[key]

        image = QImage()
        if reply.error() != QNetworkReply.NetworkError.NoError or not image.loadFromData(
            reply.readAll()
        ):
            self._failed_at[key] = self._clock()
            self.tile_failed.emit(key)
            return

        self._pixmaps[key] = QPixmap.fromImage(image)
        while len(self._pixmaps) > self._memory_tiles:
            self._pixmaps.popitem(last=False)
        self.tile_loaded.emit(key)
