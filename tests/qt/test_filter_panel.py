from datetime import datetime, time

import pytest
from PySide6.QtCore import Qt, QTime
from pytestqt.qtbot import QtBot

from mtl_park_map.enums import SignCategory
from mtl_park_map.ui.filter_panel import FilterPanel
from mtl_park_map.ui.filters import FilterState, default_filters
from mtl_park_map.ui.hotspots import Hotspot

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
        show_strips=False,
        strip_restricted=False,
        include_inferred_strips=False,
        signs_ignore_time=True,
        categories=frozenset({SignCategory.prohibited, SignCategory.other}),
        reserved=False,
        hours=(time(22, 15), time(7, 0)),
        days=(6, 1),
        months=(9, 6),
        not_in_range=False,
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
    panel.category_checks[SignCategory.permitted].setChecked(False)
    panel.category_checks[SignCategory.other].setChecked(True)
    with qtbot.waitSignal(panel.apply_requested, timeout=1000) as blocker:
        qtbot.mouseClick(panel.apply_button, Qt.MouseButton.LeftButton)
    assert blocker.args[0].categories == frozenset(
        {SignCategory.prohibited, SignCategory.other}
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


def test_strips_toggle(panel: FilterPanel):
    assert panel.state().show_strips
    panel.show_strips.setChecked(False)
    assert not panel.state().show_strips


def test_strip_status_choice(panel: FilterPanel):
    assert panel.state().strip_restricted is None
    panel.strip_status_combo.setCurrentIndex(1)
    assert panel.state().strip_restricted is False  # parkable only
    panel.strip_status_combo.setCurrentIndex(2)
    assert panel.state().strip_restricted is True  # no parking only


def test_strips_box_follows_show_strips(panel: FilterPanel):
    panel.show_strips.setChecked(False)
    assert not panel.strips_box.isEnabled()
    panel.show_strips.setChecked(True)
    assert panel.strips_box.isEnabled()


def test_ignore_time_disables_the_not_in_window_toggle(panel: FilterPanel):
    assert not panel.state().signs_ignore_time
    panel.not_in_range.setChecked(True)
    panel.signs_ignore_time.setChecked(True)
    state = panel.state()
    assert state.signs_ignore_time
    assert not panel.not_in_range.isEnabled()
    # a disabled NOT toggle can't silently invert the (ignored) window
    assert not state.not_in_range
    panel.signs_ignore_time.setChecked(False)
    assert panel.not_in_range.isEnabled()


def test_inferred_strips_toggle(panel: FilterPanel):
    assert panel.state().include_inferred_strips
    panel.include_inferred_strips.setChecked(False)
    assert not panel.state().include_inferred_strips


# --- hotspots ------------------------------------------------------------------------

HOME = Hotspot("Home", -73.5797, 45.5240)
WORK = Hotspot("Work", -73.5787, 45.5069)


def test_hotspot_list_and_selection(qtbot: QtBot, panel: FilterPanel):
    panel.set_hotspots([HOME, WORK])
    combo = panel.hotspot_combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["Saved places…", "Home", "Work"]
    with qtbot.waitSignal(panel.hotspot_selected, timeout=1000) as blocker:
        combo.setCurrentIndex(2)
        combo.activated.emit(2)  # as when the user picks it
    assert blocker.args == [WORK]
    assert panel.remove_hotspot_button.isEnabled()


def test_programmatic_list_update_does_not_navigate(qtbot: QtBot, panel: FilterPanel):
    selected: list[Hotspot] = []
    panel.hotspot_selected.connect(selected.append)
    panel.set_hotspots([HOME])
    panel.set_hotspots([HOME, WORK])
    assert selected == []
    assert panel.hotspot_combo.currentIndex() == 0
    assert not panel.remove_hotspot_button.isEnabled()


def test_save_hotspot_button(qtbot: QtBot, panel: FilterPanel):
    assert not panel.save_hotspot_button.isEnabled()
    panel.set_can_save_hotspot(True)
    with qtbot.waitSignal(panel.hotspot_save_requested, timeout=1000):
        qtbot.mouseClick(panel.save_hotspot_button, Qt.MouseButton.LeftButton)


def test_remove_selected_hotspot(qtbot: QtBot, panel: FilterPanel):
    panel.set_hotspots([HOME, WORK])
    panel.hotspot_combo.setCurrentIndex(1)
    with qtbot.waitSignal(panel.hotspot_remove_requested, timeout=1000) as blocker:
        qtbot.mouseClick(panel.remove_hotspot_button, Qt.MouseButton.LeftButton)
    assert blocker.args == [HOME]


def test_clearing_the_address_is_announced(qtbot: QtBot, panel: FilterPanel):
    panel.address_edit.setText("somewhere")
    with qtbot.waitSignal(panel.address_cleared, timeout=1000):
        panel.address_edit.clear()
