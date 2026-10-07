from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from mtl_park_map.ui.legend import Legend
from mtl_park_map.ui.palette import LAYER_SPECS


def test_lists_every_layer_top_first_then_the_pin(qtbot: QtBot):
    legend = Legend()
    qtbot.addWidget(legend)
    labels = [label.text() for label in legend.findChildren(QLabel)]
    assert labels == [spec.label for spec in reversed(LAYER_SPECS)] + ["Searched address"]
    assert not legend.grab().isNull()
