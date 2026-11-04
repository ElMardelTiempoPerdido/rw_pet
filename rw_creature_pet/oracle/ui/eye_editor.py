"""设置与面部预览共用的单眼编辑器，修改统一归入外观草稿"""
from dataclasses import replace

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QWidget

from ...i18n import tr
from ..eye_config import EYE_KINDS, EyeAppearance
from .settings_style import parameter_group_background
from .inputs import ColorButton, WheelSafeComboBox

EYE_LABELS = {'eye_1': '眼睛1', 'eye_2': '眼睛2'}
EYE_STATES = (('闭眼', False), ('睁眼', True))
EYE_HEIGHTS = (('通常', 'normal'), ('较低', 'lower'))


class EyeEditor(QWidget):
    valueChanged = Signal(object)

    def __init__(self, title, value):
        super().__init__()
        parameter_group_background(self)
        self._value = None
        form = QFormLayout(self)
        form.setContentsMargins(12, 12, 12, 12)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.visible = QCheckBox('显示')
        form.addRow(QLabel(title), self.visible)
        self.kind = WheelSafeComboBox()
        self.kind.setFixedWidth(100)
        for data, label in EYE_KINDS:
            self.kind.addItem(tr(label), data)
        form.addRow('眼睛形态', self.kind)
        self.color = ColorButton(value.color, title)
        self.color.setFixedWidth(110)
        form.addRow('颜色', self.color)
        self.state = WheelSafeComboBox()
        self.state.setFixedWidth(100)
        for label, data in EYE_STATES:
            self.state.addItem(tr(label), data)
        form.addRow('默认状态', self.state)
        self.height_mode = WheelSafeComboBox()
        self.height_mode.setFixedWidth(100)
        for label, data in EYE_HEIGHTS:
            self.height_mode.addItem(tr(label), data)
        form.addRow('眼位高度', self.height_mode)
        self.visible.toggled.connect(lambda visible: self.change(visible=visible))
        self.kind.currentIndexChanged.connect(lambda: self.change(kind=self.kind.currentData()))
        self.color.valueChanged.connect(lambda color: self.change(color=color))
        self.state.currentIndexChanged.connect(lambda: self.change(default_open=self.state.currentData()))
        self.height_mode.currentIndexChanged.connect(lambda: self.change(height_mode=self.height_mode.currentData()))
        self.setValue(value)

    def value(self):
        return self._value

    def setValue(self, value):
        if not isinstance(value, EyeAppearance):
            raise TypeError('Expected EyeAppearance')
        if value == self._value:
            return
        self._value = value
        blockers = [QSignalBlocker(widget) for widget in (self.visible, self.kind, self.color, self.state, self.height_mode)]
        self.visible.setChecked(value.visible)
        self.kind.setCurrentIndex(self.kind.findData(value.kind))
        self.color.setValue(value.color)
        self.state.setCurrentIndex(self.state.findData(value.default_open))
        self.height_mode.setCurrentIndex(self.height_mode.findData(value.height_mode))
        del blockers
        self.refresh()
        self.valueChanged.emit(value)

    def change(self, **values):
        self.setValue(replace(self._value, **values))

    def refresh(self):
        self.kind.setEnabled(self._value.visible)
        self.color.setEnabled(self._value.visible)
        self.state.setEnabled(self._value.visible)
        self.height_mode.setEnabled(self._value.visible)
        for control in (self.state, self.height_mode):
            self.layout().setRowVisible(control, self._value.kind == 'normal')
        for index, (_, label) in enumerate(EYE_KINDS):
            self.kind.setItemText(index, tr(label))
        for index, (label, _) in enumerate(EYE_STATES):
            self.state.setItemText(index, tr(label))
        for index, (label, _) in enumerate(EYE_HEIGHTS):
            self.height_mode.setItemText(index, tr(label))
