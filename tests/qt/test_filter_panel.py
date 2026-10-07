from datetime import datetime, time

import pytest
from PySide6.QtCore import Qt, QTime
from pytestqt.qtbot import QtBot

from mtl_park_map.enums import SignCategory
from mtl_park_map.ui.filter_panel import FilterPanel
from mtl_park_map.ui.filters import FilterState, default_filters

NOW = datetime(2026, 10, 6, 10, 7)  # a Tuesday


@pytest.fixture
def panel(qtbot: QtBot) -> FilterPanel:
    widget = FilterPanel(now=lambda: NOW)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_starts_with_defaults(panel: FilterPanel):
    assert panel.state() == default_filters(NOW)


def test_set_state_round_trip(panel: FilterPanel):
    state = FilterState(
        show_signs=True,
        show_spots=False,
        categories=frozenset({SignCategory.prohibited, SignCategory.other}),
        reserved=False,
        hours=(time(22, 15), time(7, 0)),
        days=(6, 1),
        months=(9, 6),
        not_in_range=True,
    )
    panel.set_state(state)
    assert panel.state() == state


def test_disabled_dimensions_are_none_and_not_editable(panel: FilterPanel):
    panel.hours_row.check.setChecked(False)
    panel.months_row.check.setChecked(False)
    state = panel.state()
    assert state.hours is None and state.months is None and state.days == (2, 2)
    assert not panel.hour_start.isEnabled()
    assert panel.day_start.isEnabled()


def test_apply_enabled_only_when_dirty(panel: FilterPanel):
    panel.mark_applied(panel.state())
    assert not panel.apply_button.isEnabled()
    panel.show_spots.setChecked(False)
    assert panel.apply_button.isEnabled()
    assert "•" in panel.apply_button.text()
    panel.show_spots.setChecked(True)
    assert not panel.apply_button.isEnabled()


def test_apply_emits_edited_state(qtbot: QtBot, panel: FilterPanel):
    panel.category_checks[SignCategory.prohibited].setChecked(True)
    with qtbot.waitSignal(panel.apply_requested, timeout=1000) as blocker:
        qtbot.mouseClick(panel.apply_button, Qt.MouseButton.LeftButton)
    assert blocker.args[0].categories == frozenset(
        {SignCategory.permitted, SignCategory.prohibited}
    )


def test_reset_restores_defaults_and_applies(qtbot: QtBot, panel: FilterPanel):
    panel.show_signs.setChecked(False)
    panel.days_row.check.setChecked(False)
    with qtbot.waitSignal(panel.apply_requested, timeout=1000) as blocker:
        qtbot.mouseClick(panel.reset_button, Qt.MouseButton.LeftButton)
    assert blocker.args[0] == default_filters(NOW)
    assert panel.state() == default_filters(NOW)


def test_now_button_fills_time_window_only(qtbot: QtBot, panel: FilterPanel):
    panel.show_spots.setChecked(False)
    panel.hours_row.check.setChecked(False)
    panel.hour_start.setTime(QTime(1, 0))
    qtbot.mouseClick(panel.now_button, Qt.MouseButton.LeftButton)
    state = panel.state()
    assert state.hours == (time(10, 7), time(11, 7))
    assert not state.show_spots  # untouched


def test_signs_box_follows_show_signs(panel: FilterPanel):
    panel.show_signs.setChecked(False)
    assert not panel.signs_box.isEnabled()
    panel.show_signs.setChecked(True)
    assert panel.signs_box.isEnabled()


def test_address_search(qtbot: QtBot, panel: FilterPanel):
    received: list[str] = []
    panel.address_requested.connect(received.append)
    qtbot.keyClicks(panel.address_edit, "   ")
    qtbot.keyClick(panel.address_edit, Qt.Key.Key_Return)
    assert received == []  # blank searches are ignored
    panel.address_edit.setText("  845 Sherbrooke  ")
    qtbot.keyClick(panel.address_edit, Qt.Key.Key_Return)
    assert received == ["845 Sherbrooke"]


def test_address_status(panel: FilterPanel):
    panel.set_address_status("Address not found", error=True)
    assert panel.address_status.isVisible()
    assert panel.address_status.text() == "Address not found"
    panel.set_address_status(None)
    assert not panel.address_status.isVisible()
