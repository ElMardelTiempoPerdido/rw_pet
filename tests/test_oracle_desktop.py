"""桌面坐标/DPI、工作区恢复、窗口生命周期及穿透声明。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.oracle_behavior import Activity
from rw_creature_pet.oracle_config import OracleConfig
from rw_creature_pet.oracle_desktop import OracleDesktopMotion, OracleDesktopViewport, OracleDesktopWindow, current_anchor
from rw_creature_pet.render_oracle import OracleRenderer


class OracleDesktopMotionTests(unittest.TestCase):
    def assert_valid(self, scene):
        nav = scene.navigator
        upper, lower = scene.body.chunks
        self.assertTrue(nav.region.contains(upper.position))
        self.assertAlmostEqual((upper.position-lower.position).length(), 9)
        self.assertLessEqual((scene.base-upper.position).length(), scene.arm.maximum_reach+1e-6)
        self.assertLess((scene.base-nav.rail.sample(nav.base.s)[0]).length(), 1e-7)
        self.assertLess(scene.arm.constraint_error, .2)
        self.assertTrue(all(scene.arm_region.segment_safe(a.position, b.position)
                            for a, b in zip(scene.arm.joints, scene.arm.joints[1:])))
        self.assertTrue(scene.pearl.region.contains(scene.pearl.position))
        self.assertTrue(scene.pearl.region.contains(scene.pearl.home))

    def test_physical_pixel_scale_and_global_coordinates(self):
        for dpr in (1., 1.25, 1.5, 2.):
            for scale in (.5, 1., 1.5, 2., 4.):
                for x, y, w, h in ((0, 0, 1920, 1040), (-1920, 40, 1280, 680), (40, -1080, 700, 500)):
                    v = OracleDesktopViewport(x, y, w, h, dpr, scale)
                    point = Vec2(84, 60)
                    self.assertLess((v.to_world(v.to_global(point))-point).length(), 1e-8)
                    self.assertAlmostEqual(v.world_size.x*v.scale, w)
                    self.assertAlmostEqual(v.world_size.y*v.scale, h)
                    self.assertAlmostEqual(v.scale*dpr, v.physical_scale)
                    if scale == 1:
                        self.assertEqual(v.physical_scale, 1.)
        for v in ((0, 0, 1920, 1040, 1, 0), (0, 0, 0, 600, 1, 1), (0, 0, 800, 600, 0, 1)):
            with self.assertRaises(ValueError):
                OracleDesktopViewport(*v)

    def test_rebuild_at_each_side_keeps_anchor_pearl_identity_and_clears_old_paths(self):
        for side in ('top', 'right', 'bottom', 'left'):
            old = OracleDesktopMotion(OracleConfig(base_side=side), OracleDesktopViewport(0, 0, 1920, 1040)).scene
            old.behavior.completed_cycles = 3
            old.pearl.glyph_id = 9
            old.observe_pearl('recall')
            old.set_autonomous(True)
            old.appearance.step = lambda scene: None
            for _ in range(95):
                old.step()
            original_side, fraction = current_anchor(old)
            self.assertFalse(old.pearl.settled)
            for viewport in (OracleDesktopViewport(-1280, 40, 1280, 680, 1.5),
                             OracleDesktopViewport(0, 0, 300, 250, 1., 4.),
                             OracleDesktopViewport(0, -1000, 1080, 1920, 2.)):
                new = OracleDesktopMotion(OracleConfig(), viewport, old).scene
                self.assertEqual(new.anchor.side, original_side)
                self.assertAlmostEqual(new.anchor.fraction, fraction)
                self.assertEqual(new.pearl.glyph_id, 9)
                self.assertEqual(new.behavior.completed_cycles, 3)
                self.assertEqual(new.eyes.random.getstate(), old.eyes.random.getstate())
                self.assertEqual(new.eyes.openness, 0.)
                self.assertTrue(new.behavior.enabled)
                self.assertEqual(new.behavior.state, Activity.IDLE)
                self.assertEqual(new.pearl.position, new.pearl.home)
                self.assertEqual(new.navigator.route.length, 0)
                for p in (*new.body.chunks, new.head, *new.arm.joints):
                    self.assertEqual(p.position, p.previous_position)
                self.assert_valid(new)
                for _ in range(15):
                    new.step()
                    self.assert_valid(new)

    def test_desktop_sized_laps_and_resize_during_movement(self):
        for width, height, dpr in ((1920, 1040, 1.), (1280, 680, 1.5), (1080, 1920, 1.)):
            motion = OracleDesktopMotion(OracleConfig(sliding_base=False),
                                         OracleDesktopViewport(0, 0, width, height, dpr))
            scene = motion.scene
            self.assertTrue(scene.sliding_base)
            self.assertTrue(scene.behavior.enabled)
            scene.appearance.step = lambda scene: None  # 独立验证桌面尺寸下的导航。
            scene.start_lap()
            visited = set()
            for tick in range(12000):
                motion.step()
                visited.add(current_anchor(scene)[0].value)
                if tick % 20 == 0:
                    self.assert_valid(scene)
                if scene.arrived:
                    break
            self.assertLess(tick, 11999)
            self.assertEqual(visited, {'top', 'right', 'bottom', 'left'})
            scene.set_target(scene.navigator.planner.corners[2])
            for _ in range(90):
                motion.step()
            motion = OracleDesktopMotion(OracleConfig(), OracleDesktopViewport(40, 0, 640, 480, 1, 4), scene)
            self.assert_valid(motion.scene)
            self.assertFalse(motion.scene.behavior.enabled)


class FakeScreen(QObject):
    availableGeometryChanged = Signal(QRect)
    geometryChanged = Signal(QRect)
    logicalDotsPerInchChanged = Signal(float)
    physicalDotsPerInchChanged = Signal(float)

    def __init__(self, rect, dpr=1.):
        super().__init__()
        self.rect, self.dpr = rect, dpr

    def availableGeometry(self):
        return self.rect

    def devicePixelRatio(self):
        return self.dpr


class OracleDesktopWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        with patch('rw_creature_pet.oracle_desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            self.window = OracleDesktopWindow(AppConfig(), renderer=OracleRenderer())
        self.window.timer.stop()
        self.screen = FakeScreen(QRect(-1280, 40, 1280, 680), 1.5)
        self.window.bind_screen(self.screen)

    def tearDown(self):
        self.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_overlay_flags_transparent_canvas_and_dpi(self):
        w = self.window
        flags = w.windowFlags()
        for flag in (Qt.WindowType.FramelessWindowHint, Qt.WindowType.WindowStaysOnTopHint,
                     Qt.WindowType.WindowTransparentForInput, Qt.WindowType.WindowDoesNotAcceptFocus):
            self.assertTrue(flags & flag)
        for attr in (Qt.WidgetAttribute.WA_TranslucentBackground, Qt.WidgetAttribute.WA_ShowWithoutActivating,
                     Qt.WidgetAttribute.WA_TransparentForMouseEvents):
            self.assertTrue(w.testAttribute(attr))
        self.assertEqual(w.geometry(), self.screen.rect)
        self.assertAlmostEqual(w.motion.viewport.scale, 1/1.5)
        self.assertTrue(w.motion.scene.behavior.enabled)
        w.set_paused(True)
        image = w.grab().toImage()
        self.assertEqual(image.pixelColor(image.width()//2, image.height()//2).alpha(), 0)

    def test_workarea_signals_coalesce_origin_only_preserves_scene_and_old_screen_disconnects(self):
        w = self.window
        scene = w.motion.scene
        self.screen.rect.translate(40, 0)
        self.screen.availableGeometryChanged.emit(self.screen.rect)
        self.screen.geometryChanged.emit(self.screen.rect)
        QTest.qWait(140)
        self.assertIs(w.motion.scene, scene)
        self.assertEqual(w.geometry(), self.screen.rect)
        w.set_paused(True)
        self.screen.rect = QRect(0, 0, 800, 560)
        self.screen.dpr = 2.
        self.screen.logicalDotsPerInchChanged.emit(192.)
        self.screen.availableGeometryChanged.emit(self.screen.rect)
        QTest.qWait(140)
        self.assertIsNot(w.motion.scene, scene)
        self.assertTrue(w.clock.paused)
        self.assertTrue(w.pause_action.isChecked())
        self.assertEqual(w.motion.viewport.dpr, 2.)
        new_screen = FakeScreen(QRect(0, -1000, 900, 1000), 1.)
        w.bind_screen(new_screen)
        w.rebuild_timer.stop()
        self.screen.availableGeometryChanged.emit(QRect())
        self.assertFalse(w.rebuild_timer.isActive())
        w.change_scale(4.)
        self.assertTrue(w.scale_actions[4.].isChecked())
        self.assertTrue(w.clock.paused)
        self.assertAlmostEqual(w.motion.viewport.world_size.x*w.motion.viewport.scale, 900)

    def test_empty_or_missing_screen_suspends_then_recovers(self):
        w = self.window
        w.bind_screen(None)
        self.assertTrue(w.clock.paused)
        self.assertFalse(w.isVisible())
        w.bind_screen(self.screen)
        self.assertFalse(w.clock.paused)
        self.assertTrue(w.isVisible())
        self.screen.rect = QRect()
        w.rebuild()
        self.assertTrue(w.clock.paused)
        self.assertFalse(w.isVisible())
        self.screen.rect = QRect(-800, 20, 800, 580)
        w.rebuild()
        self.assertFalse(w.clock.paused)
        self.assertEqual(w.geometry(), self.screen.rect)

    def test_pause_debug_return_and_cleanup(self):
        w = self.window
        w.pause_action.trigger()
        self.assertTrue(w.clock.paused)
        tick = w.motion.scene.ticks
        w.clock.advance(2, w.motion.step)
        self.assertEqual(w.motion.scene.ticks, tick)
        for was_paused in (True, False):
            w.set_paused(was_paused)
            scene = w.motion.scene
            w.open_debug()
            debug = w.debug_window
            debug.timer.stop()
            self.assertTrue(w.clock.paused)
            self.assertFalse(w.isVisible())
            self.assertIsNot(debug.scene, scene)
            self.assertIs(debug.renderer.glyphs, w.renderer.glyphs)
            w.open_debug()
            self.assertIs(w.debug_window, debug)
            debug.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
            self.assertIsNone(w.debug_window)
            self.assertIs(w.motion.scene, scene)
            self.assertEqual(w.clock.paused, was_paused)
            self.assertTrue(w.isVisible())
        w.open_debug()
        debug = w.debug_window
        w.close()
        self.assertFalse(w.timer.isActive())
        self.assertFalse(w.rebuild_timer.isActive())
        self.assertFalse(w.tray.isVisible())
        self.assertFalse(debug.timer.isActive())

    def test_idle_refresh_is_suppressed_and_eyes_or_pearl_wake_it(self):
        w = self.window
        s = w.motion.scene
        s.set_autonomous(False)
        for _ in range(700):
            s.step()
        self.assertTrue(s.appearance.sleeping)
        w.advance()
        w._next_render_time = 0.
        with patch.object(w, 'update') as update:
            w.advance()
            self.assertEqual(update.call_count, 0)
            s.eyes.OPEN_PROBABILITY = 1.
            s.eyes.begin_observation()
            s.step()
            w.advance()
            self.assertEqual(update.call_count, 1)
            self.assertTrue(s.appearance.sleeping)
            for _ in range(12):
                s.step()
                w._next_render_time = 0.
                w.advance()
            update.reset_mock()
            w._next_render_time = 0.
            w.advance()
            self.assertEqual(update.call_count, 0)
            s.set_pearl_home(s.pearl.home+Vec2(60, 0))
            w.advance()
            self.assertEqual(update.call_count, 1)
