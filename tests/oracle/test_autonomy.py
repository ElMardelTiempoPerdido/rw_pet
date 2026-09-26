"""自主邻边路线、独立活动选择、躯干侧倾与手动接管。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from collections import Counter
from dataclasses import replace
from math import atan2, degrees
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene, dot
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.pearl import PearlState
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.shared.timing import FixedStepper


class OracleAutonomyTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(replace(OracleConfig(), **settings))
        scene.appearance.step = lambda scene: None
        return scene

    def test_probability_is_configurable_rare_and_independent_of_pearl_cycle(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/'config.toml'
            path.write_text('[oracle]\ncross_edge_probability = 0.02\n', encoding='utf-8')
            self.assertEqual(AppConfig.load(path).oracle.cross_edge_probability, .02)
        for value in (-.01, 1.01, float('nan'), True):
            with self.assertRaises(ValueError):
                OracleConfig(cross_edge_probability=value)
        scene = self.scene(antigravity_probability=0.)
        counts = Counter(scene.behavior.choose_activity(scene) for _ in range(20000))
        for activity, expected in ((Activity.CROSS_EDGE, .05), (Activity.IDLE, .266), (Activity.MEDITATE, .114),
                                   (Activity.ROAM, .3325), (Activity.NOTICE, .2375)):
            self.assertAlmostEqual(counts[activity]/20000, expected, delta=.015)
        scene.set_autonomous(True)
        with patch.object(scene.behavior, 'choose_activity', return_value=Activity.IDLE):
            for _ in range(1600):
                scene.step()
        self.assertEqual(scene.behavior.completed_cycles, 0)
        self.assertEqual(scene.behavior.state, Activity.IDLE)
        self.assertEqual(scene.eyes.openness, 0.)
        scene.behavior.cross_cooldown = 40
        with patch.object(scene.behavior.random, 'random', return_value=0.):
            self.assertEqual(scene.behavior.choose_activity(scene), Activity.IDLE)
        scene = self.scene(sliding_base=False, cross_edge_probability=1.)
        self.assertEqual(scene.behavior.choose_activity(scene), Activity.IDLE)

    def test_adjacent_routes_use_only_two_edges_for_all_corners_and_sizes(self):
        for width, height, scale, fraction in ((960, 600, .6, .5), (640, 480, .35, 0.),
                                               (640, 480, .75, 1.), (3840, 1080, .35, .5),
                                               (1080, 1920, .6, .5)):
            for side in ('top', 'right', 'bottom', 'left'):
                scene = self.scene(world_width=width, world_height=height, arm_scale=scale,
                                   base_side=side, base_fraction=fraction)
                behavior, planner = scene.behavior, scene.navigator.planner
                source = behavior.current_edge(scene)
                start = scene.body.chunks[0].position
                for destination in ((source-1) % 4, (source+1) % 4):
                    result = behavior.adjacent_route(scene, destination)
                    self.assertIsNotNone(result)
                    edge, point, route = result
                    self.assertEqual(edge, destination)
                    allowed = (planner.region.boxes[source], planner.region.boxes[destination])
                    self.assertTrue(allowed[1].contains(point))
                    self.assertFalse(allowed[0].contains(point))
                    corner = planner.corners[destination if (destination-source) % 4 == 1 else source]
                    self.assertLessEqual(route.length, (corner-start).length()+(point-corner).length()+1.)
                    for curve in route.curves:
                        for i in range(101):
                            self.assertTrue(any(box.contains(curve.sample(i/100)) for box in allowed))
                with self.assertRaises(ValueError):
                    behavior.adjacent_route(scene, (source+2) % 4)
                for _ in range(40):
                    point = behavior.short_point(scene)
                    self.assertIsNotNone(point)
                    self.assertTrue(planner.region.boxes[source].contains(point))
                    self.assertLessEqual((point-start).length(), behavior.ROAM_DISTANCE[1]+1e-6)

    def test_crossing_every_corner_arrives_continuously_and_keeps_a_cooldown(self):
        for source in range(4):
            for direction in (-1, 1):
                scene = self.scene(base_side=('top', 'right', 'bottom', 'left')[source])
                destination = (source+direction) % 4
                self.assertTrue(scene.behavior.start_roam(scene, adjacent=True, target_edge=destination))
                max_lean = 0.
                for tick in range(4000):
                    old, old_velocity = scene.body.direction, scene.body.chunks[0].velocity
                    scene.step()
                    upper, lower = scene.body.chunks
                    self.assertAlmostEqual((upper.position-lower.position).length(), 9., places=6)
                    self.assertGreater(dot(old, scene.body.direction), .998)
                    self.assertLess((upper.velocity-old_velocity).length(), .4)
                    self.assertTrue(scene.navigator.region.segment_safe(upper.previous_position, upper.position))
                    self.assertTrue(all(scene.arm_region.segment_safe(a.position, b.position)
                                        for a, b in zip(scene.arm.joints, scene.arm.joints[1:])))
                    self.assertLess(scene.arm.constraint_error, .025)
                    max_lean = max(max_lean, abs(scene.pose.angle))
                    if scene.behavior.state == Activity.IDLE:
                        break
                self.assertLess(tick, 3999)
                self.assertEqual(scene.behavior.current_edge(scene), destination)
                self.assertEqual(scene.behavior.cross_cooldown, scene.behavior.CROSS_EDGE_COOLDOWN)
                self.assertGreater(max_lean, 1.)
                for _ in range(500):
                    scene.step()
                self.assertTrue(scene.arrived)
                self.assertEqual(scene.pose.angle, 0.)
                self.assertLess(abs(degrees(atan2(scene.body.direction.x, -scene.body.direction.y))), .01)

    def test_distant_autonomous_pearl_uses_recall_instead_of_bypassing_cross_limit(self):
        for source in range(4):
            scene = self.scene(base_side=('top', 'right', 'bottom', 'left')[source], cross_edge_probability=0.)
            opposite = scene.navigator.region.boxes[(source+2) % 4]
            home = Vec2((opposite.left+opposite.right)/2, (opposite.top+opposite.bottom)/2)
            # 构造唯一的远端固定珠；旧调试单珠已移除，pearl 为只读别名。
            scene.fixed_pearls.roots = (PearlState(home, scene.world, scene.navigator.region),)
            scene.set_autonomous(True)
            scene.behavior.notice(scene, mode='approach')
            scene.behavior.duration = 1
            scene.step()
            self.assertEqual(scene.behavior.state, Activity.RECALL)
            self.assertEqual(scene.navigator.route.length, 0.)
            self.assertEqual(scene.look_target, scene.pearl.position)

    def test_observation_pose_is_slow_and_pause_cancel_and_reset_keep_it_consistent(self):
        scene = self.scene()
        scene.observe_pearl('recall')
        clock = FixedStepper(40)
        for _ in range(120):
            previous = scene.pose.angle
            scene.step()
            self.assertLessEqual(abs(scene.pose.angle-previous), scene.pose.MAX_SPEED+1e-8)
            self.assertEqual(scene.look_target, scene.pearl.position)
        self.assertGreater(abs(scene.pose.angle), 5.)
        snapshot = (scene.pose.angle, scene.pose.velocity, scene.body.chunks[0].position)
        clock.set_paused(True)
        clock.advance(4., scene.step)
        self.assertEqual(snapshot, (scene.pose.angle, scene.pose.velocity, scene.body.chunks[0].position))
        scene.set_look_target(Vec2(0, 600))
        for _ in range(650):
            scene.step()
        self.assertEqual(scene.pose.angle, 0.)
        self.assertFalse(scene.behavior.active)
        self.assertTrue(scene.arrived)
        scene.reset()
        self.assertEqual((scene.pose.angle, scene.pose.velocity), (0., 0.))
        self.assertIsNone(scene.behavior.edge)


class OracleAutonomyWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_one_shot_buttons_take_over_and_fixed_mode_disables_crossing(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            window.autonomous_box.setChecked(True)
            window.cross_edge_button.click()
            self.assertFalse(window.autonomous_box.isChecked())
            self.assertEqual(window.scene.behavior.state, Activity.CROSS_EDGE)
            window.short_roam_button.click()
            self.assertEqual(window.scene.behavior.state, Activity.ROAM)
            window.set_sliding_mode(False)
            self.assertFalse(window.cross_edge_button.isEnabled())
            window.short_roam_button.click()
            self.assertEqual(window.scene.behavior.state, Activity.ROAM)
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
