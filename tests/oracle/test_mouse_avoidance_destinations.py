"""鼠标躲避的独立矩阵间距及有限次落点回退"""
import unittest
from math import atan2, degrees
from unittest.mock import patch

from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.shared.geometry import Vec2
from . import test_mouse_avoidance as ordinary


class MouseAvoidanceDestinationTests(unittest.TestCase):
    def scene(self, **options):
        options.setdefault('pearl_matrix_enabled', True)
        options.setdefault('pearl_matrix_count', 7)
        s = ordinary.MouseAvoidanceTests().scene(**options)
        s.mouse_reaction.avoidance.DISTANCE = (30., 30.)
        s.mouse_reaction.avoidance.LEAN_MOVE_DISTANCE = (30., 30.)
        return s

    def place_matrix(self, s, point):
        s.pearl_matrix.anchor.position = s.pearl_matrix.anchor.home = point

    def move(self, s, *, small=False):
        a = s.mouse_reaction.avoidance
        pointer = s.body.chunks[0].position+Vec2(30, 0)
        with patch.object(a.random, 'uniform', side_effect=lambda lo, hi: (lo+hi)*.5):
            return a.start_move(s, pointer, small=small)

    def assert_clear(self, s):
        a, matrix = s.mouse_reaction.avoidance, s.pearl_matrix
        point = s.target+a.offset
        self.assertGreaterEqual((point-matrix.anchor.position).length(), a.MATRIX_AVOID_RADIUS)
        self.assertGreaterEqual((point-matrix.home_for(point)).length(), a.MATRIX_AVOID_RADIUS)
        self.assertTrue(s.navigator.region.contains(point))

    def test_mouse_radius_is_independent_of_autonomous_radius(self):
        for radius in (0., 80., 160.):
            with self.subTest(radius=radius):
                s = self.scene(pearl_matrix_avoid_radius=radius)
                start = s.target
                self.place_matrix(s, start-Vec2(65, 0))
                self.assertTrue(self.move(s))
                self.assertEqual(s.target, start-Vec2(30, 0))
                self.assert_clear(s)
                self.assertEqual(s.behavior.matrix_clear(s, s.target), radius == 0.)
                self.assertEqual(s.config.pearl_matrix_avoid_radius, radius)

    def test_blocked_long_step_can_use_a_shorter_away_step(self):
        for small in (False, True):
            with self.subTest(small=small):
                s = self.scene()
                start = s.target
                self.place_matrix(s, start-Vec2(50, 0))
                self.assertTrue(self.move(s, small=small))
                delta = s.target-start
                self.assertGreaterEqual(delta.length(), 3. if small else 6.)
                self.assertLess(delta.length(), 30.)
                self.assertLess(delta.x, 0.)
                self.assert_clear(s)

    def test_blocked_direction_can_use_a_nearby_angle(self):
        s = self.scene()
        start = s.target
        self.place_matrix(s, start+Vec2(-28, 31))
        self.assertTrue(self.move(s))
        delta = s.target-start
        self.assertAlmostEqual(delta.length(), 30.)
        angle = abs(degrees(atan2(-delta.y, -delta.x)))
        self.assertGreater(angle, 1.)
        self.assertLessEqual(angle, s.mouse_reaction.avoidance.MOVE_ANGLE_JITTER+1e-6)
        self.assert_clear(s)

    def test_predicted_matrix_home_blocks_all_candidates_without_changing_route(self):
        s = self.scene()
        start, route = s.target, s.navigator.route
        # 当前矩阵足够远，但跟随后的位置覆盖全部短途落点
        s.pearl_matrix.anchor.position = start+Vec2(150, 0)
        s.pearl_matrix.anchor.home = start
        with patch.object(s.behavior, 'matrix_clear', wraps=s.behavior.matrix_clear) as check, \
                patch.object(s, '_move_to', wraps=s._move_to) as move:
            self.assertFalse(self.move(s))
        self.assertGreater(check.call_count, 1)
        self.assertLessEqual(check.call_count, 9)
        move.assert_not_called()
        self.assertEqual(s.target, start)
        self.assertIs(s.navigator.route, route)
        self.assertFalse(s.mouse_reaction.avoidance.moving)

    def test_other_behavior_states_still_block_before_sampling(self):
        for state in (Activity.MEDITATE, Activity.NOTICE, Activity.OBSERVE, Activity.ROAM,
                      Activity.CROSS_EDGE, Activity.DRIFT_CROSS_EDGE):
            with self.subTest(state=state):
                s = self.scene()
                s.behavior.enter(state)
                a = s.mouse_reaction.avoidance
                route, target = s.navigator.route, s.target
                with patch.object(a.random, 'uniform') as sample:
                    self.assertFalse(a.start_move(s, target+Vec2(30, 0)))
                sample.assert_not_called()
                self.assertEqual(s.behavior.state, state)
                self.assertIs(s.navigator.route, route)
                self.assertEqual(s.target, target)


if __name__ == '__main__':
    unittest.main()
