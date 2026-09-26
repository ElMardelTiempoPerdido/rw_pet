"""局部绕珠弧、冥想停稳/休眠、失重共存与调试接管。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.navigation import EdgePlanner, normalized
from rw_creature_pet.oracle.scene import OracleScene, dot
from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.shared.timing import FixedStepper


class OrbitMeditationTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(OracleConfig(**settings))
        scene.appearance.step = lambda scene: None
        return scene

    def until(self, scene, predicate, limit=3000):
        for tick in range(limit):
            before = scene.body.direction
            scene.step()
            self.assertGreater(dot(before, scene.body.direction), .998)
            self.assertLess(scene.arm.constraint_error, .025)
            if predicate():
                return tick
        self.fail(f'未完成：{scene.behavior.state}, arrived={scene.arrived}')

    def test_arc_keeps_radius_tangent_and_entire_curve_inside_box(self):
        center, start = Vec2(150, 150), Vec2(200, 150)
        for box in (Bounds(80, 80, 230, 230), Bounds(80, 139, 230, 161)):
            route = EdgePlanner.local_arc(start, center, box)
            self.assertIsNotNone(route)
            for curve in route.curves:
                for i in range(101):
                    point = curve.sample(i/100)
                    self.assertTrue(box.contains(point))
                    self.assertAlmostEqual((point-center).length(), 50., delta=.02)
            for a, b in zip(route.curves, route.curves[1:]):
                self.assertEqual(a.d, b.a)
                self.assertGreater(dot(normalized(a.d-a.c), normalized(b.b-b.a)), .999999)
        # 两个方向都会立即出界时，不能把圆弧压成沿墙抖动的假圆周。
        self.assertIsNone(EdgePlanner.local_arc(Vec2(0, 0), Vec2(-50, 0), Bounds(0, -20, 100, 20)))

    def test_orbit_cycle_on_four_edges_and_small_corners_keeps_pearl_still(self):
        for small in (False, True):
            for side in ('top', 'right', 'bottom', 'left'):
                settings = dict(base_side=side)
                if small:
                    settings.update(world_width=640, world_height=480, arm_scale=.75, base_fraction=0.)
                scene = self.scene(**settings)
                scene.observe_pearl('orbit')
                eye_state = scene.eyes.random.getstate()
                visited, orbit_center = set(), None
                def complete():
                    nonlocal orbit_center
                    visited.add(scene.behavior.state)
                    self.assertEqual(scene.eyes.random.getstate(), eye_state)
                    if scene.behavior.state == Activity.ORBIT:
                        orbit_center = orbit_center or scene.pearl.position
                        self.assertEqual(scene.pearl.position, orbit_center)
                        self.assertEqual(scene.look_target, orbit_center)
                        self.assertGreater((scene.body.chunks[0].position-orbit_center).length(), 30.)
                        self.assertTrue(all(c.certified_safe(scene.navigator.region) for c in scene.navigator.route.curves))
                    return scene.behavior.completed_cycles == 1
                self.until(scene, complete)
                self.assertTrue({Activity.APPROACH, Activity.ORBIT, Activity.OBSERVE, Activity.RETURN} <= visited)
                self.assertEqual(scene.behavior.state, Activity.IDLE)
                self.assertTrue(scene.pearl.settled and scene.arrived)

    def test_no_arc_and_fixed_base_fall_back_to_observation_without_replanning(self):
        for sliding in (True, False):
            scene = self.scene(sliding_base=sliding)
            scene.observe_pearl('orbit')
            visited = set()
            with patch.object(EdgePlanner, 'local_arc', return_value=None) as plan:
                def complete():
                    visited.add(scene.behavior.state)
                    return scene.behavior.completed_cycles == 1
                self.until(scene, complete)
                self.assertLessEqual(plan.call_count, 6)  # 五个入场候选，抵达后一次；不逐帧重算。
            self.assertNotIn(Activity.ORBIT, visited)
            self.assertIn(Activity.OBSERVE, visited)

    def test_drift_orbit_and_meditation_keep_episode_then_finish_after_deadline(self):
        scene = self.scene()
        scene.drift()
        for _ in range(250):
            scene.step()
        duration, ticks = scene.behavior.drift_duration, scene.behavior.drift_ticks
        scene.observe_pearl('orbit')
        visited = set()
        def complete():
            visited.add(scene.behavior.state)
            self.assertTrue(scene.behavior.drift_active)
            self.assertEqual(scene.behavior.drift_duration, duration)
            self.assertGreaterEqual(scene.pose.weightlessness, .999)
            return scene.behavior.completed_cycles == 1
        self.until(scene, complete)
        self.assertIn(Activity.ORBIT, visited)
        self.assertGreater(scene.behavior.drift_ticks, ticks)
        scene.meditate()
        scene.behavior.duration = 180
        scene.behavior.drift_duration = scene.behavior.drift_ticks+1
        self.until(scene, lambda: scene.behavior.state == Activity.DRIFT)
        self.assertGreaterEqual(scene.behavior.meditation_ticks, 180)
        self.until(scene, lambda: not scene.behavior.drift_active)
        self.assertEqual(scene.pose.gravity_scale, 1.)
        self.assertTrue(scene.arrived)

    def test_meditation_timer_waits_for_rest_pause_and_manual_takeover(self):
        scene = self.scene()
        scene.set_target(scene.target+Vec2(150, 0))
        for _ in range(60):
            scene.step()
        scene.meditate()
        scene.behavior.duration = 160
        for _ in range(8):
            scene.step()
        self.assertEqual(scene.behavior.meditation_ticks, 0)
        clock = FixedStepper(40)
        clock.set_paused(True)
        snapshot = (scene.ticks, scene.behavior.state_ticks, scene.behavior.meditation_ticks)
        clock.advance(4, scene.step)
        self.assertEqual(snapshot, (scene.ticks, scene.behavior.state_ticks, scene.behavior.meditation_ticks))
        self.until(scene, lambda: scene.behavior.meditation_ticks >= 20)
        position = scene.body.chunks[0].position
        scene.set_target(position+Vec2(80, 0))
        self.assertFalse(scene.behavior.active)
        self.assertEqual(scene.body.chunks[0].position, position)
        self.until(scene, lambda: scene.arrived)
        scene.reset()
        self.assertEqual(scene.behavior.meditation_ticks, 0)

    def test_autonomous_meditation_and_observation_variants_are_selectable(self):
        scene = self.scene(cross_edge_probability=0., antigravity_probability=0.)
        scene.set_autonomous(True)
        with patch.object(scene.behavior, 'choose_activity', return_value=Activity.MEDITATE):
            self.until(scene, lambda: scene.behavior.state == Activity.MEDITATE)
        self.assertTrue(scene.behavior.enabled)
        scene.behavior.duration = 30
        self.until(scene, lambda: scene.behavior.state == Activity.IDLE)
        self.assertTrue(scene.behavior.enabled)
        modes = set()
        for _ in range(100):
            scene.behavior.notice(scene)
            modes.add(scene.behavior.mode)
        self.assertEqual(modes, {'approach', 'recall', 'orbit'})

    def test_resize_cancels_new_activities_and_preserves_random_streams(self):
        for activity in ('orbit', 'meditate'):
            scene = self.scene()
            if activity == 'orbit':
                scene.observe_pearl('orbit')
                self.until(scene, lambda: scene.behavior.state == Activity.ORBIT)
            else:
                scene.meditate()
            scene.behavior.enabled = True
            streams = [r.getstate() for r in (scene.behavior.random, scene.behavior.pace_random, scene.behavior.detail_random)]
            resized = OracleDesktopMotion(OracleConfig(), OracleDesktopViewport(0, 0, 1280, 680, 1.), scene).scene
            self.assertEqual(resized.behavior.state, Activity.IDLE)
            # set_enabled 开始一个新的停留时长；细节与速度随机流不重置。
            self.assertEqual(resized.behavior.pace_random.getstate(), streams[1])
            self.assertEqual(resized.behavior.detail_random.getstate(), streams[2])
            self.assertTrue(resized.behavior.enabled)
            self.assertTrue(resized.navigator.region.contains(resized.target))


class MeditationSleepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_real_soft_parts_sleep_during_meditation_and_wake_on_command(self):
        for drift in (False, True):
            scene = OracleScene()
            if drift:
                scene.drift()
                for _ in range(350):
                    scene.step()
            scene.meditate()
            scene.behavior.duration = 2400
            for tick in range(1400):
                scene.step()
                if scene.appearance.sleeping and scene.arrived and scene.pose.settled and not scene.eyes.moving:
                    break
            self.assertLess(tick, 1399)
            before = (scene.appearance.revision, scene.pearl.revision, scene.eyes.revision)
            positions = [p.position for p in scene.appearance.points]
            for _ in range(200):
                scene.step()
            self.assertEqual(scene.behavior.state, Activity.MEDITATE)
            self.assertEqual(before, (scene.appearance.revision, scene.pearl.revision, scene.eyes.revision))
            self.assertEqual(positions, [p.position for p in scene.appearance.points])
            scene.set_target(scene.target+Vec2(60, 0))
            for _ in range(10):
                scene.step()
            self.assertFalse(scene.appearance.sleeping)

    def test_debug_controls_and_resting_meditation_do_not_repaint(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            window.orbit_pearl_button.click()
            self.assertEqual(window.scene.behavior.mode, 'orbit')
            window.meditate_button.click()
            self.assertEqual(window.scene.behavior.state, Activity.MEDITATE)
            window.scene.behavior.duration = 2400
            for _ in range(850):
                window.scene.step()
            self.assertTrue(window.scene.appearance.sleeping)
            window.refresh()
            with patch.object(window.canvas, 'update') as repaint:
                for _ in range(120):
                    window.scene.step()
                    window._next_render_time = 0.
                    window.refresh(force=False)
                repaint.assert_not_called()
            window.sliding_box.setChecked(False)
            self.assertFalse(window.orbit_pearl_button.isEnabled())
            self.assertTrue(window.meditate_button.isEnabled())
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
