"""失重期间低概率移到邻边：四角双向、连续姿态、计时和手动接管。"""
import unittest
from unittest.mock import patch

from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.scene import OracleScene, dot
from rw_creature_pet.shared.timing import FixedStepper


class DriftCrossingTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(OracleConfig(**settings))
        scene.appearance.step = lambda scene: None
        scene.drift()
        scene.behavior.drift_next_move = scene.behavior.drift_next_observation = 100000
        for _ in range(130):
            scene.step()
        return scene

    def until(self, scene, condition, limit=5000):
        for _ in range(limit):
            scene.step()
            if condition():
                return
        self.fail(f'未完成：{scene.behavior.state} / {scene.body.chunks[0].position} / {scene.target}')

    def test_rare_selection_interval_cooldown_and_disabled_modes(self):
        scene = self.scene()
        behavior = scene.behavior
        with patch.object(behavior.detail_random, 'random', return_value=.049) as draw:
            self.assertFalse(behavior.try_drift_crossing(scene))
            draw.assert_not_called()
            behavior.drift_ticks = behavior.drift_next_cross_check
            self.assertTrue(behavior.try_drift_crossing(scene))
            self.assertEqual(draw.call_count, 1)
            behavior.finish_drift_crossing(scene)
            behavior.enter(Activity.DRIFT)
            behavior.drift_ticks += 800
            self.assertFalse(behavior.try_drift_crossing(scene))
            self.assertEqual(draw.call_count, 1)
        behavior.cross_cooldown = 0
        with patch.object(behavior.detail_random, 'random', return_value=.05) as draw:
            for _ in range(100):
                self.assertFalse(behavior.try_drift_crossing(scene))
            self.assertEqual(draw.call_count, 1, '失败后不应每帧重抽')
        for settings in ({'cross_edge_probability': 0.}, {'sliding_base': False}):
            scene = self.scene(**settings)
            scene.behavior.drift_ticks = 1000
            with patch.object(scene.behavior.detail_random, 'random') as draw:
                self.assertFalse(scene.behavior.try_drift_crossing(scene))
                draw.assert_not_called()

    def test_automatic_entry_and_no_observation_or_expiry_preemption(self):
        scene = self.scene(cross_edge_probability=1.)
        behavior = scene.behavior
        behavior.drift_ticks = behavior.drift_next_move = behavior.drift_next_cross_check
        scene.step()
        self.assertEqual(behavior.state, Activity.DRIFT_CROSS_EDGE)
        destination = behavior.destination_edge
        behavior.drift_duration = behavior.drift_ticks+1
        behavior.drift_next_observation = behavior.drift_ticks+1
        for _ in range(30):
            scene.step()
            self.assertEqual(behavior.state, Activity.DRIFT_CROSS_EDGE)
            self.assertEqual(scene.pose.weightlessness, 1.)
        self.until(scene, lambda: behavior.state != Activity.DRIFT_CROSS_EDGE)
        self.assertEqual(behavior.drift_edge, destination)
        self.assertEqual(behavior.state, Activity.DRIFT)
        self.until(scene, lambda: behavior.state == Activity.IDLE)
        self.assertFalse(behavior.drift_active)
        self.assertEqual(scene.pose.weightlessness, 0.)
        self.assertTrue(scene.arrived and scene.pose.settled)

    def test_every_corner_both_directions_preserves_episode_and_safe_body(self):
        for source, side in enumerate(('top', 'right', 'bottom', 'left')):
            for sign in (-1, 1):
                with self.subTest(side=side, sign=sign):
                    scene = self.scene(world_width=640, world_height=480, arm_scale=.75, base_side=side)
                    behavior = scene.behavior
                    destination = (source+sign) % 4
                    deadline, start = behavior.drift_duration, behavior.drift_ticks
                    self.assertTrue(behavior.start_drift_crossing(scene, destination))
                    boxes = [scene.navigator.region.boxes[i] for i in (source, destination)]
                    for curve in scene.navigator.route.curves:
                        self.assertTrue(all(any(box.contains(curve.sample(i/100)) for box in boxes)
                                            for i in range(101)))
                    for tick in range(3000):
                        old = scene.body.direction
                        scene.step()
                        upper, lower = scene.body.chunks
                        self.assertEqual(behavior.drift_ticks, start+tick+1)
                        self.assertEqual(behavior.drift_duration, deadline)
                        self.assertEqual(scene.pose.weightlessness, 1.)
                        self.assertTrue(any(box.contains(upper.position) for box in boxes))
                        self.assertTrue(scene.navigator.region.segment_safe(upper.previous_position, upper.position))
                        self.assertGreater(dot(old, scene.body.direction), .998)
                        self.assertAlmostEqual((upper.position-lower.position).length(), 9., places=6)
                        self.assertLess(scene.arm.constraint_error, .025)
                        self.assertTrue(all(scene.arm_region.segment_safe(a.position, b.position)
                                            for a, b in zip(scene.arm.joints, scene.arm.joints[1:])))
                        if behavior.state != Activity.DRIFT_CROSS_EDGE:
                            break
                    self.assertLess(tick, 2999)
                    self.assertEqual(behavior.state, Activity.DRIFT)
                    self.assertEqual(behavior.drift_edge, destination)
                    self.assertEqual(behavior.cross_cooldown, behavior.CROSS_EDGE_COOLDOWN)
                    # 回到新边后，珍珠的悬浮点和后续局部路线都使用新走廊。
                    self.assertTrue(boxes[1].contains(scene.pearl.home))
                    point = behavior.drift_point(scene, scene.body.chunks[0].position)
                    self.assertTrue(boxes[1].contains(point))
                    with self.assertRaises(ValueError):
                        behavior.start_drift_crossing(scene, (destination+2) % 4)

    def test_manual_observation_meditation_and_stop_adopt_actual_edge(self):
        for command in ('recall', 'orbit', 'meditate', 'stop'):
            scene = self.scene()
            behavior = scene.behavior
            behavior.start_drift_crossing(scene, 1)
            old_box = scene.navigator.region.boxes[0]
            self.until(scene, lambda: not old_box.contains(scene.body.chunks[0].position))
            before = scene.body.chunks[0].position
            deadline, ticks = behavior.drift_duration, behavior.drift_ticks
            if command == 'stop':
                scene.stop()
            elif command == 'meditate':
                scene.meditate()
            else:
                scene.observe_pearl(command)
            self.assertEqual(behavior.drift_edge, 1)
            self.assertEqual(behavior.drift_duration, deadline)
            self.assertEqual(behavior.drift_ticks, ticks)
            scene.step()
            self.assertLess((scene.body.chunks[0].position-before).length(), 2.)
            if command != 'stop':
                self.assertTrue(behavior.drift_active)
                self.assertEqual(scene.pose.weightlessness, 1.)
                self.until(scene, lambda: behavior.state == Activity.DRIFT)
                self.assertEqual(behavior.drift_edge, 1)
            else:
                self.assertFalse(behavior.drift_active)
                self.until(scene, lambda: scene.arrived and scene.pose.settled)

    def test_large_workareas_short_arm_and_slow_base_reach_neighbor(self):
        for width, height, side, destination, speed in (
                (3840, 1080, 'top', 3, 1.8), (1080, 1920, 'right', 2, .3)):
            with self.subTest(size=(width, height), speed=speed):
                scene = self.scene(world_width=width, world_height=height, base_side=side,
                                   arm_scale=.35, base_speed=1.5, drift_speed=speed,
                                   antigravity_duration_seconds=600.)
                behavior = scene.behavior
                behavior.start_drift_crossing(scene, destination)
                for tick in range(6500):
                    scene.step()
                    upper = scene.body.chunks[0]
                    self.assertLessEqual((upper.position-scene.base).length(), scene.arm.maximum_reach+1e-6)
                    self.assertTrue(scene.navigator.region.segment_safe(upper.previous_position, upper.position))
                    self.assertLess(scene.arm.constraint_error, .025)
                    if behavior.state != Activity.DRIFT_CROSS_EDGE:
                        break
                self.assertLess(tick, 6499)
                self.assertEqual(behavior.drift_edge, destination)
                self.assertEqual(scene.pose.weightlessness, 1.)

    def test_pause_timeout_and_workarea_rebuild(self):
        scene = self.scene()
        behavior = scene.behavior
        behavior.start_drift_crossing(scene, 1)
        clock = FixedStepper(40)
        clock.set_paused(True)
        before = (behavior.drift_ticks, behavior.state_ticks, scene.body.chunks[0].position)
        clock.advance(5., scene.step)
        self.assertEqual(before, (behavior.drift_ticks, behavior.state_ticks, scene.body.chunks[0].position))
        behavior.enabled = True
        resized = OracleDesktopMotion(OracleConfig(), OracleDesktopViewport(0, 0, 1280, 680, 1.), scene).scene
        self.assertTrue(resized.behavior.enabled)
        self.assertFalse(resized.behavior.drift_active)
        self.assertTrue(resized.navigator.region.contains(resized.target))
        behavior.duration = 0
        scene.step()
        self.assertEqual(behavior.state, Activity.DRIFT)
        self.assertEqual(behavior.drift_edge, 0)
        self.assertTrue(scene.navigator.region.boxes[0].contains(scene.target))


if __name__ == '__main__':
    unittest.main()
