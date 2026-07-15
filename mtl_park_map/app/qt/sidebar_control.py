from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSpacerItem,
    QSizePolicy,
    QTimeEdit,
    QDateEdit,
    QPushButton,
    QFrame,
    QLabel,
    QCheckBox,
    QLineEdit,
)


class SideBarView(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent=parent)

        # Ui
        self.setObjectName("SideBarView")
        self.setFrameShape(QFrame.Shape.Box)
        self._le_label = QLabel("Address", self)
        self._le_address = QLineEdit(parent=self)
        self._le_address.setPlaceholderText("Enter Address (Optional)")
        self._start_t_edit = QTimeEdit(parent=self)
        self._end_t_edit = QTimeEdit(parent=self)
        self._date_edit = QDateEdit(parent=self)
        self._btn_apply = QPushButton("Apply")
        self._btn_clear = QPushButton("Clear")
        self._start_label = QLabel("Start", self)
        self._start_label.setContentsMargins(4, 0, 0, 0)
        self._end_label = QLabel("End", self)
        self._end_label.setContentsMargins(4, 0, 0, 0)
        self._chk_reserved = QCheckBox("Reserved", self)
        self._chk_not_in_range = QCheckBox("Not In Range", self)
        self._chk_include_free_parking = QCheckBox("Include Free Parking", self)
        self._chk_include_free_parking.setChecked(True)
        self._chk_include_paid_parking = QCheckBox("Include Paid Parking", self)

        # Layout
        self._v_layout = QVBoxLayout(self)
        self.setLayout(self._v_layout)

        self._dt_h_layout = QHBoxLayout(self)
        self._start_dt_v_layout = QVBoxLayout(self)
        self._end_dt_v_layout = QVBoxLayout(self)

        self._dt_h_layout.addLayout(self._start_dt_v_layout)
        self._dt_h_layout.addLayout(self._end_dt_v_layout)
        self._start_dt_v_layout.addWidget(self._start_label)
        self._start_dt_v_layout.addWidget(self._start_t_edit)
        self._end_dt_v_layout.addWidget(self._end_label)
        self._end_dt_v_layout.addWidget(self._end_t_edit)
        self._v_layout.addWidget(self._le_label)
        self._v_layout.addWidget(self._le_address)
        self._v_layout.addLayout(self._dt_h_layout)
        self._v_layout.addWidget(self._date_edit)
        self._v_layout.addWidget(self._chk_reserved)
        self._v_layout.addWidget(self._chk_not_in_range)
        self._v_layout.addWidget(self._chk_include_free_parking)
        self._v_layout.addWidget(self._chk_include_paid_parking)
        self._v_layout.addWidget(self._btn_apply)
        self._v_layout.addWidget(self._btn_clear)
        self._v_layout.addSpacerItem(
            QSpacerItem(
                0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
        )

        # Initial value
        self._start_t_edit.setTime(QTime.currentTime())
        self._end_t_edit.setTime(QTime.currentTime())
        self._date_edit.setDate(QDate.currentDate())

    @property
    def apply_button(self) -> QPushButton:
        return self._btn_apply

    @property
    def clear_button(self) -> QPushButton:
        return self._btn_clear

    @property
    def reserved(self) -> bool:
        return self._chk_reserved.isChecked()

    @property
    def not_in_range(self) -> bool:
        return self._chk_not_in_range.isChecked()

    @property
    def include_free_parking(self) -> bool:
        return self._chk_include_free_parking.isChecked()

    @property
    def include_paid_parking(self) -> bool:
        return self._chk_include_paid_parking.isChecked()

    @property
    def address(self) -> str:
        return self._le_address.text()

    def get_hour_range(self) -> tuple[float, float]:
        return (
            self._start_t_edit.time().msecsSinceStartOfDay() / 3600_000.0,
            self._end_t_edit.time().msecsSinceStartOfDay() / 3600_000.0,
        )

    def get_day(self) -> int:
        return self._date_edit.date().dayOfWeek()

    def get_month(self) -> int:
        return self._date_edit.date().month()

