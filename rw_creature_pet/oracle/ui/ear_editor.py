"""设置与预览复用的耳机部件编辑器"""
from dataclasses import replace
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QFileDialog, QLabel

from ...i18n import tr
from ...shared.messages import Message
from ..ear_config import EarPart
from ..graphics.face_assets import face_image, import_face_png, read_face_png
from .face_editor import FaceDecalEditor
from .inputs import WheelSafeComboBox, WheelSafeDoubleSpinBox

EAR_LABELS = {'ear_body': '耳机主体', 'ear_part_1': '耳机配件 1',
              'ear_part_2': '耳机配件 2', 'ear_part_3': '耳机配件 3'}
SHAPE_LABELS = (('ellipse', '椭圆'), ('rectangle', '矩形'), ('trapezoid', '梯形'),
                ('triangle', '三角形'), ('line', '直线'), ('png', 'PNG 贴图'))
TONE_LABELS = (('shell', '附件底色'), ('highlight', '附件高光'), ('split', '双面色'))


class EarPartEditor(FaceDecalEditor):
    def __init__(self, title, value, directory):
        super().__init__(title, value, directory)
        layout = self.layout()
        layout.removeWidget(self.message)
        layout.addWidget(self.message, 8, 0, 1, 5)
        self.kind = WheelSafeComboBox()
        self.tone = WheelSafeComboBox()
        for widget, options in ((self.kind, SHAPE_LABELS), (self.tone, TONE_LABELS)):
            for key, label in options:
                widget.addItem(label, key)
        layout.addWidget(QLabel('形状'), 4, 0)
        layout.addWidget(self.kind, 4, 1, 1, 2)
        layout.addWidget(QLabel('配色'), 4, 3)
        layout.addWidget(self.tone, 4, 4)
        self.width_input, self.height_input, self.rotation_input = (
            WheelSafeDoubleSpinBox() for _ in range(3))
        for control in (self.width_input, self.height_input, self.rotation_input):
            control.setDecimals(2)
            control.setSingleStep(.5)
            control.setFixedWidth(100)
            control.setRange(.5, 32.)
            control.setSuffix(' px')
        self.rotation_input.setRange(-180., 180.)
        self.rotation_input.setSingleStep(5.)
        self.rotation_input.setSuffix('°')
        layout.addWidget(QLabel('宽度'), 5, 0, 1, 2)
        layout.addWidget(self.width_input, 5, 2)
        layout.addWidget(QLabel('高度'), 5, 3)
        layout.addWidget(self.height_input, 5, 4)
        layout.addWidget(QLabel('旋转'), 6, 0, 1, 2)
        layout.addWidget(self.rotation_input, 6, 2)
        note = QLabel('以耳侧中心为原点，X 向外、Y 向下；左右镜像。直线的宽度为线宽，高度为长度')
        note.setWordWrap(True)
        layout.addWidget(note, 7, 0, 1, 5)
        self.kind.currentIndexChanged.connect(lambda: self.change(kind=self.kind.currentData()))
        self.tone.currentIndexChanged.connect(lambda: self.change(tone=self.tone.currentData()))
        for name, control in (('width', self.width_input), ('height', self.height_input), ('rotation', self.rotation_input)):
            control.valueChanged.connect(lambda value, field=name: self.change(**{field: value}))
        self.sync_inputs()

    def setValue(self, value):
        if not isinstance(value, EarPart):
            raise TypeError('Expected EarPart')
        if value == self._value:
            super().setValue(value)
            return
        super().setValue(value)
        if hasattr(self, 'kind'):
            self.sync_inputs()

    def sync_inputs(self):
        pairs = ((self.width_input, self._value.width), (self.height_input, self._value.height),
                 (self.rotation_input, self._value.rotation))
        for widget, value in pairs:
            with QSignalBlocker(widget):
                widget.setValue(value)
        for widget, value in ((self.kind, self._value.kind), (self.tone, self._value.tone)):
            with QSignalBlocker(widget):
                widget.setCurrentIndex(widget.findData(value))
        self.refresh()

    def refresh(self):
        super().refresh()
        self.x_input.setEnabled(True)
        self.y_input.setEnabled(True)
        png = self._value.kind == 'png'
        for widget in (self.thumbnail, self.file_label, self.clear_button):
            widget.setVisible(png)
        if not png and not self._error:
            self.message.hide()
        if hasattr(self, 'kind'):
            self.tone.setEnabled(not png)
            for widget, options in ((self.kind, SHAPE_LABELS), (self.tone, TONE_LABELS)):
                for index, (_, label) in enumerate(options):
                    widget.setItemText(index, tr(label))

    def choose_file(self):
        source, _ = QFileDialog.getOpenFileName(self, tr('选择耳机 PNG'), '', 'PNG (*.png)',
                                               options=QFileDialog.Option.DontUseNativeDialog)
        if source:
            self.import_file(source)

    def import_file(self, source):
        try:
            value = import_face_png(source, self.directory, self._value)
            image = face_image(value.image_path)
            value = replace(value, kind='png', width=float(image.width()), height=float(image.height()))
        except (OSError, ValueError) as exc:
            self._error = Message('导入失败：{error}', error=exc)
            self.refresh()
            return False
        unchanged = value == self._value
        self.setValue(value)
        if unchanged:
            self.valueChanged.emit(value)
        return True

    def validate(self):
        if self._value.enabled and self._value.kind == 'png':
            if not self._value.image_path:
                raise ValueError('请导入耳机 PNG、选择几何形状，或关闭此部件')
            read_face_png(self._value.image_path)
