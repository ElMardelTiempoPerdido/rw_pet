"""自定义迭代器的柔性部件编辑器，使用角色设置的统一保存边界"""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ...i18n import tr
from ...shared.messages import Message
from ..graphics.face_assets import face_image, import_face_png, read_face_png
from ..soft_part_config import SOFT_PART_RANGES, SoftPart
from .inputs import ColorButton, WheelSafeComboBox, WheelSafeDoubleSpinBox
from .settings_style import NOTE_STYLE, parameter_group_background
from .form_layout import ContentForm


SOFT_PART_LABELS = (('soft_part_1', '启用柔性部件 1'), ('soft_part_2', '启用柔性部件 2'))
CHOICES = {
    'kind': (('rectangle', '矩形'), ('ellipse', '椭圆'), ('trapezoid', '梯形'),
             ('triangle', '三角形'), ('line', '圆端直线'), ('png', 'PNG 贴图')),
    'layer': (('back', '人偶后方'), ('front', '人偶前方')),
    'anchor': (('neck', '颈根（随胸肩）'), ('head', '头部'), ('waist', '腰部')),
}
PERCENT_FIELDS = ('softness', 'damping', 'tip_width_ratio')


class SoftPartEditor(QWidget):
    valueChanged = Signal(object)

    def __init__(self, title, value, directory, *, columns):
        super().__init__()
        self.directory = Path(directory)
        self._value, self._error = None, ''
        self.parameter_controls = {}
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        parameter_group_background(self)
        form = ContentForm(self)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(14)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.enabled = QCheckBox(title)
        self.parameter_controls['enabled'] = self.enabled
        form.addRow(self.enabled)
        self.enabled.toggled.connect(lambda v: self.change(enabled=v))

        def combo(column, label, name):
            control = self.parameter_controls[name] = WheelSafeComboBox()
            control.setSizeAdjustPolicy(WheelSafeComboBox.SizeAdjustPolicy.AdjustToContents)
            if name == 'kind':
                control.setFixedWidth(100)
            for key, text in CHOICES[name]:
                control.addItem(text, key)
            column.addRow(label, control)
            control.currentIndexChanged.connect(lambda: self.change(**{name: control.currentData()}))

        left, right = columns(form)
        combo(left, '外形', 'kind')
        combo(right, '图层', 'layer')
        left, right = columns(form)
        combo(left, '固定点', 'anchor')
        color = self.parameter_controls['color'] = ColorButton(value.color, '柔性部件颜色')
        color.setFixedWidth(100)
        right.addRow('颜色', color)
        color.valueChanged.connect(lambda v: self.change(color=v))
        for pair in ((('offset_x', 'X 偏移'), ('offset_y', 'Y 偏移')),
                     (('width', '宽度'), ('length', '长度')),
                     (('angle', '根部出发角度'), ('tip_width_ratio', '梯形末端宽度')),
                     (('softness', '柔软程度'), ('damping', '回摆衰减'))):
            pair_columns = columns(form)
            if pair[0][0] == 'width':
                self.dimensions_row = form.rowCount()-1
            for column, (name, label) in zip(pair_columns, pair):
                control = self.parameter_controls[name] = WheelSafeDoubleSpinBox()
                factor = 100 if name in PERCENT_FIELDS else 1
                low, high = SOFT_PART_RANGES[name]
                control.setRange(low*factor, high*factor)
                control.setDecimals(0 if factor == 100 else 1)
                control.setSingleStep(5 if factor == 100 or name == 'angle' else .5)
                control.setSuffix(' %' if factor == 100 else '°' if name == 'angle' else ' px')
                control.setFixedWidth(100)
                control.setKeyboardTracking(True)
                column.addRow(label, control)
                control.valueChanged.connect(lambda v, n=name, f=factor: self.change(**{n: v/f}))
        self.parameter_controls['angle'].setToolTip('0 沿固定部位朝脚的方向，正值顺时针旋转')
        self.parameter_controls['tip_width_ratio'].setToolTip('相对根部宽度的比例，仅影响梯形')
        self.parameter_controls['softness'].setToolTip('越高越容易弯折')
        self.parameter_controls['damping'].setToolTip('越高越快停止回摆')

        self.png_panel = QWidget()
        png = QVBoxLayout(self.png_panel)
        png.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(64, 64)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_label = QLabel()
        self.file_label.setTextFormat(Qt.TextFormat.PlainText)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.import_button = QPushButton('导入 PNG')
        self.clear_button = QPushButton('移除贴图')
        for button in (self.import_button, self.clear_button):
            button.setAutoDefault(False)
        row.addWidget(self.thumbnail)
        row.addWidget(self.file_label, 1)
        row.addWidget(self.import_button)
        row.addWidget(self.clear_button)
        png.addLayout(row)
        # note = QLabel('静态 PNG，宽高各为 1～128 像素，不超过 1 MB；顶边中点接根部，按原始像素尺寸显示，保留原色与透明度')
        # note.setWordWrap(True)
        # note.setStyleSheet(NOTE_STYLE)
        # png.addWidget(note)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.message.setStyleSheet('color: #ad7770;')
        png.addWidget(self.message)
        form.addRow(self.png_panel)
        self.parameter_controls['image_path'] = self.file_label
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
        if not isinstance(value, SoftPart):
            raise TypeError('Expected SoftPart')
        changed = value != self._value
        self._value, self._error = value, ''
        for name, control in self.parameter_controls.items():
            with QSignalBlocker(control):
                v = getattr(value, name)
                if name == 'enabled':
                    control.setChecked(v)
                elif name in CHOICES:
                    control.setCurrentIndex(control.findData(v))
                elif name != 'image_path':
                    control.setValue(v*100 if name in PERCENT_FIELDS else v)
        self.refresh()
        if changed:
            self.valueChanged.emit(value)

    def change(self, **values):
        # 保留尚未编辑参数的原始精度，不从所有输入框重新组装对象
        self._value = replace(self._value, **values)
        self._error = ''
        self.refresh()
        self.valueChanged.emit(self._value)

    def refresh(self):
        value = self._value
        png = value.kind == 'png'
        self.layout().setRowVisible(self.dimensions_row, not png)
        for name, control in self.parameter_controls.items():
            if name != 'enabled':
                control.setEnabled(value.enabled and (name != 'color' or not png)
                                   and (name != 'tip_width_ratio' or value.kind == 'trapezoid'))
        for name, options in CHOICES.items():
            control = self.parameter_controls[name]
            for index, (_, label) in enumerate(options):
                control.setItemText(index, tr(label))
        self.png_panel.setVisible(png)
        # 即使未启用，也允许先选择 PNG；导入成功后一次性启用并提交
        self.clear_button.setEnabled(bool(value.image_path))
        image = face_image(value.image_path, value.IMAGE_MAX_SIZE) if png else None
        self.thumbnail.setPixmap(QPixmap.fromImage(image).scaled(
            64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
            if image is not None and not image.isNull() else QPixmap())
        name = value.image_name or (Path(value.image_path).name if value.image_path else '')
        text = (Message('{name} - {width}×{height} px', name=name, width=image.width(), height=image.height())
                if image is not None and not image.isNull() else name or '尚未选择 PNG')
        self.file_label.setText(tr(text))
        self.file_label.setToolTip(value.image_path)
        error = self._error
        if not error and png and value.enabled and (image is None or image.isNull()):
            error = '请导入柔性部件 PNG、选择几何形状，或关闭此部件'
        self.message.setText(tr(error))
        self.message.setVisible(bool(error))
    def choose_file(self):
        source, _ = QFileDialog.getOpenFileName(self, tr('选择柔性部件 PNG'), '', 'PNG (*.png)',
                                               options=QFileDialog.Option.DontUseNativeDialog)
        if source:
            self.import_file(source)

    def import_file(self, source):
        try:
            value = replace(import_face_png(source, self.directory, self._value), kind='png')
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
                raise ValueError('请导入柔性部件 PNG、选择几何形状，或关闭此部件')
            read_face_png(self._value.image_path, self._value.IMAGE_MAX_SIZE)
