"""柔性附件调试面板；仅修改本次场景，不写入用户配置"""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..soft_part_config import SOFT_ANCHORS, SOFT_PART_FIELDS, SOFT_PART_RANGES, SoftPart
from ..graphics.face_assets import face_image, import_face_png
from .inputs import ColorButton, WheelSafeComboBox, WheelSafeDoubleSpinBox

SHAPE_LABELS = (('rectangle', '矩形'), ('ellipse', '椭圆'), ('trapezoid', '梯形'),
                ('triangle', '三角形'), ('line', '圆端直线'), ('png', 'PNG 贴图'))


def demo_shape(shape):
    return replace(shape,
        soft_part_1=SoftPart(enabled=True, offset_x=-4., angle=-18., length=34., width=4., color='#f3a9ba'),
        soft_part_2=SoftPart(enabled=True, offset_x=4., angle=18., length=25., width=5., color='#8cd5d7'))


class SoftPartsDebugDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setWindowTitle('柔性部件调试')
        self.controls = {}
        self.png_widgets = {}
        self.errors = {}
        self._control_key = None
        self.assets = TemporaryDirectory(prefix='rw-soft-parts-')
        assets = self.assets
        self.destroyed.connect(lambda: assets.cleanup())
        layout = QVBoxLayout(self)
        note = QLabel('仅用于自定义迭代器；调整仅在本次调试中生效\n'
                      'PNG 顶边中点连接根部，按原始像素尺寸显示；拖动、漫游沿用主窗口控制')
        note.setWordWrap(True)
        layout.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        columns = QHBoxLayout(content)
        columns.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        self.groups = []
        for index, name in enumerate(SOFT_PART_FIELDS):
            group = QGroupBox(f'柔性部件 {index+1}')
            self.groups.append(group)
            form = QFormLayout(group)
            values = getattr(window.scene.config.custom_appearance, name)
            controls = self.controls[name] = {}
            enabled = controls['enabled'] = QCheckBox('启用')
            enabled.setChecked(values.enabled)
            form.addRow(enabled)
            for key, label, options in (('kind', '外形', SHAPE_LABELS),
                                        ('layer', '图层', (('back', '人偶后方'), ('front', '人偶前方')))):
                control = controls[key] = WheelSafeComboBox()
                for option, title in options:
                    control.addItem(title, option)
                control.setCurrentIndex(control.findData(getattr(values, key)))
                form.addRow(label, control)
                control.currentIndexChanged.connect(
                    lambda _, n=name, k=key, c=control: self.change(n, k, c.currentData()))
            anchor = controls['anchor'] = WheelSafeComboBox()
            for key, label in zip(SOFT_ANCHORS, ('颈根（随胸肩）', '头部', '腰部')):
                anchor.addItem(label, key)
            anchor.setCurrentIndex(anchor.findData(values.anchor))
            form.addRow('固定点', anchor)
            for key, label in (('offset_x', 'X 偏移'), ('offset_y', 'Y 偏移'), ('angle', '根部出发角度'),
                               ('length', '长度'), ('width', '宽度'), ('softness', '柔软程度'),
                               ('damping', '回摆衰减'), ('tip_width_ratio', '梯形末端宽度')):
                control = controls[key] = WheelSafeDoubleSpinBox()
                factor = 100 if key in ('softness', 'damping', 'tip_width_ratio') else 1
                low, high = SOFT_PART_RANGES[key]
                control.setRange(low*factor, high*factor)
                control.setDecimals(0 if factor == 100 else 1)
                control.setSingleStep(5 if factor == 100 or key == 'angle' else .5)
                control.setSuffix(' %' if factor == 100 else '°' if key == 'angle' else ' px')
                control.setValue(getattr(values, key)*factor)
                form.addRow(label, control)
                control.valueChanged.connect(lambda v, n=name, k=key, f=factor: self.change(n, k, v/f))
            color = controls['color'] = ColorButton(values.color, f'柔性部件 {index+1} 颜色')
            form.addRow('颜色', color)
            color.valueChanged.connect(lambda v, n=name: self.change(n, 'color', v))
            png = QWidget()
            png_layout = QVBoxLayout(png)
            png_layout.setContentsMargins(0, 0, 0, 0)
            thumbnail = QLabel()
            thumbnail.setFixedSize(64, 64)
            filename = QLabel()
            filename.setWordWrap(True)
            buttons = QHBoxLayout()
            browse, clear = QPushButton('选择 PNG…'), QPushButton('清除 PNG')
            buttons.addWidget(browse)
            buttons.addWidget(clear)
            png_layout.addWidget(thumbnail)
            png_layout.addWidget(filename)
            png_layout.addLayout(buttons)
            png_layout.addWidget(QLabel('1～128 像素，静态 PNG，保留原色和透明度'))
            error = QLabel()
            error.setWordWrap(True)
            error.setStyleSheet('color: #b04040')
            png_layout.addWidget(error)
            self.png_widgets[name] = png, thumbnail, filename, error, clear
            form.addRow(png)
            browse.clicked.connect(lambda _, n=name: self.choose_file(n))
            clear.clicked.connect(lambda _, n=name: self.clear_file(n))
            anchor.currentIndexChanged.connect(lambda _, n=name, c=anchor: self.change(n, 'anchor', c.currentData()))
            enabled.toggled.connect(lambda v, n=name: self.change(n, 'enabled', v))
            columns.addWidget(group, 1)
        layout.addWidget(scroll)
        self.status = QLabel()
        layout.addWidget(self.status)
        reset = QPushButton('重置部件姿态')
        reset.clicked.connect(self.reset_parts)
        layout.addWidget(reset)
        self.refresh_status()
        workarea = self.screen().availableGeometry()
        self.resize(min(820, workarea.width()-40), min(780, workarea.height()-60))

    def change(self, name, key, value):
        scene = self.owner.scene
        if scene.config.body_appearance != 'custom':
            return
        self.set_part(name, replace(getattr(scene.config.custom_appearance, name), **{key: value}))

    def set_part(self, name, value):
        scene = self.owner.scene
        shape = replace(scene.config.custom_appearance, **{name: value})
        scene.config = replace(scene.config, custom_appearance=shape)
        scene.soft_parts.sync(scene)
        self.errors.pop(name, None)
        self.owner.refresh()

    def choose_file(self, name):
        source, _ = QFileDialog.getOpenFileName(self, '选择柔性部件 PNG', '', 'PNG (*.png)',
                                               options=QFileDialog.Option.DontUseNativeDialog)
        if source:
            self.import_file(name, source)

    def import_file(self, name, source):
        part = getattr(self.owner.scene.config.custom_appearance, name)
        try:
            value = import_face_png(source, self.assets.name, part)
        except (OSError, ValueError) as exc:
            self.errors[name] = f'导入失败：{exc}'
            self.refresh_status()
            return False
        self.set_part(name, replace(value, kind='png'))
        return True

    def clear_file(self, name):
        part = getattr(self.owner.scene.config.custom_appearance, name)
        self.set_part(name, replace(part, image_path='', image_name=''))

    def reset_parts(self):
        self.owner.scene.soft_parts.reset(self.owner.scene)
        self.owner.refresh()

    def refresh_controls(self, scene, active):
        for group, (slot, controls) in zip(self.groups, self.controls.items()):
            group.setEnabled(active)
            part = getattr(scene.config.custom_appearance, slot)
            for key in ('width', 'length'):
                group.layout().setRowVisible(controls[key], part.kind != 'png')
            for key, control in controls.items():
                # 导入/重置也经过同一配置源，避免面板仍显示上一份值
                value = getattr(part, key)
                with QSignalBlocker(control):
                    if key == 'enabled':
                        control.setChecked(value)
                    elif key in ('kind', 'layer', 'anchor'):
                        control.setCurrentIndex(control.findData(value))
                    elif key == 'color':
                        control.setValue(value)
                    else:
                        control.setValue(value*(100 if key in ('softness', 'damping', 'tip_width_ratio') else 1))
                if key != 'enabled':
                    control.setEnabled(part.enabled and (key != 'color' or part.kind != 'png')
                                       and (key != 'tip_width_ratio' or part.kind == 'trapezoid'))
            png, thumbnail, filename, error, clear = self.png_widgets[slot]
            png.setVisible(part.kind == 'png')
            png.setEnabled(part.enabled)
            texture = face_image(part.image_path, part.IMAGE_MAX_SIZE) if part.kind == 'png' else None
            if texture is not None and not texture.isNull():
                thumbnail.setPixmap(QPixmap.fromImage(texture).scaled(
                    64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
            else:
                thumbnail.clear()
            filename.setText(part.image_name or (Path(part.image_path).name if part.image_path else '未选择 PNG'))
            filename.setToolTip(part.image_path)
            clear.setEnabled(bool(part.image_path))
            message = self.errors.get(slot, '')
            if not message and part.kind == 'png' and part.enabled and (texture is None or texture.isNull()):
                message = '请选择有效的 PNG；当前部件暂不显示'
            error.setText(message)
            error.setVisible(bool(message))

    def refresh_status(self):
        scene = self.owner.scene
        active = scene.config.body_appearance == 'custom'
        key = active, scene.config.custom_appearance, tuple(self.errors.items())
        if key != self._control_key:
            self.refresh_controls(scene, active)
            self._control_key = key
        if not active:
            self.status.setText('当前为 Bell；请使用自定义迭代器配置，或运行 tools/oracle/debug_soft_parts.py')
        else:
            self.status.setText(' / '.join(f'部件 {i+1}：'+('关闭' if part is None else
                f'{len(part.points)} 节点，'+('休眠' if part.sleeping else '运动中'))
                for i, part in enumerate(scene.soft_parts.parts)))
