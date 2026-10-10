"""窗口观察的头眼优先级、恢复、桌面轮询与 DPI 映射。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from types import SimpleNamespace
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.interaction.windows import DesktopWindow, ForegroundWindowTracker
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow, OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Bounds, Vec2
from tests.oracle.test_desktop import FakeScreen


def scene():
    model = OracleScene(OracleConfig(hide_cords=True, halo_enabled=False, physics_backend='python'))
    model.set_autonomous(True)
    model.behavior.step = lambda scene: None  # 测试窗口事件，不等待随机自主活动。
    model.appearance.step = lambda scene: None
    model.window_reaction.attention.probability = 1.
    model.window_reaction.attention.open_probability = 1.
    return model


class WindowReactionTests(unittest.TestCase):
    def test_window_attention_is_independent_of_movement_and_behavior_loop(self):
        s = scene()
        s.set_autonomous_movement(False)
        s.set_autonomous(False)  # 即使调试完全接管行为循环，窗口观察也仅服从拖拽/桌面暂停。
        r = s.window_reaction
        r.notice(s, (10, 1), s.body.chunks[0].position+Vec2(200, 0), changed=True)
        for _ in range(20):
            s.step()
        self.assertTrue(r.attention.active)
        self.assertGreater(s.look_direction.x, .9)
        self.assertEqual(s.eyes.openness, 1.)
        self.assertFalse(s.behavior.movement_enabled)

    def test_finished_observation_can_return_to_low_cost_sleep(self):
        s = OracleScene(OracleConfig(hide_cords=True, halo_enabled=False, pearl_fixed_count=0,
                                    physics_backend='python'))
        s.set_autonomous(True)
        s.behavior.step = lambda scene: None
        r = s.window_reaction
        r.attention.probability = 1.
        for _ in range(350):
            s.step()
        r.notice(s, (10, 1), Vec2(900, 500), changed=True)
        r.attention.remaining = .25
        for _ in range(1000):
            s.step()
        self.assertFalse(r.busy)
        self.assertTrue(s.appearance.sleeping)
        revisions = (s.appearance.revision, s.eyes.revision)
        for _ in range(100):
            r.notice(s, (10, 1), Vec2(900, 500), changed=False)
            s.step()
        self.assertEqual((s.appearance.revision, s.eyes.revision), revisions)

    def test_watch_moves_then_returns_to_saved_angle_and_restores_eye_intention(self):
        s = scene()
        s.look_direction = Vec2(.2, -.15)
        s.look_target = s.body.chunks[0].position+Vec2(20, -15)
        initial_look, baseline_eye_rng = s.look_direction, s.eyes.random.getstate()
        r = s.window_reaction
        r.notice(s, (10, 1), s.body.chunks[0].position+Vec2(200, 0), changed=True)
        r.attention.remaining = 1.
        for _ in range(15):
            s.step()
        self.assertGreater(s.look_direction.x, .8)
        self.assertEqual(s.eyes.openness, 1.)
        s.eyes.end_observation()  # 基础 AI 改变意愿不能覆盖临时观察。
        r.notice(s, (10, 1), s.body.chunks[0].position+Vec2(-200, 0), changed=False)
        for _ in range(20):
            s.step()
        self.assertLess(s.look_direction.x, -.8)
        self.assertEqual(s.eyes.openness, 1.)
        for _ in range(100):
            s.step()
            if not r.busy:
                break
        self.assertFalse(r.busy)
        self.assertLess((s.look_direction-initial_look).length(), .001)
        self.assertIsNone(s.eyes.attention_target)
        self.assertEqual(s.eyes.openness, 0.)
        self.assertEqual(s.eyes.random.getstate(), baseline_eye_rng)

    def test_repeated_switches_keep_original_return_angle_and_underlying_target(self):
        s, r = scene(), None
        r = s.window_reaction
        initial, ordinary = Vec2(.1, .2), Vec2(800, 500)
        s.look_direction, s.look_target = initial, ordinary
        s.eyes.begin_reaction(True)
        r.attention.open_probability = 0.
        r.notice(s, (10, 1), Vec2(0, 0), changed=True)
        for _ in range(12):
            s.step()
        self.assertEqual(s.eyes.openness, 0.)
        self.assertEqual(s.eyes.target, 1.)
        r.notice(s, (11, 1), Vec2(900, 500), changed=True)
        self.assertEqual(r.saved_look, initial)
        self.assertEqual(s.look_target, ordinary)
        r.notice(s, None, None, changed=True)
        self.assertTrue(r.returning)
        for _ in range(12):
            s.step()
        self.assertEqual(s.eyes.openness, 1., '窗口事件结束后恢复基础 AI 的睁眼意愿')

    def test_drag_takes_priority_and_rebuild_discards_event_but_preserves_rng(self):
        s = scene()
        r = s.window_reaction
        r.notice(s, (10, 1), Vec2(900, 500), changed=True)
        s.step()
        s.drag.set_enabled(True)
        s.drag.press(s.head.position, lambda _: True)
        s.step()
        self.assertFalse(r.busy)
        self.assertIsNone(s.eyes.attention_target)
        self.assertEqual(s.look_target, s.drag.controller.pointer)
        rng = r.attention.random.getstate()
        new = OracleDesktopMotion(s.config, OracleDesktopViewport(-100, 30, 1280, 720, 1.5), s).scene
        self.assertFalse(new.window_reaction.busy)
        self.assertEqual(new.window_reaction.attention.random.getstate(), rng)
        self.assertIsNone(new.eyes.attention_target)


class DesktopWindowReactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_apply_movement_setting_keeps_reading_and_persists_policy_independently(self):
        store = Mock()
        with patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            w = OracleDesktopWindow(AppConfig(), renderer=OracleRenderer(), config_store=store)
        try:
            w.timer.stop()
            s = w.motion.scene
            s.appearance.step = lambda _: None
            s.observe_pearl('recall')
            s.set_autonomous(True)
            for _ in range(1800):
                s.step()
                if s.behavior.state == Activity.OBSERVE:
                    break
            self.assertEqual(s.behavior.state, Activity.OBSERVE)
            pearl, ticks, duration = s.observed_pearl, s.behavior.state_ticks, s.behavior.duration
            config = replace(w.current_settings(), desktop=replace(w.config.desktop, autonomous=False))
            assets = OracleAssets(w.renderer, '', {}, '')
            w.apply_settings(config, assets)
            self.assertIs(w.motion.scene, s)
            self.assertIs(s.observed_pearl, pearl)
            self.assertEqual((s.behavior.state_ticks, s.behavior.duration), (ticks, duration))
            self.assertFalse(w.current_settings().desktop.autonomous)
            self.assertTrue(s.behavior.enabled)
            self.assertFalse(store.save.call_args.args[0].desktop.autonomous)
            s.drag.set_enabled(True)
            s.drag.press(s.head.position, lambda _: True)
            self.assertTrue(s.drag.resume_autonomy)
            self.assertFalse(w.current_settings().desktop.autonomous, '暂停整个循环不能改变已保存的移动许可')
            # 工作区变化中的重建也不能误把循环开启等同于允许移动。
            w.bind_screen(FakeScreen(QRect(0, 0, 1280, 720)))
            self.assertTrue(w.motion.scene.behavior.enabled)
            self.assertFalse(w.motion.scene.behavior.movement_enabled)
            self.assertFalse(w.current_settings().desktop.autonomous)
        finally:
            w.close()

    def test_poll_tracks_native_physical_coordinates_and_drops_paused_switches(self):
        config = AppConfig()
        config = replace(config, desktop=replace(config.desktop, autonomous=False))
        with patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            w = OracleDesktopWindow(config, renderer=OracleRenderer())
        try:
            w.timer.stop()
            screen = FakeScreen(QRect(-1280, 40, 1280, 680), 1.5)
            w.bind_screen(screen)
            work = Bounds(-1920, 60, 0, 1080)
            source = SimpleNamespace(read=Mock(), work_area=Mock(return_value=work))
            w.window_tracker = ForegroundWindowTracker(source)
            s = w.motion.scene
            self.assertTrue(s.behavior.enabled)
            self.assertFalse(s.behavior.movement_enabled)
            self.assertFalse(w.current_settings().desktop.autonomous)
            r = s.window_reaction
            r.attention.probability = 1.
            source.read.return_value = DesktopWindow(10, 99999, Bounds(-1500, 180, -900, 580),
                                                     Bounds(-1920, 0, 0, 1080))
            now = 1e10
            w.poll_window_attention(now)
            self.assertFalse(r.busy)
            source.read.return_value = DesktopWindow(11, 99999, source.read.return_value.bounds,
                                                     source.read.return_value.screen)
            w.poll_window_attention(now+.05)
            self.assertFalse(r.busy, '轮询有固定上限，不随 60 Hz 绘制频率重复读取')
            w.poll_window_attention(now+.2)
            self.assertTrue(r.attention.active)
            self.assertEqual(r.attention.target, Vec2(720, 320))
            state = r.attention.random.getstate()
            source.read.return_value = DesktopWindow(11, 99999, Bounds(-1928, -8, 8, 1088),
                                                     Bounds(-1920, 0, 0, 1080))
            w.poll_window_attention(now+.4)
            self.assertEqual(r.attention.target, Vec2(960, 480), '全屏取完整屏幕中心，扣除工作区偏移')
            self.assertEqual(r.attention.random.getstate(), state)
            w.set_paused(True)
            self.assertFalse(r.busy)
            source.read.return_value = DesktopWindow(12, 99999, source.read.return_value.bounds,
                                                     source.read.return_value.screen)
            w.poll_window_attention(now+.6)
            w.set_paused(False)
            w.poll_window_attention(now+.8)
            self.assertFalse(r.busy)
            source.read.return_value = DesktopWindow(13, 99999, source.read.return_value.bounds,
                                                     source.read.return_value.screen)
            w.poll_window_attention(now+1.)
            self.assertTrue(r.busy)
        finally:
            w.close()

    def test_native_mapping_does_not_double_apply_system_dpi_or_pet_scale(self):
        for dpr in (1., 1.25, 1.5, 2.):
            for scale in (1., 1.5, 2.):
                viewport = OracleDesktopViewport(-1920, 40, 1920/dpr, 1040/dpr, dpr, scale)
                work = Bounds(-1920, 40, 0, 1080)
                self.assertEqual(viewport.physical_to_world(Vec2(-960, 520), work),
                                 Vec2(960/scale, 480/scale))


if __name__ == '__main__':
    unittest.main()
