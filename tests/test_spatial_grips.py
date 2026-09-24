"""墙面落脚来自固定空间候选；支撑期及停止后不因查询而换点。"""
from math import atan2, pi
from statistics import pstdev
import unittest

from rw_creature_pet.desktop import EdgeWorld
from rw_creature_pet.gait import FootPhase
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.scene import FlatWorld
from tests.test_wall_observation import placed
from tests.test_wall_rhythm import walking


class SpatialGripTests(unittest.TestCase):
    def test_points_are_world_fixed_across_queries_and_world_instances(self):
        world = FlatWorld(700, 650, 600)
        a, b = Vec2(211.3, 287.7), Vec2(219.8, 295.4)
        first = set(world.background_candidates(a, 24))
        second = set(world.background_candidates(b, 24))
        overlap = {p for p in first if (p-b).length() <= 24}
        self.assertGreater(len(overlap), 10)
        self.assertEqual(overlap, {p for p in second if (p-a).length() <= 24})
        self.assertEqual(first, set(world.background_candidates(a, 24)))
        self.assertEqual(first, set(FlatWorld(700, 650, 600).background_candidates(a, 24)))
        self.assertTrue(all((p-a).length() <= 24 for p in first))

    def test_candidates_do_not_project_into_forbidden_regions(self):
        world = EdgeWorld(700, 650, 600)
        for hip in (Vec2(3, 3), Vec2(137, 300), Vec2(563, 300), Vec2(350, 119)):
            points = list(world.background_candidates(hip, 24))
            self.assertTrue(points)
            self.assertTrue(all(world.in_edge(p) and (p-hip).length() <= 24 for p in points))
        for hip in (Vec2(-1, 3), Vec2(701, 300), Vec2(350, 300)):
            self.assertEqual(list(world.background_candidates(hip, 24)), [])

    def test_rest_has_different_leg_spreads_without_time_based_jitter(self):
        for angle in (0, pi/4, pi/2, pi):
            s = placed(angle)
            feet = [f.position for f in s.feet]
            lengths, angles = [], []
            for f in s.feet:
                hip = s.body.chunks[f.chunk_index].position
                self.assertIn(f.position, s.world.background_candidates(hip, 25))
                offset = f.position-hip
                lengths.append(offset.length())
                angles.append(abs((atan2(offset.y, offset.x)-angle+pi) % (2*pi)-pi))
            self.assertGreater(max(lengths)-min(lengths), 1)
            self.assertGreater(max(angles)-min(angles), .15)
            self.assertTrue(all((a-b).length() >= 7.5 for i, a in enumerate(feet) for b in feet[i+1:]))
            for _ in range(500): s.step()
            self.assertEqual(feet, [f.position for f in s.feet])
            self.assertTrue(all(f.phase == FootPhase.STANCE for f in s.feet))

    def test_steps_reserve_fixed_points_and_stop_keeps_the_result(self):
        s = walking(tracking=True)
        distances, angles = [], []
        for _ in range(700):
            before = [(f.phase, f.position, f.target) for f in s.feet]
            s.step()
            self.assertGreaterEqual(s.background.grip_count, 2)
            for f, (phase, position, target) in zip(s.feet, before):
                self.assertNotEqual(f.phase, FootPhase.AIR)
                if phase == f.phase == FootPhase.STANCE:
                    self.assertEqual(position, f.position)
                if phase == FootPhase.SWING:
                    self.assertEqual(target, f.target)
                    if f.phase == FootPhase.STANCE:
                        self.assertEqual(f.position, target)
                if phase == FootPhase.STANCE and f.phase == FootPhase.SWING:
                    hip = s.body.chunks[f.chunk_index].position
                    self.assertIn(f.target, s.world.background_candidates(hip, 25))
                    offset = f.target-hip
                    distances.append(offset.length())
                    angles.append(abs(atan2(offset.y, offset.x)))
                    for other in s.feet:
                        if other is f or other.phase == FootPhase.AIR: continue
                        point = other.target if other.phase == FootPhase.SWING else other.position
                        self.assertGreaterEqual((f.target-point).length(), 7.5)
        self.assertGreater(len(distances), 60)
        self.assertGreater(pstdev(distances), 1)
        self.assertGreater(pstdev(angles), .07)
        s.background.set_direction(Vec2())
        for _ in range(100): s.step()
        feet = [(f.position, f.steps) for f in s.feet]
        for _ in range(500): s.step()
        self.assertEqual(feet, [(f.position, f.steps) for f in s.feet])
