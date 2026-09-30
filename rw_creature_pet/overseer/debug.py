"""监视者预览控制；由宿主提供画布、坐标变换和固定步长。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout,
                               QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout)

from ..shared.geometry import Vec2
from .model import Anchor, Edge, State


class OverseerDebugPanel(QDialog):
    def __init__(self, canvas, parent=None, *, config_path=None, initial_config=None):
        super().__init__(parent)
        self.canvas = canvas
        self.config_path = config_path
        self.initial_config = initial_config or canvas.overseer.config
        self.setWindowTitle('监视者调试')
        self.setWindowFlag(Qt.WindowType.Tool, True)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.edge = QComboBox()
        for text, edge in (('上边', Edge.TOP), ('右边', Edge.RIGHT), ('下边', Edge.BOTTOM), ('左边', Edge.LEFT)):
            self.edge.addItem(text, edge.value)
        self.edge.setCurrentIndex(self.edge.findData(canvas.overseer.anchor.edge.value))
        form.addRow('附着边', self.edge)
        self.fraction = QSpinBox()
        self.fraction.setRange(0, 100)
        self.fraction.setSuffix(' %')
        self.fraction.setValue(round(canvas.overseer.anchor.fraction*100))
        self.fraction.setToolTip('横边从左到右，竖边从上到下；四角会保留外形所需余量')
        form.addRow('沿边位置', self.fraction)
        self.look_mode = QComboBox()
        for text, key in (('跟随鼠标', 'mouse'), ('固定目标', 'fixed'), ('轻微扫视', 'idle')):
            self.look_mode.addItem(text, key)
        form.addRow('观察方式', self.look_mode)
        self.target_x, self.target_y = QSpinBox(), QSpinBox()
        self.target_x.setRange(0, round(canvas.scene.world.width))
        self.target_y.setRange(0, round(canvas.scene.world.height))
        self.target_x.setValue(round(canvas.overseer_fixed_target.x))
        self.target_y.setValue(round(canvas.overseer_fixed_target.y))
        coords = QHBoxLayout()
        coords.addWidget(QLabel('X'))
        coords.addWidget(self.target_x)
        coords.addWidget(QLabel('Y'))
        coords.addWidget(self.target_y)
        form.addRow('固定目标', coords)
        layout.addLayout(form)
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self.choose_color)
        self.reload_color_button = QPushButton('重新读取配色')
        self.reload_color_button.clicked.connect(self.reload_color)
        colors = QHBoxLayout()
        colors.addWidget(QLabel('主色预览'))
        colors.addWidget(self.color_button)
        colors.addWidget(self.reload_color_button)
        layout.addLayout(colors)
        self.color_hint = QLabel('配色仅在本窗口预览；持久修改请编辑 [overseer] color。')
        self.color_hint.setWordWrap(True)
        layout.addWidget(self.color_hint)
        self.avoidance = QCheckBox('鼠标靠近时缩回（与观察方式独立）')
        self.avoidance.setChecked(canvas.overseer_avoidance)
        self.avoidance.toggled.connect(self.set_avoidance)
        layout.addWidget(self.avoidance)
        self.guides = QCheckBox('辅助线：根部、视线、活动与避让范围')
        layout.addWidget(self.guides)
        motions = QHBoxLayout()
        self.emerge_button = QPushButton('探出')
        self.withdraw_button = QPushButton('缩回')
        self.emerge_button.clicked.connect(self.emerge)
        self.withdraw_button.clicked.connect(self.withdraw)
        motions.addWidget(self.emerge_button)
        motions.addWidget(self.withdraw_button)
        layout.addLayout(motions)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.show_button = QPushButton('显示 / 重置')
        self.clear_button = QPushButton('清除')
        self.focus_button = QPushButton('定位监视者')
        buttons = QHBoxLayout()
        for widget in (self.show_button, self.clear_button, self.focus_button):
            buttons.addWidget(widget)
        layout.addLayout(buttons)
        hint = QLabel('固定目标时可在场景中右键指定位置。鼠标离开场景后转为扫视。\n'
                      '暂停和单步使用主窗口控件；关闭本面板后仍保留预览。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.show_button.clicked.connect(self.show_overseer)
        self.clear_button.clicked.connect(self.clear_overseer)
        self.focus_button.clicked.connect(canvas.center_on_overseer)
        self.edge.currentIndexChanged.connect(self.relocate)
        self.fraction.valueChanged.connect(self.relocate)
        self.look_mode.currentIndexChanged.connect(self.set_look_mode)
        self.target_x.valueChanged.connect(self.set_fixed_target)
        self.target_y.valueChanged.connect(self.set_fixed_target)
        self.guides.toggled.connect(self.set_guides)
        canvas.overseer_look_picked.connect(self.pick_target)
        self.set_look_mode()
        self.set_color(canvas.overseer.config.color)
        self.refresh_status()

    def show_overseer(self):
        self.canvas.overseer.show(self.canvas.overseer_bounds(),
            Anchor(Edge(self.edge.currentData()), self.fraction.value()/100))
        self.canvas.center_on_overseer()
        self.refresh_status()

    def clear_overseer(self):
        self.canvas.overseer.clear()
        self.canvas.overseer_focus = False
        self.canvas.update()
        self.refresh_status()

    def relocate(self):
        if self.canvas.overseer.active:
            self.show_overseer()

    def emerge(self):
        self.canvas.overseer.request_emerge()
        self.refresh_status()

    def withdraw(self):
        self.canvas.overseer.request_withdraw()
        self.refresh_status()

    def set_avoidance(self, enabled):
        self.canvas.overseer_avoidance = enabled

    def refresh_status(self):
        model = self.canvas.overseer
        self.emerge_button.setEnabled(model.active)
        self.withdraw_button.setEnabled(model.active)
        if not model.active:
            self.status.setText('未显示；点击“显示 / 重置”开始。')
            return
        label = {State.HIDDEN: '隐藏', State.EMERGING: '探出',
                 State.WATCHING: '观察', State.WITHDRAWING: '缩回'}[model.state]
        reason = ('等待鼠标离开安全范围' if model.scared else
                  '手动保持缩回' if not model.wants_out else '原位观察')
        self.status.setText(f'{label} · 展开 {model.extended:.0%} · {reason}')

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.canvas.overseer.config.color), self, '监视者主色预览')
        if color.isValid():
            self.set_color(color.name())

    def set_color(self, color):
        self.canvas.overseer.set_color(color)
        self.color_button.setText(color)
        foreground = '#111111' if QColor(color).lightnessF() > .53 else '#ffffff'
        self.color_button.setStyleSheet(f'background-color: {color}; color: {foreground}; padding: 4px;')
        self.canvas.update()

    def reload_color(self):
        from ..config import AppConfig
        try:
            color = AppConfig.load(self.config_path).overseer.color if self.config_path else self.initial_config.color
            self.set_color(color)
            self.color_hint.setText('已重新读取配色；预览修改不会写入配置文件。')
        except (OSError, ValueError, TypeError) as exc:
            self.color_hint.setText(f'读取失败，保留当前颜色：{exc}')

    def set_look_mode(self):
        self.canvas.overseer_look_mode = self.look_mode.currentData()
        fixed = self.canvas.overseer_look_mode == 'fixed'
        self.target_x.setEnabled(fixed)
        self.target_y.setEnabled(fixed)

    def set_fixed_target(self):
        self.canvas.overseer_fixed_target = Vec2(self.target_x.value(), self.target_y.value())

    def pick_target(self, x, y):
        self.target_x.setValue(round(x))
        self.target_y.setValue(round(y))

    def set_guides(self, enabled):
        self.canvas.overseer_guides = enabled
        self.canvas.update()
