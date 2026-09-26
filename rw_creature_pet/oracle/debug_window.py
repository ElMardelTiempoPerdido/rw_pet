"""Oracle 四边漂浮调试窗口；QPainter 只读仿真，颜色可即时预览。"""
from dataclasses import fields, replace
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSpinBox, QVBoxLayout, QWidget

from ..shared.atlas import Atlas, AtlasError, extract_atlas
from ..config import AppConfig
from ..shared.geometry import Vec2
from .scene import OracleScene, RailSide
from .config import OracleColors
from .glyphs import load_pearl_glyphs
from .render import OracleRenderer, point
from .input import PuppetHitMap
from ..shared.timing import FixedStepper
from .voice_assets import make_bell_voice_player


COLOR_LABELS = {
    'skin': '皮肤 / 头 / 手脚', 'eyes': '眼睛', 'head_shell': '头部附件底色',
    'head_highlight': '头部附件高光', 'robe_top': '衣袍上部 / 袖子',
    'robe_bottom': '衣袍下部', 'arm': '机械臂主体', 'arm_highlight': '机械臂高光',
    'joints': '关节 / 底座', 'third_eye': '额头标记',
    'inner_robe': '高领内搭', 'collar_trim': 'V 形领边', 'beads': '念珠主体',
    'pearl': '珍珠共有色', 'pearl_primary': '珍珠主色', 'pearl_secondary': '珍珠辅色',
    'pearl_glyph': '投影（珍珠/光环）',
}


class OracleCanvas(QWidget):
    target_picked = Signal(float, float)
    look_picked = Signal(float, float)
    pearl_picked = Signal(float, float)

    def __init__(self, scene, clock, renderer):
        super().__init__()
        self.scene, self.clock, self.renderer = scene, clock, renderer
        self.skeleton = False
        self.magnifier = True
        self.show_path = True
        self.view_scale = 1.  # 屏幕物理像素 / 游戏单位；None 表示适应窗口。
        self.view_center = None
        self._pan_position = None
        self.drag_hit = PuppetHitMap()
        self._route = None
        self._route_path = None
        self.setMinimumSize(640, 420)

    def view_transform(self):
        world = self.scene.world
        dpr = self.devicePixelRatioF()
        if self.view_scale is None:
            scale = min((self.width() - 28) / world.width, (self.height() - 28) / world.height)
            center = Vec2(world.width/2, world.height/2)
        else:
            # Qt 绘制坐标是逻辑像素；抵消系统缩放后，1× 才是实际屏幕的 1px。
            scale = self.view_scale/dpr
            center = self.view_center or Vec2(world.width/2, world.height/2)
        offset = Vec2(self.width()/2-center.x*scale, self.height()/2-center.y*scale)
        # 相机落在物理像素边界，窗口尺寸改变不引入额外半像素位移。
        return scale, Vec2(round(offset.x*dpr)/dpr, round(offset.y*dpr)/dpr)

    def set_view_scale(self, scale):
        self.view_scale = scale
        self.view_center = None
        self._pan_position = None
        self.unsetCursor()
        self.update()

    def center_on_pet(self):
        upper = self.scene.body.chunks[0]
        self.view_center = upper.previous_position.lerp(upper.position, self.clock.alpha)
        self.update()

    def world_to_view(self, position):
        scale, offset = self.view_transform()
        return offset + position * scale

    def view_to_world(self, position):
        scale, offset = self.view_transform()
        return (position-offset)*(1/scale)

    def mousePressEvent(self, event):
        # 放大镜是只读检查窗，避免点击它时把目标投到下方世界坐标。
        if self.magnifier and self.magnifier_rect().contains(event.position()):
            event.accept()
            return
        position = Vec2(event.position().x(), event.position().y())
        if event.button() == Qt.MouseButton.MiddleButton:
            if self.view_scale is not None:
                self._pan_position = position
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        pos = self.view_to_world(position)
        if event.button() == Qt.MouseButton.LeftButton:
            if (not self.clock.paused and not event.modifiers()
                    and self.scene.drag.press(pos, self.drag_hit.get(
                        self.renderer, self.scene, self.clock.alpha,
                        raster_scale=self.view_transform()[0]*self.devicePixelRatioF()).contains)):
                self.grabMouse()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.pearl_picked.emit(pos.x, pos.y)
            else:
                self.target_picked.emit(pos.x, pos.y)
        elif event.button() == Qt.MouseButton.RightButton:
            self.look_picked.emit(pos.x, pos.y)
        event.accept()

    def mouseMoveEvent(self, event):
        if self.scene.drag.active:
            position = Vec2(event.position().x(), event.position().y())
            self.scene.drag.move(self.view_to_world(position))
            event.accept()
        elif self._pan_position is not None:
            position = Vec2(event.position().x(), event.position().y())
            scale, _ = self.view_transform()
            world = self.scene.world
            center = self.view_center or Vec2(world.width/2, world.height/2)
            self.view_center = center-(position-self._pan_position)*(1/scale)
            self._pan_position = position
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.scene.drag.active:
            self.scene.drag.move(self.view_to_world(Vec2(event.position().x(), event.position().y())))
            self.scene.drag.release()
            self.releaseMouse()
            self.unsetCursor()
            event.accept()
        elif event.button() == Qt.MouseButton.MiddleButton and self._pan_position is not None:
            self._pan_position = None
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def event(self, event):
        if (event.type() == QEvent.Type.UngrabMouse and hasattr(self, 'scene')
                and self.scene.drag.active):
            self.scene.drag.release(cancel=True)
            self.unsetCursor()
        return super().event(event)

    def magnifier_rect(self):
        # 衣袍垂坠后下摆距上身约 33.3；保持 4×，增高检查窗容纳完整外形。
        return QRectF(self.width() - 264, self.height() - 304, 250, 290)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor('#151e29'))
            painter.save()
            scale, offset = self.view_transform()
            painter.translate(offset.x, offset.y)
            painter.scale(scale, scale)
            world, scene = self.scene.world, self.scene
            painter.fillRect(QRectF(0, 0, world.width, world.height), QColor('#223238'))
            inner = world.inner
            painter.fillRect(QRectF(inner.left, inner.top, inner.right - inner.left, inner.bottom - inner.top), QColor('#121b26'))
            corridors = scene.navigator.region.boxes if scene.navigator else (world.corridor(scene.anchor.side),)
            for corridor in corridors:
                painter.fillRect(QRectF(corridor.left, corridor.top, corridor.right - corridor.left, corridor.bottom - corridor.top), QColor('#2d4447'))

            def pen(color, style=Qt.PenStyle.SolidLine):
                p = QPen(QColor(color), 1, style)
                p.setCosmetic(True)
                return p

            painter.setPen(pen('#2e3e4d'))
            for x in range(0, int(world.width) + 1, 40):
                painter.drawLine(QPointF(x, 0), QPointF(x, world.height))
            for y in range(0, int(world.height) + 1, 40):
                painter.drawLine(QPointF(0, y), QPointF(world.width, y))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen('#8ea1b4'))
            pad = world.rail_inset
            radius = scene.navigator.rail.radius if scene.navigator else 12
            painter.drawRoundedRect(QRectF(pad, pad, world.width - pad * 2, world.height - pad * 2), radius, radius)
            painter.setPen(pen('#5e827f', Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(inner.left, inner.top, inner.right - inner.left, inner.bottom - inner.top))
            painter.setPen(pen('#50677c', Qt.PenStyle.DotLine))
            painter.drawEllipse(point(scene.base), scene.arm.maximum_reach, scene.arm.maximum_reach)
            if scene.navigator and self.show_path:
                nav = scene.navigator
                if self._route is not nav.route:
                    self._route = nav.route
                    self._route_path = QPainterPath(point(nav.route.start))
                    for p in nav.route.samples[1:]:
                        self._route_path.lineTo(point(p))
                painter.setPen(pen('#78ada0', Qt.PenStyle.DashLine))
                painter.drawPath(self._route_path)
                painter.setPen(pen('#b8edba'))
                painter.drawEllipse(point(nav.guide), 3, 3)
            self.renderer.draw(painter, scene, self.clock.alpha, self.skeleton)

            def cross(pos, color, size=5):
                painter.setPen(pen(color))
                painter.drawLine(point(pos + Vec2(-size, 0)), point(pos + Vec2(size, 0)))
                painter.drawLine(point(pos + Vec2(0, -size)), point(pos + Vec2(0, size)))
            cross(scene.target, '#8be5ae' if scene.arrived else '#ffc478')
            # 请求点限于可见范围，仅显示合法与裁剪目标之间的连线。
            if (scene.requested_target - scene.target).length() > 1:
                p = Vec2(max(0, min(world.width, scene.requested_target.x)), max(0, min(world.height, scene.requested_target.y)))
                cross(p, '#bb7b74', 4)
                painter.setPen(pen('#bb7b74', Qt.PenStyle.DotLine))
                painter.drawLine(point(p), point(scene.target))
            if scene.look_target is not None:
                cross(scene.look_target, '#7cbfff', 7)
                painter.setPen(pen('#5b839c', Qt.PenStyle.DotLine))
                painter.drawLine(point(scene.head.position), point(scene.look_target))
            if self.show_path:
                for pearl in scene.fixed_pearls.roots:
                    cross(pearl.home, '#849aab', 3)
                if scene.pearl_matrix is not None:
                    matrix = scene.pearl_matrix
                    cross(matrix.anchor.home, '#b3a2c7', 4)
                    if not matrix.anchor.settled:
                        route = matrix.anchor.route
                        if getattr(self, '_matrix_route', None) is not route:
                            self._matrix_route = route
                            self._matrix_path = QPainterPath(point(route.start))
                            for p in route.samples[1:]:
                                self._matrix_path.lineTo(point(p))
                        painter.setPen(pen('#88769c', Qt.PenStyle.DotLine))
                        painter.drawPath(self._matrix_path)
                    if matrix.extracted is not None:
                        pearl = matrix.extracted
                        cross(pearl.home, '#e5c281', 4)
                        if not pearl.settled:
                            route = pearl.route
                            if getattr(self, '_extracted_route', None) is not route:
                                self._extracted_route = route
                                self._extracted_path = QPainterPath(point(route.start))
                                for p in route.samples[1:]:
                                    self._extracted_path.lineTo(point(p))
                            painter.setPen(pen('#c4a16a', Qt.PenStyle.DotLine))
                            painter.drawPath(self._extracted_path)
                fixed = scene.fixed_pearls.roots
                pearl = scene.observed_pearl if scene.observed_pearl in fixed else (fixed[0] if fixed else None)
                bounds = pearl.follow_bounds if pearl is not None else None
                if bounds is not None:
                    painter.setPen(pen('#536b80', Qt.PenStyle.DotLine))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(QRectF(bounds.left, bounds.top, bounds.right-bounds.left, bounds.bottom-bounds.top))
                if pearl is not None and not pearl.settled:
                    painter.setPen(pen('#849aab', Qt.PenStyle.DotLine))
                    route = pearl.route
                    if getattr(self, '_pearl_route', None) is not route:
                        self._pearl_route = route
                        self._pearl_path = QPainterPath(point(route.start))
                        for p in route.samples[1:]:
                            self._pearl_path.lineTo(point(p))
                    painter.drawPath(self._pearl_path)
            painter.restore()
            painter.setPen(QColor('#8fa4b5'))
            mode = '适应窗口' if self.view_scale is None else '固定比例'
            painter.drawText(QPointF(14, 23), f'{mode} · {scale*self.devicePixelRatioF():g}×（屏幕像素）')
            painter.drawText(QPointF(26, self.height() - 24), '绿色：边缘活动带   灰色十字：珍珠悬浮点   虚线框：珍珠跟随范围')
            if self.magnifier:
                rect = self.magnifier_rect()
                painter.save()
                painter.setClipRect(rect)
                painter.fillRect(rect, QColor('#17232e'))
                painter.translate(rect.center().x(), rect.center().y())
                zoom = 4/self.devicePixelRatioF()
                painter.scale(zoom, zoom)
                upper = scene.body.chunks[0]
                center = upper.previous_position.lerp(upper.position, self.clock.alpha)
                painter.translate(-center.x, -center.y)
                self.renderer.draw(painter, scene, self.clock.alpha, self.skeleton,
                                   raster_scale=scale*self.devicePixelRatioF())
                painter.restore()
                painter.setPen(QPen(QColor('#536b80'), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)
                painter.setPen(QColor('#bfceda'))
                painter.drawText(QPointF(rect.left() + 10, rect.top() + 22), '人偶局部 · 4× · 主视图像素')
        finally:
            painter.end()


class OracleDebugWindow(QMainWindow):
    # 调试画布最高 30 fps，固定物理仍为 40 Hz；避免空闲 CPU 全用于重复预览。
    RENDER_HZ = 30

    def __init__(self, config: AppConfig, config_path: Path | None = None, *, load_atlas=True, voice_source=None):
        super().__init__()
        self.config, self.config_path = config, config_path
        self.scene = OracleScene(config.oracle)
        self.scene.drag.set_enabled(config.interaction.drag_enabled)
        self.voice_player = make_bell_voice_player(config, config_path, self,
                                                  initialize=load_atlas, source=voice_source)
        self.voice_player.sync(self.scene.drag_reactions.voice)
        self.clock = FixedStepper(self.scene.TICK_RATE)
        self.asset_message = '几何预览（未加载图集）'
        atlas = None
        if load_atlas:
            try:
                atlas = Atlas(extract_atlas(config.game_dir))
                self.renderer = OracleRenderer(atlas, config.oracle.colors)
                self.asset_message = '已加载本机原版主图集 · Bell'
                try:
                    self.renderer.glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
                    self.asset_message += ' · 珍珠使用原版字形裁图缓存'
                except (AtlasError, OSError, ValueError) as exc:
                    self.asset_message += f' · 珍珠字形不可用：{exc}'
            except (AtlasError, OSError, ValueError) as exc:
                self.asset_message = f'图集不可用，使用几何预览：{exc}'
                self.renderer = OracleRenderer(colors=config.oracle.colors)
        else:
            self.renderer = OracleRenderer(colors=config.oracle.colors)
        self.canvas = OracleCanvas(self.scene, self.clock, self.renderer)
        self.setWindowTitle('Oracle · Bell — 漂浮与珍珠观察')
        self.resize(1220, 830)
        root, layout = QWidget(), QVBoxLayout()
        root.setLayout(layout)
        self.setCentralWidget(root)
        toolbar = QHBoxLayout()
        self.pause_button = QPushButton('暂停 [Space]')
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self.set_paused)
        self.step_button = QPushButton('单步 [N]')
        self.step_button.clicked.connect(self.single_step)
        self.reset_button = QPushButton('重置 [R]')
        self.reset_button.clicked.connect(self.reset_scene)
        self.stop_button = QPushButton('停止移动')
        self.stop_button.clicked.connect(self.stop_motion)
        self.skeleton_box = QCheckBox('骨架叠加')
        self.skeleton_box.toggled.connect(self.set_skeleton)
        self.zoom_box = QCheckBox('局部放大')
        self.zoom_box.setChecked(True)
        self.zoom_box.toggled.connect(self.set_magnifier)
        for widget in (self.pause_button, self.step_button, self.reset_button, self.stop_button,
                       self.skeleton_box, self.zoom_box):
            toolbar.addWidget(widget)
        toolbar.addStretch()
        self.drag_box = QCheckBox('允许拖动人偶')
        self.drag_box.setChecked(config.interaction.drag_enabled)
        self.drag_box.toggled.connect(self.set_drag_enabled)
        toolbar.addWidget(self.drag_box)
        toolbar.addWidget(QLabel('预览比例'))
        self.scale_input = QComboBox()
        for text, value in (('固定 1×', 1.), ('固定 2×', 2.), ('固定 4×', 4.), ('适应窗口', None)):
            self.scale_input.addItem(text, value)
        self.scale_input.setToolTip('固定倍率按屏幕像素计算，不随窗口大小或系统 DPI 缩放；适应窗口显示全景')
        self.scale_input.currentIndexChanged.connect(self.set_view_scale)
        toolbar.addWidget(self.scale_input)
        self.focus_button = QPushButton('定位人偶')
        self.focus_button.setToolTip('将人偶移到视图中心，不修改人偶位置；中键拖动可平移视图')
        self.focus_button.clicked.connect(self.canvas.center_on_pet)
        toolbar.addWidget(self.focus_button)
        layout.addLayout(toolbar)
        audio_controls = QHBoxLayout()
        audio_controls.addWidget(QLabel('像素样式'))
        self.pixel_mode_input = QComboBox()
        for text, value in (('精细像素', 'adaptive'), ('原始像素', 'classic')):
            self.pixel_mode_input.addItem(text, value)
        self.pixel_mode_input.setCurrentIndex(self.pixel_mode_input.findData(config.oracle.pixel_mode))
        self.pixel_mode_input.setToolTip('大倍率下细化人偶与光环的轮廓；原始像素保留较粗的像素块')
        self.pixel_mode_input.currentIndexChanged.connect(self.set_pixel_mode)
        audio_controls.addWidget(self.pixel_mode_input)
        self.voice_box = QCheckBox('播放语音')
        self.voice_box.setChecked(config.audio.enabled)
        self.voice_box.toggled.connect(lambda enabled: self.voice_player.configure(enabled=enabled))
        audio_controls.addWidget(self.voice_box)
        audio_controls.addWidget(QLabel('音量'))
        self.voice_volume = QSpinBox()
        self.voice_volume.setRange(0, 100)
        self.voice_volume.setSuffix(' %')
        self.voice_volume.setValue(round(config.audio.volume*100))
        self.voice_volume.valueChanged.connect(lambda value: self.voice_player.configure(volume=value/100))
        audio_controls.addWidget(self.voice_volume)
        self.voice_status = QLabel(self.voice_player.status)
        self.voice_status.setWordWrap(True)
        self.voice_player.status_changed.connect(self.voice_status.setText)
        audio_controls.addWidget(self.voice_status, 1)
        layout.addLayout(audio_controls)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('初始底座'))
        self.side_input = QComboBox()
        for text, value in (('上边', 'top'), ('右边', 'right'), ('下边', 'bottom'), ('左边', 'left')):
            self.side_input.addItem(text, value)
        self.side_input.setCurrentIndex(self.side_input.findData(config.oracle.base_side))
        controls.addWidget(self.side_input)
        self.base_input = QDoubleSpinBox()
        self.base_input.setRange(0, 100)
        self.base_input.setSuffix(' %')
        self.base_input.setValue(config.oracle.base_fraction * 100)
        controls.addWidget(self.base_input)
        self.place_button = QPushButton('放置并重置')
        self.place_button.clicked.connect(self.place_anchor)
        controls.addWidget(self.place_button)
        controls.addWidget(QLabel('基础倾角'))
        self.tilt_input = QDoubleSpinBox()
        self.tilt_input.setRange(-25, 25)
        self.tilt_input.setSuffix('°')
        self.tilt_input.setToolTip('普通行动在停留姿态附近轻微侧倾；失重时朝向由运动和观察牵引改变，结束后保留姿态。')
        self.tilt_input.valueChanged.connect(self.scene.set_tilt)
        controls.addWidget(self.tilt_input)
        self.look_pearl_button = QPushButton('靠近观察一次')
        self.look_pearl_button.clicked.connect(lambda: self.observe_pearl('approach'))
        controls.addWidget(self.look_pearl_button)
        self.clear_look_button = QPushButton('观察回正')
        self.clear_look_button.clicked.connect(self.clear_look)
        controls.addWidget(self.clear_look_button)
        controls.addStretch()
        layout.addLayout(controls)
        navigation = QHBoxLayout()
        self.sliding_box = QCheckBox('底座沿四边滑动')
        self.sliding_box.setChecked(self.scene.sliding_base)
        self.sliding_box.setToolTip('切换会重置场景；关闭后可复测首批固定底座模式')
        self.sliding_box.toggled.connect(self.set_sliding_mode)
        navigation.addWidget(self.sliding_box)
        self.clockwise_button = QPushButton('顺时针绕行一周')
        self.clockwise_button.clicked.connect(lambda: self.start_lap(True))
        self.counterclockwise_button = QPushButton('逆时针绕行一周')
        self.counterclockwise_button.clicked.connect(lambda: self.start_lap(False))
        navigation.addWidget(self.clockwise_button)
        navigation.addWidget(self.counterclockwise_button)
        self.path_box = QCheckBox('显示规划曲线')
        self.path_box.setChecked(True)
        self.path_box.toggled.connect(self.set_path_visible)
        navigation.addWidget(self.path_box)
        self.matrix_box = QCheckBox('珍珠矩阵')
        self.matrix_box.setChecked(self.scene.pearl_matrix_enabled)
        self.matrix_box.setToolTip('珍珠随人偶整组迁移，允许抽出一颗观察后回到原槽位。数量可在下方预览，0 表示不创建。')
        self.matrix_box.toggled.connect(self.set_pearl_matrix)
        navigation.addWidget(self.matrix_box)
        self.orbit_pearl_button = QPushButton('绕珠观察一次')
        self.orbit_pearl_button.setToolTip('先靠近，再沿当前边内的局部圆弧观察；空间不足时保持原地观察。')
        self.orbit_pearl_button.clicked.connect(lambda: self.observe_pearl('orbit'))
        self.orbit_pearl_button.setEnabled(self.scene.sliding_base)
        navigation.addWidget(self.orbit_pearl_button)
        self.meditate_button = QPushButton('冥想一次')
        self.meditate_button.setToolTip('向当前走廊中间稍微收拢，闭眼低头；停稳后保持 30～60 秒，外观可休眠。')
        self.meditate_button.clicked.connect(self.meditate)
        navigation.addWidget(self.meditate_button)
        navigation.addStretch()
        self.clockwise_button.setEnabled(self.scene.sliding_base)
        self.counterclockwise_button.setEnabled(self.scene.sliding_base)
        layout.addLayout(navigation)
        behavior_row = QHBoxLayout()
        self.autonomous_box = QCheckBox('自主行为')
        self.autonomous_box.setToolTip('停留、冥想、同边短途、低概率反重力漫游与邻边移动、珍珠观察独立选择；手动操作接管后停止循环。')
        self.autonomous_box.toggled.connect(self.set_autonomous)
        behavior_row.addWidget(self.autonomous_box)
        self.short_roam_button = QPushButton('短途漂浮一次')
        self.short_roam_button.clicked.connect(lambda: self.roam(False))
        behavior_row.addWidget(self.short_roam_button)
        self.drift_button = QPushButton('反重力漫游一次')
        self.drift_button.setToolTip(f'沿边自由漂浮约 {config.oracle.antigravity_duration_seconds:g} 秒'
                                    '（每次浮动 ±10%），期间可以观察珍珠、低概率移到邻边；结束后平滑恢复直立。')
        self.drift_button.clicked.connect(self.drift)
        behavior_row.addWidget(self.drift_button)
        self.cross_edge_button = QPushButton('移到邻边一次')
        self.cross_edge_button.setToolTip('只移到当前边的两条相邻边之一，最多经过一个角；此按钮不受随机概率与冷却限制。')
        self.cross_edge_button.clicked.connect(lambda: self.roam(True))
        self.cross_edge_button.setEnabled(self.scene.sliding_base)
        behavior_row.addWidget(self.cross_edge_button)
        self.recall_pearl_button = QPushButton('召近观察一次')
        self.recall_pearl_button.clicked.connect(lambda: self.observe_pearl('recall'))
        behavior_row.addWidget(self.recall_pearl_button)
        self.matrix_pearl_button = QPushButton('抽取矩阵珠一次')
        self.matrix_pearl_button.setToolTip('随机选一颗矩阵珍珠召近观察，保留空位，结束后送回；重复点击仍使用已抽出的珠子。')
        self.matrix_pearl_button.clicked.connect(self.observe_matrix_pearl)
        behavior_row.addWidget(self.matrix_pearl_button)
        self.return_pearl_button = QPushButton('结束观察并送回')
        self.return_pearl_button.clicked.connect(self.stop_motion)
        behavior_row.addWidget(self.return_pearl_button)
        behavior_row.addWidget(QLabel('Shift + 左键：移动最近固定珠的悬浮点'))
        behavior_row.addStretch()
        layout.addLayout(behavior_row)
        pearl_row = QHBoxLayout()
        self.orbits_box = QCheckBox('环绕珍珠')
        self.orbits_box.setChecked(self.scene.pearl_orbits_enabled)
        self.orbits_box.toggled.connect(self.set_pearl_orbits)
        pearl_row.addWidget(self.orbits_box)
        self.pearl_count_inputs = {}
        for key, label, maximum in (('matrix', '矩阵', 64), ('inner', '内圈', 32), ('outer', '外圈', 32),
                                    ('fixed', '固定', 32), ('satellite', '卫星', 32)):
            pearl_row.addWidget(QLabel(label))
            control = QSpinBox()
            control.setRange(0, maximum)
            control.setValue(getattr(self.scene.config, f'pearl_{key}_count'))
            control.setKeyboardTracking(False)
            control.setToolTip('0 隐藏这一类；卫星需要至少一颗固定母珠。颜色按比例分配，仅预览，永久修改请写入 TOML。')
            control.valueChanged.connect(lambda value, key=key: self.set_pearl_count(key, value))
            pearl_row.addWidget(control)
            self.pearl_count_inputs[key] = control
        pearl_row.addWidget(QLabel('数量仅本次预览；0 隐藏对应一类，永久配置见 TOML'))
        pearl_row.addStretch()
        layout.addLayout(pearl_row)
        halo_row = QHBoxLayout()
        self.halo_box = QCheckBox('光环')
        self.halo_box.setChecked(self.scene.config.halo_enabled)
        self.halo_box.toggled.connect(self.set_halo_enabled)
        halo_row.addWidget(self.halo_box)
        self.halo_pulse_button = QPushButton('光环扩张一次')
        self.halo_pulse_button.setToolTip('预览平滑扩张与恢复；保持当前自主行为，暂停时可用单步查看。')
        self.halo_pulse_button.clicked.connect(self.pulse_halo)
        halo_row.addWidget(self.halo_pulse_button)
        self.halo_flash_button = QPushButton('外圈闪烁一次')
        self.halo_flash_button.clicked.connect(self.flash_halo)
        halo_row.addWidget(self.halo_flash_button)
        self.halo_fill_button = QPushButton('实心化一次')
        self.halo_fill_button.setToolTip('强制进入实心目标并重选尺寸；保持时间与自然事件一样随机，退出时由中央挖空。暂停时可单步查看。')
        self.halo_fill_button.clicked.connect(self.fill_halo)
        halo_row.addWidget(self.halo_fill_button)
        halo_row.addWidget(QLabel('与珍珠投影共用颜色和透明度；空间不足时限制尺寸'))
        halo_row.addStretch()
        layout.addLayout(halo_row)
        hint = QLabel('左键：指定移动目标　右键：独立观察（均接管自主行为）　中键拖动：平移视图；放大镜内不设置目标')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        body = QHBoxLayout()
        body.addWidget(self.canvas, 1)
        panel = QGroupBox('外观调色 · 点击色块预览')
        panel.setFixedWidth(240)
        palette_layout = QVBoxLayout(panel)
        grid = QGridLayout()
        self.color_buttons = {}
        for row, field in enumerate(fields(OracleColors)):
            grid.addWidget(QLabel(COLOR_LABELS[field.name]), row, 0)
            button = QPushButton()
            button.setFixedWidth(92)
            button.clicked.connect(lambda checked=False, key=field.name: self.choose_color(key))
            grid.addWidget(button, row, 1)
            self.color_buttons[field.name] = button
        palette_layout.addLayout(grid)
        self.reload_button = QPushButton('重新读取配置颜色')
        self.reload_button.clicked.connect(self.reload_colors)
        self.default_button = QPushButton('恢复默认配色')
        self.default_button.clicked.connect(lambda: self.set_colors(OracleColors()))
        palette_layout.addWidget(self.reload_button)
        palette_layout.addWidget(self.default_button)
        note = QLabel('色块修改仅影响当前预览。\n永久修改：config.toml\n[oracle.colors]\n\n以完好 Moon 为基础的 Bell。\n衣袍、念珠与连接线随移动摆动，停止后逐渐收敛。')
        note.setWordWrap(True)
        palette_layout.addWidget(note)
        palette_layout.addStretch()
        body.addWidget(panel)
        layout.addLayout(body, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.assets = QLabel(self.asset_message)
        self.assets.setWordWrap(True)
        layout.addWidget(self.assets)
        self.canvas.target_picked.connect(self.pick_target)
        self.canvas.look_picked.connect(self.pick_look)
        self.canvas.pearl_picked.connect(self.pick_pearl_home)
        self.shortcuts = []
        for key, callback in (('Space', self.pause_button.click), ('N', self.single_step), ('R', self.reset_scene)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        self.last_time = perf_counter()
        self._last_status_time = 0.
        self._last_visual_revision = None
        self._next_render_time = 0.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(16)
        self.set_colors(config.oracle.colors)
        self.refresh()

    def set_colors(self, colors):
        self.renderer.colors = colors
        for name, button in self.color_buttons.items():
            value = getattr(colors, name)
            button.setText(value)
            foreground = '#111111' if QColor(value).lightnessF() > .53 else '#ffffff'
            button.setStyleSheet(f'background-color: {value}; color: {foreground}; padding: 5px;')
        self.canvas.update()

    def choose_color(self, name):
        color = QColorDialog.getColor(QColor(getattr(self.renderer.colors, name)), self, COLOR_LABELS[name])
        if color.isValid():
            self.set_colors(replace(self.renderer.colors, **{name: color.name()}))

    def reload_colors(self):
        try:
            colors = AppConfig.load(self.config_path).oracle.colors if self.config_path else self.config.oracle.colors
            self.set_colors(colors)
            self.assets.setText(self.asset_message + ' · 已重新读取颜色')
        except (OSError, ValueError, TypeError) as exc:
            self.assets.setText(f'颜色读取失败，保留当前预览：{exc}')

    def set_skeleton(self, enabled):
        self.canvas.skeleton = enabled
        self.canvas.update()

    def set_magnifier(self, enabled):
        self.canvas.magnifier = enabled
        self.canvas.update()

    def set_view_scale(self, index):
        scale = self.scale_input.currentData()
        self.canvas.set_view_scale(scale)
        self.focus_button.setEnabled(scale is not None)
        if scale is not None:
            self.canvas.center_on_pet()

    def set_pixel_mode(self, index):
        self.scene.config = replace(self.scene.config, pixel_mode=self.pixel_mode_input.currentData())
        self.canvas.update()

    def set_paused(self, paused):
        if paused:
            self.cancel_drag()
        self.clock.set_paused(paused)
        self.last_time = perf_counter()
        self.pause_button.setText('继续 [Space]' if paused else '暂停 [Space]')
        self.refresh()

    def single_step(self):
        self.pause_button.setChecked(True)
        self.clock.single_step(self.scene.step)
        self.refresh()

    def reset_scene(self):
        self.cancel_drag()
        self.scene.reset()
        self.clock.set_paused(self.pause_button.isChecked())
        self.clock.dropped_seconds = 0
        self.last_time = perf_counter()
        self.refresh()

    def place_anchor(self):
        self.cancel_drag()
        self.scene.set_anchor(self.side_input.currentData(), self.base_input.value() / 100)
        self.clock.set_paused(self.pause_button.isChecked())
        self.clock.dropped_seconds = 0
        self.last_time = perf_counter()
        self.refresh()

    def stop_motion(self):
        self.scene.stop()
        self.refresh()

    def set_sliding_mode(self, enabled):
        self.cancel_drag()
        self.scene.set_sliding_base(enabled)
        self.clock.set_paused(self.pause_button.isChecked())
        self.clock.dropped_seconds = 0
        self.last_time = perf_counter()
        self.clockwise_button.setEnabled(enabled)
        self.counterclockwise_button.setEnabled(enabled)
        self.cross_edge_button.setEnabled(enabled)
        self.orbit_pearl_button.setEnabled(enabled)
        self.refresh()

    def start_lap(self, clockwise):
        self.scene.start_lap(clockwise)
        self.refresh()

    def set_path_visible(self, enabled):
        self.canvas.show_path = enabled
        self.canvas.update()

    def pick_target(self, x, y):
        self.scene.set_target(Vec2(x, y))
        self.refresh()

    def set_autonomous(self, enabled):
        self.scene.set_autonomous(enabled)
        self.refresh()

    def set_pearl_matrix(self, enabled):
        self.scene.set_pearl_matrix(enabled)
        self.refresh()

    def set_halo_enabled(self, enabled):
        self.scene.set_halo_enabled(enabled)
        self.refresh()

    def pulse_halo(self):
        self.scene.pulse_halo()
        self.refresh()

    def flash_halo(self):
        self.scene.halo.flash_ring(2)
        self.refresh()

    def fill_halo(self):
        self.scene.halo.pulse_fill()
        self.refresh()

    def observe_pearl(self, mode):
        self.scene.observe_pearl(mode)
        self.refresh()

    def observe_matrix_pearl(self):
        self.scene.observe_matrix_pearl()
        self.refresh()

    def set_pearl_orbits(self, enabled):
        self.scene.set_pearl_orbits(enabled)
        self.refresh()

    def set_pearl_count(self, key, value):
        self.scene.set_pearl_counts(**{key: value})
        self.refresh()

    def roam(self, adjacent):
        self.scene.roam(adjacent=adjacent)
        self.refresh()

    def drift(self):
        self.scene.drift()
        self.refresh()

    def meditate(self):
        self.scene.meditate()
        self.refresh()

    def pick_pearl_home(self, x, y):
        self.scene.set_pearl_home(Vec2(x, y))
        self.refresh()

    def pick_look(self, x, y):
        self.scene.set_look_target(Vec2(x, y))
        self.refresh()

    def clear_look(self):
        self.scene.set_look_target(None)
        self.refresh()

    def on_timer(self):
        now = perf_counter()
        self.clock.advance(now - self.last_time, self.scene.step)
        self.last_time = now
        self.voice_player.sync(self.scene.drag_reactions.voice, paused=self.clock.paused)
        self.refresh(force=False)

    def refresh(self, *, force=True):
        scene = self.scene
        self.halo_pulse_button.setEnabled(scene.halo_visible)
        self.halo_flash_button.setEnabled(scene.halo_visible)
        self.halo_fill_button.setEnabled(scene.halo_visible)
        self.matrix_pearl_button.setEnabled(scene.pearl_matrix is not None)
        available = bool(scene.fixed_pearls.roots) or scene.pearl_matrix is not None
        self.look_pearl_button.setEnabled(available)
        self.recall_pearl_button.setEnabled(available)
        self.orbit_pearl_button.setEnabled(scene.sliding_base and available)
        now = perf_counter()
        revision = (scene.appearance, scene.appearance.revision, scene.pearl_visual_revision, scene.eyes.revision,
                    scene.halo_visual_revision)
        needs_frame = ((not self.clock.paused and (not scene.appearance.sleeping or not scene.arrived
                                                   or not scene.pearls_settled or scene.eyes.moving))
                       or revision != self._last_visual_revision)
        if force or (needs_frame and now >= self._next_render_time):
            self.canvas.update()
            self._last_visual_revision = revision
            interval = 1/self.RENDER_HZ
            if force or self._next_render_time == 0.:
                self._next_render_time = now+interval
            else:
                self._next_render_time += (int((now-self._next_render_time)/interval)+1)*interval
        if not force and now-self._last_status_time < .25:
            return
        self._last_status_time = now
        for control in (self.look_pearl_button, self.recall_pearl_button, self.orbit_pearl_button,
                        self.meditate_button, self.short_roam_button, self.drift_button,
                        self.cross_edge_button, self.clockwise_button, self.counterclockwise_button):
            if scene.drag.controlling:
                control.setEnabled(False)
        if not scene.drag.controlling:
            for control in (self.meditate_button, self.short_roam_button, self.drift_button):
                control.setEnabled(True)
            for control in (self.cross_edge_button, self.clockwise_button, self.counterclockwise_button):
                control.setEnabled(scene.sliding_base)
        self.autonomous_box.blockSignals(True)
        self.autonomous_box.setChecked(scene.drag.resume_autonomy if scene.drag.controlling else scene.behavior.enabled)
        self.autonomous_box.blockSignals(False)
        upper = scene.body.chunks[0]
        state = scene.behavior.state.value if scene.behavior.active else ('已停稳' if scene.arrived else '手动移动')
        if scene.drag.controlling:
            state = '鼠标拖拽' if scene.drag.active else '松手返回活动带'
            reactions = scene.drag_reactions
            state += f' · {reactions.label}'
            if reactions.voice.last_cue is not None:
                state += f' · 语音请求 {reactions.voice.last_cue.clip_id}（{reactions.voice.request_count} 次）'
        if scene.behavior.matrix_observation:
            state += f' · 矩阵 {scene.behavior.last_matrix_slot}'
        if scene.behavior.drift_active:
            state += ' · 恢复重力' if scene.behavior.drift_recovering else ' · 失重'
        state += f' · 已观察 {scene.behavior.completed_cycles} 次'
        body_angle = (scene.tilt_degrees+scene.pose.angle+180.) % 360.-180.
        state += f' · 躯干角度 {body_angle:+.1f}°'
        navigation = ''
        if scene.navigator:
            nav = scene.navigator
            base_state = '滑动' if abs(nav.base.velocity) > .01 else '停留'
            navigation = f'　底座{base_state} {nav.base.velocity:.2f} / tick'
            if nav.waiting_for_base:
                navigation += ' · 等待底座'
        self.status.setText(f'{"暂停" if self.clock.paused else "运行"} · {state} · tick {scene.ticks} · 40 Hz'
                            f'　上身 ({upper.position.x:.1f}, {upper.position.y:.1f})'
                            f'　速度 {upper.velocity.length():.3f} / tick'
                            f'　关节误差 {scene.arm.constraint_error:.3f}'
                            f'{navigation}'
                            f'　丢弃积压 {self.clock.dropped_seconds:.2f}s')

    def closeEvent(self, event):
        self.cancel_drag()
        self.timer.stop()
        super().closeEvent(event)

    def cancel_drag(self):
        self.voice_player.stop()
        self.scene.drag.release(cancel=True)
        if QWidget.mouseGrabber() is self.canvas:
            self.canvas.releaseMouse()
        self.canvas.unsetCursor()

    def set_drag_enabled(self, enabled):
        if not enabled:
            self.cancel_drag()
        self.scene.drag.set_enabled(enabled)
        self.canvas.update()
