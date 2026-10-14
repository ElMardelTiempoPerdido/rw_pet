"""两个面部贴图槽位的草稿编辑；导入副本不改变运行中的人偶"""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QFileDialog, QGridLayout, QLabel, QPushButton, QSizePolicy, QWidget

from ...i18n import tr
from ...shared.messages import Message
from ..face_config import FACE_OFFSET_LIMIT, FaceDecal
from ..graphics.face_assets import face_image, import_face_png, read_face_png
from .inputs import WheelSafeDoubleSpinBox


class FaceDecalEditor(QWidget):
    valueChanged = Signal(object)

    def __init__(self, title, value, directory):
        super().__init__()
        self.directory = Path(directory)
        self._value, self._error = None, ''
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(12)
        self.enabled = QCheckBox(title)
        self.import_button = QPushButton('导入 PNG')
        self.clear_button = QPushButton('移除贴图')
        for button in (self.import_button, self.clear_button):
            button.setAutoDefault(False)
        layout.addWidget(self.enabled, 0, 0, 1, 3)
        layout.addWidget(self.import_button, 0, 3)
        layout.addWidget(self.clear_button, 0, 4)
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(40, 40)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setStyleSheet('background-color: #c8c8c8; border: 1px solid #707070;')
        self.file_label = QLabel()
        self.file_label.setTextFormat(Qt.TextFormat.PlainText)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.thumbnail, 1, 0)
        layout.addWidget(self.file_label, 1, 1, 1, 4)
        self.x_input, self.y_input = WheelSafeDoubleSpinBox(), WheelSafeDoubleSpinBox()
        for control in (self.x_input, self.y_input):
            control.setRange(-FACE_OFFSET_LIMIT, FACE_OFFSET_LIMIT)
            control.setDecimals(2)
            control.setSingleStep(.5)
            control.setSuffix(' px')
            control.setKeyboardTracking(True)
            control.setFixedWidth(100)
        layout.addWidget(QLabel('X 偏移'), 2, 0, 1, 2)
        layout.addWidget(self.x_input, 2, 2)
        layout.addWidget(QLabel('Y 偏移'), 2, 3)
        layout.addWidget(self.y_input, 2, 4)
        layout.setColumnStretch(1, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setStyleSheet('color: #ad7770;')
        layout.addWidget(self.message, 3, 0, 1, 5)
        self.enabled.toggled.connect(lambda value: self.change(enabled=value))
        self.x_input.valueChanged.connect(lambda value: self.change(offset_x=value))
        self.y_input.valueChanged.connect(lambda value: self.change(offset_y=value))
        self.import_button.clicked.connect(self.choose_file)
        self.clear_button.clicked.connect(lambda: self.setValue(replace(
            self._value, enabled=False, image_path='', image_name='')))
        self.setValue(value)

    @property
    def dynamic_text_widgets(self):
        return self.file_label, self.message

    def value(self):
        return self._value

    def setValue(self, value):
        if not isinstance(value, FaceDecal):
            raise TypeError('Expected FaceDecal')
        if value == self._value:
            self._error = ''
            self.refresh()
            return
        changed = value != self._value
        self._value, self._error = value, ''
        blockers = [QSignalBlocker(control) for control in (self.enabled, self.x_input, self.y_input)]
        self.enabled.setChecked(value.enabled)
        self.x_input.setValue(value.offset_x)
        self.y_input.setValue(value.offset_y)
        del blockers
        self.refresh()
        if changed:
            self.valueChanged.emit(value)

    def change(self, **values):
        self._value = replace(self._value, **values)
        self.refresh()
        self.valueChanged.emit(self._value)

    def refresh(self):
        value = self._value
        image = face_image(value.image_path)
        self.thumbnail.setPixmap(QPixmap.fromImage(image) if not image.isNull() else QPixmap())
        self.clear_button.setEnabled(bool(value.image_path))
        self.x_input.setEnabled(bool(value.image_path))
        self.y_input.setEnabled(bool(value.image_path))
        name = value.image_name or Path(value.image_path).name
        text = (Message('{name} - {width}×{height} px', name=name, width=image.width(), height=image.height())
                if not image.isNull() else name or '尚未选择 PNG')
        self.file_label.setText(tr(text))
        self.file_label.setToolTip(value.image_path)
        error = self._error or ('贴图不可用，请重新导入或关闭此贴图' if value.image_path and image.isNull() else '')
        self.message.setText(tr(error))
        self.message.setVisible(bool(error))

    def choose_file(self):
        source, _ = QFileDialog.getOpenFileName(self, tr('选择面部 PNG'), '', 'PNG (*.png)',
                                               options=QFileDialog.Option.DontUseNativeDialog)
        if source:
            self.import_file(source)

    def import_file(self, source):
        try:
            value = import_face_png(source, self.directory, self._value)
        except (OSError, ValueError) as exc:
            self._error = Message('导入失败：{error}', error=exc)
            self.refresh()
            return False
        unchanged = value == self._value
        self.setValue(value)
        if unchanged:
            self.valueChanged.emit(value)  # 同路径重新导入也可能恢复丢失的托管文件
        return True

    def validate(self):
        if self._value.enabled:
            if not self._value.image_path:
                raise ValueError('请导入面部 PNG，或关闭尚未配置的贴图')
            read_face_png(self._value.image_path)
