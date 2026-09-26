"""漫游退出的最短方向回正、受控速度、普通运动基准和恢复期暂停。"""
from math import radians, sin, cos
import unittest

from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene, dot
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared.timing import FixedStepper


class UprightRecoveryTests(unittest.TestCase):
    def scene(self, angle, **settings):
        scene = OracleScene(OracleConfig(cross_edge_probability=0., **settings))
        scene.appearance.step = lambda scene: None
        scene.drift()
        scene.behavior.drift_next_move = scene.behavior.drift_next_observation = 100000
        # 受控姿态覆盖跨过半圈/多圈的角度；不依赖随机漂浮恰好转到该处。
        scene.pose.angle = angle
        scene.pose.weightlessness = scene.pose._weightlessness_target = 1.
        axis = Vec2(sin(radians(angle)), -cos(radians(angle)))
        upper, lower = scene.body.chunks
        lower.position = lower.previous_position = upper.position-axis*scene.body.connection_length
        for _ in range(80):
            scene.step()
        return scene

    def recover(self, scene):
        start = scene.pose.angle
        expected = (-start+180.) % 360.-180.
        traveled = 0.
        for tick in range(1100):
            angle, axis = scene.pose.angle, scene.body.direction
            scene.step()
            delta = scene.pose.angle-angle
            traveled += abs(delta)
            self.assertLessEqual(abs(delta), scene.pose.MAX_SPEED+1e-7)
            self.assertGreater(dot(axis, scene.body.direction), .998)
            self.assertLess(scene.arm.constraint_error, .025)
            upper, lower = scene.body.chunks
            self.assertAlmostEqual((upper.position-lower.position).length(), 9., places=6)
            self.assertTrue(scene.navigator.region.contains(upper.position))
            if scene.behavior.state == Activity.IDLE and scene.arrived and scene.pose.settled:
                break
        self.assertLess(tick, 1099)
        self.assertLessEqual(traveled, abs(expected)+.5)
        self.assertAlmostEqual((scene.pose.angle+180.) % 360.-180., 0., delta=1e-5)
        self.assertGreater(dot(scene.body.direction, Vec2(0, -1)), .9999)
        self.assertEqual(scene.pose.weightlessness, 0.)

    def test_natural_exit_and_manual_stop_take_shortest_path_from_large_angles(self):
        for angle in (-550., -181., -90., 90., 181., 550.):
            for manual in (False, True):
                with self.subTest(angle=angle, manual=manual):
                    scene = self.scene(angle)
                    before = scene.body.direction
                    if manual:
                        scene.stop()
                    else:
                        scene.behavior.drift_duration = scene.behavior.drift_ticks
                    self.assertEqual(scene.body.direction, before)
                    self.recover(scene)

    def test_recovery_on_all_edges_and_ordinary_roam_returns_to_upright(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(150., base_side=side, world_width=640, world_height=480,
                               arm_scale=.75, base_fraction=0.)
            scene.behavior.drift_duration = scene.behavior.drift_ticks
            self.recover(scene)
            self.assertTrue(scene.roam())
            for tick in range(1600):
                scene.step()
                self.assertLessEqual(abs((scene.pose.target+180.) % 360.-180.), 25.00001)
                if scene.behavior.state == Activity.IDLE and scene.arrived and scene.pose.settled:
                    break
            self.assertLess(tick, 1599)
            self.assertGreater(dot(scene.body.direction, Vec2(0, -1)), .9999)

    def test_pause_and_restart_during_recovery_keep_pose_continuous(self):
        scene = self.scene(120.)
        scene.behavior.drift_duration = scene.behavior.drift_ticks
        for _ in range(60):
            scene.step()
        self.assertTrue(scene.behavior.drift_recovering)
        self.assertGreater(abs(scene.pose.angle), 30.)
        clock = FixedStepper(40)
        clock.set_paused(True)
        snapshot = (scene.body.direction, scene.pose.angle, scene.pose.weightlessness, scene.behavior.drift_ticks)
        clock.advance(5., scene.step)
        self.assertEqual(snapshot, (scene.body.direction, scene.pose.angle, scene.pose.weightlessness, scene.behavior.drift_ticks))
        before = scene.body.direction
        scene.drift()
        scene.behavior.drift_next_move = scene.behavior.drift_next_observation = 100000
        self.assertFalse(scene.behavior.drift_recovering)
        scene.step()
        self.assertGreater(dot(before, scene.body.direction), .998)
        for _ in range(150):
            scene.step()
        self.assertEqual(scene.pose.weightlessness, 1.)
        self.assertGreater(abs(scene.pose.angle), 30.)
        scene.stop()
        self.recover(scene)


if __name__ == '__main__':
    unittest.main()
