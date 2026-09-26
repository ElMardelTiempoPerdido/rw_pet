"""有时限的整身失重：活动选择、连续姿态、四边约束、接管与恢复休眠。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from collections import Counter
from math import atan2, degrees
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.scene import OracleScene, dot
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared.timing import FixedStepper


class AntigravityTests(unittest.TestCase):
    def scene(self, **settings):
        settings.setdefault('antigravity_duration_seconds', 20.)  # 短回放检查进出状态；长时段另测。
        scene = OracleScene(OracleConfig(**settings))
        scene.appearance.step = lambda scene: None
        return scene

    def test_selection_probability_cooldown_and_autonomous_entry(self):
        for value in (-.1, 1.1, float('nan'), True):
            with self.assertRaises(ValueError):
                OracleConfig(antigravity_probability=value)
        with TemporaryDirectory() as temp:
            path = Path(temp)/'config.toml'
            path.write_text('[oracle]\nantigravity_probability = 0.15\n', encoding='utf-8')
            self.assertEqual(AppConfig.load(path).oracle.antigravity_probability, .15)
        scene = self.scene()
        counts = Counter(scene.behavior.choose_activity(scene) for _ in range(20000))
        self.assertAlmostEqual(counts[Activity.DRIFT]/20000, .95*.08, delta=.01)
        self.assertAlmostEqual(counts[Activity.CROSS_EDGE]/20000, .05, delta=.01)
        with patch.object(scene.behavior.random, 'random', return_value=.07):
            self.assertEqual(scene.behavior.choose_activity(scene), Activity.DRIFT)
            scene.behavior.drift_cooldown = 40
            self.assertEqual(scene.behavior.choose_activity(scene), Activity.IDLE)
        scene = self.scene(cross_edge_probability=0., antigravity_probability=1.)
        scene.set_autonomous(True)
        for _ in range(350):
            scene.step()
            if scene.behavior.state == Activity.DRIFT:
                break
        self.assertEqual(scene.behavior.state, Activity.DRIFT)
        self.assertTrue(scene.behavior.enabled)

    def test_long_duration_config_and_full_episode_on_each_edge(self):
        self.assertEqual(OracleConfig().antigravity_duration_seconds, 300.)
        for value in (0., -1., float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                OracleConfig(antigravity_duration_seconds=value)
        with TemporaryDirectory() as temp:
            path = Path(temp)/'config.toml'
            path.write_text('[oracle]\nantigravity_duration_seconds = 600\n', encoding='utf-8')
            self.assertEqual(AppConfig.load(path).oracle.antigravity_duration_seconds, 600.)
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(base_side=side, antigravity_duration_seconds=300., cross_edge_probability=0.)
            scene.drift()
            duration = scene.behavior.drift_duration
            self.assertTrue(270*40 <= duration <= 330*40)
            targets = set()
            observed = set()
            for tick in range(duration):
                scene.step()
                targets.add(scene.target)
                observed.add(scene.behavior.state)
                self.assertTrue(scene.behavior.drift_active)
                self.assertEqual(scene.behavior.drift_ticks, tick+1)
                self.assertTrue(scene.navigator.region.boxes[scene.behavior.drift_edge].contains(scene.body.chunks[0].position))
                self.assertLess(scene.arm.constraint_error, .025)
            self.assertGreater(len(targets), 10)
            self.assertTrue({Activity.NOTICE, Activity.OBSERVE, Activity.RETURN} <= observed)
            self.assertGreater(scene.behavior.completed_cycles, 0)
            for _ in range(2400):
                scene.step()
                if scene.behavior.state == Activity.IDLE:
                    break
            self.assertEqual(scene.behavior.state, Activity.IDLE)
            self.assertTrue(scene.arrived and scene.pose.settled)
            self.assertEqual(scene.behavior.drift_cooldown, scene.behavior.DRIFT_COOLDOWN)

    def test_manual_exit_restarts_cooldown_after_long_drift(self):
        for command in ('stop', 'look'):
            scene = self.scene(antigravity_duration_seconds=300.)
            scene.drift()
            for _ in range(6000):
                scene.step()
            self.assertEqual(scene.behavior.drift_cooldown, 0)
            before = scene.pose.angle
            if command == 'stop':
                scene.stop()
            else:
                scene.set_look_target(Vec2(550, 200))
            self.assertLess(abs(scene.pose.angle-before), 1.)
            self.assertEqual(scene.behavior.drift_cooldown, scene.behavior.DRIFT_COOLDOWN)

    def test_entry_without_movement_does_not_turn_and_exit_recovers_upright(self):
        angles = []
        for sign in (-1, 1):
            scene = self.scene(antigravity_duration_seconds=300.)
            scene.drift()
            scene.behavior.drift_next_move = scene.behavior.drift_next_observation = 100000
            for _ in range(160):
                scene.step()
            self.assertAlmostEqual(scene.pose.angle, 0., places=5)
            start = scene.body.chunks[0].position
            scene._move_to(start+Vec2(sign*120, 0))
            for _ in range(300):
                scene.step()
            angles.append(scene.pose.angle)
            axis = scene.body.direction
            scene.stop()
            self.assertGreater(dot(axis, scene.body.direction), .99999)
            for _ in range(900):
                before = scene.body.direction
                scene.step()
                self.assertGreater(dot(before, scene.body.direction), .998)
            self.assertTrue(scene.arrived and scene.pose.settled)
            self.assertAlmostEqual((scene.pose.angle+180.) % 360.-180., 0., places=5)
            self.assertGreater(dot(scene.body.direction, Vec2(0, -1)), .99999)
        self.assertLess(angles[0], -5.)
        self.assertGreater(angles[1], 5.)

    def test_both_pearl_modes_keep_weightlessness_and_resume_same_episode(self):
        for mode in ('approach', 'recall'):
            scene = self.scene(antigravity_duration_seconds=300.)
            scene.drift()
            for _ in range(400):
                scene.step()
            deadline, start = scene.behavior.drift_duration, scene.behavior.drift_ticks
            axis = scene.body.direction
            scene.observe_pearl(mode)
            visited = set()
            for tick in range(2200):
                scene.step()
                visited.add(scene.behavior.state)
                self.assertTrue(scene.behavior.drift_active)
                self.assertEqual(scene.behavior.drift_duration, deadline)
                self.assertEqual(scene.behavior.drift_ticks, start+tick+1)
                self.assertLess(scene.pose.gravity_scale, .05)
                self.assertGreater(dot(axis, scene.body.direction), .998)
                axis = scene.body.direction
                if scene.behavior.looking:
                    self.assertEqual(scene.look_target, scene.observed_pearl.position)
                if scene.behavior.completed_cycles == 1:
                    break
            self.assertLess(tick, 2199)
            self.assertEqual(scene.behavior.state, Activity.DRIFT)
            self.assertIn(Activity.APPROACH if mode == 'approach' else Activity.RECALL, visited)
            self.assertIn(Activity.OBSERVE, visited)
            self.assertTrue(scene.pearl.settled)
            # 到期正在观察时，完成本轮再退出；不能突然丢下被召近的珍珠。
            scene.observe_pearl('recall')
            scene.behavior.drift_duration = scene.behavior.drift_ticks+1
            for _ in range(2400):
                scene.step()
                if not scene.behavior.drift_active:
                    break
            self.assertFalse(scene.behavior.drift_active)
            self.assertEqual(scene.behavior.completed_cycles, 2)
            self.assertTrue(scene.pearl.settled)

    def test_whole_body_turns_continuously_on_every_edge_and_returns(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for sliding in (True, False):
                scene = self.scene(base_side=side, sliding_base=sliding,
                                   cross_edge_probability=0.,
                                   world_width=640, world_height=480,
                                   base_fraction=0. if sliding else .5,
                                   arm_scale=.75 if sliding else .35)
                scene.drift()
                # 本组隔离纯移动；观察期间可能按原有小概率睁眼，另组覆盖。
                scene.behavior.drift_next_observation = 100000
                box = (scene.navigator.region if scene.navigator else scene.body_region).boxes[
                    scene.behavior.current_edge(scene)]
                start = scene.body.chunks[0].position
                max_angle = max_distance = 0.
                eye_random = scene.eyes.random.getstate()
                for tick in range(2000):
                    before = scene.body.direction
                    scene.step()
                    upper, lower = scene.body.chunks
                    self.assertAlmostEqual((upper.position-lower.position).length(), 9., places=6)
                    self.assertGreater(dot(before, scene.body.direction), .998)
                    self.assertLess(scene.arm.constraint_error, .025)
                    self.assertTrue(all(scene.arm_region.segment_safe(a.position, b.position)
                                        for a, b in zip(scene.arm.joints, scene.arm.joints[1:])))
                    self.assertTrue(box.contains(scene.target))
                    if scene.navigator:
                        self.assertTrue(all(box.contains(p) for p in scene.navigator.route.samples))
                    neck_root = upper.position+scene.body.direction*scene.head.NECK_BASE_OFFSET
                    self.assertAlmostEqual((scene.head.position-neck_root).length(), 8., places=6)
                    max_angle = max(max_angle, abs(degrees(atan2(scene.body.direction.x, -scene.body.direction.y))))
                    max_distance = max(max_distance, (upper.position-start).length())
                    if scene.behavior.state == Activity.IDLE and scene.arrived and scene.pose.settled:
                        break
                self.assertLess(tick, 1999)
                self.assertGreater(max_angle, 1.)
                self.assertGreater(max_distance, 10.)
                self.assertAlmostEqual((scene.pose.angle+180.) % 360.-180., 0., places=5)
                self.assertGreater(dot(scene.body.direction, Vec2(0, -1)), .9999)
                self.assertEqual(scene.pose.gravity_scale, 1.)
                self.assertGreater(scene.behavior.drift_cooldown, 0)
                self.assertEqual(scene.eyes.openness, 0.)
                self.assertEqual(eye_random, scene.eyes.random.getstate())

    def test_pause_manual_interrupt_and_reset(self):
        for command in ('stop', 'look', 'disable'):
            scene = self.scene()
            scene.drift()
            for _ in range(300):
                scene.step()
            old_angle, old_axis = scene.pose.angle, scene.body.direction
            self.assertGreater(abs(old_angle), 1.)
            clock = FixedStepper(40)
            clock.set_paused(True)
            snapshot = (scene.ticks, scene.behavior.state_ticks, scene.pose.weightlessness)
            clock.advance(2., scene.step)
            self.assertEqual(snapshot, (scene.ticks, scene.behavior.state_ticks, scene.pose.weightlessness))
            if command == 'stop':
                scene.stop()
            elif command == 'look':
                scene.set_look_target(Vec2(550, 200))
            else:
                scene.set_autonomous(False)
            self.assertLess(abs(scene.pose.angle-old_angle), 1.)
            scene.step()
            self.assertGreater(dot(old_axis, scene.body.direction), .998)
            for _ in range(1500):
                scene.step()
            self.assertTrue(scene.pose.settled)
            self.assertEqual(scene.pose.gravity_scale, 1.)
            self.assertFalse(scene.behavior.active)
            scene.reset()
            self.assertEqual(scene.pose.angle, 0.)
            self.assertEqual(scene.behavior.drift_cooldown, 0)

    def test_soft_parts_follow_and_return_to_sleep(self):
        scene = OracleScene()
        scene.drift()
        for _ in range(450):
            scene.step()
        app = scene.appearance
        self.assertLess(app.gravity_scale, .05)
        self.assertGreater(abs(app.direction.x), .05)
        self.assertTrue(all((p.position-scene.body.chunks[0].position).length() < 36
                            for p in [app.head, *app.hands, *app.feet, *app.cloth, *app.necklace]))
        scene.stop()
        for tick in range(1800):
            scene.step()
            if app.sleeping and scene.pose.settled and scene.arrived:
                break
        self.assertLess(tick, 1799)
        self.assertEqual(app.gravity_scale, 1.)
        positions = [p.position for p in app.points]
        revision = app.revision
        for _ in range(200):
            scene.step()
        self.assertEqual(app.revision, revision)
        self.assertEqual(positions, [p.position for p in app.points])

    def test_one_shot_debug_control(self):
        application = QApplication.instance() or QApplication([])
        application.setQuitOnLastWindowClosed(False)
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            window.autonomous_box.setChecked(True)
            window.drift_button.click()
            self.assertEqual(window.scene.behavior.state, Activity.DRIFT)
            self.assertFalse(window.autonomous_box.isChecked())
            window.stop_motion()
            self.assertEqual(window.scene.behavior.state, Activity.IDLE)
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
