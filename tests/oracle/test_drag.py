"""真实导航/机械臂、边界与 Qt 输入会话的拖拽回归。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QRect
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.input import PuppetHitMap
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.shared.geometry import Vec2


class OracleDragPhysicsTests(unittest.TestCase):
    def make_scene(self, **kwargs):
        s = OracleScene(OracleConfig(physics_backend='python', **kwargs))
        # 此组验证主物理；另有不替换次级运动的完整回归。
        s.appearance.step = lambda _: None
        s.drag.set_enabled(True)
        return s

    def test_four_sides_reach_limit_and_smooth_recovery(self):
        for side in ('top', 'right', 'bottom', 'left'):
            with self.subTest(side=side):
                s = self.make_scene(base_side=side, arm_scale=.35)
                s.set_autonomous(True)
                start = s.body.chunks[0].position
                self.assertTrue(s.drag.press(start, lambda _: True))
                s.drag.move(s.base+s.base_normal()*3000)
                for _ in range(220):
                    old = s.body.chunks[0].position
                    s.step()
                    self.assertLess((s.body.chunks[0].position-old).length(), 9.)
                    self.assertLessEqual((s.arm.joints[-1].position-s.base).length(), s.drag.reach+1e-6)
                    self.assertLess(s.arm.constraint_error, .12)
                    self.assertAlmostEqual((s.body.chunks[0].position-s.body.chunks[1].position).length(), 9.)
                    self.assertFalse(s.behavior.enabled)
                self.assertFalse(s.body_region.contains(s.body.chunks[0].position))
                self.assertLess(s.body.chunks[0].velocity.length(), .03)
                before = s.body.chunks[0].position
                s.drag.release()
                self.assertEqual(before, s.body.chunks[0].position)
                for tick in range(1600):
                    old = s.body.chunks[0].position
                    s.step()
                    self.assertLess((s.body.chunks[0].position-old).length(), 4.)
                    if not s.drag.controlling:
                        break
                self.assertLess(tick, 1599)
                self.assertTrue(s.behavior.enabled)
                self.assertTrue(s.navigator.region.contains(s.body.chunks[0].position))
                self.assertIs(s.arm.corridor, s.arm_region)
                for _ in range(20):
                    s.step()

    def test_lower_grab_corner_travel_cancel_and_regrab(self):
        s = self.make_scene()
        for target in (Vec2(900, 240), Vec2(700, 500), Vec2(80, 360), Vec2(300, 70)):
            s.drag.press(s.body.chunks[1].position, lambda _: True)
            s.drag.move(target)
            for _ in range(240):
                s.step()
                self.assertLess(s.arm.constraint_error, .2)
                self.assertTrue(s.drag.outer.contains(s.body.chunks[0].position, .001))
            s.drag.release(cancel=True)
            for _ in range(12):
                s.step()
        for _ in range(1800):
            s.step()
            if not s.drag.controlling:
                break
        self.assertFalse(s.drag.controlling)
        self.assertFalse(s.behavior.enabled)

    def test_fixed_base_and_disable_during_grab(self):
        s = self.make_scene(sliding_base=False, base_side='left')
        base = s.base
        s.drag.press(s.body.chunks[0].position, lambda _: True)
        s.drag.move(Vec2(500, 300))
        for _ in range(140):
            s.step()
        s.drag.set_enabled(False)
        self.assertFalse(s.drag.active)
        for _ in range(1500):
            s.step()
            if not s.drag.controlling:
                break
        self.assertEqual(s.base, base)
        self.assertFalse(s.drag.controlling)
        self.assertFalse(s.drag.press(s.body.chunks[0].position, lambda _: True))

    def test_secondary_motion_and_all_pearl_groups_continue(self):
        s = OracleScene(OracleConfig(pearl_matrix_enabled=True, pearl_orbits_enabled=True,
                                    pearl_satellite_count=1))
        s.set_autonomous(True)
        s.behavior.start_drift(s)
        s.drag.set_enabled(True)
        self.assertTrue(s.drag.press(s.body.chunks[0].position, lambda _: True))
        s.drag.move(Vec2(700, 350))
        before = s.appearance.revision
        for _ in range(100):
            s.step()
        self.assertGreater(s.appearance.revision, before)
        self.assertFalse(s.behavior.drift_active)
        self.assertTrue(s.drag.active)
        s.drag.release()
        for _ in range(900):
            s.step()
            if not s.drag.controlling:
                break
        self.assertFalse(s.drag.controlling)
        self.assertTrue(s.behavior.enabled)

    def test_returned_manual_pet_can_sleep_and_other_commands_do_not_steal_drag(self):
        s = OracleScene()
        s.drag.set_enabled(True)
        s.drag.press(s.head.position, lambda _: True)
        s.drag.move(Vec2(520, 260))
        for _ in range(100):
            s.step()
        self.assertFalse(s.observe_pearl())
        self.assertFalse(s.observe_matrix_pearl())
        self.assertFalse(s.set_pearl_home(Vec2(600, 70)))
        self.assertFalse(s.roam())
        s.drift()
        s.meditate()
        self.assertTrue(s.drag.active)
        s.drag.release()
        for _ in range(2300):
            s.step()
        self.assertFalse(s.drag.controlling)
        self.assertFalse(s.behavior.enabled)
        self.assertTrue(s.appearance.sleeping)
        self.assertTrue(s.arrived)


class OracleDragInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_puppet_mask_excludes_arm_pearls_and_halo(self):
        s, renderer = OracleScene(), OracleRenderer()
        cache = PuppetHitMap()
        hit = cache.get(renderer, s)
        self.assertTrue(hit.contains(s.head.position))
        self.assertTrue(hit.contains(s.body.chunks[1].position))
        for p in (s.base, s.halo.center+Vec2(45, 0), Vec2(480, 300)):
            self.assertFalse(hit.contains(p), p)
        self.assertIs(cache.get(renderer, s), hit)
        for scale in (.5, 1/1.5, 1, 2):
            region = hit.region(scale, Vec2(100, 50))
            p = s.head.position*scale+Vec2(100, 50)
            self.assertTrue(region.contains(QPoint(round(p.x), round(p.y))))

    def test_debug_press_miss_move_does_not_grab_then_press_hit(self):
        w = OracleDebugWindow(AppConfig(interaction=InteractionConfig(True)), load_atlas=False)
        w.timer.stop()
        c = w.canvas
        c.magnifier = False
        def event(kind, p, button, buttons):
            v = c.world_to_view(p)
            return QMouseEvent(kind, QPointF(v.x, v.y), QPointF(v.x, v.y), button, buttons,
                               Qt.KeyboardModifier.NoModifier)
        try:
            p = w.scene.head.position
            c.mousePressEvent(event(QEvent.Type.MouseButtonPress, Vec2(300, 100), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
            c.mouseMoveEvent(event(QEvent.Type.MouseMove, p, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
            self.assertFalse(w.scene.drag.active)
            c.mousePressEvent(event(QEvent.Type.MouseButtonPress, p, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
            self.assertTrue(w.scene.drag.active)
            w.set_paused(True)
            self.assertFalse(w.scene.drag.active)
        finally:
            w.close()

    def test_desktop_toggle_pause_resize_and_rebuild_keep_visual_window_transparent(self):
        with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            w = OracleDesktopWindow(AppConfig(), renderer=OracleRenderer())
        w.timer.stop()
        try:
            self.assertFalse(w.drag_input.isVisible())
            w.drag_action.setChecked(True)
            w.sync_drag_input()
            self.assertTrue(w.drag_input.isVisible())
            self.assertTrue(w.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            old = w.motion.scene
            old.drag.press(old.head.position, lambda _: True)
            w.set_paused(True)
            self.assertFalse(old.drag.active)
            self.assertFalse(w.drag_input.isVisible())
            w.set_paused(False)
            w.change_scale(2.)
            self.assertTrue(w.motion.scene.drag.enabled)
            self.assertFalse(w.motion.scene.drag.controlling)
            self.assertTrue(w.motion.scene.behavior.enabled)
            w.open_debug()
            self.assertTrue(w.debug_window.drag_box.isChecked())
            self.assertFalse(w.drag_input.isVisible())
        finally:
            w.close()
