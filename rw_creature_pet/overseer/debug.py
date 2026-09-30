"""监视者预览控制；由宿主提供画布、坐标变换和固定步长。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFormLayout,
                               QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout)

from ..shared.geometry import Vec2
from .model import Anchor, Edge, State
from .events import EventPhase


class OverseerDebugPanel(QDialog):
    def __init__(self, canvas, parent=None, *, config_path=None, initial_config=None, app_config=None):
        super().__init__(parent)
        self.canvas = canvas
        self.config_path = config_path
        self.initial_config = initial_config or canvas.overseer.config
        self.app_config = app_config
        self.settings_dialog = None
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
        self.avoidance = QCheckBox('鼠标 / 人偶靠近时缩回（与观察方式独立）')
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
        self.show_button.setToolTip('不计时的手动外观预览；清除或退场后才恢复自动检查')
        self.event_status = QLabel()
        self.event_status.setWordWrap(True)
        layout.addWidget(self.event_status)
        self.start_event_button = QPushButton('随机位置触发一次')
        self.finish_event_button = QPushButton('到期 / 退场')
        self.check_event_button = QPushButton('立即抽签')
        self.skip_cooldown_button = QPushButton('结束冷却')
        self.settings_button = QPushButton('事件设置…')
        for controls in ((self.start_event_button, self.finish_event_button),
                         (self.check_event_button, self.skip_cooldown_button, self.settings_button)):
            row = QHBoxLayout()
            for button in controls:
                row.addWidget(button)
            layout.addLayout(row)
        self.start_event_button.clicked.connect(self.start_event)
        self.finish_event_button.clicked.connect(self.finish_event)
        self.check_event_button.clicked.connect(self.check_event)
        self.skip_cooldown_button.clicked.connect(self.skip_cooldown)
        self.settings_button.clicked.connect(self.open_settings)
        hint = QLabel('固定目标时可在场景中右键指定位置。鼠标离开场景后转为扫视。\n'
                      '暂停和单步使用主窗口控件；关闭本面板后仍继续调度。\n'
                      '“显示 / 重置”是不计时预览；“触发一次”才使用事件持续时间。')
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
        self.canvas.overseer_events.preview(self.canvas.overseer_bounds(),
            Anchor(Edge(self.edge.currentData()), self.fraction.value()/100))
        self.canvas.center_on_overseer()
        self.refresh_status()

    def clear_overseer(self):
        self.canvas.overseer_events.clear()
        self.canvas.overseer_focus = False
        self.canvas.update()
        self.refresh_status()

    def relocate(self):
        if self.canvas.overseer.active:
            self.show_overseer()

    def emerge(self):
        self.canvas.overseer_events.emerge()
        self.refresh_status()

    def withdraw(self):
        self.canvas.overseer.request_withdraw()
        self.refresh_status()

    def set_avoidance(self, enabled):
        self.canvas.overseer_avoidance = enabled

    def refresh_status(self):
        model = self.canvas.overseer
        events = self.canvas.overseer_events
        self.emerge_button.setEnabled(model.active and events.phase != EventPhase.EXITING)
        self.withdraw_button.setEnabled(model.active)
        self.start_event_button.setEnabled(events.phase not in (EventPhase.ACTIVE, EventPhase.EXITING))
        self.finish_event_button.setEnabled(events.phase in (EventPhase.ACTIVE, EventPhase.PREVIEW))
        self.check_event_button.setEnabled(events.phase == EventPhase.WAITING)
        self.skip_cooldown_button.setEnabled(events.phase == EventPhase.COOLDOWN)
        phase = {EventPhase.DISABLED: '自动出现已关闭', EventPhase.PREVIEW: '不计时预览（自动检查挂起）',
                 EventPhase.WAITING: f'下次检查 {events.check_remaining:.1f} s',
                 EventPhase.ACTIVE: f'事件剩余 {events.remaining:.1f} s（包含避让隐藏）',
                 EventPhase.EXITING: '正在退场，不再探出',
                 EventPhase.COOLDOWN: f'冷却剩余 {events.cooldown_remaining:.1f} s'}[events.phase]
        self.event_status.setText(f'{phase}\n检查 {events.check_count} 次 · 事件 {events.event_count} 次 · 换位 {events.relocation_count} 次\n{events.last_result}')
        if not model.active:
            self.status.setText('未显示；点击“显示 / 重置”开始。')
            return
        label = {State.HIDDEN: '隐藏', State.EMERGING: '探出',
                 State.WATCHING: '观察', State.WITHDRAWING: '缩回'}[model.state]
        reason = ('等待鼠标和人偶离开安全范围' if model.scared else
                  '手动保持缩回' if not model.wants_out else '原位观察')
        self.status.setText(f'{label} · 展开 {model.extended:.0%} · {reason}')

    def start_event(self):
        if self.canvas.overseer_events.start(self.canvas.overseer_spawn_context()):
            self.canvas.center_on_overseer()
        self.refresh_status()

    def finish_event(self):
        self.canvas.overseer_events.finish()
        self.refresh_status()

    def check_event(self):
        if self.canvas.overseer_events.check(self.canvas.overseer_spawn_context):
            self.canvas.center_on_overseer()
        self.refresh_status()

    def skip_cooldown(self):
        self.canvas.overseer_events.skip_cooldown()
        self.refresh_status()

    def apply_settings(self, config):
        self.canvas.overseer_events.configure(config)
        self.canvas.update()
        self.refresh_status()

    def open_settings(self):
        from ..config import AppConfig
        from .settings import OverseerSettingsDialog
        if self.settings_dialog is None:
            self.settings_dialog = OverseerSettingsDialog(self.canvas.overseer, self.apply_settings,
                self.app_config or AppConfig(overseer=self.initial_config), self, source=self.config_path)
        elif not self.settings_dialog.isVisible():
            self.settings_dialog.fill(self.canvas.overseer.config)
        self.settings_dialog.show()
        self.settings_dialog.raise_()

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
