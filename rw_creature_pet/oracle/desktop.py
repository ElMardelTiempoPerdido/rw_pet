"""Oracle 桌面接入：主屏工作区、物理像素倍率、透明穿透与托盘入口。"""
from dataclasses import dataclass, replace
from math import isfinite
from time import perf_counter

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, QTimer, Slot
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPixmap, QScreen
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from ..shared.atlas import Atlas, AtlasError, extract_atlas
from ..shared.desktop import configure_desktop_overlay
from ..interaction.desktop import DragInputWindow
from ..interaction.audio import AudioConfig, VoicePlayer
from .voice import bell_voice_paths
from .input import PuppetHitMap
from ..shared.geometry import Vec2
from .scene import OracleScene, RailSide
from .glyphs import load_pearl_glyphs
from .navigation import CurveRoute
from .render import OracleRenderer
from .damage import visual_bounds
from ..shared.timing import FixedStepper


@dataclass(frozen=True, slots=True)
class OracleDesktopViewport:
    """工作区使用 Qt 的全局 DIP；场景单位通过倍率换成屏幕物理像素。"""
    x: float
    y: float
    width: float
    height: float
    dpr: float = 1.
    requested_scale: float = 1.

    def __post_init__(self):
        if not all(isfinite(v) for v in (self.x, self.y, self.width, self.height, self.dpr, self.requested_scale)):
            raise ValueError('桌面坐标和缩放必须为有限数值')
        if self.width <= 0 or self.height <= 0 or self.dpr <= 0:
            raise ValueError('桌面工作区和 DPI 倍率必须大于零')
        if not .5 <= self.requested_scale <= 4:
            raise ValueError('桌宠缩放必须为 0.5～4')

    @property
    def physical_scale(self):
        # 小工作区或较大倍率时，仍为原有四边导航保留至少 640×480 单位。
        return min(self.requested_scale, self.width*self.dpr/640, self.height*self.dpr/480)

    @property
    def scale(self):
        return self.physical_scale/self.dpr

    @property
    def world_size(self):
        return Vec2(max(640., self.width/self.scale), max(480., self.height/self.scale))

    def to_global(self, point):
        return Vec2(self.x, self.y)+point*self.scale

    def to_world(self, point):
        return (point-Vec2(self.x, self.y))*(1/self.scale)


def current_anchor(scene):
    """把正在滑动的底座映射到当前边及边内比例，而非最初配置的边。"""
    p, w = scene.base, scene.world
    side = min(((p.y, RailSide.TOP), (w.width-p.x, RailSide.RIGHT),
                (w.height-p.y, RailSide.BOTTOM), (p.x, RailSide.LEFT)), key=lambda item: item[0])[1]
    horizontal = side in (RailSide.TOP, RailSide.BOTTOM)
    along = p.x if horizontal else p.y
    length = w.width if horizontal else w.height
    fraction = (along-w.rail_inset)/(length-2*w.rail_inset)
    return side, max(0., min(1., fraction))


class OracleDesktopMotion:
    def __init__(self, config, viewport, previous=None):
        self.viewport = viewport
        size = viewport.world_size
        settings = replace(config, world_width=size.x, world_height=size.y, sliding_base=True)
        if previous is not None:
            side, fraction = current_anchor(previous)
            settings = replace(settings, base_side=side.value, base_fraction=fraction,
                               pearl_matrix_enabled=previous.pearl_matrix_enabled,
                               pearl_orbits_enabled=previous.pearl_orbits_enabled,
                               halo_enabled=previous.config.halo_enabled,
                               pearl_matrix_count=previous.config.pearl_matrix_count,
                               pearl_inner_count=previous.config.pearl_inner_count,
                               pearl_outer_count=previous.config.pearl_outer_count,
                               pearl_fixed_count=previous.config.pearl_fixed_count,
                               pearl_satellite_count=previous.config.pearl_satellite_count)
        self.scene = OracleScene(settings)
        if previous is not None:
            # 原路径/速度不能沿用到变形后的非凸活动带。身体、底座、头颈及
            # 次级外观整组重建，第一帧的 previous/current 一致，避免跨屏拉线。
            old = previous.world
            for pearl, prior in zip(self.scene.fixed_pearls.roots, previous.fixed_pearls.roots):
                p = prior.home
                home = pearl.nearby_home(Vec2(p.x/old.width*size.x, p.y/old.height*size.y),
                    self.scene.body.chunks[0].position, pearl.region, settings.pearl_follow_width, settings.pearl_follow_height)
                pearl.home = pearl.target = pearl.position = pearl.previous_position = home
                pearl.route = CurveRoute([], home)
                pearl.glyph_id, pearl.color_slot = prior.glyph_id, prior.color_slot
            self.scene.fixed_pearls.sync_positions()
            self.scene.behavior.random.setstate(previous.behavior.random.getstate())
            self.scene.behavior.pace_random.setstate(previous.behavior.pace_random.getstate())
            self.scene.behavior.detail_random.setstate(previous.behavior.detail_random.getstate())
            self.scene.behavior.timing_random.setstate(previous.behavior.timing_random.getstate())
            self.scene.behavior.pearl_random.setstate(previous.behavior.pearl_random.getstate())
            self.scene.behavior.fixed_random.setstate(previous.behavior.fixed_random.getstate())
            self.scene.behavior.last_matrix_slot = previous.behavior.last_matrix_slot
            self.scene.behavior.last_fixed_index = previous.behavior.last_fixed_index
            self.scene.eyes.random.setstate(previous.eyes.random.getstate())
            for name in ('random', 'eye_random', 'voice_random'):
                getattr(self.scene.drag_reactions, name).setstate(getattr(previous.drag_reactions, name).getstate())
            self.scene.halo.random.setstate(previous.halo.random.getstate())
            self.scene.behavior.completed_cycles = previous.behavior.completed_cycles
            self.scene.behavior.cross_cooldown = previous.behavior.cross_cooldown
            self.scene.behavior.drift_cooldown = previous.behavior.drift_cooldown
        autonomous = True if previous is None else (
            previous.drag.resume_autonomy if previous.drag.controlling else previous.behavior.enabled)
        self.scene.set_autonomous(autonomous)

    def step(self):
        self.scene.step()


class OracleDesktopWindow(QWidget):
    RENDER_HZ = 30

    def __init__(self, config, scale=1., config_path=None, *, renderer=None):
        super().__init__()
        if not isfinite(scale) or not .5 <= scale <= 4:
            raise ValueError('桌宠缩放必须为 0.5～4')
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError('系统托盘不可用，无法提供桌宠退出入口')
        self.config, self.config_path = config, config_path
        self.voice_player = VoicePlayer(bell_voice_paths(config.oracle, config_path), config.audio, self)
        self.requested_scale = scale
        self.asset_message = 'Bell · 原版主图集与珍珠字形缓存'
        if renderer is None:
            atlas = Atlas(extract_atlas(config.game_dir))
            renderer = OracleRenderer(atlas, config.oracle.colors)
            try:
                renderer.glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
            except (AtlasError, OSError, ValueError) as exc:
                self.asset_message = f'珍珠投影不可用：{exc}'
        self.renderer = renderer
        configure_desktop_overlay(self)
        self.setWindowTitle('Oracle · Bell 桌宠')
        self.clock = FixedStepper(40)
        self.motion = None
        self.screen = None
        self._screen_connections = []
        self._signature = None
        self._last_revision = None
        self._painted_bounds = QRect()
        self._next_render_time = 0.
        self.last_time = perf_counter()
        self._closing = False
        self._screen_valid = False
        self.debug_window = None
        self.drag_input = DragInputWindow(self)
        self.drag_hit = PuppetHitMap()
        self.rebuild_timer = QTimer(self)
        self.rebuild_timer.setSingleShot(True)
        self.rebuild_timer.setInterval(100)
        self.rebuild_timer.timeout.connect(self.rebuild)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.advance)
        self.create_tray()
        app = QApplication.instance()
        # 调试窗口是普通顶层窗口，关闭它应回到桌宠，而非退出整个进程。
        app.setQuitOnLastWindowClosed(False)
        app.primaryScreenChanged.connect(self.bind_screen)
        app.aboutToQuit.connect(self.cleanup)
        self.bind_screen(app.primaryScreen())
        self.tray.show()
        self.timer.start(16)

    def create_tray(self):
        self.tray = QSystemTrayIcon(self)
        icon = QPixmap(32, 32)
        icon.fill(Qt.GlobalColor.transparent)
        p = QPainter(icon)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.renderer.colors.robe_top))
        p.drawEllipse(6, 17, 20, 14)
        p.setBrush(QColor(self.renderer.colors.head_shell))
        p.drawRect(3, 7, 4, 9)
        p.drawRect(25, 7, 4, 9)
        p.setBrush(QColor(self.renderer.colors.skin))
        p.drawEllipse(7, 2, 18, 18)
        p.setBrush(QColor(self.renderer.colors.eyes))
        p.drawRect(11, 12, 2, 2)
        p.drawRect(19, 12, 2, 2)
        p.end()
        self.tray.setIcon(QIcon(icon))
        self.menu = QMenu(self)
        self.pause_action = self.menu.addAction('暂停')
        self.pause_action.setCheckable(True)
        self.pause_action.toggled.connect(self.set_paused)
        self.drag_action = self.menu.addAction('允许拖动人偶')
        self.drag_action.setCheckable(True)
        self.drag_action.setChecked(self.config.interaction.drag_enabled)
        self.drag_action.toggled.connect(self.set_drag_enabled)
        audio_menu = self.menu.addMenu('语音')
        self.voice_action = audio_menu.addAction('播放语音')
        self.voice_action.setCheckable(True)
        self.voice_action.setChecked(self.voice_player.enabled)
        self.voice_action.toggled.connect(lambda enabled: self.voice_player.configure(enabled=enabled))
        volume_group = QActionGroup(audio_menu)
        for volume in sorted({0., .25, .5, .7, 1., self.voice_player.volume}):
            action = audio_menu.addAction(f'音量 {volume:.0%}')
            action.setCheckable(True)
            action.setChecked(volume == self.voice_player.volume)
            volume_group.addAction(action)
            action.triggered.connect(lambda checked=False, value=volume: self.voice_player.configure(volume=value))
        audio_menu.addSeparator()
        self.voice_status = audio_menu.addAction(self.voice_player.status)
        self.voice_status.setEnabled(False)
        self.voice_player.status_changed.connect(self.set_voice_status)
        self.matrix_action = self.menu.addAction('珍珠矩阵')
        self.matrix_action.setCheckable(True)
        self.matrix_action.setChecked(self.config.oracle.pearl_matrix_enabled)
        self.matrix_action.toggled.connect(self.set_pearl_matrix)
        self.orbits_action = self.menu.addAction('环绕珍珠（内圈 / 外圈）')
        self.orbits_action.setCheckable(True)
        self.orbits_action.setChecked(self.config.oracle.pearl_orbits_enabled)
        self.orbits_action.toggled.connect(self.set_pearl_orbits)
        sizes = self.menu.addMenu('大小（屏幕像素倍率）')
        group = QActionGroup(sizes)
        self.scale_actions = {}
        for factor in sorted({.5, 1., 1.5, 2., 3., 4., self.requested_scale}):
            action = sizes.addAction(f'{factor:g}×')
            action.setCheckable(True)
            action.setChecked(factor == self.requested_scale)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, value=factor: self.change_scale(value))
            self.scale_actions[factor] = action
        self.menu.addSeparator()
        self.debug_action = self.menu.addAction('打开调试窗口…', self.open_debug)
        self.reset_action = self.menu.addAction('重置到边缘', self.reset_position)
        self.menu.addSeparator()
        self.exit_action = self.menu.addAction('退出桌宠', self.quit_pet)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)

    @Slot(str)
    def set_voice_status(self, text):
        # QAction.setText 不是 Qt 槽；由窗口转发，避免 PySide 为原生 QAction 动态注册方法。
        self.voice_status.setText(text)

    def disconnect_screen(self):
        for signal in self._screen_connections:
            try:
                signal.disconnect(self.schedule_rebuild)
            except (RuntimeError, TypeError):
                pass
        self._screen_connections.clear()

    def bind_screen(self, screen):
        if self._closing:
            return
        self.disconnect_screen()
        self.screen = screen
        self.rebuild_timer.stop()
        if screen is not None:
            for name in ('availableGeometryChanged', 'geometryChanged',
                         'logicalDotsPerInchChanged', 'physicalDotsPerInchChanged'):
                signal = getattr(screen, name)
                signal.connect(self.schedule_rebuild)
                self._screen_connections.append(signal)
            handle = self.windowHandle()
            if handle is not None and isinstance(screen, QScreen):
                handle.setScreen(screen)
        self.rebuild()

    def schedule_rebuild(self, *args):
        if not self._closing:
            self.rebuild_timer.start()

    def rebuild(self, *, reset=False):
        if self._closing:
            return
        screen = self.screen
        try:
            rect = screen.availableGeometry() if screen is not None else None
            dpr = screen.devicePixelRatio() if screen is not None else 1.
        except RuntimeError:  # 热拔插期间 QScreen 可能已被 Qt 销毁。
            rect = None
        if rect is None or rect.isEmpty():
            self.drag_input.suspend()
            self._screen_valid = False
            self._signature = None
            self.sync_pause()
            self.hide()
            return
        viewport = OracleDesktopViewport(rect.x(), rect.y(), rect.width(), rect.height(), dpr,
                                          self.requested_scale)
        self._screen_valid = True
        if viewport != self._signature or reset:
            self.voice_player.stop()
            self.drag_input.suspend()
            previous = self.motion.scene if self.motion is not None and not reset else None
            # 仅工作区原点平移时移动窗口，不重置相同大小/DPI 的仿真。
            old = self._signature
            same_world = (not reset and old is not None and old.width == viewport.width
                          and old.height == viewport.height and old.dpr == viewport.dpr
                          and old.requested_scale == viewport.requested_scale)
            if same_world:
                self.motion.viewport = viewport
            else:
                settings = replace(self.config.oracle, pearl_matrix_enabled=self.matrix_action.isChecked(),
                                   pearl_orbits_enabled=self.orbits_action.isChecked())
                self.motion = OracleDesktopMotion(settings, viewport, previous)
            self.motion.scene.drag.set_enabled(self.drag_action.isChecked())
            self.voice_player.sync(self.motion.scene.drag_reactions.voice, paused=self.clock.paused)
            self._signature = viewport
            self.setGeometry(rect)
            self.clock.accumulator = 0.
            self.last_time = perf_counter()
            self._last_revision = None
            self._next_render_time = 0.
            self.update()
        self.sync_pause()
        actual = self.motion.viewport.physical_scale
        self.tray.setToolTip(f'Bell · {actual:g}× · 右键暂停、调试或退出\n{self.asset_message}')
        if self.debug_window is None:
            self.show()

    def event(self, event):
        if (event.type() == QEvent.Type.DevicePixelRatioChange
                and hasattr(self, 'rebuild_timer')):
            self.schedule_rebuild()
        return super().event(event)

    def change_scale(self, scale):
        if not isfinite(scale) or not .5 <= scale <= 4:
            raise ValueError('桌宠缩放必须为 0.5～4')
        self.requested_scale = scale
        if scale in self.scale_actions:
            self.scale_actions[scale].setChecked(True)
        self.rebuild()

    def reset_position(self):
        self.rebuild(reset=True)

    def set_pearl_matrix(self, enabled):
        if self.motion is not None:
            self.motion.scene.set_pearl_matrix(enabled)
            self._last_revision = None
            self.update()

    def set_pearl_orbits(self, enabled):
        if self.motion is not None:
            self.motion.scene.set_pearl_orbits(enabled)
            self._last_revision = None
            self.update()

    def sync_pause(self):
        self.clock.set_paused(self.pause_action.isChecked() or self.debug_window is not None
                              or not self._screen_valid)
        self.last_time = perf_counter()
        if self.clock.paused:
            self.voice_player.stop()
            self.drag_input.suspend()

    def set_drag_enabled(self, enabled):
        if self.motion is not None:
            self.motion.scene.drag.set_enabled(enabled)
        if not enabled:
            self.voice_player.stop()
            self.drag_input.suspend()
        self.update()

    def sync_drag_input(self):
        if (self._closing or self.motion is None or self.clock.paused
                or not self._screen_valid or self.debug_window is not None
                or not self.drag_action.isChecked()):
            self.drag_input.suspend()
            return
        scene = self.motion.scene
        self.drag_input.sync(scene.drag, self.drag_hit.get(self.renderer, scene, self.clock.alpha),
                             self.motion.viewport)

    def set_paused(self, paused):
        self.pause_action.blockSignals(True)
        self.pause_action.setChecked(paused)
        self.pause_action.blockSignals(False)
        self.pause_action.setText('继续' if paused else '暂停')
        self.sync_pause()
        self.update()

    def advance(self):
        now = perf_counter()
        if self.motion is not None:
            self.clock.advance(now-self.last_time, self.motion.step)
        self.last_time = now
        channel = self.motion.scene.drag_reactions.voice if self.motion is not None else None
        self.voice_player.sync(channel, paused=self.clock.paused or self._closing)
        if self.motion is None or self.clock.paused or self.debug_window is not None or not self._screen_valid:
            return
        s = self.motion.scene
        revision = (s.appearance, s.appearance.revision, s.pearl_visual_revision, s.eyes.revision,
                    s.halo_visual_revision)
        changed = (revision != self._last_revision or not s.appearance.sleeping or not s.arrived
                   or not s.pearls_settled or s.eyes.moving)
        if changed and now >= self._next_render_time:
            bounds = self.frame_bounds()
            self.update(bounds.united(self._painted_bounds).intersected(self.rect()))
            self._last_revision = revision
            interval = 1/self.RENDER_HZ
            if self._next_render_time == 0.:
                self._next_render_time = now+interval
            else:
                self._next_render_time += (int((now-self._next_render_time)/interval)+1)*interval

    def frame_bounds(self):
        if self.motion is None:
            return QRect()
        box = visual_bounds(self.motion.scene)
        scale = self.motion.viewport.scale
        return QRectF(box.x()*scale, box.y()*scale, box.width()*scale,
                      box.height()*scale).toAlignedRect().adjusted(-2, -2, 2, 2)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if self.motion is not None and self._screen_valid:
                scale = self.motion.viewport.scale
                p.scale(scale, scale)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                self.renderer.draw(p, self.motion.scene, self.clock.alpha)
        finally:
            p.end()
        self._painted_bounds = self.frame_bounds()
        self.sync_drag_input()

    def open_debug(self):
        if self.debug_window is None:
            self.voice_player.stop()
            from .debug_window import OracleDebugWindow
            settings = replace(self.config, oracle=replace(self.config.oracle,
                                pearl_matrix_enabled=self.matrix_action.isChecked(),
                                pearl_orbits_enabled=self.orbits_action.isChecked()),
                               interaction=replace(self.config.interaction,
                                                   drag_enabled=self.drag_action.isChecked()),
                               audio=AudioConfig(self.voice_player.enabled, self.voice_player.volume))
            debug = OracleDebugWindow(settings, self.config_path, load_atlas=False)
            debug.renderer = debug.canvas.renderer = OracleRenderer(
                self.renderer.atlas, self.renderer.colors, glyphs=self.renderer.glyphs)
            debug.asset_message = self.asset_message
            debug.assets.setText(self.asset_message+' · 独立调试；关闭窗口返回桌宠')
            debug.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.debug_window = debug
            debug.destroyed.connect(self.debug_closed)
            self.sync_pause()
            self.hide()
        self.debug_window.showNormal()
        self.debug_window.raise_()
        self.debug_window.activateWindow()

    def debug_closed(self, *args):
        self.debug_window = None
        if not self._closing:
            self.sync_pause()
            if self._screen_valid:
                self.show()
                self.update()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_debug()

    def cleanup(self):
        if self._closing:
            return
        self._closing = True
        self.voice_player.stop()
        self.drag_input.close()
        self.timer.stop()
        self.rebuild_timer.stop()
        self.disconnect_screen()
        app = QApplication.instance()
        for signal, slot in ((app.primaryScreenChanged, self.bind_screen), (app.aboutToQuit, self.cleanup)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        if self.debug_window is not None:
            self.debug_window.close()
        self.tray.hide()

    def quit_pet(self):
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
