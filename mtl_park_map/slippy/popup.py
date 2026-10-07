"""Leaflet-style info popup floating above a map point."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

_MAX_WIDTH = 300


class MapPopup(QFrame):
    """A small card with rich text and a close button.

    The owning map positions it; this widget only renders content.

    Args:
        parent: The map widget the popup floats over.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("MapPopup")
        self.setStyleSheet(
            "#MapPopup { background: white; border: 1px solid #d1d5db; border-radius: 8px; }"
            "#MapPopup QLabel { color: #1f2937; }"
            "#MapPopup QToolButton { border: none; color: #6b7280; font-size: 14px; }"
            "#MapPopup QToolButton:hover { color: #111827; }"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(shadow)

        self._label = QLabel(self)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(_MAX_WIDTH)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._label.setOpenExternalLinks(True)

        close = QToolButton(self)
        close.setText("×")
        close.setToolTip("Close")
        close.setCursor(Qt.CursorShape.ArrowCursor)
        close.clicked.connect(self.hide)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 6, 10)
        layout.setSpacing(4)
        layout.addWidget(self._label, 1)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.hide()

    def set_html(self, html: str) -> None:
        """Replace the content and resize to fit.

        Args:
            html: Rich text (Qt's HTML subset); callers must escape untrusted text.
        """
        self._label.setText(html)
        self.adjustSize()

    def text(self) -> str:
        """The current rich-text content."""
        return self._label.text()
