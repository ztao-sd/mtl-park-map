from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget
from pytestqt.qtbot import QtBot

from mtl_park_map.ui.legend import Legend
from mtl_park_map.ui.palette import LAYER_SPECS


def test_lists_every_layer_top_first_then_the_pin(qtbot: QtBot):
    legend = Legend()
    qtbot.addWidget(legend)
    labels = [label.text() for label in legend.findChildren(QLabel)]
    assert labels == [spec.label for spec in reversed(LAYER_SPECS)] + ["Searched address"]
    assert not legend.grab().isNull()


def test_strips_get_a_line_swatch(qtbot: QtBot):
    legend = Legend()
    qtbot.addWidget(legend)
    strip_specs = [s for s in LAYER_SPECS if s.kind == "strip"]
    lines = [w for w in legend.findChildren(QWidget) if type(w).__name__ == "_LineSwatch"]
    assert len(lines) == len(strip_specs) == 4
    assert sorted(w.property("dashed") for w in lines) == [False, False, True, True]


def test_legend_collapses_to_its_header(qtbot: QtBot):
    legend = Legend()
    qtbot.addWidget(legend)
    legend.show()
    expanded = legend.sizeHint()
    labels = legend.findChildren(QLabel)
    with qtbot.waitSignal(legend.collapsed_changed, timeout=1000) as blocker:
        qtbot.mouseClick(legend.header, Qt.MouseButton.LeftButton)
    assert blocker.args == [True] and legend.collapsed
    assert not any(label.isVisible() for label in labels)
    assert legend.header.isVisible()
    assert legend.sizeHint().height() < expanded.height() / 3
    qtbot.mouseClick(legend.header, Qt.MouseButton.LeftButton)
    assert not legend.collapsed and all(label.isVisible() for label in labels)


def test_legend_can_start_collapsed(qtbot: QtBot):
    legend = Legend(collapsed=True)
    qtbot.addWidget(legend)
    assert legend.collapsed
