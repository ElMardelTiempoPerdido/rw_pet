"""观察开眼的事件概率、生命周期、渲染隔离与静止刷新。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.oracle import OracleScene
from rw_creature_pet.oracle_behavior import Activity
from rw_creature_pet.oracle_config import OracleConfig
from rw_creature_pet.oracle_desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle_eyes import OracleEyes
from rw_creature_pet.oracle_window import OracleDebugWindow
from rw_creature_pet.render_oracle import OracleRenderer
from rw_creature_pet.scene import FixedStepper


class OracleEyesTests(unittest.TestCase):
    def scene(self):
        scene = OracleScene()
        scene.appearance.step = lambda scene: None
        return scene

    def test_closed_default_rare_once_per_episode_and_smooth_endpoints(self):
        eyes = OracleEyes()
        self.assertEqual(eyes.openness, 0.)
        with patch.object(eyes.random, 'random', return_value=.05) as draw:
            eyes.begin_observation()
            for tick in range(eyes.OPEN_TICKS):
                eyes.begin_observation()  # 跟踪同一目标不重新抽签。
                eyes.step()
                self.assertAlmostEqual(eyes.openness, (tick+1)/eyes.OPEN_TICKS)
            self.assertEqual(draw.call_count, 1)
            self.assertEqual(eyes.openness, 1.)
            eyes.end_observation()
            for _ in range(eyes.CLOSE_TICKS+1):
                eyes.step()
            self.assertFalse(eyes.moving)
            self.assertEqual(eyes.openness, 0.)
        count = 0
        for _ in range(10000):
            eyes.begin_observation(restart=True)
            count += eyes.target
        self.assertTrue(800 < count < 1200, count)

    def test_both_pearl_cycles_hold_one_decision_and_leave_navigation_unchanged(self):
        for mode in ('approach', 'recall'):
            closed, opened = self.scene(), self.scene()
            closed.eyes.OPEN_PROBABILITY = 0.
            opened.eyes.OPEN_PROBABILITY = 1.
            for scene in (closed, opened):
                scene.observe_pearl(mode)
            state = opened.eyes.random.getstate()
            visited = set()
            for _ in range(5000):
                closed.step()
                opened.step()
                phase = opened.behavior.state
                visited.add(phase)
                self.assertEqual(opened.eyes.random.getstate(), state)
                self.assertEqual(closed.eyes.openness, 0.)
                self.assertEqual(closed.body.chunks[0].position, opened.body.chunks[0].position)
                self.assertEqual(closed.pearl.position, opened.pearl.position)
                self.assertEqual(closed.behavior.random.getstate(), opened.behavior.random.getstate())
                if phase == Activity.OBSERVE:
                    self.assertEqual(opened.eyes.openness, 1.)
                if phase == Activity.RETURN:
                    self.assertEqual(opened.eyes.target, 0.)
                if opened.behavior.completed_cycles:
                    break
            self.assertEqual(opened.behavior.completed_cycles, 1)
            self.assertIn(Activity.OBSERVE, visited)
            self.assertEqual(opened.eyes.openness, 0.)

    def test_manual_gaze_cancel_pause_and_reset(self):
        scene = self.scene()
        scene.eyes.OPEN_PROBABILITY = 1.
        scene.set_look_target(Vec2(600, 40))
        random_state = scene.eyes.random.getstate()
        for i in range(20):
            scene.set_look_target(Vec2(600+i, 40))
            scene.step()
        self.assertEqual(scene.eyes.random.getstate(), random_state)
        self.assertEqual(scene.eyes.openness, 1.)
        scene.set_look_target(None)
        clock = FixedStepper(40)
        clock.set_paused(True)
        clock.advance(2., scene.step)
        self.assertEqual(scene.eyes.openness, 1.)
        clock.single_step(scene.step)
        self.assertLess(scene.eyes.openness, 1.)
        for cancel in (lambda: scene.set_autonomous(False), lambda: scene.set_target(Vec2(600, 70))):
            scene.observe_pearl('recall')
            cancel()
            self.assertFalse(scene.eyes.observing)
            self.assertEqual(scene.eyes.target, 0.)
        scene.reset()
        self.assertEqual(scene.eyes.openness, 0.)
        self.assertEqual(scene.eyes.random.getstate(), OracleEyes().random.getstate())

    def test_desktop_resize_keeps_random_stream_but_resets_observation(self):
        scene = self.scene()
        scene.observe_pearl('recall')
        before = scene.eyes.random.getstate()
        resized = OracleDesktopMotion(OracleConfig(), OracleDesktopViewport(0, 0, 1280, 680, 1.5), scene).scene
        self.assertEqual(resized.eyes.random.getstate(), before)
        self.assertEqual(resized.eyes.openness, 0.)
        self.assertFalse(resized.eyes.observing)


class OracleEyesRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def render(self, renderer, scene, alpha=1., direct=False):
        image = QImage(480, 400, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            painter.scale(4, 4)
            painter.translate(60-scene.body.chunks[0].position.x, 0)
            if direct:
                renderer.draw_geometry(painter, scene, alpha)
            else:
                renderer.draw(painter, scene, alpha)
        finally:
            painter.end()
        return bytes(image.constBits())

    def test_eye_animation_only_updates_head_and_rendering_is_read_only(self):
        scene, renderer = OracleScene(), OracleRenderer()
        for _ in range(650):
            scene.step()
        self.assertTrue(scene.appearance.sleeping)
        before = self.render(renderer, scene)
        frame, revision = renderer._frame, scene.appearance.revision
        scene.eyes.OPEN_PROBABILITY = 1.
        scene.eyes.begin_observation()
        random_state = scene.eyes.random.getstate()
        for _ in range(12):
            scene.step()
            for alpha in (0., .5, 1.):
                cached = self.render(renderer, scene, alpha)
                self.assertEqual(cached, self.render(renderer, scene, alpha, direct=True))
                self.assertIs(renderer._frame, frame)
        self.assertNotEqual(before, self.render(renderer, scene))
        self.assertEqual(scene.appearance.revision, revision)
        self.assertEqual(scene.eyes.random.getstate(), random_state)
        self.assertEqual(scene.eyes.openness, 1.)

    def test_sleeping_debug_window_refreshes_eyes_then_stops(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            for _ in range(650):
                window.scene.step()
            window.refresh()
            window.scene.eyes.OPEN_PROBABILITY = 1.
            window.scene.eyes.begin_observation()
            for _ in range(12):
                window.scene.step()
                window._next_render_time = 0.
                window.refresh(force=False)
            with patch.object(window.canvas, 'update') as update:
                window._next_render_time = 0.
                window.refresh(force=False)
                update.assert_not_called()
                window.scene.eyes.end_observation()
                window.scene.step()
                window.refresh(force=False)
                update.assert_called_once()
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
