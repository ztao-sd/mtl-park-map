"""Map legend overlay."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QWidget

from mtl_park_map.slippy.map_widget import paint_pin
from mtl_park_map.ui.palette import LAYER_SPECS

_SWATCH_PX = 12
_PIN_SCALE = 0.5  # 16 px tall


class _Swatch(QWidget):
    """A coloured dot matching the map markers.

    Args:
        color: Fill colour ``#rrggbb``.
    """

    def __init__(self, color: str):
        super().__init__()
        self._color = QColor(color)
        self.setFixedSize(_SWATCH_PX, _SWATCH_PX)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the dot with the markers' white outline."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("white"))
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.end()


class _PinSwatch(QWidget):
    """A small copy of the map's address pin."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(_SWATCH_PX, round(32 * _PIN_SCALE))

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the pin with its tip at the bottom centre."""
        painter = QPainter(self)
        paint_pin(painter, self.width() / 2, self.height() - 0.5, _PIN_SCALE)
        painter.end()


class Legend(QFrame):
    """What each marker colour means (top layer first)."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Legend")
        self.setStyleSheet(
            "#Legend { background: rgba(255, 255, 255, 235); border: 1px solid #d1d5db;"
            " border-radius: 8px; }"
            "#Legend QLabel { color: #374151; font-size: 12px; }"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)
        specs = list(reversed(LAYER_SPECS))
        for row, spec in enumerate(specs):
            layout.addWidget(_Swatch(spec.color), row, 0, Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(QLabel(spec.label), row, 1)
        layout.addWidget(_PinSwatch(), len(specs), 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QLabel("Searched address"), len(specs), 1)
