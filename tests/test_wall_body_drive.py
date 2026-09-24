"""前身引导、中后身实际跟随，以及抓点约束参与身体求解。"""
from math import pi
import unittest
from unittest.mock import patch

from rw_creature_pet.background import BackgroundGrip
from rw_creature_pet.gait import FootPhase
from rw_creature_pet.geometry import Vec2
from tests.test_body_following import bend
from tests.test_wall_observation import placed, rotate
from tests import test_wall_rhythm
from tests.test_wall_rhythm import walking


class WallBodyDriveTests(unittest.TestCase):
    def test_corner_propagates_front_to_middle_to_rear_and_unfolds(self):
        checker = test_wall_rhythm.WallRhythmTests()
        for orientation in (0, pi/4, pi/2, pi):
            s = walking(orientation, tracking=True)
            for _ in range(160): s.step()
            origin = [c.position for c in s.body.chunks]
            s.background.set_direction(rotate(Vec2(0, 1), orientation))
            first_response = [None]*3
            maximum_bend = 0
            for tick in range(160):
                checker.assert_step(s)
                maximum_bend = max(maximum_bend, abs(bend(s)))
                for i, c in enumerate(s.body.chunks):
                    displacement = rotate(c.position-origin[i], -orientation)
                    if first_response[i] is None and displacement.y > 2:
                        first_response[i] = tick
            self.assertTrue(all(t is not None for t in first_response))
            self.assertLess(first_response[0], first_response[1])
            self.assertLess(first_response[1], first_response[2])
            self.assertGreater(maximum_bend, .5)
            self.assertLess(abs(bend(s)), .03, '直行一段距离后应自然舒展')

    def test_short_move_starts_and_arrives_while_still_curved(self):
        for orientation in (0, pi/2, pi, -pi/2):
            s = placed(orientation)
            s.background.set_direction(rotate(Vec2(1, 0), orientation))
            for _ in range(90): s.step()
            s.background.set_direction(rotate(Vec2(0, 1), orientation))
            for _ in range(23): s.step()
            s.background.set_direction(Vec2())
            for _ in range(200): s.step()
            initial_bend = abs(bend(s))
            self.assertGreater(initial_bend, .5)
            start = s.body.chunks[1].position
            forward = s.body.chunks[0].position-start
            goal = start+forward*(5/forward.length())
            s.background.set_goal(goal, s.body, s.world)
            moved_while_bent = False
            for tick in range(400):
                s.step()
                moved_while_bent |= (s.body.chunks[1].position-start).length() > 1 and abs(bend(s)) > .3
                if s.background.arrived: break
            self.assertTrue(moved_while_bent)
            self.assertTrue(s.background.arrived)
            self.assertLess((s.body.chunks[1].position-goal).length(), .6)
            self.assertGreater(abs(bend(s)), .3)

    def test_unavailable_footholds_limit_body_then_walking_resumes(self):
        for orientation in (0, pi/4, pi/2, pi):
            s = walking(orientation, tracking=True)
            feet = [f.position for f in s.feet]
            start = s.body.chunks[1].position
            with patch.object(BackgroundGrip, '_find_grip', return_value=None):
                for _ in range(350):
                    s.step()
                    self.assertEqual(s.background.grip_count, 4)
                    self.assertEqual(feet, [f.position for f in s.feet])
                    self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
                    self.assertTrue(all((f.position-s.body.chunks[f.chunk_index].position).length() <= 25 for f in s.feet))
                    self.assertLessEqual((s.background.targets[1]-s.body.chunks[1].position).length(), 6.1)
                self.assertLess(max(c.velocity.length() for c in s.body.chunks), 1e-7)
                self.assertLess((s.body.chunks[1].position-start).length(), 30)
            stopped = s.body.chunks[1].position
            for _ in range(200): s.step()
            self.assertGreater((s.body.chunks[1].position-stopped).length(), 180)
            self.assertTrue(all(f.phase != FootPhase.AIR for f in s.feet))

    def test_reserved_swing_target_remains_reachable_through_turn(self):
        s = walking(tracking=True)
        checker = test_wall_rhythm.WallRhythmTests()
        for tick in range(750):
            if tick in (160, 200, 350):
                s.background.set_goal(s.body.chunks[1].position+Vec2(-80, 65), s.body, s.world)
            checker.assert_step(s)
            for foot in s.feet:
                if foot.phase == FootPhase.SWING:
                    self.assertLessEqual((foot.target-s.body.chunks[foot.chunk_index].position).length(), 25)
