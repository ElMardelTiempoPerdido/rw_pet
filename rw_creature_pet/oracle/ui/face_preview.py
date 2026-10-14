"""静态面部预览，与桌宠共用绘制入口，留出耳机附件的局部空间"""
from math import ceil
from dataclasses import replace
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from ...i18n import WidgetTexts, language_manager, tr
from ...shared.geometry import Vec2
from ..graphics.render import OracleRenderer
from ..ear_config import ear_radius
from .ear_editor import EAR_LABELS, EarPartEditor
from .face_editor import FaceDecalEditor
from .eye_editor import EYE_LABELS, EyeEditor
from .inputs import WheelSafeComboBox
from .settings_style import apply_settings_style, settings_font

VIEWS = (('正面', (0., 0.)), ('向左看', (-.8, 0.)), ('向右看', (.8, 0.)),
         ('抬头', (0., -.65)), ('低头', (0., .65)))
EYE_PREVIEWS = (('默认表情', 'default'), ('全部睁眼', 'open'), ('全部闭眼', 'closed'))


class FacePreviewCanvas(QWidget):
    LOGICAL_SIZE = 64  # 头部两侧及上下均留空间，后续耳机仍共用此画布

    def __init__(self, *, magnified=False):
        super().__init__()
        self.image = QImage()
        self.magnified = magnified
        self.setMinimumHeight(120 if magnified else 72)
        self.setMinimumWidth(160)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#17242d'))
        if self.image.isNull():
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        dpr = self.devicePixelRatioF()
        factor = max(1, int(min((self.width()-8)*dpr/self.image.width(),
                               (self.height()-8)*dpr/self.image.height()))) if self.magnified else 1
        w, h = self.image.width()*factor, self.image.height()*factor
        left = round((self.width()*dpr-w)/2)/dpr
        top = round((self.height()*dpr-h)/2)/dpr
        painter.drawImage(QRectF(left, top, w/dpr, h/dpr), self.image)


class FacePreviewDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('面部预览')
        self.setModal(False)
        self.renderer = OracleRenderer()
        self.settings = parent
        self._status_message = ''
        self.shape, self.outfit = None, 'normal'
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        tools = QHBoxLayout()
        self.view = WheelSafeComboBox()
        for label, gaze in VIEWS:
            self.view.addItem(label, gaze)
        self.scale = WheelSafeComboBox()
        for value in (1., 1.5, 2.):
            self.scale.addItem(f'{value:g}×', value)
        self.eye_state = WheelSafeComboBox()
        self.eye_state.setSizeAdjustPolicy(WheelSafeComboBox.SizeAdjustPolicy.AdjustToContents)
        for label, mode in EYE_PREVIEWS:
            self.eye_state.addItem(label, mode)
        tools.addWidget(QLabel('视角'))
        tools.addWidget(self.view, 1)
        tools.addWidget(QLabel('显示倍率'))
        tools.addWidget(self.scale)
        tools.addWidget(self.eye_state)
        layout.addLayout(tools)
        split = self.split = QSplitter(Qt.Orientation.Horizontal)
        view_panel = QWidget()
        views = QVBoxLayout(view_panel)
        views.setContentsMargins(0, 0, 0, 0)
        self.actual_label = QLabel('实际大小')
        views.addWidget(self.actual_label)
        self.actual = FacePreviewCanvas()
        views.addWidget(self.actual)
        views.addWidget(QLabel('放大检查'))
        self.magnified = FacePreviewCanvas(magnified=True)
        views.addWidget(self.magnified, 1)
        split.addWidget(view_panel)
        self.editors = QTabWidget()
        self.editors.setMinimumWidth(410)
        split.addWidget(self.editors)
        split.setChildrenCollapsible(False)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([440, 480])
        layout.addWidget(split, 1)
        self.face_editors, self.ear_editors = {}, {}
        self.eye_editors = {}
        eye_page = QWidget()
        eye_layout = QVBoxLayout(eye_page)
        eye_hint = QLabel('正面排列：眼睛1 / 眼睛2；编号随头部固定，转头或旋转时不交换')
        eye_hint.setWordWrap(True)
        eye_layout.addWidget(eye_hint)
        for name, source in parent.eye_editors.items():
            editor = EyeEditor(EYE_LABELS[name], source.value())
            self.bind_editor(source, editor)
            self.eye_editors[name] = editor
            eye_layout.addWidget(editor)
        state_hint = QLabel('默认睁眼保持睁开；默认闭眼仍可在观察或互动时短暂睁开；隐藏的眼睛不显示')
        state_hint.setWordWrap(True)
        eye_layout.addWidget(state_hint)
        eye_layout.addStretch(1)
        self.add_editor_page('眼睛', eye_page)
        face_page = QWidget()
        face_layout = QVBoxLayout(face_page)
        for name, source in parent.face_editors.items():
            title = '额头标记 PNG' if name == 'forehead' else '面部装饰 PNG'
            editor = FaceDecalEditor(title, source.value(), source.directory)
            self.bind_editor(source, editor)
            self.face_editors[name] = editor
            face_layout.addWidget(editor)
        face_layout.addStretch(1)
        self.add_editor_page('面部贴图', face_page)
        ear_page = QWidget()
        ear_layout = QVBoxLayout(ear_page)
        self.ear_selector = WheelSafeComboBox()
        self.ear_stack = QStackedWidget()
        for name, source in parent.ear_editors.items():
            self.ear_selector.addItem(EAR_LABELS[name], name)
            editor = EarPartEditor(EAR_LABELS[name], source.value(), source.directory)
            self.bind_editor(source, editor)
            self.ear_editors[name] = editor
            panel = QWidget()
            column = QVBoxLayout(panel)
            column.setContentsMargins(0, 0, 0, 0)
            column.addWidget(editor)
            column.addStretch(1)
            self.ear_stack.addWidget(panel)
        self.ear_selector.currentIndexChanged.connect(self.ear_stack.setCurrentIndex)
        ear_layout.addWidget(self.ear_selector)
        ear_layout.addWidget(self.ear_stack, 1)
        self.add_editor_page('耳机部件', ear_page)
        hint = QLabel('两处编辑同步；点击“保存并应用”后写入配置并更新桌宠，关闭预览保留未保存的编辑')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.status, 1)
        self.apply_button = QPushButton('保存并应用')
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(lambda: parent.save(close=False))
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)
        for signal in (self.view.currentIndexChanged, self.scale.currentIndexChanged, self.eye_state.currentIndexChanged):
            signal.connect(self.render_preview)
        apply_settings_style(self)
        dynamic = tuple(widget for editor in (*self.face_editors.values(), *self.ear_editors.values())
                        for widget in editor.dynamic_text_widgets)
        self._texts = WidgetTexts(self, exclude=(self.status, *dynamic))
        language_manager().changed.connect(self.retranslate)
        self.retranslate()
        self.resize(1040, 720)
        screen = parent.screen()
        if screen is not None:
            area = screen.availableGeometry()
            if area.width()-24 < 760:
                self.set_compact(True)
            self.resize(min(self.width(), area.width()-24), min(self.height(), area.height()-24))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_compact(self.width() < 760)

    def set_compact(self, compact):
        orientation = Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal
        if self.split.orientation() != orientation:
            self.split.setOrientation(orientation)
            self.actual_label.setVisible(not compact)
            self.actual.setVisible(not compact)
            self.split.setSizes([180, 360] if compact else [440, 480])

    def set_status(self, message):
        self._status_message = message
        self.status.setText(tr(message))

    def bind_editor(self, source, mirror):
        # 设置页是草稿的权威入口；相等值不再发信号，避免回写和光标跳动
        source.valueChanged.connect(mirror.setValue)
        mirror.valueChanged.connect(source.setValue)
        mirror.valueChanged.connect(self.settings.queue_face_preview)

    def add_editor_page(self, title, panel):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        area.setWidget(panel)
        self.editors.addTab(area, title)

    def sync_editing(self):
        idle = self.settings.form.isEnabled()
        self.editors.setEnabled(idle and self.shape is not None)
        self.apply_button.setEnabled(idle)

    def retranslate(self):
        self._texts.retranslate()
        for index, (label, _) in enumerate(VIEWS):
            self.view.setItemText(index, tr(label))
        for index, label in enumerate(EAR_LABELS.values()):
            self.ear_selector.setItemText(index, tr(label))
        for index, (label, _) in enumerate(EYE_PREVIEWS):
            self.eye_state.setItemText(index, tr(label))
        for editor in (*self.face_editors.values(), *self.ear_editors.values(), *self.eye_editors.values()):
            editor.refresh()
        self.status.setText(tr(self._status_message))
        self.setFont(settings_font())

    def set_appearance(self, colors, shape, outfit):
        self.renderer.colors, self.shape, self.outfit = colors, shape, outfit
        self.sync_editing()
        self.render_preview()

    def render_preview(self, *args):
        scale = self.scale.currentData()
        size = round(max(FacePreviewCanvas.LOGICAL_SIZE, ceil(ear_radius(self.shape)*2+4))*scale)
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.translate(size/2, size/2)
            painter.scale(scale, scale)
            mode, shape = self.eye_state.currentData(), self.shape
            if mode == 'closed' and shape is not None:
                shape = replace(shape, **{name: replace(getattr(shape, name), default_open=False)
                                         for name in EYE_LABELS})
            self.renderer.draw_head(painter, Vec2(), Vec2(0, 10), Vec2(0, -1), Vec2(*self.view.currentData()),
                                    float(mode == 'open'), pixelated=True, raster_scale=scale,
                                    shape=shape, outfit=self.outfit)
        finally:
            painter.end()
        self.actual.image = image
        # 放大检查使用同一帧的头图，去掉仅用于留位的外圈空白，较窄窗口也能看清像素
        self.magnified.image = self.renderer._head_image
        self.actual.update()
        self.magnified.update()
