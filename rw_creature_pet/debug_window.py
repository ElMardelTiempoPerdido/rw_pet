"""Qt 调试视图；所有仿真状态由 DebugScene 持有。"""
from time import perf_counter
from math import cos, radians, sin, sqrt

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QHeaderView, QLayout,
)

from .config import AppConfig
from .geometry import Vec2
from .lizard import ConnectionKind
from .gait import FlatGait, FootPhase
from .atlas import Atlas, AtlasError, extract_atlas
from .render_lizard import LizardRenderer
from .scene import DebugScene, FixedStepper


class SceneCanvas(QWidget):
    target_picked = Signal(float, float)
    observation_picked = Signal(float, float)

    def __init__(self, scene: DebugScene, clock: FixedStepper, renderer=None):
        super().__init__()
        self.scene = scene
        self.renderer = renderer
        self.show_skeleton = False
        self.clock = clock
        self.show_grid = True
        self.show_velocity = True
        self.show_projections = True
        self.follow_body = True
        self.setMinimumSize(480, 240)

    def view_transform(self):
        world = self.scene.world
        scale = min((self.width() - 40) / world.width, (self.height() - 40) / world.height)
        center = Vec2(world.width / 2, world.height / 2)
        if self.follow_body:
            scale *= 2
            half_width = self.width() / (2 * scale)
            chunk = self.scene.body.chunks[1]
            x = chunk.previous_position.lerp(chunk.position, self.clock.alpha).x
            center = Vec2(max(half_width, min(world.width - half_width, x)), (chunk.previous_position.lerp(chunk.position, self.clock.alpha).y if self.scene.background_mode else world.floor_y - 25))
        return scale, center

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            scale, center = self.view_transform()
            self.observation_picked.emit((event.position().x()-self.width()/2)/scale+center.x,
                                         (event.position().y()-self.height()/2)/scale+center.y)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.scene.background_mode and self.scene.background.enabled:
            scale, center = self.view_transform()
            point = Vec2((event.position().x() - self.width() / 2) / scale + center.x,
                         (event.position().y() - self.height() / 2) / scale + center.y)
            self.target_picked.emit(point.x, point.y)
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor("#17202b"))
            world = self.scene.world
            scale, center = self.view_transform()
            painter.translate(self.width() / 2 - center.x * scale,
                              self.height() / 2 - center.y * scale)
            painter.scale(scale, scale)
            left = max(0, center.x - self.width() / (2 * scale)) + 5
            bottom = min(world.height, center.y + self.height() / (2 * scale)) - 6

            def pen(color, width=1, style=Qt.PenStyle.SolidLine):
                result = QPen(QColor(color), width, style)
                result.setCosmetic(True)
                return result

            def line(a: Vec2, b: Vec2):
                painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))

            def label(x, y, text, color="#a8b7c9"):
                painter.save()
                painter.translate(x, y)
                painter.scale(1 / scale, 1 / scale)
                painter.setPen(QColor(color))
                painter.setFont(QFont("Microsoft YaHei UI", 9))
                painter.drawText(QPointF(0, 0), text)
                painter.restore()

            painter.setPen(pen("#3e4f64"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(0, 0, world.width, world.height))
            if self.show_grid:
                painter.setPen(pen("#243345"))
                for x in range(20, int(world.width), 20):
                    line(Vec2(x, 0), Vec2(x, world.height))
                for y in range(20, int(world.height), 20):
                    line(Vec2(0, y), Vec2(world.width, y))
            painter.fillRect(QRectF(0, world.floor_y, world.width, world.height - world.floor_y),
                             QColor("#283b39"))
            painter.setPen(pen("#79b79e", 2))
            line(Vec2(0, world.floor_y), Vec2(world.width, world.floor_y))
            if not self.follow_body:
                label(5, 10, "原点 (0, 0) · x → / y ↓")
            label(left, world.floor_y + 14, f"平地 y = {world.floor_y:g}", "#9dd7be")

            if self.renderer is not None:
                self.renderer.draw(painter, self.scene, self.clock.alpha)
            if self.show_skeleton or self.renderer is None:
                body = self.scene.body
                positions = [c.previous_position.lerp(c.position, self.clock.alpha) for c in body.chunks]
                def draw_legs(side):
                    if not (self.scene.background_mode or self.scene.gait.enabled):
                        return
                    for i, foot in enumerate(self.scene.feet):
                        if foot.side != side:
                            continue
                        hip = positions[foot.chunk_index]
                        toe = foot.previous_position.lerp(foot.position, self.clock.alpha)
                        delta = toe - hip
                        length = delta.length()
                        normal = Vec2(-delta.y, delta.x) * (1 / max(length, 1e-8))
                        knee = hip.lerp(toe, 0.5) + normal * (side * sqrt(max(0, (self.scene.gait.REACH / 2) ** 2 - (length / 2) ** 2)))
                        color = "#82d8bc" if foot.phase == FootPhase.STANCE else "#f1bd70"
                        painter.setPen(pen(color, 2 if side == 1 else 1,
                                           Qt.PenStyle.SolidLine if side == 1 else Qt.PenStyle.DashLine))
                        line(hip, knee)
                        line(knee, toe)
                        painter.setBrush(QColor(color) if foot.phase == FootPhase.STANCE else Qt.BrushStyle.NoBrush)
                        painter.drawEllipse(QPointF(toe.x, toe.y), 1.8, 1.8)
                        if foot.phase == FootPhase.STANCE:
                            line(toe + Vec2(-3, 2), toe + Vec2(3, 2))
                        label(toe.x - 3, toe.y + (24 if side == 1 else 12), str(i), color)

                draw_legs(-1)
                for connection in body.connections:
                    push = connection.kind == ConnectionKind.PUSH
                    painter.setPen(pen("#dcaa69" if push else "#91bde3", 2,
                                       Qt.PenStyle.DashLine if push else Qt.PenStyle.SolidLine))
                    # Push 连线稍向下偏移，便于看清首尾连接；物理数据不偏移。
                    offset = Vec2(0, 4 if push else 0)
                    line(positions[connection.first] + offset, positions[connection.second] + offset)
                for i, (chunk, position) in enumerate(zip(body.chunks, positions)):
                    if self.show_projections:
                        ground = world.floor_projection(position)
                        painter.setPen(pen("#679785", 1, Qt.PenStyle.DotLine))
                        line(position, ground)
                        painter.setPen(pen("#9dd7be", 2))
                        line(ground + Vec2(-3, 0), ground + Vec2(3, 0))
                        line(ground + Vec2(0, -3), ground + Vec2(0, 3))
                    painter.setPen(pen("#e9f0f7", 2))
                    painter.setBrush(QColor("#39775c") if chunk.grounded else QColor("#567fa2") if i == 0 else QColor("#30465d"))
                    painter.drawEllipse(QPointF(position.x, position.y), chunk.radius, chunk.radius)
                    label(position.x - 2, position.y + 2, str(i), "#ffffff")
                    if i == 0:
                        axis = position - positions[1]
                        axis = axis * (1 / max(axis.length(), 1e-8))
                        painter.setPen(pen("#ffffff", 3))
                        line(position + axis * chunk.radius, position + axis * (chunk.radius + 5))
                    if self.show_velocity and chunk.velocity.length() > 0:
                        tip = position + chunk.velocity * 10
                        painter.setPen(pen("#f1c679", 2))
                        line(position, tip)
                        direction = chunk.velocity * (1 / chunk.velocity.length())
                        normal = Vec2(-direction.y, direction.x)
                        line(tip, tip - direction * 3 + normal * 2)
                        line(tip, tip - direction * 3 - normal * 2)
                draw_legs(1)
                label(left, bottom, "蓝线 Normal · 橙虚线 Push · 绿足支撑 / 橙足迈步 · "
                      + ("两侧四肢，背部朝向镜头" if self.scene.background_mode else "虚线腿为远侧"))
            else:
                label(left, bottom, "白蜥蜴 · 原版图集 / 五节尾巴 · 可开启骨架叠加")
            goal = self.scene.background.goal if self.scene.background_mode else None
            if goal is not None:
                painter.setPen(pen('#82d8bc' if self.scene.background.arrived else '#f1bd70', 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(goal.x, goal.y), 10, 10)
                line(goal + Vec2(-8, 0), goal + Vec2(8, 0))
                line(goal + Vec2(0, -8), goal + Vec2(0, 8))
                label(goal.x + 12, goal.y - 24, f'目标 ({goal.x:.0f}, {goal.y:.0f})')
            observation = self.scene.appearance.look_target
            if observation is not None and not self.scene.background_mode:
                painter.setPen(pen('#77cfff', 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(observation.x, observation.y), 4, 4)
                label(observation.x+6, observation.y-6, '观察', '#77cfff')
        finally:
            painter.end()


class DebugWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.scene = DebugScene(config.debug)
        self.scene.gait.enabled = True
        self.scene.gait.set_speed(FlatGait.MAX_SPEED * FlatGait.SLOW_INTENT)
        self.clock = FixedStepper(config.debug.tick_rate)
        self.setWindowTitle("WhiteLizard · 平地步态调试 / 阶段 4")
        self.resize(1040, 740)
        self.setMinimumSize(720, 620)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel("WhiteLizard  /  平地调试")
        title.setFont(QFont("Microsoft YaHei UI", 15, QFont.Weight.Bold))
        layout.addWidget(title)
        description = QLabel("白蜥蜴原版图集与品种尺寸；反向先转身，到边界停步。个体随机倍率暂固定为 1。")
        description.setWordWrap(True)
        layout.addWidget(description)
        controls = QHBoxLayout()
        self.pause_button = QPushButton("暂停 [Space]")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.step_button = QPushButton("单步 [N]")
        self.step_button.clicked.connect(self.single_step)
        self.reset_button = QPushButton("重置 [R]")
        self.reset_button.clicked.connect(self.reset_scene)
        for button in (self.pause_button, self.step_button, self.reset_button):
            controls.addWidget(button)
        controls.addStretch()
        self.speed = QDoubleSpinBox()
        self.speed.setRange(-3, 3)
        self.speed.setSingleStep(0.25)
        self.speed.setDecimals(2)
        self.speed.setSuffix(" 单位/tick")
        self.speed.setToolTip("设置一次水平速度，保留竖直速度；之后由重力、阻力及碰撞推进。")
        controls.addWidget(self.speed)
        self.apply_speed_button = QPushButton("施加水平速度")
        self.apply_speed_button.clicked.connect(self.apply_speed)
        controls.addWidget(self.apply_speed_button)
        layout.addLayout(controls)
        walking = QHBoxLayout()
        self.gait_box = QCheckBox("启用四肢支撑")
        self.gait_box.setChecked(True)
        self.gait_box.toggled.connect(self.set_gait_enabled)
        walking.addWidget(self.gait_box)
        self.left_button = QPushButton("← 向左")
        self.stop_button = QPushButton("停止步行")
        self.right_button = QPushButton("向右 →")
        self.walk_pace = QComboBox()
        self.walk_pace.addItem("慢行", FlatGait.SLOW_INTENT)
        self.walk_pace.addItem("积极移动", FlatGait.TRACK_INTENT)
        self.walk_pace.setToolTip("即时调整平地节奏；停止时只选择下次移动的节奏。")
        self.walk_pace.currentIndexChanged.connect(self.apply_walk_pace)
        walking.addWidget(self.walk_pace)
        for button, direction in ((self.left_button, -1), (self.stop_button, 0), (self.right_button, 1)):
            button.clicked.connect(lambda checked=False, value=direction:
                                   self.set_walk_speed(value * FlatGait.MAX_SPEED * self.walk_pace.currentData()))
            walking.addWidget(button)
        self.gait_status = QLabel()
        walking.addWidget(self.gait_status)
        walking.addStretch()
        self.follow_box = QCheckBox("跟随放大")
        self.follow_box.setChecked(True)
        self.follow_box.toggled.connect(lambda value: self.set_layer("follow_body", value))
        walking.addWidget(self.follow_box)
        layout.addLayout(walking)
        background_controls = QHBoxLayout()
        self.background_box = QCheckBox("背景抓附场景")
        self.background_box.toggled.connect(self.switch_background)
        background_controls.addWidget(self.background_box)
        self.attach_box = QCheckBox("启用背景抓附")
        self.attach_box.setChecked(True)
        self.attach_box.setEnabled(False)
        self.attach_box.toggled.connect(self.set_background_attachment)
        background_controls.addWidget(self.attach_box)
        self.height_input = QDoubleSpinBox()
        self.height_input.setRange(8, self.scene.world.floor_y - 8)
        self.height_input.setValue(self.scene.spawn_height)
        self.height_input.setSuffix(" 离地高度")
        self.height_input.setEnabled(False)
        background_controls.addWidget(self.height_input)
        self.place_button = QPushButton("放置并重置")
        self.place_button.setEnabled(False)
        self.place_button.clicked.connect(self.place_background)
        background_controls.addWidget(self.place_button)
        background_controls.addStretch()
        layout.addLayout(background_controls)
        movement = QHBoxLayout()
        movement.addWidget(QLabel("方向慢行 / 点击积极追踪"))
        self.background_buttons = []
        for text, direction in (("↖", Vec2(-1, -1)), ("↑", Vec2(0, -1)), ("↗", Vec2(1, -1)),
                                ("←", Vec2(-1, 0)), ("停止", Vec2()), ("→", Vec2(1, 0)),
                                ("↙", Vec2(-1, 1)), ("↓", Vec2(0, 1)), ("↘", Vec2(1, 1))):
            button = QPushButton(text)
            button.setFixedWidth(42)
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, value=direction: self.set_background_direction(value))
            movement.addWidget(button)
            self.background_buttons.append(button)
        self.direction_angle = QDoubleSpinBox()
        self.direction_angle.setRange(0, 359.9)
        self.direction_angle.setDecimals(1)
        self.direction_angle.setSuffix("°")
        self.direction_angle.setToolTip("0° 向右，90° 向下，180° 向左，270° 向上")
        self.direction_angle.setEnabled(False)
        movement.addWidget(self.direction_angle)
        self.angle_button = QPushButton("按角度爬行")
        self.angle_button.setEnabled(False)
        self.angle_button.clicked.connect(lambda: self.set_background_direction(Vec2(cos(radians(self.direction_angle.value())), sin(radians(self.direction_angle.value())))))
        movement.addWidget(self.angle_button)
        layout.addLayout(movement)
        posture = QHBoxLayout()
        posture.addWidget(QLabel('停留姿态'))
        self.posture_input = QComboBox()
        for title, value in (('低伏休息', 'low'), ('平身站立', 'relaxed'), ('抬胸观察', 'raised')):
            self.posture_input.addItem(title, value)
        self.posture_input.currentIndexChanged.connect(self.apply_posture)
        posture.addWidget(self.posture_input)
        self.chest_angle_input = QDoubleSpinBox()
        self.chest_angle_input.setRange(0, 22)
        self.chest_angle_input.setDecimals(1)
        self.chest_angle_input.setValue(self.scene.gait.chest_angle)
        self.chest_angle_input.setSuffix('° 抬胸')
        self.chest_angle_input.valueChanged.connect(self.apply_posture)
        posture.addWidget(self.chest_angle_input)
        posture.addWidget(QLabel('右键观察 10 秒（平地 / 趴墙）'))
        clear_look = QPushButton('清除观察')
        clear_look.clicked.connect(lambda: self.scene.appearance.observe(None))
        posture.addWidget(clear_look)
        layout.addLayout(posture)
        effects = QHBoxLayout()
        effects.addWidget(QLabel("头部兴奋度"))
        self.excitement_input = QDoubleSpinBox()
        self.excitement_input.setRange(0, 1)
        self.excitement_input.setSingleStep(.1)
        self.excitement_input.setValue(.2)
        self.excitement_input.valueChanged.connect(lambda value: setattr(self.scene.appearance.colors, 'excitement', value))
        effects.addWidget(self.excitement_input)
        self.effect_buttons = {}
        for key, title in (("flash", "闪白"), ("stun", "眩晕闪烁"), ("display", "展示变色")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, effect=key: self.trigger_color_effect(effect))
            effects.addWidget(button)
            self.effect_buttons[key] = button
        self.effect_status = QLabel()
        effects.addWidget(self.effect_status)
        effects.addStretch()
        layout.addLayout(effects)
        self.asset_error = None
        renderer = None
        try:
            renderer = LizardRenderer(Atlas(extract_atlas(config.game_dir)))
        except (AtlasError, OSError) as exc:
            self.asset_error = str(exc)
        self.canvas = SceneCanvas(self.scene, self.clock, renderer)
        self.canvas.target_picked.connect(self.set_background_target)
        self.canvas.observation_picked.connect(lambda x, y: self.scene.appearance.observe(Vec2(x, y), self.scene_tick_rate()*10))
        self.canvas.setToolTip('背景抓附时点击设置追踪目标；目标自动限制在安全范围内。方向按钮或停止会取消追踪。')
        layout.addWidget(self.canvas, 1)
        toggles = QHBoxLayout()
        self.layer_boxes = {}
        for text, attr in (("网格", "show_grid"), ("速度向量", "show_velocity"), ("地面投影", "show_projections"), ("骨架叠加", "show_skeleton")):
            box = QCheckBox(text)
            box.setChecked(attr != "show_skeleton")
            if attr in ("show_velocity", "show_projections"):
                box.setEnabled(renderer is None)
                box.setToolTip("开启骨架叠加后显示")
            box.toggled.connect(lambda value, key=attr: self.set_layer(key, value))
            toggles.addWidget(box)
            self.layer_boxes[attr] = box
        toggles.addStretch()
        self.status = QLabel()
        toggles.addWidget(self.status)
        layout.addLayout(toggles)
        self.physics_status = QLabel()
        self.physics_status.setWordWrap(True)
        layout.addWidget(self.physics_status)
        self.table = QTableWidget(3, 6)
        self.table.setHorizontalHeaderLabels(["质点", "位置 (x, y)", "速度 / tick", "半径", "质量", "接地"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setFixedHeight(126)
        for row in range(3):
            for col in range(6):
                self.table.setItem(row, col, QTableWidgetItem())
        layout.addWidget(self.table)
        note = QLabel("数值表为最新 tick；画面使用前后 tick 插值。暂停/单步显示最新状态。固定调试个体，尚不支持原版 ID。")
        note.setWordWrap(True)
        layout.addWidget(note)
        path_label = QLabel(f"图集加载失败，显示骨架：{self.asset_error}" if self.asset_error else f"游戏图集：{config.game_dir} · 本机提取并缓存")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path_label)
        self.setCentralWidget(root)
        # 由控件和画布的最小尺寸约束窗口，避免窄窗口把状态栏挤进画布。
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.setMinimumSize(self.minimumSize().expandedTo(layout.minimumSize()))
        self._last_time = perf_counter()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(16)
        self.refresh()

    def scene_tick_rate(self):
        return round(1/self.clock.dt)

    def apply_posture(self):
        self.scene.gait.posture = self.posture_input.currentData()
        self.scene.gait.set_chest_angle(self.chest_angle_input.value())
        self.chest_angle_input.setEnabled(not self.scene.background_mode and self.scene.gait.posture == 'raised')

    def trigger_color_effect(self, effect):
        self.scene.appearance.colors.trigger(effect)
        self.refresh()

    def set_layer(self, key, value):
        setattr(self.canvas, key, value)
        if key == "show_skeleton":
            for attr in ("show_velocity", "show_projections"):
                self.layer_boxes[attr].setEnabled(value or self.canvas.renderer is None)
        self.canvas.update()

    def toggle_pause(self):
        if self.clock.paused:
            # 恢复后从暂停画面继续，不能插值回上一个 tick 的位置。
            for chunk in self.scene.body.chunks:
                chunk.previous_position = chunk.position
            for foot in self.scene.feet:
                foot.previous_position = foot.position
            self.scene.appearance.sync_previous()
        self.clock.set_paused(not self.clock.paused)
        self._last_time = perf_counter()
        self.refresh()

    def single_step(self):
        self.clock.single_step(self.scene.step)
        self._last_time = perf_counter()
        self.refresh()

    def reset_scene(self):
        paused = self.clock.paused
        self.scene.reset()
        self.speed.setValue(0)
        self.clock.set_paused(paused)
        self.clock.dropped_seconds = 0
        self._last_time = perf_counter()
        self.refresh()

    def apply_speed(self):
        self.scene.set_horizontal_velocity(self.speed.value())
        self.refresh()

    def set_gait_enabled(self, enabled):
        self.scene.gait.enabled = enabled
        self.refresh()

    def switch_background(self, enabled):
        if enabled:
            self._flat_state = (self.scene.gait.enabled, self.scene.gait.speed)
        self.scene.set_background_mode(enabled)
        if not enabled:
            self.scene.gait.enabled, self.scene.gait.speed = self._flat_state
        else:
            self.attach_box.blockSignals(True)
            self.attach_box.setChecked(True)
            self.attach_box.blockSignals(False)
            self.layer_boxes['show_skeleton'].setChecked(True)
        for widget in (self.attach_box, self.height_input, self.place_button):
            widget.setEnabled(enabled)
        for widget in (self.gait_box, self.left_button, self.right_button, self.stop_button, self.walk_pace):
            widget.setEnabled(not enabled)
        self.clock.set_paused(self.clock.paused)
        self.clock.dropped_seconds = 0
        self._last_time = perf_counter()
        self.refresh()

    def set_background_attachment(self, enabled):
        self.scene.background.set_enabled(enabled, self.scene.body, self.scene.world)
        self.refresh()

    def set_background_target(self, x, y):
        self.scene.background.set_goal(Vec2(x, y), self.scene.body, self.scene.world)
        self.refresh()

    def set_background_direction(self, direction):
        self.scene.background.set_direction(direction)
        self.refresh()

    def place_background(self):
        self.scene.place_on_background(self.height_input.value(), self.attach_box.isChecked())
        self.clock.set_paused(self.clock.paused)
        self.clock.dropped_seconds = 0
        self._last_time = perf_counter()
        self.refresh()

    def set_walk_speed(self, speed):
        self.gait_box.setChecked(True)
        self.scene.gait.set_speed(speed)
        self.refresh()

    def apply_walk_pace(self):
        speed = self.scene.gait.speed
        if speed:
            self.scene.gait.set_speed((1 if speed > 0 else -1) * FlatGait.MAX_SPEED * self.walk_pace.currentData())
        self.refresh()

    def on_timer(self):
        now = perf_counter()
        self.clock.advance(now - self._last_time, self.scene.step)
        self._last_time = now
        self.refresh()

    def refresh(self):
        self.posture_input.setEnabled(not self.scene.background_mode)
        self.apply_posture()
        colors = self.scene.appearance.colors
        colors.excitement = self.excitement_input.value()
        self.effect_status.setText(f"闪白 {colors.flash*self.clock.dt:.2f}s · 眩晕 {colors.stun*self.clock.dt:.2f}s · 展示 {colors.dominance:.0%}" + (" · 暂停中，单步可预览" if self.clock.paused else ""))
        self.pause_button.setText("继续 [Space]" if self.clock.paused else "暂停 [Space]")
        error = max(self.scene.body.connection_error(c) for c in self.scene.body.connections)
        gait = self.scene.gait
        desired = 1 if gait.speed > 0 else -1 if gait.speed < 0 else gait.facing
        action = ("仅身体物理" if not gait.enabled else
                  ("转向左" if gait.turn_target < 0 else "转向右") if gait.turning else
                  "减速待转" if desired != gait.facing else "边界停步" if gait.blocked else
                  "向右行走" if gait.speed > 0 else "向左行走" if gait.speed < 0 else "站立")
        self.gait_status.setText(f"{action} · 抓地 {gait.grip_count if gait.enabled else 0}/4")
        if self.scene.background_mode:
            bg = self.scene.background
            action = "背景抓附" if bg.attached else "失附下落" if not all(c.grounded for c in self.scene.body.chunks) else "已落地"
            if bg.attached and bg.direction.length():
                action = "边界停步" if bg.blocked else "背景爬行 / 对准方向"
            if bg.attached and bg.goal is not None:
                action = '已到达目标' if bg.arrived else '追踪目标'
            self.gait_status.setText(f"{action} · 抓点 {bg.grip_count}/4")
        for widget in (*self.background_buttons, self.direction_angle, self.angle_button):
            widget.setEnabled(self.scene.background_mode and self.scene.background.enabled)
        self.physics_status.setText(f"接地 {sum(c.grounded for c in self.scene.body.chunks)}/3 · "
                                    f"最大连接误差 {error:.5f} · "
                                    + (" / ".join(f"足{i} {f.phase.value}" for i, f in enumerate(self.scene.feet)) if gait.enabled or self.scene.background_mode else "四肢已关闭"))
        self.status.setText(
            f"{'暂停' if self.clock.paused else '运行'} · {self.config.debug.tick_rate} Hz · "
            f"tick {self.scene.ticks} · t={self.scene.ticks * self.clock.dt:.3f}s · "
            f"丢弃积压 {self.clock.dropped_seconds:.3f}s")
        for row, chunk in enumerate(self.scene.body.chunks):
            values = (str(row), f"{chunk.position.x:.3f}, {chunk.position.y:.3f}",
                      f"{chunk.velocity.x:.3f}, {chunk.velocity.y:.3f}",
                      f"{chunk.radius:g}", f"{chunk.mass:g}", "是" if chunk.grounded else "否")
            for col, text in enumerate(values):
                self.table.item(row, col).setText(text)
        self.canvas.update()

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return
        handlers = {Qt.Key.Key_Space: self.toggle_pause, Qt.Key.Key_N: self.single_step,
                    Qt.Key.Key_R: self.reset_scene}
        handler = handlers.get(event.key())
        if handler:
            handler()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
