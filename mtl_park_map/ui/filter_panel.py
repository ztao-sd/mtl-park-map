"""Side panel: address search, layer/category toggles and the time window."""

import calendar
from collections.abc import Callable
from datetime import datetime, time

from PySide6.QtCore import QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from mtl_park_map.enums import SignCategory
from mtl_park_map.ui.filters import FilterState, IntRange, TimeRange, default_filters

_CATEGORY_LABELS = {
    SignCategory.permitted: "Parking permitted",
    SignCategory.prohibited: "No parking",
    SignCategory.other: "Other",
}
# Combo index ↔ FilterState.reserved
_RESERVED_CHOICES: tuple[tuple[str, bool | None], ...] = (
    ("All signs", None),
    ("Reserved only", True),
    ("Exclude reserved", False),
)
# Abbreviated (Mon, Jan…) so the range rows fit a narrow dock.
_DAY_NAMES = list(calendar.day_abbr)  # Monday first, matching ISO weekday 1
_MONTH_NAMES = list(calendar.month_abbr)[1:]


def _to_qtime(t: time) -> QTime:
    """Convert a Python time of day to ``QTime`` (minute precision)."""
    return QTime(t.hour, t.minute)


def _from_qtime(t: QTime) -> time:
    """Convert a ``QTime`` to a Python time of day (minute precision)."""
    return time(t.hour(), t.minute())


class _RangeRow(QWidget):
    """An enable checkbox plus a start → end pair of editors.

    Args:
        label: Checkbox text.
        start: Start editor.
        end: End editor.
        parent: Qt parent.
    """

    def __init__(self, label: str, start: QWidget, end: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.check = QCheckBox(label)
        self.check.toggled.connect(self._sync_enabled)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.check)
        layout.addStretch(1)
        layout.addWidget(start)
        layout.addWidget(QLabel("→"))
        layout.addWidget(end)
        self._editors = (start, end)
        self._sync_enabled(False)

    def _sync_enabled(self, enabled: bool) -> None:
        """Editors are only editable while the dimension is filtered."""
        for editor in self._editors:
            editor.setEnabled(enabled)


class FilterPanel(QWidget):
    """Edits a :class:`FilterState`; emits it when the user presses Apply.

    Apply is only enabled when the edited state differs from the applied one.

    Args:
        now: Clock for the default / "Now" time window (injectable for tests).
        parent: Qt parent.
    """

    apply_requested = Signal(object)  # FilterState
    address_requested = Signal(str)

    def __init__(self, now: Callable[[], datetime] = datetime.now, parent: QWidget | None = None):
        super().__init__(parent)
        self._now = now
        self._applied: FilterState | None = None

        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("Address or place in Montreal")
        self.address_edit.setClearButtonEnabled(True)
        self.address_edit.returnPressed.connect(self._request_address)
        self.find_button = QPushButton("Find")
        self.find_button.clicked.connect(self._request_address)
        self.address_status = QLabel()
        self.address_status.setWordWrap(True)
        self.address_status.hide()

        self.show_signs = QCheckBox("Parking signs")
        self.show_spots = QCheckBox("Paid parking spots")

        self.category_checks = {c: QCheckBox(label) for c, label in _CATEGORY_LABELS.items()}
        self.reserved_combo = QComboBox()
        for label, _ in _RESERVED_CHOICES:
            self.reserved_combo.addItem(label)

        self.now_button = QPushButton("Now")
        self.now_button.setToolTip("Set the window to the next hour, today")
        self.now_button.clicked.connect(self._set_now)
        self.hour_start, self.hour_end = QTimeEdit(), QTimeEdit()
        for edit in (self.hour_start, self.hour_end):
            edit.setDisplayFormat("HH:mm")
        self.day_start, self.day_end = QComboBox(), QComboBox()
        self.month_start, self.month_end = QComboBox(), QComboBox()
        for combo in (self.day_start, self.day_end):
            combo.addItems(_DAY_NAMES)
        for combo in (self.month_start, self.month_end):
            combo.addItems(_MONTH_NAMES)
        self.hours_row = _RangeRow("Hours", self.hour_start, self.hour_end)
        self.days_row = _RangeRow("Days", self.day_start, self.day_end)
        self.months_row = _RangeRow("Months", self.month_start, self.month_end)
        self.not_in_range = QCheckBox("Signs NOT active in this window")
        self.not_in_range.setToolTip(
            "Invert the time filter, e.g. find signs whose restriction is lifted"
        )

        self.apply_button = QPushButton("Apply")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(lambda: self.apply_requested.emit(self.state()))
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Back to: permitted signs and spots, next hour")
        self.reset_button.clicked.connect(self._reset)

        self._build_layout()
        self._connect_dirty_tracking()
        self.set_state(default_filters(now()))

    # ------------------------------------------------------------------ public API

    def state(self) -> FilterState:
        """The filters as currently edited (not necessarily applied)."""
        return FilterState(
            show_signs=self.show_signs.isChecked(),
            show_spots=self.show_spots.isChecked(),
            categories=frozenset(c for c, box in self.category_checks.items() if box.isChecked()),
            reserved=_RESERVED_CHOICES[self.reserved_combo.currentIndex()][1],
            hours=self._hours(),
            days=self._combo_range(self.days_row, self.day_start, self.day_end),
            months=self._combo_range(self.months_row, self.month_start, self.month_end),
            not_in_range=self.not_in_range.isChecked(),
        )

    def set_state(self, state: FilterState) -> None:
        """Load filters into the editors.

        Disabled dimensions keep their editors' previous values, so re-enabling one
        restores what the user had.

        Args:
            state: The filters to show.
        """
        self.show_signs.setChecked(state.show_signs)
        self.show_spots.setChecked(state.show_spots)
        for category, box in self.category_checks.items():
            box.setChecked(category in state.categories)
        reserved_values = [value for _, value in _RESERVED_CHOICES]
        self.reserved_combo.setCurrentIndex(reserved_values.index(state.reserved))
        self.hours_row.check.setChecked(state.hours is not None)
        if state.hours is not None:
            self.hour_start.setTime(_to_qtime(state.hours[0]))
            self.hour_end.setTime(_to_qtime(state.hours[1]))
        self._set_combo_range(self.days_row, self.day_start, self.day_end, state.days)
        self._set_combo_range(self.months_row, self.month_start, self.month_end, state.months)
        self.not_in_range.setChecked(state.not_in_range)
        self._refresh()

    def mark_applied(self, state: FilterState) -> None:
        """Record what is currently shown on the map (for the dirty indicator).

        Args:
            state: The applied filters.
        """
        self._applied = state
        self._refresh()

    def set_address_status(self, text: str | None, error: bool = False) -> None:
        """Show a message under the address field.

        Args:
            text: Message, or ``None`` to hide it.
            error: Style it as an error.
        """
        if text is None:
            self.address_status.hide()
            return
        self.address_status.setText(text)
        self.address_status.setStyleSheet(f"color: {'#dc2626' if error else '#6b7280'};")
        self.address_status.show()

    # ------------------------------------------------------------------- internals

    def _build_layout(self) -> None:
        """Arrange the widgets top to bottom."""
        address_box = QGroupBox("Find address")
        address_row = QHBoxLayout()
        address_row.addWidget(self.address_edit, 1)
        address_row.addWidget(self.find_button)
        address_layout = QVBoxLayout(address_box)
        address_layout.addLayout(address_row)
        address_layout.addWidget(self.address_status)

        show_box = QGroupBox("Show")
        show_layout = QVBoxLayout(show_box)
        show_layout.addWidget(self.show_signs)
        show_layout.addWidget(self.show_spots)

        self.signs_box = QGroupBox("Signs")
        signs_layout = QVBoxLayout(self.signs_box)
        for box in self.category_checks.values():
            signs_layout.addWidget(box)
        reserved_form = QFormLayout()
        reserved_form.addRow("Reserved:", self.reserved_combo)
        signs_layout.addLayout(reserved_form)

        when_box = QGroupBox("When")
        when_layout = QVBoxLayout(when_box)
        when_layout.addWidget(self.hours_row)
        when_layout.addWidget(self.days_row)
        when_layout.addWidget(self.months_row)
        when_layout.addWidget(self.not_in_range)
        now_row = QHBoxLayout()
        now_row.addStretch(1)
        now_row.addWidget(self.now_button)
        when_layout.addLayout(now_row)

        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.apply_button, 1)

        layout = QVBoxLayout(self)
        for box in (address_box, show_box, self.signs_box, when_box):
            layout.addWidget(box)
        layout.addStretch(1)
        layout.addLayout(buttons)

    def _connect_dirty_tracking(self) -> None:
        """Re-evaluate the Apply button whenever any editor changes."""
        for box in (
            self.show_signs,
            self.show_spots,
            self.not_in_range,
            self.hours_row.check,
            self.days_row.check,
            self.months_row.check,
            *self.category_checks.values(),
        ):
            box.toggled.connect(self._refresh)
        for combo in (
            self.reserved_combo,
            self.day_start,
            self.day_end,
            self.month_start,
            self.month_end,
        ):
            combo.currentIndexChanged.connect(self._refresh)
        for edit in (self.hour_start, self.hour_end):
            edit.timeChanged.connect(self._refresh)

    def _refresh(self) -> None:
        """Sync dependent enabled states and the Apply button's dirty marker."""
        self.signs_box.setEnabled(self.show_signs.isChecked())
        dirty = self.state() != self._applied
        self.apply_button.setEnabled(dirty)
        self.apply_button.setText("Apply •" if dirty and self._applied is not None else "Apply")

    def _hours(self) -> TimeRange | None:
        """The hour range, if enabled."""
        if not self.hours_row.check.isChecked():
            return None
        return _from_qtime(self.hour_start.time()), _from_qtime(self.hour_end.time())

    @staticmethod
    def _combo_range(row: _RangeRow, start: QComboBox, end: QComboBox) -> IntRange | None:
        """A 1-based index range from two combos, if enabled."""
        if not row.check.isChecked():
            return None
        return start.currentIndex() + 1, end.currentIndex() + 1

    @staticmethod
    def _set_combo_range(
        row: _RangeRow, start: QComboBox, end: QComboBox, value: IntRange | None
    ) -> None:
        """Load a 1-based index range into two combos (or disable the row)."""
        row.check.setChecked(value is not None)
        if value is not None:
            start.setCurrentIndex(value[0] - 1)
            end.setCurrentIndex(value[1] - 1)

    def _set_now(self) -> None:
        """Fill (and enable) hours, day and month from the clock; keep the rest."""
        now = default_filters(self._now())
        current = self.state()
        self.set_state(
            FilterState(
                show_signs=current.show_signs,
                show_spots=current.show_spots,
                categories=current.categories,
                reserved=current.reserved,
                hours=now.hours,
                days=now.days,
                months=now.months,
                not_in_range=current.not_in_range,
            )
        )

    def _reset(self) -> None:
        """Restore the defaults and apply them immediately."""
        self.set_state(default_filters(self._now()))
        self.apply_requested.emit(self.state())

    def _request_address(self) -> None:
        """Emit a non-empty address search."""
        address = self.address_edit.text().strip()
        if address:
            self.address_requested.emit(address)
