"""Side panel: address search, layer/category toggles and the time window."""

import calendar
from collections.abc import Callable, Sequence
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
from mtl_park_map.ui.hotspots import Hotspot

_CATEGORY_LABELS = {
    SignCategory.permitted: "Parking permitted",
    SignCategory.prohibited: "No parking / no stopping",
    SignCategory.other: "Other",
}
# Combo index ↔ FilterState.reserved
_RESERVED_CHOICES: tuple[tuple[str, bool | None], ...] = (
    ("All signs", None),
    ("Reserved only", True),
    ("Exclude reserved", False),
)
# Abbreviated (Mon, Jan…) so the range rows fit a narrow dock.
# Combo index ↔ FilterState.strip_restricted
_STRIP_STATUS_CHOICES: tuple[tuple[str, bool | None], ...] = (
    ("All strips", None),
    ("Parkable only", False),
    ("No parking only", True),
)
_HOTSPOT_PLACEHOLDER = "Saved places…"
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
    address_cleared = Signal()  # the address field was emptied
    hotspot_save_requested = Signal()  # save the current address as a hotspot
    hotspot_selected = Signal(object)  # Hotspot picked from the list: go there
    hotspot_remove_requested = Signal(object)  # Hotspot to delete

    def __init__(self, now: Callable[[], datetime] = datetime.now, parent: QWidget | None = None):
        super().__init__(parent)
        self._now = now
        self._applied: FilterState | None = None

        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("Address or place in Montreal")
        self.address_edit.setClearButtonEnabled(True)
        self.address_edit.returnPressed.connect(self._request_address)
        self.address_edit.textChanged.connect(self._on_address_text_changed)
        self.find_button = QPushButton("Find")
        self.find_button.clicked.connect(self._request_address)
        self.save_hotspot_button = QPushButton("★")
        self.save_hotspot_button.setToolTip("Save the current address as a hotspot")
        self.save_hotspot_button.setFixedWidth(32)
        self.save_hotspot_button.setEnabled(False)
        self.save_hotspot_button.clicked.connect(self.hotspot_save_requested)
        self.hotspot_combo = QComboBox()
        self.hotspot_combo.setToolTip("Jump to a saved place")
        self.hotspot_combo.activated.connect(self._on_hotspot_activated)
        self.hotspot_combo.currentIndexChanged.connect(self._sync_remove_button)
        self.remove_hotspot_button = QPushButton("✕")
        self.remove_hotspot_button.setToolTip("Remove the selected hotspot")
        self.remove_hotspot_button.setFixedWidth(32)
        self.remove_hotspot_button.clicked.connect(self._request_hotspot_removal)
        self._hotspots: list[Hotspot] = []
        self.address_status = QLabel()
        self.address_status.setWordWrap(True)
        self.address_status.hide()

        self.show_signs = QCheckBox("Parking signs")
        self.show_spots = QCheckBox("Paid parking spots")
        self.show_strips = QCheckBox("No-parking curb strips")
        self.show_strips.setToolTip(
            "Curb stretches covered by no-parking signs with arrows, coloured by "
            "whether a rule applies during the window. Visible from street zoom."
        )

        self.category_checks = {c: QCheckBox(label) for c, label in _CATEGORY_LABELS.items()}
        self.strip_status_combo = QComboBox()
        self.strip_status_combo.setToolTip("Status during the selected time window")
        for label, _ in _STRIP_STATUS_CHOICES:
            self.strip_status_combo.addItem(label)
        self.include_inferred_strips = QCheckBox("Include inferred extents")
        self.include_inferred_strips.setToolTip(
            "Also use no-parking signs without arrows: their rule is assumed to cover "
            "the stretch their signs span, plus 10 m (drawn dashed)."
        )
        self.signs_ignore_time = QCheckBox("Any time (ignore the time window)")
        self.signs_ignore_time.setToolTip(
            "Show signs whatever their hours; paid spots and curb strips still use "
            "the time window."
        )
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
        self.reset_button.setToolTip(
            "Back to: permitted and no-parking signs, paid spots, next hour"
        )
        self.reset_button.clicked.connect(self._reset)

        self._build_layout()
        self._connect_dirty_tracking()
        self.set_state(default_filters(now()))
        self.set_hotspots([])

    # ------------------------------------------------------------------ public API

    def state(self) -> FilterState:
        """The filters as currently edited (not necessarily applied)."""
        return FilterState(
            show_signs=self.show_signs.isChecked(),
            show_spots=self.show_spots.isChecked(),
            show_strips=self.show_strips.isChecked(),
            strip_restricted=_STRIP_STATUS_CHOICES[self.strip_status_combo.currentIndex()][1],
            include_inferred_strips=self.include_inferred_strips.isChecked(),
            categories=frozenset(c for c, box in self.category_checks.items() if box.isChecked()),
            reserved=_RESERVED_CHOICES[self.reserved_combo.currentIndex()][1],
            hours=self._hours(),
            days=self._combo_range(self.days_row, self.day_start, self.day_end),
            months=self._combo_range(self.months_row, self.month_start, self.month_end),
            # Disabled while signs ignore time: it must not silently stay on.
            not_in_range=self.not_in_range.isChecked() and not self.signs_ignore_time.isChecked(),
            signs_ignore_time=self.signs_ignore_time.isChecked(),
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
        self.show_strips.setChecked(state.show_strips)
        strip_values = [value for _, value in _STRIP_STATUS_CHOICES]
        self.strip_status_combo.setCurrentIndex(strip_values.index(state.strip_restricted))
        self.include_inferred_strips.setChecked(state.include_inferred_strips)
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
        self.signs_ignore_time.setChecked(state.signs_ignore_time)
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
        address_row.addWidget(self.save_hotspot_button)
        hotspot_row = QHBoxLayout()
        hotspot_row.addWidget(self.hotspot_combo, 1)
        hotspot_row.addWidget(self.remove_hotspot_button)
        address_layout = QVBoxLayout(address_box)
        address_layout.addLayout(address_row)
        address_layout.addWidget(self.address_status)
        address_layout.addLayout(hotspot_row)

        show_box = QGroupBox("Show")
        show_layout = QVBoxLayout(show_box)
        show_layout.addWidget(self.show_signs)
        show_layout.addWidget(self.show_spots)
        show_layout.addWidget(self.show_strips)

        self.signs_box = QGroupBox("Signs")
        signs_layout = QVBoxLayout(self.signs_box)
        for box in self.category_checks.values():
            signs_layout.addWidget(box)
        reserved_form = QFormLayout()
        reserved_form.addRow("Reserved:", self.reserved_combo)
        signs_layout.addLayout(reserved_form)
        signs_layout.addWidget(self.signs_ignore_time)

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
        self.strips_box = QGroupBox("Curb strips")
        strips_form = QFormLayout(self.strips_box)
        strips_form.addRow("Show:", self.strip_status_combo)
        strips_form.addRow(self.include_inferred_strips)

        for box in (address_box, show_box, self.signs_box, self.strips_box, when_box):
            layout.addWidget(box)
        layout.addStretch(1)
        layout.addLayout(buttons)

    def _connect_dirty_tracking(self) -> None:
        """Re-evaluate the Apply button whenever any editor changes."""
        for box in (
            self.show_signs,
            self.show_spots,
            self.show_strips,
            self.not_in_range,
            self.signs_ignore_time,
            self.include_inferred_strips,
            self.hours_row.check,
            self.days_row.check,
            self.months_row.check,
            *self.category_checks.values(),
        ):
            box.toggled.connect(self._refresh)
        for combo in (
            self.reserved_combo,
            self.strip_status_combo,
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
        # "NOT active in this window" only concerns signs, which may ignore time.
        self.not_in_range.setEnabled(not self.signs_ignore_time.isChecked())
        self.strips_box.setEnabled(self.show_strips.isChecked())
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
                show_strips=current.show_strips,
                strip_restricted=current.strip_restricted,
                include_inferred_strips=current.include_inferred_strips,
                categories=current.categories,
                reserved=current.reserved,
                hours=now.hours,
                days=now.days,
                months=now.months,
                not_in_range=current.not_in_range,
                signs_ignore_time=current.signs_ignore_time,
            )
        )

    def _reset(self) -> None:
        """Restore the defaults and apply them immediately."""
        self.set_state(default_filters(self._now()))
        self.apply_requested.emit(self.state())

    def set_hotspots(self, hotspots: Sequence[Hotspot]) -> None:
        """Fill the saved-places list (no navigation happens).

        Args:
            hotspots: Saved places, in display order.
        """
        self._hotspots = list(hotspots)
        self.hotspot_combo.blockSignals(True)
        self.hotspot_combo.clear()
        self.hotspot_combo.addItem(_HOTSPOT_PLACEHOLDER)
        for hotspot in self._hotspots:
            self.hotspot_combo.addItem(hotspot.name)
        self.hotspot_combo.setCurrentIndex(0)
        self.hotspot_combo.blockSignals(False)
        self.hotspot_combo.setEnabled(bool(self._hotspots))
        self._sync_remove_button()

    def set_can_save_hotspot(self, enabled: bool) -> None:
        """Enable the ★ button (there is a current address to save).

        Args:
            enabled: Whether an address is pinned.
        """
        self.save_hotspot_button.setEnabled(enabled)

    def _selected_hotspot(self) -> Hotspot | None:
        """The hotspot chosen in the list, if any (index 0 is the placeholder)."""
        index = self.hotspot_combo.currentIndex()
        return self._hotspots[index - 1] if 0 < index <= len(self._hotspots) else None

    def _sync_remove_button(self) -> None:
        """✕ is only usable with a hotspot selected."""
        self.remove_hotspot_button.setEnabled(self._selected_hotspot() is not None)

    def _on_hotspot_activated(self, index: int) -> None:
        """The user picked an entry: go there (the placeholder does nothing).

        Args:
            index: Picked combo index.
        """
        if 0 < index <= len(self._hotspots):
            self.hotspot_selected.emit(self._hotspots[index - 1])

    def _request_hotspot_removal(self) -> None:
        """Ask to delete the selected hotspot."""
        hotspot = self._selected_hotspot()
        if hotspot is not None:
            self.hotspot_remove_requested.emit(hotspot)

    def _on_address_text_changed(self, text: str) -> None:
        """Announce an emptied address field (e.g. the clear button).

        Args:
            text: The new text.
        """
        if not text.strip():
            self.address_cleared.emit()

    def _request_address(self) -> None:
        """Emit a non-empty address search."""
        address = self.address_edit.text().strip()
        if address:
            self.address_requested.emit(address)
