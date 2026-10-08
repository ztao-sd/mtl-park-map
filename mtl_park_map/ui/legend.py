"""Map legend overlay, collapsible to its header."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QToolButton, QVBoxLayout, QWidget

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


class _LineSwatch(QWidget):
    """A short stroke matching the map's curb strips.

    The ``dashed`` Qt property tells inferred-extent swatches apart.

    Args:
        color: Stroke colour ``#rrggbb``.
        dashed: Draw it dashed, like strips whose extent was inferred.
    """

    def __init__(self, color: str, dashed: bool = False):
        super().__init__()
        self._color = QColor(color)
        self.setProperty("dashed", dashed)
        self.setFixedSize(_SWATCH_PX + 10, _SWATCH_PX)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw a thick horizontal stroke (rounded, or dashed)."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self._color, 4.0)
        if self.property("dashed"):
            pen.setDashPattern([1.5, 1.0])
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        else:
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        y = self.height() / 2
        painter.drawLine(3, round(y), self.width() - 3, round(y))
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
    """What each marker and strip colour means (top layer first).

    Clicking the header collapses it to just the header, to free up map space.

    Args:
        collapsed: Start collapsed.
    """

    collapsed_changed = Signal(bool)

    def __init__(self, collapsed: bool = False) -> None:
        super().__init__()
        self.setObjectName("Legend")
        self.setStyleSheet(
            "#Legend { background: rgba(255, 255, 255, 235); border: 1px solid #d1d5db;"
            " border-radius: 8px; }"
            "#Legend QLabel { color: #374151; font-size: 12px; }"
            "#Legend QToolButton { border: none; color: #111827; font-size: 12px;"
            " font-weight: 600; }"
        )
        self.header = QToolButton()
        self.header.setText("Legend")
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setCursor(Qt.CursorShape.ArrowCursor)
        self.header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.header.clicked.connect(lambda: self.set_collapsed(not self._collapsed))

        self._rows = QWidget()
        grid = QGridLayout(self._rows)
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        specs = list(reversed(LAYER_SPECS))
        for row, spec in enumerate(specs):
            swatch = (
                _LineSwatch(spec.color, spec.dashed) if spec.kind == "strip" else _Swatch(spec.color)
            )
            grid.addWidget(swatch, row, 0, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(QLabel(spec.label), row, 1)
        grid.addWidget(_PinSwatch(), len(specs), 0, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(QLabel("Searched address"), len(specs), 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 12, 8)
        layout.setSpacing(0)
        layout.addWidget(self.header, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._rows)

        self._collapsed = not collapsed  # force the first sync below
        self.set_collapsed(collapsed)

    @property
    def collapsed(self) -> bool:
        """Whether only the header is shown."""
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """Show or hide the entries (the header stays).

        Args:
            collapsed: ``True`` to keep only the header.
        """
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._rows.setVisible(not collapsed)
        self.header.setArrowType(
            Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow
        )
        self.header.setToolTip("Show the legend" if collapsed else "Hide the legend")
        self.adjustSize()
        self.collapsed_changed.emit(collapsed)
