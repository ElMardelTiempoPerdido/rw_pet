"""主屏幕工作区桌宠：透明输入穿透窗口、托盘控制、边缘巡游。"""
from dataclasses import dataclass
from time import perf_counter
from math import isfinite

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .atlas import Atlas, extract_atlas
from .config import DebugConfig
from .geometry import Vec2
from .render_lizard import LizardRenderer
from .scene import DebugScene, FlatWorld, FixedStepper


def configure_desktop_overlay(window):
    """两种桌宠共用的顶层窗口契约；透明像素与可见像素都不接收输入。"""
    window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                          | Qt.WindowType.WindowStaysOnTopHint
                          | Qt.WindowType.WindowTransparentForInput
                          | Qt.WindowType.WindowDoesNotAcceptFocus)
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


@dataclass(frozen=True, slots=True)
class EdgeWorld(FlatWorld):
    def background_regions(self):
        w, h = self.width, self.floor_y
        return ((0, 0, w*.2, h), (w*.8, 0, w*.2, h),
                (0, 0, w, h*.2), (0, h*.8, w, h*.2))

    def background_position(self, point, radius=0.0):
        # 将显示圆限制在四条边缘带的并集；中央桌面区域不是可抓附背景。
        w, h, r = self.width, self.floor_y, radius
        rectangles = ((r, r, w*.2-r, h-r), (w*.8+r, r, w-r, h-r),
                      (r, r, w-r, h*.2-r), (r, h*.8+r, w-r, h-r))
        candidates = [Vec2(max(x0, min(x1, point.x)), max(y0, min(y1, point.y)))
                      for x0, y0, x1, y1 in rectangles if x0 <= x1 and y0 <= y1]
        return min(candidates, key=lambda p: (p-point).length())

    def in_edge(self, p):
        return (0 <= p.x <= self.width and 0 <= p.y <= self.floor_y
                and (p.x <= self.width*.2 or p.x >= self.width*.8
                     or p.y <= self.floor_y*.2 or p.y >= self.floor_y*.8))

    def background_grip(self, hip, goal, reach):
        point = super(EdgeWorld, self).background_grip(hip, goal, reach)
        return point if point is not None and self.in_edge(hip) and self.in_edge(point) else None


class DesktopMotion:
    def __init__(self, width, height, scale=1.0, mode='floor'):
        if not isfinite(scale) or not .5 <= scale <= 4:
            raise ValueError('桌宠缩放必须为 0.5～4')
        if width < 300 or height < 250:
            raise ValueError('工作区过小，无法容纳桌宠')
        # 极小工作区降低实际倍率，给头尾及转向留足空间。
        self.scale = min(scale, width/600, height/500)
        w, h = width/self.scale, height/self.scale
        self.scene = DebugScene(DebugConfig(world_width=w, world_height=h+20, floor_y=h))
        self.scene.world = EdgeWorld(w, h+20, h)
        self.mode = mode
        self.route_index = 0
        inset = 55.
        self.route = (Vec2(w-inset, h-inset), Vec2(w-inset, inset),
                      Vec2(inset, inset), Vec2(inset, h-inset))
        if mode == 'wall':
            self.scene.place_on_background(inset)
            self.scene.background.set_goal(self.route[0], self.scene.body, self.scene.world)
        elif mode == 'floor':
            self.scene.gait.enabled = True
            gait = self.scene.gait
            gait.set_speed(gait.MAX_SPEED * gait.SLOW_INTENT)
        else:
            raise ValueError('未知桌面活动模式')

    def step(self):
        s = self.scene
        if self.mode == 'floor' and s.gait.blocked:
            s.gait.set_speed(-s.gait.speed)
        elif self.mode == 'wall' and s.background.arrived:
            self.route_index = (self.route_index+1) % len(self.route)
            s.background.set_goal(self.route[self.route_index], s.body, s.world)
        s.step()


class DesktopWindow(QWidget):
    def __init__(self, config, scale=1.0, mode='floor'):
        super().__init__()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError('系统托盘不可用，无法提供桌宠退出入口')
        self.renderer = LizardRenderer(Atlas(extract_atlas(config.game_dir)))
        self.requested_scale, self.mode = scale, mode
        configure_desktop_overlay(self)
        self.clock = FixedStepper(40)
        self.screen = None
        self.bind_screen(QApplication.primaryScreen())
        QApplication.instance().primaryScreenChanged.connect(self.bind_screen)
        self.tray = QSystemTrayIcon(self)
        icon = QPixmap(32, 32)
        icon.fill(Qt.GlobalColor.transparent)
        p = QPainter(icon)
        p.setBrush(QColor('white')); p.setPen(QColor('#333333'))
        p.drawEllipse(3, 10, 26, 12); p.drawEllipse(23, 12, 3, 3); p.end()
        self.tray.setIcon(QIcon(icon))
        self.menu = QMenu()
        group = QActionGroup(self.menu)
        for key, title in (('floor', '底部行走'), ('wall', '四边爬墙')):
            action = self.menu.addAction(title)
            action.setCheckable(True); action.setChecked(key == mode)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, selected=key: self.change_mode(selected))
        sizes = self.menu.addMenu('大小')
        size_group = QActionGroup(sizes)
        for factor in (1., 1.5, 2., 3.):
            action = sizes.addAction(f'{factor:g} 倍')
            action.setCheckable(True); action.setChecked(factor == scale)
            size_group.addAction(action)
            action.triggered.connect(lambda checked=False, value=factor: self.change_scale(value))
        pause = self.menu.addAction('暂停')
        pause.setCheckable(True)
        pause.toggled.connect(self.set_paused)
        self.menu.addSeparator()
        self.menu.addAction('退出桌宠', QApplication.instance().quit)
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip('WhiteLizard · 右键切换活动、暂停或退出')
        self.tray.show()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.advance)
        self.last_time = perf_counter()
        self.timer.start(16)
        QApplication.instance().aboutToQuit.connect(self.tray.hide)

    def bind_screen(self, screen):
        if self.screen is not None:
            try:
                self.screen.availableGeometryChanged.disconnect(self.rebuild)
            except (RuntimeError, TypeError):
                pass
        self.screen = screen
        if screen is not None:
            screen.availableGeometryChanged.connect(self.rebuild)
            self.rebuild()

    def rebuild(self, *args):
        rect = self.screen.availableGeometry()
        self.motion = DesktopMotion(rect.width(), rect.height(), self.requested_scale, self.mode)
        self.setGeometry(rect)
        self.clock.accumulator = 0
        self.last_time = perf_counter()
        self.update()

    def change_mode(self, mode):
        self.mode = mode
        self.rebuild()

    def change_scale(self, scale):
        self.requested_scale = scale
        self.rebuild()

    def set_paused(self, paused):
        self.clock.set_paused(paused)
        s = self.motion.scene
        for point in [*s.body.chunks, *s.feet]:
            point.previous_position = point.position
        s.appearance.sync_previous()
        self.last_time = perf_counter()
        self.update()

    def advance(self):
        now = perf_counter()
        self.clock.advance(now-self.last_time, self.motion.step)
        self.last_time = now
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.scale(self.motion.scale, self.motion.scale)
        self.renderer.draw(p, self.motion.scene, self.clock.alpha)
        p.end()

    def closeEvent(self, event):
        self.timer.stop()
        self.tray.hide()
        super().closeEvent(event)
